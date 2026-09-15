import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import dispatch_driver


ROOT = Path(__file__).resolve().parents[1]


class TaskContextTests(unittest.TestCase):
    def test_dispatch_supplies_context_without_a_second_intent_read(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            intent = repo / '.project/intent/INTENT.md'
            intent.parent.mkdir(parents=True)
            intent.write_text('## Success criteria\n\n1. First outcome.\n2. Other outcome.\n\n'
                              '## Constraints\n\nKeep the wire format.\n')
            task = repo / 'T001.md'
            task.write_text('## Intent coverage\n\n- SC1\n')
            brief = dispatch_driver.brief_text(
                dict(worktree=str(repo), task_id='T001', task_file='T001.md',
                     base='a' * 40, mode='serial'),
                ROOT / 'skills/gsd-path/references/coder.md',
                ROOT / 'skills/gsd-path/templates/task.md')
            self.assertIn('1. First outcome.', brief)
            self.assertIn('Keep the wire format.', brief)
            self.assertNotIn('2. Other outcome.', brief)
            self.assertIn('Mode: owned-criteria', brief)

    def test_cli_preserves_global_rules_and_only_projects_owned_criteria(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            intent = repo / '.project/intent/INTENT.md'
            intent.parent.mkdir(parents=True)
            task = repo / 'T001.md'
            task.write_text('# Task\n\n## Intent coverage\n\n- SC2\n')
            prefix = '# Intent\n\n## Summary\n\nKeep existing callers working.\n\n'
            suffix = ('## Scope: out (vetoes)\n\nNever publish customer data.\n\n'
                      '## Constraints\n\nUse the standard library.\n\n'
                      '## Corrections\n\nKeep compatibility.\n\n'
                      '## Owner extension\n\nPreserve this unknown section verbatim.\n')
            criteria = '## Success criteria\n\n1. Unrelated export works.\n2. Assigned command works.\n   Preserve multiline detail.\n\n'
            original = prefix + criteria + suffix
            intent.write_text(original)
            command = [sys.executable, '-B', str(ROOT / 'scripts/task_context.py'),
                       '--repo', str(repo), '--task', str(task)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(prefix, result.stdout)
            self.assertIn(suffix, result.stdout)
            self.assertIn('2. Assigned command works.\n   Preserve multiline detail.', result.stdout)
            self.assertNotIn('1. Unrelated export works.', result.stdout)
            self.assertIn(hashlib.sha256(original.encode()).hexdigest(), result.stdout)
            self.assertIn(str(intent), result.stdout)
            self.assertIn('Mode: owned-criteria', result.stdout)
            self.assertEqual(intent.read_text(), original)

            # Bundled commands must work outside the source repository, too.
            for skill in ('gsd-path', 'gsd-path-build', 'path'):
                bundled = command.copy()
                bundled[2] = str(ROOT / 'skills' / skill / 'scripts/task_context.py')
                installed = subprocess.run(bundled, cwd=repo, capture_output=True, text=True)
                self.assertEqual(installed.returncode, 0, installed.stderr)
                self.assertEqual(installed.stdout, result.stdout)

            intent.write_text(original.replace('Keep compatibility.', 'Keep SC1 unchanged.'))
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('1. Unrelated export works.', result.stdout)

            # Unstructured text could carry a constraint: retain the complete input.
            ambiguous = original.replace('1. Unrelated', 'Never remove any command.\n1. Unrelated')
            intent.write_text(ambiguous)
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Mode: full-intent', result.stdout)
            self.assertIn(ambiguous, result.stdout)

            task.write_text('## Intent coverage\n\n- SC99\n')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('SC99', result.stderr)
            self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
