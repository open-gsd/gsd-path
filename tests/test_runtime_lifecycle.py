"""Behavioral contract for pinned runtime storage outside Git checkouts."""
import json
import os
import re
import shlex
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import install

SOURCE = Path(__file__).resolve().parents[1]


class RuntimeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "project"
        self.repo.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.environment = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Runtime test")
        self.git("config", "user.email", "runtime@example.invalid")
        (self.repo / "README.md").write_text("fixture\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")

    def git(self, *args, repo=None):
        return subprocess.check_output(
            ["git", "-c", "core.excludesFile=/dev/null", *args],
            cwd=repo or self.repo, text=True, stderr=subprocess.PIPE,
        ).strip()

    def provision(self):
        install.install(SOURCE, [], project=self.repo, migrate_legacy=False)

    def pin(self):
        return json.loads((self.repo / ".gsd-path/runtime.json").read_text())

    def runtime_command(self, option, source=SOURCE):
        return subprocess.run(
            [sys.executable, "-B", str(SOURCE / "scripts/install.py"),
             option, "--project", str(self.repo), "--source-root", str(source)],
            capture_output=True, text=True,
        )

    def test_install_keeps_runtime_outside_checkout(self):
        self.provision()
        self.assertTrue((self.repo / ".gsd-path/runtime.json").is_file())
        self.assertFalse((self.repo / ".gsd-path/runtime").exists())
        self.assertTrue((self.home / ".gsd-path/runtimes" / self.pin()["digest"] / "pipeline_state.py").is_file())

    def test_fresh_named_checkout_resolves_without_writes(self):
        self.provision()
        self.git("add", ".")
        self.git("commit", "-m", "project configuration")
        sidecar = self.root / "sidecar"
        self.git("worktree", "add", "-b", "gsd-path-verify/runtime", str(sidecar))
        result = subprocess.run(
            [sys.executable, "-B", str(sidecar / ".gsd-path/status_runtime.py"),
             "--repo", str(sidecar), "--runtime-path"], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()), self.home / ".gsd-path/runtimes" / self.pin()["digest"])
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all", repo=sidecar), "")

    def test_refresh_keeps_pin_and_upgrade_is_explicit(self):
        self.provision()
        before = (self.repo / ".gsd-path/runtime.json").read_bytes()
        altered = self.root / "source"
        shutil.copytree(SOURCE / "scripts", altered / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(SOURCE / "package.json", altered / "package.json")
        with (altered / "scripts/pipeline_state.py").open("a") as handle:
            handle.write("\n# different runtime version\n")
        with (altered / "scripts/status_runtime.py").open("a") as handle:
            handle.write("\n# compatible bootstrap update\n")
        install.install(SOURCE, [], project=self.repo, migrate_legacy=False, update=True)
        self.assertEqual((self.repo / ".gsd-path/runtime.json").read_bytes(), before)
        # Execute the upgrade recipe from the canonical ship skill.
        ship = (SOURCE / "skills/gsd-path-ship/SKILL.md").read_text()
        blocks = re.findall(r"```bash\n(.*?)```", ship, re.S)
        upgrade = next(block for block in blocks if block.lstrip().startswith("node <trusted-gsd-path>") and "<trust-root>" in block)
        resolver = next(block for block in blocks if "--runtime-path" in block and "<trust-root>" in block)
        for line in (upgrade + resolver).splitlines():
            if not line.strip():
                continue
            command = shlex.split(line.replace("<trusted-gsd-path>", str(altered)).replace("<trust-root>", str(self.repo)))
            if command[0] == "python3":
                command[0] = sys.executable
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if "--dry-run" in command:
                self.assertEqual((self.repo / ".gsd-path/runtime.json").read_bytes(), before)
            if "--runtime-path" in command:
                self.assertEqual(Path(result.stdout.strip()), self.home / ".gsd-path/runtimes" / self.pin()["digest"])
        self.assertNotEqual((self.repo / ".gsd-path/runtime.json").read_bytes(), before)
        self.assertTrue((self.home / ".gsd-path/runtimes" / json.loads(before)["digest"]).is_dir())
        (self.repo / ".project").mkdir()
        (self.repo / ".project/STATE.md").write_text(
            (SOURCE / "skills/gsd-path/templates/state.md").read_text().replace("<slug>", "fixture"))
        failures = [item for item in install.doctor(SOURCE, [], lambda _: self.root, self.repo)
                    if item["level"] == "fail"]
        self.assertEqual(failures, [])

    def test_failed_upgrade_restores_launcher_and_selection(self):
        self.provision()
        from scripts import runtime_store
        altered = self.root / "new-source"
        shutil.copytree(SOURCE / "scripts", altered / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(SOURCE / "package.json", altered / "package.json")
        with (altered / "scripts/status_runtime.py").open("a") as handle:
            handle.write("\n# compatible bootstrap update\n")
        pin = (self.repo / ".gsd-path/runtime.json").read_bytes()
        launcher = (self.repo / ".gsd-path/status_runtime.py").read_bytes()
        write = runtime_store.atomic_config
        def fail_selection(path, content):
            if path.name == "runtime.json":
                raise OSError("injected selection write failure")
            return write(path, content)
        with mock.patch.object(runtime_store, "atomic_config", side_effect=fail_selection):
            with self.assertRaisesRegex(OSError, "injected selection"):
                runtime_store.operate(altered, self.repo, "upgrade")
        self.assertEqual((self.repo / ".gsd-path/runtime.json").read_bytes(), pin)
        self.assertEqual((self.repo / ".gsd-path/status_runtime.py").read_bytes(), launcher)

    def test_missing_runtime_fails_read_only_then_explicit_restore(self):
        self.provision()
        pin = self.pin()
        self.git("add", ".")
        self.git("commit", "-m", "project configuration")
        shutil.rmtree(self.home / ".gsd-path/runtimes" / pin["digest"])
        result = subprocess.run(
            [sys.executable, "-B", str(self.repo / ".gsd-path/status_runtime.py"),
             "--repo", str(self.repo)], capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--runtime-restore", result.stderr)
        self.assertIn(pin["digest"], result.stderr)
        self.assertFalse((self.home / ".gsd-path/runtimes" / pin["digest"]).exists())
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all"), "")

        restored = self.runtime_command("--runtime-restore")
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(self.pin(), pin)
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all"), "")

    def test_node_installer_uses_same_external_store(self):
        script = "import {install} from './scripts/install.mjs'; await install(process.cwd(), [], {project: process.argv[1], migrateLegacy:false});"
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(self.repo)],
                                cwd=SOURCE, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.repo / ".gsd-path/runtime").exists())
        self.assertTrue((self.home / ".gsd-path/runtimes" / self.pin()["digest"]).is_dir())

    def test_tracked_migration_leaves_reviewable_deletions_and_working_launcher(self):
        runtime = self.repo / ".gsd-path/runtime"
        runtime.mkdir(parents=True)
        for name in install.PROJECT_RUNTIME_SCRIPTS:
            shutil.copy2(SOURCE / "scripts" / name, runtime / name)
        for name in (*install.GUARD_SCRIPTS, "status_runtime.py"):
            shutil.copy2(SOURCE / "scripts" / name, runtime.parent / name)
        self.git("add", ".")
        self.git("commit", "-m", "legacy runtime")
        result = self.runtime_command("--runtime-migrate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(runtime.exists())
        self.assertIn(" D .gsd-path/runtime/pipeline_state.py", self.git("status", "--porcelain"))
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        command = subprocess.run([sys.executable, "-B", str(runtime.parent / "git_guard.py"), "pre-commit"],
                                 cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(command.returncode, 0, command.stderr)

    def test_modified_legacy_runtime_is_preserved(self):
        runtime = self.repo / ".gsd-path/runtime"
        runtime.mkdir(parents=True)
        for name in install.PROJECT_RUNTIME_SCRIPTS:
            shutil.copy2(SOURCE / "scripts" / name, runtime / name)
        shutil.copy2(SOURCE / "scripts/status_runtime.py", runtime.parent / "status_runtime.py")
        self.git("add", ".")
        self.git("commit", "-m", "legacy runtime")
        changed = runtime / "pipeline_state.py"
        changed.write_text(changed.read_text() + "\n# user edit\n")
        before = changed.read_bytes()
        result = self.runtime_command("--runtime-migrate")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("locally modified", result.stderr)
        self.assertEqual(changed.read_bytes(), before)
        self.assertFalse((runtime.parent / "runtime.json").exists())

    def test_corrupt_runtime_can_be_explicitly_restored(self):
        self.provision()
        runtime = self.home / ".gsd-path/runtimes" / self.pin()["digest"]
        (runtime / "pipeline_state.py").write_text("broken\n")
        result = self.runtime_command("--runtime-restore")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((runtime / "pipeline_state.py").read_bytes(), (SOURCE / "scripts/pipeline_state.py").read_bytes())


    def test_migration_resumes_after_process_exit(self):
        runtime = self.repo / ".gsd-path/runtime"
        runtime.mkdir(parents=True)
        for name in install.PROJECT_RUNTIME_SCRIPTS:
            shutil.copy2(SOURCE / "scripts" / name, runtime / name)
        shutil.copy2(SOURCE / "scripts/status_runtime.py", runtime.parent / "status_runtime.py")
        self.git("add", ".")
        self.git("commit", "-m", "legacy runtime")
        code = """
import os, sys
from pathlib import Path
from scripts import runtime_store
original = runtime_store.atomic_config
def crash(path, content):
    original(path, content)
    if path.name == 'runtime.json':
        os._exit(77)
runtime_store.atomic_config = crash
runtime_store.operate(Path(sys.argv[1]), Path(sys.argv[2]), 'migrate')
"""
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        result = subprocess.run([sys.executable, "-B", "-c", code, str(SOURCE), str(alias / self.repo.name)], cwd=SOURCE)
        self.assertEqual(result.returncode, 77)
        self.assertTrue(list((self.home / ".gsd-path/runtime-migrations").glob("*.json")))
        resumed = self.runtime_command("--runtime-migrate")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertFalse(runtime.exists())
        self.assertEqual(list((self.home / ".gsd-path/runtime-migrations").glob("*.json")), [])

    def test_status_and_git_guard_execute_in_named_checkouts(self):
        self.provision()
        # Install the stable guard wiring through the normal opt-in entry point.
        install.refresh_hooks(SOURCE, self.repo, True, selected=["claude"], initialize=True)
        (self.repo / ".project").mkdir()
        state = (SOURCE / "skills/gsd-path/templates/state.md").read_text().replace("<slug>", "fixture")
        (self.repo / ".project/STATE.md").write_text(state)
        self.git("add", ".")
        self.git("-c", "core.hooksPath=/dev/null", "commit", "-m", "runtime wiring")
        for branch in ("gsd-path-task/T001", "gsd-path-verify/check", "gsd-path-integrate/M001"):
            with self.subTest(branch=branch):
                checkout = self.root / branch.replace("/", "-")
                self.git("worktree", "add", "-b", branch, str(checkout))
                # Status reads the inherited project state from this worktree.
                result = subprocess.run([sys.executable, "-B", str(checkout / ".gsd-path/status_runtime.py"),
                                         "--repo", str(checkout)], cwd=checkout, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsInstance(json.loads(result.stdout), dict)
                guard = subprocess.run([sys.executable, "-B", str(checkout / ".gsd-path/git_guard.py"), "pre-commit"],
                                       cwd=checkout, capture_output=True, text=True)
                self.assertEqual(guard.returncode, 0, guard.stderr)
                self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all", repo=checkout), "")

    def test_wrong_source_cannot_restore_selected_runtime(self):
        self.provision()
        altered = self.root / "wrong-source"
        shutil.copytree(SOURCE / "scripts", altered / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(SOURCE / "package.json", altered / "package.json")
        with (altered / "scripts/pipeline_state.py").open("a") as handle:
            handle.write("\n# another version\n")
        before = self.pin()
        result = self.runtime_command("--runtime-restore", altered)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source does not match declared runtime", result.stderr)
        self.assertEqual(self.pin(), before)

    def test_publication_lock_is_released_after_process_exit(self):
        self.provision()
        runtime = self.home / ".gsd-path/runtimes" / self.pin()["digest"]
        code = """
import os, sys
from pathlib import Path
from scripts.runtime_store import publication_lock
with publication_lock(Path(sys.argv[1]).parent, Path(sys.argv[1]).name):
    os._exit(77)
"""
        result = subprocess.run([sys.executable, "-B", "-c", code, str(runtime)], cwd=SOURCE)
        self.assertEqual(result.returncode, 77)
        (runtime / "pipeline_state.py").write_text("incomplete")
        restored = self.runtime_command("--runtime-restore")
        self.assertEqual(restored.returncode, 0, restored.stderr)

    def test_missing_runtime_guard_fails_without_writes(self):
        self.provision()
        install.refresh_hooks(SOURCE, self.repo, True, selected=["claude"], initialize=True)
        self.git("add", ".")
        self.git("commit", "-m", "guard wiring")
        runtime = self.home / ".gsd-path/runtimes" / self.pin()["digest"]
        shutil.rmtree(runtime)
        result = subprocess.run([sys.executable, "-B", str(self.repo / ".gsd-path/git_guard.py"), "pre-commit"],
                                cwd=self.repo, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--runtime-restore", result.stderr)
        self.assertFalse(runtime.exists())
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all"), "")

    def test_native_guard_trusts_only_selected_runtime_helpers(self):
        self.provision()
        install.refresh_hooks(SOURCE, self.repo, True, selected=["claude"], initialize=True)
        helper = self.home / ".gsd-path/runtimes" / self.pin()["digest"] / "pipeline_state.py"
        foreign = self.root / "pipeline_state.py"
        shutil.copyfile(helper, foreign)
        for candidate, expected in ((helper, 0), (foreign, 2)):
            with self.subTest(candidate=candidate):
                payload = {"tool_name": "Bash", "tool_input": {
                    "command": f"python3 -B {shlex.quote(str(candidate))} --archive .project/archive/001-x",
                    "workdir": str(self.repo),
                }}
                result = subprocess.run([sys.executable, "-B", str(self.repo / ".gsd-path/guard_hook.py")],
                                        cwd=self.repo, input=json.dumps(payload), text=True, capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)


    def test_helpers_without_B_keep_runtime_and_checkout_clean(self):
        self.provision()
        self.git("add", ".")
        self.git("commit", "-m", "runtime")
        runtime = self.home / ".gsd-path/runtimes" / self.pin()["digest"]
        environment = dict(os.environ)
        environment.pop("PYTHONDONTWRITEBYTECODE", None)
        environment.pop("PYTHONPYCACHEPREFIX", None)
        for name in install.PROJECT_RUNTIME_SCRIPTS:
            with self.subTest(helper=name):
                result = subprocess.run([sys.executable, "-X", "pycache_prefix=", str(runtime / name), "--help"],
                                        cwd=self.repo, env=environment, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((runtime / "__pycache__").exists(), name)
        self.assertEqual(install.status_runtime.resolve_runtime(self.repo), runtime)
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all"), "")

    def test_atomic_config_preserves_bytes_with_windows_text_semantics(self):
        writer = install.runtime_store
        fdopen = os.fdopen
        def windows_fdopen(fd, mode, *args, **kwargs):
            if mode == "w":
                kwargs["newline"] = "\r\n"
            return fdopen(fd, mode, *args, **kwargs)
        target = self.root / "config"
        with mock.patch.object(writer.os, "fdopen", side_effect=windows_fdopen):
            writer.atomic_config(target, "first\nsecond\n")
        self.assertEqual(target.read_bytes(), b"first\nsecond\n")

    def test_restore_preserves_declaration_annotations(self):
        self.provision()
        pin = self.pin()
        pin["comment"] = "project annotation"
        declaration = self.repo / ".gsd-path/runtime.json"
        declaration.write_text(json.dumps(pin))
        original = declaration.read_bytes()
        self.assertTrue(install.status_runtime.resolve_runtime(self.repo).is_dir())
        result = self.runtime_command("--runtime-restore")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(declaration.read_bytes(), original)

    def test_hook_preview_rejects_same_foreign_guard_as_apply(self):
        directory = self.repo / ".gsd-path"
        directory.mkdir()
        guard = directory / "guard_hook.py"
        guard.write_text("user guard\n")
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                with self.assertRaisesRegex(install.InstallerError, "not a managed GSD Path guard"):
                    install.refresh_hooks(SOURCE, self.repo, True, dry_run, ["claude"], True)
                self.assertEqual(guard.read_text(), "user guard\n")
                self.assertFalse((directory / "runtime.json").exists())


if __name__ == "__main__":
    unittest.main()
