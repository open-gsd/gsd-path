from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import discovery, probe
from .config import Config
from .model import ProjectStatus

Event = Dict[str, object]


class Watcher:
    def __init__(self, config: Config, probe_hook: Optional[Callable[[str], None]] = None):
        self.config = config
        self.projects: Dict[str, ProjectStatus] = {}
        self._mtimes: Dict[str, Optional[float]] = {}
        self._probe_hook = probe_hook

    def poll_once(self) -> List[Event]:
        roots = discovery.scan(self.config.parents, self.config.excludes, self.config.max_depth)
        events: List[Event] = []
        current: Dict[str, ProjectStatus] = {}
        for root in roots:
            mtime = probe.tree_mtime(Path(root) / ".project")
            old = self.projects.get(root)
            if old is not None and mtime is not None and self._mtimes.get(root) == mtime:
                current[root] = old
                continue
            status = self._probe(root)
            self._mtimes[root] = mtime
            current[root] = status
            if old is None:
                events.append({
                    "type": "project-added",
                    "root": root,
                    "detail": f"{status.project or root} — phase {status.phase} ({status.status})",
                })
            else:
                events.extend(self._diff(old, status))
        for root in sorted(set(self.projects) - set(current)):
            old = self.projects[root]
            events.append({
                "type": "project-removed",
                "root": root,
                "detail": old.project or root,
            })
            self._mtimes.pop(root, None)
        self.projects = current
        return events

    def run(self, callback: Callable[[List[Event]], None],
            stop_event: Optional[threading.Event] = None) -> None:
        stop_event = stop_event or threading.Event()
        while not stop_event.is_set():
            events = self.poll_once()
            if events:
                callback(events)
            stop_event.wait(self.config.poll_seconds)

    def _probe(self, root: str) -> ProjectStatus:
        if self._probe_hook is not None:
            self._probe_hook(root)
        return probe.probe_project(root)

    @staticmethod
    def _diff(old: ProjectStatus, new: ProjectStatus) -> List[Event]:
        events: List[Event] = []
        root = new.root
        if old.phase != new.phase:
            events.append({
                "type": "phase-changed",
                "root": root,
                "detail": f"{old.phase} -> {new.phase}",
            })
        if old.status != new.status:
            events.append({
                "type": "status-changed",
                "root": root,
                "detail": f"{old.status} -> {new.status}",
            })
        if new.status == "blocked" and old.status != "blocked":
            events.append({
                "type": "blocked",
                "root": root,
                "detail": f"{new.project or root} is blocked in phase {new.phase}",
            })
        if (old.tasks_done, old.tasks_total) != (new.tasks_done, new.tasks_total):
            events.append({
                "type": "tasks-changed",
                "root": root,
                "detail": f"{new.tasks_done}/{new.tasks_total} done (was {old.tasks_done}/{old.tasks_total})",
            })
        if new.pending_answers and len(new.pending_answers) != len(old.pending_answers):
            events.append({
                "type": "pending-answers",
                "root": root,
                "detail": f"{len(new.pending_answers)} pending answer(s)",
            })
        return events
