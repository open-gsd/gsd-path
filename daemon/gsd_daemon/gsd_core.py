"""Read a gsd-core project (.planning/) into the card fields GSD Path cards use.

gsd-core decides completion from files on disk, and so does this reader: a
plan is done when its SUMMARY exists, a phase is done when its VERIFICATION
says `status: passed`. ROADMAP checkboxes are notes for people and are not read.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .model import ProjectStatus, TaskSummary
from .probe import _natural_key, _section_paragraph, parse_frontmatter

# The steps of one gsd-core phase, in order. The card's phase strip shows them.
STEPS = ["discuss", "research", "plan", "execute", "verify"]

PHASE_DIR_RE = re.compile(r"^(\d+(?:\.\d+)*)-(.+)$")
PLAN_FILE_RE = re.compile(r"^(\d+(?:\.\d+)*)-(\d+)-PLAN\.md$")
ROADMAP_PHASE_RE = re.compile(r"^###\s+Phase\s+(\d+(?:\.\d+)*):\s*(.+?)\s*$", re.MULTILINE)
ROADMAP_PLAN_RE = re.compile(r"^\s*-\s+\[[ xX]\]\s+(\d+(?:\.\d+)*-\d+)-PLAN\.md\s*[—-]+\s*(.+?)\s*$", re.MULTILINE)
MILESTONE_HEADING_RE = re.compile(r"^##\s+(v[\w.]+)\s+(.+?)\s*\((Shipped|Planned)[^)]*\)\s*$", re.MULTILINE)
GOAL_RE = re.compile(r"^\*\*Goal:\*\*\s*(.+?)\s*$", re.MULTILINE)
SECTION_RE = r"^###?\s+{heading}[^\n]*\n(.*?)(?=^##|\Z)"
LIST_ITEM_RE = re.compile(r"^\s*-\s+(\S.*?)\s*$", re.MULTILINE)
# VERIFICATION statuses mapped onto the review verdicts the attention rules know.
VERDICTS = {"passed": "pass", "gaps_found": "failed"}


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _value(fields: dict, key: str) -> Optional[str]:
    value = fields.get(key)
    return str(value).strip().strip('"\'') or None if value is not None else None


def _status_of(path: Path) -> Optional[str]:
    return _value(parse_frontmatter(_text(path)), "status")


def _section_items(text: str, heading: str) -> List[str]:
    match = re.search(SECTION_RE.format(heading=re.escape(heading)), text, re.MULTILINE | re.DOTALL)
    items = LIST_ITEM_RE.findall(match.group(1)) if match else []
    return [item for item in items if item.strip("*_ .").lower() not in ("none", "none yet")]


def _phase_dirs(base: Path) -> List[Tuple[str, str, Path]]:
    """(number, slug, folder) for the current milestone; shipped phases move to milestones/."""
    try:
        entries = sorted((p for p in (base / "phases").iterdir() if p.is_dir()), key=lambda p: _natural_key(p.name))
    except OSError:
        return []
    found = []
    for entry in entries:
        match = PHASE_DIR_RE.match(entry.name)
        if match:
            found.append((match.group(1), match.group(2), entry))
    return found


def _same_phase(a: Optional[str], b: str) -> bool:
    try:
        return a is not None and float(a) == float(b)
    except ValueError:
        return a == b


def _step(folder: Path, plans: List[TaskSummary], verdict: Optional[str]) -> Optional[str]:
    """The step a phase is in; None when its VERIFICATION passed."""
    if verdict == "pass":
        return None
    if plans:
        return "verify" if all(plan.status == "done" for plan in plans) else "execute"
    names = {entry.name for entry in folder.iterdir()} if folder.is_dir() else set()
    if any(name.endswith("-RESEARCH.md") for name in names):
        return "plan"
    if any(name.endswith("-CONTEXT.md") for name in names):
        return "research"
    return "discuss"


def _milestones(base: Path, current: Optional[str], name: Optional[str], goal: Optional[str]) -> List[dict]:
    """Oldest first, as the GSD Path roadmap lists them."""
    found = []
    for match in MILESTONE_HEADING_RE.finditer(_text(base / "MILESTONES.md")):
        number, title, kind = match.group(1), match.group(2).strip(), match.group(3)
        rest = match.string[match.end():]
        nxt = MILESTONE_HEADING_RE.search(rest)
        block = rest[:nxt.start()] if nxt else rest
        goal_match = GOAL_RE.search(block)
        archive = base / "milestones" / f"{number}-ROADMAP.md"
        found.append({
            "number": number, "slug": title,
            "status": "active" if number == current else "shipped" if kind == "Shipped" else "planned",
            "goal": goal_match.group(1) if goal_match else None,
            "archive": str(archive.relative_to(base.parent)) if archive.is_file() else None,
        })
    found.reverse()
    if current and not any(m["number"] == current for m in found):
        found.append({"number": current, "slug": name or current, "status": "active", "goal": goal, "archive": None})
    return found


def read(status: ProjectStatus, base: Path) -> List[dict]:
    """Fill status from base (the .planning folder); return extra attention items."""
    state_text = _text(base / "STATE.md")
    state = parse_frontmatter(state_text)
    roadmap = _text(base / "ROADMAP.md")
    phase_names = {number: name for number, name in ROADMAP_PHASE_RE.findall(roadmap)}
    plan_titles = dict(ROADMAP_PLAN_RE.findall(roadmap))

    status.phases = list(STEPS)
    title = re.search(r"^#\s+(.+?)\s*$", _text(base / "PROJECT.md"), re.MULTILINE)
    status.project = title.group(1) if title else None
    version, name = _value(state, "milestone"), _value(state, "milestone_name")
    if (version or "").lower() == "none":  # between milestones: the last one shipped
        version = name = None
    status.milestone = name or version
    status.status = _value(state, "status")
    status.vision = (_section_paragraph(base / "PROJECT.md", "Core Value")
                     or _section_paragraph(base / "PROJECT.md", "What This Is"))
    status.intent = _value(state, "last_activity_desc")

    current = _value(state, "current_phase")
    extra: List[dict] = []
    steps: Dict[int, Optional[str]] = {}
    folders = _phase_dirs(base)
    top = max((_natural_key(number) for number, _, _ in folders), default=None)
    # gsd-core makes a phase folder on first discuss/plan; later ROADMAP phases wait at discuss.
    planned = [(number, name, None) for number, name in phase_names.items()
               if folders and not any(_same_phase(number, n) for n, _, _ in folders)
               and (_natural_key(number) > top or _same_phase(current, number))]
    phases = sorted(folders + planned, key=lambda phase: _natural_key(phase[0]))
    for wave, (number, slug, folder) in enumerate(phases, 1):
        status.waves[wave] = f"{number} {phase_names.get(number.lstrip('0') or '0', slug)}"
        if folder is None:
            steps[wave] = "discuss"
            if _same_phase(current, number):
                status.current_wave = wave
            continue
        plans = []
        for entry in sorted(folder.iterdir(), key=lambda p: _natural_key(p.name)):
            match = PLAN_FILE_RE.match(entry.name)
            if not match:
                continue
            plan_id = f"{match.group(1)}-{match.group(2)}"
            files = parse_frontmatter(_text(entry)).get("files_modified")
            plans.append(TaskSummary(
                id=plan_id, title=plan_titles.get(plan_id), wave=wave,
                status="done" if (folder / f"{plan_id}-SUMMARY.md").is_file() else "pending",
                files=files if isinstance(files, list) else []))
        status.tasks.extend(plans)
        verdict = None
        for kind, suffix in (("verification", "VERIFICATION"), ("uat", "UAT")):
            path = folder / f"{number}-{suffix}.md"
            if not path.is_file():
                continue
            raw = _status_of(path)
            value = VERDICTS.get(raw, raw) if kind == "verification" else raw
            if kind == "verification":
                verdict = value
            status.reviews.append({"file": str(path.relative_to(base.parent)), "kind": kind,
                                   "verdict": value, "cycle": None, "depth": None, "note": None})
            if value == "human_needed":
                extra.append({"kind": "question", "label": f"Phase {number} needs a human check", "ref": path.name})
        steps[wave] = _step(folder, plans, verdict)
        if _same_phase(current, number):
            status.current_wave = wave
    if status.current_wave is None:
        status.current_wave = next((wave for wave, step in steps.items() if step), None)
    status.phase = steps.get(status.current_wave) if status.current_wave else None
    status.tasks_total = len(status.tasks)
    status.tasks_done = sum(1 for task in status.tasks if task.status == "done")

    goal = None
    if current:
        match = re.search(rf"^###\s+Phase\s+{re.escape(current)}:.*?$\n(.*?)(?=^###\s|\Z)", roadmap, re.MULTILINE | re.DOTALL)
        goal_match = GOAL_RE.search(match.group(1)) if match else None
        goal = goal_match.group(1) if goal_match else None
    status.roadmap_milestones = _milestones(base, version, name, goal)

    for blocker in _section_items(state_text, "Blockers"):
        extra.append({"kind": "blocked", "label": blocker, "ref": "STATE.md"})

    if (status.status or "").lower() == "milestone_complete":
        status.workflow = {"state": "shipped", "label": "Shipped"}
    elif (status.status or "").lower() == "blocked":
        status.workflow = {"state": "blocked", "label": "Blocked", "reason": "STATE.md status is blocked."}
    elif not steps:
        status.workflow = {"state": "idle", "label": "Not started", "reason": "No phase folder exists yet."}
    elif all(step is None for step in steps.values()):
        status.workflow = {"state": "shipped", "label": "Shipped"}
    else:
        status.workflow = {"state": "active", "label": f"In {status.phase or 'progress'}"}
    return extra
