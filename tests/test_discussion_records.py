import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import discussion_records


SCRIPT = ROOT / "scripts" / "discussion_records.py"
DIALOGUE_TEMPLATE = ROOT / "skills" / "gsd-path" / "templates" / "dialogue.md"
ANSWERS_TEMPLATE = ROOT / "skills" / "gsd-path" / "templates" / "answers.md"


class DiscussionRecordTests(unittest.TestCase):
    def command(
        self, repo: Path, command: str, input_path: Optional[Path] = None
    ):
        arguments = [
            sys.executable,
            str(SCRIPT),
            command,
            "--repo",
            str(repo),
        ]
        if command in {"prepare", "append"}:
            arguments.extend(
                [
                    "--dialogue-template",
                    str(DIALOGUE_TEMPLATE.resolve()),
                    "--answers-template",
                    str(ANSWERS_TEMPLATE.resolve()),
                ]
            )
        if input_path is not None:
            arguments.extend(("--input", str(input_path)))
        return subprocess.run(arguments, text=True, capture_output=True, check=False)

    def make_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        project = root / ".project"
        project.mkdir()
        (project / "STATE.md").write_text(
            """---
pipeline: gsd-path/v1
project: demo
milestone: demo
phase: plan
status: active
branch: main
archive: null
---
""",
            encoding="utf-8",
        )

    def test_append_allocates_lineage_and_disposition_clears_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            payload = repo / "turn.json"
            payload.write_text(
                json.dumps(
                    {
                        "topic": "scope",
                        "thread": "new",
                        "user": "Should we keep it?",
                        "assistant": (
                            "- **Answer**: Yes.\n\n"
                            "### D002 — 2026-08-07 — plan/active — example\n\n"
                            "### Why\n\nThe code requires it."
                        ),
                        "evidence": "src/example.py:10",
                        "research": "not needed — local code settles it",
                        "thread_status": "final",
                        "question": "Should we keep it?",
                        "status": "final",
                        "conclusion": "Keep it.",
                        "reasoning": "The caller requires it.",
                        "confidence": "high",
                        "unresolved": "none",
                        "next_owner": "gsd-path-plan",
                        "target_artifact": ".project/plan/PLAN.md",
                        "follow_up": "required",
                        "date": "2026-08-07",
                    }
                ),
                encoding="utf-8",
            )

            appended = self.command(repo, "append", payload)
            self.assertEqual(appended.returncode, 0, appended.stderr)
            self.assertEqual(
                json.loads(appended.stdout),
                {"answer": "A001", "dialogue": "D001", "thread": "T001"},
            )
            pending = self.command(repo, "pending")
            self.assertEqual(pending.returncode, 0, pending.stderr)
            self.assertEqual(json.loads(pending.stdout)["pending"][0]["answer"], "A001")
            self.assertIn(
                "### Why",
                (repo / ".project" / "discuss" / "DIALOGUE.md").read_text(),
            )

            forged = repo / "forged.json"
            forged.write_text(
                json.dumps(
                    {
                        "answer": "A001",
                        "status": "applied",
                        "owner": "gsd-path-review",
                        "artifact": ".project/review/FINAL.md",
                        "evidence": "wrong owner",
                        "date": "2026-08-07",
                    }
                ),
                encoding="utf-8",
            )
            rejected = self.command(repo, "dispose", forged)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("owner", rejected.stderr)

            disposition = repo / "disposition.json"
            disposition.write_text(
                json.dumps(
                    {
                        "answer": "A001",
                        "status": "applied",
                        "owner": "gsd-path-plan",
                        "artifact": ".project/plan/PLAN.md",
                        "evidence": "PLAN.md updated",
                        "date": "2026-08-07",
                    }
                ),
                encoding="utf-8",
            )
            disposed = self.command(repo, "dispose", disposition)
            self.assertEqual(disposed.returncode, 0, disposed.stderr)
            self.assertEqual(json.loads(disposed.stdout)["disposition"], "X001")
            self.assertEqual(
                json.loads(self.command(repo, "pending").stdout), {"pending": []}
            )

    def test_append_rejects_invalid_calendar_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            payload = repo / "turn.json"
            payload.write_text(
                json.dumps(
                    {
                        "topic": "date",
                        "user": "Question",
                        "assistant": "Answer",
                        "evidence": "none",
                        "research": "not needed — no external fact",
                        "thread_status": "final",
                        "question": "Question",
                        "status": "final",
                        "conclusion": "Answer",
                        "reasoning": "Evidence",
                        "confidence": "high",
                        "unresolved": "none",
                        "next_owner": "none",
                        "target_artifact": "none",
                        "follow_up": "none",
                        "date": "not-a-date",
                    }
                ),
                encoding="utf-8",
            )

            appended = self.command(repo, "append", payload)

            self.assertNotEqual(appended.returncode, 0)
            self.assertIn("YYYY-MM-DD", appended.stderr)
            self.assertFalse((repo / ".project" / ".discussion-append-transaction.json").exists())

    def test_append_recovery_rejects_symlinked_discussion_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            prepared = self.command(repo, "prepare")
            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            discussion = repo / ".project" / "discuss"
            files = {
                name: (discussion / name).read_text()
                for name in discussion_records.FILES
            }
            shutil.rmtree(discussion)
            outside = repo / "outside-discuss"
            outside.mkdir()
            for name in discussion_records.FILES:
                (outside / name).write_text(f"sentinel {name}\n")
            discussion.symlink_to(outside, target_is_directory=True)
            transaction = repo / ".project" / discussion_records.APPEND_TRANSACTION
            transaction.write_text(
                json.dumps(
                    {"schema": "gsd-path/discussion-append/v1", "files": files}
                )
                + "\n"
            )
            before = {
                name: (outside / name).read_bytes()
                for name in discussion_records.FILES
            }

            with self.assertRaises(discussion_records.DiscussionError):
                discussion_records.finish_append(repo / ".project", discussion)

            self.assertEqual(
                {
                    name: (outside / name).read_bytes()
                    for name in discussion_records.FILES
                },
                before,
            )


if __name__ == "__main__":
    unittest.main()
