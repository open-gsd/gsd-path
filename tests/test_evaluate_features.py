import json
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import evaluate_features as evaluation
from tests.evaluate_codex import ROOT, command


class FeatureEvaluationTests(unittest.TestCase):
    def test_prepare_pins_a_program_fixture_and_refuses_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            command(["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(candidate)], root)
            destination = root / "evaluation"
            result = evaluation.prepare(destination, candidate, ["program", "greenfield"])
            program_prompt = (destination / 'program/prompt.txt').read_text()
            greenfield_prompt = (destination / 'greenfield/prompt.txt').read_text()
            self.assertIn('It must observe lookahead', program_prompt)
            self.assertNotIn('It must observe lookahead', greenfield_prompt)
            repo = destination / "program/repo"
            self.assertEqual(result["candidate"], command(["git", "rev-parse", "HEAD"], candidate))
            self.assertTrue((repo / ".agents/skills/gsd-path/SKILL.md").is_file())
            self.assertFalse((repo / ".project").exists())
            self.assertEqual(command(["git", "remote", "get-url", "origin"], repo), str((destination / "program/origin.git").resolve()))
            broken = evaluation.evaluate_program(repo)
            self.assertEqual(broken["verdict"], "fail")
            self.assertGreater(len(broken["checks"]), 0)
            with self.assertRaisesRegex(ValueError, "already exists"):
                evaluation.prepare(destination, candidate, ["program"])

    def test_program_oracle_accepts_real_behavior_and_rejects_broken_filter(self):
        source = '''import csv, json, sys
from pathlib import Path
store, action, *args = sys.argv[1:]
path = Path(store)
rows = json.loads(path.read_text()) if path.exists() else []
try:
    if Path(__file__).name == 'ledger.py':
        if action == 'add':
            name, amount = args
            if not name or any(r['name'] == name for r in rows): raise ValueError('bad name')
            rows.append(dict(name=name, amount=int(amount)))
        elif action == 'remove':
            if not any(r['name'] == args[0] for r in rows): raise ValueError('missing')
            rows = [r for r in rows if r['name'] != args[0]]
        rows.sort(key=lambda r:r['name'])
        if action == 'list': print(json.dumps(rows))
        else: path.write_text(json.dumps(rows))
    else:
        if args: rows = [r for r in rows if r['name'].startswith(args[1])]
        if action == 'total': print(sum(r['amount'] for r in rows))
        else:
            writer = csv.writer(sys.stdout)
            writer.writerow(['name','amount'])
            writer.writerows((r['name'],r['amount']) for r in sorted(rows,key=lambda r:r['name']))
except (ValueError, IndexError) as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(2)
'''
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            for name in ('ledger.py', 'reports.py'): (repo / name).write_text(source)
            self.assertEqual(evaluation.evaluate_program(repo)['verdict'], 'pass')
            (repo / 'reports.py').write_text(source.replace("r['name'].startswith(args[1])", 'True'))
            self.assertEqual(evaluation.evaluate_program(repo)['verdict'], 'fail')

    def test_result_recorder_detects_subtest_failure_and_skip(self):
        class Broken(unittest.TestCase):
            def test_subtest(self):
                with self.subTest(case='failure'): self.assertEqual(1, 2)
            @unittest.skip('unavailable host')
            def test_skip(self): pass
            def test_pass(self): self.assertTrue(True)
        result = evaluation.run_tests(unittest.defaultTestLoader.loadTestsFromTestCase(Broken))
        statuses = result['tests']
        self.assertEqual(statuses[next(k for k in statuses if k.endswith('test_subtest'))], 'fail')
        self.assertEqual(statuses[next(k for k in statuses if k.endswith('test_skip'))], 'skip')
        self.assertEqual(statuses[next(k for k in statuses if k.endswith('test_pass'))], 'pass')

    def test_native_review_requires_live_evidence_and_invalidates_changed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'manifest.json').write_text(json.dumps({'candidate': 'abc', 'scenarios': ['program']}))
            arm = root / 'program'
            arm.mkdir()
            evidence = arm / 'captures.jsonl'
            evidence.write_text(json.dumps({'timestamp': '2026-09-05T10:00:00+00:00'}) + '\n')
            with self.assertRaisesRegex(ValueError, 'native run'):
                evaluation.record_review(root, 'lookahead', 'pass', [evidence], 'Evaluator checked the canonical receipts')
            run = arm / 'run-example'
            run.mkdir()
            (run / 'run.json').write_text(json.dumps({'exit_code': 0, 'elapsed_seconds': 1}))
            (run / 'events.jsonl').write_text(json.dumps({'raw': json.dumps({'type': 'thread.started', 'thread_id': 'fixture'})})+'\n')
            # The assessment is explicitly an operator judgment, never an automatic helper verdict.
            evaluation.record_review(root, 'lookahead', 'unverifiable', [evidence], 'Missing promotion')
            self.assertEqual(evaluation.report(root)['features']['lookahead']['native'], 'unverifiable')
            evidence.write_text(evidence.read_text() + json.dumps({'timestamp': '2026-09-05T11:00:00+00:00'}) + '\n')
            self.assertEqual(evaluation.report(root)['features']['lookahead']['native'], 'stale-review')

    def test_report_cannot_pass_lookahead_without_observed_promotions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'manifest.json').write_text(json.dumps({'candidate': 'abc', 'scenarios': ['program']}))
            (root / 'program').mkdir()
            (root / 'reviews.jsonl').write_text(json.dumps({
                'candidate': 'abc', 'feature': 'lookahead', 'verdict': 'pass', 'evidence': []}) + '\n')
            report = evaluation.report(root)
            self.assertNotEqual(report['features']['lookahead']['native'], 'pass')
            self.assertEqual(report['verdict'], 'incomplete')

    def test_product_receipt_rejects_changed_code_without_rerunning_oracle(self):
        from tests.test_evaluate_codex import GOOD_COUNTER
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'manifest.json').write_text(json.dumps({'candidate': 'abc', 'scenarios': ['quick']}))
            repo = root / 'quick/repo'
            repo.mkdir(parents=True)
            script = repo / 'count.py'
            script.write_text(GOOD_COUNTER)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(evaluation.main(['accept', '--directory', str(root), '--scenario', 'quick']), 0)
            self.assertEqual(evaluation.report(root)['scenarios']['quick']['product'], 'pass')
            script.write_text("print('broken')")
            self.assertEqual(evaluation.report(root)['scenarios']['quick']['product'], 'stale')

    def test_check_reuses_a_pinned_receipt_without_executing_tests_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / 'plugin'
            command(['git', 'clone', '--quiet', str(ROOT), str(plugin)], root)
            revision = command(['git', 'rev-parse', 'HEAD'], plugin)
            (root / 'manifest.json').write_text(json.dumps({'candidate': revision, 'scenarios': []}))
            saved = {'candidate': revision, 'exit_code': 0, 'tests': {'cached': 'pass'}}
            (root / 'automated.json').write_text(json.dumps(saved))
            self.assertEqual(evaluation.check(root), saved)
            self.assertFalse((root / 'automated-command.log').exists())
            (plugin / 'changed.txt').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'candidate changed'):
                evaluation.check(root)

    def test_skips_missing_and_failed_checks_never_become_passes(self):
        for actual, expected in [({}, "untested"), ({"a": "skip"}, "unverifiable"),
                                 ({"a": "fail"}, "fail"), ({"a": "pass"}, "pass")]:
            with self.subTest(actual=actual):
                self.assertEqual(evaluation.summarize_tests(actual, ["a"]), expected)
        self.assertEqual(evaluation.summarize_tests({"a": "pass"}, ["a", "b"]), "untested")

    def test_lookahead_needs_early_planning_and_observed_promotion(self):
        before = {"label": "m2-approved", "timestamp": "2026-09-05T10:00:00+00:00",
                  "state": {"phase": "build", "status": "active", "milestone": "storage"},
                  "next": {"phase": "plan", "status": "done", "milestone": "reports", "branch": None}}
        promoted = {"label": "m2-promoted", "timestamp": "2026-09-05T11:00:00+00:00",
                    "state": {"phase": "plan", "status": "done", "milestone": "reports"}, "next": None,
                    "promotion": {"milestone": "reports", "status": "promoted", "drift": {"class": "clean"}}}
        result = evaluation.lookahead_evidence([before, promoted])
        self.assertTrue(result["planning_during_build"])
        self.assertTrue(result["clean_promotion"])
        self.assertFalse(result["drift_reopened"])
        self.assertEqual(result["concurrent_agents"], "unverifiable")
        before["state"]["phase"] = "shipped"
        self.assertFalse(evaluation.lookahead_evidence([before, promoted])["planning_during_build"])
        self.assertFalse(evaluation.lookahead_evidence([before, promoted])["clean_promotion"])

    def test_drift_requires_matching_milestone_and_reopened_plan(self):
        before = {"timestamp": "2026-09-05T10:00:00+00:00",
                  "state": {"phase": "build", "status": "active", "milestone": "reports"},
                  "next": {"phase": "plan", "status": "done", "milestone": "filtering", "branch": None}}
        after = {"timestamp": "2026-09-05T11:00:00+00:00",
                 "state": {"phase": "plan", "status": "active", "milestone": "filtering"}, "next": None,
                 "promotion": {"milestone": "filtering", "status": "promoted", "drift": {"class": "changed"}}}
        self.assertTrue(evaluation.lookahead_evidence([before, after])["drift_reopened"])
        after["state"]["status"] = "done"
        self.assertFalse(evaluation.lookahead_evidence([before, after])["drift_reopened"])


if __name__ == "__main__":
    unittest.main()
