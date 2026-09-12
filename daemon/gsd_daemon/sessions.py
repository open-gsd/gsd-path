"""Usage from host session logs, matched to watched projects by cwd.

Sources:
- Codex rollout JSONL (``~/.codex/sessions`` and Orca's per-account homes):
  ``session_meta``/``turn_context`` give cwd and model, ``token_usage_record``
  gives one usage record per model response, ``task_started`` gives timing.
- Claude Code transcripts (``~/.claude/projects/*/*.jsonl``): each assistant
  record carries ``message.model`` and ``message.usage``.

Cost is tokens × a per-model price table (USD per million tokens) from the
daemon config. A model without a price contributes tokens only.
"""
from __future__ import annotations

import glob
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

CWD_RE = re.compile(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"')
SKILL_RE = re.compile(r"\$gsd-path-[a-z][a-z-]*")
TASK_RE = re.compile(r"\bT\d{3,}\b")
HEAD_BYTES = 65536
RECENT_LIMIT = 20

DEFAULT_SESSION_DIRS = (
    "~/.codex/sessions",
    "~/Library/Application Support/orca/codex-accounts/*/home/sessions",
    "~/.claude/projects",
)


def expand_session_dirs(patterns: Iterable[str]) -> List[str]:
    dirs: List[str] = []
    for pattern in patterns:
        for path in sorted(glob.glob(os.path.expanduser(pattern))):
            if os.path.isdir(path) and path not in dirs:
                dirs.append(path)
    return dirs


def _iso(value) -> Optional[str]:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return value if isinstance(value, str) else None


def _epoch(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _num(value) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return ""


def cost_for(prices: dict, model: Optional[str], tokens_in: int, cached: int, tokens_out: int) -> Optional[float]:
    price = prices.get(model or "") if isinstance(prices, dict) else None
    if not isinstance(price, dict):
        return None
    return (tokens_in * float(price.get("input", 0)) + cached * float(price.get("cached", 0))
            + tokens_out * float(price.get("output", 0))) / 1e6


def parse_session(path: Path) -> Tuple[Optional[str], List[dict]]:
    """Return (cwd, records) for one Codex rollout or Claude transcript."""
    cwd: Optional[str] = None
    records: List[dict] = []
    skill: Optional[str] = None
    task: Optional[str] = None
    model: Optional[str] = None
    host = "codex"
    turn_started: Dict[str, float] = {}
    last_at: Dict[str, float] = {}
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                kind = record.get("type")
                payload = record.get("payload")
                if kind in ("user", "assistant") and isinstance(record.get("message"), dict):
                    host = "claude"
                    cwd = cwd or record.get("cwd")
                    message = record["message"]
                    text = _text_of(message.get("content"))
                    if kind == "user":
                        skill = skill or _first(SKILL_RE, text)
                        task = task or _first(TASK_RE, text)
                        continue
                    usage = message.get("usage") or {}
                    if not isinstance(usage, dict) or not usage:
                        continue
                    tokens_in = _num(usage.get("input_tokens")) + _num(usage.get("cache_creation_input_tokens"))
                    records.append({
                        "at": record.get("timestamp"), "turn": record.get("parentUuid") or record.get("uuid"),
                        "model": message.get("model"), "host": host,
                        "tokens_in": tokens_in, "tokens_cached": _num(usage.get("cache_read_input_tokens")),
                        "tokens_out": _num(usage.get("output_tokens")), "duration_s": None,
                        "subagent": bool(record.get("isSidechain")),
                    })
                    continue
                if not isinstance(payload, dict):
                    continue
                if kind == "session_meta":
                    cwd = cwd or payload.get("cwd")
                elif kind == "turn_context":
                    cwd = cwd or payload.get("cwd")
                    model = payload.get("model") or model
                elif kind == "event_msg" and payload.get("type") == "task_started":
                    turn_id = payload.get("turn_id")
                    started = payload.get("started_at")
                    if turn_id and isinstance(started, (int, float)):
                        turn_started[turn_id] = float(started)
                elif kind == "response_item" and payload.get("role") == "user":
                    text = _text_of(payload.get("content"))
                    skill = skill or _first(SKILL_RE, text)
                    task = task or _first(TASK_RE, text)
                elif kind == "token_usage_record":
                    usage = payload.get("usage") or payload.get("turn_token_usage") or {}
                    turn_id = payload.get("turn_id")
                    at = record.get("timestamp")
                    now = _epoch(at)
                    previous = last_at.get(turn_id) or turn_started.get(turn_id)
                    duration = round(now - previous, 1) if now is not None and previous is not None and now >= previous else None
                    if now is not None and turn_id:
                        last_at[turn_id] = now
                    records.append({
                        "at": at, "turn": turn_id, "model": model, "host": host,
                        "tokens_in": _num(usage.get("input_tokens")) - _num(usage.get("cached_input_tokens")),
                        "tokens_cached": _num(usage.get("cached_input_tokens")),
                        "tokens_out": _num(usage.get("output_tokens")), "duration_s": duration,
                        "subagent": False,
                    })
    except OSError:
        return None, []
    agent = skill or host
    if task:
        agent = f"{agent} · {task}"
    for entry in records:
        entry["agent"] = agent + (" · subagent" if entry.pop("subagent", False) else "")
    return cwd, records


def _add(slot: dict, tokens: int, cost: Optional[float]) -> None:
    slot["turns"] += 1
    slot["tokens"] += tokens
    if cost is not None:
        slot["cost"] += cost
        slot["priced"] += 1


def _finish(slot: dict) -> dict:
    """Round the cost, or drop it when no turn in the slot had a price."""
    out = dict(slot)
    out["cost"] = round(slot["cost"], 2) if slot.pop("priced", 0) else None
    out.pop("priced", None)
    return out


def _first(pattern: "re.Pattern", text: str) -> Optional[str]:
    match = pattern.search(text or "")
    return match.group(0) if match else None


def _read_head_cwd(path: Path) -> Optional[str]:
    try:
        with path.open("rb") as handle:
            head = handle.read(HEAD_BYTES).decode("utf-8", "replace")
    except OSError:
        return None
    match = CWD_RE.search(head)
    if not match:
        return None
    try:
        return json.loads('"' + match.group(1) + '"')
    except ValueError:
        return match.group(1)


class SessionIndex:
    """Incrementally parsed session files, keyed by path; only files whose cwd
    lies under a watched root are parsed in full."""

    def __init__(self, dirs: Iterable[str], prices: Optional[dict] = None,
                 cache_path: Optional[Path] = None):
        self.dirs = list(dirs)
        self.prices = prices or {}
        self.cache_path = Path(cache_path) if cache_path else None
        # path -> cwd read from the file head; persisted so a daemon restart
        # does not re-read the head of every session file on the machine.
        self._cwd: Dict[str, Optional[str]] = self._load_cache()
        self._unresolved: Dict[str, Tuple[int, int]] = {}
        self._parsed: Dict[str, Tuple[Tuple[int, float], List[dict]]] = {}

    def _load_cache(self) -> Dict[str, Optional[str]]:
        if self.cache_path is None:
            return {}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}

    def _save_cache(self) -> None:
        if self.cache_path is None:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=self.cache_path.name + ".", dir=str(self.cache_path.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({k: v for k, v in self._cwd.items() if v is not None}, handle)
            os.replace(tmp, self.cache_path)
        except OSError:
            pass

    def _files(self) -> Iterable[Path]:
        for base in self.dirs:
            for dirpath, _dirs, files in os.walk(base):
                for name in files:
                    if name.endswith(".jsonl"):
                        yield Path(dirpath) / name

    @staticmethod
    def _owner(cwd: Optional[str], roots: List[str]) -> Optional[str]:
        if not cwd:
            return None
        cwd = os.path.abspath(os.path.expanduser(cwd))
        for root in roots:
            if cwd == root or cwd.startswith(root.rstrip(os.sep) + os.sep):
                return root
        return None

    def scan(self, roots: Iterable[str]) -> None:
        roots = [os.path.abspath(r) for r in roots]
        new_heads = 0
        for path in self._files():
            key = str(path)
            if self._cwd.get(key) is None:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                head_stamp = (stat.st_size, stat.st_mtime_ns)
                if self._unresolved.get(key) != head_stamp:
                    self._cwd[key] = _read_head_cwd(path)
                    if self._cwd[key] is None:
                        self._unresolved[key] = head_stamp
                    else:
                        self._unresolved.pop(key, None)
                    new_heads += 1
            root = self._owner(self._cwd[key], roots)
            if root is None:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            stamp = (stat.st_size, stat.st_mtime)
            cached = self._parsed.get(key)
            if cached is not None and cached[0] == stamp:
                continue
            cwd, records = parse_session(path)
            if cwd and self._cwd[key] is None:
                self._cwd[key] = cwd
            self._parsed[key] = (stamp, records)
        if new_heads:
            self._save_cache()

    def records_for(self, root: str) -> List[dict]:
        root = os.path.abspath(root)
        out: List[dict] = []
        for key, (_stamp, records) in self._parsed.items():
            if self._owner(self._cwd.get(key), [root]) == root:
                out.extend(records)
        out.sort(key=lambda r: r.get("at") or "")
        return out

    def spend_for(self, root: str, milestones: List[dict], current: Optional[str]) -> Optional[dict]:
        """Aggregate usage for a project.

        ``milestones`` are roadmap entries with ``number`` and optional
        ``manifest.shipped`` dates; a record dated on or before a shipped date
        belongs to the earliest such milestone, later records to ``current``.
        """
        records = self.records_for(root)
        if not records:
            return None
        boundaries = sorted(
            ((m["manifest"]["shipped"], m["number"]) for m in milestones
             if isinstance(m, dict) and isinstance(m.get("manifest"), dict) and m["manifest"].get("shipped")),
        )
        totals = {"turns": 0, "prompts": set(), "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0, "cost": 0.0, "priced": 0}
        models: Dict[str, dict] = {}
        agents: Dict[str, dict] = {}
        by_milestone: Dict[str, dict] = {}
        unpriced: List[str] = []
        for entry in records:
            cost = cost_for(self.prices, entry.get("model"), entry["tokens_in"], entry["tokens_cached"], entry["tokens_out"])
            entry["cost"] = round(cost, 4) if cost is not None else None
            tokens = entry["tokens_in"] + entry["tokens_cached"] + entry["tokens_out"]
            totals["turns"] += 1
            totals["prompts"].add(entry.get("turn"))
            totals["tokens_in"] += entry["tokens_in"]
            totals["tokens_cached"] += entry["tokens_cached"]
            totals["tokens_out"] += entry["tokens_out"]
            if cost is None:
                if entry.get("model") and entry["model"] not in unpriced:
                    unpriced.append(entry["model"])
            else:
                totals["cost"] += cost
                totals["priced"] += 1
            model_slot = models.setdefault(entry.get("model") or "unknown", {"model": entry.get("model") or "unknown", "host": entry["host"], "turns": 0, "tokens": 0, "cost": 0.0, "priced": 0})
            _add(model_slot, tokens, cost)
            agent_slot = agents.setdefault(entry["agent"], {"agent": entry["agent"], "models": [], "turns": 0, "tokens": 0, "cost": 0.0, "priced": 0})
            _add(agent_slot, tokens, cost)
            if entry.get("model") and entry["model"] not in agent_slot["models"]:
                agent_slot["models"].append(entry["model"])
            day = (entry.get("at") or "")[:10]
            number = current
            for shipped, candidate in boundaries:
                if day and day <= shipped:
                    number = candidate
                    break
            if number:
                _add(by_milestone.setdefault(number, {"turns": 0, "tokens": 0, "cost": 0.0, "priced": 0}), tokens, cost)
        return {
            "turns": totals["turns"],
            "prompts": len(totals["prompts"]),
            "tokens_in": totals["tokens_in"],
            "tokens_cached": totals["tokens_cached"],
            "tokens_out": totals["tokens_out"],
            "cost": round(totals["cost"], 2) if totals["priced"] else None,
            "unpriced": unpriced,
            "models": [_finish(m) for m in sorted(models.values(), key=lambda m: -m["tokens"])],
            "agents": [_finish(a) for a in sorted(agents.values(), key=lambda a: -a["tokens"])],
            "milestones": {number: _finish(slot) for number, slot in by_milestone.items()},
            "recent": list(reversed(records[-RECENT_LIMIT:])),
        }
