import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import guard_hook

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "guard_hook.py"


def run_guard(payload):
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    output = io.StringIO()
    error = io.StringIO()
    status = 0
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
        sys.stdin = io.StringIO(stdin)
        try:
            guard_hook.main()
        except SystemExit as exit_signal:
            status = exit_signal.code
        finally:
            sys.stdin = sys.__stdin__
    return status, output.getvalue(), error.getvalue()


class GuardHookTests(unittest.TestCase):
    def assert_denied(self, payload):
        status, output, error = run_guard(payload)
        self.assertEqual(status, 2, error)
        self.assertIn("gsd-path guard:", error)
        decision = json.loads(output)
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertEqual(
            decision["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def assert_allowed(self, payload):
        status, output, error = run_guard(payload)
        self.assertEqual(status, 0, error)
        self.assertEqual(output, "")

    def test_denies_edit_inside_archive(self):
        self.assert_denied(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": ".project/archive/001-mvp/plan/PLAN.md"},
            }
        )

    def test_denies_absolute_archive_path_and_camel_case_keys(self):
        self.assert_denied(
            {
                "toolName": "Write",
                "toolInput": {"filePath": "/repo/.project/archive/002-x/BOARD.md"},
            }
        )

    def test_allows_edit_outside_archive(self):
        self.assert_allowed(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": ".project/plan/PLAN.md"},
            }
        )

    def test_allows_reading_archive(self):
        self.assert_allowed(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": ".project/archive/001-mvp/MANIFEST.md"},
            }
        )

    def test_denies_destructive_git_commands(self):
        for command in (
            "git reset --hard HEAD~2",
            "git clean -fd",
            "git push --force origin main",
            "git push origin main --force-with-lease",
            "git branch -D gsd-path/feature",
            "rm -rf .project/archive/001-mvp",
            "mv .project/archive/001-mvp /tmp/x",
            "echo broken > .project/archive/001-mvp/MANIFEST.md",
            "cp foo .project/archive/001-mvp/MANIFEST.md",
            "tee .project/archive/001-mvp/x",
            "git checkout -- .project/archive/001-mvp/MANIFEST.md",
            "git restore .project/archive/001-mvp/MANIFEST.md",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_denies_archive_path_via_any_tool_name(self):
        self.assert_denied(
            {
                "tool_name": "StrReplace",
                "tool_input": {
                    "relative_path": ".project/archive/001-mvp/plan/PLAN.md",
                },
            }
        )

    def test_denies_archive_path_with_traversal(self):
        self.assert_denied(
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "foo/../../.project/archive/001-mvp/MANIFEST.md",
                },
            }
        )

    def test_denies_archive_path_with_backslashes(self):
        self.assert_denied(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": ".project\\archive\\001-mvp\\MANIFEST.md",
                },
            }
        )

    def test_allows_cp_and_checkout_outside_archive(self):
        for command in (
            "cp foo .project/plan/PLAN.md",
            "git checkout -- app.py",
            "git restore app.py",
        ):
            with self.subTest(command=command):
                self.assert_allowed(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_allows_ordinary_git_commands(self):
        for command in (
            "git status",
            "git push origin main",
            "git branch -d merged-branch",
            "git reset HEAD~1",
            "git clean -n",
            "git status && git log --oneline",
            "cat .project/archive/001-mvp/MANIFEST.md",
        ):
            with self.subTest(command=command):
                self.assert_allowed(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_denies_argv_array_commands(self):
        self.assert_denied(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": ["bash", "-lc", "rm -rf .project/archive"],
                },
            }
        )
        self.assert_denied(
            {
                "tool_name": "Bash",
                "tool_input": {"command": ["git", "reset", "--hard", "HEAD~2"]},
            }
        )

    def test_allows_safe_argv_array_commands(self):
        self.assert_allowed(
            {
                "tool_name": "Bash",
                "tool_input": {"command": ["git", "status"]},
            }
        )

    def test_denies_case_variant_archive_paths(self):
        self.assert_denied(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": ".Project/Archive/001-mvp/MANIFEST.md"},
            }
        )

    def test_denies_case_variant_archive_commands(self):
        for command in (
            "rm -rf .Project/Archive/001-mvp",
            "RM -rf .project/archive/001-mvp",
            "echo broken > .Project/Archive/001-mvp/MANIFEST.md",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_allows_safe_branch_delete_despite_casefolding(self):
        self.assert_allowed(
            {"tool_name": "Bash", "tool_input": {"command": "git branch -d merged"}}
        )

    def test_write_tool_containing_read_verb_is_not_read_only(self):
        for tool in ("get_and_write", "CatEdit", "list_then_delete"):
            with self.subTest(tool=tool):
                self.assert_denied(
                    {
                        "tool_name": tool,
                        "tool_input": {
                            "file_path": ".project/archive/001-mvp/MANIFEST.md",
                        },
                    }
                )

    def test_segment_boundary_blocks_joining_across_operators(self):
        self.assert_allowed(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git status; echo reset --hard"},
            }
        )

    def test_fails_open_on_bad_input(self):
        for payload in ("not json", "[]", '"string"'):
            with self.subTest(payload=payload):
                self.assert_allowed(payload)

    def test_subprocess_contract_end_to_end(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(
                {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}
            ),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["permissionDecision"], "deny")

    def test_subprocess_denies_cp_into_archive(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "cp foo .project/archive/001-mvp/MANIFEST.md",
                    },
                }
            ),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
