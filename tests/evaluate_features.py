"""Opt-in feature evaluation with pinned fixtures and separate native evidence."""

import argparse
import contextlib
import csv
import datetime as dt
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests import evaluate_codex, widget_acceptance
from tests.dogfood import FIXTURE_SCRIPT

SCENARIOS = json.loads((Path(__file__).with_name('feature_scenarios.json')).read_text())
GROUPS = {
    'install': ['test_install', 'test_sync_skill_resources'],
    'inspect': ['test_detect_project', 'test_check_docs_audit'],
    'define': ['test_detect_project', 'test_pipeline_state'],
    'research': ['test_handoffs'], 'decide': ['test_handoffs'],
    'roadmap': ['test_pipeline_state', 'test_handoffs'],
    'plan': ['test_task_briefs', 'test_handoffs', 'test_workflow_run'],
    'build': ['test_build_state', 'test_isolation'],
    'lookahead': ['test_pipeline_state', 'test_detect_project', 'test_pipeline_undo'],
    'review': ['test_handoffs'], 'panels': ['test_review_panel'],
    'skeptics': ['test_review_findings'], 'patch': ['test_review_findings', 'test_handoffs'],
    'lean-verification': ['test_lean_verification'],
    'discuss': ['test_discussion_records'], 'docs-audit': ['test_check_docs_audit'],
    'undo': ['test_pipeline_undo'], 'forensics': ['test_pipeline_diagnose'],
    'loop': ['test_loop_run'], 'abandon': ['test_archive_milestone'],
    'ship': ['test_archive_milestone', 'test_full_cycle', 'test_pipeline_git'],
    'pr-integration': ['test_archive_milestone', 'test_pipeline_git'],
    'bootstrap': ['test_bootstrap_repository'],
    'guards': ['test_guard_hook', 'test_git_guard'],
}


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path, value):
    evaluate_codex.write_json(Path(path), value)


def git(repo, *args):
    return evaluate_codex.command(['git', *args], Path(repo))


