#!/usr/bin/env python3
# gsd-path project runtime
"""Show and edit Path preferences without advancing a pipeline phase."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROLES = ('coder', 'reviewer', 'review_panel', 'skeptic', 'inspect_codebase',
         'inspect_docs', 'docs_audit', 'research', 'decide', 'roadmap', 'plan', 'plan_patch')
HOSTS = ('codex', 'claude', 'grok', 'opencode', 'copilot', 'qwen', 'antigravity',
         'cursor', 'zed', 'kiro', 'kimi')


def sibling(name):
    import importlib
    return importlib.import_module(f'{__package__}.{name}' if __package__ else name)


def safe_path(path):
    # Resolve host aliases (macOS /var) at the repo/home boundary, not here.
    for item in (path, path.parent):
        if item.is_symlink():
            raise ValueError(f'unsafe symlink: {item}')
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError(f'expected a regular unlinked file: {path}')
    return path


def read_object(path):
    safe_path(path)
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'{path} must contain an object')
    return value


def user_path():
    return Path.home().resolve() / '.gsd-path/config.json'


def model_key(key):
    bits = key.split('.')
    if len(bits) == 4 and bits[:2] == ['models', 'roles']:
        role, field = bits[2:]
    elif len(bits) == 5 and bits[:2] == ['models', 'hosts'] and bits[2] in HOSTS:
        role, field = bits[3:]
    else:
        raise ValueError(f'unknown setting: {key}')
    if role not in ROLES or field not in ('model', 'effort'):
        raise ValueError(f'unknown setting: {key}')
    return bits


def flatten(data, prefix=''):
    result = {}
    for key, value in data.items():
        name = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            result.update(flatten(value, name))
        else:
            result[name] = value
    return result


def validate_value(key, value):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f'{key} requires a nonempty string')
    if key == 'integration':
        if value not in ('direct', 'pull-request'):
            raise ValueError('integration must be direct or pull-request')
    elif key == 'review_panel':
        if any(char.isspace() for char in value):
            raise ValueError('use off, detected, or comma-separated families without spaces')
        sibling('review_panel').parse_review_panel_value(value)
    else:
        model_key(key)


def validate_models(data):
    if not isinstance(data, dict) or set(data) - {'roles', 'hosts'}:
        raise ValueError('models must contain roles and/or hosts')
    for group, entries in data.items():
        if not isinstance(entries, dict):
            raise ValueError(f'models.{group} must be an object')
        groups = [('roles', entries)] if group == 'roles' else [(f'hosts.{host}', roles) for host, roles in entries.items()]
        for prefix, roles in groups:
            if not isinstance(roles, dict) or (prefix.startswith('hosts.') and prefix[6:] not in HOSTS):
                raise ValueError(f'unknown or malformed model group: {prefix}')
            for role, fields in roles.items():
                if role not in ROLES or not isinstance(fields, dict):
                    raise ValueError(f'unknown or malformed role: {role}')
                for field, value in fields.items():
                    validate_value(f'models.{prefix}.{role}.{field}', value)
    return data


def preferences(path, user=False):
    data = read_object(path)
    allowed = {'integration', 'review_panel', 'models'} if user else {'review_panel'}
    if set(data) - allowed:
        raise ValueError(f'{path}: unknown setting')
    for key, value in data.items():
        if key == 'models':
            validate_models(value)
        else:
            validate_value(key, value)
    return data


def user_defaults():
    return preferences(user_path(), user=True)


def initial_state(text):
    mode = user_defaults().get('integration', 'direct')
    for key in ('integration_default', 'integration'):
        text = re.sub(rf'(?m)^{key}: direct\b', f'{key}: {mode}', text)
    return text


def show(repo, scope='project'):
    defaults = user_defaults()
    values = {'integration': {'value': defaults.get('integration', 'direct'),
                              'source': str(user_path()) if 'integration' in defaults else 'built-in'},
              'review_panel': {'value': defaults.get('review_panel', 'off'),
                               'source': str(user_path()) if 'review_panel' in defaults else 'built-in'}}
    models = {key: {'value': value, 'source': str(user_path())}
              for key, value in flatten(defaults.get('models', {}), 'models').items()}
    result = {'scope': scope, 'settings': values, 'models': models, 'roles': ROLES,
              'hosts': HOSTS, 'locked': None, 'approved_review_panel': None}
    if scope == 'project':
        state_api = sibling('pipeline_state')
        repo = state_api._repo_root(repo)
        state, text, path = state_api.load_state(repo)
        config = repo / '.project/config.json'
        local = preferences(config)
        if 'review_panel' in local:
            values['review_panel'] = {'value': local['review_panel'], 'source': str(config)}
        policy_path = repo / '.project/model-policy.json'
        policy = validate_models(read_object(policy_path))
        models.update({key: {'value': value, 'source': str(policy_path)}
                       for key, value in flatten(policy, 'models').items()})
        values['integration'] = {'value': state.integration_default, 'source': str(path),
                                 'current': state.integration, 'current_source': state.integration_source}
        locked = state.phase in ('build', 'ship', 'shipped') or sibling('build_recovery').context(repo, text)
        values['integration']['locked'] = 'Shipping mode is locked when build starts.' if locked else None
        if state.phase in ('ship', 'shipped') or state.archive:
            result['locked'] = 'Project settings are locked during ship and after shipment.'
        panel = sibling('review_panel')
        paths = [repo / '.project/plan/PLAN.md', repo / '.project/intent/INTENT.md', repo / '.project/CHARTER.md']
        texts = [p.read_text(encoding='utf-8') if safe_path(p).exists() else None for p in paths]
        approved = panel.parse_sources(*texts)
        result['approved_review_panel'] = {'value': ','.join(approved['families']) if approved['mode'] == 'named' else approved['mode'],
                                          'source': approved['source']}
    return result


def set_value(repo, scope, key, value, reset=False):
    repo = repo.resolve()
    if not reset:
        validate_value(key, value)
    elif key not in ('integration', 'review_panel'):
        model_key(key)
    current = show(repo, scope)
    if current['locked']:
        raise ValueError(current['locked'])
    if scope == 'project':
        state, _, _ = sibling('pipeline_state').load_state(repo)
        branch = subprocess.run(['git', '-C', str(repo), 'branch', '--show-current'],
                                capture_output=True, text=True)
        if branch.returncode or not state.branch or branch.stdout.strip() != state.branch:
            raise ValueError('Run the router to bind the project branch before editing settings.')
        head = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--verify', 'HEAD'], capture_output=True)
        if head.returncode == 0:
            closed = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('git_guard.py')),
                                     'closed-milestone'], cwd=repo, capture_output=True, text=True)
            if closed.returncode:
                raise ValueError(closed.stderr.strip() or 'Cannot verify the milestone branch is open.')
    if scope == 'project' and key == 'integration':
        if reset:
            raise ValueError('choose an explicit project shipping mode')
        sibling('pipeline_state').configure_integration(repo, 'default', value)
        return show(repo, scope)
    path = user_path() if scope == 'user' else repo / '.project' / ('model-policy.json' if key.startswith('models.') else 'config.json')
    safe_path(path)
    safe_path(path.with_name(f'.{path.name}.lock'))
    lock = (sibling('pipeline_state')._state_lock(repo / '.project') if scope == 'project'
            else sibling('loop_run').log_lock({'log': str(path)}))
    with lock:
        current = show(repo, scope)
        if current['locked']:
            raise ValueError(current['locked'])
        data = read_object(path)
        bits = key.split('.')
        if scope == 'project' and bits[0] == 'models':
            bits = bits[1:]
        node = data
        for bit in bits[:-1]:
            node = node.setdefault(bit, {})
        if reset:
            node.pop(bits[-1], None)
        else:
            node[bits[-1]] = value
        safe_path(path)
        safe_path(path.with_name(f'.{path.name}.gsd-path-tmp'))
        sibling('_common').atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + '\n')
    return show(repo, scope)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('show', 'validate', 'set', 'reset'))
    parser.add_argument('key', nargs='?')
    parser.add_argument('value', nargs='?')
    parser.add_argument('--scope', choices=('user', 'project'), default='project')
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        declaration = args.repo / '.gsd-path/runtime.json'
        if args.scope == 'project' and (declaration.exists() or declaration.is_symlink()):
            runtime = sibling('status_runtime').resolve_runtime(args.repo.resolve())
            helper = runtime / 'path_config.py'
            if not helper.is_file():
                raise ValueError('Update the selected project runtime to use Path settings.')
            if helper.resolve() != Path(__file__).resolve():
                return subprocess.call([sys.executable, '-B', str(helper), *sys.argv[1:]])
        if args.action in ('set', 'reset'):
            if not args.key or (args.action == 'set' and args.value is None):
                raise ValueError('set requires KEY VALUE; reset requires KEY')
            result = set_value(args.repo, args.scope, args.key, args.value, args.action == 'reset')
        else:
            result = show(args.repo, args.scope)
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({'error': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
