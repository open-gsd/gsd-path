import contextlib
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
                "toolInput": {"filePath": "/repo/.project/archive/002-x/STATE.md"},
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
            "git -c clean.requireForce=false clean -d",
            "git clean -di",
            "git clean --interactive",
            "git update-ref -d refs/heads/task/demo",
            "git update-ref --stdin",
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

    def test_denies_powershell_archive_mutations(self):
        for command in (
            "Remove-Item -Recurse .project/archive/001-mvp",
            r"Move-Item README.md .project\archive\001-mvp\README.md",
            "Copy-Item README.md .project/archive/001-mvp/README.md",
            "Rename-Item .project/archive/001-mvp/OLD.md NEW.md",
            "Set-Content .project/archive/001-mvp/NOTE.md broken",
            "Add-Content .project/archive/001-mvp/NOTE.md broken",
            "Clear-Content .project/archive/001-mvp/NOTE.md",
            "New-Item .project/archive/001-mvp/NEW.md",
            "'broken' | Out-File .project/archive/001-mvp/NOTE.md",
            r"del .project\archive\001-mvp\NOTE.md",
            "Get-Item .project/archive/001-mvp/NOTE.md | Remove-Item",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "PowerShell", "tool_input": {"command": command}}
                )

    def test_denies_unproven_archive_shell_commands(self):
        for command in (
            "sed -i 's/a/b/' .project/archive/001-mvp/NOTE.md",
            "python3 -c 'write()' .project/archive/001-mvp/NOTE.md",
            "cat .project/archive/001-mvp/NOTE.md > /tmp/note.md",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_denies_archive_mutation_from_archive_working_directory(self):
        for key in ("working_directory", "workdir", "cwd"):
            with self.subTest(key=key):
                self.assert_denied(
                    {
                        "tool_name": "Shell",
                        "tool_input": {
                            "command": "touch NOTE.md",
                            key: ".project/archive/001-mvp",
                        },
                    }
                )

    def test_resolves_archive_operands_against_working_directory(self):
        for key in ("working_directory", "workdir", "cwd"):
            with self.subTest(key=key):
                self.assert_denied(
                    {
                        "tool_name": "Shell",
                        "tool_input": {
                            "command": "rm -rf archive/001-mvp",
                            key: "/repo/.project",
                        },
                    }
                )

    def test_allows_relative_archive_read_from_project_directory(self):
        self.assert_allowed(
            {
                "tool_name": "Shell",
                "tool_input": {
                    "command": "cat archive/001-mvp/MANIFEST.md",
                    "working_directory": "/repo/.project",
                },
            }
        )

    def test_allows_archive_read_from_archive_working_directory(self):
        self.assert_allowed(
            {
                "tool_name": "Shell",
                "tool_input": {
                    "command": "cat NOTE.md",
                    "working_directory": ".project/archive/001-mvp",
                },
            }
        )

    def test_allows_read_tool_from_archive_working_directory(self):
        self.assert_allowed(
            {
                "tool_name": "Read",
                "tool_input": {
                    "path": "NOTE.md",
                    "cwd": ".project/archive/001-mvp",
                },
            }
        )

    def test_denies_ambiguous_archive_mutations(self):
        for command in (
            "rm .project/$(printf archive)/001-mvp/NOTE.md",
            "cd .project && rm archive/001-mvp/NOTE.md",
            'P=.project; rm "$P/archive/001-mvp/NOTE.md"',
            'rm "$P/001-mvp/MANIFEST.md"',
            "bash -lc '(cd .project && rm archive/001-mvp/NOTE.md)'",
            "bash -lc 'pushd .project >/dev/null && rm archive/001-mvp/PLAN.md'",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_denies_write_capable_and_multiline_archive_reads(self):
        for command in (
            "git diff --output=.project/archive/001-mvp/NOTE.md HEAD",
            "cat .project/archive/001-mvp/NOTE.md\nrm .project/archive/001-mvp/NOTE.md",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_denies_destructive_git_commands_with_quoted_flags(self):
        for command in (
            "git reset '--hard' HEAD~1",
            "git clean '-fd'",
            "git push '--force-with-lease' origin main",
            "git branch '-D' gsd-path/task",
            "env git reset '--hard' HEAD~1",
            "git -C repo reset '--hard' HEAD~1",
            "FOO=1 git reset '--hard' HEAD~1",
            "git.exe reset '--hard' HEAD~1",
            "echo ok\ngit reset '--hard' HEAD~1",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_denies_semantic_force_pushes_and_branch_deletes(self):
        for command in (
            "git push origin +main",
            "git push --mirror origin",
            "git branch --delete --force gsd-path/task",
            "git branch -df gsd-path/task",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_denies_destructive_git_through_command_wrappers(self):
        for command in (
            "bash -lc 'git reset --hard HEAD~1'",
            "bash --norc -c 'git reset --hard HEAD~1'",
            "sh -c 'git clean -fd'",
            "command git push origin +main",
            "exec git branch --delete --force task",
            "pwsh -Command 'git reset --hard HEAD~1'",
            "cmd /c 'git clean -fd'",
            "cmd.exe /c 'call git reset --hard HEAD~1'",
            "env -- git reset --hard HEAD~1",
            "env -u TOKEN -- git clean -fd",
            'G=git; "$G" reset --hard HEAD~1',
            "git -c alias.wipe='reset --hard' wipe HEAD~1",
            "git -calias.wipe='reset --hard' wipe HEAD~1",
            "git --config-env=alias.wipe=WIPE wipe HEAD~1",
            "bash -lc 'set -- git; \"$1\" reset --hard HEAD~1'",
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.wipe "
            "GIT_CONFIG_VALUE_0='reset --hard' git wipe HEAD~1",
            "if git reset --hard HEAD~1; then :; fi",
            "git config alias.wipe 'reset --hard'",
            "eval 'git reset --hard HEAD~1'",
            "source /tmp/unsafe-gsd-path-command.sh",
            ". /tmp/unsafe-gsd-path-command.sh",
            "builtin eval 'git reset --hard HEAD~1'",
            'echo "$(git reset --hard HEAD~1)"',
            "bash -lc 'export HOME=/tmp/aliases; git wipe HEAD~1'",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_denies_deleting_archive_ancestor(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            (repository / ".project" / "archive" / "001-mvp").mkdir(parents=True)
            try:
                os.chdir(repository)
                self.assert_denied(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": "rm -rf .project"},
                    }
                )
            finally:
                os.chdir(previous)

    def test_allows_reading_unresolved_path(self):
        self.assert_allowed(
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'cat "$P/001-mvp/MANIFEST.md"'},
            }
        )

    def test_denies_archive_path_through_symlink(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            archive = repository / ".project" / "archive" / "001-mvp"
            archive.mkdir(parents=True)
            (repository / "history").symlink_to(
                ".project/archive", target_is_directory=True
            )
            try:
                os.chdir(repository)
                self.assert_denied(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": "rm history/001-mvp/PLAN.md"},
                    }
                )
            finally:
                os.chdir(previous)

    def test_denies_destructive_persistent_git_alias(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(
                ["git", "config", "alias.wipe", "reset --hard"],
                cwd=repository,
                check=True,
            )
            try:
                os.chdir(repository)
                self.assert_denied(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": "git wipe HEAD~1"},
                    }
                )
            finally:
                os.chdir(previous)

    def test_denies_git_alias_through_alternate_home(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            home = root / "home"
            repository.mkdir()
            home.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(
                [
                    "git",
                    "config",
                    "--file",
                    str(home / ".gitconfig"),
                    "alias.wipe",
                    "reset --hard",
                ],
                check=True,
            )
            try:
                os.chdir(repository)
                self.assert_denied(
                    {
                        "tool_name": "Bash",
                        "tool_input": {
                            "command": f"HOME={shlex.quote(str(home))} git wipe HEAD~1"
                        },
                    }
                )
            finally:
                os.chdir(previous)

    def test_denies_git_alias_through_env_working_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(
                ["git", "config", "alias.wipe", "reset --hard"],
                cwd=repository,
                check=True,
            )
            self.assert_denied(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": f"env -C {shlex.quote(str(repository))} git wipe HEAD~1"
                    },
                }
            )

    def test_allows_safe_git_through_command_wrappers(self):
        for command in (
            "bash -lc 'git status'",
            "command git branch -d merged",
            "env -- git status",
            "git -c core.quotepath=false status",
        ):
            with self.subTest(command=command):
                self.assert_allowed(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_denies_archive_paths_hidden_by_shell_expansion(self):
        for command in (
            "rm .project/arc[h]ive/001-mvp/NOTE.md",
            "rm .project/{archive,active}/001-mvp/NOTE.md",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_denies_execution_capable_archive_read_options(self):
        for command in (
            "rg --pre rm .project/archive/001-mvp/NOTE.md",
            "rg --pre=rm .project/archive/001-mvp/NOTE.md",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_allows_powershell_archive_reads(self):
        self.assert_allowed(
            {
                "tool_name": "PowerShell",
                "tool_input": {
                    "command": "Get-Content .project/archive/001-mvp/NOTE.md"
                },
            }
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

    def test_denies_codex_apply_patch_inside_archive(self):
        self.assert_denied(
            {
                "tool_name": "apply_patch",
                "tool_input": "*** Begin Patch\n*** Update File: .project/archive/001-mvp/PLAN.md\n@@\n-old\n+new\n*** End Patch",
            }
        )

    def test_denies_nested_apply_patch_inside_archive(self):
        self.assert_denied(
            {
                "tool_name": "ApplyPatch",
                "tool_input": {
                    "patch": "*** Begin Patch\n*** Update File: .project/archive/001-mvp/PLAN.md\n@@\n-old\n+new\n*** End Patch"
                },
            }
        )

    def test_allows_codex_apply_patch_outside_archive(self):
        self.assert_allowed(
            {
                "tool_name": "apply_patch",
                "tool_input": "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+git reset --hard is blocked\n*** End Patch",
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
        self.assert_denied(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": ["bash", "-lc", "git reset --hard HEAD~1"]
                },
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

    def test_fails_closed_on_bad_input(self):
        for payload in ("not json", "[]", '"string"', {}, {"tool_name": []}):
            with self.subTest(payload=payload):
                self.assert_denied(payload)

    def test_fails_closed_on_internal_error(self):
        with mock.patch.object(guard_hook, "collect", side_effect=RuntimeError("boom")):
            self.assert_denied({"tool_name": "Edit", "tool_input": {}})

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