def prepare(directory, candidate, scenarios=None):
    directory, candidate = Path(directory).resolve(), Path(candidate).resolve()
    selected = list(SCENARIOS) if scenarios is None else list(dict.fromkeys(scenarios))
    if not selected or set(selected) - SCENARIOS.keys():
        raise ValueError('select known scenarios')
    if directory.exists():
        raise ValueError('evaluation directory already exists; preserve it and choose a new path')
    if git(candidate, 'status', '--porcelain'):
        raise ValueError('commit candidate changes before preparing a reproducible evaluation')
    revision = git(candidate, 'rev-parse', 'HEAD')
    directory.mkdir(parents=True)
    plugin = directory / 'plugin'
    git(directory, 'clone', '--quiet', '--no-hardlinks', str(candidate), str(plugin))
    manifest = {'schema': 'gsd-path/feature-evaluation/v1', 'candidate': revision,
                'created_at': stamp(), 'scenarios': selected, 'host': 'codex'}
    write_json(directory / 'manifest.json', manifest)
    for name in selected:
        spec = SCENARIOS[name]
        arm = directory / name
        repo = arm / 'repo'
        repo.mkdir(parents=True)
        git(repo, 'init', '-q', '-b', 'main')
        git(repo, 'config', 'user.name', 'Feature Evaluation')
        git(repo, 'config', 'user.email', 'evaluation@example.invalid')
        (repo / 'README.md').write_text('# Feature evaluation fixture\n')
        if spec['fixture'] == 'program':
            for filename in ('ledger.py', 'reports.py'):
                (repo / filename).write_text("raise SystemExit('Not implemented')\n")
        elif spec['fixture'] in ('counter', 'stale-docs'):
            (repo / 'count.py').write_text(FIXTURE_SCRIPT)
            if spec['fixture'] == 'stale-docs':
                (repo / 'README.md').write_text('# Counter\n\nThe --json flag prints JSON.\n')
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'fixture: initial product')
        remote = arm / 'origin.git'
        git(arm, 'clone', '--quiet', '--bare', str(repo), str(remote))
        git(repo, 'remote', 'add', 'origin', str(remote))
        output = evaluate_codex.command(['node', str(plugin / 'scripts/install.mjs'), '--codex',
                                         '--local', '--project', str(repo), '--hooks', '--no-color'], repo)
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'fixture: install pinned candidate')
        git(repo, 'push', '-u', 'origin', 'main')
        write_json(arm / 'install.json', {'candidate': revision, 'head': git(repo, 'rev-parse', 'HEAD'),
                                        'exit_code': 0, 'output': output})
        invocation = '$gsd-path-docs-audit' if name == 'docs-audit' else '$gsd-path'
        skill = repo / '.agents/skills' / invocation[1:] / 'SKILL.md'
        prompt = f'''{invocation}

Use ONLY the pinned local skill at {skill} and its sibling bundles. This is a
feature evaluation, not an update of the plugin. Use real native children and
canonical helpers. Do not change installed skills or hand-repair pipeline state.
No testing token/time limit is set. Do not invent limits, approvals or receipts.
Stop at reviewable owner gates. Remote actions are limited to the existing local
origin; any GitHub action needs separate explicit owner approval of its target.
Do not read evaluator tests or other scenario workspaces.

{spec['request']}

Scenario steps:
'''
        prompt += '\n'.join(f'{i}. {step}' for i, step in enumerate(spec['steps'], 1))
        prompt += "\n\nAt each named checkpoint, stop and identify the canonical artifacts for capture.\n"
        if 'lookahead' in spec['features']:
            prompt += '''It must observe lookahead before the active milestone ships and promotion before
build starts. A missed checkpoint remains unverifiable; do not reconstruct or
backdate state. Do not introduce a fake delay to manufacture overlap. Approval
of a future plan may not invalidate an in-flight task or review base; surface a
scheduling conflict if the current contracts lack a safe path.
'''
        prompt += f'''Use python3 {plugin / 'tests/evaluate_codex.py'} activity --arm {arm} --category
<implementation|verification|review> -- <command> for measured shell work. That
wrapper starts in the primary repo: select a sidecar cwd explicitly when needed.
'''
        if spec.get('external'):
            prompt += '\nEXTERNAL PREREQUISITE: ' + spec['external'] + '\n'
        (arm / 'prompt.txt').write_text(prompt)
        (arm / 'STEPS.md').write_text(f'# {name}\n\n' + '\n'.join(f'- {s}' for s in spec['steps']) + '\n')
    report(directory)
    return manifest


def product_sources(repo):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(repo).glob('*.py'))}


def evaluate_program(repo):
    repo = Path(repo).resolve()
    checks = []
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / 'ledger.json'
        def call(script, args, expected=None, kind='text', error=False):
            p = subprocess.run([sys.executable, '-B', str(repo / script), str(store), *args],
                               cwd=tmp, capture_output=True, text=True)
            actual = p.stdout
            try:
                if kind == 'json': actual = json.loads(actual)
                elif kind == 'csv': actual = list(csv.reader(io.StringIO(actual)))
            except (ValueError, csv.Error): actual = None
            passed = bool(p.returncode and p.stderr.strip()) if error else (
                p.returncode == 0 and not p.stderr and (expected is None or actual == expected))
            if kind == 'json' and isinstance(actual, list):
                passed = passed and all(isinstance(row, dict) and type(row.get('amount')) is int for row in actual)
            checks.append({'command': [script, *args], 'pass': passed, 'exit_code': p.returncode,
                           'stdout': p.stdout, 'stderr': p.stderr})
        call('ledger.py', ['list'], [], 'json')
        for name, amount in [('apple', '7'), ('apricot', '-2'), ('b,"x', '4')]:
            call('ledger.py', ['add', name, amount])
        rows = [{'name': 'apple', 'amount': 7}, {'name': 'apricot', 'amount': -2}, {'name': 'b,"x', 'amount': 4}]
        call('ledger.py', ['list'], rows, 'json')
        saved = store.read_bytes() if store.exists() else None
        for args in (['add', 'apple', '99'], ['add', 'bad', 'nope'], ['add', '', '3']):
            call('ledger.py', args, error=True)
            checks.append({'check': 'invalid input preserves store bytes',
                           'pass': store.exists() and store.read_bytes() == saved})
        call('reports.py', ['total'], '9\n')
        call('reports.py', ['csv'], [['name', 'amount'], ['apple', '7'], ['apricot', '-2'], ['b,"x', '4']], 'csv')
        call('reports.py', ['total', '--prefix', 'ap'], '5\n')
        call('reports.py', ['csv', '--prefix', 'ap'], [['name', 'amount'], ['apple', '7'], ['apricot', '-2']], 'csv')
        call('reports.py', ['total', '--prefix', 'AP'], '0\n')
        call('reports.py', ['csv', '--prefix', 'missing'], [['name', 'amount']], 'csv')
        call('ledger.py', ['remove', 'apple'])
        call('ledger.py', ['list'], rows[1:], 'json')
        call('ledger.py', ['remove', 'missing'], error=True)
    return {'verdict': 'pass' if all(c['pass'] for c in checks) else 'fail', 'checks': checks}


