#!/usr/bin/env python3
# gsd-path project runtime
"""Resolve explicit sub-agent model choices without model reasoning."""

import argparse
import hashlib
import json
import re
import sys
sys.dont_write_bytecode = True
from pathlib import Path

try:
    from ._common import atomic_write
    from .loop_run import log_lock
    from .review_panel import family_of_slug
except ImportError:
    from _common import atomic_write
    from loop_run import log_lock
    from review_panel import family_of_slug

FIELDS = ('model', 'effort')
HEAVY = ('plan', 'plan_patch', 'decide', 'roadmap')
LIGHT = ('inspect_docs', 'docs_audit')
SCHEMA = 'gsd-path/model-selection/v1'


class PolicyError(ValueError):
    """An explicit selection cannot be honored."""


def object_value(value, label):
    if not isinstance(value, dict):
        raise PolicyError(f'{label} must be an object')
    return value


def read_json(path):
    try:
        return object_value(json.loads(Path(path).read_text(encoding='utf-8')), str(path))
    except (OSError, ValueError) as error:
        raise PolicyError(f'{path}: {error}') from error


def settings(value, label):
    object_value(value, label)
    if set(value) - set(FIELDS):
        raise PolicyError(f'{label}: unknown model setting')
    for field, setting in value.items():
        if not isinstance(setting, str) or not setting.strip() or setting != setting.strip():
            raise PolicyError(f'{label}.{field} must be a nonempty string (or inherit)')
    return value


def policy_path(repo, project_dir):
    project = Path(repo) / project_dir
    return (project.parent if project.name == 'next' else project) / 'model-policy.json'


def load_policy(repo, project_dir):
    path = policy_path(repo, project_dir)
    data = read_json(path) if path.exists() else {}
    if set(data) - {'roles', 'hosts'}:
        raise PolicyError(f'{path}: unknown policy field')
    groups = [('roles', object_value(data.get('roles', {}), 'roles'))]
    for host, group in object_value(data.get('hosts', {}), 'hosts').items():
        groups.append((f'hosts.{host}', object_value(group, f'hosts.{host}')))
    for label, group in groups:
        for role, choice in group.items():
            settings(choice, f'{label}.{role}')
    return data


