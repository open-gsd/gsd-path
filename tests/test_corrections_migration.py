"""The migrate-corrections renumbering: pure transform, gate acceptance, upgrade preflight (#551)."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import _common, build_recovery, install

PROJECT_ROOT = Path(__file__).resolve().parents[1]

LEGACY_INTENT = (
    "# Intent — demo\n\n"
    "Surfaces: none\n\n"
    "## Success criteria\n\n"
    "1. The demo command prints hello.\n\n"
    "## Corrections\n\n"
    "- 2026-10-19: \"History scope (recommended)\"\n"
    "- 2026-10-20: \"Drop the wizard\"\n\n"
    "## Log\n\n"
    "- 2026-10-18 — define — intent approved\n"
)


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(("git", "-C", str(root), *arguments),
                            capture_output=True, encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stderr
    return result.stdout


class MigrateCorrectionsTests(unittest.TestCase):
    def test_migrate_numbers_legacy_entries_in_file_order(self) -> None:
        migrated = _common.migrate_corrections(LEGACY_INTENT)
        self.assertIn('- C1 2026-10-19: "History scope (recommended)"', migrated)
        self.assertIn('- C2 2026-10-20: "Drop the wizard"', migrated)
        stripped = migrated.replace("- C1 2026-10-19:", "- 2026-10-19:").replace(
            "- C2 2026-10-20:", "- 2026-10-20:")
        self.assertEqual(stripped, LEGACY_INTENT)

    def test_migrate_is_idempotent_and_a_native_file_is_a_noop(self) -> None:
        once = _common.migrate_corrections(LEGACY_INTENT)
        self.assertEqual(_common.migrate_corrections(once), once)
        self.assertEqual(_common.migrate_corrections(once + "tail"), once + "tail")

    def test_migrate_numbers_mixed_files_into_the_running_sequence(self) -> None:
        mixed = "## Corrections\n\n- C1 2026-10-19: first\n- 2026-10-20: second\n"
        self.assertEqual(
            _common.migrate_corrections(mixed),
            "## Corrections\n\n- C1 2026-10-19: first\n- C2 2026-10-20: second\n",
        )

    def test_migrate_leaves_none_and_log_lines_untouched(self) -> None:
        text = (
            "## Corrections\n\n- none\n\n"
            "## Log\n\n- 2026-10-18 — define — read `- 2026-10-19: not a correction`\n"
        )
        self.assertEqual(_common.migrate_corrections(text), text)

    def test_migrate_recognizes_the_heading_and_indent_the_gate_accepts(self) -> None:
        # The Corrections gate strips entry lines and tolerates heading
        # trailing spaces; the migrator must recognize the same forms, keep
        # entry trailing spaces, and ignore an indented pseudo-heading the
        # gate's flush-left section parser never sees.
        text = (
            " ## Corrections\n\n- 2026-10-19: before the real section\n\n"
            "## Corrections  \n\n  - 2026-10-20: indented legacy  \n\n## Log\n\n- x\n"
        )
        migrated = _common.migrate_corrections(text)
        self.assertIn("  - C1 2026-10-20: indented legacy  \n", migrated)
        self.assertIn("- 2026-10-19: before the real section\n", migrated)
        self.assertNotIn("- C1 2026-10-19", migrated)

    def test_intent_unchanged_accepts_byte_equal_and_migrated_only(self) -> None:
        migrated = _common.migrate_corrections(LEGACY_INTENT)
        self.assertTrue(_common.intent_unchanged(LEGACY_INTENT, LEGACY_INTENT))
        self.assertTrue(_common.intent_unchanged(LEGACY_INTENT, migrated))
        self.assertFalse(_common.intent_unchanged(LEGACY_INTENT, migrated + "extra"))
        # The check re-runs the migration; stripping ids out is not accepted.
        self.assertFalse(_common.intent_unchanged(migrated, LEGACY_INTENT))

    def test_migrate_corrections_records_parses_the_state_log(self) -> None:
        base, content = "a" * 40, "b" * 64
        state = (
            "---\nphase: build\nstatus: active\n---\n\n## Log\n\n"
            f"- 2026-11-01T10:00:00+00:00 — build — migrate-corrections: "
            f'{{"base": "{base}", "current": "{content}"}}\n'
            "- 2026-11-01T11:00:00+00:00 — build — build started\n"
            "- 2026-11-01T12:00:00+00:00 — build — migrate-corrections: not json\n"
        )
        self.assertEqual(_common.migrate_corrections_records(state), [(base, content)])
        self.assertEqual(_common.migrate_corrections_records("---\n---\n"), [])


class RecoveryAcceptsMigrationTests(unittest.TestCase):
    def make_repo(self) -> tuple:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name) / "repo"
        (repo / ".project/intent").mkdir(parents=True)
        (repo / ".project/plan").mkdir(parents=True)
        (repo / ".project/tasks").mkdir(parents=True)
        (repo / ".project/tasks/T001-demo.md").write_text(
            "---\nid: T001\ntitle: Demo task T001\nwave: 1\ndeps: []\nstatus: done\n"
            "agent: coder\nbase: null\nworktree: null\ntask_branch: null\n"
            "files:\n  - src/app.py\n---\ntask T001\n",
            encoding="utf-8",
        )
        (repo / ".project/STATE.md").write_text(
            "---\nphase: build\nstatus: active\n---\n\n## Log\n\n- 2026-10-18 — build — build started\n",
            encoding="utf-8",
        )
        (repo / ".project/intent/INTENT.md").write_text(LEGACY_INTENT, encoding="utf-8")
        (repo / ".project/plan/PLAN.md").write_text(
            "# Plan — demo\n\n## Config\n\n- max_review_cycles: 3\n\n"
            "## Wave 1 — demo\n\n| Task | Title | Deps | Files |\n|------|-------|------|-------|\n",
            encoding="utf-8",
        )
        git(repo, "init", "-q", "-b", "gsd-path/M001")
        git(repo, "config", "user.name", "Test")
        git(repo, "config", "user.email", "test@example.test")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "base")
        return repo, git(repo, "rev-parse", "HEAD").strip()

    def test_renumbering_alone_is_not_a_stale_intent(self) -> None:
        repo, base = self.make_repo()
        (repo / ".project/intent/INTENT.md").write_text(
            _common.migrate_corrections(LEGACY_INTENT), encoding="utf-8")
        recovery = {"base": base}
        self.assertEqual(build_recovery.stale_review_reasons(repo, recovery, {1}), {})

    def test_any_other_intent_change_is_still_stale(self) -> None:
        repo, base = self.make_repo()
        (repo / ".project/intent/INTENT.md").write_text(
            _common.migrate_corrections(LEGACY_INTENT) + "extra", encoding="utf-8")
        recovery = {"base": base}
        self.assertEqual(
            build_recovery.stale_review_reasons(repo, recovery, {1}),
            {1: "INTENT.md changed"},
        )

    def test_a_recorded_migration_cannot_author_other_changes(self) -> None:
        repo, base = self.make_repo()
        import hashlib
        forged = _common.migrate_corrections(LEGACY_INTENT) + "extra"
        digest = hashlib.sha256(forged.encode("utf-8")).hexdigest()
        (repo / ".project/intent/INTENT.md").write_text(forged, encoding="utf-8")
        (repo / ".project/STATE.md").write_text(
            "---\nphase: build\nstatus: active\n---\n\n## Log\n\n"
            f"- 2026-11-01T10:00:00+00:00 — build — migrate-corrections: "
            f'{{"base": "{base}", "current": "{digest}"}}\n',
            encoding="utf-8",
        )
        recovery = {"base": base}
        self.assertEqual(
            build_recovery.stale_review_reasons(repo, recovery, {1}),
            {1: "INTENT.md changed"},
        )


class UpgradePreflightTests(unittest.TestCase):
    def make_project(self, intent: str) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "repo"
        (project / ".project/intent").mkdir(parents=True)
        (project / ".project/STATE.md").write_text(
            "---\nphase: build\nstatus: active\n---\n\n## Log\n\n- 2026-10-18 — build — build started\n",
            encoding="utf-8",
        )
        (project / ".project/intent/INTENT.md").write_text(intent, encoding="utf-8")
        return project

    def test_preflight_warns_and_names_the_migrator_for_legacy_corrections(self) -> None:
        project = self.make_project(LEGACY_INTENT)
        warnings = install.runtime_upgrade_preflight(PROJECT_ROOT, project)
        self.assertTrue(any("intent" in warning for warning in warnings), warnings)
        self.assertTrue(any("migrate-corrections" in warning for warning in warnings), warnings)

    def test_preflight_is_quiet_for_a_native_intent(self) -> None:
        project = self.make_project(_common.migrate_corrections(LEGACY_INTENT))
        self.assertEqual(install.runtime_upgrade_preflight(PROJECT_ROOT, project), [])

    def test_preflight_is_quiet_without_an_open_milestone(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "repo"
        project.mkdir()
        self.assertEqual(install.runtime_upgrade_preflight(PROJECT_ROOT, project), [])


if __name__ == "__main__":
    unittest.main()
