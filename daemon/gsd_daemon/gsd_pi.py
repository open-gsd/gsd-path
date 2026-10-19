"""Read a gsd-pi project (.gsd/) into the card fields GSD Path cards use.

gsd-pi keeps its truth in gsd.db and renders the markdown from it. The reader
opens the database read-only. A project with no rows there falls back to the
legacy markdown layout (milestones/M###/slices/S##/tasks), and then to the
milestone registry in STATE.md.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from .model import ProjectStatus, TaskSummary
from .probe import _section_paragraph

# The same steps as a gsd-core card; gsd-pi's own phase names map onto them.
STEPS = ["discuss", "research", "plan", "execute", "verify"]
STEP_OF = {
    "pre-planning": "discuss", "needs-discussion": "discuss", "discussing": "discuss",
    "researching": "research",
    "planning": "plan", "refining": "plan", "evaluating-gates": "plan", "replanning-slice": "plan",
    "executing": "execute", "escalating-task": "execute",
    "verifying": "verify", "summarizing": "verify", "advancing": "verify",
    "validating-milestone": "verify", "completing-milestone": "verify",
}
# gsd-pi's closed statuses (status-guards.ts).
CLOSED = {"complete", "done", "skipped", "closed", "cancelled", "blocker-accepted"}
ID_RE = r"(M\d+(?:-[a-z0-9]+)?)"
STATE_FIELD_RE = r"^\*\*{label}:\*\*\s*(.+?)\s*$"
REGISTRY_RE = re.compile(r"^-\s+(✅|🔄|⏸️|⬜)\s+\*\*" + ID_RE + r":\*\*\s*(.*?)\s*$", re.MULTILINE)
REGISTRY_STATUS = {"✅": "complete", "🔄": "active", "⏸️": "parked", "⬜": "pending"}
SLICE_LINE_RE = re.compile(r"^-\s+\[([ xX])\]\s+\*\*(S\d+):\s*(.+?)\*\*", re.MULTILINE)
TASK_LINE_RE = re.compile(r"^-\s+\[([ xX])\]\s+\*\*(T\d+):\s*(.+?)\*\*", re.MULTILINE)


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _query(connection: sqlite3.Connection, *queries: str) -> List[dict]:
    """The rows of the first query this schema version accepts; [] when none does."""
    for sql in queries:
        try:
            return [dict(row) for row in connection.execute(sql)]
        except sqlite3.Error:
            continue
    return []


def _from_db(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        # The daemon never writes a watched project. No -wal file means no open writer, and mode=ro
        # would create -wal/-shm there; immutable=1 does not. With a writer, mode=ro sees its commits.
        path = path.resolve()
        live = path.with_name(path.name + "-wal").exists()
        connection = sqlite3.connect(path.as_uri() + ("?mode=ro" if live else "?immutable=1"),
                                     uri=True, timeout=1)
    except (sqlite3.Error, ValueError):
        return None
    try:
        connection.row_factory = sqlite3.Row
        data = {
            "milestones": _query(connection, "SELECT id, title, status, vision FROM milestones ORDER BY id",
                                 "SELECT id, title, status FROM milestones ORDER BY id"),
            "slices": _query(connection, "SELECT milestone_id, id, title, status FROM slices ORDER BY milestone_id, id"),
            "tasks": _query(connection,
                            "SELECT milestone_id, slice_id, id, title, status, files FROM tasks ORDER BY milestone_id, slice_id, id",
                            "SELECT milestone_id, slice_id, id, title, status FROM tasks ORDER BY milestone_id, slice_id, id"),
            "assessments": _query(connection, "SELECT path, milestone_id, status, scope FROM assessments ORDER BY created_at, path"),
            "evidence": _query(connection, "SELECT milestone_id, command, verdict, created_at FROM verification_evidence "
                                           "ORDER BY created_at DESC, id DESC"),
        }
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return data if data["milestones"] else None


def _from_markdown(base: Path) -> Optional[dict]:
    """The legacy layout, where the markdown was the record."""
    try:
        folders = sorted(p for p in (base / "milestones").iterdir() if p.is_dir() and re.fullmatch(ID_RE, p.name))
    except OSError:
        return None
    data: Dict[str, List[dict]] = {"milestones": [], "slices": [], "tasks": [], "assessments": [], "evidence": []}
    for folder in folders:
        mid = folder.name
        roadmap = _text(folder / f"{mid}-ROADMAP.md")
        title = re.search(rf"^#\s+{re.escape(mid)}:\s*(.+?)\s*$", roadmap, re.MULTILINE)
        vision = re.search(r"^\*\*Vision:\*\*\s*(.+?)\s*$", roadmap, re.MULTILINE)
        data["milestones"].append({"id": mid, "title": title.group(1) if title else "",
                                   "status": "complete" if (folder / f"{mid}-SUMMARY.md").is_file() else "active",
                                   "vision": vision.group(1) if vision else None})
        for mark, sid, slice_title in SLICE_LINE_RE.findall(roadmap):
            data["slices"].append({"milestone_id": mid, "id": sid, "title": slice_title,
                                   "status": "complete" if mark != " " else "pending"})
            slice_dir = folder / "slices" / sid
            for task_mark, tid, task_title in TASK_LINE_RE.findall(_text(slice_dir / f"{sid}-PLAN.md")):
                done = task_mark != " " or (slice_dir / "tasks" / f"{tid}-SUMMARY.md").is_file()
                data["tasks"].append({"milestone_id": mid, "slice_id": sid, "id": tid, "title": task_title,
                                      "status": "complete" if done else "pending"})
    return data if data["milestones"] else None


def _from_registry(state_text: str) -> Optional[dict]:
    milestones = [{"id": mid, "title": title, "status": REGISTRY_STATUS[glyph], "vision": None}
                  for glyph, mid, title in REGISTRY_RE.findall(state_text)]
    return {"milestones": milestones, "slices": [], "tasks": [], "assessments": [], "evidence": []} if milestones else None


def _field(state_text: str, label: str) -> Optional[str]:
    match = re.search(STATE_FIELD_RE.format(label=re.escape(label)), state_text, re.MULTILINE)
    value = match.group(1) if match else None
    return None if value is None or value.lower() == "none" else value


def _task_status(raw: str) -> str:
    raw = (raw or "").lower()
    if raw in CLOSED:
        return "done"
    if raw == "blocked":
        return "blocked"
    return "active" if raw in ("active", "in_progress") else "pending"


def read(status: ProjectStatus, base: Path) -> List[dict]:
    """Fill status from base (the .gsd folder); return extra attention items."""
    state_text = _text(base / "STATE.md")
    data = _from_db(base / "gsd.db") or _from_markdown(base) or _from_registry(state_text) or {
        "milestones": [], "slices": [], "tasks": [], "assessments": [], "evidence": []}

    status.phases = list(STEPS)
    title = re.search(r"^#\s+(.+?)\s*$", _text(base / "PROJECT.md"), re.MULTILINE)
    status.project = title.group(1) if title and title.group(1).lower() != "project" else None
    status.vision = (_section_paragraph(base / "PROJECT.md", "Core Value")
                     or _section_paragraph(base / "PROJECT.md", "What This Is"))
    status.intent = _section_paragraph(base / "STATE.md", "Next Action")
    try:
        nxt = json.loads(_text(base / "state.json") or "{}").get("next") or {}
        status.next_skill = nxt.get("command") if isinstance(nxt.get("command"), str) else None
    except (ValueError, AttributeError):
        status.next_skill = None

    raw_phase = (_field(state_text, "Phase") or "").lower() or None
    status.status = raw_phase
    active = re.match(ID_RE, _field(state_text, "Active Milestone") or "")
    milestones = data["milestones"]
    ids = [m["id"] for m in milestones]
    current = (active.group(1) if active and active.group(1) in ids else None) \
        or next((m["id"] for m in milestones if (m["status"] or "").lower() in ("active", "in_progress")), None) \
        or next((m["id"] for m in milestones if (m["status"] or "").lower() not in CLOSED), None)
    for m in milestones:
        closed = (m["status"] or "").lower() in CLOSED
        status.roadmap_milestones.append({
            "number": m["id"], "slug": m["title"] or m["id"],
            "status": "shipped" if closed else "active" if m["id"] == current else "planned",
            "goal": m.get("vision") or None, "archive": None})
        if m["id"] == current:
            status.milestone = m["title"] or m["id"]
    if current is None and status.roadmap_milestones:
        # Nothing open: the card's milestone is the last one shipped.
        status.milestone = status.roadmap_milestones[-1]["slug"]

    slices = [s for s in data["slices"] if s["milestone_id"] == current]
    index = {s["id"]: wave for wave, s in enumerate(slices, 1)}
    for wave, s in enumerate(slices, 1):
        status.waves[wave] = f"{s['id']} {s['title']}".strip()
    for task in data["tasks"]:
        if task["milestone_id"] != current or task["slice_id"] not in index:
            continue
        try:
            files = json.loads(task.get("files") or "[]")
        except ValueError:
            files = []
        status.tasks.append(TaskSummary(
            id=f"{task['slice_id']}-{task['id']}", title=task["title"] or None, wave=index[task["slice_id"]],
            status=_task_status(task["status"]),
            files=[str(f) for f in files] if isinstance(files, list) else []))
    status.tasks_total = len(status.tasks)
    status.tasks_done = sum(1 for task in status.tasks if task.status == "done")
    active_slice = re.match(r"(S\d+)", _field(state_text, "Active Slice") or "")
    status.current_wave = index.get(active_slice.group(1)) if active_slice else None
    if status.current_wave is None:
        status.current_wave = next((index[s["id"]] for s in slices if (s["status"] or "").lower() not in CLOSED), None)

    if raw_phase in STEP_OF:
        status.phase = STEP_OF[raw_phase]
    elif current is not None:
        # No STATE.md phase: derive it from the open slice's tasks.
        open_tasks = [t for t in status.tasks if t.wave == status.current_wave]
        status.phase = ("verify" if slices and status.current_wave is None else
                        "plan" if not open_tasks else
                        "execute" if any(t.status != "done" for t in open_tasks) else "verify")

    status.reviews = [{"file": a["path"], "kind": a["scope"] or "assessment", "verdict": a["status"] or None,
                       "cycle": None, "depth": None, "note": None}
                      for a in data["assessments"] if a["milestone_id"] == current]
    status.ledger = [{"command": e["command"], "commit": None, "result": e["verdict"], "recorded_at": e["created_at"]}
                     for e in data["evidence"] if e["milestone_id"] == current][:20]

    extra = [{"kind": "blocked", "label": item, "ref": "STATE.md"}
             for item in re.findall(r"^\s*-\s+(\S.*?)\s*$", _section(state_text, "Blockers"), re.MULTILINE)
             if item.strip("*_ .").lower() not in ("none", "none yet")]

    all_closed = bool(milestones) and all((m["status"] or "").lower() in CLOSED for m in milestones)
    if raw_phase == "complete" or all_closed:
        status.workflow = {"state": "shipped", "label": "Shipped"}
    elif raw_phase == "blocked":
        status.workflow = {"state": "blocked", "label": "Blocked", "reason": "STATE.md phase is blocked."}
    elif raw_phase == "paused":
        status.workflow = {"state": "idle", "label": "Paused", "reason": "gsd-pi is paused."}
    elif current is None:
        status.workflow = {"state": "idle", "label": "Not started", "reason": "No milestone is recorded yet."}
    else:
        status.workflow = {"state": "active", "label": f"In {status.phase or 'progress'}"}
    return extra


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""
