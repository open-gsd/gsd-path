"""Dispatch and approval lint the same briefs at the appropriate task bases."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import state_checkpoint
from tests.test_task_briefs import TASK_TEMPLATE


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_task_briefs.py"
POLICY_CONTRACT = "- `fixtures/policy.json` carries the policy document."


def git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test",
         "-c", "user.email=test@example.test", "-c", "commit.gpgsign=false",
         *arguments],
        capture_output=True, encoding="utf-8", errors="replace", check=True,
    )
    return completed.stdout.strip()


class DispatchBriefBasesTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / "coordinator"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.write("legacy/notes.md", "historical notes\n")
        self.write("src/app.py", "print('hello')\n")
        self.historical = self.commit("historical product")
        git(self.repo, "rm", "-q", "legacy/notes.md")
        self.base = self.commit("remove historical notes")

    def write(self, relative: str, text: str, *, repo: Path = None) -> None:
        path = (repo or self.repo) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def commit(self, message: str, *, repo: Path = None) -> str:
        root = repo or self.repo
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", message)
        return git(root, "rev-parse", "HEAD")

    def plan(self, track: str = ".project") -> None:
        self.write(f"{track}/plan/PLAN.md", "# Plan\n\n" + "".join(
            f"## Wave {wave} — Deliver wave {wave}\n\n"
            f"Goal: Deliver wave {wave}.\nReview depth: full\n\n"
            for wave in (1, 2, 3, 4)
        ))

    def task(self, task_id: str, *, track: str = ".project", wave: int = 1,
             deps=(), files=None, context: str = "Implement the owned file.",
             contract: str = "- None", verify: str = None,
             status: str = "pending", base: str = "null",
             member: str = None) -> Path:
        owned = files or (f"src/{task_id.lower()}.py",)
        text = TASK_TEMPLATE.format(
            task_id=task_id, files_block="\n".join(f"  - {name}" for name in owned),
            context=context, approach="Implement the stated behavior.",
            contract=contract, verify=verify or f"python3 {owned[0]}",
        ).replace("wave: 1", f"wave: {wave}", 1).replace(
            "deps: []", f"deps: [{', '.join(deps)}]", 1
        ).replace("status: pending", f"status: {status}", 1).replace(
            "base: null", f"base: {base}", 1
        )
        if status != "pending":
            text = text.replace("agent: null", "agent: coder", 1)
        if status == "in-progress":
            text = text.replace("worktree: null", f"worktree: {self.repo}", 1).replace(
                "task_branch: null", "task_branch: main", 1
            )
        if member is not None:
            text = text.replace("files:\n", f"repo: {member}\nfiles:\n", 1)
        relative = f"{track}/tasks/{task_id}-demo.md"
        self.write(relative, text)
        return self.repo / relative

    def combined_plan(self, track: str = ".project") -> None:
        self.plan(track)
        self.task("T001", track=track, status="done", base=self.historical,
                  context="Read `legacy/notes.md`.",
                  verify="python3 src/t001.py\npython3 legacy/notes.md")
        self.task("T002", track=track, wave=2, files=("fixtures/policy.json",),
                  contract=POLICY_CONTRACT)
        self.task("T003", track=track, wave=3, deps=("T002",),
                  context="Read `fixtures/policy.json`.", contract=POLICY_CONTRACT,
                  verify="python3 src/t003.py\npython3 fixtures/policy.json")

    def lint(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--repo", str(self.repo),
             "--base", self.base, *arguments],
            capture_output=True, encoding="utf-8", errors="replace", check=False,
        )

    def assert_passes(self, result: subprocess.CompletedProcess, tasks: int) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["tasks"], tasks)
        self.assertEqual(result.stderr, "")

    def assert_diagnostic(self, result: subprocess.CompletedProcess, *fragments: str) -> None:
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("task brief validation failed:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        for fragment in fragments:
            self.assertIn(fragment, result.stderr)

    def test_manual_dispatch_uses_landed_base_after_named_path_is_deleted(self) -> None:
        self.plan()
        self.task("T001", status="done", base=self.historical,
                  context="Read `legacy/notes.md`.",
                  verify="python3 src/t001.py\npython3 legacy/notes.md")
        self.assertFalse((self.repo / "legacy/notes.md").exists())
        self.assert_passes(self.lint(), 1)

    def test_pending_task_can_read_a_dependency_file_before_it_is_created(self) -> None:
        self.plan()
        self.task("T001", files=("fixtures/policy.json",), contract=POLICY_CONTRACT)
        self.task("T002", wave=2, deps=("T001",), context="Read `fixtures/policy.json`.",
                  contract=POLICY_CONTRACT,
                  verify="python3 src/t002.py\npython3 fixtures/policy.json")
        self.assertFalse((self.repo / "fixtures/policy.json").exists())
        self.assert_passes(self.lint("--tasks-dir", ".project/tasks"), 2)

    def test_infers_active_lookahead_and_other_plan_tracks(self) -> None:
        for track in (".project", ".project/next", "milestones/second"):
            with self.subTest(track=track):
                self.combined_plan(track)
                self.assert_passes(self.lint("--tasks-dir", f"{track}/tasks"), 3)

    def test_explicit_project_dir_selects_its_plan_over_default_track(self) -> None:
        self.plan()
        self.task("T001", context="Read `ghost/unrelated.py`.")
        self.combined_plan(".project/next")
        self.assert_passes(self.lint("--project-dir", ".project/next"), 3)

    def test_dispatch_accepts_a_dependency_still_in_progress(self) -> None:
        self.combined_plan()
        self.task("T002", wave=2, files=("fixtures/policy.json",),
                  status="in-progress", base=self.base, contract=POLICY_CONTRACT)
        for arguments in ((), ("--project-dir", ".project")):
            with self.subTest(arguments=arguments):
                self.assert_passes(self.lint(*arguments), 3)

    def test_plan_approval_still_requires_clean_unlanded_metadata(self) -> None:
        track = ".project/next"
        self.combined_plan(track)
        state_checkpoint._validate_plan_briefs(self.repo, "plan", track)
        self.task("T002", track=track, wave=2, files=("fixtures/policy.json",),
                  status="in-progress", base=self.base, contract=POLICY_CONTRACT)
        with self.assertRaisesRegex(state_checkpoint.PipelineStateError, "initially"):
            state_checkpoint._validate_plan_briefs(self.repo, "plan", track)

    def test_unsupplied_path_is_the_only_diagnostic_in_an_otherwise_valid_plan(self) -> None:
        self.combined_plan()
        self.task("T002", wave=2, files=("fixtures/policy.json",),
                  context="Read `fixtures/absent.json`.", contract=POLICY_CONTRACT)
        result = self.lint()
        self.assert_diagnostic(result, "T002:", "fixtures/absent.json")
        self.assertNotIn("T001:", result.stderr)
        self.assertNotIn("T003:", result.stderr)

    def test_unrelated_tasks_do_not_supply_files(self) -> None:
        self.plan()
        self.task("T001", files=("fixtures/policy.json",))
        self.task("T002", wave=2, context="Read `fixtures/policy.json`.")
        self.assert_diagnostic(self.lint(), "T002:", "missing at the layer base: fixtures/policy.json")

    def test_landed_tasks_receive_no_dependency_file_allowance(self) -> None:
        self.plan()
        self.task("T001", status="done", base=self.historical,
                  files=("fixtures/policy.json",))
        self.task("T002", wave=2, deps=("T001",), status="done", base=self.historical,
                  context="Read `fixtures/policy.json`.")
        self.assert_diagnostic(self.lint("--project-dir", ".project"),
                               "T002:", "missing at the layer base: fixtures/policy.json")

    def test_loose_tasks_and_tracks_without_a_plan_keep_layer_base_lint(self) -> None:
        for track, tasks_dir, has_plan in (
            ("loose", "loose/tasks", False),
            (".project/next", ".project/next/tasks", False),
            ("loose", "loose/briefs", True),
        ):
            with self.subTest(tasks_dir=tasks_dir):
                if has_plan:
                    self.plan(track)
                path = self.task("T001", track=track, status="done", base=self.historical,
                                 context="Read `legacy/notes.md`.")
                destination = self.repo / tasks_dir / path.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination != path:
                    path.rename(destination)
                self.assert_diagnostic(self.lint("--tasks-dir", tasks_dir),
                                       "missing at the layer base: legacy/notes.md")

    def test_malformed_historical_bases_report_diagnostics_without_tracebacks(self) -> None:
        self.plan()
        for base in ("short-sha", "f" * 40):
            with self.subTest(base=base):
                self.task("T001", status="done", base=base)
                self.assert_diagnostic(self.lint("--project-dir", ".project"),
                                       "T001", "historical base", base)

    def test_plan_approval_reports_a_malformed_historical_base(self) -> None:
        track = ".project/next"
        self.plan(track)
        self.task("T001", track=track, status="done", base="short-sha")
        with self.assertRaisesRegex(state_checkpoint.PipelineStateError, "historical base"):
            state_checkpoint._validate_plan_briefs(self.repo, "plan", track)

    def test_invalid_dependency_graphs_report_diagnostics_without_tracebacks(self) -> None:
        self.plan()
        for dependencies, diagnostic in ((("T999",), "unknown dependency T999"),
                                         (("T001",), "dependency cycle")):
            with self.subTest(dependencies=dependencies):
                self.task("T001", deps=dependencies)
                self.assert_diagnostic(self.lint("--project-dir", ".project"), diagnostic)

    def member(self) -> Path:
        checkout = self.root / "member"
        git(self.root, "clone", "-q", str(self.repo), str(checkout))
        git(checkout, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.write(".project/MEMBERS.md", "# Members\n\n## api\n"
                   f"Checkout: {checkout}\nRemote: https://github.com/example/api.git\n"
                   "Integration: default\n")
        return checkout

    def test_transitive_same_repo_dependency_survives_a_cross_repo_intermediate(self) -> None:
        self.member()
        self.plan()
        self.task("T001", files=("fixtures/policy.json",))
        self.task("T002", wave=2, deps=("T001",), member="api")
        self.task("T003", wave=3, deps=("T002",), context="Read `fixtures/policy.json`.")
        self.assert_passes(self.lint("--project-dir", ".project"), 3)

    def test_dependency_in_another_repo_does_not_supply_a_same_named_file(self) -> None:
        self.member()
        self.plan()
        self.task("T001", files=("fixtures/policy.json",))
        self.task("T002", wave=2, deps=("T001",), member="api",
                  context="Read `fixtures/policy.json`.")
        self.assert_diagnostic(self.lint("--project-dir", ".project"),
                               "T002:", "missing at the layer base: fixtures/policy.json")

    def test_member_historical_base_can_resolve_in_coordinator_or_only_in_member(self) -> None:
        checkout = self.member()
        self.plan()
        # The clone contains the coordinator's historical object as well as its HEAD.
        self.task("T001", member="api", status="done", base=self.historical,
                  context="Read `legacy/notes.md`.")
        self.assert_passes(self.lint("--project-dir", ".project"), 1)
        self.write("legacy/member-notes.md", "member-only history\n", repo=checkout)
        member_base = self.commit("member historical product", repo=checkout)
        git(checkout, "rm", "-q", "legacy/member-notes.md")
        self.commit("remove member historical product", repo=checkout)
        git(checkout, "update-ref", "refs/remotes/origin/main", "HEAD")
        with self.assertRaises(subprocess.CalledProcessError):
            git(self.repo, "cat-file", "-e", f"{member_base}^{{commit}}")
        self.task("T001", member="api", status="done", base=member_base,
                  context="Read `legacy/member-notes.md`.")
        self.assert_passes(self.lint("--project-dir", ".project"), 1)


if __name__ == "__main__":
    unittest.main()
