import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/core_hook_settings.py"


class HookSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.settings = self.root / "settings.json"
        self.receipt = self.root / "change.json"
        self.original_command = shlex.join([sys.executable, "-c", "raise SystemExit(7)"])
        self.original = json.dumps({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": self.original_command},
            {"type": "command", "command": "company-guard"},
        ]}]}, "enabledPlugins": {"gsd-path@marketplace": True}}, indent=4).encode()
        self.settings.write_bytes(self.original)

    def command(self, action):
        args = [sys.executable, "-B", str(SCRIPT), action, "--receipt", str(self.receipt)]
        if action == "plan":
            args += ["--settings", str(self.settings), "--repo", str(self.project),
                     "--location", '["hooks","PreToolUse",0,"hooks",0,"command"]']
        return subprocess.run(args, capture_output=True, text=True)

    def test_review_apply_execute_restore_and_preserve_unrelated_settings(self):
        planned = self.command("plan")
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertTrue(self.receipt.is_file(), planned.stdout)
        self.assertEqual(self.settings.read_bytes(), self.original)
        applied = self.command("apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        data = json.loads(self.settings.read_bytes())
        commands = data["hooks"]["PreToolUse"][0]["hooks"]
        self.assertNotEqual(commands[0]["command"], self.original_command)
        self.assertEqual(commands[1]["command"], "company-guard")
        self.assertEqual(data["enabledPlugins"], {"gsd-path@marketplace": True})
        for cwd, expected in ((self.project, 0), (self.root, 7)):
            result = subprocess.run(commands[0]["command"], shell=True,
                                    input=json.dumps({"cwd": str(cwd)}), text=True, capture_output=True)
            self.assertEqual(result.returncode, expected, result.stderr)
        self.assertEqual(self.command("apply").returncode, 0)
        self.assertEqual(self.command("restore").returncode, 0)
        self.assertEqual(self.settings.read_bytes(), self.original)
        self.assertEqual(self.command("restore").returncode, 0)

    def test_apply_and_restore_refuse_to_overwrite_later_changes(self):
        self.assertEqual(self.command("plan").returncode, 0)
        later = self.original + b"\n"
        self.settings.write_bytes(later)
        self.assertNotEqual(self.command("apply").returncode, 0)
        self.assertEqual(self.settings.read_bytes(), later)
        self.settings.write_bytes(self.original)
        self.assertEqual(self.command("apply").returncode, 0)
        later = self.settings.read_bytes() + b"\n"
        self.settings.write_bytes(later)
        self.assertNotEqual(self.command("restore").returncode, 0)
        self.assertEqual(self.settings.read_bytes(), later)

    def test_core_cutover_keeps_path_archive_guard_active(self):
        data = json.loads(self.original)
        path_command = shlex.join([sys.executable, "-B", str(SCRIPT.with_name("guard_hook.py"))])
        data["hooks"]["PreToolUse"][0]["hooks"][1]["command"] = path_command
        self.settings.write_text(json.dumps(data))
        self.assertEqual(self.command("plan").returncode, 0)
        self.assertEqual(self.command("apply").returncode, 0)
        hooks = json.loads(self.settings.read_bytes())["hooks"]["PreToolUse"][0]["hooks"]
        event = json.dumps({"cwd": str(self.project), "tool_name": "Write", "tool_input": {
            "file_path": str(self.project / ".project/archive/001-example/INTENT.md"), "content": "overwrite",
        }})
        results = [subprocess.run(hook["command"], shell=True, input=event, text=True, capture_output=True) for hook in hooks]
        self.assertEqual(results[0].returncode, 0, results[0].stderr)
        self.assertEqual(results[1].returncode, 2, results[1].stderr)
        self.assertEqual(json.loads(results[1].stdout)["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
