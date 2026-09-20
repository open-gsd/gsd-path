"""On-demand records and coverage; never infer absence as zero or success."""
from __future__ import annotations

import json
from pathlib import Path

from .history import resolve_history_path
from .project_files import FileAccessError, _read_current, file_index


def _records(root, path):
    try:
        raw, modified = _read_current(root, path)
        text = raw.decode('utf-8-sig')
    except FileAccessError as error:
        return [], {'path': path, 'status': error.status, 'error': str(error)}
    except UnicodeError:
        return [], {'path': path, 'status': 'unsupported', 'error': 'Source is not UTF-8 text.'}
    records, invalid = [], []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError('expected an object')
            records.append(record)
        except ValueError:
            invalid.append(number)
    return records, {'path': path, 'status': 'partial' if invalid else 'loaded', 'records': len(records),
                     'invalid_lines': invalid, 'modified': modified}


def project_records(watcher, raw_root):
    project = next((p for p in watcher.projects.values() if str(p.root) == raw_root), None)
    if project is None:
        raise FileAccessError('Select a watched project.', 403)
    root = Path(raw_root).resolve(strict=True)
    listing = file_index(root)
    usage, usage_source = _records(root, '.project/build/usage.jsonl')
    ledger, ledger_source = _records(root, '.project/build/verify-ledger.jsonl')
    sources = [usage_source, ledger_source,
               {'path': '.gsd-path/status_runtime.py', 'status': 'loaded' if project.status_source == 'runtime' else 'unverified',
                'detail': 'Runtime status' if project.status_source == 'runtime' else 'Parsed-file fallback; runtime status was not verified.'}]
    activity = []
    try:
        lines = resolve_history_path().read_text(encoding='utf-8').splitlines()
        invalid = []
        for number, line in enumerate(lines, 1):
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError('expected an object')
                if event.get('root') == raw_root:
                    activity.append(event)
            except ValueError:
                invalid.append(number)
        sources.append({'path': 'daemon activity history', 'status': 'partial' if invalid else 'loaded',
                        'records': len(activity), 'invalid_lines': invalid})
    except FileNotFoundError:
        sources.append({'path': 'daemon activity history', 'status': 'missing'})
    except (OSError, UnicodeError) as error:
        sources.append({'path': 'daemon activity history', 'status': 'failed', 'error': str(error)})
    try:
        turns = watcher.sessions.records_for(raw_root)
        if not isinstance(turns, list):
            turns = []
        sources.append({'path': 'host session usage', 'status': 'indexed' if turns else 'no indexed records', 'records': len(turns),
                        'detail': 'Records currently indexed from Codex and Claude Code logs matched by working directory. This is not a completeness check of all host logs. Other hosts are not supported.'})
    except (OSError, ValueError) as error:
        turns = []
        sources.append({'path': 'host session usage', 'status': 'failed', 'error': str(error)})
    known_paths = {f['path'] for f in listing['files']}
    for path in ['.project/STATE.md', '.project/ROADMAP.md', '.project/CHARTER.md', '.project/intent/INTENT.md',
                 '.project/plan/PLAN.md', '.project/review/FINAL.md', '.project/discuss/ANSWERS.md', '.project/LESSONS.md', '.project/next/STATE.md']:
        sources.append({'path': path, 'status': 'available' if path in known_paths else 'missing'})
    sources.extend({**source, 'path': source['source']} for source in listing['coverage'])
    return {'root': raw_root, 'sources': sources, 'files': listing['files'], 'file_scope': listing['scope'],
            'usage_records': usage, 'verify_records': list(reversed(ledger)),
            'activity': list(reversed(activity)), 'turns': list(reversed(turns)),
            'project': project.to_dict()}
