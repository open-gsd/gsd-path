import base64
import hashlib
import json
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_core.py"


class CoreMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.planning = self.repo / ".planning"
        self.planning.mkdir(parents=True)
        self.source = {
            "PROJECT.md": b"# Project\n## Out of scope\nNo payments\n",
            "STATE.md": b"---\ngsd_state_version: '1.0'\n---\nPhase: 2\n",
            "ROADMAP.md": b"- [x] foundation\n- [ ] delivery\n",
            "phases/02/PLAN.md": b"Unfinished work\r\n",
            "phases/01/SUMMARY.md": b"Completed evidence\n",
        }
        for name, content in self.source.items():
            target = self.planning / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    def run_command(self, command, *args):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), command, "--repo", str(self.repo), *args],
            capture_output=True, text=True,
        )

    def test_preview_is_read_only_and_hashes_all_history(self):
        result = self.run_command("preview")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(
            {entry["path"]: entry["sha256"] for entry in data["files"]},
            {name: hashlib.sha256(content).hexdigest() for name, content in self.source.items()},
        )
        self.assertEqual(list(self.repo.iterdir()), [self.planning])

    def test_prepare_preserves_bytes_and_does_not_claim_path_completion(self):
        output = self.root / "bundle"
        result = self.run_command("prepare", "--output", str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((output / "manifest.json").is_file(), result.stdout)
        for name, content in self.source.items():
            self.assertEqual((output / "core" / name).read_bytes(), content)
            self.assertEqual((self.planning / name).read_bytes(), content)
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "prepared")
        self.assertFalse(manifest["hooks_verified"])
        self.assertFalse((self.repo / ".project").exists())
        repeated = self.run_command("prepare", "--output", str(output))
        self.assertNotEqual(repeated.returncode, 0)
        self.assertEqual((output / "core/PROJECT.md").read_bytes(), self.source["PROJECT.md"])

    def test_rejects_empty_core_input_and_symlinks_without_output(self):
        for name in self.source:
            (self.planning / name).unlink()
        self.assertNotEqual(self.run_command("preview").returncode, 0)
        for name, content in self.source.items():
            (self.planning / name).write_bytes(content)
        (self.planning / "outside").symlink_to(self.root, target_is_directory=True)
        output = self.root / "bundle"
        result = self.run_command("prepare", "--output", str(output))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside", result.stderr)
        self.assertFalse(output.exists())

    def test_partial_and_quick_only_core_trees_are_preserved_with_missing_inputs(self):
        for name in self.source:
            (self.planning / name).unlink()
        quick = self.planning / "quick/001/PLAN.md"
        quick.parent.mkdir(parents=True)
        quick.write_bytes(b"Unfinished quick fix\n")
        output = self.root / "partial-bundle"
        result = self.run_command("prepare", "--output", str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["missing_inputs"], ["PROJECT.md", "REQUIREMENTS.md", "ROADMAP.md", "STATE.md"])
        self.assertEqual((output / "core/quick/001/PLAN.md").read_bytes(), quick.read_bytes())
        self.assertEqual(self.verify(output).returncode, 0)

    def test_rejects_output_inside_source_project(self):
        output = self.repo / "bundle"
        result = self.run_command("prepare", "--output", str(output))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_unreadable_nested_source_rejects_capture_without_output(self):
        phases = self.planning / "phases"
        mode = phases.stat().st_mode
        phases.chmod(0)
        try:
            for command in ("preview", "prepare"):
                with self.subTest(command=command):
                    output = self.root / "bundle"
                    args = ("--output", str(output)) if command == "prepare" else ()
                    result = self.run_command(command, *args)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Permission denied", result.stderr)
                    self.assertIn(str(phases), result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertFalse(output.exists())
        finally:
            phases.chmod(mode)

    def test_unreadable_nested_bundle_rejects_incomplete_manifest(self):
        output = self.root / "bundle"
        prepared = self.run_command("prepare", "--output", str(output))
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        manifest_path = output / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"] = [
            entry for entry in manifest["files"] if not entry["path"].startswith("phases/")
        ]
        manifest_path.write_text(json.dumps(manifest))
        phases = output / "core/phases"
        mode = phases.stat().st_mode
        phases.chmod(0)
        try:
            result = self.verify(output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Permission denied", result.stderr)
            self.assertIn(str(phases), result.stderr)
            self.assertEqual(result.stdout, "")
        finally:
            phases.chmod(mode)

    def test_hook_inventory_preserves_commands_plugins_and_settings(self):
        settings = self.root / "settings.json"
        content = json.dumps({
            "enabledPlugins": {"gsd-core@open-gsd": True, "gsd-path@open-gsd": True},
            "hooks": {"PreToolUse": [{"matcher": "Write", "hooks": [
                {"type": "command", "command": "node /tools/gsd-read-guard.js"},
                {"type": "command", "command": "company-guard"},
            ]}]},
            "statusLine": {"type": "command", "command": "node /tools/gsd-statusline.js"},
        })
        settings.write_text(content)
        output = self.root / "bundle"
        result = self.run_command("prepare", "--output", str(output), "--hook-settings", str(settings))
        self.assertEqual(result.returncode, 0, result.stderr)
        review = json.loads(result.stdout)["hook_review"]
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["settings"], str(settings))
        self.assertEqual(review[0]["plugins"]["gsd-core@open-gsd"], True)
        self.assertEqual([item["command"] for item in review[0]["commands"]], [
            "node /tools/gsd-read-guard.js", "company-guard", "node /tools/gsd-statusline.js",
        ])
        self.assertEqual(settings.read_text(), content)
        self.assertEqual(json.loads((output / "manifest.json").read_text())["hook_review"], review)
        self.assertFalse(json.loads(result.stdout)["hooks_verified"])

        for index, item in enumerate(review[0]["commands"]):
            with self.subTest(command=item["command"]):
                receipt = self.root / f"hook-{index}.json"
                planned = subprocess.run([
                    sys.executable, "-B", str(SCRIPT.with_name("core_hook_settings.py")),
                    "plan", "--settings", review[0]["settings"], "--repo", str(self.repo),
                    "--location", json.dumps(item["location"]), "--receipt", str(receipt),
                ], capture_output=True, text=True)
                self.assertEqual(planned.returncode, 0, planned.stderr)
                self.assertEqual(json.loads(planned.stdout)["status"], "planned")
                change = json.loads(receipt.read_text())
                self.assertEqual(change["original_command"], item["command"])
                self.assertEqual(base64.b64decode(change["before"]), content.encode())
                expected = json.loads(content)
                selected = expected
                for key in item["location"][:-1]:
                    selected = selected[key]
                selected[item["location"][-1]] = change["replacement_command"]
                self.assertNotEqual(change["replacement_command"], item["command"])
                self.assertEqual(json.loads(base64.b64decode(change["after"])), expected)
                self.assertEqual(settings.read_text(), content)

    def test_hook_inventory_rejects_invalid_settings_before_preparing(self):
        settings = self.root / "settings.json"
        for index, content in enumerate(("not json", "[]", '{"hooks": []}')):
            with self.subTest(content=content):
                output = self.root / f"bundle-{index}"
                settings.write_text(content)
                result = self.run_command("prepare", "--output", str(output), "--hook-settings", str(settings))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())

    def verify(self, output):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "verify", "--output", str(output)],
            capture_output=True, text=True,
        )

    def test_verify_bundle_rejects_changed_missing_and_extra_evidence(self):
        output = self.root / "bundle"
        prepared = self.run_command("prepare", "--output", str(output))
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        verified = self.verify(output)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout)["status"], "verified-bundle")
        self.assertFalse(json.loads(verified.stdout)["hooks_verified"])
        target = output / "core/phases/02/PLAN.md"
        target.write_text("Lost unfinished work")
        self.assertNotEqual(self.verify(output).returncode, 0)
        target.unlink()
        self.assertNotEqual(self.verify(output).returncode, 0)
        target.write_bytes(self.source["phases/02/PLAN.md"])
        extra = output / "core/extra.md"
        extra.write_text("unrecorded")
        self.assertNotEqual(self.verify(output).returncode, 0)
        extra.unlink()
        self.assertEqual(self.verify(output).returncode, 0)

    def test_verify_rejects_unowned_manifest_and_linked_evidence(self):
        output = self.root / "bundle"
        self.assertEqual(self.run_command("prepare", "--output", str(output)).returncode, 0)
        manifest_path = output / "manifest.json"
        original = manifest_path.read_bytes()
        data = json.loads(original)
        data["schema"] = "different-owner/v1"
        manifest_path.write_text(json.dumps(data))
        self.assertNotEqual(self.verify(output).returncode, 0)
        manifest_path.write_bytes(original)
        target = output / "core/PROJECT.md"
        target.unlink()
        target.symlink_to(self.planning / "PROJECT.md")
        self.assertNotEqual(self.verify(output).returncode, 0)

    def test_installed_migration_helper_preserves_and_verifies_core(self):
        root = SCRIPT.parent.parent
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                skills = self.root / host / "skills"
                installed = subprocess.run([
                    sys.executable, "-B", str(root / "scripts/install.py"),
                    f"--{host}", f"--{host}-root", str(skills),
                ], capture_output=True, text=True)
                self.assertEqual(installed.returncode, 0, installed.stderr)
                skill = skills / "gsd-path-migrate"
                self.assertTrue((skill / "SKILL.md").is_file())
                helper = skill / "scripts/migrate_core.py"
                output = self.root / f"{host}-bundle"
                prepared = subprocess.run([
                    sys.executable, "-B", str(helper), "prepare", "--repo", str(self.repo),
                    "--output", str(output),
                ], capture_output=True, text=True)
                self.assertEqual(prepared.returncode, 0, prepared.stderr)
                self.assertEqual((output / "core/phases/02/PLAN.md").read_bytes(), self.source["phases/02/PLAN.md"])
                verified = subprocess.run([
                    sys.executable, "-B", str(helper), "verify", "--output", str(output),
                ], capture_output=True, text=True)
                self.assertEqual(verified.returncode, 0, verified.stderr)
                self.assertEqual(json.loads(verified.stdout)["status"], "verified-bundle")
                settings = self.root / f"{host}-settings.json"
                settings.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
                    {"type": "command", "command": "exit 7"},
                ]}]}}))
                original = settings.read_bytes()
                receipt = self.root / f"{host}-receipt.json"
                settings_helper = skill / "scripts/core_hook_settings.py"
                for action in ("plan", "apply", "restore"):
                    argv = [sys.executable, "-B", str(settings_helper), action, "--receipt", str(receipt)]
                    if action == "plan":
                        argv += ["--settings", str(settings), "--repo", str(self.repo),
                                 "--location", '["hooks","PreToolUse",0,"hooks",0,"command"]']
                    changed = subprocess.run(argv, capture_output=True, text=True)
                    self.assertEqual(changed.returncode, 0, changed.stderr)
                    if action == "apply":
                        self.assertNotEqual(settings.read_bytes(), original)
                self.assertEqual(settings.read_bytes(), original)
                gate = skill / "scripts/core_hook_gate.py"
                command = shlex.join([sys.executable, "-c", "raise SystemExit(7)"])
                for cwd, expected in ((self.repo, 0), (self.root, 7)):
                    gated = subprocess.run([
                        sys.executable, "-B", str(gate), "--repo", str(self.repo), "--command", command,
                    ], input=json.dumps({"cwd": str(cwd)}), text=True, capture_output=True)
                    self.assertEqual(gated.returncode, expected, gated.stderr)


if __name__ == "__main__":
    unittest.main()