def summarize_tests(results, wanted):
    states = [results.get(name) for name in wanted]
    if 'fail' in states:
        return 'fail'
    if not states or None in states:
        return 'untested'
    if any(state != 'pass' for state in states):
        return 'unverifiable'
    return 'pass'


def run_tests(suite):
    statuses = {}
    class Result(unittest.TextTestResult):
        def addSuccess(self, test):
            super().addSuccess(test)
            statuses.setdefault(test.id(), 'pass')
        def addFailure(self, test, err):
            super().addFailure(test, err)
            statuses[test.id()] = 'fail'
        def addError(self, test, err):
            super().addError(test, err)
            statuses[test.id()] = 'fail'
        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            statuses[test.id()] = 'skip'
        def addSubTest(self, test, subtest, err):
            super().addSubTest(test, subtest, err)
            if err is not None: statuses[test.id()] = 'fail'
        def addExpectedFailure(self, test, err):
            super().addExpectedFailure(test, err)
            statuses[test.id()] = 'expected-failure'
        def addUnexpectedSuccess(self, test):
            super().addUnexpectedSuccess(test)
            statuses[test.id()] = 'fail'
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        result = unittest.TextTestRunner(stream=output, resultclass=Result).run(suite)
    return {'tests': statuses, 'tests_run': result.testsRun, 'successful': result.wasSuccessful(),
            'output': output.getvalue()}


def check(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text())
    plugin = directory / 'plugin'
    if git(plugin, 'rev-parse', 'HEAD') != manifest['candidate'] or git(plugin, 'status', '--porcelain'):
        raise ValueError('pinned candidate changed')
    receipt = directory / 'automated.json'
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved['candidate'] != manifest['candidate']: raise ValueError('automated receipt belongs to another candidate')
        return saved
    # Execute the pinned test code, not an importing session's checkout.
    result = subprocess.run([sys.executable, '-B', str(plugin / 'tests/evaluate_features.py'),
                             '_check', '--directory', str(directory)], cwd=plugin, capture_output=True, text=True)
    (directory / 'automated-command.log').write_text(result.stdout + result.stderr)
    if not receipt.exists(): raise ValueError('automated runner did not produce its receipt; see automated-command.log')
    return json.loads(receipt.read_text())


