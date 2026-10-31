from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import discovery, flavors, probe, sessions
from .config import Config, resolve_config_path
from .model import PATH_FLAVOR, ProjectStatus

Event = Dict[str, object]


def _current_number(status: ProjectStatus) -> Optional[str]:
    for milestone in status.roadmap_milestones:
        if milestone.get("slug") and milestone.get("slug") == status.milestone:
            return milestone.get("number")
    match = re.search(r"M\d{3,}", status.branch or "")
    return match.group(0) if match else "now"


class Watcher:
    def __init__(self, config: Config, probe_hook: Optional[Callable[[str], None]] = None):
        self.config = config
        self.projects: Dict[str, ProjectStatus] = {}
        self._mtimes: Dict[str, Tuple[Optional[float], ...]] = {}
        self._probe_hook = probe_hook
        self.sessions = sessions.SessionIndex(sessions.expand_session_dirs(config.session_dirs), config.prices,
                                              cache_path=resolve_config_path().parent / "sessions-index.json")

    def poll_once(self, scan_sessions: bool = True) -> List[Event]:
        pairs = discovery.scan_projects(self.config.parents, self.config.excludes, self.config.max_depth)
        events: List[Event] = []
        # Keyed by card id: the root for GSD Path, "<root>::<flavor>" for the others.
        current: Dict[str, ProjectStatus] = {}
        for root, flavor in pairs:
            key = flavors.project_id(root, flavor)
            old = self.projects.get(key)
            mtime = self._cache_key(root, flavor, old)
            if old is not None and any(mtime) and self._mtimes.get(key) == mtime:
                current[key] = old
                continue
            status = self._probe(root, flavor)
            self._mtimes[key] = mtime
            current[key] = status
            if old is None:
                events.append({
                    "type": "project-added",
                    "root": root,
                    "id": key,
                    "detail": f"{status.project or root} — phase {status.phase} ({status.status})",
                })
            else:
                events.extend(self._diff(old, status))
        for key in sorted(set(self.projects) - set(current)):
            old = self.projects[key]
            events.append({
                "type": "project-removed",
                "root": old.root,
                "id": key,
                "detail": old.project or old.root,
            })
            self._mtimes.pop(key, None)
        if scan_sessions:
            self._attach_spend(current)
        else:
            for key, status in current.items():
                previous = self.projects.get(key)
                status.spend = previous.spend if previous is not None else None
        self.projects = current
        return events

    @staticmethod
    def _cache_key(root: str, flavor: str, status: Optional[ProjectStatus]) -> Tuple[Optional[float], ...]:
        if flavor != PATH_FLAVOR:
            return (probe.tree_mtime(flavors.state_dir(root, flavor), flavors.SKIP[flavor]),)
        # The project install decides the workflow status and changes without
        # touching .project, and ship writes the member-close journal in the Git
        # common dir, so both are part of the cache key.
        journal = status.member_close_journal if status is not None else None
        return (probe.tree_mtime(Path(root) / ".project"),
                probe.tree_mtime(Path(root) / ".gsd-path" / "status_runtime.py"),
                probe.tree_mtime(Path(root) / ".gsd-path" / "runtime.json"),
                probe.tree_mtime(Path(journal)) if journal else None)

    def _attach_spend(self, current: Dict[str, ProjectStatus]) -> None:
        """Usage from host session logs changes without touching .project, so
        it is refreshed on every poll, from the incremental session index."""
        try:
            self.sessions.scan(sorted({status.root for status in current.values()}))
        except Exception:  # a broken session file must never stop the poll
            return
        for status in current.values():
            try:
                status.spend = self.sessions.spend_for(status.root, status.roadmap_milestones, _current_number(status))
            except Exception:
                status.spend = None

    def run(self, callback: Callable[[List[Event]], None],
            stop_event: Optional[threading.Event] = None) -> None:
        stop_event = stop_event or threading.Event()
        while not stop_event.is_set():
            events = self.poll_once()
            if events:
                callback(events)
            stop_event.wait(self.config.poll_seconds)

    def _probe(self, root: str, flavor: str = PATH_FLAVOR) -> ProjectStatus:
        if self._probe_hook is not None:
            self._probe_hook(root)
        return probe.probe_project(root) if flavor == PATH_FLAVOR else flavors.probe_foreign(root, flavor)

    @staticmethod
    def _diff(old: ProjectStatus, new: ProjectStatus) -> List[Event]:
        events: List[Event] = []
        root = new.root
        key = new.id or root
        if old.phase != new.phase:
            events.append({
                "type": "phase-changed",
                "root": root,
                "id": key,
                "detail": f"{old.phase} -> {new.phase}",
            })
        if old.status != new.status:
            events.append({
                "type": "status-changed",
                "root": root,
                "id": key,
                "detail": f"{old.status} -> {new.status}",
            })
        if new.status == "blocked" and old.status != "blocked":
            events.append({
                "type": "blocked",
                "root": root,
                "id": key,
                "detail": f"{new.project or root} is blocked in phase {new.phase}",
            })
        if (old.tasks_done, old.tasks_total) != (new.tasks_done, new.tasks_total):
            events.append({
                "type": "tasks-changed",
                "root": root,
                "id": key,
                "detail": f"{new.tasks_done}/{new.tasks_total} done (was {old.tasks_done}/{old.tasks_total})",
            })
        if new.pending_answers and len(new.pending_answers) != len(old.pending_answers):
            events.append({
                "type": "pending-answers",
                "root": root,
                "id": key,
                "detail": f"{len(new.pending_answers)} pending answer(s)",
            })
        return events
