import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import loop_run


SCRIPT = ROOT / "scripts" / "loop_run.py"

BASE_SPEC = """\
# LOOP — demo

loop: demo
status: active
trigger: manual
verify: exit 0
max_iterations: 3
wall_clock: 30m
log: .project/loop/demo.LOG.jsonl

## Goal

Green.
"""


def write_spec(root: Path, body: str = BASE_SPEC) -> Path:
    spec = root / "LOOP.md"
    spec.write_text(body, encoding="utf-8")
    return spec


def append_log(root: Path, records: list[dict]) -> None:
    log = root / ".project" / "loop" / "demo.LOG.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def log_record(age_seconds: int = 0, wall_clock_used: int = 0, result: str = "pass") -> dict:
    return {
        "timestamp": (
            datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        ).isoformat(),
        "loop": "demo",
        "trigger": "manual",
        "iterations": 0,
        "result": result,
        "wall_clock_used": wall_clock_used,
        "rescue": False,
        "notes": "",
    }


class LoopRunTests(unittest.TestCase):
    def command(
        self, spec: Path, command: str, *extra: str, cwd: Optional[Path] = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), command, "--spec", str(spec), *extra],
            cwd=cwd or spec.parent,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_parse_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root)
            fields = loop_run.parse_spec(spec)
            self.assertEqual("demo", fields["loop"])
            self.assertEqual("active", fields["status"])
            self.assertEqual(["exit 0"], fields["verify"])
            self.assertEqual(3, fields["max_iterations"])
            self.assertEqual(1800, fields["wall_clock"])
            result = self.command(spec, "check")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("run", json.loads(result.stdout)["decision"])

    def test_parse_rejects_malformed_fields(self) -> None:
        malformed = [
            BASE_SPEC.replace("max_iterations: 3", "max_iterations: three"),
            BASE_SPEC.replace("max_iterations: 3", "max_iterations: 0"),
            BASE_SPEC.replace("wall_clock: 30m", "wall_clock: soon"),
            BASE_SPEC.replace("status: active", "status:"),
            BASE_SPEC.replace("status: active", "status: busy"),
            BASE_SPEC.replace("trigger: manual", "trigger: manual\ntrigger: event"),
            BASE_SPEC.replace("verify: exit 0\n", ""),
            BASE_SPEC + "period_budget: 4h\n",
        ]
        for body in malformed:
            with self.subTest(body=body):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    spec = write_spec(Path(temporary_directory), body)
                    result = self.command(spec, "check")
                    self.assertEqual(2, result.returncode, result.stdout)
                    self.assertTrue(result.stderr.strip())

    def test_check_paused_skips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root, BASE_SPEC.replace("status: active", "status: paused"))
            result = self.command(spec, "check")
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("skip", payload["decision"])
            self.assertEqual("status paused", payload["reason"])

    def test_check_cooldown_not_expired_skips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root, BASE_SPEC.replace("trigger: manual", "trigger: manual\ncooldown: 15m"))
            append_log(root, [log_record(age_seconds=60)])
            result = self.command(spec, "check")
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("skip", payload["decision"])
            self.assertIn("cooldown", payload["reason"])

    def test_check_cooldown_expired_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root, BASE_SPEC.replace("trigger: manual", "trigger: manual\ncooldown: 15m"))
            append_log(root, [log_record(age_seconds=3600)])
            result = self.command(spec, "check")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("run", json.loads(result.stdout)["decision"])

    def test_check_skip_when_exit_zero_skips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root, BASE_SPEC.replace("trigger: manual", "trigger: manual\nskip_when: exit 0"))
            result = self.command(spec, "check")
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("skip", payload["decision"])
            self.assertEqual("skip_when matched", payload["reason"])

    def test_check_skip_when_nonzero_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root, BASE_SPEC.replace("trigger: manual", "trigger: manual\nskip_when: exit 1"))
            result = self.command(spec, "check")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("run", json.loads(result.stdout)["decision"])

    def test_check_period_budget_exhausted_skips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(
                root,
                BASE_SPEC.replace(
                    "trigger: manual", "trigger: manual\nperiod: 24h\nperiod_budget: 1h"
                ),
            )
            append_log(root, [log_record(age_seconds=60, wall_clock_used=3600)])
            result = self.command(spec, "check")
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("skip", payload["decision"])
            self.assertEqual("period budget exhausted", payload["reason"])

    def test_check_period_budget_outside_window_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(
                root,
                BASE_SPEC.replace(
                    "trigger: manual", "trigger: manual\nperiod: 24h\nperiod_budget: 1h"
                ),
            )
            append_log(root, [log_record(age_seconds=172800, wall_clock_used=3600)])
            result = self.command(spec, "check")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("run", json.loads(result.stdout)["decision"])

    def test_verify_all_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root)
            result = self.command(spec, "verify")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("pass", json.loads(result.stdout)["result"])

    def test_verify_identifies_failing_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(
                root,
                BASE_SPEC.replace(
                    "verify: exit 0",
                    "verify: exit 0\nverify: echo boom && exit 3",
                ),
            )
            result = self.command(spec, "verify")
            self.assertEqual(1, result.returncode)
            payload = json.loads(result.stdout)
            self.assertEqual("fail", payload["result"])
            self.assertEqual(1, len(payload["failures"]))
            self.assertEqual("echo boom && exit 3", payload["failures"][0]["command"])
            self.assertEqual(3, payload["failures"][0]["exit_code"])
            self.assertIn("boom", payload["failures"][0]["output_tail"])

    def test_record_then_status_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root)
            first = self.command(
                spec, "record", "--result", "pass", "--iterations", "2", "--used", "5m"
            )
            self.assertEqual(0, first.returncode, first.stderr)
            second = self.command(
                spec, "record", "--result", "blocked", "--used", "10m", "--rescue",
                "--notes", "needed a human gate",
            )
            self.assertEqual(0, second.returncode, second.stderr)
            log = root / ".project" / "loop" / "demo.LOG.jsonl"
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(records))
            self.assertEqual(2, records[0]["iterations"])
            self.assertEqual(300, records[0]["wall_clock_used"])
            self.assertTrue(records[1]["rescue"])
            status = self.command(spec, "status")
            self.assertEqual(0, status.returncode, status.stderr)
            payload = json.loads(status.stdout)
            self.assertEqual(
                {
                    "loop": "demo",
                    "runs": 2,
                    "accepted": 1,
                    "rejected": 0,
                    "blocked": 1,
                    "skipped": 0,
                    "human_rescues": 1,
                    "wall_clock_used_seconds": 900,
                },
                payload,
            )

    def test_record_requires_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root)
            result = self.command(spec, "record")
            self.assertEqual(2, result.returncode, result.stdout)

    def test_trailing_html_comment_is_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(
                root,
                BASE_SPEC.replace("status: active", "status: active   <!-- active | paused | done -->"),
            )
            result = self.command(spec, "check")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("run", json.loads(result.stdout)["decision"])


if __name__ == "__main__":
    unittest.main()
