import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Optional, Sequence, Tuple

from scripts import check_task_briefs


CONTRACT = "- `render(name: str) -> str` in `src/app.py` returns the greeting."

TASK_TEMPLATE = """---
id: {task_id}
title: Demo task {task_id}
wave: 1
deps: []
status: pending
agent: null
base: null
worktree: null
task_branch: null
files:
{files_block}
---

# {task_id} — demo

## Context

{context}

## Approach

{approach}

## Interface contract

{contract}

## Intent coverage

- None

## Acceptance criteria

1. The demo behavior holds.

## Verify

```bash
{verify}
```

## Log

- 2026-08-11 — created by planner
"""


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(root), *arguments),
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


class TaskBriefTests(unittest.TestCase):
    def write(self, root: Path, relative: str, content: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def init_repo(self, root: Path) -> None:
        git(root, "init")
        git(root, "config", "user.email", "test@example.test")
        git(root, "config", "user.name", "Test")
        self.write(root, "src/app.py", "def render(name):\n    return name\n")
        self.write(root, "tests/test_app.py", "import unittest\n")
        self.write(root, "scripts/check.sh", "#!/bin/sh\nexit 0\n")

    def commit(self, root: Path) -> str:
        git(root, "add", ".")
        git(root, "commit", "-m", "layer base")
        return git(root, "rev-parse", "HEAD")

    def write_task(
        self,
        root: Path,
        task_id: str,
        *,
        files: Sequence[str] = ("src/app.py",),
        contract: str = CONTRACT,
        context: str = "The task extends `src/app.py` and adds `tests/test_new.py`.",
        approach: str = "- Keep `tests/test_app.py` green.",
        verify: str = "python3 tests/test_app.py\nbash ./scripts/check.sh tests/test_app.py",
        slug: Optional[str] = None,
    ) -> None:
        files_block = "\n".join(f"  - {entry}" for entry in files)
        self.write(
            root,
            f".project/tasks/{task_id}-{slug or 'demo'}.md",
            TASK_TEMPLATE.format(
                task_id=task_id,
                files_block=files_block,
                context=context,
                approach=approach,
                contract=contract,
                verify=verify,
            ),
        )

    def write_happy_tasks(self, root: Path) -> None:
        self.write_task(root, "T001", files=("src/app.py", "tests/test_new.py"))
        self.write_task(
            root,
            "T002",
            files=("tests/test_app.py",),
            context="The task re-reads `src/app.py` for the review.",
        )

    def run_main(self, argv: Sequence[str]) -> Tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = check_task_briefs.main(list(argv))
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def lint(self, root: Path, base: str) -> Tuple[int, str, str]:
        return self.run_main(["--repo", str(root), "--base", base])

    def test_happy_path_passes_with_json_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            base = self.commit(root)

            exit_code, stdout, _stderr = self.lint(root, base)

            self.assertEqual(exit_code, 0)
            summary = json.loads(stdout)
            self.assertEqual(summary["base"], base)
            self.assertEqual(summary["tasks"], 2)
            self.assertGreater(summary["checked"], 0)

    def test_legacy_commit_frontmatter_field_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            task_path = root / ".project/tasks/T001-demo.md"
            task_path.write_text(
                task_path.read_text(encoding="utf-8").replace(
                    "base: null\n", "base: null\ncommit: null\n", 1
                ),
                encoding="utf-8",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("T001: forbidden frontmatter field: commit", stderr)

    def test_declared_file_with_new_parent_directory_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            self.write_task(
                root, "T003", files=("newpkg/mod.py",), contract="- None",
                context="The task adds a module.",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 0, stderr)
            self.assertFalse((root / "newpkg").exists())

    def test_new_path_rejects_non_directory_ancestors(self) -> None:
        for kind in ("file", "symlink", "git"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.init_repo(root)
                parent = root / "obstacle"
                if kind == "file":
                    parent.write_text("not a directory")
                elif kind == "symlink":
                    parent.symlink_to("src", target_is_directory=True)
                base = self.commit(root)
                path = ".git/new/file.py" if kind == "git" else "obstacle/file.py"
                self.write_task(root, "T001", files=(path,), contract="- None",
                                context="Create the owned file.", verify="python3 " + path)
                result, _, error = self.lint(root, base)
                self.assertEqual(result, 1)
                self.assertIn(path, error)

    def test_hallucinated_prose_path_in_context_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            self.write_task(
                root, "T003", contract="- None",
                context="The task rewires `src/missing.py` entirely.",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("T003", stderr)
            self.assertIn("src/missing.py", stderr)

    def test_backticked_url_route_in_prose_is_not_a_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            self.write_task(
                root, "T003", contract="- None",
                context="The handler serves `/api/users` and `/api/users/{id}`.",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 0, stderr)

    def test_consumer_can_share_distinct_contracts_with_two_providers(self) -> None:
        total = "- `total_amount(records) -> int`: return the integer sum."
        export = "- `write_csv(records, stream) -> None`: write CSV rows."
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            base = self.commit(root)
            for task_id, file, contract in (
                ("T001", "total.py", total),
                ("T002", "export.py", export),
                ("T003", "reports.py", total + "\n\n" + export),
            ):
                self.write_task(
                    root, task_id, files=(file,), contract=contract,
                    context="Deliver the owned reporting capability.",
                    approach="Keep the exact shared shapes.",
                    verify="python3 " + file,
                )

            status, _output, error = self.lint(root, base)
            self.assertEqual(status, 0, error)

            consumer = root / ".project/tasks/T003-demo.md"
            consumer.write_text(consumer.read_text().replace("write CSV rows", "write JSON rows"))
            status, _output, error = self.lint(root, base)
            self.assertEqual(status, 1)
            self.assertIn("T002: interface contract is not shared", error)
            self.assertIn("T003: interface contract is not shared", error)
            self.assertNotIn("T001:", error)

    def test_unshared_interface_contract_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_task(root, "T001", files=("src/app.py", "tests/test_new.py"))
            self.write_task(
                root, "T002", files=("tests/test_app.py",),
                context="The task re-reads `src/app.py` for the review.",
                contract="- `other() -> None` in `src/app.py` does something else.",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("interface contract is not shared", stderr)
            self.assertIn("T001", stderr)
            self.assertIn("T002", stderr)

    def test_verify_block_path_missing_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            self.write_task(
                root, "T003", contract="- None",
                context="The task adds a check.",
                verify="python3 tests/test_missing.py",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("T003", stderr)
            self.assertIn("tests/test_missing.py", stderr)

    def test_absolute_files_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            self.write_task(
                root, "T003", files=("/abs/x.py",), contract="- None",
                context="The task adds a file.",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("not repo-relative", stderr)

    def test_parent_traversal_files_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            self.write_task(
                root, "T003", files=("../outside.py",), contract="- None",
                context="The task adds a file.",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("..", stderr)

    def test_missing_section_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            self.write_task(root, "T003", contract="- None",
                            context="The task adds a file.")
            task_path = root / ".project/tasks/T003-demo.md"
            task_path.write_text(
                task_path.read_text(encoding="utf-8").replace("## Log", "## Notes"),
                encoding="utf-8",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("missing ## Log section", stderr)

    def test_missing_frontmatter_field_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            self.write_task(root, "T003", contract="- None",
                            context="The task adds a file.")
            task_path = root / ".project/tasks/T003-demo.md"
            task_path.write_text(
                task_path.read_text(encoding="utf-8").replace(
                    "task_branch: null\n", ""
                ),
                encoding="utf-8",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("missing frontmatter field: task_branch", stderr)

    def test_duplicate_frontmatter_field_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            task_path = root / ".project/tasks/T001-demo.md"
            task_path.write_text(
                task_path.read_text(encoding="utf-8").replace(
                    "status: pending\n", "status: pending\nstatus: done\n"
                ),
                encoding="utf-8",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("frontmatter repeats field: status", stderr)

    def test_malformed_frontmatter_line_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            task_path = root / ".project/tasks/T001-demo.md"
            task_path.write_text(
                task_path.read_text(encoding="utf-8").replace(
                    "status: pending\n", "status pending\n"
                ),
                encoding="utf-8",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("malformed frontmatter line", stderr)

    def test_empty_tasks_dir_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            (root / ".project" / "tasks").mkdir(parents=True)
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("no task briefs found", stderr)

    def test_missing_tasks_dir_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("tasks directory not found", stderr)

    def test_unindented_block_list_items_are_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            task_path = root / ".project/tasks/T001-demo.md"
            task_path.write_text(
                task_path.read_text(encoding="utf-8").replace("\n  - ", "\n- "),
                encoding="utf-8",
            )
            base = self.commit(root)

            exit_code, stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 0, stderr)
            summary = json.loads(stdout)
            self.assertEqual(summary["tasks"], 2)

    def test_block_list_items_strip_quotes_like_inline_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            # Quoting must not disguise an unsafe path.
            self.write_task(
                root, "T003", files=('"../outside.py"',), contract="- None",
                context="The task adds a module.",
            )
            base = self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, base)

            self.assertEqual(exit_code, 1)
            self.assertIn("must not contain", stderr)

    def test_frontmatter_preserves_hashes_inside_quoted_values(self) -> None:
        fields, error = check_task_briefs._frontmatter(
            "---\n"
            'title: "Fix #123" # comment\n'
            "worktree: 'worktrees/task#1'\n"
            "files:\n"
            "  - 'docs/plan #1.md' # comment\n"
            "---\n"
        )

        self.assertIsNone(error)
        self.assertIsNotNone(fields)
        self.assertEqual(fields["title"], "Fix #123")
        self.assertEqual(fields["worktree"], "worktrees/task#1")
        self.assertEqual(fields["files"], ["docs/plan #1.md"])

    def test_frontmatter_preserves_hash_in_quoted_inline_list(self) -> None:
        fields, error = check_task_briefs._frontmatter(
            "---\nfiles: ['docs/plan #1.md'] # planning note\n---\n"
        )

        self.assertIsNone(error)
        self.assertIsNotNone(fields)
        self.assertEqual(fields["files"], ["docs/plan #1.md"])

    def test_frontmatter_strips_comment_after_plain_apostrophe(self) -> None:
        fields, error = check_task_briefs._frontmatter(
            "---\ntitle: Don't regress # planning note\n---\n"
        )

        self.assertIsNone(error)
        self.assertIsNotNone(fields)
        self.assertEqual(fields["title"], "Don't regress")

    def test_unresolvable_base_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.write_happy_tasks(root)
            self.commit(root)

            exit_code, _stdout, stderr = self.lint(root, "0" * 40)

            self.assertEqual(exit_code, 1)
            self.assertIn("--base does not resolve", stderr)


if __name__ == "__main__":
    unittest.main()
