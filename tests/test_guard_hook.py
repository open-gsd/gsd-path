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
from tests._platform import posix_only, requires_symlink

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "guard_hook.py"

# The stable launcher surface as it shipped before #468: no successor walk.
PRE_SUCCESSOR_LAUNCHER = """\
import hashlib
import json
import stat
import sys
from pathlib import Path

RUNTIME_SCHEMA = "gsd-path/runtime/v1"


def runtime_home():
    return Path.home() / ".gsd-path" / "runtimes"


def declaration(repo):
    path = repo / ".gsd-path" / "runtime.json"
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError(f"unsafe runtime declaration: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema") != RUNTIME_SCHEMA
            or not isinstance(data.get("version"), str)
            or not isinstance(data.get("digest"), str)
            or len(data["digest"]) != 64
            or any(c not in "0123456789abcdef" for c in data["digest"])):
        raise ValueError(f"invalid runtime declaration: {path}")
    return data


def manifest_digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_runtime(data):
    root = runtime_home() / data["digest"]
    try:
        if any(p.is_symlink() for p in (root, root.parent, root.parent.parent)):
            raise ValueError("symlinked runtime storage")
        manifest_path = root / "manifest.json"
        if manifest_path.is_symlink():
            raise ValueError("symlinked manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (not isinstance(manifest, dict) or manifest_digest(manifest) != data["digest"]
                or manifest.get("version") != data["version"]):
            raise ValueError("manifest identity mismatch")
        files = manifest.get("files")
        if not isinstance(files, dict) or "pipeline_state.py" not in files:
            raise ValueError("invalid runtime file inventory")
        for name, expected in files.items():
            if Path(name).name != name or not name.endswith(".py"):
                raise ValueError("invalid runtime file name")
            path = root / name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"runtime file changed: {name}")
        runtime_entries = set()
        for path in root.iterdir():
            if path.name == "__pycache__":
                if not stat.S_ISDIR(path.lstat().st_mode):
                    raise ValueError("unexpected runtime files")
                for cached in path.iterdir():
                    if cached.suffix != ".pyc" or not stat.S_ISREG(cached.lstat().st_mode):
                        raise ValueError("unexpected runtime files")
                continue
            runtime_entries.add(path.name)
        if runtime_entries != set(files) | {"manifest.json"}:
            raise ValueError("unexpected runtime files")
    except (OSError, ValueError, TypeError) as error:
        raise ValueError(f"runtime {data['digest']} is unavailable or invalid ({error})") from error
    return root


def resolve_runtime(repo):
    return validate_runtime(declaration(repo))


def run_guard(repo, name):
    root = resolve_runtime(repo)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    previous_pycache_prefix = sys.pycache_prefix
    sys.pycache_prefix = str(root / "manifest.json")
    try:
        code = compile((root / name).read_bytes(), str(root / name), "exec")
        exec(code, {"__name__": "__main__", "__file__": str(repo / ".gsd-path" / name)})
    finally:
        sys.pycache_prefix = previous_pycache_prefix
"""


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

    def assert_denied_with(self, payload, reason):
        status, _output, error = run_guard(payload)
        self.assertEqual(status, 2, error)
        self.assertIn(reason, error)

    def scoped_cleanup_fixture(self, root, state=None):
        """A repository with an ordinary and a Path-owned branch and worktree."""
        repo = self.init_git_repo(root / "repo")
        self.git(repo, "branch", "feature/x")
        self.git(repo, "branch", "gsd-path/M001")
        self.git(repo, "worktree", "add", "-q", "-b", "plain", str(root / "plain-worktree"))
        self.git(
            repo, "worktree", "add", "-q", "-b", "gsd-path-task/T001",
            str(root / "task-worktree"),
        )
        if state is not None:
            (repo / ".project").mkdir()
            (repo / ".project" / "STATE.md").write_text(state, encoding="utf-8")
        return repo

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
                self.bash_in(repo, f"git worktree remove --force {shlex.quote(str(task_worktree))}")
            )

            managed = root / "managed-task"
            self.git(repo, "worktree", "add", "-q", "-b", "gsd-path-task/T002", str(managed))
            self.assert_denied(
                self.bash_in(repo, f"git worktree remove -f -- {shlex.quote(str(managed))}")
            )

    def test_ownership_scope_uses_cd_and_git_c_repository_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
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
                    # A parameter is denied also when it names the safe repository:
                    # the shell can change it in ways the guard does not track.
                    (owned, f'cd {safe_path} && git -C "$PWD" branch -D same-name'),
                    (safe, f'cd {owned_path} && git -C "$OLDPWD" branch -D same-name'),
                    (safe, 'git -C "$PWD" branch -D same-name'),
                    (safe, 'unset W; git -C "$W" branch -D same-name'),
                    (owned, f'W={safe_path}; git -C "$W" branch -D same-name'),
                ):
                    with self.subTest(root=root, command=command):
                        self.assert_denied(self.bash_in(root, command))
                self.assert_allowed(
                    self.bash_in(owned, f"git -C {safe_path} branch -D same-name")
                )
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
                    'git -C "$PWD" branch -D same-name',
                    f'W={shlex.quote(str(safe))}; git -C "$W" branch -D same-name',
                ):
                    with self.subTest(command=command):
                        self.assert_denied(self.bash_in(safe, command))
                for command in (
                    f"git -C {shlex.quote(str(safe))} branch -D same-name",
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
                        'git -C "$W" branch -D same-name',
                        f'INDIRECT={shlex.quote(str(safe))}; git -C "$INDIRECT" branch -D same-name',
                    ):
                        with self.subTest(spelling=spelling, command=command):
                            self.assert_denied(self.bash_in(safe, command))
                    for command in (
                        f"git -C {shlex.quote(str(safe))} branch -D same-name",
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

    def test_scoped_cleanup_keeps_ordinary_git_and_path_owned_results(self):
        for label, state in (
            ("no-state", None),
            ("active", "---\nphase: build\nbranch: gsd-path/M001\n---\n"),
            ("shipped", "---\nphase: shipped\nbranch: gsd-path/M001\n---\n"),
        ):
            with self.subTest(state=label), tempfile.TemporaryDirectory() as temporary:
                repo = self.scoped_cleanup_fixture(Path(temporary).resolve(), state)
                for command in (
                    "git status",
                    "git log --oneline -1",
                    "git commit -m message",
                    "git push origin feature/x",
                    "git branch -D feature/x",
                    "git update-ref -d refs/heads/feature/x",
                    "git worktree remove --force ../plain-worktree",
                ):
                    with self.subTest(command=command):
                        self.assert_allowed(self.bash_in(repo, command))
                for command, rule in (
                    ("git branch -D gsd-path/M001", "branch"),
                    ("git branch -D gsd-path-task/T001", "branch"),
                    ("git update-ref -d refs/heads/gsd-path/M001", "update-ref"),
                    ("git worktree remove --force ../task-worktree", "worktree"),
                    ("git reset --hard HEAD", "reset"),
                    ("git push --force origin feature/x", "push"),
                ):
                    with self.subTest(command=command):
                        self.assert_denied_with(
                            self.bash_in(repo, command), guard_hook.GIT_REASONS[rule]
                        )

    def test_env_wrapper_denies_only_scoped_deletions_and_possible_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.scoped_cleanup_fixture(Path(temporary).resolve())
            self.git(repo, "config", "alias.retire", "branch -D")
            for command in (
                "env -u HOME git status",
                "env -i git log --oneline -1",
                "env -u HOME git commit -m message",
                "env --unset=XDG_CONFIG_HOME git push origin feature/x",
                "env -i git branch --show-current",
                "env -i git worktree list",
            ):
                with self.subTest(command=command):
                    self.assert_allowed(self.bash_in(repo, command))
            self.assert_denied_with(
                self.bash_in(repo, "env -i git reset --hard HEAD"),
                guard_hook.GIT_REASONS["reset"],
            )
            for command in (
                "env -u HOME git branch -D feature/x",
                "env -u HOME git branch -D gsd-path/M001",
                "env -i git update-ref -d refs/heads/feature/x",
                "env -i git worktree remove --force ../plain-worktree",
                "env -i git retire feature/x",
                "env -u HOME git not-a-git-command",
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(
                        self.bash_in(repo, command),
                        guard_hook.GIT_REASONS["git-environment"],
                    )

    def test_scoped_deletion_does_not_read_a_plain_redirection_as_a_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.scoped_cleanup_fixture(Path(temporary).resolve())
            redirections = (
                "2>/dev/null", "2> /dev/null", ">/dev/null", ">/dev/null 2>&1",
                "&>/dev/null", ">> out.log", "< /dev/null", "2>&1 | tail -1",
            )
            for delete, owned, rule in (
                ("git branch -D feature/x", "git branch -D gsd-path/M001", "branch"),
                (
                    "git update-ref -d refs/heads/feature/x",
                    "git update-ref -d refs/heads/gsd-path/M001",
                    "update-ref",
                ),
                (
                    "git worktree remove --force ../plain-worktree",
                    "git worktree remove --force ../task-worktree",
                    "worktree",
                ),
            ):
                for redirection in redirections:
                    with self.subTest(command=delete, redirection=redirection):
                        self.assert_allowed(
                            self.bash_in(repo, f"{delete} {redirection}")
                        )
                        self.assert_denied_with(
                            self.bash_in(repo, f"{owned} {redirection}"),
                            guard_hook.GIT_REASONS[rule],
                        )
            self.assert_allowed(
                self.bash_in(repo, "git branch -D 2>/dev/null feature/x")
            )
            self.assert_denied_with(
                self.bash_in(repo, "git branch -D feature/x 2>/dev/null gsd-path/M001"),
                guard_hook.GIT_REASONS["branch"],
            )
            unresolved = guard_hook.GIT_REASONS["unresolved-target"].format(
                action="git branch -D"
            )
            for command in (
                "git branch -D feature/x < <(cat README.md)",
                "git branch -D feature/x <<EOF\ntext\nEOF",
                "git branch -D feature/x <<< text",
                "git branch -D feature/x > out*",
                "git branch -D feature/x 2 >/dev/null",
                "git branch -D feature/x # cleanup",
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(self.bash_in(repo, command), unresolved)
            self.assert_denied(self.bash_in(repo, 'git branch -D feature/x > "$OUT"'))

    def test_redirection_at_each_position_does_not_hide_a_destructive_git_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.scoped_cleanup_fixture(Path(temporary).resolve())
            for owned, plain, rule in (
                (
                    "git 2>/dev/null branch -D gsd-path/M001",
                    "git 2>/dev/null branch -D feature/x",
                    "branch",
                ),
                (
                    "2>/dev/null git branch -D gsd-path/M001",
                    "2>/dev/null git branch -D feature/x",
                    "branch",
                ),
                (
                    ">/dev/null command git branch -D gsd-path/M001",
                    ">/dev/null command git branch -D feature/x",
                    "branch",
                ),
                (
                    "git worktree 2>/dev/null remove --force ../task-worktree",
                    "git worktree 2>/dev/null remove --force ../plain-worktree",
                    "worktree",
                ),
                (
                    "git update-ref >/dev/null -d refs/heads/gsd-path/M001",
                    "git update-ref >/dev/null -d refs/heads/feature/x",
                    "update-ref",
                ),
                (
                    "git update-ref >/dev/null refs/heads/gsd-path/M001 " + "0" * 40,
                    "git update-ref >/dev/null refs/heads/feature/x " + "0" * 40,
                    "update-ref",
                ),
            ):
                with self.subTest(command=owned):
                    self.assert_denied_with(
                        self.bash_in(repo, owned), guard_hook.GIT_REASONS[rule]
                    )
                    self.assert_allowed(self.bash_in(repo, plain))
            for command, rule in (
                ("git push --force 2>/dev/null origin feature/x", "push"),
                ("git 2>/dev/null push --force origin feature/x", "push"),
                ("git reset 2>/dev/null --hard", "reset"),
                ("2>/dev/null git reset --hard", "reset"),
                ("git clean >/dev/null -fd", "clean"),
                ("git stash 2>/dev/null drop", "stash"),
                ("git checkout >/dev/null -- .", "checkout"),
                ("git branch 2>/dev/null -m old new", "branch-move"),
                ("git reset <<< text --hard", "reset"),
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(
                        self.bash_in(repo, command), guard_hook.GIT_REASONS[rule]
                    )
            self.assert_denied_with(
                self.bash_in(repo, "git <<< text branch -D feature/x"),
                guard_hook.GIT_REASONS["unresolved-target"].format(
                    action="git branch -D"
                ),
            )
            self.assert_denied_with(
                self.bash_in(repo, "2>/dev/null env -i git branch -D feature/x"),
                guard_hook.GIT_REASONS["git-environment"],
            )
            self.assert_allowed(self.bash_in(repo, "git 2>/dev/null status"))

    def test_redirection_joined_to_a_separator_or_word_does_not_hide_git(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.scoped_cleanup_fixture(Path(temporary).resolve())
            joins = (
                "true;>/dev/null {}",
                "true &&>/dev/null {}",
                "true ||>/dev/null {}",
                "true|>/dev/null {}",
                "(>/dev/null {})",
                "true\n>/dev/null {}",
                "true;</dev/null {}",
                "(true)>/dev/null;>/dev/null {}",
            )
            for join in joins:
                for command, rule in (
                    ("git branch -D gsd-path/M001", "branch"),
                    ("git update-ref -d refs/heads/gsd-path/M001", "update-ref"),
                    ("git push --force origin feature/x", "push"),
                    ("git reset --hard", "reset"),
                    ("git clean -fd", "clean"),
                    ("git stash drop", "stash"),
                    ("git checkout -- .", "checkout"),
                    ("git branch -m old new", "branch-move"),
                ):
                    with self.subTest(join=join, command=command):
                        self.assert_denied(self.bash_in(repo, join.format(command)))
                with self.subTest(join=join):
                    self.assert_denied(
                        self.bash_in(
                            repo,
                            join.format("git worktree remove --force ../task-worktree"),
                        )
                    )
                    self.assert_allowed(self.bash_in(repo, join.format("git status")))
            for join in ("true;>/dev/null {}", "true\n>/dev/null {}"):
                with self.subTest(join=join):
                    self.assert_denied_with(
                        self.bash_in(repo, join.format("git branch -D gsd-path/M001")),
                        guard_hook.GIT_REASONS["branch"],
                    )
                    self.assert_allowed(
                        self.bash_in(repo, join.format("git branch -D feature/x"))
                    )
            for command in (
                "git 10>/dev/null branch -D gsd-path/M001",
                "git {fd}>/dev/null branch -D gsd-path/M001",
                "git 10>/dev/null push --force origin feature/x",
                "git update-ref refs/heads/gsd-path/M001 00>/dev/null",
                "command git 10>/dev/null reset --hard",
                "git branch -D feature/x 10>/dev/null",
                "git update-ref -d refs/heads/feature/x {fd}>/dev/null",
                "echo a\\\\;>/dev/null git branch -D gsd-path/M001",
                "echo a\\\\&&>/dev/null git reset --hard",
                "echo a\\\\;>/dev/null git push --force origin feature/x",
                "echo a\\\\;>/dev/null git worktree remove --force ../task-worktree",
                "echo a\\\\\n>/dev/null git clean -fd",
                "cat <(git push --force origin feature/x)",
                "cat <(git branch -D gsd-path/M001)",
                "tee >(git reset --hard)",
                "git diff <(git stash drop) <(git clean -fd)",
                "cat <(cat <(git update-ref -d refs/heads/gsd-path/M001))",
                "git branch <(echo) -D gsd-path/M001",
                "git branch <(echo) -D feature/x",
                "git reset <(echo) --hard",
                "git push <(echo) --force origin feature/x",
                "git clean <(echo) -fd",
                "git stash <(echo) drop",
                "git checkout <(echo) -- .",
                "git branch <(echo) -m old new",
                "git update-ref <(echo) -d refs/heads/gsd-path/M001",
                "git worktree remove <(echo) --force ../task-worktree",
                "git reset <(cat <(echo)) >(cat) --hard",
                "(git reset <(echo)) && git reset <(echo a; echo b) --hard",
            ):
                with self.subTest(command=command):
                    self.assert_denied(self.bash_in(repo, command))
            for command in (
                "git status 10>/dev/null; git update-ref -d refs/heads/feature/x",
                "cat <(git status); git update-ref -d refs/heads/feature/x",
                "cat <(cat <(git status)); git update-ref -d refs/heads/feature/x",
                "make 10>/dev/null <(git status); git update-ref -d refs/heads/feature/x",
                "cat <(case x in x) git status;; esac); "
                "git update-ref -d refs/heads/feature/x",
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(
                        self.bash_in(repo, command),
                        guard_hook.GIT_REASONS["update-ref-order"],
                    )
            for command in (
                "git log -n 10 >/dev/null",
                "git branch -D feature/x &>/dev/null",
                "git status 2>&1 | tail -1",
                "exec 3>/dev/null",
                "exec {fd}>/dev/null",
                "exec {lock}>/dev/null; make test",
                "exec 10>/dev/null",
                "command make test 10>/dev/null",
                "bash -c 'make test' 10>/dev/null",
                "echo hi 10>/dev/null",
                "make {fd}>/dev/null",
                "cat <<EOF\ntext\nEOF",
                "make 2>&1 | tee /dev/null",
                "git status 10>/dev/null",
                "git log --oneline -1 {fd}>/dev/null",
                "echo a\\\\;>/dev/null git status",
                "echo a\\\\;>/dev/null git branch -D feature/x",
                "cat <(git log --oneline -1)",
                "git diff <(git show HEAD) <(git show HEAD)",
                "diff <(echo a) <(echo b)",
                "diff <(echo a) <(echo b); git branch -D feature/x",
                "git log <(echo) --oneline -1",
                "make 10>/dev/null; git update-ref -d refs/heads/feature/x",
                "diff <(echo a) <(echo b); git update-ref -d refs/heads/feature/x",
            ):
                with self.subTest(command=command):
                    self.assert_allowed(self.bash_in(repo, command))

    def test_destructive_git_in_a_case_body_of_a_process_substitution_is_denied(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.scoped_cleanup_fixture(Path(temporary).resolve())
            for command, rule in (
                ("git branch -D gsd-path/M001", "branch"),
                ("git branch -D gsd-path-task/T001", "branch"),
                ("git update-ref -d refs/heads/gsd-path/M001", "update-ref"),
                ("git worktree remove --force ../task-worktree", "worktree"),
                ("git reset --hard HEAD", "reset"),
                ("git push --force origin feature/x", "push"),
                ("git clean -fd", "clean"),
                ("git stash drop", "stash"),
                ("git checkout -- .", "checkout"),
                ("git branch -m old new", "branch-move"),
            ):
                for wrap in (
                    "cat <(case x in x) {};; esac)",
                    "cat <(cat <(case x in x) {};; esac))",
                    "cat <(echo) <(case x in x) {};; esac",
                ):
                    with self.subTest(command=command, wrap=wrap):
                        self.assert_denied_with(
                            self.bash_in(repo, wrap.format(command)),
                            guard_hook.GIT_REASONS[rule],
                        )
            for command in (
                "cat <(case x in x) git status;; esac)",
                "cat <(case x in x) git branch -D feature/x;; esac)",
                "cat <(case x in x) echo hi;; esac)",
            ):
                with self.subTest(command=command):
                    self.assert_allowed(self.bash_in(repo, command))

    def test_git_alias_words_are_arguments_and_never_redirections(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.scoped_cleanup_fixture(Path(temporary).resolve())
            self.git(repo, "config", "alias.del", "branch -D > gsd-path/M001")
            self.git(repo, "config", "alias.unref", "update-ref -d > refs/heads/gsd-path/M001")
            self.git(repo, "config", "alias.retire", "branch -D")
            for command in (
                "git del feature/x",
                "git del feature/x 2>/dev/null",
                "git unref refs/heads/feature/x",
            ):
                with self.subTest(command=command):
                    self.assert_denied(self.bash_in(repo, command))
            self.assert_allowed(self.bash_in(repo, "git retire feature/x"))
            self.assert_allowed(self.bash_in(repo, "git retire feature/x 2>/dev/null"))
            self.assert_denied_with(
                self.bash_in(repo, "git retire gsd-path/M001 2>/dev/null"),
                guard_hook.GIT_REASONS["branch"],
            )
            # What the guard denies: Git gives the alias words to branch -D.
            subprocess.run(["git", "del", "feature/x"], cwd=repo, capture_output=True)
            branches = self.git(repo, "branch", "--format=%(refname:short)").stdout.split()
            self.assertNotIn("gsd-path/M001", branches)

    def test_git_context_name_counts_only_where_a_command_sets_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.scoped_cleanup_fixture(Path(temporary).resolve())
            self.git(repo, "config", "alias.lg", "log --oneline")
            for command in (
                "git lg HOME",
                "echo HOME; git lg",
                "echo GIT_DIR XDG_CONFIG_HOME; git lg",
                "grep GIT_DIR README.md; git lg",
                "printf HOME; git lg",
                "echo HOME && git branch -D feature/x",
                "for d in HOME GIT_DIR; do git lg; done",
                "read x <<< HOME; git lg",
                "read -r line < HOME; git lg",
                "echo read HOME; git lg",
                "git lg -- read HOME",
                "printf -v x HOME; git lg",
                "printf -vx HOME; git lg",
            ):
                with self.subTest(command=command):
                    self.assert_allowed(self.bash_in(repo, command))
            for command in (
                "read HOME; git lg",
                "read -r GIT_DIR <<< .git; git lg",
                "while read XDG_CONFIG_HOME; do git lg; done",
                "printf -v HOME %s /tmp; git lg",
                "for GIT_DIR in .git; do git lg; done",
                "getopts a HOME; git lg",
                "print -v HOME /tmp; git lg",
                "printf -vHOME %s /tmp; git lg",
                "printf -vGIT_DIR %s .git; git lg",
                "select GIT_DIR in .git; do git lg; done",
                "read -r x HOME < README.md; git lg",
                "< README.md read HOME; git lg",
                "command read HOME; git lg",
                "IFS= read -r GIT_DIR; git lg",
                "true && read HOME; git branch -D feature/x",
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(
                        self.bash_in(repo, command),
                        guard_hook.GIT_REASONS["git-environment"],
                    )
            for command in ("export GIT_DIR", "unset HOME", "local XDG_CONFIG_HOME"):
                with self.subTest(command=command):
                    self.assert_denied(
                        self.bash_in(repo, f"{command}; git branch -D feature/x")
                    )

    def test_built_in_git_runs_in_a_directory_that_does_not_exist_yet(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo = self.scoped_cleanup_fixture(root)
            self.git(repo, "config", "alias.retire", "branch -D")
            for command in (
                "mkdir new && cd new && git init",
                "mkdir new && cd new && git status",
                "git init fresh && cd fresh && git commit --allow-empty -m initial",
            ):
                with self.subTest(command=command):
                    self.assert_allowed(self.bash_in(repo, command))
            self.assert_allowed(self.bash_in(root / "absent", "git status"))
            self.assert_denied_with(
                self.bash_in(root / "absent", "git branch -D gsd-path/M001"),
                "git target repository cannot be resolved",
            )
            self.assert_denied_with(
                self.bash_in(repo, "mkdir new && cd new && git reset --hard HEAD"),
                guard_hook.GIT_REASONS["reset"],
            )
            self.assert_denied_with(
                self.bash_in(repo, "mkdir new && cd new && git retire feature/x"),
                "git alias configuration cannot be validated",
            )
            for command in ("mkdir new && cd new && git STATUS", "env -i git STATUS"):
                with self.subTest(command=command):
                    self.assert_denied(self.bash_in(repo, command))
            for target in ("feature/x", "gsd-path/M001"):
                with self.subTest(target=target):
                    self.assert_denied_with(
                        self.bash_in(repo, f"mkdir new && cd new && git branch -D {target}"),
                        guard_hook.GIT_REASONS["unresolved-target"].format(
                            action="git branch -D"
                        ),
                    )

    def test_ordinary_git_commands_are_not_possible_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.scoped_cleanup_fixture(Path(temporary).resolve())
            clone = "git clone https://example.invalid/r.git r && cd r && "
            for command in (
                clone + "git submodule update --init",
                clone + "env -u HOME git submodule update --init",
                "env -u HOME git submodule update --init",
                "mkdir new && cd new && git mergetool",
                "env -i git count-objects -v",
                "mkdir n && cd n && git init && git commit -m Commit",
                "env -i git commit -m Commit",
                "env -i git log STATUS",
            ):
                with self.subTest(command=command):
                    self.assert_allowed(self.bash_in(repo, command))

    def test_gsd_path_text_in_a_path_does_not_make_a_worktree_path_owned(self):
        for label, state in (
            ("no-state", None),
            ("active", "---\nphase: build\nbranch: gsd-path/M001\n---\n"),
            ("shipped", "---\nphase: shipped\nbranch: gsd-path/M001\n---\n"),
        ):
            with self.subTest(state=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve() / "gsd-path"
                repo = self.scoped_cleanup_fixture(root, state)
                inside = repo / "worktrees" / "feature"
                inside.parent.mkdir()
                self.git(repo, "worktree", "add", "-q", str(inside), "feature/x")
                recorded = root / "recorded-task"
                self.git(repo, "worktree", "add", "-q", "-b", "recorded", str(recorded))
                tasks = repo / ".project" / "tasks"
                tasks.mkdir(parents=True)
                (tasks / "T001.md").write_text(
                    f"---\ntask_branch: null\nworktree: {recorded}\n---\n",
                    encoding="utf-8",
                )
                legacy = root / "repo.gsd-path" / "verify" / "T001"
                self.git(repo, "worktree", "add", "-q", "--detach", str(legacy))
                integrate = root / ".repo-gsd-path-integrate-T001"
                self.git(repo, "worktree", "add", "-q", "--detach", str(integrate))
                for target in (inside, root / "plain-worktree"):
                    with self.subTest(target=target.name):
                        self.assert_allowed(
                            self.bash_in(
                                repo,
                                f"git worktree remove --force {shlex.quote(str(target))}",
                            )
                        )
                for target in (recorded, root / "task-worktree", legacy, integrate):
                    with self.subTest(target=target.name):
                        self.assert_denied_with(
                            self.bash_in(
                                repo,
                                f"git worktree remove --force {shlex.quote(str(target))}",
                            ),
                            guard_hook.GIT_REASONS["worktree"],
                        )

    def test_alias_inspection_runs_in_the_native_form_of_the_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.scoped_cleanup_fixture(Path(temporary).resolve())
            self.git(repo, "config", "alias.retire", "branch -D")

            # Stand in for the Git Bash drive mapping, which only Windows applies.
            def native(value):
                return value.replace("/gitbash", repo.as_posix(), 1)

            with mock.patch.object(guard_hook, "native_path_text", side_effect=native):
                self.assert_allowed(self.bash_in(repo, "cd /gitbash && git status"))
                self.assert_allowed(
                    self.bash_in(repo, "cd /gitbash && git retire feature/x")
                )
                self.assert_denied_with(
                    self.bash_in(repo, "cd /gitbash && git retire gsd-path/M001"),
                    guard_hook.GIT_REASONS["branch"],
                )

    def test_scoped_deletion_after_a_parameter_cd_stays_denied(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            owned = self.init_git_repo(parent / "owned")
            unrelated = self.init_git_repo(parent / "unrelated")
            for repo in (owned, unrelated):
                self.git(repo, "branch", "same-name")
            (owned / ".project").mkdir()
            (owned / ".project" / "STATE.md").write_text(
                "---\nphase: build\nbranch: same-name\n---\n", encoding="utf-8"
            )
            for repo in (owned, unrelated):
                directory = shlex.quote(repo.as_posix())
                with self.subTest(repo=repo.name):
                    self.assert_denied_with(
                        self.bash_in(
                            parent, f'D={directory}; cd "$D" && git branch -D same-name'
                        ),
                        guard_hook.GIT_REASONS["unresolved-target"].format(
                            action="git branch -D"
                        ),
                    )
                    self.assert_allowed(
                        self.bash_in(
                            parent, f'D={directory}; cd "$D" && git -C "$PWD" status --short'
                        )
                    )
            self.assert_denied_with(
                self.bash_in(parent, "unset D; cd $D && git status"),
                "cd target $D cannot be resolved by the guard",
            )

    @posix_only
    def test_scoped_cleanup_works_when_git_rejects_nul_worktree_listing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo = self.scoped_cleanup_fixture(root)
            self.git(repo, "worktree", "add", "-q", "--detach", str(root / "detached-worktree"))
            # Git before 2.36 has no `worktree list -z`.
            shim = root / "bin" / "git"
            shim.parent.mkdir()
            shim.write_text(
                "#!/bin/sh\n"
                'case " $* " in *" worktree list "*" -z "*)\n'
                '  echo "error: unknown switch z" >&2; exit 129;;\n'
                "esac\n"
                f'exec {shlex.quote(shutil.which("git"))} "$@"\n',
                encoding="utf-8",
            )
            shim.chmod(0o755)
            path = f"{shim.parent}{os.pathsep}{os.environ['PATH']}"
            with mock.patch.dict(os.environ, {"PATH": path}):
                rejected = subprocess.run(
                    ["git", "worktree", "list", "--porcelain", "-z"],
                    cwd=repo, capture_output=True, check=False,
                )
                self.assertEqual(129, rejected.returncode)
                for command in (
                    "git branch -D feature/x",
                    "git update-ref -d refs/heads/feature/x",
                    "git worktree remove --force ../plain-worktree",
                    "git worktree remove --force ../detached-worktree",
                ):
                    with self.subTest(command=command):
                        self.assert_allowed(self.bash_in(repo, command))
                for command, rule in (
                    ("git branch -D gsd-path/M001", "branch"),
                    ("git update-ref -d refs/heads/gsd-path/M001", "update-ref"),
                    ("git worktree remove --force ../task-worktree", "worktree"),
                ):
                    with self.subTest(command=command):
                        self.assert_denied_with(
                            self.bash_in(repo, command), guard_hook.GIT_REASONS[rule]
                        )

    def test_git_ignores_an_alias_for_each_built_in_command_the_guard_skips(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo = self.init_git_repo(root / "repo")
            (root / "home").mkdir()
            environment = {**os.environ, "HOME": str(root / "home")}
            for command in sorted(guard_hook.GIT_BUILT_IN_COMMANDS):
                with self.subTest(command=command):
                    result = subprocess.run(
                        ["git", "-c", f"alias.{command}=!echo alias-ran", command,
                         "--no-such-option"],
                        cwd=repo, env=environment, capture_output=True,
                        encoding="utf-8", errors="replace", check=False,
                    )
                    self.assertNotIn("alias-ran", result.stdout)

    def scoped_pair_fixture(self, parent):
        """`owned` binds the branch `bound` in STATE; `unrelated` has a plain `bound`."""
        owned = self.init_git_repo(parent / "owned")
        unrelated = self.init_git_repo(parent / "unrelated")
        for repo in (owned, unrelated):
            self.git(repo, "branch", "bound")
        (owned / ".project").mkdir()
        (owned / ".project" / "STATE.md").write_text(
            "---\nphase: build\nbranch: bound\n---\n", encoding="utf-8"
        )
        return owned, unrelated

    def test_scoped_deletion_is_denied_after_a_directory_change_the_guard_cannot_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            owned, unrelated = self.scoped_pair_fixture(Path(temporary).resolve())
            a, b = (shlex.quote(repo.as_posix()) for repo in (owned, unrelated))
            # A directory with the literal name ~ is not the home directory.
            self.git(self.init_git_repo(owned / "~" / "r"), "branch", "bound")
            unresolved = guard_hook.GIT_REASONS["unresolved-target"].format(
                action="git branch -D"
            )
            delete = "git branch -D bound"
            for command in (
                f"cd {a} {b}; {delete}",
                f"cd {a} {b} && {delete}",
                f"cd -- {a} {b}; {delete}",
                f"cd -P {b}; {delete}",
                f"cd {b} -P; {delete}",
                f"cd {b} 2>/dev/null extra; {delete}",
                f"cd {b}-missing 2>/dev/null; {delete}",
                f"cd '' {b}; {delete}",
                f"chdir {b}; {delete}",
                f"pushd {b}; {delete}",
                f"CD {b}; {delete}",
                f"/usr/bin/cd {b} && {delete}",
                f"env cd {b} && {delete}",
                f"true # note; cd {b}\n{delete}",
                f"false &&\ncd {b}; {delete}",
                f"cd ~/r && {delete}",
                # Without the builtin, cd is the program /usr/bin/cd: no effect.
                f"enable -n cd; cd {b} && {delete}",
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(self.bash_in(owned, command), unresolved)
            for command in (
                f"function enter {{ cd {a}; }}; enter; {delete}",
                f"trap 'cd {a}' DEBUG; {delete}",
                f"alias enter='cd {a}'\nenter\n{delete}",
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(self.bash_in(unrelated, command), unresolved)
            self.assert_denied_with(
                self.bash_in(owned, f"cd {b}-missing; {delete}"),
                "git target repository cannot be resolved",
            )
            # A shell with CDPATH can find the plain name `unrelated` elsewhere.
            self.assert_denied_with(
                self.bash_in(owned.parent, f"cd unrelated && {delete}"), unresolved
            )
            self.assert_allowed(
                self.bash_in(owned.parent, f"cd ./unrelated && {delete}")
            )
            for command in (
                f"cd {b} && {delete}",
                f"cd -- {b} && {delete}",
                f"cd {b}; {delete}",
                f"cd {b} &&\n{delete}",
                f"cd ../unrelated && {delete}",
                f"cd {a} {b}; git status",
                f"cd -P {b}; git log --oneline -1",
            ):
                with self.subTest(command=command):
                    self.assert_allowed(self.bash_in(owned, command))

    def test_scoped_deletion_with_a_parameter_in_the_git_command_is_denied(self):
        with tempfile.TemporaryDirectory() as temporary:
            owned, unrelated = self.scoped_pair_fixture(Path(temporary).resolve())
            a, b = (shlex.quote(repo.as_posix()) for repo in (owned, unrelated))
            unresolved = guard_hook.GIT_REASONS["unresolved-target"].format(
                action="git branch -D"
            )
            delete = 'git -C "$W" branch -D bound'
            # The shell changes W in ways the guard does not track.
            for command in (
                f"W={b}; read W <<< {a}; {delete}",
                f"W={b}; W+=/../owned; {delete}",
                f"W={b}; for W in {a}; do :; done; {delete}",
                f"W={b}; printf -v W %s {a}; {delete}",
                f"keep() {{ W={b}; }}; {delete}",
                f"true # note; W={b}\n{delete}",
                f"W={b}; {delete}",
                f'cd {b} && git -C "$PWD" branch -D bound',
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(self.bash_in(owned, command), unresolved)
            self.assert_allowed(
                self.bash_in(owned, f'W={b}; git -C "$W" status --short')
            )
            # read sets GIT_DIR and set -a exports it; the guard tracks neither.
            self.assert_denied_with(
                self.bash_in(
                    unrelated, f"set -a; read GIT_DIR <<< {a}/.git; git branch -D bound"
                ),
                guard_hook.GIT_REASONS["git-environment"],
            )
            self.assert_allowed(self.bash_in(owned, f"git -C {b} branch -D bound"))
            # A literal ~ or glob in the directory is expanded by the shell only.
            self.git(self.init_git_repo(owned / "~" / "r"), "branch", "bound")
            self.assert_denied_with(
                self.bash_in(owned, "git -C ~/r branch -D bound"), unresolved
            )

    def test_update_ref_deletion_follows_the_exact_name_as_git_does(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.scoped_cleanup_fixture(Path(temporary).resolve())
            self.git(repo, "branch", "FOO")
            self.git(repo, "symbolic-ref", "FOO", "refs/heads/gsd-path/M001")
            self.git(repo, "symbolic-ref", "refs/heads/first", "refs/heads/gsd-path/M001")
            self.git(repo, "symbolic-ref", "refs/heads/second", "refs/heads/first")
            self.git(repo, "symbolic-ref", "refs/heads/plain-alias", "refs/heads/feature/x")
            self.git(repo, "update-ref", "refs/remotes/origin/stale", "HEAD")
            self.git(repo, "update-ref", "refs/remotes/origin/gsd-path/M001", "HEAD")
            (repo / "README.md").write_text("changed\n", encoding="utf-8")
            self.git(repo, "stash")
            owned = guard_hook.GIT_REASONS["update-ref"]
            unresolved = guard_hook.GIT_REASONS["unresolved-target"].format(
                action="git update-ref deletion"
            )
            for command in (
                "git update-ref -d refs/heads/second",
                "git update-ref -m --no-deref -d refs/heads/second",
                "git update-ref -d refs/remotes/origin/gsd-path/M001",
                "git update-ref -d refs/stash",
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(self.bash_in(repo, command), owned)
            for command in (
                # Git deletes the Path branch that the symbolic ref FOO names,
                # not the branch FOO; HEAD moves with each git switch.
                "git update-ref -d FOO",
                "git update-ref -d FOO " + "0" * 40,
                "git update-ref -d HEAD",
                # -m takes refs/heads/feature/x as its value here.
                "git update-ref -dm refs/heads/feature/x refs/heads/gsd-path/M001",
                "git update-ref -d feature/x",
                "git update-ref --stdin",
                "git update-ref --std",
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(self.bash_in(repo, command), unresolved)
            # An earlier Git command of the same command line can point a
            # symbolic ref at the Path branch after the guard has read it.
            repoint = "git symbolic-ref {} refs/heads/gsd-path/M001"
            for command in (
                repoint.format("refs/heads/plain-alias")
                + " && git update-ref -d refs/heads/plain-alias",
                repoint.format("refs/heads/feature/x")
                + "; git update-ref -d refs/heads/feature/x",
                "bash -c '" + repoint.format("refs/heads/plain-alias")
                + "'; git update-ref -d refs/heads/plain-alias",
                "git status && git update-ref -m --no-deref -d refs/heads/plain-alias",
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(
                        self.bash_in(repo, command),
                        guard_hook.GIT_REASONS["update-ref-order"],
                    )
            for command in (
                "git update-ref -d refs/heads/feature/x",
                "git update-ref -m note -d refs/heads/feature/x",
                "git update-ref -d refs/heads/plain-alias",
                "git update-ref --no-deref -d refs/heads/second",
                "git update-ref -d refs/remotes/origin/stale",
                "git status && git update-ref --no-deref -d refs/heads/feature/x",
                "ls && git update-ref -d refs/heads/feature/x",
            ):
                with self.subTest(command=command):
                    self.assert_allowed(self.bash_in(repo, command))

    def test_forced_branch_deletion_reads_names_and_options_as_git_does(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.scoped_cleanup_fixture(
                Path(temporary).resolve(),
                "---\nphase: build\nbranch: bound\n---\n",
            )
            self.git(repo, "branch", "bound")
            for name in ("stale", "gsd-path/M001", "bound"):
                self.git(repo, "update-ref", f"refs/remotes/origin/{name}", "HEAD")
            owned = guard_hook.GIT_REASONS["branch"]
            unresolved = guard_hook.GIT_REASONS["unresolved-target"].format(
                action="git branch -D"
            )
            for command in (
                "git branch -rD origin/stale",
                "git branch -r -D origin/stale",
                "git branch --remotes --delete --force origin/stale",
                "git branch --del --force feature/x",
            ):
                with self.subTest(command=command):
                    self.assert_allowed(self.bash_in(repo, command))
            for command in (
                "git branch -rD origin/gsd-path/M001",
                "git branch -r -D origin/bound",
                # --color takes no separate value, so git deletes both names.
                "git branch -D --color gsd-path/M001 feature/x",
                "git branch --delete --forc gsd-path/M001",
                "git branch --del --force gsd-path/M001",
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(self.bash_in(repo, command), owned)
            for command in (
                "git branch -rD origin/missing",
                "git branch -D -r feature/x",
                "git branch -D refs/heads/feature/x",
            ):
                with self.subTest(command=command):
                    self.assert_denied_with(self.bash_in(repo, command), unresolved)

    def test_branch_names_that_differ_only_in_case_from_a_bound_branch_are_owned(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.init_git_repo(Path(temporary).resolve() / "repo")
            # A packed Bound and a loose bound share one file on macOS and Windows.
            self.git(repo, "branch", "Bound")
            self.git(repo, "pack-refs", "--all")
            self.git(repo, "branch", "bound")
            (repo / ".project").mkdir()
            (repo / ".project" / "STATE.md").write_text(
                "---\nphase: build\nbranch: bound\n---\n", encoding="utf-8"
            )
            self.assert_denied_with(
                self.bash_in(repo, "git branch -D Bound"), guard_hook.GIT_REASONS["branch"]
            )
            self.assert_denied_with(
                self.bash_in(repo, "git update-ref -d refs/heads/Bound"),
                guard_hook.GIT_REASONS["update-ref"],
            )

    def test_forced_worktree_removal_reads_the_option_and_the_target_as_git_does(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.scoped_cleanup_fixture(Path(temporary).resolve())
            for option in ("--forc", "--fo"):
                with self.subTest(option=option):
                    self.assert_denied_with(
                        self.bash_in(repo, f"git worktree remove {option} ../task-worktree"),
                        guard_hook.GIT_REASONS["worktree"],
                    )
            self.assert_allowed(
                self.bash_in(repo, "git worktree remove --forc ../plain-worktree")
            )

    @requires_symlink
    def test_forced_worktree_removal_is_denied_when_git_can_pick_another_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo = self.scoped_cleanup_fixture(root)
            # Git tries the unique path suffix first: the Path-owned worktree.
            (repo / "task-worktree").symlink_to(
                root / "plain-worktree", target_is_directory=True
            )
            self.assert_denied_with(
                self.bash_in(repo, "git worktree remove --force task-worktree"),
                guard_hook.GIT_REASONS["unresolved-target"].format(
                    action="git worktree remove --force"
                ),
            )

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

    def test_allows_pipelines_of_read_commands_in_archive_context(self):
        for command in (
            "cat NOTE.md | wc -l",
            "cat NOTE.md | head -3 | tail -1",
            "cat NOTE.md | grep -c x",
        ):
            with self.subTest(command=command):
                self.assert_allowed(
                    {
                        "tool_name": "Bash",
                        "tool_input": {
                            "command": command,
                            "cwd": ".project/archive/001-mvp",
                        },
                    }
                )
        for command in (
            "cat NOTE.md | tee out.txt",
            "python3 -",
            "python3 - <<'EOF'\nprint(1)\nEOF",
        ):
            with self.subTest(command=command):
                self.assert_denied(
                    {
                        "tool_name": "Bash",
                        "tool_input": {
                            "command": command,
                            "cwd": ".project/archive/001-mvp",
                        },
                    }
                )

    def test_heredoc_body_does_not_flip_archive_context(self):
        for command in (
            "python3 - <<'EOF'\n# mention of .project/archive/001-mvp\nprint(1)\nEOF",
            "bash -c 'cat <<EOF\nmention of .project/archive/001-mvp here\nEOF'",
        ):
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command))
        self.assert_denied(
            self.bash("bash -c 'echo broken > .project/archive/001-mvp/NOTE.md'")
        )

    def test_ssh_from_archive_cwd_is_denied_as_unproven_read(self):
        status, _, error = run_guard(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "ssh host 'cat /etc/hosts'",
                    "cwd": ".project/archive/001-mvp",
                },
            }
        )
        self.assertEqual(status, 2, error)
        self.assertIn(guard_hook.ARCHIVE_UNPROVEN_READ_REASON, error)
        self.assertNotIn(guard_hook.ARCHIVE_REASON, error)
        status, _, error = run_guard(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "touch NOTE.md",
                    "cwd": ".project/archive/001-mvp",
                },
            }
        )
        self.assertEqual(status, 2, error)
        self.assertIn(guard_hook.ARCHIVE_REASON, error)

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
                'rm -rf "scratch folder"',
            )
            # Windows needs PATH (to find git), SYSTEMROOT to start any process, and
            # USERPROFILE so the state-root check can resolve the home directory.
            kept = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "USERPROFILE") if os.name == "nt" and name in os.environ}
            with mock.patch.dict(os.environ, kept, clear=True):
                for commands, assertion in ((denied, self.assert_denied), (allowed, self.assert_allowed)):
                    for command in commands:
                        with self.subTest(command=command):
                            assertion({
                                "tool_name": "Bash",
                                "tool_input": {"command": command},
                                "cwd": str(repository),
                            })

    def test_allows_quoted_spaces_in_destructive_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary).resolve()
            (repository / ".project" / "archive" / "001-mvp").mkdir(parents=True)
            (repository / "scratch folder").mkdir()
            for command, assertion in (
                ('rm -rf "scratch folder"', self.assert_allowed),
                ('rm "$var/whatever"', self.assert_denied),
                ('rm "scratch;other"', self.assert_denied),
            ):
                with self.subTest(command=command):
                    assertion(
                        {
                            "tool_name": "Bash",
                            "tool_input": {"command": command, "cwd": str(repository)},
                        }
                    )

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
        # The expanded cd target is tracked, so the later write is still caught
        # as a protected control write rather than by refusing the cd itself.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            (root / ".project").mkdir(parents=True)
            (root / ".project" / "STATE.md").write_bytes("owned\n".encode("utf-8"))
            with (
                mock.patch.object(guard_hook.os, "getcwd", return_value=str(root)),
                mock.patch.object(guard_hook, "repository_root", return_value=root),
            ):
                self.assert_denied(
                    self.bash("TARGET=.project; cd $TARGET; printf broken > STATE.md")
                )

    def test_allows_tracked_assignment_in_cd_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = shlex.quote(str(Path(temporary).resolve()))
            self.assert_allowed(
                self.bash(f'dir={directory} && cd "$dir" && git status')
            )
        self.assert_denied(self.bash('dir="a b"; cd "$dir" && git status'))
        self.assert_denied(self.bash('cd "$unassigned" && git status'))

    def test_denies_cd_to_shell_maintained_directory_variables(self):
        for command in (
            'cd .project/archive/001-mvp && cd "$PWD" && touch NOTE.md',
            "cd .project/archive/001-mvp && cd / && cd $OLDPWD && touch NOTE.md",
            'PWD=/tmp; cd .project/archive/001-mvp && cd "$PWD" && touch NOTE.md',
        ):
            with self.subTest(command=command):
                self.assert_denied(self.bash(command))

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

    def make_closed_milestone_repo(self) -> Path:
        """A shipped milestone repo on its bound branch: the shell rule that
        reports "accepts no new work" engages for tool cwd inside it."""
        import tempfile
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "repo"
        root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "gsd-path/M001", str(root)], check=True)
        subprocess.run(["git", "config", "user.name", "Guard test"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
        state = root / ".project/STATE.md"
        state.parent.mkdir()
        state.write_text(
            "---\n"
            "pipeline: gsd-path/v2\n"
            "project: demo\n"
            "milestone: demo\n"
            "phase: shipped\n"
            "status: done\n"
            "branch: gsd-path/M001\n"
            "archive: .project/archive/001-demo\n"
            "---\n\n# Project State\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", ".project/STATE.md"], cwd=root, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "ship: M001 — demo"],
            cwd=root, check=True,
        )
        return root

    def test_fetch_family_survives_a_closed_milestone(self):
        repo = self.make_closed_milestone_repo()

        def inside(command):
            return {
                "tool_name": "Bash",
                "tool_input": {"command": command, "cwd": str(repo)},
            }

        # The fetch family needs configured remotes (an unconfigured name
        # makes git fetch from a local directory of that name).
        subprocess.run(
            ["git", "remote", "add", "origin", str(repo)], cwd=repo, check=True
        )
        subprocess.run(["git", "remote", "add", "upstream", str(repo)], cwd=repo, check=True)
        for command in ("git fetch", "git fetch origin", "git fetch upstream"):
            with self.subTest(command=command):
                self.assert_allowed(inside(command))

        # A configured refspec that would move a local branch is refused.
        subprocess.run(["git", "remote", "add", "peer", str(repo)], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "remote.peer.fetch",
             "+refs/heads/main:refs/heads/retired"],
            cwd=repo, check=True,
        )
        self.assert_denied(inside("git fetch peer"))
        # Restoring remote-tracking-only refspecs re-allows the fetch.
        subprocess.run(
            ["git", "config", "remote.peer.fetch",
             "+refs/heads/*:refs/remotes/peer/*"],
            cwd=repo, check=True,
        )
        self.assert_allowed(inside("git fetch peer"))

        # An unconfigured remote name is refused (git would fetch from a
        # local directory of that name).
        self.assert_denied(inside("git fetch neighbor"))

        # Configured fetch behavior that runs a program, deletes refs,
        # rewrites every ref or forces tags is refused; unsetting it
        # restores the allowance.
        for key, value in (
            ("remote.origin.uploadpack", "touch pwned; git-upload-pack"),
            ("remote.origin.prune", "true"),
            ("remote.origin.pruneTags", "true"),
            ("fetch.prune", "true"),
            ("fetch.pruneTags", "true"),
            ("remote.origin.mirror", "true"),
            ("remote.origin.tagopt", "--tags"),
        ):
            with self.subTest(key=key):
                subprocess.run(["git", "config", key, value], cwd=repo, check=True)
                self.assert_denied(inside("git fetch origin"))
                subprocess.run(["git", "config", "--unset", key], cwd=repo, check=True)
                self.assert_allowed(inside("git fetch origin"))

        # A -C value that is literally named fetch must not let a later
        # global flag ride in before the real subcommand.
        (repo / "fetch").mkdir()
        self.assert_allowed(inside("git -C fetch fetch origin"))
        for command in (
            "git -C fetch -p fetch origin",
            "git -C fetch --no-pager fetch origin",
            "git -C fetch --bare fetch origin",
        ):
            with self.subTest(command=command):
                self.assert_denied(inside(command))

        denied = (
            "git fetch origin main",
            "git fetch origin +refs/heads/*:refs/heads/*",
            "git fetch --prune origin",
            "git fetch --write-commit-graph origin",
            "git fetch --update-head-ok origin main",
            "git fetch --upload-pack='rm -rf /' origin",
            "git -c diff.context=5 fetch origin",
            "git --git-dir=/tmp/other fetch origin",
            "git fetch http://evil/",
            "git fetch ../neighbor",
            "git pull",
            "git push",
            "git -p fetch origin",
            "git --no-pager fetch origin",
        )
        for command in denied:
            with self.subTest(command=command):
                self.assert_denied(inside(command))

    def test_git_global_execution_options_deny_everywhere(self):
        # The pre-#468 hole: global options before the subcommand were
        # stripped before the read-only checks, so --upload-pack/--exec
        # slipped past a nominally read-only fetch.
        for command in (
            "git --upload-pack='touch /tmp/x' fetch origin",
            "git --exec='rm' fetch origin",
            "git --upload-pack='rm -rf /' status",
            "git --receive-pack='sh' push origin main",
        ):
            with self.subTest(command=command):
                self.assert_denied(self.bash(command))

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

    def test_allows_parameters_in_read_only_git_arguments(self):
        for command in (
            'git log --format="$t %H"',
            't=abc; git log --format="$t %H"',
            'git show "HEAD:$f"',
            'git show "HEAD:${f}"',
            'git log --format="%H%n%s"',
            '# note\ngit log --format="$t %H"',
            'x=abc; cd .project/archive/001-mvp && git log --format="%H $x"',
            'cd .project/archive/001-mvp && git log --format="%H $x"',
            'cd .project/archive/001-mvp && git show "HEAD:$f"',
        ):
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command))
        self.assert_denied(self.bash('git commit -m "$msg"'))
        # Deliberate fail-closed choice: a parameter outside double quotes
        # stays denied, because its expansion word-splits and can add a write
        # option such as --output.
        unquoted = (
            "git show HEAD:$f",
            "git diff --format=$x",
            "x='a --output=NOTE.md'; git diff --format=$x",
            "x='c --output=.project/archive/001-mvp/NOTE.md'; git diff --format=\"a b\"$x",
            'git diff --format="a b"$x',
            'git diff "a b"$x',
            'git log --format="a b"$1',
            "git log --format='$t %H'",
            'git log --format=$t\\ %H',
            'git log "--format=$@ %H"',
            'git log # "\n git diff --format=$x "',
            # Quoting outside plain single and double quotes disables the
            # exception for the whole command, quoted parameters included.
            "x='c --output=.project/archive/001-mvp/NOTE.md'; "
            "git diff --no-index --src-prefix=a$'\\'''\"'$x\"'\"\\''' /dev/null f",
            "git log --format=a$'\\'''\"'$x\"'\"\\'''",
            "echo $'a'; git log --format=\"$t %H\"",
            'echo $"a"; git log --format="$t %H"',
            'git log --format="${t:-"a"} $x %H"',
            "# it's\ngit log --format=\"$t %H\"",
            'git log --format="$t %H" <<< "x"',
            # A wrapped string is parsed by a second shell after the outer
            # one expands parameters, so its inner quotes prove nothing.
            'read x < v.txt; eval "git diff --src-prefix=\\"a $x\\""',
            'read x < v.txt; bash -c "git diff --src-prefix=\\"a $x\\""',
            'read x < v.txt; sh -c "git log --format=\\"a $x\\""',
            'eval "git status \\"a $x\\""',
            'eval "git log --format=\\"a $1\\""',
            "bash -c 'git log --format=\"$t %H\"'",
            'powershell -Command git log "--format=$t %H"',
            # Only plain $name and ${name} are single-word: zsh flags and
            # array or positional forms split even inside double quotes.
            *(
                "x='c --output=.project/archive/001-mvp/NOTE.md'; "
                f'git diff --no-index "--src-prefix=a {form}" /dev/null f'
                for form in (
                    "${=x}", "${(s: :)x}", "${(z)x}", "${(f)x}", "$x[@]",
                    "$argv[@]", "${x[@]}", "${x:-b}", "$1", "$*", "$#", "$t $=x",
                )
            ),
            'git log --format="a ${=x}"',
            # One word is enough where git runs the value as a command.
            'read x < v.txt; git ls-remote --upload-pack="$x" .',
            'read x < v.txt; git ls-remote --upload-pack "a $x" .',
            'read x < v.txt; git ls-remote "--exec=$x" .',
            'read x < v.txt; git ls-remote --exec "a $x" .',
            'read x < v.txt; git ls-remote --receive-pack="$x" .',
            'read x < v.txt; git ls-remote --receive-pack "a $x" .',
            'read x < v.txt; git ls-remote "ext::$x"',
            # git accepts each unique prefix of a long option name.
            'read x < v.txt; git ls-remote --upload-pa="a $x" .',
            "read x < v.txt; git ls-remote --upl=$x .",
            'read x < v.txt; git ls-remote "--upl=$x" .',
            'read x < v.txt; git ls-remote --upload-pac "a $x" .',
            "read x < v.txt; git ls-remote --exe=$x .",
            'read x < v.txt; git ls-remote "--exe=a $x" .',
            'read x < v.txt; git ls-remote "--receive-p=a $x" .',
            'git diff "--outpu=a $f"',
            'read x < v.txt; git -c "diff.external=$x" diff',
            'read x < v.txt; git "-cdiff.external=$x" diff',
            'read x < v.txt; git -c "core.fsmonitor=$x" status',
            # A literal value is just as dangerous: git executes the
            # configured program while the subcommand stays read-only.
            'git -c core.fsmonitor=/tmp/fsm-hook status .project/archive',
            'cd .project/archive/001-mvp && git -c core.fsmonitor=/tmp/fsm-hook status',
            'git -c core.hooksPath=/tmp/hooks status',
            'git -c core.editor=/tmp/editor.sh log -1',
            'git -c core.sshCommand=/tmp/ssh.sh ls-remote origin',
            'git -c core.pager=/tmp/pager.sh log',
            'git -c diff.my.textconv=/tmp/tc.sh log',
            'git -c filter.driver.clean=/tmp/clean.sh show HEAD:file',
            'git -c merge.rewriter.driver=/tmp/merge.sh merge topic',
            'git --config-env=core.fsmonitor=FSM status',
            'git -c core.fsmonitor=true status',
            'git --config-env=core.fsmonitor=FALSE_VALUE status',
            # Keys that load code through a path or URL have no disabling value.
            'git -c include.path=/tmp/cfg status',
            'git -c includeIf.gitdir:/tmp/.path=/tmp/cfg status',
            'git -c core.hooksPath= status',
            'git -c remote.o.uploadpack=/tmp/h.sh ls-remote o',
            'git -c remote.o.receivepack=/tmp/h.sh ls-remote o',
            'git -c core.gitProxy=/tmp/h.sh ls-remote git://example.invalid/x',
            'git -c url.x.insteadOf=y ls-remote x',
            'git -c url.x.pushInsteadOf=y ls-remote x',
            # The persisted form runs the program on each later plain git.
            'git config core.fsmonitor /tmp/h.sh',
            'git config core.fsmonitor /tmp/h.sh && git status',
            'git config --local core.hooksPath /tmp/hooks',
            'git config --add include.path /tmp/cfg',
            'git config set core.fsmonitor /tmp/h.sh',
            'git config core.fsmonitor /tmp/h.sh >/dev/null',
            # A digit before a redirection is a real operand, and a quoted
            # operator is a real value: both are a set.
            'git config core.hooksPath 5 >/dev/null',
            'git config core.hooksPath 5 >> log.txt',
            'git config core.fsmonitor 2 >/dev/null',
            # One token can become several git arguments, or two tokens
            # one: only plain literal words prove the read or set form.
            # A run of continuations joins the words on its two sides.
            'git config core.fsmoni\\\n\\\ntor /abs/h.sh',
            'git c\\\n\\\nonfig core.fsmonitor /abs/h.sh',
            'git con\\\n\\\n\\\nfig core.fsmonitor /abs/h.sh',
            'git con\\\r\nfig core.fsmonitor /abs/h.sh',
            'git con\\\r\n\\\r\nfig core.fsmonitor /abs/h.sh',
            # The guard checks the command that a command runner runs.
            *(
                f"{wrapper} git -c core.fsmonitor=/abs/h.sh status"
                for wrapper in (
                    "nice", "nice -n 5", "nice -n5", "nice --adjustment=5", "nohup",
                    "timeout 5", "timeout -s KILL 5", "timeout --signal=KILL 2.5s",
                    "sudo", "sudo -u root", "sudo -Eu root", "sudo --user root",
                    "sudo FOO=1", "watch", "watch -n 5", "stdbuf -o0", "stdbuf -o L",
                    "setsid", "time -p", "env nice", "nice env", "nice command",
                    "nice nohup", "/usr/bin/nice", "sudo.exe", "nice --",
                )
            ),
            # A runner option that writes or edits a file is not skipped.
            'nice time -o .project/archive/001-mvp/N ls',
            'env time -o .project/archive/001-mvp/N ls',
            '/usr/bin/time -o .project/archive/001-mvp/N ls',
            'timeout 5 time -o .project/archive/001-mvp/N ls',
            'nice time --output=.project/archive/001-mvp/N ls',
            'nice time --outp .project/archive/001-mvp/N ls',
            'nice time -ao .project/archive/001-mvp/N ls',
            'nice time -o .project/archive/001-mvp/N git status',
            'sudo -e cat .project/archive/001-mvp/plan/PLAN.md',
            'sudo --edit .project/archive/001-mvp/plan/PLAN.md',
            'sudo -D .project/archive/001-mvp touch N',
            'watch -s .project/archive/001-mvp ls',
            'nice time -oN ls',
            'nice time -pao N ls',
            # A runner option word that is not literal can spell a file option.
            'read x < v.txt; nice /usr/bin/time "-$x" ls',
            'read x < v.txt; nice time "-$x" git status',
            'read x < v.txt; sudo "-$x" touch N',
            'watch --interval="$t" ls',
            'nice time -\\o N ls',
            'sudo -{u,e} root ls',
            # An attached short option value is no more options, and the next
            # word is the command.
            'sudo -uroot git -c core.fsmonitor=/abs/h.sh status',
            'sudo -hlocalhost git -c core.fsmonitor=/abs/h.sh status',
            'sudo -uroot git config core.fsmonitor /abs/h.sh',
            'sudo -Eu root git -c core.fsmonitor=/abs/h.sh status',
            'nice -n5 git -c core.fsmonitor=/abs/h.sh status',
            'timeout infinity git -c core.fsmonitor=/abs/h.sh status',
            # A runner operand must be a literal word.
            'timeout "$T" make',
            'timeout ${T:-5} make',
            'timeout five make',
            'watch -n $t ls',
            'nice -n $n git status',
            'sudo -u $u ls',
            'env $A=1 git status',
            'nice $CMD',
            'timeout .5 git -c core.fsmonitor=/abs/h.sh status',
            'watch -q 3 git -c core.fsmonitor=/abs/h.sh status',
            'nice --adj 5 git -c core.fsmonitor=/abs/h.sh status',
            "nice sh -c 'git -c core.fsmonitor=/abs/h.sh status'",
            'nice /usr/bin/git -c core.fsmonitor=/abs/h.sh status',
            'nice git config core.fsmonitor /abs/h.sh',
            'timeout 5 git -c $x',
            'timeout $t git status',
            'sudo GIT_CONFIG_COUNT=1 git status',
            # A parameter in a global option value is unresolved with or
            # without a visible subcommand: bash splits it into both.
            'read x < v.txt; git -c $x',
            'git -c $x',
            'git --git-dir $x',
            'git --git-dir=$x',
            # Each global option word must be one word.
            'git -{p,c} core.fsmonitor=/abs/h.sh status',
            'X=/abs/h.sh git --{no-pager,config-env=core.fsmonitor=X} status',
            'git --no-pager{,} -c core.fsmonitor=/abs/h.sh status',
            'git --no-\\\npager {config,core.fsmonitor,/abs/h.sh}',
            # git runs a pager.<cmd> value that is no boolean as the pager.
            'git -c "pager.status=touch .project/archive/001-mvp/N" status',
            'git -c pager.log=/abs/h.sh log',
            'git -c PAGER.LOG=/abs/h.sh log',
            'git -c pager.log=cat log',
            'git config pager.log /abs/h.sh',
            # git runs a credential helper when a remote asks for credentials.
            'git -c credential.helper=/abs/h.sh ls-remote http://127.0.0.1:8080/x.git',
            'git -c credential.https://x.helper=/abs/h.sh ls-remote origin',
            'git config credential.helper /abs/h.sh',
            # The value word of a git global option must be one word.
            'git -c {core.fsmonitor=/abs/h.sh,status}',
            'git -c{core.fsmonitor=/abs/h.sh,status}',
            'git -c {a.b=c,config,core.fsmonitor,/abs/h.sh}',
            'git -C {.,config,core.fsmonitor,/abs/h.sh}',
            'git -C{.,config,core.fsmonitor,/abs/h.sh}',
            'git --git-dir {.git,config,core.fsmonitor,/abs/h.sh}',
            'git --git-dir={.git,config}',
            'git --work-tree {.,config,core.fsmonitor,/abs/h.sh}',
            'git --namespace {a,config,core.fsmonitor,/abs/h.sh}',
            "git -c 'a.b=c'{,config,core.fsmonitor,/abs/h.sh}",
            'git -c user.name=A\\ B log -1',
            'git -C sub\\ dir status',
            # The subcommand word must be one literal word too.
            'git {config,core.fsmonitor,/abs/h.sh}',
            'git con\\\nfig core.fsmonitor /abs/h.sh',
            'git --no-pager {config,core.fsmonitor,/abs/h.sh}',
            "git con''fig core.fsmonitor /abs/h.sh",
            # Comment text is no argument: a mode word in it proves nothing.
            'git config core.fsmonitor /tmp/h.sh # --get',
            'git config core.fsmonitor /tmp/h.sh #--get',
            'git config --get core.fsmonitor # note',
            'git config {core.hooksPath,/tmp/hooks}',
            'git config core.hooksPath{,/tmp/hooks}',
            'git config {core.fsmonitor,/abs/h.sh}',
            'git config {--add,core.fsmonitor,/abs/h.sh}',
            'git config core.fsmoni\\\ntor /tmp/h.sh',
            'git config "core.fsmoni\\\ntor" /tmp/h.sh',
            'git config core.hooksPath\\ x',
            'git config user.name Jeremy\\ M',
            "git config --get core.fsmoni''tor",
            'git config --get-regexp core.*',
            'git config --get core.[f]smonitor',
            'git config user.{name,email}',
            'git config branch.{1..3}.merge',
            # zsh reads one ASCII digit as a file descriptor; a longer or
            # non-ASCII digit word is the value.
            'git config core.hooksPath 12>/dev/null',
            'git config core.hooksPath 12>/dev/null && git commit -m x',
            'git config core.hooksPath \u0663>/dev/null',
            'git config core.hooksPath \u00b2>/dev/null',
            'git config core.hooksPath 5 2>/dev/null',
            "git config core.hooksPath '2'>/dev/null",
            'git config core.hooksPath \\> x',
            'git config include.path 5 > /dev/null && git status',
            "git config core.hooksPath '>' x",
            # Signature verification runs the configured program in a read.
            'git -c gpg.program=/tmp/h.sh log --show-signature',
            'git -c gpg.ssh.program=/tmp/h.sh log --show-signature',
            'git -c gpg.x509.program=/tmp/h.sh log --show-signature',
            'git -c log.showSignature=true -c gpg.program=/tmp/h.sh log',
            'git config gpg.program /tmp/h.sh',
            'git config >/dev/null core.fsmonitor /tmp/h.sh',
            'git config --replace-all core.fsmonitor /tmp/h.sh',
            'git config --type path core.fsmonitor /tmp/h.sh',
            # A mode word that git reads as a value or operand is no read mode.
            'git config --file --get core.fsmonitor /tmp/h.sh',
            'git config --global set core.fsmonitor /tmp/h.sh',
            'git config core.fsmonitor /tmp/h.sh -- --get',
            # A section rename can carry a key into an executed section, and
            # --edit launches the editor.
            'git config foo.fsmonitor /tmp/h.sh && git config --rename-section foo core',
            'git config --rename-section foo core',
            'git config --rename-sec foo core',
            'git config rename-section foo core',
            'git config --remove-section foo',
            'git config remove-section foo',
            'git config --edit',
            'git config --global -e',
            'git config edit',
            'git log --format="$x[@] %H"',
            "git diff --output=$f",
            # Unbraced zsh expansion flags match no parameter syntax, so an
            # argument carrying one must still enter the parameter proof;
            # zsh splits $=x exactly like the braced forms above.
            *(
                f'git log --format="{flag}"'
                for flag in ("$=x", "$~x", "$^x", "$+x")
            ),
            'x="a --output=.project/archive/001-mvp/NOTE.md"; git log --format="$=x"',
            'x="a --output=NOTE.md"; cd .project/archive/001-mvp && git log --format="$=x"',
            # A backslash-escaped marker executes as literal text while the
            # token keeps the bare marker, so the pair is never provable.
            'git log --format="\\$t %H"',
            't=hi; git log --format="\\$t %H"',
            # The -C directory operand takes the same zsh flag check: zsh
            # splits the value, which can carry a subcommand and --output.
            *(
                prefix + form
                for prefix in ("", "x='. diff --output=.project/archive/001-mvp/N.md'; ")
                for form in ("git -C $=x", "git -C$=x", 'git -C "$=x"')
            ),
        )
        for command in unquoted:
            for prefix in ("", "cd .project/archive/001-mvp && "):
                with self.subTest(command=prefix + command):
                    self.assert_denied(self.bash(prefix + command))
        for command in (
            "git diff --output=$f",
            "git diff --output $f",
            'git diff "--output=$f x"',
            "git diff $o",
            "git log -$o",
            "git show HEAD:$f",
            "git diff --format=$x",
            "x='a --output=NOTE.md'; git diff --format=$x",
            "cd .project/archive/001-mvp && x='a --output=NOTE.md'; git diff --format=$x",
            "x='a --output=.project/archive/001-mvp/NOTE.md'; git diff --format=$x",
            'x=$(cat /tmp/v); git diff --format=$x',
            'x=$(cat /tmp/v); git log --format="$x %H"',
            'git log --format="$(cat /tmp/v) %H"',
        ):
            with self.subTest(command=command):
                self.assert_denied(self.bash(command))

    def test_denies_executed_config_keys_but_allows_plain_settings(self):
        # Only -c keys whose value git runs as a program are denied; ordinary
        # settings keep working (see the literal-value cases in the test above).
        for command in (
            "git -c user.name=Test log -1",
            "git -c user.name='A B' log -1",
            'git -c "user.name=A B" log -1',
            "git -c user.name='{a,b} *' log -1",
            'git -C . status',
            "git --no-pager log -1",
            "nice make",
            "sudo systemctl status",
            "git status",
            "command git status",
            "env git status",
            "echo git",
            "grep -r git README.md",
            # A command runner denies nothing itself: its command is checked.
            "nice make",
            "timeout 5 npm test",
            "timeout .5 make",
            "sudo -E -u root ls",
            'sudo -u "$USER" ls',
            "sudo -upostgres psql",
            "sudo -u postgres psql",
            "sudo -udeploy ls",
            "sudo -ujenkins make",
            "sudo -uDeploy ls",
            "sudo -h",
            "nice -n",
            "timeout infinity make",
            "timeout 1e3 make",
            "nohup npm run build",
            "time -p make",
            "nice time -p make",
            "sudo --preserve-env=PATH make install",
            "stdbuf -oL -eL python3 x.py",
            "watch -n 2 ls",
            "nice git status",
            "nice -n 5 git status",
            "watch git status",
            "command nice git status",
            "timeout 5 git log -1",
            "sudo apt install git",
            "sudo apt-get install -y git",
            "timeout 60 brew install git",
            "sudo -u git psql",
            "nice grep -r git README.md",
            "sudo ls vendor/git",
            "nohup npm run git",
            "watch -n 5 which git",
            "time -p grep git README.md",
            "time -p make git",
            # A program that only names git runs no git the guard could check.
            "which git",
            "type git",
            "hash git",
            "man git",
            "whereis git",
            "pgrep git",
            "brew install git",
            "apt-get install -y git",
            "gh pr create --title git",
            "gh repo clone cli/cli git",
            "pytest tests/git",
            "make git",
            "time git status",
            "git -c credential.helper= ls-remote origin",
            "git -c pager.status=false status",
            "git -c pager.log=false log -1",
            "git -c pager.diff=FALSE diff",
            "git -c pager.log= log -1",
            "git config pager.log",
            "git -c core.pagerx=1 status",
            "git config --get credential.helper",
            'git -C "." status',
            "git --git-dir=.git status",
            "git -c core.autocrlf=false status",
            'git -c "commit.gpgsign=false" log -1',
            # Disabling forms of a program key run no program.
            "git -c core.fsmonitor=false status",
            "git -c core.fsmonitor=FALSE status",
            "git -c core.fsmonitor status",
            "git -c filter.lfs.smudge= -c filter.lfs.process= checkout main",
            # Reading or unsetting a persisted key writes no program.
            "git config --unset core.fsmonitor",
            "git config unset core.fsmonitor",
            "git config --get core.fsmonitor",
            "git config core.fsmonitor",
            # A redirection after a bare read is no value.
            "git config core.fsmonitor 2>/dev/null",
            "git config core.hooksPath 2>/dev/null || true",
            "git config --global core.editor 2>/dev/null",
            "git config gpg.program 2>/dev/null",
            "git config core.fsmonitor >/dev/null",
            "git config core.fsmonitor > out.txt",
            "git config core.fsmonitor < /dev/null",
            "git config core.fsmonitor >/dev/null 2>&1",
            "git config --get core.fsmonitor 2>/dev/null",
            "git config --get core.hooksPath 2>/dev/null || true",
            "git config --get-all core.hooksPath 2>&1",
            "git config get core.editor 2>/dev/null",
            "git config --get core.fsmonitor --show-origin",
            "git config --get-urlmatch core.fsmonitor https://x",
            "git config --global --get core.editor",
            "git config --unset core.fsmonitor 2>/dev/null",
            "git config --unset-all core.fsmonitor",
            "git config unset core.fsmonitor 2>/dev/null",
            "git config --list",
            "git config -l > config.txt",
            "git config list",
            "git config user.name Test",
            # Plain quoted words are literal, with the characters in them.
            'git config user.name "Test User"',
            "git config user.name 'Test {a,b} *'",
            "git config --get 'core.fsmonitor'",
            'git config --get "core.hooksPath" 2>/dev/null',
            'git config user.name ""',
            "git config --get-regexp '^user\\.'",
            "git config \\\n  --get core.fsmonitor",
            # A joined word in another command leaves this one literal.
            "echo a\\\nb; git config user.name x",
            "git config user.name '#x'",
            "git \\\n  config --get user.name",
            'git "config" --get user.name',
        ):
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command))

    def test_allows_literal_dollar_in_git_arguments(self):
        # A $ that starts no expansion (a regex anchor, a price) is inert text.
        for command in (
            "git log --grep='fix$'",
            "git grep -n 'foo$'",
            "git log -G'foo$' --oneline",
            "git commit -m 'costs 5$'",
            "git branch --list 'feat$'",
            "git config --get-regexp 'user\\..*$'",
            "git log --format='%H$'",
        ):
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command))
        # In archive cwd only the archive read commands pass; grep, commit,
        # branch and config are denied there with or without a $.
        for command in (
            "git log --grep='fix$'",
            "git log -G'foo$' --oneline",
            "git log --format='%H$'",
        ):
            command = "cd .project/archive/001-mvp && " + command
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command))
        for command in (
            "git grep -n foo",
            "git commit -m costs",
            "git branch --list feat",
            "git config --get-regexp user",
        ):
            command = "cd .project/archive/001-mvp && " + command
            with self.subTest(command=command):
                self.assert_denied(self.bash(command))

    def test_denies_abbreviated_git_write_options_in_archive_context(self):
        for option in (
            "--ext-diff", "--ext-d", "--textconv", "--textc", "--tex", "--te",
            "--output=NOTE.md",
        ):
            with self.subTest(option=option):
                self.assert_denied(
                    self.bash(f"cd .project/archive/001-mvp && git diff {option}")
                )
        for command in (
            "cd .project/archive/001-mvp && git diff --stat",
            "cd .project/archive/001-mvp && git diff --text",
            "cd .project/archive/001-mvp && git log --text -1",
            "cd .project/archive/001-mvp && git show --text HEAD",
            "git diff --text .project/archive/001-mvp/plan/PLAN.md",
            "git log --text -- .project/archive/001-mvp/plan/PLAN.md",
        ):
            with self.subTest(command=command):
                self.assert_allowed(self.bash(command))

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


class PowerShellExpressionTests(unittest.TestCase):
    """PowerShell assignments parse; non-pure expressions stay denied (#468)."""

    assert_denied = GuardHookTests.assert_denied
    assert_allowed = GuardHookTests.assert_allowed

    def setUp(self) -> None:
        import tempfile
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name) / "repo"
        GuardHookTests.init_git_repo(self, self.repo)
        self.home = Path(temporary.name) / "home"
        self.home.mkdir()
        patcher = mock.patch.dict(
            os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def powershell(self, command):
        return {"tool_name": "PowerShell", "tool_input": {"command": command, "cwd": str(self.repo)}}

    def test_process_local_assignments_pass(self) -> None:
        for command in (
            '$env:PATH = "x"',
            "$build_root = C:/work/src",
            "$count = 5",
            '$env:PATH = "x"; Get-Location',
        ):
            with self.subTest(command=command):
                self.assert_allowed(self.powershell(command))

    def test_assignments_with_unresolvable_values_stay_denied(self) -> None:
        for command in (
            "$x = $y",
            "$x = $(Get-Content secret.txt)",
            "$env:PATH = $other",
            "$x = [System.IO.File]::ReadAllText('f')",
            # A bare-word value runs as a pipeline; it is judged as that command.
            "$x = git config core.fsmonitor evil",
            "$x = Remove-Item C:/Users/x/file.txt",
            "$x = iex foo",
        ):
            with self.subTest(command=command):
                self.assert_denied(self.powershell(command))

    def test_assignment_chained_with_a_destructive_command_stays_denied(self) -> None:
        self.assert_denied(
            self.powershell('$env:PATH = "x"; Remove-Item -Recurse ' + str(self.repo / ".project"))
        )

    def test_pure_static_members_pass_and_others_deny(self) -> None:
        self.assert_allowed(self.powershell("[Math]::Abs(-1)"))
        self.assert_allowed(self.powershell("[System.Math]::Max(1, 2)"))
        for command in (
            "[System.IO.File]::WriteAllText('x','y')",
            "[Environment]::SetEnvironmentVariable('a','b','Machine')",
            "[System.Net.WebClient]::new()",
        ):
            with self.subTest(command=command):
                self.assert_denied(self.powershell(command))

    def test_dynamic_execution_and_opaque_payloads_deny(self) -> None:
        for command in (
            'Invoke-Expression "Remove-Item -Recurse x"',
            'iex "Remove-Item -Recurse x"',
            "Add-Type -TypeDefinition 'class X {}'",
            "Start-Process notepad",
            "saps notepad",
            "New-Object System.Net.WebClient",
            "& $cmd",
            "& foo",
            "&foo",
            "1 | % { & foo }",
            "powershell -EncodedCommand YWJj",
            "pwsh -enc YWJj",
            # A script block executes its contents: the static call is an
            # argument of ForEach-Object, not an executable.
            "1 | ForEach-Object { [System.IO.File]::WriteAllText('x','y') }",
            "Get-ChildItem | ForEach-Object { iex $_.FullName }",
            "1 | % {iex x}",
            "1 | % {[System.IO.File]::WriteAllText('x','y')}",
            # Wrapped payloads are inspected with the same rules.
            "pwsh -Command '[System.IO.File]::WriteAllText(\"x\",\"y\")'",
        ):
            with self.subTest(command=command):
                self.assert_denied(self.powershell(command))

    def test_git_configuration_assignments_deny(self) -> None:
        # The PowerShell env form is refused exactly like the shell form:
        # it changes where Git reads its configuration.
        self.assert_denied(self.powershell("$env:GIT_CONFIG_GLOBAL = cfg; git status"))
        self.assert_denied(self.powershell("$env:GIT_CONFIG_COUNT = 1; git fetch origin"))


class DestructiveScopeTests(unittest.TestCase):
    """Out-of-repo scratch deletes pass; pipeline state stays protected (#468)."""

    status = GuardHookTests.status
    make_closed_milestone_repo = GuardHookTests.make_closed_milestone_repo
    bash_in = GuardHookTests.bash_in
    assert_denied = GuardHookTests.assert_denied
    assert_allowed = GuardHookTests.assert_allowed

    def setUp(self) -> None:
        import tempfile
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.scratch = Path(temporary.name).resolve() / "scratch"
        self.scratch.mkdir()
        (self.scratch / "file.txt").write_bytes(b"scratch\n")
        # A controlled home keeps the state-root check away from this machine's
        # real ~/.gsd-path tree.
        self.home = Path(temporary.name).resolve() / "home"
        self.home.mkdir()
        patcher = mock.patch.dict(
            os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def inside_closed(self, repo, command):
        return {"tool_name": "Bash", "tool_input": {"command": command, "cwd": str(repo)}}

    def test_closed_milestone_allows_out_of_repo_scratch_deletes(self) -> None:
        repo = self.make_closed_milestone_repo()
        target = self.scratch / "file.txt"
        for command in (f"rm {target.as_posix()}", f"rm -f {target.as_posix()}",
                        f"Remove-Item '{target.as_posix()}'"):
            with self.subTest(command=command):
                self.assert_allowed(self.inside_closed(repo, command))
        # The scratch directory itself is also outside every scope root.
        self.assert_allowed(self.inside_closed(repo, f"rm -r {self.scratch.as_posix()}"))

    def test_closed_milestone_keeps_denying_in_scope_deletes(self) -> None:
        repo = self.make_closed_milestone_repo()
        product = repo / "app.py"
        product.write_bytes(b"x\n")
        for command in (
            f"rm {product.as_posix()}",
            f"rm {(repo / '.project' / 'STATE.md').as_posix()}",
            f"rm {(repo / '.gsd-path' / 'runtime.json').as_posix()}",
        ):
            with self.subTest(command=command):
                self.assert_denied(self.inside_closed(repo, command))
        # Wildcards and variables never reach the scope check: the shape gate
        # refuses them first.
        self.assert_denied(self.inside_closed(repo, f"rm {self.scratch.as_posix()}/*.txt"))
        # A symlink into the repository resolves inside it.
        link = self.scratch / "link-to-repo"
        self.addCleanup(lambda: link.unlink() if link.is_symlink() else None)
        link.symlink_to(repo)
        self.assert_denied(self.inside_closed(repo, f"rm {(link / 'app.py').as_posix()}"))
        # A recursive delete of an ANCESTOR removes the repository (and any
        # state root) even though the operand itself classifies external.
        self.assert_denied(self.inside_closed(repo, f"rm -r {repo.parent.as_posix()}"))
        self.assert_denied(self.inside_closed(repo, f"rm -r {self.home.as_posix()}"))

    def test_state_roots_stay_protected_in_every_phase(self) -> None:
        state = self.home / ".gsd-path" / "runtimes" / "abc123"
        state.mkdir(parents=True)
        marker = state / "manifest.json"
        marker.write_bytes(b"{}\n")
        repo = self.make_closed_milestone_repo()
        # Closed milestone: the state root is inside pipeline scope.
        self.assert_denied(self.inside_closed(repo, f"rm {marker.as_posix()}"))
        self.assert_denied(self.inside_closed(repo, f"rm -r {state.as_posix()}"))
        # The same rule denies in an active phase, before the closed check runs.
        self.assert_denied(self.bash_in(repo, f"rm {marker.as_posix()}"))
        # A scratch file outside the state root still passes in an active phase.
        self.assert_allowed(self.bash_in(repo, f"rm {(self.scratch / 'file.txt').as_posix()}"))

    def test_managed_worktree_under_a_state_root_allows_its_own_deletes(self) -> None:
        repo = self.scratch / "primary"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
             "commit", "-q", "--allow-empty", "-m", "init"], check=True,
        )
        worktree = self.home / ".gsd-path" / "projects" / "A" / "B" / "task" / "t1"
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "t1", str(worktree)],
            check=True,
        )
        (worktree / "build").mkdir()
        for command in ("rm -rf build", f"rm -rf {(worktree / 'build').as_posix()}", "mv a.py b.py"):
            with self.subTest(command=command):
                self.assert_allowed(self.bash_in(worktree, command))
        # The checkout itself and state beside it stay protected.
        state = self.home / ".gsd-path" / "runtimes" / "abc123"
        state.mkdir(parents=True)
        for command in (f"rm -r {worktree.as_posix()}", f"rm -r {state.as_posix()}", f"rm -r {worktree.parent.as_posix()}"):
            with self.subTest(command=command):
                self.assert_denied(self.bash_in(worktree, command))

    def make_task_isolate(self, task_id):
        """A registered task worktree under a state root, with its dispatch
        authorization ref and pinned workspace receipt, plus its primary."""
        repo = self.scratch / f"primary-{task_id}"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
             "commit", "-q", "--allow-empty", "-m", "init"], check=True,
        )
        base = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, encoding="utf-8",
        ).stdout.strip()
        root = self.home / ".gsd-path" / "projects" / "A" / "B"
        worktree = root / "task" / task_id
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-q",
             "-b", f"gsd-path-task/{task_id}", str(worktree)],
            check=True,
        )
        receipts = repo / ".git" / "gsd-path" / "workspaces"
        receipts.mkdir(parents=True)
        (receipts / "primary.json").write_text(
            json.dumps({"primary": str(repo.resolve()), "root": str(root.resolve())}) + "\n",
            encoding="utf-8",
        )
        self.authorize_task(worktree, task_id, base)
        return repo, worktree

    def authorize_task(self, worktree, task_id, sha):
        subprocess.run(
            ["git", "-C", str(worktree), "update-ref",
             f"refs/gsd-path/task-authorizations/{task_id}", sha, "0" * len(sha)],
            check=True,
        )

    def test_authorized_task_isolate_allows_its_own_deletes_from_the_primary(self) -> None:
        repo, worktree = self.make_task_isolate("T002")
        (worktree / "openwiki").mkdir()
        # The hook's working directory is the primary; a parallel coder's
        # isolate is never among them (#546).
        self.assert_allowed(self.bash_in(repo, f"rm -rf {(worktree / 'openwiki').as_posix()}"))
        # A commit inside the isolate must not end acceptance.
        subprocess.run(
            ["git", "-C", str(worktree), "-c", "user.name=t", "-c", "user.email=t@example.com",
             "commit", "-q", "--allow-empty", "-m", "wip"], check=True,
        )
        (worktree / "build").mkdir()
        self.assert_allowed(self.bash_in(repo, f"rm -rf {(worktree / 'build').as_posix()}"))
        # The isolate root itself stays pipeline state.
        self.assert_denied(self.bash_in(repo, f"rm -r {worktree.as_posix()}"))
        # Without the authorization ref the same delete refuses again.
        subprocess.run(
            ["git", "-C", str(worktree), "update-ref", "-d",
             "refs/gsd-path/task-authorizations/T002"], check=True,
        )
        (worktree / "docs").mkdir()
        self.assert_denied(self.bash_in(repo, f"rm -rf {(worktree / 'docs').as_posix()}"))

    @requires_symlink
    def test_authorized_isolate_symlinked_operand_still_refused(self) -> None:
        repo, worktree = self.make_task_isolate("T005")
        (worktree / "safe").mkdir()
        outside = self.home / ".gsd-path" / "runtimes" / "abc123"
        outside.mkdir(parents=True)
        link = worktree / "linked"
        os.symlink(str(outside), str(link))
        # An accepted first operand must not let a symlinked second operand
        # through on the cached acceptance.
        self.assert_denied(
            self.bash_in(repo, f"rm -rf {(worktree / 'safe').as_posix()} {link.as_posix()}")
        )
        # The accepted operand alone still passes.
        self.assert_allowed(self.bash_in(repo, f"rm -rf {(worktree / 'safe').as_posix()}"))

    def test_rogue_task_worktree_without_authorization_stays_denied(self) -> None:
        repo, worktree = self.make_task_isolate("T003")
        rogue_root = worktree.parent
        rogue = rogue_root / "task" / "ROGUE"
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-q",
             "-b", "gsd-path-task/ROGUE", str(rogue)],
            check=True,
        )
        (rogue / "openwiki").mkdir()
        # Branch name, registration, and placement all match a task isolate;
        # only the unforgeable authorization ref is missing.
        self.assert_denied(self.bash_in(repo, f"rm -rf {(rogue / 'openwiki').as_posix()}"))

    def test_foreign_repository_task_worktree_stays_denied(self) -> None:
        # A session repo to stand in for the pipeline primary.
        repo, _worktree = self.make_task_isolate("T004")
        # A second repository under the session's control forges the whole
        # acceptance stack: task branch, registration, authorization ref,
        # and workspace receipt all live under ITS .git, which the guard
        # does not protect the way it protects the session repository's.
        foreign = self.scratch / "foreign"
        subprocess.run(["git", "init", "-q", "-b", "main", str(foreign)], check=True)
        subprocess.run(
            ["git", "-C", str(foreign), "-c", "user.name=t", "-c", "user.email=t@example.com",
             "commit", "-q", "--allow-empty", "-m", "init"], check=True,
        )
        base = subprocess.run(
            ["git", "-C", str(foreign), "rev-parse", "HEAD"],
            check=True, capture_output=True, encoding="utf-8",
        ).stdout.strip()
        root = self.home / ".gsd-path" / "projects" / "X" / "Y"
        worktree = root / "task" / "FRGN"
        subprocess.run(
            ["git", "-C", str(foreign), "worktree", "add", "-q",
             "-b", "gsd-path-task/FRGN", str(worktree)],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(worktree), "update-ref",
             "refs/gsd-path/task-authorizations/FRGN", base, "0" * len(base)],
            check=True,
        )
        receipts = foreign / ".git" / "gsd-path" / "workspaces"
        receipts.mkdir(parents=True)
        (receipts / "primary.json").write_text(
            json.dumps({"primary": str(foreign.resolve()), "root": str(root.resolve())}) + "\n",
            encoding="utf-8",
        )
        (worktree / "openwiki").mkdir()
        self.assert_denied(self.bash_in(repo, f"rm -rf {(worktree / 'openwiki').as_posix()}"))

    def test_legacy_and_unpinned_isolates_allow_their_own_deletes(self) -> None:
        configured = self.home / "worktrees"
        with mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(configured)}):
            primary = configured / "proj"
            subprocess.run(["git", "init", "-q", "-b", "main", str(primary)], check=True)
            subprocess.run(
                ["git", "-C", str(primary), "-c", "user.name=t", "-c", "user.email=t@example.com",
                 "commit", "-q", "--allow-empty", "-m", "init"], check=True,
            )
            base = subprocess.run(
                ["git", "-C", str(primary), "rev-parse", "HEAD"],
                check=True, capture_output=True, encoding="utf-8",
            ).stdout.strip()
            # Legacy layout beside the primary: <primary>.gsd-path/task/<id>,
            # preferred by worktree_path when registered.
            legacy = primary.parent / f"{primary.name}.gsd-path" / "task" / "T009"
            subprocess.run(
                ["git", "-C", str(primary), "worktree", "add", "-q",
                 "-b", "gsd-path-task/T009", str(legacy)],
                check=True,
            )
            self.authorize_task(legacy, "T009", base)
            (legacy / "build").mkdir()
            self.assert_allowed(self.bash_in(primary, f"rm -rf {(legacy / 'build').as_posix()}"))
            # Unpinned workspace shape: <root>/<id1>/<id2>/task/<id>, no receipt.
            unpinned = configured / "aa" / "bb" / "task" / "T010"
            subprocess.run(
                ["git", "-C", str(primary), "worktree", "add", "-q",
                 "-b", "gsd-path-task/T010", str(unpinned)],
                check=True,
            )
            self.authorize_task(unpinned, "T010", base)
            (unpinned / "build").mkdir()
            self.assert_allowed(self.bash_in(primary, f"rm -rf {(unpinned / 'build').as_posix()}"))

    def test_destructive_literal_paths_accept_non_ascii_letters(self) -> None:
        repo = self.scratch / "plain"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        (repo / "docs" / "7-计划与进展").mkdir(parents=True)
        self.assert_allowed(self.bash_in(repo, "rm -rf docs/7-计划与进展"))
        self.assert_allowed(self.bash_in(repo, f"rm -rf {(repo / 'docs/7-计划与进展').as_posix()}"))
        # Injection-relevant shapes stay refused.
        self.assert_denied(self.bash_in(repo, 'rm "scratch;other"'))
        self.assert_denied(self.bash_in(repo, 'rm "$var/whatever"'))

    def test_closed_milestone_checks_operands_after_double_dash(self) -> None:
        repo = self.make_closed_milestone_repo()
        target = self.scratch / "file.txt"
        self.assert_allowed(self.inside_closed(repo, f"rm -- {target.as_posix()}"))
        self.assert_denied(self.inside_closed(repo, f"rm -- {target.as_posix()} -foo"))

    def test_closed_milestone_protects_member_checkout_ancestors(self) -> None:
        repo = self.make_closed_milestone_repo()
        member = self.scratch / "members" / "app"
        member.mkdir(parents=True)
        (repo / ".project" / "MEMBERS.md").write_text(
            "# Members\n\n## app\n"
            f"Checkout: {member}\nRemote: https://github.com/example/app.git\n"
            "Integration: default\n",
            encoding="utf-8",
        )
        self.assert_denied(self.inside_closed(repo, f"rm -r {member.parent.as_posix()}"))
        self.assert_allowed(self.inside_closed(repo, f"rm {(self.scratch / 'file.txt').as_posix()}"))


