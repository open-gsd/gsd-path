import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import evaluate_codex as evaluation
from tests.dogfood import FIXTURE_SCRIPT
from tests.widget_acceptance import evaluate


GOOD_COUNTER = """import argparse, json
p = argparse.ArgumentParser()
p.add_argument('count', type=int, nargs='?', default=0)
p.add_argument('--json', action='store_true')
a = p.parse_args()
print(json.dumps({'widgets': a.count}) if a.json else f'{a.count} widgets')
"""


class EvaluationTests(unittest.TestCase):
    def test_runner_uses_and_pins_explicit_sandbox(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arm = root / "direct"
            repo = arm / "repo"
            repo.mkdir(parents=True)
            evaluation.command(["git", "init", "-q"], repo)
            evaluation.command(["git", "config", "user.name", "Test"], repo)
            evaluation.command(["git", "config", "user.email", "test@example.invalid"], repo)
            evaluation.command(["git", "commit", "--allow-empty", "-qm", "fixture"], repo)
            (arm / "prompt.txt").write_text("fixture prompt")
            binary = root / "bin"
            binary.mkdir()
            host = binary / "codex"
            host.write_text(f"#!{sys.executable}\nimport sys,json\n"
                            "if '--version' in sys.argv: print('fixture-cli')\n"
                            "else: print(json.dumps({'type':'turn.completed','usage':{'output_tokens':1},'argv':sys.argv,'prompt':sys.stdin.read()}))\n")
            host.chmod(0o755)
            arguments = [sys.executable, str(evaluation.ROOT / "tests/evaluate_codex.py"), "run", "--arm", str(arm),
                         "--model", "fixture", "--reasoning", "high", "--sandbox", "danger-full-access"]
            result = subprocess.run(arguments, capture_output=True, text=True, env={**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"]})
            self.assertEqual(result.returncode, 0, result.stderr)
            recorded = json.loads(result.stdout)
            self.assertEqual(recorded["sandbox"], "danger-full-access")
            events = next(arm.glob("run-*/events.jsonl"))
            event = json.loads(json.loads(events.read_text())["raw"])
            self.assertEqual(event["argv"][event["argv"].index("--sandbox") + 1], "danger-full-access")
            self.assertEqual(event["prompt"], "fixture prompt")

    def test_oracle_rejects_old_constant_and_wrong_json_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            script = repo / "count.py"
            for broken in (FIXTURE_SCRIPT, "print('3 widgets')\n",
                           GOOD_COUNTER.replace("{'widgets': a.count}", "{'widgets': str(a.count)}")):
                script.write_text(broken)
                self.assertEqual(evaluate(repo)["verdict"], "fail")
            script.write_text(GOOD_COUNTER)
            self.assertEqual(evaluate(repo)["verdict"], "pass")

    def test_activity_records_real_exit_and_missing_data_stays_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(json.dumps({"candidate": "fixture", "fixture": "fixture"}))
            for mode in ("path", "direct"):
                repo = root / mode / "repo"
                repo.mkdir(parents=True)
                subprocess.run(["git", "init", "-q", str(repo)], check=True)
                for key, value in (("user.name", "Test"), ("user.email", "test@example.invalid")):
                    evaluation.command(["git", "config", key, value], repo)
                (repo / "count.py").write_text(GOOD_COUNTER)
                evaluation.command(["git", "add", "."], repo)
                evaluation.command(["git", "commit", "-qm", "fixture"], repo)
            result = subprocess.run([sys.executable, str(evaluation.ROOT / "tests/evaluate_codex.py"), "activity",
                                     "--arm", str(root / "path"), "--category", "verification", "--",
                                     sys.executable, "-c", "raise SystemExit(7)"], capture_output=True)
            self.assertEqual(result.returncode, 7)
            summary = evaluation.report(root)
            path = summary["arms"]["path"]
            self.assertEqual(path["failed_commands"], 1)
            self.assertGreaterEqual(path["activity_seconds"]["verification"], 0)
            self.assertIsNone(path["activity_seconds"]["implementation"])
            self.assertIsNone(path["usage"])
            self.assertEqual(path["product"]["verdict"], "pass")
            self.assertEqual(path["pipeline"], "unverifiable")
            self.assertEqual(path["measurement"], "unavailable")
            self.assertTrue((root / "comparison.md").is_file())
            reported = subprocess.run([sys.executable, str(evaluation.ROOT / "tests/evaluate_codex.py"),
                                       "report", "--directory", str(root)], capture_output=True)
            self.assertEqual(reported.returncode, 3)
            (root / "direct/repo/count.py").write_text("print('wrong')\n")
            reported = subprocess.run([sys.executable, str(evaluation.ROOT / "tests/evaluate_codex.py"),
                                       "report", "--directory", str(root)], capture_output=True)
            self.assertEqual(reported.returncode, 1)

    def test_prepare_isolates_arms_at_same_product_base_and_refuses_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            evaluation.command(["git", "clone", "--quiet", "--no-hardlinks", str(evaluation.ROOT), str(candidate)], root)
            destination = root / "comparison"
            manifest = evaluation.prepare(destination, candidate)
            for mode in ("path", "direct"):
                repo = destination / mode / "repo"
                self.assertEqual((repo / "count.py").read_text(), FIXTURE_SCRIPT)
                evaluation.command(["git", "merge-base", "--is-ancestor", manifest["fixture"], "HEAD"], repo)
            self.assertTrue((destination / "path/repo/.agents/skills/gsd-path/SKILL.md").is_file())
            installation = json.loads((destination / "path/install.json").read_text())
            self.assertEqual(installation["exit_code"], 0)
            self.assertIn("installed", installation["output"])
            self.assertEqual(installation["candidate"], manifest["candidate"])
            self.assertFalse((destination / "direct/repo/.agents").exists())
            with self.assertRaisesRegex(ValueError, "already exists"):
                evaluation.prepare(destination, candidate)


if __name__ == "__main__":
    unittest.main()
