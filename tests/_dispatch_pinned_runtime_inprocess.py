"""In-process pinned-runtime reload test (run via subprocess from test_dispatch_driver).

The leading underscore keeps unittest discovery from running this module in
the shared test process. The test reloads runtime helper modules from a
temporary copy and must run in an isolated subprocess.
"""

import importlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import dispatch_driver

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PINNED_MARKER = "gsd-path-pinned-runtime-marker-209"


class DispatchPinnedRuntimeInProcessTests(unittest.TestCase):
    def test_activate_pinned_runtime_reloads_scripts_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / ".gsd-path").mkdir(parents=True)
            (repo / ".gsd-path/runtime.json").write_text('{"digest":"test"}', encoding="utf-8")
            runtime = Path(temp) / "runtime"
            shutil.copytree(
                PROJECT_ROOT / "scripts",
                runtime,
                ignore=shutil.ignore_patterns("__pycache__", "dev"),
            )
            marker = f"\nPINNED_RUNTIME_MARKER = '{PINNED_MARKER}'\n"
            (runtime / "isolation.py").write_bytes(
                (runtime / "isolation.py").read_bytes() + marker.encode("utf-8"))
            completed = subprocess.CompletedProcess([], 0, stdout=str(runtime))
            with mock.patch.object(dispatch_driver.subprocess, "run", return_value=completed):
                dispatch_driver._activate_pinned_runtime(repo)
            self.assertEqual(
                getattr(dispatch_driver.isolation, "PINNED_RUNTIME_MARKER", None),
                PINNED_MARKER,
            )
            self.assertIn(dispatch_driver.isolation.IsolationError, dispatch_driver.STOP_ERRORS)


if __name__ == "__main__":
    unittest.main()