class RuntimeHotfixRefGuardTests(unittest.TestCase):
    """Agent writes under refs/gsd-path/ forge the trust those refs prove (#480)."""

    def setUp(self) -> None:
        import tempfile
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        subprocess.run(("git", "init", "-q", "-b", "gsd-path/M001", str(self.repo)), check=True)
        (self.repo / ".project").mkdir()
        (self.repo / ".project" / "STATE.md").write_text(
            "---\npipeline: gsd-path/v2\nproject: demo\nmilestone: demo\nphase: build\n"
            "status: active\nbranch: gsd-path/M001\narchive: null\n---\n\n# Project State\n",
            encoding="utf-8",
        )
        subprocess.run(("git", "add", ".project/STATE.md"), cwd=self.repo, check=True, capture_output=True)
        subprocess.run(
            ("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"),
            cwd=self.repo, check=True, capture_output=True)

    def event(self, command: str):
        return {"tool_name": "Bash", "tool_input": {"command": command, "cwd": str(self.repo)}}

    def test_agent_cannot_create_a_runtime_hotfix_ref(self) -> None:
        status, output, error = run_guard(self.event(
            f"git update-ref refs/gsd-path/runtime-hotfix/T001-{'a' * 40} {'b' * 40}"))
        self.assertEqual(status, 2, error)
        self.assertIn("refs/gsd-path/", output)

    def test_agent_cannot_run_runtime_hotfix_in_any_command_shape(self) -> None:
        tail = f"runtime-hotfix --repo . --task-id T001 --runtime {'1' * 64} --authorized-by x"
        for command in (
            f"python3 scripts/isolation.py {tail}",
            f"py -3 scripts/isolation.py {tail}",
            f"python3 -I -B scripts/isolation.py {tail}",
            f"cd scripts && python3 isolation.py {tail}",
            f"true; python3 scripts/isolation.py {tail}",
            f"env A=1 python3 scripts/isolation.py {tail}",
            f"sh -c 'python3 scripts/isolation.py {tail}'",
            f"py -3 -B scripts/isolation.py {tail}",
            f"cd scripts && python3 -m isolation {tail}",
            f"python3 -B -m scripts.isolation {tail}",
            f"python3 - {tail} < scripts/isolation.py",
            f"python3 -Bm isolation {tail}",
            f"python3 -Im isolation {tail}",
            f"python3 -misolation {tail}",
            f"python3 --check-hash-based-pycs never scripts/isolation.py {tail}",
        ):
            with self.subTest(command=command):
                status, output, error = run_guard(self.event(command))
                self.assertEqual(status, 2, error + output)
                self.assertIn("operator-only", output)

    def test_read_only_mentions_of_runtime_hotfix_stay_allowed(self) -> None:
        for command in (
            "rg isolation.py -e runtime-hotfix",
            "python3 scripts/isolation.py --help runtime-hotfix",
            "python3 scripts/isolation.py preflight --task-id runtime-hotfix",
        ):
            with self.subTest(command=command):
                status, output, error = run_guard(self.event(command))
                self.assertEqual(status, 0, error + output)

    def test_git_mentions_of_runtime_hotfix_are_deliberately_denied(self) -> None:
        for command in (
            "git log --grep isolation.py --grep runtime-hotfix",
            'git commit -m "docs: explain runtime-hotfix"',
        ):
            with self.subTest(command=command):
                status, output, error = run_guard(self.event(command))
                self.assertEqual(status, 2, error + output)
                self.assertIn("refs/gsd-path/", output)

    def test_agent_cannot_push_or_fetch_into_path_owned_refs(self) -> None:
        ref = f"refs/gsd-path/runtime-hotfix/T001-{'a' * 40}"
        for command in (
            f"git push . {'b' * 40}:{ref}",
            f"git fetch . {'b' * 40}:{ref}",
            f"git fetch origin +refs/gsd-path/*:refs/gsd-path/*",
            f"git fetch --refmap=+refs/tags/*:refs/gsd-path/runtime-hotfix/* . refs/tags/T001",
            f"git symbolic-ref {ref} refs/tags/fake",
            f"git send-pack . {'b' * 40}:{ref}",
            "git log refs/gsd-path/checkpoint",
            f"git -c remote.self.url=. -c remote.self.push=refs/tags/fake:{ref} push self",
            f"REF={ref} git push . HEAD:refs/heads/ordinary",
            "git push . b:refs/{gsd-path,zz}/runtime-hotfix/T001-x",
            "git update-ref r{e,}fs/gs{d,}-path/runtime-hotfix/T001-x b",
            "git push . b:refs/gsd-pat[h]/runtime-hotfix/T001-x",
        ):
            with self.subTest(command=command):
                status, output, error = run_guard(self.event(command))
                self.assertEqual(status, 2, error + output)
                self.assertIn("refs/gsd-path/", output)

    def test_agent_can_still_push_ordinary_refspecs(self) -> None:
        for command in (
            "git push origin HEAD:refs/heads/ordinary-work",
            "git log -1 HEAD@{1}",
            "git push origin 'refs/heads/{a,b}'",
            "git add src/{a,b}.py",
            "git diff HEAD -- tests/test_{a,b}.py",
            "git checkout -- {a,b}.py",
            "git log HEAD~{1..3}",
            "git commit -m fix,{a,b}",
        ):
            with self.subTest(command=command):
                status, output, error = run_guard(self.event(command))
                self.assertEqual(status, 0, error + output)

    def test_agent_can_still_update_ordinary_refs(self) -> None:
        status, output, error = run_guard(self.event(
            "git update-ref refs/heads/ordinary-work " + "b" * 40))
        self.assertEqual(status, 0, error + output)


