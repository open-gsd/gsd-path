from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

from . import gitinfo
from .history import resolve_history_path
from .model import ProjectStatus, TaskSummary

PIPELINE_MARKER = "gsd-path/v2"

FRONTMATTER_RE = re.compile(r"^([a-z_]+):\s*([^#]*?)(?:\s+#.*)?$")
WAVE_HEADING_RE = re.compile(r"^## Wave (?P<wave>\d+) — (?P<name>.+?)\s*$", re.MULTILINE)
ROADMAP_HEADING_RE = re.compile(r"^### (M\d{3,}) — ([a-z0-9][a-z0-9-]*)\s*$", re.MULTILINE)
ROADMAP_STATUS_RE = re.compile(r"^Status:\s*([a-z]+)", re.MULTILINE)
ROADMAP_ARCHIVE_RE = re.compile(r"^Archive:\s*(\S+)", re.MULTILINE)
ROADMAP_GOAL_RE = re.compile(r"^Goal:\s*(.+?)\s*$", re.MULTILINE)
ROADMAP_DEPENDS_RE = re.compile(r"^Depends on:\s*\[([^\]]*)\]", re.MULTILINE)
ROADMAP_INTEGRATED_RE = re.compile(r"^Integrated:\s*([0-9a-f]{7,40})", re.MULTILINE)
MANIFEST_SHIPPED_RE = re.compile(r"^Shipped:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
MANIFEST_VERDICT_RE = re.compile(r"^Final verdict:\s*(.+?)\s*$", re.MULTILINE)
MANIFEST_COUNTS_RE = re.compile(r"^Waves:\s*(\d+)\s+Tasks:\s*(\d+)\s+done\s*/\s*(\d+)\s+total(?:\s+Review cycles used:\s*([\d/]+))?", re.MULTILINE)
MANIFEST_CARRIED_RE = re.compile(r"^Carried forward:\s*(\d+)", re.MULTILINE)
SECTION_RE_TEMPLATE = r"^##\s+{heading}\s*$\n(.*?)(?=^##\s|\Z)"
TASK_FILE_RE = re.compile(r"^(T\d{3,})-[a-z0-9][a-z0-9-]*\.md$")
BLOCK_LIST_ITEM_RE = re.compile(r"^\s*-\s+(\S.*?)\s*$")
RUNTIME_STATUS_SCHEMA = "gsd-path/status/v1"

REVIEW_VERDICT_RE = re.compile(r"^(?:Wave|Overall|Gap)\s+verdict:\s*([A-Za-z-]+)",
                               re.IGNORECASE | re.MULTILINE)
REVIEW_CYCLE_RE = re.compile(r"^Cycle:\s*(\d+)", re.MULTILINE)
REVIEW_DEPTH_RE = re.compile(r"^Depth:\s*([A-Za-z-]+)", re.MULTILINE)
WAVE_REVIEW_FILE_RE = re.compile(r"^wave-\d+\.cycle\d+(?:\.[a-z]+)?\.md$")
GAP_REVIEW_FILE_RE = re.compile(r"^final-gap-\d+\.md$")
CRITERION_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
CRITERION_ID_RE = re.compile(r"^(SC\d+)\s*—\s*(.*)$")
CRITERION_VERDICT_RE = re.compile(r"^-\s+\*\*Verdict\*\*:\s*([A-Za-z-]+)", re.MULTILINE)
ANSWER_HEADING_RE = re.compile(r"^## Answer (A\d+)\b")
DISPOSITION_HEADING_RE = re.compile(r"^## Disposition X\d+\b")
ANSWER_FIELD_RE = re.compile(r"^-\s+\*\*([^*]+)\*\*:\s*(.*)$")
STATE_LOG_RE = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2})\s+—\s+([a-z]+)\s+—")
META_LINE_RE = re.compile(r"^(?:\*\*)?[A-Za-z][A-Za-z /()-]*(?:\*\*)?\s*:")

STALE_AFTER_S = 12 * 3600
NEGATIVE_REVIEW_VERDICTS = {"blocked", "fail", "failed", "not-met", "unverifiable"}
NEGATIVE_CRITERION_VERDICTS = {"not-met", "unverifiable"}

