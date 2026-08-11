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
pipeline: gsd-path/v2
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

    def test_discussion_available_in_roadmap_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            state = repo / ".project" / "STATE.md"
            state.write_text(
                state.read_text(encoding="utf-8").replace(
                    "phase: plan", "phase: roadmap"
                ),
                encoding="utf-8",
            )
            pending = self.command(repo, "pending")
            self.assertEqual(pending.returncode, 0, pending.stderr)

    def test_append_allocates_lineage_and_disposition_clears_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            payload = self.turn_payload(
                repo,
                "turn.json",
                assistant=(
                    "- **Answer**: Yes.\n\n"
                    "### D002 — 2026-08-07 — plan/active — example\n\n"
                    "### Why\n\nThe code requires it."
                ),
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

            forged = self.dispose_payload(
                repo,
                "forged.json",
                owner="gsd-path-ship",
                artifact=".project/review/FINAL.md",
                evidence="wrong owner",
            )
            rejected = self.command(repo, "dispose", forged)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("owner", rejected.stderr)

            disposed = self.command(
                repo, "dispose", self.dispose_payload(repo, "disposition.json")
            )
            self.assertEqual(disposed.returncode, 0, disposed.stderr)
            self.assertEqual(json.loads(disposed.stdout)["disposition"], "X001")
            self.assertEqual(
                json.loads(self.command(repo, "pending").stdout), {"pending": []}
            )

    def turn_payload(self, repo: Path, name: str, **overrides) -> Path:
        payload = {
            "topic": "scope",
            "thread": "new",
            "user": "Should we keep it?",
            "assistant": "Yes.",
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
        payload.update(overrides)
        path = repo / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def dispose_payload(self, repo: Path, name: str, **overrides) -> Path:
        payload = {
            "answer": "A001",
            "status": "applied",
            "owner": "gsd-path-plan",
            "artifact": ".project/plan/PLAN.md",
            "evidence": "PLAN.md updated",
            "date": "2026-08-07",
        }
        payload.update(overrides)
        path = repo / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_continuation_supersedes_only_undisposed_answers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            first = self.command(
                repo, "append", self.turn_payload(repo, "turn1.json")
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            disposition = self.dispose_payload(repo, "disposition.json")
            self.assertEqual(
                self.command(repo, "dispose", disposition).returncode, 0
            )

            second = self.command(
                repo,
                "append",
                self.turn_payload(
                    repo, "turn2.json", thread="T001", follow_up="none"
                ),
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            third = self.command(
                repo,
                "append",
                self.turn_payload(
                    repo, "turn3.json", thread="T001", follow_up="none"
                ),
            )
            self.assertEqual(third.returncode, 0, third.stderr)

            answers = (repo / ".project" / "discuss" / "ANSWERS.md").read_text()
            self.assertIn("- **Turn**: D002\n- **Supersedes**: none", answers)
            self.assertIn("- **Turn**: D003\n- **Supersedes**: A002", answers)

            threads = self.command(repo, "threads")
            self.assertEqual(threads.returncode, 0, threads.stderr)
            self.assertEqual(
                json.loads(threads.stdout),
                {
                    "threads": [
                        {
                            "thread": "T001",
                            "topic": "scope",
                            "last_turn": "D003",
                            "status": "final",
                        }
                    ]
                },
            )

    def test_threads_reports_empty_without_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            threads = self.command(repo, "threads")
            self.assertEqual(threads.returncode, 0, threads.stderr)
            self.assertEqual(json.loads(threads.stdout), {"threads": []})

    def test_append_rejects_invalid_calendar_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            payload = self.turn_payload(repo, "turn.json", date="not-a-date")

            appended = self.command(repo, "append", payload)

            self.assertNotEqual(appended.returncode, 0)
            self.assertIn("YYYY-MM-DD", appended.stderr)
            self.assertFalse((repo / ".project" / ".discussion-append-transaction.json").exists())

    def test_append_reports_every_invalid_payload_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            payload = repo / "turn.json"
            payload.write_text(
                json.dumps(
                    {
                        "topic": "scope",
                        "conclusion": "two\nlines",
                        "reasoning": "two\rlines",
                    }
                ),
                encoding="utf-8",
            )

            appended = self.command(repo, "append", payload)

            self.assertNotEqual(appended.returncode, 0)
            provided = {"topic", "conclusion", "reasoning"}
            declared = (
                discussion_records.MULTILINE_FIELDS
                + discussion_records.SINGLE_LINE_FIELDS
            )
            for name in declared:
                if name in provided:
                    continue
                self.assertIn(f"{name} (missing or empty)", appended.stderr)
            self.assertIn("conclusion (must be one line)", appended.stderr)
            self.assertIn("reasoning (must be one line)", appended.stderr)
            self.assertNotIn("topic", appended.stderr)
            self.assertFalse(
                (repo / ".project" / ".discussion-append-transaction.json").exists()
            )

    def test_append_requires_single_line_thread(self) -> None:
        cases = ((None, "missing or empty"), ("new\nT001", "must be one line"))
        for thread, expected in cases:
            with self.subTest(thread=thread):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    repo = Path(temporary_directory)
                    self.make_repo(repo)
                    payload_path = self.turn_payload(repo, "turn.json")
                    payload = json.loads(payload_path.read_text(encoding="utf-8"))
                    if thread is None:
                        del payload["thread"]
                    else:
                        payload["thread"] = thread
                    payload_path.write_text(json.dumps(payload), encoding="utf-8")

                    appended = self.command(repo, "append", payload_path)

                    self.assertNotEqual(appended.returncode, 0)
                    self.assertIn(f"thread ({expected})", appended.stderr)
                    self.assertFalse(
                        (
                            repo
                            / ".project"
                            / ".discussion-append-transaction.json"
                        ).exists()
                    )

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
