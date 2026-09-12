from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

ENV_HISTORY = "GSD_DAEMON_HISTORY"


def default_history_path() -> Path:
    return Path.home() / ".gsd-path" / "history.jsonl"


def resolve_history_path(path: Optional[Union[str, Path]] = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get(ENV_HISTORY)
    if env:
        return Path(env)
    return default_history_path()


def append_event(event: dict, path: Optional[Union[str, Path]] = None) -> Path:
    resolved = resolve_history_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    record = dict(event)
    record.setdefault("at", datetime.now(timezone.utc).isoformat())
    with resolved.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return resolved
