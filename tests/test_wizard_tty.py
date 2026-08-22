"""End-to-end: `gsd-path` with no flags on a real TTY opens the wizard, which
hands off to the installer. Drives the wizard through a pty, then asserts the
dry-run output and exit code. Unix only (pty)."""

import os
import pty
import re
import select
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT_ROOT / "scripts" / "install.mjs"
ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")

DOWN, SPACE, ENTER = b"\x1b[B", b" ", b"\r"


@unittest.skipUnless(hasattr(os, "fork") and sys.platform != "win32", "needs a pty")
class WizardTtyTests(unittest.TestCase):
    def drive(self, keys, home, cwd, timeout=30):
        pid, fd = pty.fork()
        if pid == 0:  # child
            os.chdir(cwd)
            os.environ["HOME"] = str(home)
            os.environ.pop("NO_COLOR", None)
            os.execvp("node", ["node", str(INSTALLER)])
        out = b""
        deadline = time.time() + timeout
        exited = None

        def pump(seconds):
            nonlocal out, exited
            end = time.time() + seconds
            while time.time() < end:
                ready, _, _ = select.select([fd], [], [], 0.05)
                if ready:
                    try:
                        chunk = os.read(fd, 65536)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        return False
                    out += chunk
                if exited is None:
                    pid_done, status = os.waitpid(pid, os.WNOHANG)
                    if pid_done:
                        exited = status
            return True

        pump(1.0)
        for key in keys:
            os.write(fd, key)
            pump(0.3)
        while exited is None and time.time() < deadline and pump(0.2):
            pass
        if exited is None:
            _, exited = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(exited), ANSI.sub(b"", out).decode("utf-8", "replace")

    def test_wizard_dry_run_hands_off_to_installer(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp, "home")
            repo = Path(tmp, "repo")
            home.mkdir()
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            # local scope → toggle codex + claude → no contracts → dry run
            code, text = self.drive(
                [DOWN, ENTER, SPACE, DOWN, SPACE, ENTER, DOWN, ENTER, DOWN, ENTER],
                home,
                repo,
            )
        self.assertEqual(code, 0, text)
        self.assertIn("GSD Path", text)
        self.assertIn("gsd-path --codex --claude --local", text)
        self.assertIn("would install", text)
        self.assertIn("Dry run", text)
        self.assertFalse((repo / ".claude").exists())

    def test_wizard_quit_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp, "home")
            home.mkdir()
            code, text = self.drive([b"q"], home, tmp)
            self.assertEqual(code, 0, text)
            self.assertIn("Cancelled", text)
            self.assertEqual(sorted(os.listdir(tmp)), ["home"])
            self.assertEqual(os.listdir(home), [])


if __name__ == "__main__":
    unittest.main()