STATE_KEYS = (
    "pipeline",
    "project",
    "milestone",
    "phase",
    "status",
    "branch",
    "archive",
    "integration_default",
    "integration",
    "integration_source",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_frontmatter(text: str) -> Dict[str, object]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: Dict[str, object] = {}
    index = 1
    while index < len(lines) and lines[index].strip() != "---":
        line = lines[index]
        match = FRONTMATTER_RE.match(line)
        if not match:
            index += 1
            continue
        key, raw = match.group(1), match.group(2).strip()
        if raw:
            fields[key] = _scalar(raw)
            index += 1
            continue
        items: List[str] = []
        cursor = index + 1
        while cursor < len(lines):
            item = BLOCK_LIST_ITEM_RE.match(lines[cursor])
            if not item or lines[cursor].strip() == "---":
                break
            items.append(item.group(1))
            cursor += 1
        if items:
            fields[key] = items
            index = cursor
        else:
            fields[key] = None
            index += 1
    return fields


def _scalar(raw: str) -> object:
    if raw == "null":
        return None
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [part.strip() for part in inner.split(",") if part.strip()]
    return raw


def parse_state_file(path: Union[str, Path]) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    fields = parse_frontmatter(text)
    return {key: fields.get(key) for key in STATE_KEYS if key in fields}


def is_project_root(root: Union[str, Path]) -> bool:
    state = parse_state_file(Path(root) / ".project" / "STATE.md")
    return state.get("pipeline") == PIPELINE_MARKER


def parse_task_file(path: Union[str, Path]) -> Optional[TaskSummary]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    fields = parse_frontmatter(text)
    task_id = fields.get("id")
    if not isinstance(task_id, str):
        name_match = TASK_FILE_RE.match(Path(path).name)
        task_id = name_match.group(1) if name_match else None
    if task_id is None:
        return None
    wave = fields.get("wave")
    try:
        wave = int(wave) if wave is not None else None
    except (TypeError, ValueError):
        wave = None
    files = fields.get("files")
    return TaskSummary(
        id=task_id,
        title=fields.get("title") if isinstance(fields.get("title"), str) else None,
        wave=wave,
        status=fields.get("status") if isinstance(fields.get("status"), str) else None,
        files=[str(item) for item in files] if isinstance(files, list) else [],
    )


def parse_plan(path: Union[str, Path]) -> Dict[int, str]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    return {int(match.group("wave")): match.group("name") for match in WAVE_HEADING_RE.finditer(text)}


def parse_roadmap(path: Union[str, Path]) -> List[dict]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    milestones = []
    matches = list(ROADMAP_HEADING_RE.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end():end]
        status_match = ROADMAP_STATUS_RE.search(block)
        archive_match = ROADMAP_ARCHIVE_RE.search(block)
        archive = archive_match.group(1) if archive_match else None
        goal_match = ROADMAP_GOAL_RE.search(block)
        depends_match = ROADMAP_DEPENDS_RE.search(block)
        integrated_match = ROADMAP_INTEGRATED_RE.search(block)
        milestones.append({
            "number": match.group(1),
            "slug": match.group(2),
            "status": status_match.group(1) if status_match else None,
            "archive": None if archive in (None, "null") else archive,
            "goal": goal_match.group(1)[:400] if goal_match else None,
            "depends": [d.strip() for d in depends_match.group(1).split(",") if d.strip()] if depends_match else [],
            "integrated": integrated_match.group(1) if integrated_match else None,
            "manifest": None,
            "duration_s": None,
            "tokens": None,
        })
    return milestones


def parse_manifest(path: Union[str, Path]) -> Optional[dict]:
    """Ship summary of an archived milestone from its MANIFEST.md."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    shipped = MANIFEST_SHIPPED_RE.search(text)
    verdict = MANIFEST_VERDICT_RE.search(text)
    counts = MANIFEST_COUNTS_RE.search(text)
    carried = MANIFEST_CARRIED_RE.search(text)
    cycles = [int(c) for c in counts.group(4).split("/") if c] if counts and counts.group(4) else []
    return {
        "shipped": shipped.group(1) if shipped else None,
        "verdict": verdict.group(1)[:200] if verdict else None,
        "waves": int(counts.group(1)) if counts else None,
        "tasks_done": int(counts.group(2)) if counts else None,
        "tasks_total": int(counts.group(3)) if counts else None,
        "cycles_avg": round(sum(cycles) / len(cycles), 1) if cycles else None,
        "carried": int(carried.group(1)) if carried else 0,
    }


def parse_phase_log(state_path: Union[str, Path]) -> List[dict]:
    """Phases of the current milestone from the STATE.md log.

    Each phase once, in the order it was first entered; the current phase
    carries the date it was last entered. The log persists across milestones,
    so only the tail from the latest milestone start (its define, or the
    inspect right before it) is read.
    """
    try:
        text = Path(state_path).read_text(encoding="utf-8")
    except OSError:
        return []
    log = []
    for line in text.splitlines():
        match = STATE_LOG_RE.match(line.strip())
        if not match:
            continue
        date, phase = match.group(1), match.group(2)
        if not log or log[-1]["phase"] != phase:
            log.append({"phase": phase, "date": date})
    start = max((i for i, entry in enumerate(log) if entry["phase"] == "define"), default=0)
    if start > 0 and log[start - 1]["phase"] == "inspect":
        start -= 1
    # Ship can send a milestone back through plan and build; keep each phase
    # once, in first-seen order, and date the current phase by its latest entry.
    seen: Dict[str, dict] = {}
    for entry in log[start:]:
        seen.setdefault(entry["phase"], dict(entry))
    if log:
        seen[log[-1]["phase"]]["date"] = log[-1]["date"]
    return list(seen.values())


def _section_paragraph(path: Union[str, Path], heading: str, limit: int = 400) -> Optional[str]:
    """First paragraph under a '## heading' section, or None."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(SECTION_RE_TEMPLATE.format(heading=re.escape(heading)), text,
                      re.MULTILINE | re.DOTALL)
    if not match:
        return None
    for paragraph in re.split(r"\n\s*\n", match.group(1).strip()):
        joined = " ".join(line.strip() for line in paragraph.splitlines()).strip()
        if joined:
            return joined[:limit]
    return None