def check_candidate(directory):
    directory = Path(directory).resolve()
    modules = sorted({module for group in GROUPS.values() for module in group})
    suite = unittest.defaultTestLoader.loadTestsFromNames(['tests.' + name for name in modules])
    started = stamp()
    result = run_tests(suite)
    node = subprocess.run(['npm', 'test'], cwd=ROOT, capture_output=True, text=True)
    sync = subprocess.run([sys.executable, '-B', 'scripts/sync_skill_resources.py', '--check'],
                          cwd=ROOT, capture_output=True, text=True)
    result.update(candidate=git(ROOT, 'rev-parse', 'HEAD'), started_at=started, ended_at=stamp(),
                  modules=modules, node={'exit_code': node.returncode, 'output': node.stdout + node.stderr},
                  sync={'exit_code': sync.returncode, 'output': sync.stdout + sync.stderr})
    result['exit_code'] = 0 if result['successful'] and node.returncode == 0 and sync.returncode == 0 else 1
    write_json(directory / 'automated.json', result)
    return result


def record_review(directory, feature, verdict, evidence, reason):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text())
    if feature not in GROUPS or verdict not in ('pass', 'fail', 'unverifiable'):
        raise ValueError('unknown feature or verdict')
    relevant = [directory / name for name in manifest['scenarios'] if feature in SCENARIOS[name]['features']]
    live = [p for arm in relevant for p in arm.glob('run-*/run.json') if (p.parent / 'events.jsonl').is_file()]
    if not live: raise ValueError('native run evidence is required before recording a native review')
    if not evidence or not reason.strip(): raise ValueError('a native review needs evidence paths and a reason')
    references = []
    for name in evidence:
        path = Path(name).resolve()
        if not path.is_file() or not any(arm in path.parents for arm in relevant):
            raise ValueError('evidence must be a real file within a relevant scenario')
        references.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    review = {'candidate': manifest['candidate'], 'feature': feature, 'verdict': verdict,
              'basis': 'operator review of native evidence; not an automatic helper verdict',
              'reason': reason, 'evidence': references, 'timestamp': stamp()}
    with (directory / 'reviews.jsonl').open('a') as output:
        output.write(json.dumps(review) + '\n')
    return review


def lookahead_evidence(captures):
    result = {'planning_during_build': False, 'clean_promotion': False,
              'drift_reopened': False, 'concurrent_agents': 'unverifiable'}
    planned = {}
    for capture in sorted(captures, key=lambda c: c['timestamp']):
        active, future = capture.get('state') or {}, capture.get('next') or {}
        if (active.get('phase'), active.get('status')) == ('build', 'active') and future.get('branch') is None:
            if future.get('phase') in ('inspect', 'define', 'research', 'decide', 'plan') and future.get('milestone'):
                result['planning_during_build'] = True
            if future.get('milestone') and (future.get('phase'), future.get('status')) == ('plan', 'done'):
                planned[future['milestone']] = capture['timestamp']
        promotion = capture.get('promotion') or {}
        milestone = active.get('milestone')
        if (not future and milestone in planned and planned[milestone] < capture['timestamp']
                and promotion.get('milestone') == milestone and promotion.get('status') == 'promoted'
                and active.get('phase') == 'plan'):
            drift = promotion.get('drift', {}).get('class')
            result['clean_promotion'] |= drift == 'clean' and active.get('status') == 'done'
            result['drift_reopened'] |= drift == 'changed' and active.get('status') == 'active'
    return result


def capture(arm, label, promotion=None):
    arm = Path(arm).resolve()
    repo = arm / 'repo'
    helper = repo / '.agents/skills/gsd-path/scripts/pipeline_state.py'
    def status(project):
        return json.loads(evaluate_codex.command([sys.executable, '-B', str(helper), 'status',
                                                 '--repo', str(repo), '--project-dir', project], repo))
    primary = status('.project')
    future = status('.project/next') if (repo / '.project/next/STATE.md').exists() else None
    value = {'timestamp': stamp(), 'label': label, 'head': git(repo, 'rev-parse', 'HEAD'),
             'state': primary['state'], 'next': future['state'] if future else None,
             'primary_receipt': primary, 'next_receipt': future, 'promotion': None}
    if promotion:
        receipt = json.loads(Path(promotion).read_text())
        if receipt.get('commit') != value['head'] or receipt.get('milestone') != value['state']['milestone']:
            raise ValueError('promotion receipt must match the captured milestone and HEAD')
        value['promotion'] = receipt
        value['promotion_source'] = str(Path(promotion).resolve())
    with (arm / 'captures.jsonl').open('a') as output:
        output.write(json.dumps(value) + '\n')
    return value


