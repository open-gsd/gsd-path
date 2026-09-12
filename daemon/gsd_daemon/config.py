from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

ENV_CONFIG = "GSD_DAEMON_CONFIG"


def default_config_path() -> Path:
    return Path.home() / ".gsd-path" / "daemon.json"


def resolve_config_path(path: Optional[Union[str, Path]] = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get(ENV_CONFIG)
    if env:
        return Path(env)
    return default_config_path()


def _abs(value: str) -> str:
    return os.path.abspath(os.path.expanduser(value))


@dataclass
class Config:
    parents: List[str] = field(default_factory=list)
    excludes: List[str] = field(default_factory=list)
    max_depth: int = 6
    poll_seconds: int = 5
    notify: bool = True
    history: bool = True

    def to_dict(self) -> dict:
        return {
            "parents": list(self.parents),
            "excludes": list(self.excludes),
            "max_depth": self.max_depth,
            "poll_seconds": self.poll_seconds,
            "notify": self.notify,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        if not isinstance(data, dict):
            return cls()
        parents = data.get("parents")
        excludes = data.get("excludes")
        return cls(
            parents=[_abs(p) for p in parents if isinstance(p, str)] if isinstance(parents, list) else [],
            excludes=[_abs(p) for p in excludes if isinstance(p, str)] if isinstance(excludes, list) else [],
            max_depth=_int_or(data.get("max_depth"), 6),
            poll_seconds=_int_or(data.get("poll_seconds"), 5),
            notify=bool(data.get("notify", True)),
            history=bool(data.get("history", True)),
        )

    @classmethod
    def load(cls, path: Optional[Union[str, Path]] = None) -> "Config":
        resolved = resolve_config_path(path)
        try:
            data = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls.from_dict(data)

    def save(self, path: Optional[Union[str, Path]] = None) -> Path:
        resolved = resolve_config_path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        fd, tmp = tempfile.mkstemp(prefix=resolved.name + ".", dir=str(resolved.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, resolved)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return resolved

    def add_parent(self, folder: str) -> None:
        folder = _abs(folder)
        if folder not in self.parents:
            self.parents.append(folder)

    def remove_parent(self, folder: str) -> None:
        folder = _abs(folder)
        if folder in self.parents:
            self.parents.remove(folder)


def _int_or(value, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value > 0:
        return value
    return default