def parse_latest_lesson(path: Union[str, Path], limit: int = 300) -> Optional[str]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        item = BLOCK_LIST_ITEM_RE.match(line)
        if item:
            return item.group(1)[:limit]
    return None


def _natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def _review_kind(name: str) -> str:
    if WAVE_REVIEW_FILE_RE.match(name):
        return "wave"
    if name == "FINAL.md":
        return "final"
    if GAP_REVIEW_FILE_RE.match(name):
        return "gap"
    if name == "PATCH-FINDINGS.md":
        return "patch-findings"
    return "other"


def _first_note(text: str) -> Optional[str]:
    in_comment = False
    for line in text.splitlines():
        stripped = line.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue
        stripped = re.sub(r"^[-*]\s+", "", stripped).strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped[0] in "✅❌⚠⛔":
            continue
        if META_LINE_RE.match(stripped):
            continue
        return stripped[:200]
    return None


def parse_reviews(review_dir: Union[str, Path]) -> List[dict]:
    review_dir = Path(review_dir)
    try:
        entries = sorted(review_dir.iterdir(), key=lambda entry: _natural_key(entry.name))
    except OSError:
        return []
    reviews = []
    for entry in entries:
        if not entry.is_file() or not entry.name.endswith(".md"):
            continue
        try:
            text = entry.read_text(encoding="utf-8")
        except OSError:
            continue
        verdict = REVIEW_VERDICT_RE.search(text)
        cycle = REVIEW_CYCLE_RE.search(text)
        depth = REVIEW_DEPTH_RE.search(text)
        reviews.append({
            "file": entry.name,
            "kind": _review_kind(entry.name),
            "verdict": verdict.group(1).lower() if verdict else None,
            "cycle": int(cycle.group(1)) if cycle else None,
            "depth": depth.group(1).lower() if depth else None,
            "note": _first_note(text),
        })
    return reviews


def parse_final_criteria(final_path: Union[str, Path]) -> Optional[List[dict]]:
    try:
        text = Path(final_path).read_text(encoding="utf-8")
    except OSError:
        return None
    criteria = []
    matches = list(CRITERION_HEADING_RE.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end():end]
        verdict = CRITERION_VERDICT_RE.search(block)
        heading = match.group(1)
        id_match = CRITERION_ID_RE.match(heading)
        if id_match:
            criterion_id, criterion_text = id_match.group(1), id_match.group(2).strip()
        else:
            criterion_id, criterion_text = None, heading
        criteria.append({
            "id": criterion_id,
            "text": criterion_text[:200],
            "verdict": verdict.group(1).lower() if verdict else None,
        })
    return criteria