def report(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text())
    automated = json.loads((directory / 'automated.json').read_text()) if (directory / 'automated.json').exists() else {}
    if automated and automated.get('candidate') != manifest['candidate']:
        raise ValueError('automated evidence belongs to another candidate')
    features = {}
    for feature, modules in GROUPS.items():
        ids = [name for name in automated.get('tests', {}) if any(name.startswith('tests.' + m + '.') for m in modules)]
        complete_modules = all(any(name.startswith('tests.' + m + '.') for name in ids) for m in modules)
        features[feature] = {'automated': summarize_tests(automated.get('tests', {}), ids) if complete_modules else 'untested',
                             'native': 'untested', 'scenarios': [n for n in manifest['scenarios'] if feature in SCENARIOS[n]['features']]}
    features['install']['native'] = 'not-required'
    if automated and automated.get('node', {}).get('exit_code') != 0:
        features['install']['automated'] = 'fail'
    scenarios = {}
    for name in manifest['scenarios']:
        arm = directory / name
        runs = [json.loads(p.read_text()) for p in sorted(arm.glob('run-*/run.json'))]
        captures = [json.loads(line) for line in (arm / 'captures.jsonl').read_text().splitlines()] if (arm / 'captures.jsonl').exists() else []
        scenarios[name] = {'native': 'review-required' if runs else 'untested', 'runs': len(runs),
                           'active_seconds': sum(r['elapsed_seconds'] for r in runs),
                           'failed_invocations': sum(r['exit_code'] != 0 for r in runs),
                           'prerequisite': SCENARIOS[name].get('external'),
                           'captures': len(captures)}
        activity_file = arm / 'activities.jsonl'
        activities = [json.loads(line) for line in activity_file.read_text().splitlines()] if activity_file.exists() else []
        scenarios[name]['activity_seconds'] = {
            category: sum(event['duration_seconds'] for event in activities if event['category'] == category)
            if any(event['category'] == category for event in activities) else None
            for category in ('implementation', 'verification', 'review')}
        scenarios[name]['measurement'] = 'partial' if runs else 'unavailable'
        if name == 'program': scenarios[name]['lookahead'] = lookahead_evidence(captures)
        product = arm / 'product.json'
        scenarios[name]['product'] = 'untested'
        if product.exists():
            receipt = json.loads(product.read_text())
            current = receipt.get('sources') == product_sources(arm / 'repo')
            scenarios[name]['product'] = receipt['verdict'] if current else 'stale'
        for feature in SCENARIOS[name]['features']:
            if runs: features[feature]['native'] = 'review-required'
    reviews = directory / 'reviews.jsonl'
    if reviews.exists():
        for line in reviews.read_text().splitlines():
            review = json.loads(line)
            valid = review['candidate'] == manifest['candidate'] and bool(review['evidence'])
            for ref in review['evidence']:
                path = Path(ref['path'])
                valid = valid and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == ref['sha256']
            features[review['feature']]['native'] = review['verdict'] if valid else 'stale-review'
            features[review['feature']]['review'] = review
    observed = scenarios.get('program', {}).get('lookahead', {})
    if features['lookahead']['native'] == 'pass' and not all(
            observed.get(key) for key in ('planning_during_build', 'clean_promotion', 'drift_reopened')):
        features['lookahead']['native'] = 'unverifiable'
    complete = all(row['automated'] == 'pass' and row['native'] in ('pass', 'not-required') for row in features.values())
    complete = complete and automated.get('sync', {}).get('exit_code') == 0
    complete = complete and all(scenarios.get(name, {}).get('product') == 'pass'
                                for name in ('program', 'quick', 'greenfield'))
    result = {'candidate': manifest['candidate'], 'verdict': 'complete' if complete else 'incomplete', 'features': features,
              'scenarios': scenarios, 'note': 'Native feature verdicts require review of canonical artifacts and real host traces; CLI exit, prose and helper tests alone never prove them.'}
    write_json(directory / 'report.json', result)
    lines = ['# Feature evaluation', '', f"Candidate: {manifest['candidate']}", '', result['note'], '',
             '| Feature | Automated | Native | Scenarios |', '|---|---|---|---|']
    for name, row in features.items():
        lines.append(f"| {name} | {row['automated']} | {row['native']} | {', '.join(row['scenarios']) or 'host/install checks'} |")
    (directory / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    actions = p.add_subparsers(dest='action', required=True)
    prep = actions.add_parser('prepare')
    prep.add_argument('--directory', type=Path, required=True)
    prep.add_argument('--candidate', type=Path, default=ROOT)
    prep.add_argument('--scenario', choices=tuple(SCENARIOS), action='append')
    run = actions.add_parser('run')
    run.add_argument('--directory', type=Path, required=True)
    run.add_argument('--scenario', choices=tuple(SCENARIOS), required=True)
    run.add_argument('--model', required=True)
    run.add_argument('--reasoning', required=True)
    run.add_argument('--sandbox', choices=('read-only', 'workspace-write', 'danger-full-access'), required=True)
    run.add_argument('--resume')
    run.add_argument('--prompt-file', type=Path)
    cap = actions.add_parser('capture')
    cap.add_argument('--directory', type=Path, required=True)
    cap.add_argument('--scenario', choices=tuple(SCENARIOS), required=True)
    cap.add_argument('--label', required=True)
    cap.add_argument('--promotion', type=Path)
    review = actions.add_parser('review')
    review.add_argument('--directory', type=Path, required=True)
    review.add_argument('--feature', choices=tuple(GROUPS), required=True)
    review.add_argument('--verdict', choices=('pass', 'fail', 'unverifiable'), required=True)
    review.add_argument('--evidence', type=Path, action='append', required=True)
    review.add_argument('--reason', required=True)
    for name in ('report', 'accept', 'check', '_check'):
        cmd = actions.add_parser(name)
        cmd.add_argument('--directory', type=Path, required=True)
        if name == 'accept': cmd.add_argument('--scenario', choices=('program', 'quick', 'greenfield'), required=True)
    a = p.parse_args(argv)
    if a.action == 'prepare': result = prepare(a.directory, a.candidate, a.scenario)
    elif a.action == 'run':
        if SCENARIOS[a.scenario].get('external'):
            p.error(SCENARIOS[a.scenario]['external'] + ' Use the reviewed external procedure in the test plan.')
        result = evaluate_codex.run(a.directory.resolve() / a.scenario, a.model, a.reasoning,
                                    a.sandbox, a.resume, a.prompt_file)
    elif a.action == 'capture': result = capture(a.directory / a.scenario, a.label, a.promotion)
    elif a.action == 'check': result = check(a.directory)
    elif a.action == '_check': result = check_candidate(a.directory)
    elif a.action == 'review': result = record_review(a.directory, a.feature, a.verdict, a.evidence, a.reason)
    elif a.action == 'accept':
        arm = a.directory.resolve() / a.scenario
        result = evaluate_program(arm / 'repo') if a.scenario == 'program' else widget_acceptance.evaluate(arm / 'repo')
        result['sources'] = product_sources(arm / 'repo')
        write_json(arm / 'product.json', result)
    else: result = report(a.directory)
    if a.action in ('check', '_check'):
        print(json.dumps({key: result[key] for key in ('candidate', 'tests_run', 'exit_code')}, indent=2))
    else:
        print(json.dumps(result, indent=2))
    if a.action == 'report': return 0 if result['verdict'] == 'complete' else 3
    return result.get('exit_code', 1 if result.get('verdict') == 'fail' else 0)


if __name__ == '__main__':
    raise SystemExit(main())
