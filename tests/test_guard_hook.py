import contextlib
import io
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import guard_hook
from install import PROJECT_RUNTIME_SCRIPTS
import status_runtime
from tests._platform import requires_symlink

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
    def status(self, root, phase="plan", action="run-phase", route_phase=None):
        route_phase = route_phase or phase
        route = {
            "action": action,
            "reason": f"state is {phase}/active",
        }
        if action == "run-phase":
            route["phase"] = route_phase
        return {
            "schema": "gsd-path/status/v1",
            "advance": False,
            "state": {
                "pipeline": "gsd-path/v2",
                "project": "demo",
                "milestone": "demo",
                "phase": phase,
                "status": "active",
                "branch": "gsd-path/M001",
                "archive": None,
                "integration_default": "direct",
                "integration": "direct",
                "integration_source": "default",
            },
            "route": route,
            "path": str(root / ".project" / "STATE.md"),
            "next_skill": (
                f"gsd-path-{route_phase}" if action == "run-phase" else "gsd-path"
            ),
        }

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

    def init_git_repo(self, root):
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "config", "user.name", "Guard test"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "guard-test@example.invalid"],
            cwd=root,
            check=True,
        )
        (root / "README.md").write_text("guard fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True)
        return root

    def git(self, root, *arguments):
        return subprocess.run(
            ["git", *arguments], cwd=root, check=True, capture_output=True,
            encoding="utf-8", errors="replace",
        )

    def bash_in(self, root, command):
        return {
            "tool_name": "Bash",
            "tool_input": {"command": command, "cwd": str(root)},
        }

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

    def test_bundled_helper_may_name_the_archive(self):
        helper = 'python3 -B scripts/pipeline_state.py record-shipment --repo . --archive .project/archive/001-x --event "archive preflight passed; shipment recorded"'
        self.assert_allowed({"tool_name": "Bash", "tool_input": {"command": helper}})
        for suffix in (
            " && git commit -qm ship",
            "; git commit -qm ship",
            " | cat",
            " &",
            " > receipt.txt",
            " $(printf shipped)",
            ' --event "two\nlines"',
            ' --event "two\rlines"',
            r" --event sh\ipped",
        ):
            with self.subTest(suffix=suffix):
                self.assert_denied({
                    "tool_name": "Bash",
                    "tool_input": {"command": helper + suffix},
                })

    def test_documented_record_shipment_command_is_allowed(self):
        ship = SCRIPT.parent.parent / "skills" / "gsd-path" / "SHIP.md"
        blocks = (
            section.split("```", 1)[0].strip()
            for section in ship.read_text(encoding="utf-8").split("```bash\n")[1:]
        )
        command = next(
            block for block in blocks
            if block.startswith("python3 <absolute pipeline_state.py> record-shipment")
        )
        command = (
            command.replace(
                "<absolute pipeline_state.py>",
                # Agents type POSIX paths in Git Bash; backslashes are shell escapes.
                shlex.quote((SCRIPT.parent / "pipeline_state.py").as_posix()),
            )
            .replace("<root>", ".")
            .replace("<STATE.archive>", ".project/archive/001-x")
        )
        self.assert_allowed({
            "tool_name": "Bash",
            "tool_input": {"command": command},
        })

    def test_bundled_helper_rejects_shell_redirections(self):
        archive = ".project/archive/001-x/MANIFEST.md"
        for suffix in (
            f"&> {archive}",
            f"&>> {archive}",
            f">& {archive}",
            f"2> {archive}",
            f"1>> {archive}",
            f"< {archive}",
            f"--archive {archive} 2>&1",
            f"--archive {archive} <&0",
            f"--archive {archive} > out.txt",
            f"--archive {archive} >| out.txt",
        ):
            with self.subTest(suffix=suffix):
                self.assert_denied({
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": f"python3 scripts/pipeline_state.py --help {suffix}",
                    },
                })

    def test_bundled_helper_rejects_identical_copy_outside_runtime(self):
        for name in ("pipeline_state.py", "archive_milestone.py"):
            with self.subTest(helper=name), tempfile.TemporaryDirectory() as temporary:
                helper = Path(temporary) / name
                shutil.copyfile(SCRIPT.parent / name, helper)
                self.assert_denied({
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": f"python3 -B {helper} --archive .project/archive/001-x",
                    },
                })

    def test_bundled_helper_rejects_interpreter_paths(self):
        for interpreter in ("tools/python3", "/usr/bin/python3", "./python", "Python3"):
            with self.subTest(interpreter=interpreter):
                self.assert_denied({
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": f"{interpreter} scripts/pipeline_state.py --archive .project/archive/001-x",
                    },
                })

    def test_bundled_helper_uses_installed_runtime_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / ".gsd-path" / "runtime"
            runtime.mkdir(parents=True)
            with mock.patch.object(guard_hook, "__file__", str(runtime.parent / "guard_hook.py")):
                for name in ("pipeline_state.py", "archive_milestone.py"):
                    helper = runtime / name
                    shutil.copyfile(SCRIPT.parent / name, helper)
                    shutil.copyfile(helper, runtime.parent / name)
                    for interpreter in ("python", "python3 -B"):
                        with self.subTest(helper=name, interpreter=interpreter):
                            self.assert_allowed({
                                "tool_name": "Bash",
                                "tool_input": {
                                    "command": f"{interpreter} .gsd-path/runtime/{name} --archive .project/archive/001-x",
                                    "workdir": str(root),
                                },
                            })
                    self.assert_denied({
                        "tool_name": "Bash",
                        "tool_input": {
                            "command": f"python3 {runtime.parent / name} --archive .project/archive/001-x",
                        },
                    })

    def test_bundled_helper_rejects_script_expansions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / ".gsd-path" / "runtime"
            runtime.mkdir(parents=True)
            name = "pipeline_state.py"
            shutil.copyfile(SCRIPT.parent / name, runtime / name)
            shutil.copyfile(SCRIPT.parent / name, runtime.parent / name)
            brace_directory = runtime / "{child,child}"
            brace_directory.mkdir()
            shutil.copyfile(SCRIPT.parent / name, brace_directory / name)
            with mock.patch.object(guard_hook, "__file__", str(runtime.parent / "guard_hook.py")):
                for operand in (
                    f".gsd-path/runtime/$X/../{name}",
                    f".gsd-path/runtime/${{X}}/../{name}",
                    f".gsd-path/runtime/*/../{name}",
                    f".gsd-path/runtime/?/../{name}",
                    f"~/.gsd-path/runtime/{name}",
                    f".gsd-path/runtime//../{name}",
                    f".gsd-path/runtime/{{..,..}}/../{name}",
                    f".gsd-path/runtime/{{child,child}}/{name}",
                    f".gsd-path/runtime/../.gsd-path/runtime/{name}",
                    f".gsd-path/runtime/../runtime/{name}",
                ):
                    with self.subTest(operand=operand):
                        self.assert_denied({
                            "tool_name": "Bash",
                            "tool_input": {
                                "command": f"python3 {operand} --archive .project/archive/001-x",
                                "workdir": str(root),
                            },
                        })

    def test_bundled_helper_preserves_literal_quotes_in_script_operand(self):
        self.assert_denied({
            "tool_name": "Bash",
            "tool_input": {
                "command": """python3 "'scripts/pipeline_state.py'" --archive .project/archive/001-x""",
            },
        })

    def test_bundled_helper_allows_spaces_and_quotes_in_runtime_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            for directory in ("My Project", "Owner's Project", 'A "quoted" project'):
                if os.name == "nt" and '"' in directory:
                    with self.subTest(directory=directory):
                        self.skipTest("Windows file names cannot contain a double quote")
                    continue
                root = Path(temporary) / directory
                runtime = root / ".gsd-path" / "runtime"
                runtime.mkdir(parents=True)
                with mock.patch.object(guard_hook, "__file__", str(runtime.parent / "guard_hook.py")):
                    for name in ("pipeline_state.py", "archive_milestone.py"):
                        helper = runtime / name
                        shutil.copyfile(SCRIPT.parent / name, helper)
                        with self.subTest(directory=directory, helper=name):
                            self.assert_allowed({
                                "tool_name": "Bash",
                                "tool_input": {
                                    "command": f"python3 -B {shlex.quote(helper.as_posix())} --archive .project/archive/001-x",
                                    "workdir": str(root),
                                },
                            })

    def test_bundled_helper_rejects_continuation_inside_script_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "My Project"
            runtime = root / ".gsd-path" / "runtime"
            runtime.mkdir(parents=True)
            helper = runtime / "pipeline_state.py"
            shutil.copyfile(SCRIPT.parent / helper.name, helper)
            with mock.patch.object(guard_hook, "__file__", str(runtime.parent / "guard_hook.py")):
                for continuation in ("\\\n", "\\\r\n"):
                    operand = str(helper).replace("My Project", f"My{continuation}Project")
                    with self.subTest(continuation=continuation):
                        self.assert_denied({
                            "tool_name": "Bash",
                            "tool_input": {
                                "command": f'python3 "{operand}" --archive .project/archive/001-x',
                                "workdir": str(root),
                            },
                        })

    def test_bundled_helper_tool_directory_does_not_fall_back_to_cwd(self):
        for key in ("working_directory", "workdir", "cwd"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with mock.patch.object(guard_hook.os, "getcwd", return_value=str(SCRIPT.parent.parent)):
                    self.assert_denied({
                        "tool_name": "Bash",
                        "tool_input": {
                            "command": "python3 -B scripts/pipeline_state.py --archive .project/archive/001-x",
                            key: str(root),
                        },
                    })

    def test_cursor_event_gets_explicit_allow(self):
        payload = {"cursor_version": "2026.09.02-c22c1a3", "hook_event_name": "preToolUse",
                   "tool_name": "Edit", "tool_input": {"file_path": ".project/plan/PLAN.md"}}
        status, output, error = run_guard(payload)
        self.assertEqual((status, json.loads(output), error), (0, {"permission": "allow"}, ""))

    def test_plain_prompt_denies_product_write_outside_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes(
                "owned\n".encode("utf-8")
            )
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                status, output, error = run_guard(
                    {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}
                )
        self.assertEqual(status, 2, error)
        self.assertIn("gsd-path-plan", json.loads(output)["reason"])

    def test_plain_prompt_reports_exact_block_route(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            blocked = self.status(root, action="block")
            blocked["route"]["reason"] = "branch mismatch"
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(guard_hook, "project_status", return_value=blocked),
            ):
                status, output, error = run_guard(
                    {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}
                )

        self.assertEqual(status, 2, error)
        self.assertIn("next: block: branch mismatch", json.loads(output)["reason"])

    def test_non_file_tools_are_not_treated_as_direct_writes(self):
        for tool in (
            "UpdatePlan",
            "CreateIssue",
            "SetGoal",
            "PostMessage",
            "write_stdin",
        ):
            with self.subTest(tool=tool):
                self.assert_allowed({"tool_name": tool, "tool_input": {}})

    def test_plain_prompt_allows_glob_read_with_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes(
                "owned\n".encode("utf-8")
            )
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook,
                    "project_status",
                    return_value=self.status(root),
                ),
            ):
                self.assert_allowed(
                    {"tool_name": "Glob", "tool_input": {"path": "."}}
                )

    def test_ambiguous_write_with_file_target_is_guarded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "Update",
                        "tool_input": {"file_path": "src/app.py"},
                    }
                )

    def test_save_file_with_file_target_is_guarded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "SaveFile",
                        "tool_input": {"file_path": "src/app.py", "content": "x"},
                    }
                )

    def test_copy_and_touch_file_tools_are_direct_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                for tool_name in ("CopyFile", "TouchFile"):
                    with self.subTest(tool_name=tool_name):
                        self.assert_denied(
                            {
                                "tool_name": tool_name,
                                "tool_input": {"target_file": "src/app.py"},
                            }
                        )

    def test_move_file_guards_product_source_with_external_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes(
                "owned\n".encode("utf-8")
            )
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "MoveFile",
                        "tool_input": {
                            "source_file": "src/app.py",
                            "target_file": str(Path(temporary) / "app.py"),
                        },
                    }
                )

    def test_download_file_tool_is_a_direct_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "DownloadFile",
                        "tool_input": {"target_file": "src/generated.bin"},
                    }
                )

    def test_project_status_rejects_incomplete_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = subprocess.CompletedProcess(
                [], 0, stdout='{"schema":"gsd-path/status/v1"}\n', stderr=""
            )
            with mock.patch.object(guard_hook.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(ValueError, "invalid payload"):
                    guard_hook.project_status(root)

    def test_project_status_rejects_semantically_invalid_build_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = self.status(root, phase="build")
            payload["state"]["status"] = "invented"
            result = subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(payload), stderr=""
            )
            with mock.patch.object(guard_hook.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(ValueError, "invalid payload"):
                    guard_hook.project_status(root)

    def test_project_status_accepts_canonical_integration_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = self.status(root, phase="build")
            result = subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(payload), stderr=""
            )
            with mock.patch.object(guard_hook.subprocess, "run", return_value=result):
                self.assertEqual(payload, guard_hook.project_status(root))

    def test_project_status_rejects_inconsistent_default_integration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = self.status(root, phase="build")
            payload["state"]["integration"] = "pull-request"
            result = subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(payload), stderr=""
            )
            with mock.patch.object(guard_hook.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(ValueError, "invalid payload"):
                    guard_hook.project_status(root)

    def test_batch_write_preserves_each_path_working_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes(
                "owned\n".encode("utf-8")
            )
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "BatchWrite",
                        "tool_input": {
                            "operations": [
                                {"cwd": str(Path(temporary)), "path": "outside.txt"},
                                {"cwd": str(root), "path": "src/app.py"},
                            ]
                        },
                    }
                )

    def test_plain_prompt_allows_pipeline_artifact_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes(
                "owned\n".encode("utf-8")
            )
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                self.assert_allowed(
                    {
                        "tool_name": "Write",
                        "tool_input": {"file_path": ".project/intent/INTENT.md"},
                    }
                )

    @requires_symlink
    def test_plain_prompt_denies_pipeline_control_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            outside = Path(temporary) / "outside"
            outside.mkdir()
            (root / ".gsd-path").symlink_to(outside, target_is_directory=True)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            for phase in ("plan", "build"):
                with (
                    mock.patch.object(guard_hook, "repository_root", return_value=root),
                    mock.patch.object(
                        guard_hook,
                        "project_status",
                        return_value=self.status(root, phase=phase),
                    ),
                ):
                    (root / "src").mkdir(exist_ok=True)
                    (root / "src" / "app.py").write_bytes("app\n".encode("utf-8"))
                    link = root / ".project" / "link"
                    if not link.exists():
                        link.symlink_to(root / "src" / "app.py")
                    protected_paths = [
                        ".project",
                        ".project/STATE.md",
                        ".project/next/STATE.md",
                        ".gsd-path/guard_hook.py",
                    ]
                    if phase != "build":
                        protected_paths.append(".project/link")
                    for path in protected_paths:
                        with self.subTest(phase=phase, path=path):
                            self.assert_denied(
                                {
                                    "tool_name": "Write",
                                    "tool_input": {"file_path": path},
                                }
                            )

    def test_linked_worktree_common_git_files_are_protected(self):
        with tempfile.TemporaryDirectory() as temporary:
            primary = Path(temporary) / "primary"
            linked = Path(temporary) / "linked"
            primary.mkdir()
            subprocess.run(
                ["git", "init", "-q", "-b", "main"], cwd=primary, check=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=primary, check=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.test"],
                cwd=primary,
                check=True,
            )
            (primary / ".project").mkdir()
            (primary / ".project" / "STATE.md").write_bytes(
                "owned\n".encode("utf-8")
            )
            subprocess.run(["git", "add", "."], cwd=primary, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "fixture"], cwd=primary, check=True
            )
            subprocess.run(
                ["git", "worktree", "add", "-q", "-b", "task", str(linked)],
                cwd=primary,
                check=True,
            )
            common = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-common-dir"],
                    cwd=linked,
                    encoding="utf-8", errors="replace",
                    capture_output=True,
                    check=True,
                ).stdout.strip()
            )
            if not common.is_absolute():
                common = linked / common
            authorization = common.resolve() / "refs/gsd-path/task-authorizations/T001"
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=linked),
                mock.patch.object(
                    guard_hook,
                    "project_status",
                    return_value=self.status(linked, phase="build"),
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "Write",
                        "tool_input": {"file_path": str(authorization)},
                    }
                )

    @requires_symlink
    def test_project_alias_symlink_does_not_spoof_case_behavior(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            try:
                (root / ".PROJECT").symlink_to(
                    root / ".project", target_is_directory=True
                )
                (root / ".Project").mkdir()
            except FileExistsError:
                self.skipTest("requires a case-sensitive test filesystem")
            (root / ".project" / "STATE.md").write_bytes(
                "owned\n".encode("utf-8")
            )
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "Write",
                        "tool_input": {"file_path": ".Project/app.py"},
                    }
                )

    def test_case_insensitive_state_alias_is_protected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes(
                "owned\n".encode("utf-8")
            )

            def case_insensitive_samefile(left, right):
                return os.path.abspath(left).casefold() == os.path.abspath(
                    right
                ).casefold()

            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    os.path, "samefile", side_effect=case_insensitive_samefile
                ),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "Write",
                        "tool_input": {"file_path": ".project/state.md"},
                    }
                )

    def test_case_insensitive_missing_control_path_is_protected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes(
                "owned\n".encode("utf-8")
            )
            original_samefile = os.path.samefile

            def case_insensitive_project_root(left, right):
                pair = {Path(left), Path(right)}
                if pair == {root / ".PROJECT", root / ".project"}:
                    return True
                return original_samefile(left, right)

            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    os.path, "samefile", side_effect=case_insensitive_project_root
                ),
                mock.patch.object(
                    guard_hook,
                    "project_status",
                    return_value=self.status(root, phase="build"),
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "Write",
                        "tool_input": {"file_path": ".PROJECT/next/STATE.md"},
                    }
                )

    def test_plain_prompt_allows_external_file_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook,
                    "project_status",
                    side_effect=ValueError("external writes do not need status"),
                ),
            ):
                self.assert_allowed(
                    {
                        "tool_name": "Edit",
                        "tool_input": {"file_path": str(root.parent / "note.txt")},
                    }
                )

    def test_plain_prompt_allows_routed_parallel_build_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook,
                    "project_status",
                    return_value=self.status(root, phase="build"),
                ),
            ):
                self.assert_allowed(
                    {
                        "tool_name": "Edit",
                        "tool_input": {"file_path": "src/app.py"},
                    }
                )

    def test_parallel_build_worktree_does_not_override_recovery_route(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            recovery = self.status(root, phase="build", action="resume-undo")
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(guard_hook, "project_status", return_value=recovery),
            ):
                self.assert_denied(
                    {
                        "tool_name": "Edit",
                        "tool_input": {"file_path": "src/app.py"},
                    }
                )

    def test_plain_prompt_allows_product_write_during_routed_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook,
                    "project_status",
                    return_value=self.status(root, phase="build"),
                ),
            ):
                self.assert_allowed(
                    {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}
                )

    def test_plain_prompt_denies_product_write_before_routed_build_starts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook,
                    "project_status",
                    return_value=self.status(root, phase="plan", route_phase="build"),
                ),
            ):
                self.assert_denied(
                    {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}
                )

    def test_plain_prompt_status_routes_before_git_without_writing_bytecode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            managed = root / ".gsd-path"
            runtime = managed / "runtime"
            runtime.mkdir(parents=True)
            shutil.copy2(SCRIPT, managed / "guard_hook.py")
            shutil.copy2(SCRIPT.parent / "status_runtime.py", managed / "status_runtime.py")
            scripts = SCRIPT.parent
            for name in PROJECT_RUNTIME_SCRIPTS:
                shutil.copy2(scripts / name, runtime / name)
            state = root / ".project" / "STATE.md"
            state.parent.mkdir()
            state.write_bytes(
                "---\n"
                "pipeline: gsd-path/v2\n"
                "project: demo\n"
                "milestone: demo\n"
                "phase: plan\n"
                "status: done\n"
                "branch: null\n"
                "archive: null\n"
                "---\n".encode("utf-8"),
            )
            environment = os.environ.copy()
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            result = subprocess.run(
                [sys.executable, str(managed / "guard_hook.py")],
                cwd=root,
                env=environment,
                input=json.dumps(
                    {
                        "tool_name": "Edit",
                        "tool_input": {"file_path": "src/app.py"},
                    }
                ),
                encoding="utf-8", errors="replace",
                capture_output=True,
                check=False,
            )

            self.assertEqual(2, result.returncode, result.stderr)
            self.assertIn("bind-initial", result.stderr)
            self.assertFalse((runtime / "__pycache__").exists())

    def test_status_launcher_retries_runtime_publication_gap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            managed = root / ".gsd-path"
            runtime = managed / "runtime" / "pipeline_state.py"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes("old runtime\n".encode("utf-8"))
            calls = []

            def exec_runtime(command, **options):
                calls.append((command, options))
                if len(calls) == 1:
                    runtime.unlink()
                    runtime.write_bytes("new runtime with a new inode\n".encode("utf-8"))
                    return subprocess.CompletedProcess(command, 0, b"old route\n", b"")
                return subprocess.CompletedProcess(command, 0, b"new route\n", b"")

            with mock.patch.object(status_runtime.subprocess, "run", side_effect=exec_runtime):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(0, status_runtime.launch(root))

            self.assertEqual(2, len(calls))
            self.assertEqual("new route\n", output.getvalue())
            self.assertEqual("0", calls[0][1]["env"]["GIT_OPTIONAL_LOCKS"])

    def test_status_launcher_waits_before_running_during_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / ".gsd-path" / "runtime" / "pipeline_state.py"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes("runtime\n".encode("utf-8"))
            result = subprocess.CompletedProcess([], 0, b"route\n", b"")
            with (
                mock.patch.object(
                    status_runtime,
                    "install_lock_active",
                    side_effect=[True, False, False],
                ),
                mock.patch.object(status_runtime.time, "sleep") as sleep,
                mock.patch.object(status_runtime.subprocess, "run", return_value=result) as run,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(0, status_runtime.launch(root))

            sleep.assert_called_once()
            run.assert_called_once()

    def test_status_launcher_rejects_stale_refresh_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = root / ".gsd-path-install-lock"
            lock.mkdir()
            owner_path = lock / status_runtime.INSTALL_LOCK_OWNER
            owner_path.write_bytes(
                json.dumps(
                    {
                        "schema": status_runtime.INSTALL_LOCK_SCHEMA,
                        "pid": os.getpid(),
                        "identity": status_runtime.process_identity(os.getpid()),
                    }
                ).encode("utf-8"),
            )
            self.assertTrue(status_runtime.install_lock_active(lock))
            finished = subprocess.Popen([sys.executable, "-c", "pass"])
            finished.wait()
            owner_path.write_bytes(
                json.dumps(
                    {
                        "schema": status_runtime.INSTALL_LOCK_SCHEMA,
                        "pid": finished.pid,
                        "identity": "expired",
                    }
                ).encode("utf-8"),
            )
            self.assertFalse(status_runtime.install_lock_active(lock))
            error = io.StringIO()

            with contextlib.redirect_stderr(error):
                self.assertEqual(2, status_runtime.launch(root))

            self.assertIn("status runtime is unavailable", error.getvalue())

    def test_status_launcher_uses_pid_liveness_when_identity_probe_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / ".gsd-path-install-lock"
            lock.mkdir()
            (lock / status_runtime.INSTALL_LOCK_OWNER).write_bytes(
                json.dumps(
                    {
                        "schema": status_runtime.INSTALL_LOCK_SCHEMA,
                        "pid": os.getpid(),
                        "identity": "temporarily unavailable",
                    }
                ).encode("utf-8"),
            )
            with mock.patch.object(status_runtime, "process_identity", return_value=None):
                self.assertTrue(status_runtime.install_lock_active(lock))

    def test_status_launcher_rechecks_lock_when_runtime_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = subprocess.CompletedProcess([], 0, b"route\n", b"")
            identity = (1, 2, 3, 4)
            with (
                mock.patch.object(
                    status_runtime,
                    "install_lock_active",
                    side_effect=[False, True, False, False],
                ),
                mock.patch.object(
                    status_runtime,
                    "runtime_identity",
                    side_effect=[None, identity, identity],
                ),
                mock.patch.object(
                    status_runtime.subprocess, "run", return_value=result
                ) as run,
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(0, status_runtime.launch(root))

            run.assert_called_once()
            self.assertEqual("route\n", output.getvalue())

    def test_plain_prompt_denies_mixed_product_patch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "ApplyPatch",
                        "tool_input": {
                            "patch": "*** Update File: .project/STATE.md\n"
                            "*** Update File: src/app.py\n"
                        },
                    }
                )

    def test_plain_prompt_denies_standard_unified_diff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "ApplyDiff",
                        "tool_input": {
                            "diff": (
                                "--- a/src/app.py\n+++ b/src/app.py\n"
                                "@@ -1 +1 @@\n-old\n+new\n"
                            )
                        },
                    }
                )

    def test_plain_prompt_denies_raw_unified_diff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes(
                "owned\n".encode("utf-8")
            )
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "ApplyDiff",
                        "tool_input": (
                            "--- a/src/app.py\n+++ b/src/app.py\n"
                            "@@ -1 +1 @@\n-old\n+new\n"
                        ),
                    }
                )

    def test_plain_prompt_denies_raw_rename_only_diff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", return_value=self.status(root)
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "ApplyDiff",
                        "tool_input": (
                            "diff --git a/src/old.py b/src/new.py\n"
                            "similarity index 100%\n"
                            "rename from src/old.py\n"
                            "rename to src/new.py\n"
                        ),
                    }
                )

    def test_routed_build_denies_quoted_control_path_diff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes(
                "owned\n".encode("utf-8")
            )
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook,
                    "project_status",
                    return_value=self.status(root, phase="build"),
                ),
            ):
                self.assert_denied(
                    {
                        "tool_name": "ApplyDiff",
                        "tool_input": {
                            "diff": (
                                '--- "a/.project/STATE.md"\n'
                                '+++ "b/.project/STATE.md"\n'
                                "@@ -1 +1 @@\n-old\n+new\n"
                            )
                        },
                    }
                )

    def test_plain_prompt_fails_loud_when_status_is_invalid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_bytes("invalid\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(
                    guard_hook, "project_status", side_effect=ValueError("invalid")
                ),
            ):
                status, output, error = run_guard(
                    {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}
                )
        self.assertEqual(status, 2, error)
        self.assertIn("gsd-path-forensics", json.loads(output)["reason"])

    def test_allows_reading_archive(self):
        self.assert_allowed(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": ".project/archive/001-mvp/MANIFEST.md"},
            }
        )

    def test_allows_read_only_sed_from_archive(self):
        self.assert_allowed(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "sed -n '1,5p' .project/archive/001-mvp/review/x.md"
                },
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
            "git update-ref refs/heads/task/demo " + "0" * 40,
            "git update-ref refs/heads/task/demo ''",
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

    def test_allows_forced_delete_of_literal_non_path_branch_in_every_state(self):
        for label, state in (
            ("no-state", None),
            ("active", "---\nphase: build\nbranch: bound\n---\n"),
            ("shipped", "---\nphase: shipped\nbranch: bound\n---\n"),
        ):
            with self.subTest(state=label), tempfile.TemporaryDirectory() as temporary:
                repo = self.init_git_repo(Path(temporary) / "repo")
                self.git(repo, "branch", "ordinary")
                if state is not None:
                    project = repo / ".project"
                    project.mkdir()
                    (project / "STATE.md").write_text(state, encoding="utf-8")
                self.assert_allowed(self.bash_in(repo, "git branch -D ordinary"))

    def test_forced_branch_deletes_block_path_namespaces_and_recorded_branches(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.init_git_repo(Path(temporary) / "repo")
            names = (
                "gsd-path/M001",
                "gsd-path-task/T001",
                "gsd-path-verify/T001",
                "gsd-path-integrate/T001",
                "bound-without-marker",
                "task/demo",
                "ordinary",
            )
            for name in names:
                self.git(repo, "branch", name)
            project = repo / ".project"
            tasks = project / "plan" / "tasks"
            tasks.mkdir(parents=True)
            (project / "STATE.md").write_text(
                "---\nphase: build\nbranch: bound-without-marker\n---\n",
                encoding="utf-8",
            )
            (tasks / "T001.md").write_text(
                "---\ntask_branch: task/demo\nworktree: null\n---\n",
                encoding="utf-8",
            )
            for flag, target in (
                ("-D", "gsd-path/M001"),
                ("-df", "gsd-path-task/T001"),
                ("-fd", "gsd-path-verify/T001"),
                ("--delete --force", "gsd-path-integrate/T001"),
                ("-D", "bound-without-marker"),
                ("-D", "task/demo"),
                ("-D", "ordinary task/demo"),
            ):
                with self.subTest(flag=flag, target=target):
                    self.assert_denied(
                        self.bash_in(repo, f"git branch {flag} {target}")
                    )

    def test_non_path_update_ref_deletes_are_allowed_but_owned_refs_are_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.init_git_repo(Path(temporary) / "repo")
            for name in ("ordinary", "bound-without-marker", "task/demo", "gsd-path/M001"):
                self.git(repo, "branch", name)
            project = repo / ".project"
            tasks = project / "tasks"
            tasks.mkdir(parents=True)
            (project / "STATE.md").write_text(
                "---\nphase: build\nbranch: bound-without-marker\n---\n",
                encoding="utf-8",
            )
            (tasks / "T001.md").write_text(
                "---\ntask_branch: task/demo\nworktree: null\n---\n",
                encoding="utf-8",
            )
            self.git(repo, "update-ref", "refs/gsd-path/task-authorizations/T001", "HEAD")
            self.git(
                repo,
                "symbolic-ref",
                "refs/heads/path-alias",
                "refs/heads/gsd-path/M001",
            )
            self.git(
                repo, "symbolic-ref", "refs/gsd-path/checkpoint", "refs/heads/ordinary"
            )
            for command in (
                "git update-ref -d refs/heads/ordinary",
                "git update-ref -d refs/heads/ordinary HEAD",
                "git update-ref refs/heads/ordinary " + "0" * 40 + " HEAD",
            ):
                with self.subTest(command=command):
                    self.assert_allowed(self.bash_in(repo, command))
            for ref in (
                "refs/heads/bound-without-marker",
                "refs/heads/task/demo",
                "refs/heads/gsd-path/M001",
                "refs/gsd-path/task-authorizations/T001",
                "refs/heads/path-alias",
            ):
                with self.subTest(ref=ref):
                    self.assert_denied(
                        self.bash_in(repo, f"git update-ref -d {ref}")
                    )
            self.assert_allowed(
                self.bash_in(repo, "git update-ref --no-deref -d refs/heads/path-alias")
            )
            self.assert_denied(
                self.bash_in(
                    repo,
                    "git update-ref -d refs/heads/bound-without-marker HEAD",
                )
            )
            for flag in ("", "--no-deref "):
                for deletion in (
                    "-d refs/gsd-path/checkpoint",
                    "refs/gsd-path/checkpoint " + "0" * 40,
                ):
                    with self.subTest(flag=flag, deletion=deletion):
                        self.assert_denied(
                            self.bash_in(repo, f"git update-ref {flag}{deletion}")
                        )

    def test_forced_worktree_remove_checks_registered_path_and_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = self.init_git_repo(root / "repo")
            ordinary = root / "nested" / "ordinary-worktree"
            ordinary.parent.mkdir()
            self.git(repo, "worktree", "add", "-q", "-b", "ordinary-wt", str(ordinary))
            self.assert_allowed(
                self.bash_in(repo, "git worktree remove --force ordinary-worktree")
            )
            self.assert_denied(
                self.bash_in(repo, "git worktree remove --force missing-worktree")
            )

            task_worktree = root / "recorded-task"
            self.git(repo, "worktree", "add", "-q", "-b", "recorded-wt", str(task_worktree))
            tasks = repo / ".project" / "tasks"
            tasks.mkdir(parents=True)
            (tasks / "T001.md").write_text(
                f"---\ntask_branch: null\nworktree: {task_worktree}\n---\n",
                encoding="utf-8",
            )
            self.assert_denied(
                self.bash_in(repo, f"git worktree remove --force {task_worktree}")
            )

            managed = root / "managed-task"
            self.git(repo, "worktree", "add", "-q", "-b", "gsd-path-task/T002", str(managed))
            self.assert_denied(
                self.bash_in(repo, f"git worktree remove -f -- {managed}")
            )

    def test_ownership_scope_uses_cd_and_git_c_repository_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            owned = self.init_git_repo(parent / "owned")
            unrelated = self.init_git_repo(parent / "unrelated")
            self.git(owned, "branch", "same-name")
            self.git(unrelated, "branch", "same-name")
            project = owned / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                "---\nphase: build\nbranch: same-name\n---\n", encoding="utf-8"
            )

            self.assert_denied(self.bash_in(owned, "git branch -D same-name"))
            self.assert_allowed(
                self.bash_in(owned, "cd ../unrelated && git branch -D same-name")
            )
            self.assert_allowed(
                self.bash_in(owned, "git -C ../unrelated branch -D same-name")
            )
            self.assert_allowed(
                self.bash_in(owned, "git -C .. -C unrelated branch -D same-name")
            )
            self.assert_denied(
                self.bash_in(
                    parent,
                    f"cd {owned} ; (cd {unrelated}) ; git branch -D same-name",
                )
            )
            self.assert_denied(
                self.bash_in(
                    owned,
                    f"cd {unrelated} ; (cd {owned}) ; git branch -D same-name",
                )
            )
            self.assert_denied(
                self.bash_in(
                    owned,
                    f"cd {owned} ; true || cd {unrelated} ; git branch -D same-name",
                )
            )
            self.assert_denied(
                self.bash_in(
                    owned,
                    f"cd {owned} ; if false; then cd {unrelated}; fi; "
                    "git branch -D same-name",
                )
            )
            self.assert_denied(
                self.bash_in(
                    owned,
                    f"coproc cd {unrelated}; git branch -D same-name",
                )
            )
            for command in (
                f"eval 'cd {owned}'; git branch -D same-name",
                f"command cd {owned}; git branch -D same-name",
                f"builtin cd {owned}; git branch -D same-name",
            ):
                with self.subTest(command=command):
                    self.assert_denied(self.bash_in(unrelated, command))
            self.assert_denied(
                self.bash_in(
                    owned,
                    f"cd {owned} ; cd {unrelated} & wait; "
                    "git branch -D same-name",
                )
            )

    def test_git_c_uses_segment_pwd_oldpwd_and_unset_variables(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            owned = self.init_git_repo(parent / "owned")
            safe = self.init_git_repo(parent / "safe")
            owned_path = shlex.quote(owned.as_posix())
            safe_path = shlex.quote(safe.as_posix())
            for repo in (owned, safe):
                self.git(repo, "branch", "same-name")
            project = owned / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                "---\nphase: build\nbranch: same-name\n---\n", encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {"PWD": str(safe), "OLDPWD": str(safe), "W": str(safe)}):
                for root, command in (
                    (safe, f'cd {owned_path} && git -C "$PWD" branch -D same-name'),
                    (owned, f'cd {safe_path} && git -C "$OLDPWD" branch -D same-name'),
                    (owned, 'git -C "$PWD" branch -D same-name'),
                    (owned, 'unset W; git -C "$W" branch -D same-name'),
                ):
                    with self.subTest(root=root, command=command):
                        self.assert_denied(self.bash_in(root, command))
                for root, command in (
                    (owned, f'cd {safe_path} && git -C "$PWD" branch -D same-name'),
                    (safe, f'cd {owned_path} && git -C "$OLDPWD" branch -D same-name'),
                    (safe, 'git -C "$PWD" branch -D same-name'),
                    (safe, 'unset W; git -C "$W" branch -D same-name'),
                    (owned, f'W={safe_path}; git -C "$W" branch -D same-name'),
                    (owned, f'git -C {safe_path} branch -D same-name'),
                ):
                    with self.subTest(root=root, command=command):
                        self.assert_allowed(self.bash_in(root, command))
                self.assert_denied(
                    self.bash_in(safe, f"git -C {owned_path} branch -D same-name")
                )

    def test_git_c_literal_parameter_paths_fail_closed_for_scoped_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            safe = self.init_git_repo(Path(temporary) / "quote-safe")
            owned = self.init_git_repo(safe / "$PWD")
            for repo in (safe, owned):
                self.git(repo, "branch", "same-name")
            project = owned / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                "---\nphase: build\nbranch: same-name\n---\n", encoding="utf-8"
            )
            self.git(safe, "config", "alias.literal-path", '-C "$PWD" branch -D')
            with mock.patch.dict(os.environ, {"PWD": str(safe)}):
                for command in (
                    "git -C '$PWD' branch -D same-name",
                    "git '-C$PWD' branch -D same-name",
                    r"git -C \$PWD branch -D same-name",
                    r"git -C\$PWD branch -D same-name",
                    "W='$PWD'; git -C \"$W\" branch -D same-name",
                    "command git -C '$PWD' branch -D same-name",
                    "echo \"'\"; git -C '$PWD' branch -D same-name",
                    "git literal-path same-name",
                ):
                    with self.subTest(command=command):
                        self.assert_denied(self.bash_in(safe, command))
                for command in (
                    'git -C "$PWD" branch -D same-name',
                    f"git -C {shlex.quote(str(safe))} branch -D same-name",
                    f'W={shlex.quote(str(safe))}; git -C "$W" branch -D same-name',
                    "git -C '$PWD' status --short",
                ):
                    with self.subTest(command=command):
                        self.assert_allowed(self.bash_in(safe, command))

    def test_git_c_cmd_parameter_spellings_fail_closed_for_scoped_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            safe = self.init_git_repo(Path(temporary) / "syntax-safe")
            self.git(safe, "branch", "same-name")
            for spelling in ("%W%", "!W!"):
                owned = self.init_git_repo(safe / spelling)
                self.git(owned, "branch", "same-name")
                project = owned / ".project"
                project.mkdir()
                (project / "STATE.md").write_text(
                    "---\nphase: build\nbranch: same-name\n---\n", encoding="utf-8"
                )
                self.git(safe, "config", "alias.literal-cmd-path", f'-C "{spelling}" branch -D')
                with mock.patch.dict(os.environ, {"W": str(safe), "INDIRECT": spelling}):
                    for command in (
                        f"git -C {spelling} branch -D same-name",
                        f"git -C '{spelling}' branch -D same-name",
                        f'git "-C{spelling}" branch -D same-name',
                        f'P="{spelling}"; git -C "$P" branch -D same-name',
                        'git -C "$INDIRECT" branch -D same-name',
                        'P=$INDIRECT; git -C "$P" branch -D same-name',
                        f"command git -C '{spelling}' branch -D same-name",
                        "git literal-cmd-path same-name",
                    ):
                        with self.subTest(spelling=spelling, command=command):
                            self.assert_denied(self.bash_in(safe, command))
                    for command in (
                        f"git -C {shlex.quote(str(safe))} branch -D same-name",
                        'git -C "$W" branch -D same-name',
                        f'INDIRECT={shlex.quote(str(safe))}; git -C "$INDIRECT" branch -D same-name',
                        f"git -C '{spelling}' status --short",
                    ):
                        with self.subTest(spelling=spelling, command=command):
                            self.assert_allowed(self.bash_in(safe, command))

    def test_ownership_scoping_fails_closed_for_env_git_context_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            owned = self.init_git_repo(parent / "owned")
            unrelated = self.init_git_repo(parent / "unrelated")
            self.git(owned, "branch", "ordinary")
            self.git(unrelated, "branch", "ordinary")
            self.git(unrelated, "config", "alias.retire", "branch -D ordinary")
            project = owned / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                "---\nphase: build\nbranch: ordinary\n---\n", encoding="utf-8"
            )

            with mock.patch.dict(
                os.environ,
                {
                    "GIT_DIR": str(unrelated / ".git"),
                    "GIT_WORK_TREE": str(unrelated),
                },
            ):
                for command in (
                    "env -i git branch -D ordinary",
                    "env --ignore-environment git branch -D ordinary",
                    "env -u GIT_DIR -u GIT_WORK_TREE git branch -D ordinary",
                    "env --unset=GIT_DIR --unset GIT_WORK_TREE git branch -D ordinary",
                    "env -u HOME git branch -D ordinary",
                    "env --unset=XDG_CONFIG_HOME git branch -D ordinary",
                    "env -i git retire ordinary",
                ):
                    with self.subTest(command=command):
                        reason = guard_hook.command_denial(command, [str(owned)])
                        self.assertIsNotNone(reason)

    def test_env_config_unset_is_denied_before_alias_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owned = self.init_git_repo(root / "owned")
            self.git(owned, "branch", "ordinary")
            project = owned / ".project"
            tasks = project / "plan" / "tasks"
            tasks.mkdir(parents=True)
            (tasks / "T001.md").write_text(
                "---\ntask_branch: ordinary\nworktree: null\n---\n",
                encoding="utf-8",
            )
            home = root / "alias-home"
            home.mkdir()
            alias_config = home / ".gitconfig"
            alias_config.write_text(
                "[alias]\n\tretire2 = branch -D ordinary\n", encoding="utf-8"
            )
            empty_global = root / "empty-global"
            empty_global.write_text("", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {"HOME": str(home), "GIT_CONFIG_GLOBAL": str(empty_global)},
            ):
                self.assertIsNone(
                    guard_hook.git_alias("retire2", [], [str(owned)])
                )
                changed_environment = os.environ.copy()
                changed_environment.pop("GIT_CONFIG_GLOBAL")
                actual_alias = subprocess.run(
                    ["git", "config", "--get", "alias.retire2"],
                    cwd=owned,
                    env=changed_environment,
                    capture_output=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(0, actual_alias.returncode, actual_alias.stderr)
                self.assertEqual("branch -D ordinary", actual_alias.stdout.strip())
                reason = guard_hook.command_denial(
                    "env -u GIT_CONFIG_GLOBAL git retire2 ordinary", [str(owned)]
                )
                self.assertIsNotNone(reason)

    @requires_symlink
    def test_ownership_scoping_fails_closed_for_symlink_cd_and_cdpath(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            owned = self.init_git_repo(parent / "owned")
            unrelated = self.init_git_repo(parent / "unrelated")
            self.git(owned, "branch", "same-name")
            self.git(unrelated, "branch", "same-name")
            project = owned / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                "---\nphase: build\nbranch: same-name\n---\n", encoding="utf-8"
            )

            child = unrelated / "child"
            child.mkdir()
            (owned / "link").symlink_to(child, target_is_directory=True)
            self.assert_denied(
                self.bash_in(
                    parent,
                    f"cd {owned / 'link'}; cd ..; git branch -D same-name",
                )
            )

            (unrelated / "owned").mkdir()
            self.assert_denied(
                self.bash_in(
                    unrelated,
                    f"CDPATH={parent} cd owned; git branch -D same-name",
                )
            )

    def test_owned_delete_fails_closed_on_malformed_or_unreadable_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.init_git_repo(Path(temporary) / "repo")
            self.git(repo, "branch", "ordinary")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                "---\nbranch: ordinary\nbranch: other\n---\n", encoding="utf-8"
            )
            self.assert_denied(self.bash_in(repo, "git branch -D ordinary"))

        with tempfile.TemporaryDirectory() as temporary:
            repo = self.init_git_repo(Path(temporary) / "repo")
            self.git(repo, "branch", "ordinary")
            tasks = repo / ".project" / "plan" / "tasks"
            tasks.mkdir(parents=True)
            (tasks / "T001.md").write_text(
                "---\ntask_branch: ordinary\nworktree: null\n---\n",
                encoding="utf-8",
            )
            original_scandir = os.scandir

            def hide_task_directory(path):
                if Path(path) == tasks:
                    raise PermissionError("task directory is unreadable")
                return original_scandir(path)

            with mock.patch.object(guard_hook.os, "scandir", side_effect=hide_task_directory):
                self.assert_denied(self.bash_in(repo, "git branch -D ordinary"))

    def test_denies_powershell_archive_mutations(self):
        for command in (
            "Remove-Item -Recurse .project/archive/001-mvp",
            r"Move-Item README.md .project\archive\001-mvp\README.md",
            r"ls .Project\Archive && Copy-Item README.md .project\ARCHIVE\001-mvp\README.md",
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
            "sed -n 'w /tmp/side-effect' .project/archive/001-mvp/NOTE.md",
            "sed -n 's/a/b/e' .project/archive/001-mvp/NOTE.md",
            "sed -n 's/a/b/w /tmp/side-effect' .project/archive/001-mvp/NOTE.md",
            "sed -n '1{s/^/ /e}' .project/archive/001-mvp/NOTE.md",
            "readonly P=.project/archive/001-mvp; export P=/tmp; sed -i 's/a/b/' \"$P/NOTE.md\"",
            "python3 -c 'write()' .project/archive/001-mvp/NOTE.md",
            "cat .project/archive/001-mvp/NOTE.md > /tmp/note.md",
            "ls .project/archive/001-mvp && echo broken > .project/archive/001-mvp/NOTE.md",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_rejects_readonly_assignment_state_before_protected_write(self):
        self.assert_denied(
            self.bash(
                'readonly P=.project/STATE.md; export P=/tmp/NOTE.md; '
                'sed -i s/a/b/ "$P"'
            )
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
            'A=.pro; B=ject/ar; C=chive; rm -rf "$A$B$C"',
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
            "powershell -Command git reset --hard HEAD~1",
            "cmd /c 'git clean -fd'",
            "cmd /c git reset --hard HEAD~1",
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
            "printf '%s\\0' reset --hard HEAD~1 | xargs -0 git",
            "find . -maxdepth 0 -exec git reset --hard HEAD~1 \\;",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_allows_ordinary_commands_from_repository_root_containing_archive(self):
        # Seen live 2026-09-06: once .project/archive/ existed, the guard treated the
        # repository root as archive context and denied echo, unittest and the
        # archive helper itself. Containing an archive is not being inside one.
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary).resolve()
            (repository / ".project" / "archive" / "001-mvp").mkdir(parents=True)
            try:
                os.chdir(repository)
                for command in ("echo guard-probe", "python3 -m unittest", "python3 .gsd-path/archive_milestone.py render-manifest --repo " + str(repository)):
                    with self.subTest(command=command):
                        self.assert_allowed(
                            {
                                "tool_name": "Bash",
                                "tool_input": {"command": command},
                                "cwd": str(repository),
                            }
                        )
                self.assert_denied(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": "rm -rf .project", "cwd": str(repository)},
                    }
                )
            finally:
                os.chdir(previous)

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

    def test_denies_destructive_commands_on_archive_ancestors(self):
        commands = (
            "rm -rf .project", "rmdir .project", "unlink .project",
            "shred .project", "trash .project", "mv .project elsewhere",
            "rsync --delete elsewhere/ .project/",
            "Remove-Item -Recurse .project", "ri -Recurse .project",
            "del .project", "erase .project", "rd /s .project",
            "Move-Item .project elsewhere", "mi .project elsewhere",
            "move .project elsewhere", "rm.exe -rf .project",
            "find .project -delete", "find.exe .project -delete",
            "find .project -exec rm -rf {} +",
            r"find .project -execdir unlink {} \;",
            r"find .project -ok rmdir {} \;",
        )
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary).resolve()
            (repository / ".project" / "archive" / "001-mvp").mkdir(parents=True)
            for command in commands:
                with self.subTest(command=command):
                    self.assert_denied(
                        {
                            "tool_name": "Bash",
                            "tool_input": {"command": command},
                            "cwd": str(repository),
                        }
                    )
            self.assert_allowed(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "find .project -type f -print"},
                    "cwd": str(repository),
                }
            )

    def test_denies_expansion_in_destructive_operands(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary).resolve()
            (repository / ".project" / "archive" / "001-mvp").mkdir(parents=True)
            (repository / "scratch").mkdir()
            (repository / "scratch" / "disposable.txt").touch()
            root = shlex.quote(repository.as_posix())
            denied = (
                f'ROOT={root}; rm -rf "$ROOT"',
                f'ROOT={root}; ROOT=scratch rm -rf "$ROOT"',
                f"TARGET='scratch {repository.as_posix()}'; rm -rf $TARGET",
                'TARGET=scratch; rm -rf "$TARGET"',
                'rm -f scratch/*.txt',
                'rm -rf .project',
                'rm -rf "scratch"*',
                'rm -rf `echo scratch`',
                f'ROOT={root}; rm -rf "$ROOT"; ROOT=scratch',
                f'ROOT={root}; CHILD=$ROOT; rm -rf "$CHILD"',
                f'ROOT={root}; command rm -rf "$ROOT"',
                'rm -rf .proj*',
                'rm -rf .projec[t]',
                'TARGET=.proj*; rm -rf "$TARGET"',
                'Move-Item .proj* elsewhere',
                'find .proj* -delete',
                'rm -rf "$GUARD_UNKNOWN_TARGET"',
                'TARGET=$GUARD_UNKNOWN_TARGET; rm -rf "$TARGET"',
                'rm -rf "$(echo scratch)"',
                'rm -rf no-matches-*',
                'rm -rf **/.project',
                'rm -rf .{project,unused}',
                'rm -rf ~/x',
                'rm -rf ~root/x',
                'rm -rf "scratch folder"',
                'rm -rf "scratch;other"',
                'rm -rf ""',
                "Remove-Item -Recurse -Force '.proj*'",
                "Remove-Item -LiteralPath 'scratch/*'",
                "Move-Item 'scratch/?' elsewhere",
                'rm -f "scratch/*.txt"',
                "rm -f 'scratch/file?[x]'",
                'command rm -f "scratch/*.txt"',
                "sh -c 'rm -f \"scratch/*.txt\"'",
                r'rm -f scratch/\*.txt',
            )
            allowed = (
                'echo .proj*',
                f'ROOT={root}; echo "$ROOT"',
                'echo "$GUARD_UNKNOWN_TARGET"',
                'python3 -m unittest tests.test_guard*',
                f'ROOT={root}; python3 .gsd-path/archive_milestone.py render-manifest --repo "$ROOT"',
                'rm -rf scratch',
                'rm -rf ./scratch/old-file.txt',
                "rm -rf './scratch/old-file.txt'",
                'rm -rf scratch_123',
                'rm -rf "scratch"',
            )
            # Windows needs PATH (to find git) and SYSTEMROOT to start any process.
            kept = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT") if os.name == "nt" and name in os.environ}
            with mock.patch.dict(os.environ, kept, clear=True):
                for commands, assertion in ((denied, self.assert_denied), (allowed, self.assert_allowed)):
                    for command in commands:
                        with self.subTest(command=command):
                            assertion({
                                "tool_name": "Bash",
                                "tool_input": {"command": command},
                                "cwd": str(repository),
                            })

    def test_destructive_commands_require_a_single_simple_segment(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary).resolve() / "repo"
            (repository / ".project" / "archive" / "001-mvp").mkdir(parents=True)
            (repository / "scratch").mkdir()
            denied = (
                "(cd scratch); rm -rf .project",
                "cd missing; rm -rf .project",
                "echo ready; rm scratch",
                "true && rm scratch",
                "false || rm scratch",
                "echo ready | rm scratch",
                "echo ready\nrm scratch",
                "(rm scratch)",
                "echo $(rm scratch)",
                "sh -c 'cd scratch; rm old-file.txt'",
                f"cd rep*; cd {shlex.quote(str(repository))}; rm scratch",
                "cd ..; cd rep*; rm -rf .project",
                "cd ..; pushd rep*; mv scratch elsewhere",
                "cd ..; Set-Location rep*; Remove-Item -Recurse .project",
                "cd ..; chdir rep*; rm scratch",
                "cd ..; sl rep*; rm scratch",
                "cd rep*; cd child; rm scratch",
                "cd rep*; command rm scratch",
                "cd rep*; sh -c 'rm scratch'",
                "cd $TARGET; rm scratch",
                "cd ~/repo; rm scratch",
                "cd .{project,unused}; rm scratch",
            )
            allowed = (
                "cd ..; cd repo; python3 -m unittest",
                "cd ..; cd rep*; python3 -m unittest",
                "cd rep*; sh -c 'echo ready'",
                "rm scratch",
                "command rm scratch",
            )
            for command in denied:
                with self.subTest(archive_reason=command):
                    self.assertEqual(
                        guard_hook.command_denial(command, [str(repository)]),
                        guard_hook.DESTRUCTIVE_SHAPE_REASON,
                    )
            for commands, assertion in ((denied, self.assert_denied), (allowed, self.assert_allowed)):
                for command in commands:
                    with self.subTest(command=command):
                        assertion({
                            "tool_name": "Bash",
                            "tool_input": {"command": command},
                            "cwd": str(repository),
                        })

    def test_denies_protected_write_after_parameter_directory_change(self):
        self.assert_denied(self.bash("TARGET=.project; cd $TARGET; printf broken > STATE.md"))

    def test_denies_deleting_archive_ancestor_on_windows(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            (repository / ".project" / "archive" / "001-mvp").mkdir(parents=True)
            try:
                os.chdir(repository)
                self.assert_denied(
                    {
                        "tool_name": "PowerShell",
                        "tool_input": {
                            "command": "Remove-Item -Recurse .project",
                            "working_directory": str(repository),
                        },
                    }
                )
            finally:
                os.chdir(previous)

    def test_resolves_inherited_archive_parameters(self):
        for command in (
            'rm "$P/001-mvp/MANIFEST.md"',
            r'cmd.exe /c "del %P%\001-mvp\MANIFEST.md"',
            r'cmd.exe /V:ON /c "del !P!\001-mvp\MANIFEST.md"',
        ):
            with self.subTest(command=command), mock.patch.dict(
                os.environ, {"P": ".project/archive"}
            ):
                self.assert_denied(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                )

    def test_allows_inherited_non_archive_parameter(self):
        with mock.patch.dict(os.environ, {"TMPDIR": "/tmp"}):
            self.assert_allowed(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": 'mkdir "$TMPDIR/build"'},
                }
            )

    def test_allows_visible_non_archive_assignment(self):
        self.assert_allowed(
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'OUT=build; mkdir "$OUT/cache"'},
            }
        )

    def test_allows_reading_unresolved_path(self):
        self.assert_allowed(
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'cat "$P/001-mvp/MANIFEST.md"'},
            }
        )

    @requires_symlink
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

    def test_empty_working_directory_is_treated_as_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = shlex.quote(str(Path(temporary).resolve()))
            subprocess.run(["git", "init", "-q", temporary], check=True)
            for command, assertion in (
                (f"git -C {repository} status --short", self.assert_allowed),
                (f"git -C {repository} reset --hard HEAD~1", self.assert_denied),
            ):
                with self.subTest(command=command):
                    assertion({
                        "tool_name": "Shell",
                        "tool_input": {"command": command, "cwd": ""},
                        "cwd": "",
                    })

    def test_allows_safe_git_through_command_wrappers(self):
        for command in (
            "bash -lc 'git status'",
            "command git branch -d merged",
            "env -- git status",
            "git -c core.quotepath=false status",
            "find . -maxdepth 1 -type f",
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

    def bash(self, command):
        return {"tool_name": "Bash", "tool_input": {"command": command}}

    def test_allows_shell_constructs_that_touch_no_protected_path(self):
        for command in (
            "ls src\nls tests",
            "for f in src/*.py; do wc -l \"$f\"; done",
            "while read line; do echo \"$line\"; done < names.txt",
            "if [ -f setup.py ]; then python3 setup.py --version; fi",
            "export NODE_ENV=test && npm test",
            "set -euo pipefail; npm test",
            "unset DEBUG; npm test",
            "cat <<'EOF' > notes.txt\nrm -rf .project\nEOF",
            "python3 - <<EOF\nprint(1)\nEOF",
            'echo "$(date)"',
            "echo `git rev-parse HEAD`",
            "npm run $1",
            "find src -name '*.py' | xargs grep -l TODO",
            "find src -name '*.py' -exec grep -l TODO {} \\;",
            "ls src \\\n  tests",
            "command -v python3",
            "eval echo hello",
            "declare NAME=value",
        ):
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command))

    def test_allows_issue_327_read_only_shell_cases(self):
        repository = shlex.quote(str(Path.cwd()))
        for command in (
            "ls .project .project/archive && echo done",
            'IFS=\'|\' read a b <<<"$ev"',
            "python3 - <<'PY'\nvalue = \"`literal text`\"\nprint(value)\nPY",
            "D=/x; D=/y; python3 $D/a.py",
            "sed -i 's/…`a`$/…`b`/' notes.md",
        ):
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command))
        self.assert_allowed(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": f"cd {repository} && grep -c '^- \\*\\*Check\\*\\*' .project/review/final-gap-*.md",
                    "working_directory": ".project/archive/001-mvp",
                },
            }
        )

    def test_resolves_literal_assignment_for_git_c(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "target-repo"
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            command = f"W={shlex.quote(str(repository))}; git -C $W status --short"
            self.assert_allowed(self.bash(command))
            quoted = f"W={shlex.quote(str(repository))}; git -C \"$W\" status --short"
            self.assert_allowed(self.bash(quoted))
            exported = f"export W={shlex.quote(str(repository))}; git -C $W status --short"
            self.assert_allowed(self.bash(exported))
            for name in ("target repo", "target[name]"):
                literal_repository = Path(temporary) / name
                subprocess.run(["git", "init", "-q", str(literal_repository)], check=True)
                literal = f"git -C {shlex.quote(str(literal_repository))} status --short"
                self.assert_allowed(self.bash(literal))
            archive_cwd = Path(temporary) / ".project" / "archive" / "001-mvp"
            archive_cwd.mkdir(parents=True)
            self.assert_allowed(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": command,
                        "working_directory": str(archive_cwd),
                    },
                }
            )

    def test_denies_word_split_git_subcommands_from_variables(self):
        for command in (
            "G='reset --hard'; git $G HEAD~1",
            "G='clean -fd'; git $G",
            "G='restore .'; git $G",
            "W='/tmp/target repo'; git -C $W status --short",
            "W='/tmp/target[repo]'; git -C $W status --short",
        ):
            with self.subTest(command=command):
                self.assert_denied(self.bash(command))

    def test_assignment_state_is_segment_local_and_last_value_wins(self):
        self.assert_denied(
            self.bash('P=.project/archive; echo x > "$P/NOTE.md"; P=/tmp')
        )
        self.assert_allowed(
            self.bash('P=/tmp; echo x > "$P/NOTE.md"; P=.project/archive')
        )

    def test_conditional_and_subshell_assignments_do_not_change_archive_context(self):
        for command in (
            "P=.project/archive/001-mvp; false && P=/tmp; sed -i 's/a/b/' \"$P/NOTE.md\"",
            "P=.project/archive/001-mvp; true || P=/tmp; sed -i 's/a/b/' \"$P/NOTE.md\"",
            "P=.project/archive/001-mvp; (P=/tmp); sed -i 's/a/b/' \"$P/NOTE.md\"",
        ):
            with self.subTest(command=command):
                self.assert_denied(self.bash(command))

    def test_ignores_quoted_but_checks_expanded_heredoc_substitutions(self):
        self.assert_allowed(
            self.bash("python3 - <<'PY'\nvalue = `literal text`\nPY")
        )
        self.assert_denied(
            self.bash(
                "python3 - <<EOF\n$(rm -rf .project/archive/001-mvp)\nEOF"
            )
        )
        self.assert_denied(
            self.bash(
                "echo ok # <<'EOF'\n$(printf changed > .project/archive/001-test/OUT.md)\nEOF"
            )
        )
        self.assert_denied(self.bash("RT=$(cmd); cd $RT"))

    def test_denials_name_the_shell_construct(self):
        for command, construct in (
            ("cd $(mktemp -d) && ls", "cd target $(mktemp -d)"),
            ("source ./env.sh", "source runs the script file ./env.sh"),
            (". ./env.sh", ". runs the script file ./env.sh"),
            ("find . -exec rm {} \\;", "find -exec runs rm"),
            ("ls | xargs rm", "xargs runs rm"),
            ("export HOME=/tmp; git status", "HOME changes where Git reads"),
            ("git commit -m \"$(cat msg)\"", "git argument $(cat msg)"),
            ("echo x > \"$1\"", "write target $1"),
            ("cat <<EOF\nno terminator", "here-document EOF is not terminated"),
            ("echo 'unbalanced", "cannot be tokenized"),
            ("bash script.sh", "bash reads commands from a file"),
            ("echo $(ls", "command substitution $( is not closed"),
        ):
            with self.subTest(command=command):
                status, _, error = run_guard(self.bash(command))
                self.assertEqual(status, 2)
                self.assertIn(construct, error)

    def test_shell_constructs_still_cannot_reach_the_archive(self):
        for command in (
            "for f in .project/archive/001-mvp/*; do rm \"$f\"; done",
            "export P=.project/archive; rm -rf \"$P/001-mvp\"",
            "cat <<EOF > .project/archive/001-mvp/NOTE.md\nx\nEOF",
            "eval rm .project/archive/001-mvp/NOTE.md",
            "echo $(rm .project/archive/001-mvp/NOTE.md)",
            "ls | xargs -I{} cat .project/archive/{}",
        ):
            with self.subTest(command=command):
                self.assert_denied(self.bash(command))

    def test_denies_newly_covered_destructive_git_commands(self):
        for command, phrase in (
            ("git worktree remove --force .worktrees/t1", "worktree remove --force"),
            ("git worktree remove -f .worktrees/t1", "worktree remove --force"),
            ("git stash drop", "stash drop"),
            ("git stash clear", "stash clear"),
            ("git checkout -- .", "checkout -- ."),
            ("git checkout .", "checkout -- ."),
            ("git restore .", "restore ."),
            ("git restore --staged --worktree .", "restore ."),
            ("git branch -m old new", "branch -m"),
            ("git branch -M main", "branch -m"),
            ("git branch --move old new", "branch -m"),
        ):
            with self.subTest(command=command):
                status, _, error = run_guard(self.bash(command))
                self.assertEqual(status, 2)
                self.assertIn(phrase, error)
        for command in (
            "git worktree remove .worktrees/t1",
            "git stash list",
            "git stash push -m wip",
            "git restore --staged .",
            "git checkout -- app.py",
            "git branch -d merged-branch",
        ):
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command))

    def test_denies_shell_writes_to_protected_control_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            (root / ".project" / "next").mkdir(parents=True)
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            (root / ".gsd-path").mkdir()
            with (
                mock.patch.object(guard_hook.os, "getcwd", return_value=str(root)),
                mock.patch.object(guard_hook, "repository_root", return_value=root),
                mock.patch.object(guard_hook, "repository_control_roots", return_value=[]),
            ):
                for command, path in (
                    ("echo phase: build > .project/STATE.md", ".project/STATE.md"),
                    ("echo x >> .project/next/STATE.md", ".project/next/STATE.md"),
                    ("echo x | tee .project/next/STATE.md", ".project/next/STATE.md"),
                    ("sed -i 's/plan/build/' .project/STATE.md", ".project/STATE.md"),
                    ("perl -pi -e 's/a/b/' .project/STATE.md", ".project/STATE.md"),
                    ("cp STATE.md .project/STATE.md", ".project/STATE.md"),
                    ("rm -rf .project", ".project"),
                    ("touch .gsd-path/guard_hook.py", ".gsd-path/guard_hook.py"),
                    ("bash -c 'echo x > .project/STATE.md'", ".project/STATE.md"),
                    ("cat <<EOF > .project/STATE.md\nphase: build\nEOF", ".project/STATE.md"),
                ):
                    with self.subTest(command=command):
                        status, _, error = run_guard(self.bash(command))
                        self.assertEqual(status, 2)
                        self.assertIn("shell command writes " + path, error)
                status, _, error = run_guard(self.bash("cd .project && rm STATE.md"))
                self.assertEqual(status, 2)
                self.assertIn(guard_hook.DESTRUCTIVE_SHAPE_REASON, error)
                for command in (
                    "echo x > build.log",
                    "echo x > .project/plan/PLAN.md",
                    "cat .project/STATE.md",
                    "echo x 2>&1",
                    "echo x >&2",
                    "sed -n 1p .project/STATE.md",
                ):
                    with self.subTest(command=command):
                        self.assert_allowed(self.bash(command))

    def test_shell_writes_are_ungated_without_pipeline_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            with mock.patch.object(guard_hook, "repository_root", return_value=root):
                self.assert_allowed(self.bash("echo x > .project/STATE.md"))

    def test_control_file_denial_names_the_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            (root / ".project").mkdir(parents=True)
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with mock.patch.object(guard_hook, "repository_root", return_value=root):
                status, _, error = run_guard(
                    {"tool_name": "Write", "tool_input": {"file_path": ".project/STATE.md"}}
                )
                self.assertEqual(status, 2)
                self.assertIn("pipeline_state.py", error)
                self.assertIn(".project/STATE.md", error)

    def test_subprocess_contract_end_to_end(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(
                {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}
            ),
            capture_output=True,
            encoding="utf-8", errors="replace",
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
            encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