def parse_verify_ledger(path: Union[str, Path], limit: int = 20) -> List[dict]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        entries.append({
            "command": record.get("command"),
            "commit": record.get("commit"),
            "result": record.get("result"),
            "recorded_at": record.get("recorded_at"),
        })
    return list(reversed(entries[-limit:]))


def _answer_fields(body: List[str]) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for line in body:
        match = ANSWER_FIELD_RE.match(line.strip())
        if match:
            fields[match.group(1).strip().lower()] = match.group(2).strip()
    return fields


def parse_pending_answers(path: Union[str, Path]) -> List[dict]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    sections = []  # (kind, answer_id, body_lines)
    current = None
    for line in lines:
        answer_match = ANSWER_HEADING_RE.match(line)
        if answer_match:
            current = ("answer", answer_match.group(1), [])
            sections.append(current)
            continue
        if DISPOSITION_HEADING_RE.match(line):
            current = ("disposition", None, [])
            sections.append(current)
            continue
        if line.startswith("## "):
            current = None
            continue
        if current is not None:
            current[2].append(line)
    disposed = set()
    answers = []
    for kind, answer_id, body in sections:
        fields = _answer_fields(body)
        if kind == "disposition":
            target = fields.get("answer")
            if target:
                disposed.add(target)
            continue
        answers.append((answer_id, fields))
    pending = []
    for answer_id, fields in answers:
        if fields.get("follow-up") != "required":
            continue
        if fields.get("status") not in ("final", "NEEDS-USER"):
            continue
        if answer_id in disposed:
            continue
        question = fields.get("question")
        pending.append({
            "id": answer_id,
            "question": question[:200] if question else None,
            "owner": fields.get("next owner"),
            "status": fields.get("status"),
            "thread": fields.get("thread"),
            "target": fields.get("target artifact"),
        })
    return pending


def _collect_answers(answers_path: Union[str, Path],
                     runtime_pending: Optional[List[dict]]) -> List[dict]:
    direct = parse_pending_answers(answers_path)
    if runtime_pending is None:
        return direct
    by_id = {item["id"]: item for item in direct}
    merged = []
    for record in runtime_pending:
        if not isinstance(record, dict):
            continue
        answer_id = record.get("answer") or record.get("id")
        base = by_id.get(answer_id, {})
        merged.append({
            "id": answer_id,
            "question": base.get("question") or (record.get("question") or None),
            "owner": record.get("owner") or base.get("owner"),
            "status": record.get("status") or base.get("status"),
            "thread": base.get("thread"),
            "target": record.get("target") or base.get("target"),
        })
    return merged


def _num(value) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def parse_usage(path: Union[str, Path]) -> Optional[dict]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    entries = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            entries.append(record)
    tokens_in = sum(_num(entry.get("tokens_in")) for entry in entries)
    tokens_out = sum(_num(entry.get("tokens_out")) for entry in entries)
    cost = sum(_num(entry.get("cost")) for entry in entries)
    total = tokens_in + tokens_out

    models: Dict[tuple, float] = {}
    phases: Dict[str, float] = {}
    tasks: Dict[str, dict] = {}
    for entry in entries:
        tokens = _num(entry.get("tokens_in")) + _num(entry.get("tokens_out"))
        model = entry.get("model") if isinstance(entry.get("model"), str) else None
        family = entry.get("family") if isinstance(entry.get("family"), str) else None
        models[(model or "unknown", family)] = models.get((model or "unknown", family), 0.0) + tokens
        phase = entry.get("phase") if isinstance(entry.get("phase"), str) else None
        phases[phase or "unknown"] = phases.get(phase or "unknown", 0.0) + tokens
        task = entry.get("task") if isinstance(entry.get("task"), str) else None
        task_key = task or "unknown"
        slot = tasks.setdefault(task_key, {"task": task_key, "model": model, "tokens": 0.0})
        slot["tokens"] += tokens
        if model and not slot["model"]:
            slot["model"] = model

    return {
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "cost": round(cost, 2),
        "models": [
            {"model": model, "family": family,
             "share": round(tokens / total, 4) if total else 0.0}
            for (model, family), tokens in sorted(models.items(), key=lambda item: -item[1])
        ],
        "by_phase": [
            {"phase": phase, "tokens": int(tokens)}
            for phase, tokens in sorted(phases.items(), key=lambda item: -item[1])
        ],
        "by_task": [
            {"task": slot["task"], "model": slot["model"], "tokens": int(slot["tokens"])}
            for slot in sorted(tasks.values(), key=lambda item: -item["tokens"])[:10]
        ],
    }


