"""Chart data for the native app, built from what the daemon already records:
host session logs, the activity history, task files, and the verify ledger.

A chart with no data is ``None`` with a reason in ``missing``. It is never zero.
"""
from __future__ import annotations

import json
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from .history import resolve_history_path
from .probe import _parse_iso
from .sessions import cost_for


def usage_by_day(records: Iterable[dict], prices: dict) -> Optional[dict]:
    """Tokens, turns, and cost per day. A model without a price adds tokens but no cost."""
    days: Dict[str, dict] = {}
    unpriced: List[str] = []
    for entry in records:
        date = (entry.get("at") or "")[:10]
        if not date:
            continue
        day = days.setdefault(date, {"date": date, "tokens": 0, "turns": 0, "cost": None})
        day["tokens"] += entry["tokens_in"] + entry["tokens_cached"] + entry["tokens_out"]
        day["turns"] += 1
        cost = cost_for(prices, entry.get("model"), entry["tokens_in"], entry["tokens_cached"], entry["tokens_out"])
        if cost is not None:
            day["cost"] = round((day["cost"] or 0.0) + cost, 4)
        elif entry.get("model") and entry["model"] not in unpriced:
            unpriced.append(entry["model"])
    if not days:
        return None
    return {"days": [days[date] for date in sorted(days)], "unpriced": unpriced}


def phase_seconds(events: Iterable[dict], roots: Iterable[str], now: datetime) -> Optional[List[dict]]:
    """Time in each phase from recorded phase changes: a phase lasts until the
    next change in that project, and the last one until now."""
    wanted = {os.path.abspath(root) for root in roots}
    changes: Dict[str, list] = {}
    for event in events:
        root = event.get("root")
        at = _parse_iso(event.get("at"))
        detail = event.get("detail")
        if (event.get("type") != "phase-changed" or not isinstance(root, str) or at is None
                or not isinstance(detail, str) or " -> " not in detail):
            continue
        root = os.path.abspath(os.path.expanduser(root))
        if root in wanted:
            changes.setdefault(root, []).append((at, detail.split(" -> ", 1)[1]))
    totals: Dict[str, float] = {}
    for entries in changes.values():
        entries.sort(key=lambda entry: entry[0])
        for index, (at, phase) in enumerate(entries):
            if phase == "None":  # the phase became unreadable: this time belongs to no phase
                continue
            end = entries[index + 1][0] if index + 1 < len(entries) else now
            totals[phase] = totals.get(phase, 0.0) + max(0.0, (end - at).total_seconds())
    if not totals:
        return None
    return [{"phase": phase, "seconds": int(seconds)}
            for phase, seconds in sorted(totals.items(), key=lambda item: -item[1])]


def tasks_per_wave(tasks) -> Optional[List[dict]]:
    waves: Dict[int, dict] = {}
    for task in tasks:
        if task.wave is None:
            continue
        slot = waves.setdefault(task.wave, {"wave": task.wave, "total": 0, "done": 0})
        slot["total"] += 1
        slot["done"] += task.status == "done"
    return [waves[wave] for wave in sorted(waves)] or None


def verify_history(ledger: Iterable[dict]) -> Optional[List[dict]]:
    """Verify runs, oldest first, so a chart reads left to right."""
    return sorted(ledger, key=lambda entry: entry.get("recorded_at") or "") or None


def _history_events() -> List[dict]:
    # ponytail: reads the whole history file on each request; keep an offset index if it gets slow.
    try:
        lines = resolve_history_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def route(handler, _body=None) -> dict:
    """GET /api/stats[?root=<watched project>]. Without root: all projects."""
    query = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
    root = (query.get("root") or [None])[0]
    watcher = handler.watcher
    if root is not None and root not in watcher.projects:
        raise ValueError("root is not a watched project")
    projects = [watcher.projects[root]] if root else list(watcher.projects.values())
    roots = list(dict.fromkeys(str(project.root) for project in projects))
    missing: Dict[str, str] = {}

    # A scan changes the session index; read it under the scan lock.
    # ponytail: this waits for a scan in progress; copy-on-write records if charts must not wait.
    with handler.scan_lock:
        records = [entry for item in roots for entry in watcher.sessions.records_for(item)]
    usage = usage_by_day(records, watcher.sessions.prices)
    if usage is None:
        missing["days"] = "No host sessions matched. Check the session folders in Settings."

    phases = phase_seconds(_history_events(), roots, datetime.now(timezone.utc))
    if phases is None:
        missing["phases"] = "No phase change recorded yet. The monitor records one when it sees it happen."

    if root:
        waves = tasks_per_wave(projects[0].tasks)
        if waves is None:
            missing["waves"] = "The current milestone has no tasks in waves."
    else:
        waves = None
        missing["waves"] = "Choose a project to see its waves."

    verify = verify_history(
        {**entry, "project": project.project or os.path.basename(str(project.root))}
        for project in projects for entry in project.ledger)
    if verify is None:
        missing["verify"] = "No verify run recorded."

    return {"scope": root, "days": usage["days"] if usage else None, "unpriced": usage["unpriced"] if usage else [],
            "phases": phases, "waves": waves, "verify": verify, "missing": missing}
