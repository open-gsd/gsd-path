#!/usr/bin/env python3
"""Render a read-only coder intent view from the approved task and intent."""

import argparse
import hashlib
import re
import sys
from pathlib import Path

try:
    from scripts import check_handoffs as contracts
except ImportError:
    import check_handoffs as contracts


def render(repo: Path, task: Path) -> str:
    intent_path = repo.resolve() / '.project/intent/INTENT.md'
    task = task.resolve()
    intent = intent_path.read_bytes().decode('utf-8')
    task_text = task.read_bytes().decode('utf-8')
    owned = contracts._owned_criteria(task_text, task.stem)
    criteria = contracts._success_criteria(intent)
    unknown = set(owned) - set(criteria)
    if unknown:
        raise contracts.HandoffError('unknown owned criteria: ' + ', '.join(sorted(unknown)))
    projected, mode = intent, 'full-intent'
    sections = list(re.finditer(r'(?ms)^## Success criteria[ \t]*\n(?P<body>.*?)(?=^## |\Z)', intent))
    if len(sections) == 1:
        section = sections[0]
        body = section['body']
        items = list(re.finditer(r'(?m)^(\d+)\. .+\n?', body))
        # Project only simple numbered prose. Preserve unfamiliar Markdown in full.
        simple = (items and not body[:items[0].start()].strip()
                  and '```' not in body and '~~~' not in body and '<!--' not in body
                  and [f'SC{item[1]}' for item in items] == list(criteria))
        chunks = [body[item.start():items[n + 1].start() if n + 1 < len(items) else len(body)]
                  for n, item in enumerate(items)]
        simple = simple and all(not line.strip() or line[:1].isspace()
                                for chunk in chunks for line in chunk.splitlines()[1:])
        if simple:
            before, after = intent[:section.start('body')], intent[section.end('body'):]
            # Corrections and task interfaces can explicitly refer to another SC.
            required = set(owned) | set(re.findall(r'\bSC\d+\b', before + after + task_text))
            selected = ''.join(chunk for item, chunk in zip(items, chunks) if f'SC{item[1]}' in required)
            projected = before + '\n' + (selected or '- No criteria assigned.\n\n') + after
            mode = 'owned-criteria'
    return ('## Generated intent context\n\n'
            f'Source: {intent_path}\n'
            f'Intent SHA256: {hashlib.sha256(intent.encode()).hexdigest()}\n'
            f'Task: {task}\n'
            f'Task SHA256: {hashlib.sha256(task_text.encode()).hexdigest()}\n'
            f'Mode: {mode}\n\n'
            'Use this view for intent. All non-criterion text is verbatim; selected criteria retain '
            'their original numbers. The source remains authoritative. Read it if a dependency '
            'or ambiguity requires omitted criteria.\n\n' + projected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--task', type=Path, required=True)
    args = parser.parse_args()
    try:
        output = render(args.repo, args.task)
    except (OSError, contracts.HandoffError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(output, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
