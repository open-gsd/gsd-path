import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import _common
from _platform import WINDOWS, fake_cli, posix_only, requires_bash, windows_only


def _hold_lock(path: str, ready, release) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import _common as common

    with common.exclusive_lock(Path(path)):
        ready.set()
        release.wait(30)


def _hold_directory_mutex(path: str, ready, release, crash: bool) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import _common as common

    with common.directory_mutex(Path(path)):
        ready.set()
        release.wait(30)
        if crash:
            os._exit(1)


class AtomicWriteTests(unittest.TestCase):
    def test_writes_lf_bytes_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "STATE.md"
            _common.atomic_write(path, "one\ntwo\n")
            self.assertEqual(path.read_bytes(), b"one\ntwo\n")
            self.assertFalse((Path(directory) / ".STATE.md.gsd-path-tmp").exists())

    def test_writes_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            _common.atomic_write(path, "café ✓\n")
            self.assertEqual(path.read_bytes(), "café ✓\n".encode("utf-8"))

    @windows_only
    def test_replaces_while_a_reader_holds_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "STATE.md"
            path.write_bytes(b"old\n")
            reader = open(path, "rb")
            threading_release = threading.Timer(0.2, reader.close)
            threading_release.start()
            try:
                _common.atomic_write(path, "new\n")
            finally:
                threading_release.join()
                reader.close()
            self.assertEqual(path.read_bytes(), b"new\n")


class ReplaceTests(unittest.TestCase):
    def test_non_busy_error_is_not_retried(self) -> None:
        error = PermissionError(13, "denied")
        error.winerror = 1920
        # Build paths before patching os.name: pathlib picks WindowsPath from it.
        source, destination = Path("a"), Path("b")
        with mock.patch.object(_common.os, "name", "nt"), \
                mock.patch.object(_common.os, "replace", side_effect=error) as replace:
            with self.assertRaises(PermissionError):
                _common.replace(source, destination)
        self.assertEqual(replace.call_count, 1)

    def test_busy_error_is_retried(self) -> None:
        error = PermissionError(13, "busy")
        error.winerror = 32
        source, destination = Path("a"), Path("b")
        with mock.patch.object(_common.os, "name", "nt"), \
                mock.patch.object(_common.time, "sleep"), \
                mock.patch.object(_common.os, "replace", side_effect=[error, error, None]) as replace:
            _common.replace(source, destination)
        self.assertEqual(replace.call_count, 3)


class FsyncDirectoryTests(unittest.TestCase):
    def test_accepts_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _common.fsync_directory(Path(directory))