def _parse_iso(value) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def time_in_phase_seconds(root: Union[str, Path], phase: Optional[str],
                          state_path: Union[str, Path],
                          now: Optional[datetime] = None) -> Optional[int]:
    if not phase:
        return None
    now = now or datetime.now(timezone.utc)
    root_abs = os.path.abspath(str(root))
    try:
        lines = resolve_history_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "phase-changed":
            continue
        event_root = event.get("root")
        if not isinstance(event_root, str):
            continue
        if os.path.abspath(os.path.expanduser(event_root)) != root_abs:
            continue
        at = _parse_iso(event.get("at"))
        if at is not None:
            return max(0, int((now - at).total_seconds()))
    try:
        text = Path(state_path).read_text(encoding="utf-8")
    except OSError:
        return None
    found = None
    for line in text.splitlines():
        match = STATE_LOG_RE.match(line.strip())
        if match and match.group(2) == phase:
            found = match.group(1)
    if found is None:
        return None
    try:
        since = datetime.fromisoformat(found).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0, int((now - since).total_seconds()))


def tree_mtime(path: Union[str, Path]) -> Optional[float]:
    try:
        latest = os.stat(path).st_mtime
    except OSError:
        return None
    for dirpath, dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                latest = max(latest, os.stat(os.path.join(dirpath, name)).st_mtime)
            except OSError:
                continue
    return latest


