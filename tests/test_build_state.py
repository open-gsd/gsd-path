from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import _common, build_state, isolation

# Git for Windows bash, never the System32 WSL launcher CreateProcess finds first.
BASH = _common.find_bash()


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_state.py"
BRANCH = "gsd-path/M001"


def run_git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(repo), *arguments),
        encoding="utf-8", errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def task_text(
    task_id: str,
    title: str,
    wave: int,
    deps: tuple[str, ...],
    files: tuple[str, ...],
    *,
    status: str = "pending",
    agent: str | None = None,
    base: str | None = None,
    worktree: str | None = None,
    task_branch: str | None = None,
    log: tuple[str, ...] = ("created",),
) -> str:
    scalar = lambda value: value if value is not None else "null"
    deps_value = ", ".join(deps)
    files_value = ", ".join(files)
    log_lines = "\n".join(f"- {item}" for item in log)
    return f"""---
id: {task_id}
title: {title}
wave: {wave}
deps: [{deps_value}]
status: {status}
agent: {scalar(agent)}
base: {scalar(base)}
worktree: {scalar(worktree)}
task_branch: {scalar(task_branch)}
files: [{files_value}]
---

# {task_id} — {title}

## Log

{log_lines}
"""


def plan_text(
    rows_by_wave: tuple[
        tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...], ...
    ],
) -> str:
    blocks = ["# Plan — test"]
    for wave, rows in enumerate(rows_by_wave, start=1):
        blocks.extend(
            (
                f"## Wave {wave} — test",
                "",
                f"Goal: exercise {len(rows)} canonical task files",
            )
        )
        blocks.append("")
    return "\n".join(blocks)


class BuildStateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.email", "test@example.com")
        run_git(self.repo, "config", "user.name", "Test User")
        run_git(self.repo, "switch", "-q", "-c", BRANCH)
        (self.repo / ".project" / "plan").mkdir(parents=True)
        (self.repo / ".project" / "tasks").mkdir()
        (self.repo / ".project" / "STATE.md").write_bytes(
            f"""---
pipeline: gsd-path/v2
project: test
milestone: test
phase: build
status: active
branch: {BRANCH}
archive: null
---
""".encode("utf-8"),
        )

    def write_plan(
        self,
        rows_by_wave: tuple[
            tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...], ...
        ],
    ) -> None:
        (self.repo / ".project" / "plan" / "PLAN.md").write_bytes(
            plan_text(rows_by_wave).encode("utf-8")
        )

    def write_task(self, task_id: str, content: str, slug: str = "task") -> None:
        (self.repo / ".project" / "tasks" / f"{task_id}-{slug}.md").write_bytes(
            content.encode("utf-8")
        )

    def commit_all(self, subject: str) -> str:
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-q", "-m", subject)
        return run_git(self.repo, "rev-parse", "HEAD")

    def cli(self, *arguments: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            (sys.executable, str(SCRIPT), *arguments, "--repo", str(self.repo)),
            encoding="utf-8", errors="replace",
            capture_output=True,
            check=False,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            self.fail(
                f"CLI did not return JSON: {result.stdout!r}; "
                f"stderr={result.stderr!r}; {error}"
            )
        return result, payload

    def test_ready_reads_canonical_task_files_without_plan_rows(self) -> None:
        self.write_plan(
            (
                (("T001", "First", (), ("one.py",)),),
                (("T002", "Later", (), ("two.py",)),),
            )
        )
        self.write_task("T001", task_text("T001", "First", 1, (), ("one.py",)))
        self.write_task("T002", task_text("T002", "Later", 2, (), ("two.py",)))
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["current_wave"], 1)
        self.assertEqual([task["id"] for task in payload["ready"]], ["T001"])

    def test_ready_rejects_a_lookahead_project_directory(self) -> None:
        self.write_plan(((("T001", "Next", (), ("next.py",)),),))
        self.write_task("T001", task_text("T001", "Next", 1, (), ("next.py",)))
        next_root = self.repo / ".project" / "next"
        next_root.mkdir()
        (self.repo / ".project" / "STATE.md").rename(next_root / "STATE.md")
        (self.repo / ".project" / "plan").rename(next_root / "plan")
        (self.repo / ".project" / "tasks").rename(next_root / "tasks")
        self.commit_all("lookahead plan")

        result, payload = self.cli("ready", "--project-dir", ".project/next")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-project-dir")
        self.assertIn("lookahead", payload["error"]["message"])

    def test_ready_uses_complete_pipeline_state_validation(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        self.write_task("T001", task_text("T001", "One", 1, (), ("one.py",)))
        state_path = self.repo / ".project" / "STATE.md"
        state_path.write_bytes(
            state_path.read_text(encoding="utf-8").replace("archive: null\n", "").encode("utf-8"),
        )
        self.commit_all("invalid state")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-state")
        self.assertIn("missing fields: archive", payload["error"]["message"])

    def test_ready_honors_same_wave_dependency_order(self) -> None:
        rows = (
            (
                ("T001", "Foundation", (), ("one.py",)),
                ("T002", "Consumer", ("T001",), ("two.py",)),
            ),
        )
        self.write_plan(rows)
        self.write_task("T001", task_text("T001", "Foundation", 1, (), ("one.py",)))
        self.write_task(
            "T002", task_text("T002", "Consumer", 1, ("T001",), ("two.py",))
        )
        base = self.commit_all("plan")

        _, before = self.cli("ready")
        self.assertEqual([task["id"] for task in before["ready"]], ["T001"])

        task_path = self.repo / ".project" / "tasks" / "T001-task.md"
        self.write_task(
            "T001",
            task_text(
                "T001",
                "Foundation",
                1,
                (),
                ("one.py",),
                status="in-progress",
                agent="builder",
                base=base,
                worktree=str(self.repo),
            ),
        )
        task_path.write_bytes(
            (task_path.read_text(encoding="utf-8") + "- implementation complete\n").encode("utf-8"),
        )
        (self.repo / "one.py").write_bytes("done = True\n".encode("utf-8"))
        isolation.land(
            self.repo,
            self.repo,
            base,
            "T001",
            "Foundation",
            ".project/tasks/T001-task.md",
            ["one.py"],
        )
        result, after = self.cli("ready")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([task["id"] for task in after["ready"]], ["T002"])

    def test_ready_rejects_done_task_without_a_proven_landing(self) -> None:
        rows = (
            (
                ("T001", "Foundation", (), ("one.py",)),
                ("T002", "Consumer", ("T001",), ("two.py",)),
            ),
        )
        self.write_plan(rows)
        self.write_task("T001", task_text("T001", "Foundation", 1, (), ("one.py",)))
        self.write_task(
            "T002", task_text("T002", "Consumer", 1, ("T001",), ("two.py",))
        )
        base = self.commit_all("plan")
        self.write_task(
            "T001",
            task_text(
                "T001",
                "Foundation",
                1,
                (),
                ("one.py",),
                status="done",
                agent="builder",
                base=base,
            ),
        )

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-task-state")
        self.assertIn("retry land", payload["error"]["message"])

    def test_ready_blocks_the_wave_until_failed_or_blocked_tasks_recover(self) -> None:
        self.write_plan(
            (
                (
                    ("T001", "Blocked", (), ("one.py",)),
                    ("T002", "Independent", (), ("two.py",)),
                ),
            )
        )
        self.write_task(
            "T001", task_text("T001", "Blocked", 1, (), ("one.py",))
        )
        self.write_task(
            "T002", task_text("T002", "Independent", 1, (), ("two.py",))
        )
        base = self.commit_all("plan")
        self.write_task(
            "T001",
            task_text(
                "T001",
                "Blocked",
                1,
                (),
                ("one.py",),
                status="blocked",
                agent="builder",
                base=base,
                worktree=str(self.repo),
            ),
        )
        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "task-recovery-required")
        self.assertEqual(payload["error"]["details"]["wave"], 1)
        self.assertEqual(
            payload["error"]["details"]["tasks"],
            [{"id": "T001", "status": "blocked"}],
        )

    def test_ready_validates_failed_or_blocked_task_ownership(self) -> None:
        self.write_plan(((('T001', 'Failed', (), ('one.py',)),),))
        self.write_task(
            "T001",
            task_text("T001", "Failed", 1, (), ("one.py",), status="failed"),
        )
        self.commit_all("invalid failed task")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-task-state")
        self.assertIn("missing agent, base, or worktree", payload["error"]["message"])

    def test_ready_rejects_done_task_with_incomplete_dependency(self) -> None:
        rows = (
            (
                ("T001", "Foundation", (), ("one.py",)),
                ("T002", "Consumer", ("T001",), ("two.py",)),
            ),
        )
        self.write_plan(rows)
        self.write_task("T001", task_text("T001", "Foundation", 1, (), ("one.py",)))
        self.write_task(
            "T002", task_text("T002", "Consumer", 1, ("T001",), ("two.py",))
        )
        base = self.commit_all("plan")
        self.write_task(
            "T002",
            task_text(
                "T002",
                "Consumer",
                1,
                ("T001",),
                ("two.py",),
                status="done",
                agent="builder",
                base=base,
            ),
        )

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-task-state")
        self.assertIn("done task has an incomplete dependency", payload["error"]["message"])

    def test_ready_reports_dependency_cycle(self) -> None:
        self.write_plan(
            (
                (
                    ("T001", "One", ("T002",), ("one.py",)),
                    ("T002", "Two", ("T001",), ("two.py",)),
                ),
            )
        )
        self.write_task("T001", task_text("T001", "One", 1, ("T002",), ("one.py",)))
        self.write_task("T002", task_text("T002", "Two", 1, ("T001",), ("two.py",)))
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "dependency-cycle")
        self.assertEqual(payload["error"]["details"]["cycle"], ["T001", "T002", "T001"])

    def test_ready_reports_a_missing_dependency(self) -> None:
        self.write_plan(((("T001", "One", ("T999",), ("one.py",)),),))
        self.write_task("T001", task_text("T001", "One", 1, ("T999",), ("one.py",)))
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "missing-dependency")
        self.assertEqual(payload["error"]["details"]["dependency"], "T999")

    def test_ready_rejects_incomplete_active_metadata(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        self.write_task(
            "T001", task_text("T001", "One", 1, (), ("one.py",), status="in-progress")
        )
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-task-state")

    def test_ready_rejects_overlapping_candidates(self) -> None:
        self.write_plan(
            (
                (
                    ("T001", "One", (), ("shared.py",)),
                    ("T002", "Two", (), ("shared.py",)),
                ),
            )
        )
        self.write_task("T001", task_text("T001", "One", 1, (), ("shared.py",)))
        self.write_task("T002", task_text("T002", "Two", 1, (), ("shared.py",)))
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "ready-file-overlap")
        self.assertEqual(payload["error"]["details"]["tasks"], ["T001", "T002"])

    def test_ready_rejects_a_noncanonical_task_filename(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        (self.repo / ".project" / "tasks" / "T001.md").write_bytes(
            task_text("T001", "One", 1, (), ("one.py",)).encode("utf-8")
        )
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-task-file")

    def test_ready_rejects_a_stray_entry_beside_a_canonical_task(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        self.write_task("T001", task_text("T001", "One", 1, (), ("one.py",)))
        (self.repo / ".project" / "tasks" / "notes.md").write_bytes(
            "post-review notes\n".encode("utf-8")
        )
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-task-file")
        self.assertIn("notes.md", payload["error"]["message"])

    def test_ready_skips_an_ignored_ds_store_beside_canonical_tasks(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        self.write_task("T001", task_text("T001", "One", 1, (), ("one.py",)))
        self.commit_all("plan")
        (self.repo / ".git" / "info" / "exclude").write_bytes(".DS_Store\n".encode("utf-8"))
        (self.repo / ".project" / "tasks" / ".DS_Store").write_bytes("finder\n".encode("utf-8"))

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 0, payload)

    def test_ready_rejects_duplicate_task_ids(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        content = task_text("T001", "One", 1, (), ("one.py",))
        self.write_task("T001", content, "first")
        self.write_task("T001", content, "second")
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "duplicate-task-file")

    def prepare_in_progress_task(self) -> tuple[str, str]:
        self.write_plan(((("T001", "Implement feature", (), ("app.py",)),),))
        (self.repo / "app.py").write_bytes("value = 0\n".encode("utf-8"))
        self.write_task(
            "T001", task_text("T001", "Implement feature", 1, (), ("app.py",))
        )
        base = self.commit_all("plan")
        self.write_task(
            "T001",
            task_text(
                "T001",
                "Implement feature",
                1,
                (),
                ("app.py",),
                status="in-progress",
                agent="builder",
                base=base,
                worktree=str(self.repo),
            ),
        )
        return base, ".project/tasks/T001-task.md"

    def land_task(self, task_file: str, sequence: int) -> str:
        (self.repo / "app.py").write_bytes(f"value = {sequence}\n".encode("utf-8"))
        current = (self.repo / task_file).read_text(encoding="utf-8")
        (self.repo / task_file).write_bytes(
            (current + f"- implementation {sequence}\n").encode("utf-8")
        )
        fields = dict(
            line.split(": ", 1)
            for line in current.split("---", 2)[1].strip().splitlines()
            if ": " in line
        )
        base = fields["base"]
        result = isolation.land(
            self.repo,
            self.repo,
            base,
            "T001",
            "Implement feature",
            task_file,
            ["app.py"],
        )
        return str(result["commit"])

    def test_reconcile_proves_one_canonical_landed_commit(self) -> None:
        base, task_file = self.prepare_in_progress_task()
        landed = self.land_task(task_file, 1)
        before = run_git(self.repo, "status", "--porcelain=v1", "--untracked-files=all")

        result, payload = self.cli("reconcile", "--task-id", "T001")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            run_git(self.repo, "status", "--porcelain=v1", "--untracked-files=all"), before
        )
        self.assertEqual(payload["classification"], "proven-landed")
        self.assertEqual(payload["landed_commit"], landed)
        self.assertEqual(len(payload["history"]["candidates"]), 1)
        self.assertTrue(payload["history"]["candidates"][0]["valid"])

    def test_reconcile_proves_done_commit_from_isolation_history(self) -> None:
        _, task_file = self.prepare_in_progress_task()
        landed = self.land_task(task_file, 1)

        result, payload = self.cli("reconcile", "--task-id", "T001")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["classification"], "proven-landed")
        self.assertEqual(payload["landed_commit"], landed)

    def test_reconcile_rejects_rewritten_ancestral_dispatch_base(self) -> None:
        (self.repo / "seed.txt").write_bytes("seed\n".encode("utf-8"))
        earlier = self.commit_all("seed")
        base, task_file = self.prepare_in_progress_task()
        landed = self.land_task(task_file, 1)
        path = self.repo / task_file
        path.write_bytes(
            path.read_text(encoding="utf-8")
            .replace(f"base: {base}", f"base: {earlier}").encode("utf-8"),
        )

        result, payload = self.cli("reconcile", "--task-id", "T001")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["classification"], "blocked")
        self.assertIn("no landing commit", payload["reasons"][0])

    def test_verify_landed_uses_canonical_paths_for_archived_tasks(self) -> None:
        _, task_file = self.prepare_in_progress_task()
        landed = self.land_task(task_file, 1)
        archive = self.repo / ".project" / "archive" / "001-test"
        archive.mkdir(parents=True)
        (self.repo / ".project" / "plan").rename(archive / "plan")
        (self.repo / ".project" / "tasks").rename(archive / "tasks")

        result, payload = self.cli(
            "verify-landed",
            "--project-dir",
            ".project/archive/001-test",
            "--head",
            landed,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["head"], landed)
        self.assertEqual(len(payload["tasks"]), 1)
        self.assertEqual(payload["tasks"][0]["classification"], "proven-landed")
        self.assertEqual(
            payload["tasks"][0]["task"]["task_file"],
            ".project/tasks/T001-task.md",
        )

    def attest_task_outside_land(self) -> tuple[str, str]:
        base, task_file = self.prepare_in_progress_task()
        (self.repo / "app.py").write_bytes("value = 1\n".encode("utf-8"))
        self.write_task(
            "T001",
            task_text(
                "T001", "Implement feature", 1, (), ("app.py",),
                status="done", agent="builder", base=base, log=("created", "done by hand"),
            )
            + "\n## Verify\n\n```bash\npython3 -c 'print(1)'\n```\n",
        )
        head = self.commit_all("feat: direct commit outside land")
        isolation_error = isolation.IsolationError
        with self.assertRaises(isolation_error):
            isolation.attest(self.repo, task_file, "ruling")  # no verify evidence yet
        result, _ = self.cli("verify-record", "--command", "python3 -c 'print(1)'", "--commit", head, "--result", "pass")
        self.assertEqual(result.returncode, 0, result.stderr)
        attested = isolation.attest(self.repo, task_file, "owner ruling")
        return attested["commit"], task_file

    def test_reconcile_and_verify_landed_report_attested_tasks(self) -> None:
        commit, task_file = self.attest_task_outside_land()

        result, payload = self.cli("reconcile", "--task-id", "T001")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["classification"], "attested")
        self.assertEqual(payload["landed_commit"], commit)

        result, payload = self.cli("verify-landed", "--project-dir", ".project", "--head", commit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["tasks"][0]["classification"], "attested")
        self.assertEqual(payload["tasks"][0]["landed_commit"], commit)

        result, payload = self.cli("ready")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reconcile_marks_unlanded_owned_work_resumable(self) -> None:
        self.prepare_in_progress_task()

        result, payload = self.cli("reconcile", "--task-id", "T001")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["classification"], "resumable")
        self.assertEqual(payload["history"]["candidates"], [])

    def test_reconcile_blocks_in_progress_without_a_recorded_base(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        self.write_task(
            "T001",
            task_text(
                "T001",
                "One",
                1,
                (),
                ("one.py",),
                status="in-progress",
                agent="builder",
                worktree=str(self.repo),
            ),
        )
        self.commit_all("invalid dispatch")

        result, payload = self.cli("reconcile", "--task-id", "T001")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["classification"], "blocked")
        self.assertIn("invalid base", payload["reasons"][0])

    def test_ready_reports_the_verify_heavy_marker(self) -> None:
        self.write_plan(
            (
                (
                    ("T001", "Heavy", (), ("one.py",)),
                    ("T002", "Light", (), ("two.py",)),
                ),
            )
        )
        heavy = task_text("T001", "Heavy", 1, (), ("one.py",))
        heavy += "\n## Verify\n\n```bash\npytest one.py\n```\nHeavy: yes\n"
        self.write_task("T001", heavy)
        self.write_task("T002", task_text("T002", "Light", 1, (), ("two.py",)))
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            {task["id"]: task["verify_heavy"] for task in payload["ready"]},
            {"T001": True, "T002": False},
        )

    def write_verify_task(self, task_id: str, wave: int, files: tuple[str, ...], command: str, *,
                          status: str = "done", repo: str = "", deps: tuple[str, ...] = ()) -> None:
        text = task_text(task_id, f"Task {task_id}", wave, deps, files, status=status)
        text = text.replace("\n## Log", f"\n## Verify\n\n```bash\n{command}\n```\n\n## Log")
        self.write_task(task_id, text.replace("files: [", f"repo: {repo}\nfiles: [") if repo else text)

    def test_regression_verifies_names_done_earlier_wave_tasks_that_share_a_file(self) -> None:
        self.write_verify_task("T001", 1, ("shared.py",), "check one")
        self.write_verify_task("T002", 1, ("other.py",), "check other")  # no shared file
        self.write_verify_task("T003", 2, ("shared.py", "more.py"), "check one")  # the same command as T001
        self.write_verify_task("T004", 3, ("shared.py",), "check pending", status="pending")
        self.write_verify_task("T005", 3, ("shared.py",), "check member", repo="api")  # another repository
        self.write_verify_task("T006", 3, ("shared.py",), "check three")
        self.write_verify_task("T007", 4, ("shared.py", "new.py"), "check own", status="in-progress")
        self.write_verify_task("T008", 4, ("shared.py",), "check same wave")
        self.write_verify_task("T009", 5, ("shared.py",), "check later wave")
        self.write_verify_task("T010", 4, ("shared.py",), "check own member", status="in-progress", repo="api")

        self.assertEqual(
            build_state.regression_verifies(self.repo, "T007", "check own"),
            [
                {"tasks": ["T001", "T003"], "command": "check one"},
                {"tasks": ["T006"], "command": "check three"},
            ],
        )
        # The own Verify already runs an identical command.
        self.assertEqual(
            build_state.regression_verifies(self.repo, "T007", "check one"),
            [{"tasks": ["T006"], "command": "check three"}],
        )
        # Text that holds a command does not prove that it runs or that its failure counts.
        for own in ("set -e\n(\ncheck one\n) || true\n(\ncheck three\n)",
                    "set -e\n(\ncheck one\n)\n(\ncheck three\n)"):  # T007 has no deps: not a fix task
            self.assertEqual(
                [item["command"] for item in build_state.regression_verifies(self.repo, "T007", own)],
                ["check one", "check three"],
                own,
            )
        # A member task overlaps only tasks of its own repository.
        self.assertEqual(
            build_state.regression_verifies(self.repo, "T010", "check own member"),
            [{"tasks": ["T005"], "command": "check member"}],
        )

    def test_regression_verifies_skips_only_the_sources_of_an_exact_fix_task_verify(self) -> None:
        self.write_verify_task("T001", 1, ("shared.py",), "check one")
        self.write_verify_task("T002", 1, ("shared.py",), "check two")
        self.write_verify_task("T003", 1, ("shared.py",), "check three")
        self.write_verify_task("T004", 2, ("shared.py",), "unused", status="in-progress", deps=("T001", "T002"))
        generated = _common.fix_verify(["check one", "check two"])  # what fix-tasks writes for deps T001, T002

        def reruns(own: str) -> list:
            return [item["command"] for item in build_state.regression_verifies(self.repo, "T004", own)]

        self.assertEqual(reruns(generated), ["check three"])
        # Any other shape runs every earlier command again.
        for own in (generated + " || true", generated + "\ntrue", generated.replace("set -e\n", ""),
                    _common.fix_verify(["check one"]), _common.fix_verify(["check one", "check three"])):
            self.assertEqual(reruns(own), ["check one", "check two", "check three"], own)

    def test_ready_marks_a_task_heavy_when_its_landing_reruns_a_heavy_verify(self) -> None:
        self.write_plan(
            (
                (("T001", "Heavy", (), ("one.py",)),),
                (
                    ("T002", "Edits the heavy file", (), ("one.py",)),
                    ("T003", "Unrelated", (), ("two.py",)),
                ),
            )
        )
        def with_verify(text: str, heavy: str) -> str:
            return text.replace("\n## Log", f"\n## Verify\n\n```bash\ntest -f one.py\n```\nHeavy: {heavy}\n\n## Log")

        self.write_task("T001", with_verify(task_text("T001", "Heavy", 1, (), ("one.py",)), "yes"))
        self.write_task(
            "T002", with_verify(task_text("T002", "Edits the heavy file", 2, (), ("one.py",)), "no")
        )
        self.write_task("T003", task_text("T003", "Unrelated", 2, (), ("two.py",)))
        base = self.commit_all("plan")
        active = task_text("T001", "Heavy", 1, (), ("one.py",), status="in-progress", agent="builder",
                           base=base, worktree=str(self.repo), log=("created", "implementation complete"))
        self.write_task("T001", with_verify(active, "yes"))
        (self.repo / "one.py").write_bytes("done = True\n".encode("utf-8"))
        isolation.land(self.repo, self.repo, base, "T001", "Heavy", ".project/tasks/T001-task.md", ["one.py"])

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 0, payload)
        self.assertEqual(
            {task["id"]: task["verify_heavy"] for task in payload["ready"]},
            {"T002": True, "T003": False},
        )

    def shared_source_plan(self, *wave_two: tuple) -> None:
        """Wave 1 is landed: T001 owns one.py and two.py, T002 owns three.py. Wave 2 is pending."""
        wave_one = (("T001", "Source", (), ("one.py", "two.py")), ("T002", "Other source", (), ("three.py",)))
        self.write_plan((wave_one, wave_two))
        for wave, rows in ((1, wave_one), (2, wave_two)):
            for task_id, title, deps, files in rows:
                self.write_task(task_id, task_text(task_id, title, wave, deps, files))
        self.commit_all("plan")
        for task_id, title, _, files in wave_one:
            self.land_serial(task_id, title, 1, (), files)

    def land_serial(self, task_id: str, title: str, wave: int, deps: tuple, files: tuple) -> None:
        base = run_git(self.repo, "rev-parse", "HEAD")
        self.write_task(task_id, task_text(task_id, title, wave, deps, files, status="in-progress",
                                           agent="builder", base=base, worktree=str(self.repo),
                                           log=("created", "implementation complete")))
        (self.repo / files[0]).write_bytes(f"owner = '{task_id}'\n".encode("utf-8"))
        isolation.land(self.repo, self.repo, base, task_id, title, f".project/tasks/{task_id}-task.md", list(files))

    def ready_ids(self) -> list:
        result, payload = self.cli("ready")
        self.assertEqual(result.returncode, 0, payload)
        return [task["id"] for task in payload["ready"]]

    def test_ready_returns_one_of_the_tasks_that_share_a_regression_source(self) -> None:
        # T003 and T004 have no file in common, and each one shares a file with T001.
        self.shared_source_plan(
            ("T003", "Edits one", (), ("one.py",)),
            ("T004", "Edits two", (), ("two.py",)),
            ("T005", "Unrelated", (), ("four.py",)),
        )

        self.assertEqual(self.ready_ids(), ["T003", "T005"])
        self.land_serial("T003", "Edits one", 2, (), ("one.py",))
        # T004 starts from a base that has T003, so its rerun of T001's Verify sees both edits.
        self.assertEqual(self.ready_ids(), ["T004", "T005"])
        self.land_serial("T004", "Edits two", 2, (), ("two.py",))
        self.land_serial("T005", "Unrelated", 2, (), ("four.py",))
        _, payload = self.cli("ready")
        self.assertIsNone(payload["current_wave"], payload)  # the wave finished one task at a time

    def test_ready_returns_together_tasks_that_share_different_regression_sources(self) -> None:
        self.shared_source_plan(
            ("T003", "Edits one", (), ("one.py",)),
            ("T004", "Edits three", (), ("three.py",)),
        )

        self.assertEqual(self.ready_ids(), ["T003", "T004"])

    def test_ready_holds_a_task_while_a_dispatched_task_shares_its_regression_source(self) -> None:
        # T003 becomes ready after T004 was dispatched: T003 has the lower id but T004 goes first.
        self.shared_source_plan(
            ("T003", "Edits one", ("T005",), ("one.py",)),
            ("T004", "Edits two", (), ("two.py",)),
            ("T005", "Unrelated", (), ("four.py",)),
        )
        self.assertEqual(self.ready_ids(), ["T004", "T005"])
        # A parallel round leaves the primary task file pending; the task branch shows the dispatch.
        run_git(self.repo, "branch", "gsd-path-task/T004")
        self.land_serial("T005", "Unrelated", 2, (), ("four.py",))

        self.assertEqual(self.ready_ids(), ["T004"])  # T003's dependency landed, and T003 still waits
        run_git(self.repo, "branch", "-D", "gsd-path-task/T004")
        self.land_serial("T004", "Edits two", 2, (), ("two.py",))
        self.assertEqual(self.ready_ids(), ["T003"])

    def test_ready_holds_a_task_while_an_in_progress_task_shares_its_regression_source(self) -> None:
        self.shared_source_plan(
            ("T003", "Edits one", (), ("one.py",)),
            ("T004", "Edits two", (), ("two.py",)),
        )
        base = run_git(self.repo, "rev-parse", "HEAD")
        self.write_task("T004", task_text("T004", "Edits two", 2, (), ("two.py",), status="in-progress",
                                           agent="builder", base=base, worktree=str(self.repo)))

        self.assertEqual(self.ready_ids(), [])  # T003 waits for the serial task T004

    def test_verify_ledger_records_and_looks_up_runs(self) -> None:
        (self.repo / "seed.txt").write_bytes("seed\n".encode("utf-8"))
        first = self.commit_all("seed")
        (self.repo / "seed.txt").write_bytes("more\n".encode("utf-8"))
        second = self.commit_all("more")
        command = "python3  -m unittest   tests.test_one"

        result, payload = self.cli("verify-lookup", "--command", command, "--commit", first)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((payload["hit"], payload["reuse"], payload["entry"]), (False, False, None))

        result, payload = self.cli(
            "verify-record", "--command", command, "--commit", first, "--result", "pass"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["ledger"], ".project/build/verify-ledger.jsonl")
        self.assertEqual(payload["entry"]["command"], command)
        ledger = self.repo / ".project" / "build" / "verify-ledger.jsonl"
        self.assertEqual(len(ledger.read_text(encoding="utf-8").splitlines()), 1)

        result, payload = self.cli(
            "verify-lookup", "--command", command, "--commit", first
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["hit"])
        self.assertTrue(payload["reuse"])
        self.assertEqual(payload["entry"]["commit"], first)
        self.assertEqual(payload["entry"]["result"], "pass")
        self.assertIn("recorded_at", payload["entry"])

        result, payload = self.cli("verify-lookup", "--command", command, "--commit", second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(payload["hit"])

        result, payload = self.cli(
            "verify-record", "--command", command, "--commit", first, "--result", "fail"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result, payload = self.cli("verify-lookup", "--command", command, "--commit", first)
        self.assertTrue(payload["hit"])
        self.assertFalse(payload["reuse"])
        self.assertEqual(payload["entry"]["result"], "fail")

    def test_verify_record_refuses_an_ignored_ledger(self) -> None:
        (self.repo / ".gitignore").write_bytes("build/\n".encode("utf-8"))
        commit = self.commit_all("product rule")
        result, _ = self.cli(
            "verify-record", "--command", "true", "--commit", commit, "--result", "pass"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".gitignore:1:build/ excludes .project/build/verify-ledger.jsonl", result.stdout + result.stderr)
        self.assertFalse((self.repo / ".project" / "build" / "verify-ledger.jsonl").exists())

    def test_verify_ledger_preserves_shell_semantics_and_ignores_legacy(self) -> None:
        commit = self.commit_all("seed")
        passed = "test 'a b' = 'a b'"
        failed = "test 'a  b' = 'a b'"
        self.assertEqual(subprocess.run([BASH, "-c", passed]).returncode, 0)
        self.assertNotEqual(subprocess.run([BASH, "-c", failed]).returncode, 0)
        self.cli("verify-record", "--command", passed, "--commit", commit, "--result", "pass")
        _, result = self.cli("verify-lookup", "--command", failed, "--commit", commit)
        self.assertFalse(result["reuse"])
        multiline = "cat <<'END'\na  b\nEND\n"
        _, recorded = self.cli("verify-record", "--command", multiline, "--commit", commit, "--result", "pass")
        self.assertEqual(recorded["entry"]["command"], multiline)
        ledger = self.repo / ".project/build/verify-ledger.jsonl"
        ledger.write_bytes((json.dumps({"command": passed, "commit": commit, "result": "pass", "recorded_at": "legacy"}) + "\n").encode("utf-8"))
        _, result = self.cli("verify-lookup", "--command", passed, "--commit", commit)
        self.assertFalse(result["reuse"])

    def test_verify_ledger_rejects_malformed_entries_and_short_commits(self) -> None:
        (self.repo / "seed.txt").write_bytes("seed\n".encode("utf-8"))
        commit = self.commit_all("seed")
        ledger = self.repo / ".project" / "build" / "verify-ledger.jsonl"
        ledger.parent.mkdir()
        ledger.write_bytes('{"command": "x"}\n'.encode("utf-8"))

        result, payload = self.cli("verify-lookup", "--command", "x", "--commit", commit)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-ledger")

        result, payload = self.cli(
            "verify-record", "--command", "x", "--commit", commit, "--result", "pass"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-ledger")
        self.assertEqual(ledger.read_text(encoding="utf-8"), '{"command": "x"}\n')

        ledger.unlink()
        result, payload = self.cli(
            "verify-record", "--command", "x", "--commit", commit[:7], "--result", "pass"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-commit")

    def test_isolation_rejects_a_second_landing_for_done_task(self) -> None:
        _, task_file = self.prepare_in_progress_task()
        self.land_task(task_file, 1)

        with self.assertRaises(isolation.IsolationError):
            self.land_task(task_file, 2)


if __name__ == "__main__":
    unittest.main()
