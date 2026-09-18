import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import state_checkpoint
from scripts import (
    archive_milestone,
    integration,
    pipeline_diagnose,
    pipeline_git,
    pipeline_state,
    pipeline_undo,
)

from tests import test_archive_milestone as archive_tests
from tests.test_pipeline_undo import write_plan_tasks
from tests.test_task_briefs import PLAN_WAVE


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def diagnose_installed(repo: Path) -> dict[str, object]:
    script = (
        PROJECT_ROOT
        / "skills"
        / "gsd-path-forensics"
        / "scripts"
        / "pipeline_diagnose.py"
    )
    completed = subprocess.run(
        [sys.executable, str(script), "diagnose", "--repo", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def state_text(
    *,
    phase: str = "plan",
    status: str = "done",
    branch: str = "gsd-path/M001",
    milestone: str = "first",
    archive: str = "null",
) -> str:
    return (
        "---\n"
        "pipeline: gsd-path/v2\n"
        "project: demo\n"
        f"milestone: {milestone}\n"
        f"phase: {phase}\n"
        f"status: {status}\n"
        f"branch: {branch}\n"
        f"archive: {archive}\n"
        "---\n\n"
        "# Project State\n\n"
        "## Log\n\n"
        "- 2026-08-28 — fixture\n"
    )


class PipelineDiagnoseTests(unittest.TestCase):
    def test_shipped_diagnosis_reports_missing_proof_without_refreshing_refs(self) -> None:
        fixture = archive_tests.ArchiveMilestoneTests()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            fixture.make_publishable_bound_repo(repo, root / "origin.git")
            archive, _ = fixture.ship_canonical_bound(repo)
            integrated = fixture.integrate(repo)
            self.assertEqual(integrated.returncode, 0, integrated.stderr)
            run_git(repo, "update-ref", "-d", f"refs/remotes/origin/tags/milestone/{archive}")
            refs = run_git(repo, "show-ref").stdout
            head = run_git(repo, "rev-parse", "HEAD").stdout
            state = (repo / ".project/STATE.md").read_bytes()

            for diagnose in (pipeline_diagnose.diagnose, diagnose_installed):
                with self.subTest(entrypoint=diagnose.__name__):
                    result = diagnose(repo)

                    self.assertEqual(run_git(repo, "show-ref").stdout, refs)
                    self.assertEqual(run_git(repo, "rev-parse", "HEAD").stdout, head)
                    self.assertEqual((repo / ".project/STATE.md").read_bytes(), state)
                    findings = [item for item in result["findings"] if item["id"] == "integration"]
                    self.assertEqual(len(findings), 1)
                    self.assertIn("missing published milestone tag", findings[0]["evidence"])
                    self.assertEqual(findings[0]["retry"], "$gsd-path-ship")

    def test_promotion_retry_preserves_base_and_landing(self) -> None:
        base = "a" * 40
        landing = "b" * 40
        retry = pipeline_diagnose._route_retry(
            Path("/tmp/repo with spaces"),
            {
                "action": "resume-promotion",
                "milestone": "second",
                "branch": "gsd-path/M002",
                "integrate": landing,
                "landing": landing,
                "base": base,
            },
            None,
        )

        self.assertIsNotNone(retry)
        arguments = pipeline_state.parse_args(shlex.split(retry)[2:])
        self.assertEqual(arguments.base, base)
        self.assertEqual(arguments.landing, landing)
        self.assertIsNone(arguments.integrate)

    def test_handoff_retry_preserves_missing_remote_permission(self) -> None:
        route = {
            "action": "resume-next-handoff",
            "branch": "gsd-path/M002",
            "previous_branch": "gsd-path/M001",
            "ship": "a" * 40,
            "remote_default": "origin/main",
            "base": "b" * 40,
            "landing": "c" * 40,
        }
        for allowed in (False, True):
            with self.subTest(allowed=allowed):
                retry = pipeline_diagnose._route_retry(
                    Path("/tmp/repo with spaces"),
                    {**route, "allow_remote_absent": allowed},
                    None,
                )

                self.assertIsNotNone(retry)
                arguments = pipeline_git.parse_args(shlex.split(retry)[2:])
                self.assertEqual(arguments.allow_missing_previous, allowed)
                self.assertEqual(arguments.landing, "c" * 40)

    def test_healthy_bound_plan_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            run_git(Path(tmp), "init", "-b", "gsd-path/M001", str(repo))
            run_git(repo, "config", "user.name", "GSD Path Test")
            run_git(repo, "config", "user.email", "test@example.com")
            project = repo / ".project"
            (project / "intent").mkdir(parents=True)
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")
            (project / "intent" / "INTENT.md").write_text(
                "# Intent — first\n\nLane: quick\n",
                encoding="utf-8",
            )
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: plan done")

            result = diagnose_installed(repo)
            self.assertEqual(result["status"], "ok")
            self.assertFalse(
                any(item["severity"] == "stuck" for item in result["findings"])
            )

    def test_branch_mismatch_is_stuck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            run_git(Path(tmp), "init", "-b", "gsd-path/M001", str(repo))
            run_git(repo, "config", "user.name", "GSD Path Test")
            run_git(repo, "config", "user.email", "test@example.com")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture")
            run_git(repo, "checkout", "-b", "other")

            result = diagnose_installed(repo)
            self.assertEqual(result["status"], "stuck")
            ids = {item["id"] for item in result["findings"]}
            self.assertTrue({"branch-mismatch", "route-block"} & ids)
            self.assertTrue(
                all("<" not in item["retry"] for item in result["findings"])
            )
            first_stuck = next(
                item for item in result["findings"] if item["severity"] == "stuck"
            )
            self.assertTrue(first_stuck["retry"].startswith("NEEDS-USER:"))

    def test_blocked_undo_transaction_does_not_emit_apply_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            run_git(Path(tmp), "init", "-b", "gsd-path/M001", str(repo))
            run_git(repo, "config", "user.name", "GSD Path Test")
            run_git(repo, "config", "user.email", "test@example.com")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(phase="plan", status="active"),
                encoding="utf-8",
            )
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: approval base")
            parent = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            (project / "plan").mkdir()
            (project / "plan" / "PLAN.md").write_text(
                PLAN_WAVE.format(title="first"),
                encoding="utf-8",
            )
            write_plan_tasks(repo)
            state_checkpoint.checkpoint_approval(repo, "plan", parent)
            approved = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            with mock.patch.object(
                pipeline_undo,
                "_reset_to",
                side_effect=pipeline_undo.UndoError("interrupted"),
            ):
                with self.assertRaisesRegex(pipeline_undo.UndoError, "interrupted"):
                    pipeline_undo.apply_undo(repo, "checkpoint", approved)
            run_git(repo, "switch", "-c", "other")

            result = pipeline_diagnose.diagnose(repo)

            finding = next(
                item
                for item in result["findings"]
                if item["id"] == "journal-resume-undo"
            )
            self.assertTrue(finding["retry"].startswith("NEEDS-USER:"))
            self.assertNotIn("pipeline_undo.py apply", finding["retry"])

    def test_pending_discussion_disposition_is_stuck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            run_git(Path(tmp), "init", "-b", "gsd-path/M001", str(repo))
            run_git(repo, "config", "user.name", "GSD Path Test")
            run_git(repo, "config", "user.email", "test@example.com")
            project = repo / ".project"
            discussion = project / "discuss"
            discussion.mkdir(parents=True)
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")
            (project / "intent").mkdir()
            (project / "intent" / "INTENT.md").write_text(
                "# Intent — first\n\nLane: quick\n", encoding="utf-8"
            )
            (discussion / "DIALOGUE.md").write_text(
                "# GSD Path Discussion — Dialogue\n\n## Turns\n\n"
                "### D001 — 2026-08-28 — plan/done — Review\n\n"
                "- **Thread**: T001\n- **Reply to**: none\n- **Type**: question\n"
                "- **Status**: open\n\nQuestion\n",
                encoding="utf-8",
            )
            (discussion / "ANSWERS.md").write_text(
                "# GSD Path Discussion — Answers\n\n"
                "## Answer A001 — 2026-08-28 — Review\n\n"
                "- **Thread**: T001\n- **Turn**: D001\n- **Supersedes**: none\n"
                "- **Status**: final\n- **Phase/status**: plan/done\n"
                "- **Confidence**: high\n- **Follow-up**: required\n"
                "- **Next owner**: planner\n- **Target artifact**: .project/plan/PLAN.md\n\n"
                "Conclusion\n\nReasoning\n",
                encoding="utf-8",
            )
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: pending discussion")

            result = pipeline_diagnose.diagnose(repo)
            pending = next(
                (
                    item
                    for item in result["findings"]
                    if item["id"] == "pending-answers"
                ),
                None,
            )
            self.assertIsNotNone(pending, result)
            assert pending is not None
            self.assertEqual(result["status"], "stuck")
            self.assertIn(".project/plan/PLAN.md", pending["evidence"])
            self.assertTrue(pending["retry"].startswith("NEEDS-USER:"))

    def test_shipment_journal_retry_uses_validated_route_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            run_git(Path(tmp), "init", "-b", "gsd-path/M001", str(repo))
            run_git(repo, "config", "user.name", "GSD Path Test")
            run_git(repo, "config", "user.email", "test@example.com")
            project = repo / ".project"
            project.mkdir()
            state = state_text(phase="ship", status="active")
            (project / "STATE.md").write_text(state, encoding="utf-8")
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: shipment")
            journal = Path(
                run_git(repo, "rev-parse", "--git-path", "gsd-path-shipment.json").stdout.strip()
            )
            if not journal.is_absolute():
                journal = repo / journal
            event = "archive preflight passed; shipment recorded"
            journal.write_text(
                json.dumps(
                    {
                        "schema": "gsd-path/shipment/v1",
                        "repo": str(repo.resolve()),
                        "archive": ".project/archive/001-first",
                        "event": event,
                        "roadmap_before": None,
                        "roadmap_after": None,
                        "state_before": state,
                        "state_after": state,
                    }
                ),
                encoding="utf-8",
            )

            result = diagnose_installed(repo)
            findings = [
                item
                for item in result["findings"]
                if item["id"].startswith("journal-")
            ]
            self.assertEqual(len(findings), 1)
            self.assertIn("--archive .project/archive/001-first", findings[0]["retry"])
            self.assertIn(event, findings[0]["retry"])
            self.assertNotIn("<", findings[0]["retry"])
            retry = shlex.split(findings[0]["retry"])
            self.assertTrue(Path(retry[1]).is_file())

    def test_incomplete_artifact_collection_has_exact_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            run_git(Path(tmp), "init", "-b", "gsd-path/M001", str(repo))
            run_git(repo, "config", "user.name", "GSD Path Test")
            run_git(repo, "config", "user.email", "test@example.com")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(phase="build", status="active"), encoding="utf-8"
            )
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: collect")
            head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            common = Path(run_git(repo, "rev-parse", "--git-common-dir").stdout.strip())
            if not common.is_absolute():
                common = repo / common
            journal = common / "gsd-path" / "collect-artifact" / "pending.json"
            journal.parent.mkdir(parents=True)
            journal.write_text(
                json.dumps(
                    {
                        "schema": "gsd-path/collect-artifact/v1",
                        "primary_worktree": str(repo.resolve()),
                        "source_worktree": str(repo.resolve()),
                        "base": head,
                        "branch": "gsd-path-verify/demo",
                        "source": "artifact.md",
                        "destination": ".project/review/artifact.md",
                        "expected_destination": "base",
                        "bytes": 4,
                        "previous_sha256": None,
                        "replaced": False,
                        "sha256": "b" * 64,
                        "stage": "prepared",
                    }
                ),
                encoding="utf-8",
            )

            result = pipeline_diagnose.diagnose(repo)
            finding = next(
                item for item in result["findings"] if item["id"] == "collect-artifact"
            )
            retry = shlex.split(finding["retry"])
            self.assertEqual(result["status"], "stuck")
            self.assertEqual(Path(retry[1]).name, "isolation.py")
            self.assertIn("--expected-destination", retry)
            self.assertNotIn("<", finding["retry"])

    def test_orphan_project_is_unowned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            run_git(Path(tmp), "init", "-b", "main", str(repo))
            run_git(repo, "config", "user.name", "GSD Path Test")
            run_git(repo, "config", "user.email", "test@example.com")
            intent = repo / ".project" / "intent"
            intent.mkdir(parents=True)
            (intent / "INTENT.md").write_text("# leftover\n", encoding="utf-8")
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: orphan")

            result = pipeline_diagnose.diagnose(repo)
            self.assertEqual(result["status"], "unowned")
            orphan = next(item for item in result["findings"] if item["id"] == "orphan")
            self.assertTrue(orphan["retry"].startswith("NEEDS-USER:"))

    def test_missing_project_names_the_initialize_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            run_git(Path(tmp), "init", "-b", "main", str(repo))
            (repo / "README.md").write_text("# app\n", encoding="utf-8")

            result = pipeline_diagnose.diagnose(repo)
            self.assertEqual(result["status"], "stuck")
            finding = next(item for item in result["findings"] if item["id"] == "no-project")
            self.assertIn("detect_project.py initialize", finding["retry"])
            self.assertIn("--template", finding["retry"])
            self.assertIn("state.md", finding["retry"])
            self.assertNotIn("NEEDS-USER", finding["retry"])
            self.assertFalse(any(item["id"] == "status" for item in result["findings"]))

    def test_leftover_worktrees_have_supported_recovery_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            run_git(root, "init", "-b", "gsd-path/M001", str(repo))
            run_git(repo, "config", "user.name", "GSD Path Test")
            run_git(repo, "config", "user.email", "test@example.com")
            project = repo / ".project"
            (project / "archive" / "001-first").mkdir(parents=True)
            (project / "STATE.md").write_text(
                state_text(
                    phase="shipped",
                    status="done",
                    archive=".project/archive/001-first/",
                ),
                encoding="utf-8",
            )
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: worktrees")
            verify = root / "verify"
            dirty = root / "dirty"
            integrate = integration.integration_names(repo, "001-first")[1]
            run_git(
                repo,
                "worktree",
                "add",
                "-b",
                "gsd-path-verify/demo",
                str(verify),
                "HEAD",
            )
            run_git(
                repo,
                "worktree",
                "add",
                "-b",
                "gsd-path-task/T001",
                str(dirty),
                "HEAD",
            )
            (dirty / "rejected.txt").write_text("keep\n", encoding="utf-8")
            run_git(
                repo,
                "worktree",
                "add",
                "-b",
                "gsd-path-integrate/M001",
                str(integrate),
                "HEAD",
            )

            result = pipeline_diagnose.diagnose(repo)
            findings = [
                item for item in result["findings"] if item["id"] == "leftover-worktrees"
            ]
            retries = [shlex.split(item["retry"]) for item in findings]

            retire = next(parts for parts in retries if "retire" in parts)
            self.assertEqual(retire[retire.index("--branch") + 1], "gsd-path-verify/demo")
            dirty_finding = next(
                item
                for item in findings
                if item["evidence"].startswith("gsd-path-task/T001 @")
            )
            self.assertTrue(dirty_finding["retry"].startswith("NEEDS-USER:"))
            integration_retry = next(parts for parts in retries if "integrate" in parts)
            self.assertEqual(Path(integration_retry[1]).name, "archive_milestone.py")
            self.assertEqual(integration_retry[integration_retry.index("--slug") + 1], "first")

            run_git(repo, "worktree", "remove", str(integrate))
            run_git(repo, "branch", "-D", "gsd-path-integrate/M001")
            noncanonical = root / "integrate"
            run_git(
                repo,
                "worktree",
                "add",
                "-b",
                "gsd-path-integrate/M001",
                str(noncanonical),
                "HEAD",
            )

            blocked = pipeline_diagnose.diagnose(repo)
            blocked_finding = next(
                item
                for item in blocked["findings"]
                if item["evidence"].startswith("gsd-path-integrate/M001 @")
            )
            self.assertTrue(blocked_finding["retry"].startswith("NEEDS-USER:"))

    def test_helper_loaders_surface_internal_import_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "archive_milestone.py").write_text(
                "import missing_helper_dependency\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(directory)
            for name in (
                "pipeline_undo.py",
                "pipeline_diagnose.py",
                "discussion_records.py",
            ):
                with self.subTest(helper=name):
                    target = directory / name
                    shutil.copy2(PROJECT_ROOT / "scripts" / name, target)
                    completed = subprocess.run(
                        [sys.executable, str(target), "--help"],
                        cwd=PROJECT_ROOT,
                        env=environment,
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("missing_helper_dependency", completed.stderr)

    def test_cli_diagnose_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            run_git(Path(tmp), "init", "-b", "gsd-path/M001", str(repo))
            run_git(repo, "config", "user.name", "GSD Path Test")
            run_git(repo, "config", "user.email", "test@example.com")
            project = repo / ".project"
            (project / "intent").mkdir(parents=True)
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")
            (project / "intent" / "INTENT.md").write_text(
                "# Intent — first\n\nLane: quick\n",
                encoding="utf-8",
            )
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: plan done")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(
                        Path(__file__).resolve().parents[1]
                        / "scripts"
                        / "pipeline_diagnose.py"
                    ),
                    "diagnose",
                    "--repo",
                    str(repo),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["schema"], pipeline_diagnose.DIAGNOSE_SCHEMA)
            self.assertEqual(payload["status"], "ok")


if __name__ == "__main__":
    unittest.main()