def resolve(repo, project_dir, role, capabilities, overrides, previous=None):
    """Resolve each field once; a saved selection bypasses changed project policy."""
    caps = object_value(capabilities, 'capabilities')
    host = caps.get('host')
    if not isinstance(host, str) or not host:
        raise PolicyError(f'{role}: host identity is required for model selection')
    if previous is not None:
        if (previous.get('schema'), previous.get('role'), previous.get('host')) != (SCHEMA, role, host):
            raise PolicyError(f'{role}: recorded selection belongs to another role or host')
        selected = dict(previous['selected'])
        sources = dict(previous['sources'])
        policy_hash = previous['policy_hash']
        for field, value in settings(overrides, 'task').items():
            if value != selected[field]:
                raise PolicyError(f'explicit {field}={value!r} differs from the pinned selection; reassign explicitly')
        if (selected['model'] == 'inherit' and previous.get('effective_model')
                and caps.get('inherited_model') != previous['effective_model']):
            raise PolicyError('recorded inherited model no longer matches the advertised identity')
    else:
        policy = load_policy(repo, project_dir)
        try:
            from .path_config import user_defaults
        except ImportError:
            from path_config import user_defaults
        try:
            defaults = user_defaults().get('models', {})
        except (OSError, ValueError, RuntimeError) as error:
            raise PolicyError(str(error)) from error
        selected = dict.fromkeys(FIELDS, 'inherit')
        sources = dict.fromkeys(FIELDS, 'default')
        tier = 'heavy' if role in HEAVY else 'light' if role in LIGHT else None
        hint = ('high' if tier == 'heavy' else 'low') if host == 'codex' and tier else tier
        hint = caps.get('effort_hints', {}).get(tier, hint)
        if hint in caps.get('effort', {}).get('values', []):
            selected['effort'] = hint
        for label, group in (
            (f'user.roles.{role}', defaults.get('roles', {}).get(role, {})),
            (f'user.hosts.{host}.{role}', defaults.get('hosts', {}).get(host, {}).get(role, {})),
            (f'roles.{role}', policy.get('roles', {}).get(role, {})),
            (f'hosts.{host}.{role}', policy.get('hosts', {}).get(host, {}).get(role, {})),
            ('task', settings(overrides, 'task')),
        ):
            for field, value in group.items():
                selected[field], sources[field] = value, label
        policy_hash = hashlib.sha256(json.dumps({'user': defaults, 'project': policy}, sort_keys=True).encode()).hexdigest()
    native, cli, controls = {}, {}, {}
    for field, value in selected.items():
        spec = object_value(caps.get(field, {}), f'capabilities.{field}')
        controls[field] = spec.get('args', [])
        if value == 'inherit':
            cli[field] = []
            continue
        if value not in spec.get('values', []):
            raise PolicyError(f'{role}: {sources[field]} requests {field}={value!r}, unavailable on {host}')
        native_field = spec.get('field')
        if native_field:
            if not isinstance(native_field, str) or not re.fullmatch(r'[A-Za-z_]\w*', native_field):
                raise PolicyError(f'{host}: invalid native field for {field}')
            if native_field in native:
                raise PolicyError(f'{host}: model and effort use the same native field')
            native[native_field] = value
        args = spec.get('args', [])
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            raise PolicyError(f'{host}: {field} args must be an argument list')
        if args and not any('{value}' in arg for arg in args):
            raise PolicyError(f'{host}: {field} args must deliver {{value}}')
        cli[field] = [arg.replace('{value}', value) for arg in args]
    return {'schema': SCHEMA, 'role': role, 'host': host, 'selected': selected,
            'sources': sources, 'native': native, 'cli': cli, 'controls': controls, 'policy_hash': policy_hash,
            'effective_model': (selected['model'] if selected['model'] != 'inherit'
                                else caps.get('inherited_model')),
            'identity_evidence': 'requested controls; host execution is recorded by the dispatcher'}


def validate_panel(selection, family, excluded=()):
    model = selection['effective_model']
    actual = family_of_slug(model) if model else None
    if actual != family or actual in excluded:
        raise PolicyError(f'panel model {model!r} must belong to independent family {family}')


def command_args(argv, selection):
    """Expand whole-argument slots only. Never parse or rewrite arbitrary host commands."""
    result = list(argv)
    if any('{model}' in arg for arg in result):
        raise PolicyError('legacy model placeholder is incompatible with capability-based dispatch')
    for field in FIELDS:
        slot = '{' + field + '_args}'
        explicit = selection['sources'][field] != 'default'
        args = selection['cli'][field]
        # Only match the controls declared by the adapter, not guessed CLI syntax.
        templates = selection['controls'][field]
        prefixes = [arg.split('{value}')[0] for arg in templates if '{value}' in arg and arg != '{value}']
        flags = [arg for arg in templates if arg.startswith('-') and '{value}' not in arg]
        if any(any(arg.startswith(prefix) for prefix in prefixes)
               or (not prefixes and any(arg == flag or arg.startswith(flag + '=') for flag in flags))
               for arg in result):
            raise PolicyError(f'fixed {field} controls conflict with policy selection')
        if result.count(slot) > 1 or any(slot in arg and arg != slot for arg in result):
            raise PolicyError(f'{slot} must occur once as a whole argument')
        if slot not in result:
            if explicit:
                raise PolicyError(f'explicit {field} requires a {slot} slot in the child command')
            if selection['selected'][field] != 'inherit':
                raise PolicyError(f'{field} hint requires a {slot} slot in the child command')
            continue
        if selection['selected'][field] != 'inherit' and not args:
            raise PolicyError(f'host does not advertise CLI arguments for {field}')
        index = result.index(slot)
        result[index:index + 1] = args
    return result


