from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional


def pick_folder() -> Optional[str]:
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["osascript", "-e", "POSIX path of (choose folder)"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                return None
            return _clean(result.stdout)
        if sys.platform == "win32":
            script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "if ($dialog.ShowDialog() -eq 'OK') { $dialog.SelectedPath }"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                return None
            return _clean(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def _clean(output: str) -> Optional[str]:
    path = output.strip().rstrip("/\\")
    if not path:
        return None
    return os.path.abspath(os.path.expanduser(path))