class ExclusiveLockTests(unittest.TestCase):
    def test_second_process_is_refused_while_held(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.lock"
            context = multiprocessing.get_context("spawn")
            ready, release = context.Event(), context.Event()
            holder = context.Process(target=_hold_lock, args=(str(path), ready, release))
            holder.start()
            try:
                self.assertTrue(ready.wait(30))
                with self.assertRaises(BlockingIOError):
                    with _common.exclusive_lock(path, blocking=False):
                        pass
                with self.assertRaises(TimeoutError):
                    with _common.exclusive_lock(path, timeout=0.2):
                        pass
            finally:
                release.set()
                holder.join(30)
            with _common.exclusive_lock(path, blocking=False):
                pass

    def test_creates_parent_and_can_be_reacquired(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "state.lock"
            with _common.exclusive_lock(path):
                self.assertTrue(path.exists())
            with _common.exclusive_lock(path):
                pass


@windows_only
class DirectoryMutexTests(unittest.TestCase):
    def hold(self, directory: Path, crash: bool = False):
        context = multiprocessing.get_context("spawn")
        ready, release = context.Event(), context.Event()
        holder = context.Process(target=_hold_directory_mutex,
                                 args=(str(directory), ready, release, crash))
        holder.start()
        self.assertTrue(ready.wait(30))
        return holder, release

    def test_second_process_is_refused_while_held(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            holder, release = self.hold(Path(directory))
            try:
                with self.assertRaises(BlockingIOError):
                    with _common.directory_mutex(Path(directory), blocking=False):
                        pass
                with self.assertRaises(TimeoutError):
                    with _common.directory_mutex(Path(directory), timeout=0.3):
                        pass
            finally:
                release.set()
                holder.join(30)
            with _common.directory_mutex(Path(directory), blocking=False):
                pass

    def test_crashed_holder_releases_the_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            holder, release = self.hold(Path(directory), crash=True)
            release.set()
            holder.join(30)
            with _common.directory_mutex(Path(directory), timeout=5):
                pass

    def test_distinct_directories_do_not_contend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "a", Path(directory) / "b"
            first.mkdir()
            second.mkdir()
            holder, release = self.hold(first)
            try:
                with _common.directory_mutex(second, blocking=False):
                    pass
            finally:
                release.set()
                holder.join(30)


class ProcessAliveTests(unittest.TestCase):
    def test_current_process_is_alive(self) -> None:
        self.assertTrue(_common.process_alive(os.getpid()))

    def test_exited_process_is_not_alive(self) -> None:
        exited = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"],
                                capture_output=True, encoding="utf-8", errors="replace", check=True)
        self.assertFalse(_common.process_alive(int(exited.stdout)))

    def test_invalid_pids_are_not_alive(self) -> None:
        self.assertFalse(_common.process_alive(0))
        self.assertFalse(_common.process_alive(-1))

    @windows_only
    def test_never_signals_on_windows(self) -> None:
        with mock.patch.object(_common.os, "kill") as kill:
            _common.process_alive(os.getpid())
        kill.assert_not_called()


class KillTreeTests(unittest.TestCase):
    def test_kills_child_and_grandchild(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "grandchild.pid"
            script = textwrap.dedent(f"""
                import subprocess, sys, time
                grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
                open({str(pid_file)!r}, "w").write(str(grandchild.pid))
                time.sleep(60)
            """)
            process = _common.popen_group([sys.executable, "-c", script])
            try:
                deadline = time.monotonic() + 30
                while not pid_file.exists() or not pid_file.read_text(encoding="utf-8"):
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.05)
                grandchild = int(pid_file.read_text(encoding="utf-8"))
                self.assertTrue(_common.process_alive(grandchild))
                _common.kill_tree(process)
                process.wait(30)
                deadline = time.monotonic() + 10
                while _common.process_alive(grandchild) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(_common.process_alive(grandchild))
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


class BashTests(unittest.TestCase):
    @posix_only
    def test_posix_uses_bash_from_path(self) -> None:
        self.assertEqual(_common.bash_argv("true"), ["bash", "-c", "true"])

    @windows_only
    def test_windows_never_picks_the_wsl_launcher(self) -> None:
        system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "bash.exe")
        with mock.patch.dict(os.environ, {}, clear=False) as environment, \
                mock.patch.object(_common.shutil, "which",
                                  side_effect=lambda name: system32 if name == "bash" else None), \
                mock.patch.object(_common.os.path, "isfile", side_effect=lambda path: path == system32):
            environment.pop("GSD_PATH_BASH", None)
            with self.assertRaises(_common.ShellNotFound):
                _common.find_bash()

    @windows_only
    def test_windows_override_must_exist(self) -> None:
        with mock.patch.dict(os.environ, {"GSD_PATH_BASH": r"C:\missing\bash.exe"}):
            with self.assertRaises(_common.ShellNotFound):
                _common.find_bash()

    @requires_bash
    def test_runs_a_bash_command(self) -> None:
        result = subprocess.run(_common.bash_argv('printf "%s" "$((1 + 2))"'),
                                capture_output=True, encoding="utf-8", errors="replace", check=True)
        self.assertEqual(result.stdout, "3")

    @staticmethod
    def _long_mixed_quote_script() -> str:
        filler = "\n".join(
            f"# filler 'line' {index} \"quoted tail\" padding" for index in range(320)
        )
        return (
            "echo start-mixed-quotes\n"
            + filler
            + "\npython3 - <<'PY'\nprint('heredoc-ran')\nPY\n"
            + "echo trailing-end\n"
        )

    @posix_only
    def test_windows_emulation_runs_exact_bytes_from_a_temp_file(self) -> None:
        # #448: on Windows bash_argv writes the command to a temp .sh file,
        # because Git for Windows' bash truncates a quoted argv near 8 KB.
        # Emulate the nt branch on POSIX the way the module supports.
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        script = self._long_mixed_quote_script()
        self.assertGreater(len(script), 9000)
        with mock.patch.object(_common.os, "name", "nt"), \
                mock.patch.dict(os.environ, {"GSD_PATH_BASH": bash}):
            argv = _common.bash_argv(script)
        self.assertEqual(len(argv), 2)
        self.assertTrue(os.path.basename(argv[1]).startswith("gsd-path-command-"), argv[1])
        self.assertTrue(argv[1].endswith(".sh"), argv[1])
        self.assertEqual(os.path.dirname(argv[1]), os.path.realpath(tempfile.gettempdir()))
        self.assertEqual(Path(argv[1]).read_bytes(), script.encode("utf-8"))
        with mock.patch.object(_common.os, "name", "nt"), \
                mock.patch.dict(os.environ, {"GSD_PATH_BASH": bash}):
            other = _common.bash_argv(script)[1]
        self.assertNotEqual(other, argv[1])
        try:
            result = subprocess.run(argv, capture_output=True, encoding="utf-8",
                                    errors="replace", check=True)
            self.assertIn("start-mixed-quotes", result.stdout)
            self.assertIn("heredoc-ran", result.stdout)
            self.assertIn("trailing-end", result.stdout)
        finally:
            _common._remove_quietly(argv[1])
            _common._remove_quietly(other)
        self.assertFalse(Path(argv[1]).exists())

    @posix_only
    def test_windows_emulation_keeps_the_script_out_of_a_hostile_tmpdir(self) -> None:
        # A TMPDIR pointing into the tree being verified must not place the
        # script inside it: the file would dirty the worktree (#448).
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        here = os.path.realpath(os.getcwd())
        with mock.patch.dict(os.environ, {"TMPDIR": here, "GSD_PATH_BASH": bash}), \
                mock.patch.object(_common.os, "name", "nt"), \
                mock.patch.object(tempfile, "tempdir", None):
            guarded = _common.bash_argv("true")[1]
        try:
            resolved = os.path.realpath(guarded)
            self.assertNotEqual(resolved, here)
            self.assertFalse(resolved.startswith(here + os.sep), guarded)
        finally:
            _common._remove_quietly(guarded)

    @posix_only
    def test_windows_emulation_removes_the_script_at_process_exit(self) -> None:
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        child = textwrap.dedent(
            f"""
            import os, sys
            sys.path.insert(0, {str(ROOT / "scripts")!r})
            from unittest import mock
            import _common
            with mock.patch.object(_common.os, "name", "nt"), \\
                    mock.patch.dict(os.environ, {{"GSD_PATH_BASH": {bash!r}}}):
                path = _common.bash_argv("true")[1]
            print(path)
            print(os.path.exists(path))
            """
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", child],
            capture_output=True, encoding="utf-8", errors="replace", check=True,
        )
        path, existed = result.stdout.split()
        self.assertEqual(existed, "True")
        self.assertFalse(Path(path).exists())

    @windows_only
    def test_windows_runs_long_mixed_quote_script_in_full(self) -> None:
        script = self._long_mixed_quote_script()
        self.assertGreater(len(script), 9000)
        argv = _common.bash_argv(script)
        self.assertEqual(len(argv), 2)  # [bash, temp .sh file]; never -c with the whole script
        try:
            result = subprocess.run(argv, capture_output=True, encoding="utf-8",
                                    errors="replace")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("start-mixed-quotes", result.stdout)
            self.assertIn("heredoc-ran", result.stdout)
            # A truncated script used to end inside comments and pass silently.
            self.assertIn("trailing-end", result.stdout)
        finally:
            _common._remove_quietly(argv[1])


class ResolveArgvTests(unittest.TestCase):
    @posix_only
    def test_posix_is_unchanged(self) -> None:
        self.assertEqual(_common.resolve_argv(["codex", "exec"]), ["codex", "exec"])

    @windows_only
    def test_windows_finds_cmd_shims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shim = fake_cli(Path(directory), "fakecli", "import sys; print('ok', *sys.argv[1:])")
            with mock.patch.dict(os.environ, {"PATH": directory + os.pathsep + os.environ["PATH"]}):
                argv = _common.resolve_argv(["fakecli", "one"])
                self.assertEqual(Path(argv[0]).resolve(), shim.resolve())
                result = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace", check=True)
                self.assertEqual(result.stdout.strip(), "ok one")
                with self.assertRaises(ValueError):
                    _common.resolve_argv(["fakecli", "a & calc"])

    @windows_only
    def test_windows_missing_command(self) -> None:
        with self.assertRaises(FileNotFoundError):
            _common.resolve_argv(["gsd-path-no-such-command"])


class SplitCommandTests(unittest.TestCase):
    def test_splits_quoted_arguments(self) -> None:
        self.assertEqual(_common.split_command('coder --flag "two words"'),
                         ["coder", "--flag", "two words"])

    def test_empty(self) -> None:
        self.assertEqual(_common.split_command("   "), [])

    def test_single_quotes_group_as_in_sh(self) -> None:
        self.assertEqual(_common.split_command("codex exec '{model_args}' --json -"),
                         ["codex", "exec", "{model_args}", "--json", "-"])

    @windows_only
    def test_keeps_windows_backslashes(self) -> None:
        self.assertEqual(
            _common.split_command(r'C:\Python312\python.exe "C:\Program Files\x\coder.py" -v'),
            [r"C:\Python312\python.exe", r"C:\Program Files\x\coder.py", "-v"],
        )


class RmtreeForceTests(unittest.TestCase):
    def test_removes_read_only_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory) / "tree"
            (tree / "objects").mkdir(parents=True)
            target = tree / "objects" / "pack"
            target.write_bytes(b"x")
            target.chmod(0o444)
            _common.rmtree_force(tree)
            self.assertFalse(tree.exists())


