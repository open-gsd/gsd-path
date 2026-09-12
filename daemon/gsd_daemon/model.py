from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

SCHEMA = "gsd-path-daemon/status/v1"


@dataclass
class TaskSummary:
    id: str
    title: Optional[str] = None
    wave: Optional[int] = None
    status: Optional[str] = None
    files: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "wave": self.wave,
            "status": self.status,
            "files": list(self.files),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskSummary":
        return cls(
            id=data.get("id"),
            title=data.get("title"),
            wave=data.get("wave"),
            status=data.get("status"),
            files=list(data.get("files") or []),
        )


@dataclass
class ProjectStatus:
    root: str
    project: Optional[str] = None
    milestone: Optional[str] = None
    phase: Optional[str] = None
    status: Optional[str] = None
    branch: Optional[str] = None
    archive: Optional[str] = None
    integration: Optional[str] = None
    tasks: List[TaskSummary] = field(default_factory=list)
    tasks_done: int = 0
    tasks_total: int = 0
    current_wave: Optional[int] = None
    waves: Dict[int, str] = field(default_factory=dict)
    roadmap_milestones: List[dict] = field(default_factory=list)
    next_milestone: Optional[dict] = None
    phase_log: List[dict] = field(default_factory=list)
    vision: Optional[str] = None
    intent: Optional[str] = None
    lesson: Optional[str] = None
    git: Optional[dict] = None
    pending_answers: List[dict] = field(default_factory=list)
    next_skill: Optional[str] = None
    status_source: str = "parse-only"
    state_mtime: Optional[float] = None
    last_activity_iso: Optional[str] = None
    reviews: List[dict] = field(default_factory=list)
    criteria: Optional[List[dict]] = None
    ledger: List[dict] = field(default_factory=list)
    answers: List[dict] = field(default_factory=list)
    time_in_phase_s: Optional[int] = None
    usage: Optional[dict] = None
    spend: Optional[dict] = None
    health: str = "green"
    attention: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "project": self.project,
            "milestone": self.milestone,
            "phase": self.phase,
            "status": self.status,
            "branch": self.branch,
            "archive": self.archive,
            "integration": self.integration,
            "tasks": [task.to_dict() for task in self.tasks],
            "tasks_done": self.tasks_done,
            "tasks_total": self.tasks_total,
            "current_wave": self.current_wave,
            "waves": {str(number): name for number, name in sorted(self.waves.items())},
            "roadmap_milestones": list(self.roadmap_milestones),
            "next_milestone": self.next_milestone,
            "phase_log": list(self.phase_log),
            "vision": self.vision,
            "intent": self.intent,
            "lesson": self.lesson,
            "git": self.git,
            "pending_answers": list(self.pending_answers),
            "next_skill": self.next_skill,
            "status_source": self.status_source,
            "state_mtime": self.state_mtime,
            "last_activity_iso": self.last_activity_iso,
            "reviews": list(self.reviews),
            "criteria": list(self.criteria) if self.criteria is not None else None,
            "ledger": list(self.ledger),
            "answers": list(self.answers),
            "time_in_phase_s": self.time_in_phase_s,
            "usage": self.usage,
            "spend": self.spend,
            "health": self.health,
            "attention": list(self.attention),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectStatus":
        waves = data.get("waves") or {}
        return cls(
            root=data.get("root"),
            project=data.get("project"),
            milestone=data.get("milestone"),
            phase=data.get("phase"),
            status=data.get("status"),
            branch=data.get("branch"),
            archive=data.get("archive"),
            integration=data.get("integration"),
            tasks=[TaskSummary.from_dict(item) for item in data.get("tasks") or []],
            tasks_done=data.get("tasks_done") or 0,
            tasks_total=data.get("tasks_total") or 0,
            current_wave=data.get("current_wave"),
            waves={int(number): name for number, name in waves.items()},
            roadmap_milestones=list(data.get("roadmap_milestones") or []),
            next_milestone=data.get("next_milestone"),
            phase_log=list(data.get("phase_log") or []),
            vision=data.get("vision"),
            intent=data.get("intent"),
            lesson=data.get("lesson"),
            git=data.get("git"),
            pending_answers=list(data.get("pending_answers") or []),
            next_skill=data.get("next_skill"),
            status_source=data.get("status_source") or "parse-only",
            state_mtime=data.get("state_mtime"),
            last_activity_iso=data.get("last_activity_iso"),
            reviews=list(data.get("reviews") or []),
            criteria=list(data["criteria"]) if data.get("criteria") is not None else None,
            ledger=list(data.get("ledger") or []),
            answers=list(data.get("answers") or []),
            time_in_phase_s=data.get("time_in_phase_s"),
            usage=data.get("usage"),
            spend=data.get("spend"),
            health=data.get("health") or "green",
            attention=list(data.get("attention") or []),
        )


def aggregate(projects: List[ProjectStatus], generated_at: str) -> dict:
    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "projects": [project.to_dict() for project in projects],
    }
