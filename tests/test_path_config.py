import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import detect_project, model_policy
from tests.test_pipeline_state import state_text

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/path_config.py'
CAPS = {'host': 'codex', 'model': {'field': 'model', 'values': ['example']},
        'effort': {'field': 'reasoning_effort', 'values': ['high', 'low']}}


class PathConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.repo = self.home / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-b', 'gsd-path/M001', str(self.repo)],
                       check=True, capture_output=True)
        (self.repo / '.project').mkdir()
        self.state = self.repo / '.project/STATE.md'
        self.state.write_text(state_text(phase='define', status='active', branch='gsd-path/M001'))
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'USERPROFILE': str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def profile(self, data):
        path = self.home / '.gsd-path/config.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data))
        return path

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, '-B', str(HELPER), *args,
                                 '--repo', str(self.repo)], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_user_models_affect_new_assignments_only(self):
        self.profile({'models': {'roles': {'coder': {'model': 'example'}}}})
        first = model_policy.resolve(self.repo, '.project', 'coder', CAPS, {})
        self.assertEqual(first['selected']['model'], 'example')
        self.profile({'models': {'roles': {'coder': {'model': 'inherit'}}}})
        pinned = model_policy.resolve(self.repo, '.project', 'coder', CAPS, {}, previous=first)
        self.assertEqual(pinned['selected']['model'], 'example')
        self.assertEqual(model_policy.resolve(self.repo, '.project', 'coder', CAPS, {})['selected']['model'], 'inherit')

    def test_new_state_uses_user_shipping_default(self):
        self.profile({'integration': 'pull-request'})
        template = (ROOT / 'skills/gsd-path/templates/state.md').read_text()
        text = detect_project.filled_state_template(template, 'demo', 'define')
        self.assertIn('integration_default: pull-request', text)
        self.assertIn('integration: pull-request', text)

    def test_cli_shipping_and_build_lock(self):
        self.cli('set', 'integration', 'pull-request')
        shown = self.cli('show')
        self.assertEqual(shown['settings']['integration']['value'], 'pull-request')
        self.state.write_text(state_text(phase='build', status='active', branch='gsd-path/M001'))
        before = self.state.read_bytes()
        self.assertIn('locked', self.cli('set', 'integration', 'pull-request', ok=False)['error'])
        self.assertEqual(self.state.read_bytes(), before)

    def test_review_preferences_do_not_rewrite_approved_contracts(self):
        intent = self.repo / '.project/intent/INTENT.md'
        intent.parent.mkdir()
        intent.write_text('Review panel: off\n')
        plan = self.repo / '.project/plan/PLAN.md'
        plan.parent.mkdir()
        plan.write_text('- review_panel: gpt\n')
        self.cli('set', 'review_panel', 'detected')
        shown = self.cli('show')
        self.assertEqual(shown['settings']['review_panel']['value'], 'detected')
        self.assertEqual(intent.read_text(), 'Review panel: off\n')
        self.assertEqual(shown['approved_review_panel']['value'], 'gpt')
        self.assertEqual(shown['approved_review_panel']['source'], 'plan')
        self.assertEqual(plan.read_text(), '- review_panel: gpt\n')

    def test_model_precedence_and_reset(self):
        self.cli('set', 'models.hosts.codex.coder.effort', 'high', '--scope', 'user')
        self.cli('set', 'models.roles.coder.effort', 'low')
        resolved = model_policy.resolve(self.repo, '.project', 'coder', CAPS, {})
        self.assertEqual(resolved['selected']['effort'], 'low')
        self.cli('set', 'models.roles.coder.effort', 'inherit')
        self.assertEqual(model_policy.resolve(self.repo, '.project', 'coder', CAPS, {})['selected']['effort'], 'inherit')
        self.cli('reset', 'models.roles.coder.effort')
        self.assertEqual(model_policy.resolve(self.repo, '.project', 'coder', CAPS, {})['selected']['effort'], 'high')

    def test_invalid_and_unsafe_writes_leave_files_unchanged(self):
        path = self.profile({'review_panel': 'off'})
        before = path.read_bytes()
        for key, value in [('review_panel', 'unknown'), ('models.roles.typo.model', 'example'),
                           ('integration', 'anything'), ('phase', 'build')]:
            self.cli('set', key, value, '--scope', 'user', ok=False)
            self.assertEqual(path.read_bytes(), before)
        config = self.repo / '.project/config.json'
        config.symlink_to(path)
        self.cli('set', 'review_panel', 'detected', ok=False)
        self.assertEqual(path.read_bytes(), before)

    def test_show_is_read_only_and_malformed_config_fails_loudly(self):
        paths = sorted(str(p) for p in self.home.rglob('*'))
        self.cli('show')
        self.assertEqual(sorted(str(p) for p in self.home.rglob('*')), paths)
        path = self.profile({})
        path.write_text('{bad')
        self.cli('validate', ok=False)
        self.cli('set', 'review_panel', 'off', '--scope', 'user', ok=False)
        self.assertEqual(path.read_text(), '{bad')

    def test_closed_branch_remains_locked_if_live_state_is_rewritten(self):
        from scripts.pipeline_git import ship_subject
        self.state.write_text(state_text(phase='shipped', status='done', milestone='demo',
                              branch='gsd-path/M001', archive='.project/archive/001-demo'))
        for args in [('add', '.'), ('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                                  'commit', '-m', ship_subject('001-demo'))]:
            subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True)
        self.state.write_text(state_text(phase='define', status='active', branch='gsd-path/M001'))
        before = self.state.read_bytes()
        for key, value in [('integration', 'pull-request'), ('review_panel', 'detected'),
                           ('models.roles.coder.model', 'example')]:
            result = self.cli('set', key, value, ok=False)
            self.assertIn('closed milestone', result['error'])
        self.assertEqual(self.state.read_bytes(), before)
        self.assertFalse((self.repo / '.project/config.json').exists())

    def test_bootstrap_uses_default_without_extra_project_files(self):
        from scripts.bootstrap_repository import BootstrapRequest, render_state
        self.profile({'integration': 'pull-request'})
        request = BootstrapRequest(str(self.home), 'owner', 'demo', 'private',
                                   str(self.repo), str(self.repo), 'gsd-path/M001', None)
        text = render_state(ROOT / 'skills/gsd-path/templates/state.md', request)
        self.assertIn('integration_default: pull-request', text)
        self.assertIn('integration: pull-request', text)

    def test_bundled_router_helper_can_edit_a_legacy_project(self):
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Test',
                        '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture'],
                       check=True, capture_output=True)
        helper = ROOT / 'skills/path/scripts/path_config.py'
        result = subprocess.run([sys.executable, '-B', str(helper), 'set', 'review_panel',
                                 'detected', '--repo', str(self.repo)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads((self.repo / '.project/config.json').read_text())['review_panel'], 'detected')

    def test_shipping_retains_project_preferences(self):
        from tests.test_archive_milestone import ArchiveMilestoneTests
        fixture = ArchiveMilestoneTests()
        fixture.make_repo(self.repo)
        files = {'config.json': {'review_panel': 'detected'},
                 'model-policy.json': {'roles': {'coder': {'model': 'inherit'}}}}
        for name, data in files.items():
            (self.repo / '.project' / name).write_text(json.dumps(data))
        archive = fixture.prepare_archive(self.repo)
        result = fixture.render_manifest(self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = fixture.preflight(self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, data in files.items():
            self.assertEqual(json.loads((self.repo / '.project' / name).read_text()), data)
            self.assertFalse((archive / name).exists())

    def test_config_edits_do_not_block_an_inflight_task_landing(self):
        from scripts import isolation
        from tests.test_isolation import IsolationTests, TASK_FILE
        fixture = IsolationTests()
        repo = self.home / 'landing'
        repo.mkdir()
        base = fixture.init_bound_repo(repo)
        source = Path(isolation.isolate_task(repo, base, 'T001', 2)['worktree'])
        fixture.write(source, 'src/app.py', "print('done')\n")
        fixture.write(source, '.project/tasks/T001.md', TASK_FILE + 'log\n')
        config = '{"review_panel":"detected"}\n'
        models = '{"roles":{"coder":{"model":"inherit"}}}\n'
        fixture.write(repo, '.project/config.json', config)
        fixture.write(repo, '.project/model-policy.json', models)
        result = isolation.land(repo, source, base, 'T001', 'add greeting',
                                '.project/tasks/T001.md', ['src/app.py'])
        self.assertEqual(result['mode'], 'parallel')
        self.assertEqual((repo / 'src/app.py').read_text(), "print('done')\n")
        self.assertEqual((repo / '.project/config.json').read_text(), config)
        self.assertEqual((repo / '.project/model-policy.json').read_text(), models)
        self.assertEqual(isolation.uncommitted_paths(repo),
                         {'.project/config.json', '.project/model-policy.json'})


if __name__ == '__main__':
    unittest.main()