class GitOutputEncodingTests(unittest.TestCase):
    def test_non_ascii_paths_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "café.md").write_bytes("x".encode("utf-8"))
            result = _common.run_git(repo, "-c", "core.quotepath=false", "ls-files", "--others", "-z")
            self.assertEqual(result.stdout.split("\0")[0], "café.md")

    def test_input_reaches_git_byte_exact(self) -> None:
        # A Windows text-mode pipe would send "\r\n" and hash different bytes.
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            text = "one\ntwo — ✓\n"
            (repo / "file.md").write_bytes(text.encode("utf-8"))
            from_file = _common.run_git(repo, "hash-object", "file.md").stdout.strip()
            from_input = _common.run_git(repo, "hash-object", "--stdin", input=text).stdout.strip()
            self.assertEqual(from_input, from_file)


class ProcessAliveCopyTests(unittest.TestCase):
    """status_runtime and install cannot import _common; their copies must not drift."""

    def function_source(self, path: Path, name: str) -> str:
        import ast

        text = path.read_bytes().decode("utf-8")
        node = next(item for item in ast.parse(text).body
                    if isinstance(item, ast.FunctionDef) and item.name == name)
        lines = text.splitlines(keepends=True)[node.lineno - 1:node.end_lineno]
        return "".join(lines).replace(f"def {name}(", "def process_alive(", 1)

    def test_copies_match(self) -> None:
        canonical = self.function_source(ROOT / "scripts" / "_common.py", "process_alive")
        self.assertEqual(self.function_source(ROOT / "scripts" / "status_runtime.py", "process_alive"),
                         canonical)
        self.assertEqual(self.function_source(ROOT / "scripts" / "install.py", "_process_alive"),
                         canonical)