def task_settings(path):
    # Reuse the task contract parser; nested or duplicate overrides are not accepted.
    try:
        from .check_handoffs import _strict_frontmatter
    except ImportError:
        from check_handoffs import _strict_frontmatter
    fields = _strict_frontmatter(Path(path).read_text(encoding='utf-8'), str(path))
    return settings({key: fields[key] for key in FIELDS if key in fields}, str(path))


def native_record(args):
    """The parent owns lifecycle; release requires its recorded terminal-result receipt."""
    record = args.record.resolve()
    with log_lock({'log': str(record)}):
        data = read_json(record) if record.exists() else None
        identity = {'repo': str(args.repo.resolve()), 'project_dir': args.project_dir,
                    'scope': args.scope, 'assignment': args.assignment, 'role': args.role}
        if data is not None and data.get('identity') != identity:
            raise PolicyError('record belongs to another assignment or milestone/track/cycle')
        if args.action == 'release':
            if data is None or not args.terminal_result:
                raise PolicyError('release requires an existing record and terminal-result evidence')
            data.update(active=False, terminal_result=args.terminal_result)
        else:
            if args.capabilities is None:
                raise PolicyError('capabilities are required')
            if args.action == 'reassign' and (data is None or data['active'] or not args.ruling):
                raise PolicyError('reassign requires an inactive assignment and an explicit owner ruling')
            caps = read_json(args.capabilities)
            overrides = task_settings(args.task) if args.task else {}
            for field in FIELDS:
                value = getattr(args, field)
                if value is not None:
                    if field in overrides and overrides[field] != value:
                        raise PolicyError('reassignment conflicts with the approved task contract')
                    overrides[field] = value
            if data and args.action == 'reassign':
                changed_fields = set(overrides)
                overrides = dict(data['selection']['selected'], **overrides)
            previous = data['selection'] if data and args.action == 'resolve' else None
            selection = resolve(args.repo, args.project_dir, args.role, caps, overrides, previous)
            if data and args.action == 'reassign':
                for field in FIELDS:
                    if field not in changed_fields:
                        selection['sources'][field] = data['selection']['sources'][field]
            if (args.panel_family and selection['sources']['model'] == 'default'
                    and selection['selected']['model'] == 'inherit' and args.panel_model):
                selection = resolve(args.repo, args.project_dir, args.role, caps,
                                    dict(overrides, model=args.panel_model), previous)
            for field in FIELDS:
                if selection['selected'][field] != 'inherit' and not caps.get(field, {}).get('field'):
                    raise PolicyError(f'host does not advertise a native field for {field}')
            if args.panel_family:
                validate_panel(selection, args.panel_family, args.exclude_family)
            history = data.get('history', []) if data else []
            if data and args.action == 'reassign':
                history = [*history, {'selection': data['selection'], 'ruling': args.ruling,
                                     'terminal_result': data.get('terminal_result')}]
            data = {'identity': identity, 'selection': selection, 'history': history,
                    'active': args.action == 'resolve'}
        atomic_write(record, json.dumps(data, indent=2, sort_keys=True) + '\n')
        return {'status': 'ready', **data}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('resolve', 'release', 'reassign'))
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--project-dir', default='.project')
    parser.add_argument('--scope', required=True, help='milestone, track and review cycle identity')
    parser.add_argument('--assignment', required=True)
    parser.add_argument('--role', required=True)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--capabilities', type=Path)
    parser.add_argument('--task', type=Path)
    parser.add_argument('--model')
    parser.add_argument('--effort')
    parser.add_argument('--ruling')
    parser.add_argument('--terminal-result')
    parser.add_argument('--panel-family')
    parser.add_argument('--panel-model', help='default model from the panel roster; policy may override it')
    parser.add_argument('--exclude-family', action='append', default=[])
    try:
        result = native_record(parser.parse_args(argv))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'blocked', 'reason': str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
