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

    def claim(self, spec: Path) -> str:
        result = self.command(spec, "claim")
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)["claim"]

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
            claim = self.claim(spec)
            result = self.command(spec, "verify", "--claim", claim)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("pass", json.loads(result.stdout)["result"])

    def test_verify_requires_the_active_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            spec = write_spec(Path(temporary_directory))
            result = self.command(spec, "verify")
            self.assertEqual(2, result.returncode)
            self.assertIn("verify requires --claim", result.stderr)

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
            claim = self.claim(spec)
            result = self.command(spec, "verify", "--claim", claim)
            self.assertEqual(1, result.returncode)
            payload = json.loads(result.stdout)
            self.assertEqual("fail", payload["result"])
            self.assertEqual(1, len(payload["failures"]))
            self.assertEqual("echo boom && exit 3", payload["failures"][0]["command"])
            self.assertEqual(3, payload["failures"][0]["exit_code"])
            self.assertIn("boom", payload["failures"][0]["output_tail"])

    def test_verify_hung_command_fails_at_wall_clock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(
                root,
                BASE_SPEC.replace("verify: exit 0", "verify: sleep 5").replace(
                    "wall_clock: 30m", "wall_clock: 1s"
                ),
            )
            claim = self.claim(spec)
            result = self.command(spec, "verify", "--claim", claim)
            self.assertEqual(1, result.returncode)
            failure = json.loads(result.stdout)["failures"][0]
            self.assertIsNone(failure["exit_code"])
            self.assertIn("admitted wall-clock deadline", failure["output_tail"])

    def test_verify_shares_one_deadline_across_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(
                root,
                BASE_SPEC.replace(
                    "verify: exit 0",
                    "verify: sleep 0.7\nverify: sleep 0.7",
                ).replace("wall_clock: 30m", "wall_clock: 1s"),
            )
            claim = self.claim(spec)
            result = self.command(spec, "verify", "--claim", claim)
            self.assertEqual(1, result.returncode)
            payload = json.loads(result.stdout)
            self.assertEqual("fail", payload["result"])
            self.assertIn(
                "admitted wall-clock deadline",
                payload["failures"][0]["output_tail"],
            )

    def test_verify_uses_the_smaller_period_budget_admitted_to_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(
                root,
                BASE_SPEC.replace("trigger: manual", "trigger: manual\nperiod: 1d\nperiod_budget: 1s")
                .replace("verify: exit 0", "verify: sleep 5"),
            )
            claimed = self.command(spec, "claim")
            payload = json.loads(claimed.stdout)
            self.assertEqual(1, payload["remaining"]["wall_clock_seconds"])
            result = self.command(
                spec, "verify", "--claim", payload["claim"]
            )
            self.assertEqual(1, result.returncode)
            self.assertIn(
                "admitted wall-clock deadline",
                json.loads(result.stdout)["failures"][0]["output_tail"],
            )

    def test_claim_finish_then_status_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root)
            first_claim = self.claim(spec)
            verified = self.command(spec, "verify", "--claim", first_claim)
            self.assertEqual(0, verified.returncode, verified.stderr)
            first = self.command(
                spec, "finish", "--claim", first_claim, "--result", "pass"
            )
            self.assertEqual(0, first.returncode, first.stderr)
            second_claim = self.claim(spec)
            second = self.command(
                spec, "finish", "--claim", second_claim, "--result", "blocked", "--rescue",
                "--notes", "needed a human gate",
            )
            self.assertEqual(0, second.returncode, second.stderr)
            log = root / ".project" / "loop" / "demo.LOG.jsonl"
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(
                ["claim", "verify", "finish", "claim", "finish"],
                [record["event"] for record in records],
            )
            self.assertEqual(0, records[2]["iterations"])
            self.assertTrue(records[4]["rescue"])
            status = self.command(spec, "status")
            self.assertEqual(0, status.returncode, status.stderr)
            payload = json.loads(status.stdout)
            self.assertEqual(2, payload["runs"])
            self.assertEqual(1, payload["accepted"])
            self.assertEqual(1, payload["blocked"])
            self.assertEqual(1, payload["human_rescues"])
            self.assertIsNone(payload["active_claim"])

    def test_finish_requires_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root)
            result = self.command(spec, "finish")
            self.assertEqual(2, result.returncode, result.stdout)
            self.assertIn("finish requires --result", result.stderr)

    def test_claim_and_finish_are_append_only_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root)
            claimed = self.command(spec, "claim")
            self.assertEqual(0, claimed.returncode, claimed.stderr)
            claim = json.loads(claimed.stdout)["claim"]

            blocked = self.command(spec, "claim")
            blocked_payload = json.loads(blocked.stdout)
            self.assertEqual("skip", blocked_payload["decision"])
            self.assertNotIn("claim", blocked_payload)
            self.assertFalse(blocked_payload["recovery"]["recoverable"])
            self.assertGreaterEqual(blocked_payload["recovery"]["elapsed_seconds"], 0)
            self.assertEqual(
                1800, blocked_payload["recovery"]["wall_clock_limit"]
            )

            verified = self.command(spec, "verify", "--claim", claim)
            self.assertEqual(0, verified.returncode, verified.stderr)

            finished = self.command(
                spec,
                "finish",
                "--claim",
                claim,
                "--result",
                "pass",
            )
            self.assertEqual(0, finished.returncode, finished.stderr)
            repeated = self.command(
                spec,
                "finish",
                "--claim",
                claim,
                "--result",
                "pass",
            )
            self.assertEqual(0, repeated.returncode, repeated.stderr)
            self.assertEqual("already finished", json.loads(repeated.stdout)["reason"])

            log = root / ".project" / "loop" / "demo.LOG.jsonl"
            records = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(
                ["claim", "verify", "finish"],
                [record["event"] for record in records],
            )
            status = json.loads(self.command(spec, "status").stdout)
            self.assertEqual(1, status["runs"])
            self.assertEqual(1, status["accepted"])
            self.assertIsNone(status["active_claim"])

    def test_only_an_expired_claim_is_returned_for_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(
                root, BASE_SPEC.replace("wall_clock: 30m", "wall_clock: 1s")
            )
            claim = self.claim(spec)
            log = root / ".project/loop/demo.LOG.jsonl"
            record = json.loads(log.read_text(encoding="utf-8"))
            record["timestamp"] = (
                datetime.now(timezone.utc) - timedelta(seconds=2)
            ).isoformat()
            log.write_text(json.dumps(record) + "\n", encoding="utf-8")

            recovery = json.loads(self.command(spec, "claim").stdout)

            self.assertEqual("skip", recovery["decision"])
            self.assertEqual(claim, recovery["claim"])
            self.assertTrue(recovery["recovery"]["recoverable"])
            self.assertEqual(1, recovery["recovery"]["elapsed_seconds"])

    def test_recover_derives_a_failed_result_and_iterations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root, BASE_SPEC.replace("verify: exit 0", "verify: exit 1"))
            claim = self.claim(spec)
            self.assertEqual(1, self.command(spec, "verify", "--claim", claim).returncode)
            self.assertEqual(1, self.command(spec, "verify", "--claim", claim).returncode)
            log = root / ".project/loop/demo.LOG.jsonl"
            records = [json.loads(line) for line in log.read_text().splitlines()]
            records[0]["timestamp"] = (
                datetime.now(timezone.utc) - timedelta(seconds=1801)
            ).isoformat()
            log.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )

            recovered = self.command(spec, "recover", "--claim", claim)
            self.assertEqual(0, recovered.returncode, recovered.stderr)
            recovered_payload = json.loads(recovered.stdout)
            self.assertEqual("fail", recovered_payload["recorded"])
            self.assertEqual(1, recovered_payload["iterations"])
            repeated = self.command(spec, "recover", "--claim", claim)
            self.assertEqual(0, repeated.returncode, repeated.stderr)
            self.assertEqual("already recovered", json.loads(repeated.stdout)["reason"])
            finish = json.loads(log.read_text().splitlines()[-1])
            self.assertEqual("fail", finish["result"])
            self.assertEqual(1, finish["iterations"])

    def test_recover_closes_an_expired_claim_after_a_passing_verify(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root)
            claim = self.claim(spec)
            verified = self.command(spec, "verify", "--claim", claim)
            self.assertEqual(0, verified.returncode, verified.stderr)
            log = root / ".project/loop/demo.LOG.jsonl"
            records = [json.loads(line) for line in log.read_text().splitlines()]
            records[0]["timestamp"] = (
                datetime.now(timezone.utc) - timedelta(seconds=1801)
            ).isoformat()
            log.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )

            recovered = self.command(spec, "recover", "--claim", claim)

            self.assertEqual(0, recovered.returncode, recovered.stderr)
            finish = json.loads(log.read_text().splitlines()[-1])
            self.assertEqual("pass", finish["result"])
            self.assertEqual(0, finish["iterations"])

    def test_status_rejects_a_malformed_finish_record(self) -> None:
        mutations = {
            "missing timestamp": lambda record: record.pop("timestamp"),
            "wrong loop": lambda record: record.update(loop="other"),
            "wrong iterations": lambda record: record.update(iterations=1),
            "wrong wall clock": lambda record: record.update(wall_clock_used=1),
            "wrong result": lambda record: record.update(result="maybe"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                spec = write_spec(root)
                claim = self.claim(spec)
                log = root / ".project/loop/demo.LOG.jsonl"
                claim_record = json.loads(log.read_text())
                finish = {
                    "event": "finish",
                    "claim": claim,
                    "timestamp": claim_record["timestamp"],
                    "loop": "demo",
                    "trigger": "manual",
                    "iterations": 0,
                    "result": "blocked",
                    "wall_clock_used": 0,
                    "rescue": False,
                    "notes": "",
                }
                mutate(finish)
                append_log(root, [finish])

                result = self.command(spec, "status")

                self.assertEqual(2, result.returncode)
                self.assertTrue(result.stderr.strip())

    def test_concurrent_claims_admit_one_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root)
            command = [sys.executable, str(SCRIPT), "claim", "--spec", str(spec)]
            processes = [
                subprocess.Popen(
                    command,
                    cwd=root,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for _ in range(2)
            ]
            completed = [process.communicate() for process in processes]
            self.assertEqual([0, 0], [process.returncode for process in processes])
            payloads = [json.loads(stdout) for stdout, _stderr in completed]
            self.assertEqual(["run", "skip"], sorted(item["decision"] for item in payloads))
            admitted = next(item for item in payloads if item["decision"] == "run")
            rejected = next(item for item in payloads if item["decision"] == "skip")
            self.assertIn("claim", admitted)
            self.assertNotIn("claim", rejected)
            self.assertFalse(rejected["recovery"]["recoverable"])

    def test_verify_events_enforce_max_iterations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(
                root,
                BASE_SPEC.replace("verify: exit 0", "verify: exit 1").replace(
                    "max_iterations: 3", "max_iterations: 2"
                ),
            )
            claim = self.claim(spec)
            for expected_iteration in range(3):
                verified = self.command(spec, "verify", "--claim", claim)
                self.assertEqual(1, verified.returncode)
                self.assertEqual(
                    expected_iteration, json.loads(verified.stdout)["iteration"]
                )
            exhausted = self.command(spec, "verify", "--claim", claim)
            self.assertEqual(2, exhausted.returncode)
            self.assertIn("max_iterations", exhausted.stderr)
            wrong_count = self.command(
                spec,
                "finish",
                "--claim",
                claim,
                "--result",
                "fail",
                "--iterations",
                "1",
            )
            self.assertEqual(2, wrong_count.returncode)
            self.assertIn("helper-observed", wrong_count.stderr)
            finished = self.command(
                spec,
                "finish",
                "--claim",
                claim,
                "--result",
                "fail",
                "--iterations",
                "2",
            )
            self.assertEqual(0, finished.returncode, finished.stderr)

    def test_claim_uses_and_finish_enforces_remaining_period_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(
                root,
                BASE_SPEC.replace(
                    "trigger: manual", "trigger: manual\nperiod: 24h\nperiod_budget: 10m"
                ),
            )
            append_log(root, [log_record(age_seconds=60, wall_clock_used=480)])
            claimed = json.loads(self.command(spec, "claim").stdout)
            self.assertEqual(120, claimed["remaining"]["wall_clock_seconds"])
            claim = claimed["claim"]

            log = root / ".project/loop/demo.LOG.jsonl"
            records = [json.loads(line) for line in log.read_text().splitlines()]
            records[-1]["timestamp"] = (
                datetime.now(timezone.utc) - timedelta(seconds=121)
            ).isoformat()
            log.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )

            too_late = self.command(
                spec,
                "finish",
                "--claim",
                claim,
                "--result",
                "pass",
            )
            self.assertEqual(2, too_late.returncode)
            self.assertIn("wall clock", too_late.stderr)
            finished = self.command(
                spec,
                "finish",
                "--claim",
                claim,
                "--result", "blocked",
            )
            self.assertEqual(0, finished.returncode, finished.stderr)
            records = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertGreaterEqual(records[-1]["wall_clock_used"], 121)
            gated = json.loads(self.command(spec, "check").stdout)
            self.assertEqual("period budget exhausted", gated["reason"])

    def test_legacy_record_command_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            spec = write_spec(root)
            result = self.command(spec, "record", "--result", "pass")
            self.assertEqual(2, result.returncode)
            self.assertIn("invalid choice", result.stderr)

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

    def test_skill_claims_before_verify_and_finishes_the_exact_claim(self) -> None:
        skill = (ROOT / "skills" / "gsd-path-loop" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        process = skill.split("## Process", 1)[1].split("## Rules", 1)[0]

        self.assertLess(
            process.index("loop_run.py claim"),
            process.index("loop_run.py verify"),
        )
        self.assertIn("loop_run.py finish --spec <path> --claim", process)
        self.assertIn("verify --spec\n   <path> --claim <retained claim>", process)
        self.assertIn("derives elapsed time from the claim", process)
        self.assertNotIn("--used", process)


if __name__ == "__main__":
    unittest.main()
