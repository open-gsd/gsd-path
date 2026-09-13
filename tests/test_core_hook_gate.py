import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/core_hook_gate.py"


class CoreHookGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "path project"
        self.project.mkdir()
        self.core = self.root / "core project"
        self.core.mkdir()
        self.marker = self.root / "hook-ran"
        hook = self.root / "original.py"
        hook.write_text(
            "import pathlib, sys\n"
            f"pathlib.Path({str(self.marker)!r}).write_text('ran')\n"
            "sys.stdout.buffer.write(sys.stdin.buffer.read())\n"
            "sys.stderr.write('original hook error')\n"
            "raise SystemExit(2)\n"
        )
        self.command = shlex.join([sys.executable, str(hook)])

    def gate(self, payload):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--repo", str(self.project), "--command", self.command],
            input=payload, capture_output=True, cwd=self.core,
        )

    def test_migrated_project_and_subdirectories_skip_core_hook(self):
        nested = self.project / "src"
        nested.mkdir()
        for cwd in (self.project, nested):
            with self.subTest(cwd=cwd):
                result = self.gate(json.dumps({"cwd": str(cwd), "tool_name": "Write"}).encode())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"")
                self.assertFalse(self.marker.exists())

    def test_other_project_keeps_exact_payload_output_and_denial(self):
        payload = json.dumps({"cwd": str(self.core), "tool_name": "Write"}).encode() + b"\n"
        result = self.gate(payload)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, payload)
        self.assertEqual(result.stderr, b"original hook error")
        self.assertEqual(self.marker.read_text(), "ran")

    def test_uncertain_or_unrelated_cwd_does_not_bypass_core(self):
        for value in (b"bad json", b"null", b"{}", b'{"cwd":null}', b'{"cwd":"relative"}',
                      json.dumps({"cwd": str(self.project) + "-other"}).encode()):
            with self.subTest(value=value):
                self.assertEqual(self.gate(value).returncode, 2)

    def test_recorded_native_codex_events_are_scoped(self):
        trace = SCRIPT.parent.parent / "docs/trust-validation/evidence/releases/1.0.0/codex-quick-4295d75/guard/traced-hook-payloads.log"
        events = [json.loads(line) for line in trace.read_text().splitlines() if line.startswith("{")]
        self.assertTrue(events)
        for event in events:
            with self.subTest(tool=event["tool_name"]):
                self.assertTrue(Path(event["cwd"]).is_absolute())
                # Relocate the captured evaluation project into this fixture.
                event["cwd"] = str(self.project)
                self.assertEqual(self.gate(json.dumps(event).encode()).returncode, 0)
                event["cwd"] = str(self.core)
                self.assertEqual(self.gate(json.dumps(event).encode()).returncode, 2)


if __name__ == "__main__":
    unittest.main()
