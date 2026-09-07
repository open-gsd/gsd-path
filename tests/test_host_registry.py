import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.hosts import HostSpec, known_hosts, load  # noqa: E402

MANIFEST = json.loads((ROOT / "scripts" / "skill-resources.json").read_text())["hosts"]


class HostRegistryTests(unittest.TestCase):
    def test_every_manifest_host_has_a_module_matching_the_manifest(self):
        for host in known_hosts():
            with self.subTest(host=host):
                spec = load(host)
                self.assertIsInstance(spec, HostSpec)
                self.assertEqual(spec.name, host)
                self.assertEqual(spec.skill_root, MANIFEST[host]["local_root"])
                self.assertEqual(spec.guard_tier, MANIFEST[host]["guard_tier"])
                self.assertIn(spec.child_api, MANIFEST[host]["child_apis"])
                self.assertEqual(spec.install_flag, f"--{host}")
                self.assertTrue(spec.invocation.endswith("gsd-path"), spec.invocation)

    def test_modules_declare_live_verification_honestly(self):
        """Set GSD_LIVE_HOSTS to require live-verified host CLIs on PATH."""
        import shutil
        binaries = {"claude": "claude", "codex": "codex", "grok": "grok", "opencode": "opencode", "copilot": "copilot",
                    "qwen": "qwen", "antigravity": "antigravity", "cursor": "cursor", "zed": "zed", "kiro": "kiro", "kimi": "kimi"}
        for host in known_hosts():
            with self.subTest(host=host):
                spec = load(host)
                self.assertIsInstance(spec.verified_live, bool)
                if "GSD_LIVE_HOSTS" in os.environ and spec.verified_live:
                    self.assertIsNotNone(shutil.which(binaries[host]), f"{host} claims live verification without a CLI on PATH")

    def test_default_verification_does_not_require_host_clis(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("shutil.which", return_value=None):
            HostRegistryTests("test_modules_declare_live_verification_honestly").test_modules_declare_live_verification_honestly()

    def test_opt_in_verification_rejects_missing_host_cli(self):
        with mock.patch.dict(os.environ, {"GSD_LIVE_HOSTS": ""}), mock.patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(AssertionError, "claims live verification"):
                HostRegistryTests("test_modules_declare_live_verification_honestly").test_modules_declare_live_verification_honestly()

    def test_bind_child_reports_missing_evidence_as_lookup_error(self):
        import tempfile
        for host in known_hosts():
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "quick").mkdir()
                with self.assertRaises((LookupError, NotImplementedError)):
                    load(host).bind_child(Path(tmp), "build_t001")


if __name__ == "__main__":
    unittest.main()