class PopenDetachedTests(unittest.TestCase):
    def test_runs_and_reports_exit(self) -> None:
        process = _common.popen_detached([sys.executable, "-c", "raise SystemExit(3)"],
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
        self.assertEqual(process.wait(30), 3)

    @windows_only
    def test_falls_back_when_the_job_forbids_breakaway(self) -> None:
        real = subprocess.Popen
        calls = []

        def popen(argv, creationflags=0, **kwargs):
            calls.append(creationflags)
            if creationflags & _common._CREATE_BREAKAWAY_FROM_JOB:
                raise PermissionError(5, "Access is denied")
            return real(argv, creationflags=creationflags, **kwargs)

        with mock.patch.object(_common.subprocess, "Popen", side_effect=popen):
            process = _common.popen_detached([sys.executable, "-c", "pass"])
        self.assertEqual(process.wait(30), 0)
        self.assertEqual(len(calls), 2)
        self.assertFalse(calls[1] & _common._CREATE_BREAKAWAY_FROM_JOB)


class GitDrvfsWorkaroundTests(unittest.TestCase):
    @posix_only
    def test_drvfs_mount_adds_index_workaround_flags(self) -> None:
        mounts = "/dev/sda1 /mnt/c drvfs rw,relatime 0 0\n"
        repo = Path("/mnt/c/Users/demo/repo")
        with mock.patch.object(Path, "read_text", return_value=mounts), \
                mock.patch.object(_common.os, "name", "posix"):
            self.assertEqual(
                _common.git_drvfs_config_flags(repo),
                ("-c", "core.preloadindex=false", "-c", "index.threads=1"),
            )

    @posix_only
    def test_native_linux_mount_has_no_workaround(self) -> None:
        mounts = "/dev/sda1 / ext4 rw 0 0\n"
        repo = Path("/home/demo/repo")
        with mock.patch.object(Path, "read_text", return_value=mounts), \
                mock.patch.object(_common.os, "name", "posix"):
            self.assertEqual(_common.git_drvfs_config_flags(repo), ())

    def test_git_index_lock_retryable(self) -> None:
        self.assertTrue(_common.git_index_lock_retryable(
            "fatal: Unable to create '/repo/.git/index.lock': File exists."
        ))
        self.assertFalse(_common.git_index_lock_retryable("fatal: not a git repository"))


if __name__ == "__main__":
    unittest.main()
