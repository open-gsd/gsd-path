from __future__ import annotations

import subprocess
import sys


def _osascript_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str, enabled: bool = True) -> bool:
    if not enabled:
        return False
    try:
        if sys.platform == "darwin":
            script = (
                f'display notification "{_osascript_quote(message)}" '
                f'with title "{_osascript_quote(title)}"'
            )
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5, check=False)
            return True
        if sys.platform == "win32":
            return _notify_windows(title, message)
    except (OSError, subprocess.SubprocessError):
        return False
    return False


def _notify_windows(title: str, message: str) -> bool:
    def ps_quote(value: str) -> str:
        return value.replace("'", "''")

    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
        "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
        "$nodes = $template.GetElementsByTagName('text'); "
        f"$nodes.Item(0).AppendChild($template.CreateTextNode('{ps_quote(title)}')) | Out-Null; "
        f"$nodes.Item(1).AppendChild($template.CreateTextNode('{ps_quote(message)}')) | Out-Null; "
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('gsd-path-daemon').Show($toast)"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return True
        fallback = subprocess.run(
            ["msg", "*", f"{title}: {message}"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return fallback.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