class SuccessorRuntimeAcceptanceTests(unittest.TestCase):
    """#468 option (i): on a closed milestone, helper acceptance follows the
    pinned runtime's hashed successors list — named runtimes run, everything
    else stays refused with the closed-milestone reason."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        environment = mock.patch.dict(
            os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.source = Path(__file__).resolve().parents[1]
        import runtime_store

        self.runtime_store = runtime_store
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "gsd-path/M001", str(self.repo)], check=True)
        subprocess.run(["git", "config", "user.name", "Guard test"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo, check=True)
        state = self.repo / ".project" / "STATE.md"
        state.parent.mkdir()
        state.write_text(
            "---\n"
            "pipeline: gsd-path/v2\n"
            "project: demo\n"
            "milestone: demo\n"
            "phase: shipped\n"
            "status: done\n"
            "branch: gsd-path/M001\n"
            "archive: .project/archive/001-demo\n"
            "---\n\n# Project State\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", ".project/STATE.md"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "ship: M001 — demo"], cwd=self.repo, check=True)

    def package(self, name: str, version: str) -> Path:
        """This package with its own version and a real byte difference."""
        package = self.root / name
        shutil.copytree(
            self.source / "scripts", package / "scripts",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copy2(self.source / "package.json", package / "package.json")
        data = json.loads((package / "package.json").read_text(encoding="utf-8"))
        data["version"] = version
        (package / "package.json").write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        helper = package / "scripts" / "pipeline_state.py"
        helper.write_bytes(helper.read_bytes() + f"# {name}\n".encode("utf-8"))
        return package

    def publish(self, package: Path, successors=()):
        return self.runtime_store.publish(package, successors=successors)

    def pin_repo(self, pin) -> None:
        guard_directory = self.repo / ".gsd-path"
        guard_directory.mkdir(exist_ok=True)
        (guard_directory / "runtime.json").write_text(
            self.runtime_store.pin_text(pin), encoding="utf-8"
        )
        for name in self.runtime_store.GUARDS:
            (guard_directory / name).write_text(
                self.runtime_store.guard_launcher(name), encoding="utf-8"
            )
        shutil.copyfile(
            self.source / "scripts" / "status_runtime.py",
            guard_directory / "status_runtime.py",
        )

    def guard(self, helper: Path):
        command = (
            f"python3 -B {shlex.quote(helper.as_posix())} "
            f"status --repo {shlex.quote(self.repo.as_posix())}"
        )
        payload = {"tool_name": "Bash", "tool_input": {"command": command, "cwd": str(self.repo)}}
        return subprocess.run(
            [sys.executable, "-B", str(self.repo / ".gsd-path" / "guard_hook.py")],
            cwd=self.repo, input=json.dumps(payload),
            encoding="utf-8", errors="replace", capture_output=True,
        )

    def helper(self, pin) -> Path:
        return (
            self.home / ".gsd-path" / "runtimes" / pin["digest"] / "pipeline_state.py"
        )

    def test_closed_milestone_accepts_only_hashed_successors(self) -> None:
        successor = self.publish(self.package("newer", "2.0.0"))
        unlisted = self.publish(self.package("unlisted", "3.0.0"))
        pin = self.publish(self.source, successors=(successor["digest"],))
        self.pin_repo(pin)

        for name, expected in (
            ("pinned", 0),
            ("named successor", 0),
            ("unlisted runtime", 2),
        ):
            with self.subTest(runtime=name):
                helper = {
                    "pinned": self.helper(pin),
                    "named successor": self.helper(successor),
                    "unlisted runtime": self.helper(unlisted),
                }[name]
                result = self.guard(helper)
                self.assertEqual(result.returncode, expected, result.stderr + result.stdout)

        denial = self.guard(self.helper(unlisted))
        self.assertIn("closed milestone", denial.stderr + denial.stdout)

    def test_successor_chains_walk_only_while_blessed_bytes_name_them(self) -> None:
        third = self.publish(self.package("third", "3.0.0"))
        second = self.publish(
            self.package("second", "2.0.0"), successors=(third["digest"],)
        )
        outsider = self.publish(self.package("outsider", "9.0.0"))
        pin = self.publish(self.source, successors=(second["digest"],))
        self.pin_repo(pin)

        for name, expected in (
            ("pinned", 0),
            ("first successor", 0),
            ("second successor", 0),
            ("unblessed runtime", 2),
        ):
            with self.subTest(runtime=name):
                helper = {
                    "pinned": self.helper(pin),
                    "first successor": self.helper(second),
                    "second successor": self.helper(third),
                    "unblessed runtime": self.helper(outsider),
                }[name]
                result = self.guard(helper)
                self.assertEqual(result.returncode, expected, result.stderr + result.stdout)

    def test_a_broken_named_successor_never_widens_or_breaks_the_pin(self) -> None:
        corrupt = self.publish(self.package("corrupt", "2.0.0"))
        missing = "a" * 64
        pin = self.publish(
            self.source, successors=(corrupt["digest"], missing)
        )
        # Break the named successor's bytes after publication.
        victim = self.home / ".gsd-path" / "runtimes" / corrupt["digest"] / "pipeline_state.py"
        victim.write_bytes(victim.read_bytes() + b"# tampered\n")
        self.pin_repo(pin)

        self.assertEqual(self.guard(self.helper(pin)).returncode, 0)
        self.assertEqual(self.guard(self.helper(corrupt)).returncode, 2)

    def test_a_divergent_launcher_cannot_widen_acceptance(self) -> None:
        successor = self.publish(self.package("divergent-newer", "2.0.0"))
        unlisted = self.publish(self.package("divergent-outsider", "3.0.0"))
        pin = self.publish(self.source, successors=(successor["digest"],))
        self.pin_repo(pin)
        # A drifted project launcher that accepts every store entry: the
        # walk must come from the pinned runtime's own bytes, not the
        # launcher's preloaded module (#468 review finding).
        launcher = self.repo / ".gsd-path" / "status_runtime.py"
        launcher.write_bytes(
            launcher.read_bytes()
            + b"\n\ndef accepted_runtime_dirs(repo):\n"
            b"    from pathlib import Path\n"
            b"    return {Path.home() / '.gsd-path' / 'runtimes'}\n"
        )

        self.assertEqual(self.guard(self.helper(pin)).returncode, 0)
        self.assertEqual(self.guard(self.helper(successor)).returncode, 0)
        denial = self.guard(self.helper(unlisted))
        self.assertEqual(denial.returncode, 2, denial.stderr + denial.stdout)
        self.assertIn("closed milestone", denial.stderr + denial.stdout)

    def test_a_stale_launcher_still_accepts_the_pinned_successors(self) -> None:
        successor = self.publish(self.package("stale-newer", "2.0.0"))
        unlisted = self.publish(self.package("stale-outsider", "3.0.0"))
        pin = self.publish(self.source, successors=(successor["digest"],))
        self.pin_repo(pin)
        # The project launcher predates successors: no walk of its own. The
        # guard loads the walk from the pinned runtime's bytes regardless.
        (self.repo / ".gsd-path" / "status_runtime.py").write_text(
            PRE_SUCCESSOR_LAUNCHER, encoding="utf-8")

        self.assertEqual(self.guard(self.helper(pin)).returncode, 0)
        self.assertEqual(self.guard(self.helper(successor)).returncode, 0)
        self.assertEqual(self.guard(self.helper(unlisted)).returncode, 2)


if __name__ == "__main__":
    unittest.main()
