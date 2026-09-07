import json
import sys
import unittest
from pathlib import Path

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
        # A module may only claim live verification when its CLI exists on this machine.
        import shutil
        binaries = {"claude": "claude", "codex": "codex", "grok": "grok", "opencode": "opencode", "copilot": "copilot",
                    "qwen": "qwen", "antigravity": "antigravity", "cursor": "cursor", "zed": "zed", "kiro": "kiro", "kimi": "kimi"}
        for host in known_hosts():
            with self.subTest(host=host):
                spec = load(host)
                if spec.verified_live:
                    self.assertIsNotNone(shutil.which(binaries[host]), f"{host} claims live verification without a CLI on PATH")

    def test_bind_child_reports_missing_evidence_as_lookup_error(self):
        import tempfile
        for host in known_hosts():
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "quick").mkdir()
                with self.assertRaises((LookupError, NotImplementedError)):
                    load(host).bind_child(Path(tmp), "build_t001")


if __name__ == "__main__":
    unittest.main()
