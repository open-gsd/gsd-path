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
import status_runtime

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

    def test_plain_prompt_denies_product_write_outside_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_text(
                "owned\n", encoding="utf-8"
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            (root / ".project" / "STATE.md").write_text(
                "owned\n", encoding="utf-8"
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            (root / ".project" / "STATE.md").write_text(
                "owned\n", encoding="utf-8"
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            (root / ".project" / "STATE.md").write_text(
                "owned\n", encoding="utf-8"
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
            (root / ".project" / "STATE.md").write_text(
                "owned\n", encoding="utf-8"
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

    def test_plain_prompt_denies_pipeline_control_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            outside = Path(temporary) / "outside"
            outside.mkdir()
            (root / ".gsd-path").symlink_to(outside, target_is_directory=True)
            (root / ".project").mkdir()
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
                    (root / "src" / "app.py").write_text("app\n", encoding="utf-8")
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
            (primary / ".project" / "STATE.md").write_text(
                "owned\n", encoding="utf-8"
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
                    text=True,
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
            (root / ".project" / "STATE.md").write_text(
                "owned\n", encoding="utf-8"
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
            (root / ".project" / "STATE.md").write_text(
                "owned\n", encoding="utf-8"
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
            (root / ".project" / "STATE.md").write_text(
                "owned\n", encoding="utf-8"
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            for name in (
                "pipeline_state.py",
                "check_handoffs.py",
                "isolation.py",
                "discussion_records.py",
                "pipeline_git.py",
                "archive_milestone.py",
                "review_panel.py",
                "_common.py",
                "state_checkpoint.py",
                "state_promote.py",
                "discussion_validate.py",
                "integration.py",
            ):
                shutil.copy2(scripts / name, runtime / name)
            state = root / ".project" / "STATE.md"
            state.parent.mkdir()
            state.write_text(
                "---\n"
                "pipeline: gsd-path/v2\n"
                "project: demo\n"
                "milestone: demo\n"
                "phase: plan\n"
                "status: done\n"
                "branch: null\n"
                "archive: null\n"
                "---\n",
                encoding="utf-8",
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
                text=True,
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
            runtime.write_text("old runtime\n", encoding="utf-8")
            calls = []

            def exec_runtime(command, **options):
                calls.append((command, options))
                if len(calls) == 1:
                    runtime.unlink()
                    runtime.write_text("new runtime with a new inode\n", encoding="utf-8")
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
            runtime.write_text("runtime\n", encoding="utf-8")
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
            owner_path.write_text(
                json.dumps(
                    {
                        "schema": status_runtime.INSTALL_LOCK_SCHEMA,
                        "pid": os.getpid(),
                        "identity": status_runtime.process_identity(os.getpid()),
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(status_runtime.install_lock_active(lock))
            finished = subprocess.Popen([sys.executable, "-c", "pass"])
            finished.wait()
            owner_path.write_text(
                json.dumps(
                    {
                        "schema": status_runtime.INSTALL_LOCK_SCHEMA,
                        "pid": finished.pid,
                        "identity": "expired",
                    }
                ),
                encoding="utf-8",
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
            (lock / status_runtime.INSTALL_LOCK_OWNER).write_text(
                json.dumps(
                    {
                        "schema": status_runtime.INSTALL_LOCK_SCHEMA,
                        "pid": os.getpid(),
                        "identity": "temporarily unavailable",
                    }
                ),
                encoding="utf-8",
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            (root / ".project" / "STATE.md").write_text(
                "owned\n", encoding="utf-8"
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
            (root / ".project" / "STATE.md").write_text(
                "owned\n", encoding="utf-8"
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
            (root / ".project" / "STATE.md").write_text("invalid\n", encoding="utf-8")
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

    @unittest.skipUnless(os.name == "nt", "requires native Windows paths")
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

    def test_denials_name_the_shell_construct(self):
        for command, construct in (
            ("source ./env.sh", "source runs the script file ./env.sh"),
            (". ./env.sh", ". runs the script file ./env.sh"),
            ("find . -exec rm {} \\;", "find -exec runs rm"),
            ("ls | xargs rm", "xargs runs rm"),
            ("export HOME=/tmp; git status", "HOME changes where Git reads"),
            ("git commit -m \"$(cat msg)\"", "git argument $(cat msg)"),
            ("cd $(mktemp -d) && ls", "cd target $(mktemp -d)"),
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
            (root / ".gsd-path").mkdir()
            with (
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
                    ("cd .project && rm STATE.md", "STATE.md"),
                    ("bash -c 'echo x > .project/STATE.md'", ".project/STATE.md"),
                    ("cat <<EOF > .project/STATE.md\nphase: build\nEOF", ".project/STATE.md"),
                ):
                    with self.subTest(command=command):
                        status, _, error = run_guard(self.bash(command))
                        self.assertEqual(status, 2)
                        self.assertIn("shell command writes " + path, error)
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
            (root / ".project" / "STATE.md").write_text("owned\n", encoding="utf-8")
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
