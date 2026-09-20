"""Narrow bridge from dashboard settings to the plugin's config command."""
import json
from pathlib import Path
import subprocess
import sys


def configure(plugin, projects, request, write=False):
    allowed = {'scope', 'root', 'key', 'value', 'action'} if write else {'scope', 'root'}
    if not isinstance(request, dict) or set(request) - allowed:
        raise ValueError('unknown settings request field')
    scope = request.get('scope', 'user')
    if scope not in ('user', 'project'):
        raise ValueError('scope must be user or project')
    root = request.get('root')
    command = [sys.executable, '-B']
    if scope == 'project':
        if not isinstance(root, str) or root not in projects:
            raise ValueError('select a watched project')
        launcher = Path(root) / '.gsd-path/status_runtime.py'
        if not launcher.is_file() or launcher.is_symlink():
            raise ValueError('Update this project runtime before editing Path settings.')
        resolved = subprocess.run(command + [str(launcher), '--repo', root, '--runtime-path'],
                                  capture_output=True, text=True)
        if resolved.returncode:
            raise ValueError(resolved.stderr.strip() or 'Cannot resolve project runtime.')
        helper = Path(resolved.stdout.strip()) / 'path_config.py'
    else:
        helper = plugin.src_dir / 'scripts/path_config.py'
    if not helper.is_file() or helper.is_symlink():
        raise ValueError('Update the plugin or selected project runtime to use Path settings.')
    action = request.get('action', 'set') if write else 'show'
    if action not in (('set', 'reset') if write else ('show',)):
        raise ValueError('settings action must be set or reset')
    args = [action, '--scope', scope]
    if root and scope == 'project':
        args += ['--repo', root]
    if write:
        key, value = request.get('key'), request.get('value')
        if not isinstance(key, str) or key.startswith('-'):
            raise ValueError('setting key must be a string')
        args = [action, key] + args[1:]
        if action == 'set':
            if not isinstance(value, str) or value.startswith('-'):
                raise ValueError('setting value must be a string')
            args.insert(2, value)
    result = subprocess.run(command + [str(helper)] + args, capture_output=True, text=True)
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise ValueError(result.stderr.strip() or 'Settings command returned no result.')
    if result.returncode:
        raise ValueError(payload.get('error', result.stderr.strip()))
    return payload
