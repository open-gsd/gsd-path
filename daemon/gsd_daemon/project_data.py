"""On-demand records and coverage; never infer absence as zero or success."""
from __future__ import annotations

import json
from pathlib import Path

from .history import resolve_history_path
from .project_files import FileAccessError, _read_current, file_index, watched_root


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


def project_records(watcher, key):
    raw_root = watched_root(watcher.projects, key)
    project = watcher.projects.get(key) or next(p for p in watcher.projects.values() if str(p.root) == raw_root)
    root = Path(raw_root).resolve(strict=True)
    listing = file_index(root)
    if project.record_files is None:
        usage, usage_source = _records(root, '.project/build/usage.jsonl')
        ledger, ledger_source = _records(root, '.project/build/verify-ledger.jsonl')
        runtime = project.status_source == 'runtime'
        # Without a runtime payload, the workflow result says why: not set up, not started or unverified.
        sources = [usage_source, ledger_source,
                   {'path': '.gsd-path/status_runtime.py', 'status': 'loaded' if runtime else project.workflow.get('label', 'Unverified').lower(),
                    'detail': 'Runtime status' if runtime else project.workflow.get('reason') or 'Parsed-file fallback; runtime status was not verified.'}]
    else:
        # gsd-pi and gsd-core keep no GSD Path usage or runtime; their verify ledger is the card's (newest first).
        usage, ledger, sources = [], list(reversed(project.ledger)), []
    activity = []
    try:
        lines = resolve_history_path().read_text(encoding='utf-8').splitlines()
        invalid = []
        for number, line in enumerate(lines, 1):
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError('expected an object')
                if event.get('id', event.get('root')) == (project.id or raw_root):
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
    paths = ['.project/STATE.md', '.project/ROADMAP.md', '.project/CHARTER.md', '.project/intent/INTENT.md',
             '.project/plan/PLAN.md', '.project/review/FINAL.md', '.project/discuss/ANSWERS.md', '.project/LESSONS.md', '.project/next/STATE.md']
    for path in [f['path'] for f in project.record_files] if project.record_files is not None else paths:
        sources.append({'path': path, 'status': 'available' if path in known_paths else 'missing'})
    sources.extend({**source, 'path': source['source']} for source in listing['coverage'])
    return {'root': raw_root, 'id': project.id or raw_root, 'sources': sources, 'files': listing['files'], 'file_scope': listing['scope'],
            'usage_records': usage, 'verify_records': list(reversed(ledger)),
            'activity': list(reversed(activity)), 'turns': list(reversed(turns)),
            'project': project.to_dict()}
