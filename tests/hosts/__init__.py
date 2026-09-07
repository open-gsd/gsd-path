"""Per-host headless runners for live release evidence.

Each host module exposes ``SPEC``, a :class:`HostSpec`. ``tests/evaluate_host.py``
provides shared prepare / run / bind-child steps for release evidence. See its
module docstring for usage and each host module for capabilities and limitations.

Contract for a host module (``tests/hosts/<host>.py``):

- ``SPEC.name`` matches the key in ``scripts/skill-resources.json`` ``hosts``.
- ``SPEC.command(prompt_path, resume)`` returns the headless argv, or raises
  ``NotImplementedError`` with the documented alternative when none is available.
  The prompt is piped
  on stdin unless ``SPEC.prompt_on_stdin`` is False, in which case the module must
  place the prompt text into argv itself.
- ``SPEC.parse_events(lines)`` reads the recorded stdout lines and returns
  ``{"session_id", "final_message", "usage"}`` (values may be None when the host does
  not expose them; never invent them).
- ``SPEC.bind_child(run_root, child_id)`` returns the structured evidence that binds the
  logical task name (the task file ``agent`` field) to a *completed* child through the
  manifest-declared child API, or raises ``LookupError`` with the reason. It must only
  read what the host actually recorded (stream events, session transcripts).
- ``SPEC.verified_live`` states whether the module was checked against a real CLI on
  this machine; modules written from documentation alone must say False.
"""

from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

MANIFEST = Path(__file__).resolve().parents[2] / "scripts" / "skill-resources.json"


@dataclass
class HostSpec:
    name: str
    install_flag: str
    skill_root: str
    invocation: str
    child_api: str
    guard_tier: str
    command: Callable[[Path, Optional[str]], List[str]]
    parse_events: Callable[[Sequence[str]], Dict]
    bind_child: Callable[[Path, str], Dict]
    prompt_on_stdin: bool = True
    verified_live: bool = False
    notes: str = ""
    extra: Dict = field(default_factory=dict)


def load(host: str) -> HostSpec:
    return import_module(f"tests.hosts.{host}").SPEC


def known_hosts() -> List[str]:
    import json
    return list(json.loads(MANIFEST.read_text())["hosts"])
