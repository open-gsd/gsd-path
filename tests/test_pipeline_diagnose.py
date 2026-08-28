import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import pipeline_diagnose


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def state_text(
    *,
    phase: str = "plan",
    status: str = "done",
    branch: str = "gsd-path/M001",
    milestone: str = "first",
) -> str:
    return (
        "---\n"
        "pipeline: gsd-path/v2\n"
        "project: demo\n"
        f"milestone: {milestone}\n"
        f"phase: {phase}\n"
        f"status: {status}\n"
        f"branch: {branch}\n"
        "archive: null\n"
        "---\n\n"
        "# Project State\n\n"
        "## Log\n\n"
        "- 2026-08-28 — fixture\n"
    )


class PipelineDiagnoseTests(unittest.TestCase):
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

            result = pipeline_diagnose.diagnose(repo)
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
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture")
            run_git(repo, "checkout", "-b", "other")

            result = pipeline_diagnose.diagnose(repo)
            self.assertEqual(result["status"], "stuck")
            ids = {item["id"] for item in result["findings"]}
            self.assertTrue({"branch-mismatch", "route-block"} & ids)

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

            result = pipeline_diagnose.diagnose(repo)
            findings = [item for item in result["findings"] if item["id"].startswith("journal-")]
            self.assertEqual(len(findings), 1)
            self.assertIn("--archive .project/archive/001-first", findings[0]["retry"])
            self.assertIn(event, findings[0]["retry"])
            self.assertNotIn("<", findings[0]["retry"])

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
            self.assertIn("orphan", {item["id"] for item in result["findings"]})

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
