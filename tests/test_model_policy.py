"""Exercise model policy through dispatch and real child argument delivery."""

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import dispatch_driver


class DispatchPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / '.project').mkdir()
        self.policy = self.root / '.project/model-policy.json'
        self.policy.write_text(json.dumps({'roles': {'coder': {'model': 'small', 'effort': 'low'}}}))
        self.caps = self.root / 'capabilities.json'
        self.caps.write_text(json.dumps({
            'host': 'codex',
            'model': {'values': ['small', 'large'], 'field': 'model', 'args': ['--model', '{value}']},
            'effort': {'values': ['low', 'high'], 'field': 'reasoning_effort',
                       'args': ['--effort', '{value}']},
        }))
        self.child = self.root / 'child.py'
        self.child.write_text('import json, sys\nprint(json.dumps(sys.argv[1:]))\n')
        self.options = argparse.Namespace(
            repo=self.root, project_dir='.project', action='round',
            model_capabilities=self.caps, model=None, effort=None,
            child_timeout=None, child_command=shlex.join(
                [sys.executable, str(self.child), '{model_args}', '{effort_args}']))
        self.state = {'task_id': 'T001', 'worktree': str(self.root)}

    def launch(self, state=None):
        # Only the detached wrapper is replaced; execute the emitted child argv below.
        with mock.patch.object(dispatch_driver.subprocess, 'Popen') as wrapper:
            wrapper.return_value.pid = os.getpid()
            result = dispatch_driver.spawn(self.root / 'records', state or self.state,
                                           self.options, lambda _: 'task brief')
        output = subprocess.run(result['command'], capture_output=True, text=True, check=True)
        return result, json.loads(output.stdout)

    def test_project_choice_reaches_child(self):
        _, received = self.launch()
        self.assertEqual(received, ['--model', 'small', '--effort', 'low'])

    def test_unsupported_explicit_choice_stops_before_attempt(self):
        self.policy.write_text(json.dumps({'roles': {'coder': {'model': 'unavailable'}}}))
        with self.assertRaisesRegex(Exception, 'unavailable'):
            self.launch()
        self.assertFalse((self.root / 'records/T001').exists())

    def test_retry_keeps_choice_after_policy_edit(self):
        state, _ = self.launch()
        state['finished_at'] = 'completed'
        self.policy.write_text(json.dumps({'roles': {'coder': {'model': 'large', 'effort': 'high'}}}))
        _, received = self.launch(state)
        self.assertEqual(received, ['--model', 'small', '--effort', 'low'])

    def test_task_partial_override_preserves_role_effort(self):
        task = self.root / '.project/task.md'
        task.write_text('---\nid: T001\nmodel: large\n---\n')
        self.state['task_file'] = '.project/task.md'
        _, received = self.launch()
        self.assertEqual(received, ['--model', 'large', '--effort', 'low'])

    def test_opaque_command_cannot_ignore_explicit_choice(self):
        self.options.child_command = shlex.join([sys.executable, str(self.child)])
        with self.assertRaisesRegex(Exception, 'model_args'):
            self.launch()

    def test_native_fields_match_every_installed_host(self):
        from scripts import model_policy
        manifest = json.loads((Path(__file__).parents[1] / 'scripts/skill-resources.json').read_text())
        for host in manifest['hosts']:
            caps = json.loads(self.caps.read_text())
            caps['host'] = host
            with self.subTest(host=host):
                result = model_policy.resolve(self.root, '.project', 'coder', caps, {})
                self.assertEqual(result['native'], {'model': 'small', 'reasoning_effort': 'low'})
                caps['model']['values'] = []
                with self.assertRaisesRegex(model_policy.PolicyError, 'small'):
                    model_policy.resolve(self.root, '.project', 'coder', caps, {})

    def test_fixed_command_model_cannot_override_policy_slot(self):
        self.options.child_command += ' --model large'
        with self.assertRaisesRegex(Exception, 'conflict'):
            self.launch()

    def test_invalid_capabilities_are_a_typed_policy_error(self):
        from scripts import model_policy
        self.caps.write_text('{broken json')
        with self.assertRaises(model_policy.PolicyError):
            self.launch()

    def test_driver_reassignment_is_explicit_and_preserves_old_attempt(self):
        state, _ = self.launch()
        state['finished_at'] = 'completed'
        dispatch_driver.save_state(Path(state['_path']), {k: v for k, v in state.items() if k != '_path'})
        old = Path(state['_path']).read_bytes()
        self.options.model = 'large'
        self.options.effort = None
        self.options.ruling = 'Use large for this task.'
        # Public driver operation, with the real saved attempt in the records tree.
        operation = getattr(dispatch_driver, 'reassign_model', None)
        if operation is None:
            result = {'status': 'unsupported'}
        else:
            result = operation(self.root / 'records', 'T001', self.options)
        self.assertEqual(result['status'], 'reassigned')
        self.options.model = None
        _, received = self.launch(state)
        self.assertEqual(received, ['--model', 'large', '--effort', 'low'])
        self.assertEqual(Path(state['_path']).read_bytes(), old)

    def native(self, action='resolve', *extra, scope='M001/active/plan'):
        script = Path(__file__).parents[1] / 'scripts/model_policy.py'
        result = subprocess.run([
            sys.executable, '-B', str(script), action, '--repo', str(self.root),
            '--scope', scope, '--assignment', 'plan', '--role', 'plan',
            '--record', str(self.root / 'native.json'), '--capabilities', str(self.caps),
            *extra], capture_output=True, text=True)
        self.assertNotEqual(result.stdout, '', result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_native_reassignment_keeps_unmodified_fields(self):
        code, first = self.native('resolve', '--model', 'small', '--effort', 'low')
        self.assertEqual(code, 0, first)
        code, blocked = self.native('reassign', '--model', 'large', '--ruling', 'Upgrade this plan.')
        self.assertNotEqual(code, 0)
        self.assertIn('inactive', blocked['reason'])
        self.assertEqual(self.native('release', '--terminal-result', 'host:completed/plan')[0], 0)
        code, changed = self.native('reassign', '--model', 'large', '--ruling', 'Upgrade this plan.')
        self.assertEqual(code, 0, changed)
        self.assertEqual(changed['selection']['selected'], {'model': 'large', 'effort': 'low'})
        self.assertEqual(changed['history'][0]['selection'], first['selection'])

    def test_invalid_task_override_fails_task_contract_validation(self):
        from scripts import check_handoffs
        with self.assertRaisesRegex(check_handoffs.HandoffError, 'model'):
            check_handoffs._strict_frontmatter('---\nid: T001\nmodel: [small, large]\n---\n', 'task')

    def test_panel_choice_reaches_brief_and_child_without_family_drift(self):
        self.options.action = 'panel'
        self.state.update(family='gpt', slug='gpt-old')
        caps = json.loads(self.caps.read_text())
        caps['model']['values'] = ['gpt-old', 'gpt-new', 'claude-other']
        self.caps.write_text(json.dumps(caps))
        self.policy.write_text(json.dumps({'roles': {'review_panel': {'model': 'gpt-new'}}}))
        state, received = self.launch()
        self.assertEqual(state['slug'], 'gpt-new')
        self.assertEqual(received, ['--model', 'gpt-new'])
        dispatch_driver.update_state(state, finished_at='completed')
        self.state['excluded_families'] = ['gpt']
        with self.assertRaisesRegex(Exception, 'independent family'):
            self.launch()

    def test_known_inherited_identity_change_blocks_retry(self):
        from scripts import model_policy
        self.policy.unlink()
        caps = {'host': 'codex', 'inherited_model': 'small'}
        first = model_policy.resolve(self.root, '.project', 'coder', caps, {})
        caps['inherited_model'] = 'large'
        with self.assertRaisesRegex(model_policy.PolicyError, 'inherited model'):
            model_policy.resolve(self.root, '.project', 'coder', caps, {}, first)

    def test_host_override_explicit_inherit_and_default_hints(self):
        from scripts import model_policy
        self.policy.write_text(json.dumps({'roles': {'plan': {'model': 'small', 'effort': 'low'}},
                                           'hosts': {'codex': {'plan': {'model': 'large'}}}}))
        caps = json.loads(self.caps.read_text())
        selected = model_policy.resolve(self.root, '.project/next', 'plan', caps, {'effort': 'inherit'})
        self.assertEqual(selected['native'], {'model': 'large'})
        self.assertEqual(selected['sources'], {'model': 'hosts.codex.plan', 'effort': 'task'})
        self.policy.unlink()
        self.assertEqual(model_policy.resolve(self.root, '.project', 'plan', caps, {})['native'],
                         {'reasoning_effort': 'high'})
        self.assertEqual(model_policy.resolve(self.root, '.project', 'docs_audit', caps, {})['native'],
                         {'reasoning_effort': 'low'})
        self.assertEqual(model_policy.resolve(self.root, '.project', 'coder', {'host': 'zed'}, {})['native'], {})

    def test_native_resume_and_scope_collision(self):
        code, first = self.native('resolve', '--model', 'small')
        self.assertEqual(code, 0, first)
        self.policy.write_text(json.dumps({'roles': {'plan': {'model': 'large', 'effort': 'low'}}}))
        self.assertEqual(self.native()[1]['selection'], first['selection'])
        before = (self.root / 'native.json').read_bytes()
        self.assertNotEqual(self.native(scope='M002/active/plan')[0], 0)
        self.assertEqual((self.root / 'native.json').read_bytes(), before)

    def test_legacy_command_without_policy_is_unchanged(self):
        self.policy.unlink()
        self.options.model_capabilities = None
        self.options.child_command = shlex.join([sys.executable, str(self.child), 'owner-argument'])
        _, received = self.launch()
        self.assertEqual(received, ['owner-argument'])

    def test_new_attempt_reloads_assignment_selection(self):
        state, _ = self.launch()
        dispatch_driver.update_state(state, finished_at='completed', outcome='blocked')
        self.policy.write_text(json.dumps({'roles': {'coder': {'model': 'large'}}}))
        _, received = self.launch()
        self.assertEqual(received, ['--model', 'small', '--effort', 'low'])

    def test_bundled_helpers_execute_outside_source_checkout(self):
        repo = Path(__file__).parents[1]
        manifest = json.loads((repo / 'scripts/skill-resources.json').read_text())
        for skill in manifest['skills']:
            with self.subTest(skill=skill):
                script = repo / 'skills' / skill / 'scripts/model_policy.py'
                result = subprocess.run([
                    sys.executable, '-B', str(script), 'resolve', '--repo', str(self.root),
                    '--scope', 'M001/active', '--assignment', 'T001', '--role', 'coder',
                    '--record', str(self.root / f'{skill}.json'), '--capabilities', str(self.caps)],
                    cwd=self.root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual(json.loads(result.stdout)['selection']['native'],
                                 {'model': 'small', 'reasoning_effort': 'low'})

    def test_policy_reaches_real_wave_and_landing(self):
        from tests.test_dispatch_driver import DispatchDriverTests
        fixture = DispatchDriverTests()
        fixture.fixture(self.root)
        child = self.root / 'fake_coder.py'
        child.write_text("import sys\nassert sys.argv[1:] == ['--model', 'small', '--effort', 'low']\n"
                         + child.read_text())
        subprocess.run(['git', '-C', str(self.root), 'commit', '-qam', 'fixture argv assertion'], check=True,
                       capture_output=True)
        result = fixture.round(self.root, '--model-capabilities', str(self.caps), '--child-command',
                               shlex.join([sys.executable, str(child), '{model_args}', '{effort_args}']),
                               '--wait', '60')
        self.assertEqual(result['status'], 'done', result)
        self.assertEqual(sorted(row['task'] for row in result['landed']), ['T001', 'T002'])

    def test_invalid_policy_leaves_ready_task_unactivated(self):
        from tests.test_dispatch_driver import DispatchDriverTests
        fixture = DispatchDriverTests()
        self.policy.write_text(json.dumps({'roles': {'coder': {'model': 'unavailable'}}}))
        fixture.fixture(self.root)
        result = fixture.round(self.root, '--model-capabilities', str(self.caps))
        self.assertEqual(result['status'], 'blocked', result)
        self.assertIn('unavailable', json.dumps(result))
        self.assertEqual(fixture.branches(self.root), ['gsd-path/M001'])
        for path in (self.root / '.project/tasks').glob('*.md'):
            fields, _ = dispatch_driver.isolation.task_frontmatter(path.read_text())
            self.assertEqual(fields['status'], 'pending')

    def test_changed_explicit_override_cannot_bypass_pinned_selection(self):
        state, _ = self.launch()
        dispatch_driver.update_state(state, finished_at='completed')
        task = self.root / '.project/task.md'
        task.write_text('---\nid: T001\nmodel: large\n---\n')
        state['task_file'] = '.project/task.md'
        with self.assertRaisesRegex(Exception, 'reassign'):
            self.launch(state)

    def test_reassign_model_preserves_implicit_effort_and_command(self):
        self.policy.write_text(json.dumps({'roles': {'coder': {'model': 'small'}}}))
        self.options.child_command = shlex.join([sys.executable, str(self.child), '{model_args}'])
        state, _ = self.launch()
        dispatch_driver.update_state(state, finished_at='completed')
        self.options.model, self.options.ruling = 'large', 'Upgrade this task.'
        result = dispatch_driver.reassign_model(self.root / 'records', 'T001', self.options)
        self.assertEqual(result['selection']['sources']['effort'], 'default')
        self.options.model = None
        _, received = self.launch(state)
        self.assertEqual(received, ['--model', 'large'])

    def test_panel_override_is_scoped_to_one_assignment(self):
        self.options.action = 'panel'
        self.options.model_overrides = self.root / 'overrides.json'
        self.options.model_overrides.write_text(json.dumps({'panel_gpt': {'model': 'gpt-new'}}))
        caps = json.loads(self.caps.read_text())
        caps['model']['values'] = ['gpt-new', 'claude-other']
        self.caps.write_text(json.dumps(caps))
        self.policy.write_text('{}')
        self.state.update(task_id='panel_claude', family='claude', slug='claude-other')
        state, received = self.launch()
        self.assertEqual(state['slug'], 'claude-other')
        self.assertEqual(received, ['--model', 'claude-other'])
        self.state.update(task_id='panel_gpt', family='gpt', slug='gpt-old')
        state, received = self.launch()
        self.assertEqual(state['slug'], 'gpt-new')
        self.assertEqual(received, ['--model', 'gpt-new'])

    def test_rejected_task_does_not_stop_independent_sibling(self):
        from tests.test_dispatch_driver import DispatchDriverTests
        fixture = DispatchDriverTests()
        fixture.fixture(self.root)
        task = next((self.root / '.project/tasks').glob('T001*.md'))
        task.write_text(task.read_text().replace('id: T001', 'id: T001\nmodel: unavailable', 1))
        subprocess.run(['git', '-C', str(self.root), 'commit', '-qam', 'fixture task override'],
                       check=True, capture_output=True)
        result = fixture.round(
            self.root, '--model-capabilities', str(self.caps),
            '--child-command', shlex.join([sys.executable, str(self.root / 'fake_coder.py'),
                                          '{model_args}', '{effort_args}']),
            '--capacity', '1', '--wait', '60')
        self.assertEqual([row['task'] for row in result['landed']], ['T002'], result)
        self.assertEqual(result['status'], 'blocked', result)
        self.assertTrue(any(row.get('task_id') == 'T001' and 'unavailable' in row['reason']
                            for row in result['blocked']), result)
        self.assertFalse((dispatch_driver.records_root(self.root) / 'T001').exists())
        self.assertFalse(any('t001' in branch.lower() for branch in fixture.branches(self.root)))
        task = next((self.root / '.project/tasks').glob('T001*.md'))
        fields, _ = dispatch_driver.isolation.task_frontmatter(task.read_text())
        self.assertEqual(fields['status'], 'pending')

    def test_legacy_retry_does_not_adopt_new_policy(self):
        self.policy.unlink()
        self.options.model_capabilities = None
        self.options.child_command = shlex.join([sys.executable, str(self.child), 'owner-argument'])
        state, received = self.launch()
        self.assertEqual(received, ['owner-argument'])
        dispatch_driver.update_state(state, finished_at='completed', outcome='question')
        self.policy.write_text(json.dumps({'roles': {'coder': {'model': 'large'}}}))
        self.options.model_capabilities = self.caps
        self.options.child_command = shlex.join([sys.executable, str(self.child), '{model_args}'])
        _, received = self.launch()
        self.assertEqual(received, ['owner-argument'])

    def test_legacy_retry_rejects_explicit_selection_without_migration(self):
        self.policy.unlink()
        self.options.model_capabilities = None
        self.options.child_command = shlex.join([sys.executable, str(self.child)])
        state, _ = self.launch()
        dispatch_driver.update_state(state, finished_at='completed', outcome='question')
        self.options.model_capabilities = self.caps
        self.options.model = 'large'
        self.options.child_command += ' {model_args}'
        with self.assertRaisesRegex(Exception, 'legacy.*assignment'):
            self.launch()

    def test_detected_panel_excludes_canonical_family_before_persisting(self):
        from tests.test_dispatch_driver import DispatchDriverTests
        fixture = DispatchDriverTests()
        self.policy.unlink()
        caps = json.loads(self.caps.read_text())
        caps['model']['values'] = ['gpt-6-astra', 'claude-opus', 'grok-4']
        self.caps.write_text(json.dumps(caps))
        fixture.fixture(self.root)
        fixture.set_panel(self.root, 'detected')
        self.assertEqual(fixture.round(self.root, '--wait', '60')['status'], 'done')
        review = fixture.review(
            self.root, '--wait', '60', '--model', 'claude-opus',
            '--model-capabilities', str(self.caps), '--child-command',
            shlex.join([sys.executable, str(self.root / 'fake_reviewer.py'), '{model_args}']))
        self.assertEqual(review['status'], 'pass', review)
        result = fixture.panel(
            self.root, '--wait', '60', '--parent-slug', 'gpt-6-astra',
            '--model-capabilities', str(self.caps), '--child-command',
            shlex.join([sys.executable, str(self.root / 'fake_panelist.py'), '{model_args}']),
            advertised='gpt-6-astra,claude-opus,grok-4')
        self.assertEqual(result['status'], 'pass', result)
        roster = dispatch_driver.load_state(dispatch_driver.records_root(self.root)
                                            / 'panels/wave-1-cycle-1/roster.json')
        self.assertEqual(roster['families'], ['grok'])
        self.assertEqual(set(result['families']), {'grok'})

    def test_capability_command_rejects_legacy_model_placeholder(self):
        self.options.child_command += ' -m {model}'
        with self.assertRaisesRegex(Exception, 'model.*placeholder'):
            self.launch()


if __name__ == '__main__':
    unittest.main()
