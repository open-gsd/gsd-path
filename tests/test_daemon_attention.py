import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon import probe
from gsd_daemon.model import ProjectStatus

STATE = """---
pipeline: gsd-path/v2
project: demo
milestone: demo-ms
phase: build
status: active
branch: gsd-path/M001
archive: null
---

# Project State
"""

RUNTIME_PENDING = """import json
print(json.dumps({
    "schema": "gsd-path/status/v1",
    "state": {},
    "route": {},
    "pending_answers": [{
        "answer": "A001",
        "id": "A001",
        "question": "Default poll interval: 5s vs 10s?",
        "owner": "gsd-path-define",
        "status": "final",
    }],
    "next_skill": None,
}))
"""

FINAL_REVIEW_BLOCKED = """# Final Review — demo

Overall verdict: blocked

## Success criteria

### SC1 — daemon discovers v2 projects

- **Verdict**: met

### SC4 — Windows tray parity verified

- **Verdict**: not-met
"""

WAVE_REVIEW_PASS = """# Review — wave 1, cycle 1

Wave verdict: pass
Cycle: 1
Depth: full

all good
"""

ANSWERS_MD = """# GSD Path Discussion — Answers

## Answer A001 — 2026-09-11 — poll interval

- **Thread**: T001
- **Turn**: D001
- **Supersedes**: none
- **Question**: Default poll interval: 5s vs 10s?
- **Status**: NEEDS-USER
- **Conclusion**: none
- **Next owner**: gsd-path-define
- **Target artifact**: .project/intent/INTENT.md
- **Follow-up**: required

## Answer A002 — 2026-09-11 — disposed

- **Thread**: T002
- **Turn**: D002
- **Supersedes**: none
- **Question**: disposed question
- **Status**: final
- **Next owner**: gsd-path-plan
- **Target artifact**: .project/plan/PLAN.md
- **Follow-up**: required

## Disposition X001 — 2026-09-11

- **Answer**: A002
- **Status**: applied
- **Owner**: gsd-path-plan
- **Artifact**: .project/plan/PLAN.md
- **Evidence**: updated
"""


def make_task(project_dir: Path, task_id: str, slug: str, status: str,
              title: str = None) -> Path:
    tasks_dir = project_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    title = title or f"Task {task_id}"
    path = tasks_dir / f"{task_id}-{slug}.md"
    path.write_text(
        f"""---
id: {task_id}
title: {title}
wave: 1
deps: []
status: {status}
agent: null
base: null
worktree: null
task_branch: null
files:
  - src/a.py
---

# {task_id} — {title}
""",
        encoding="utf-8",
    )
    return path


def make_project(root: Path) -> Path:
    project_dir = root / ".project"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "STATE.md").write_text(STATE, encoding="utf-8")
    make_task(project_dir, "T001", "first-task", status="done", title="First task")
    make_task(project_dir, "T002", "second-task", status="in-progress", title="Second task")
    return root


def age_tree(path: Path, seconds: float) -> None:
    stamp = time.time() - seconds
    for dirpath, dirnames, filenames in os.walk(path, topdown=False):
        for name in filenames:
            os.utime(os.path.join(dirpath, name), (stamp, stamp))
        for name in dirnames:
            os.utime(os.path.join(dirpath, name), (stamp, stamp))
    os.utime(path, (stamp, stamp))


class AttentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "demo"

    def kinds(self, status: ProjectStatus) -> list:
        return [item["kind"] for item in status.attention]

    def test_pending_answer_question_amber(self) -> None:
        make_project(self.root)
        runtime_dir = self.root / ".gsd-path" / "runtime"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "pipeline_state.py").write_text(RUNTIME_PENDING, encoding="utf-8")
        status = probe.probe_project(self.root)
        self.assertEqual(self.kinds(status), ["question"])
        item = status.attention[0]
        self.assertEqual(item["label"], "Default poll interval: 5s vs 10s?")
        self.assertEqual(item["ref"], "A001")
        self.assertEqual(status.health, "amber")

    def test_parse_only_pending_answers_question_amber(self) -> None:
        make_project(self.root)
        discuss_dir = self.root / ".project" / "discuss"
        discuss_dir.mkdir()
        (discuss_dir / "ANSWERS.md").write_text(ANSWERS_MD, encoding="utf-8")
        status = probe.probe_project(self.root)
        self.assertEqual(status.status_source, "parse-only")
        self.assertEqual(status.pending_answers, [])
        self.assertEqual([item["id"] for item in status.answers], ["A001"])
        self.assertEqual(self.kinds(status), ["question"])
        item = status.attention[0]
        self.assertEqual(item["label"], "Default poll interval: 5s vs 10s?")
        self.assertEqual(item["ref"], "A001")
        self.assertEqual(status.health, "amber")

    def test_no_double_count_when_pending_answers_populated(self) -> None:
        make_project(self.root)
        runtime_dir = self.root / ".gsd-path" / "runtime"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "pipeline_state.py").write_text(RUNTIME_PENDING, encoding="utf-8")
        discuss_dir = self.root / ".project" / "discuss"
        discuss_dir.mkdir()
        (discuss_dir / "ANSWERS.md").write_text(ANSWERS_MD, encoding="utf-8")
        status = probe.probe_project(self.root)
        self.assertEqual(status.status_source, "runtime")
        self.assertEqual(len(status.pending_answers), 1)
        self.assertEqual(len(status.answers), 1)
        self.assertEqual(self.kinds(status), ["question"])
        self.assertEqual(status.attention[0]["ref"], "A001")
        self.assertEqual(status.health, "amber")

    def test_blocked_task_red(self) -> None:
        make_project(self.root)
        path = self.root / ".project" / "tasks" / "T002-second-task.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("status: in-progress", "status: blocked"),
            encoding="utf-8",
        )
        status = probe.probe_project(self.root)
        self.assertEqual(self.kinds(status), ["blocked"])
        item = status.attention[0]
        self.assertEqual(item["label"], "T002 — Second task")
        self.assertEqual(item["ref"], "T002")
        self.assertEqual(status.health, "red")

    def test_failing_review_and_not_met_criterion_red(self) -> None:
        make_project(self.root)
        review_dir = self.root / ".project" / "review"
        review_dir.mkdir()
        (review_dir / "FINAL.md").write_text(FINAL_REVIEW_BLOCKED, encoding="utf-8")
        (review_dir / "wave-1.cycle1.md").write_text(WAVE_REVIEW_PASS, encoding="utf-8")
        status = probe.probe_project(self.root)
        self.assertEqual(self.kinds(status), ["failed", "failed"])
        review_item, criterion_item = status.attention
        self.assertEqual(review_item["label"], "FINAL.md — blocked")
        self.assertEqual(review_item["ref"], "FINAL.md")
        self.assertEqual(criterion_item["label"], "SC4 — Windows tray parity verified")
        self.assertEqual(criterion_item["ref"], "SC4")
        self.assertEqual(status.health, "red")

    def test_passing_reviews_are_not_attention(self) -> None:
        make_project(self.root)
        review_dir = self.root / ".project" / "review"
        review_dir.mkdir()
        (review_dir / "wave-1.cycle1.md").write_text(WAVE_REVIEW_PASS, encoding="utf-8")
        status = probe.probe_project(self.root)
        self.assertEqual(status.attention, [])
        self.assertEqual(status.health, "green")

    def test_stale_active_project_amber(self) -> None:
        make_project(self.root)
        age_tree(self.root / ".project", seconds=3 * 86400)
        status = probe.probe_project(self.root)
        self.assertEqual(self.kinds(status), ["stale"])
        item = status.attention[0]
        self.assertEqual(item["label"], "no activity for 3d")
        self.assertIsNone(item["ref"])
        self.assertEqual(status.health, "amber")

    def test_shipped_project_not_stale(self) -> None:
        make_project(self.root)
        state_path = self.root / ".project" / "STATE.md"
        state_path.write_text(STATE.replace("status: active", "status: shipped"),
                              encoding="utf-8")
        age_tree(self.root / ".project", seconds=3 * 86400)
        status = probe.probe_project(self.root)
        self.assertEqual(status.attention, [])
        self.assertEqual(status.health, "green")

    def test_recently_active_project_not_stale(self) -> None:
        make_project(self.root)
        status = probe.probe_project(self.root)
        self.assertEqual(status.attention, [])
        self.assertEqual(status.health, "green")

    def test_health_attention_round_trip(self) -> None:
        make_project(self.root)
        path = self.root / ".project" / "tasks" / "T002-second-task.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("status: in-progress", "status: blocked"),
            encoding="utf-8",
        )
        status = probe.probe_project(self.root)
        data = json.loads(json.dumps(status.to_dict(), sort_keys=True))
        self.assertEqual(data["health"], "red")
        self.assertEqual(data["attention"], status.attention)
        restored = ProjectStatus.from_dict(data)
        self.assertEqual(restored.health, "red")
        self.assertEqual(restored.attention, status.attention)
        self.assertEqual(restored.to_dict(), data)

    def test_defaults_green_and_empty(self) -> None:
        status = ProjectStatus(root="/tmp/none")
        self.assertEqual(status.health, "green")
        self.assertEqual(status.attention, [])
        restored = ProjectStatus.from_dict(json.loads(json.dumps(status.to_dict())))
        self.assertEqual(restored.health, "green")
        self.assertEqual(restored.attention, [])


if __name__ == "__main__":
    unittest.main()