def _runtime_status(root: str) -> Optional[dict]:
    runtime = Path(root) / ".gsd-path" / "runtime" / "pipeline_state.py"
    if not runtime.is_file():
        return None
    try:
        result = subprocess.run(
            ["python3", "-B", str(runtime), "status", "--repo", root],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("schema") != RUNTIME_STATUS_SCHEMA:
        return None
    return payload


def _activity_time(status: ProjectStatus) -> Optional[datetime]:
    parsed = _parse_iso(status.last_activity_iso)
    if parsed is not None:
        return parsed
    if status.state_mtime is not None:
        return datetime.fromtimestamp(status.state_mtime, tz=timezone.utc)
    return None


def _human_age(seconds: float) -> str:
    days = int(seconds // 86400)
    if days >= 1:
        return f"{days}d"
    return f"{max(0, int(seconds // 3600))}h"


def compute_attention(status: ProjectStatus,
                      now: Optional[datetime] = None) -> List[dict]:
    items: List[dict] = []
    questions = status.answers or status.pending_answers
    for pending in questions:
        if not isinstance(pending, dict):
            continue
        label = pending.get("question") or pending.get("id") or pending.get("answer") or "pending question"
        items.append({"kind": "question", "label": label, "ref": pending.get("id") or pending.get("answer")})
    for task in status.tasks:
        if task.status and "blocked" in task.status.lower():
            label = f"{task.id} — {task.title}" if task.title else str(task.id)
            items.append({"kind": "blocked", "label": label, "ref": task.id})
    for review in status.reviews:
        verdict = review.get("verdict")
        if isinstance(verdict, str) and verdict.lower() in NEGATIVE_REVIEW_VERDICTS:
            name = review.get("file") or "review"
            items.append({"kind": "failed",
                          "label": f"{name} — {verdict.lower()}",
                          "ref": review.get("file")})
    for criterion in status.criteria or []:
        verdict = criterion.get("verdict")
        if isinstance(verdict, str) and verdict.lower() in NEGATIVE_CRITERION_VERDICTS:
            ref = criterion.get("id")
            text = criterion.get("text") or "criterion"
            label = f"{ref} — {text}" if ref else text
            items.append({"kind": "failed", "label": label, "ref": ref})
    shipped = (status.status or "").lower() in ("shipped", "archived") or bool(status.archive)
    active_work = status.tasks_total > status.tasks_done
    activity = _activity_time(status)
    if not shipped and active_work and activity is not None:
        now = now or datetime.now(timezone.utc)
        age = (now - activity).total_seconds()
        if age > STALE_AFTER_S:
            items.append({"kind": "stale",
                          "label": f"no activity for {_human_age(age)}",
                          "ref": None})
    return items


def health_for(attention: List[dict]) -> str:
    kinds = {item.get("kind") for item in attention}
    if kinds & {"blocked", "failed"}:
        return "red"
    if kinds & {"question", "stale"}:
        return "amber"
    return "green"


def probe_project(root: Union[str, Path], enrich: bool = True) -> ProjectStatus:
    root = os.path.abspath(str(root))
    project_dir = Path(root) / ".project"
    state_path = project_dir / "STATE.md"
    state = parse_state_file(state_path)

    tasks = []
    tasks_dir = project_dir / "tasks"
    if tasks_dir.is_dir():
        for entry in sorted(tasks_dir.iterdir()):
            if entry.is_file() and TASK_FILE_RE.match(entry.name):
                task = parse_task_file(entry)
                if task is not None:
                    tasks.append(task)
    tasks_done = sum(1 for task in tasks if task.status == "done")
    unfinished_waves = sorted({task.wave for task in tasks if task.status != "done" and task.wave is not None})

    next_milestone = None
    next_state_path = project_dir / "next" / "STATE.md"
    if next_state_path.is_file():
        next_state = parse_state_file(next_state_path)
        if next_state:
            next_milestone = {
                "milestone": next_state.get("milestone"),
                "phase": next_state.get("phase"),
                "status": next_state.get("status"),
            }

    roadmap = parse_roadmap(project_dir / "ROADMAP.md")
    for milestone in roadmap:
        if milestone["archive"]:
            milestone["manifest"] = parse_manifest(Path(root) / milestone["archive"] / "MANIFEST.md")

    status = ProjectStatus(
        root=root,
        project=state.get("project"),
        milestone=state.get("milestone"),
        phase=state.get("phase"),
        status=state.get("status"),
        branch=state.get("branch"),
        archive=state.get("archive"),
        integration=state.get("integration"),
        tasks=tasks,
        tasks_done=tasks_done,
        tasks_total=len(tasks),
        current_wave=unfinished_waves[0] if unfinished_waves else None,
        waves=parse_plan(project_dir / "plan" / "PLAN.md"),
        roadmap_milestones=roadmap,
        next_milestone=next_milestone,
        phase_log=parse_phase_log(state_path),
        vision=_section_paragraph(project_dir / "CHARTER.md", "Vision"),
        intent=_section_paragraph(project_dir / "intent" / "INTENT.md", "Summary"),
        lesson=parse_latest_lesson(project_dir / "LESSONS.md"),
        git=gitinfo.git_branch_head_dirty(root),
        status_source="parse-only",
        state_mtime=tree_mtime(state_path),
        last_activity_iso=_iso(tree_mtime(project_dir)),
        reviews=parse_reviews(project_dir / "review"),
        criteria=parse_final_criteria(project_dir / "review" / "FINAL.md"),
        ledger=parse_verify_ledger(project_dir / "build" / "verify-ledger.jsonl"),
        usage=parse_usage(project_dir / "build" / "usage.jsonl"),
        time_in_phase_s=time_in_phase_seconds(root, state.get("phase"), state_path),
    )

    runtime_pending: Optional[List[dict]] = None
    if enrich:
        payload = _runtime_status(root)
        if payload is not None:
            pending = payload.get("pending_answers")
            status.pending_answers = pending if isinstance(pending, list) else []
            runtime_pending = status.pending_answers
            next_skill = payload.get("next_skill")
            status.next_skill = next_skill if isinstance(next_skill, str) else None
            runtime_git = payload.get("git")
            if isinstance(runtime_git, dict):
                status.git = runtime_git
            status.status_source = "runtime"
    status.answers = _collect_answers(project_dir / "discuss" / "ANSWERS.md", runtime_pending)
    status.attention = compute_attention(status)
    status.health = health_for(status.attention)
    return status


def _iso(mtime: Optional[float]) -> Optional[str]:
    if mtime is None:
        return None
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
