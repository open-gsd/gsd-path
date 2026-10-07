import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

SOURCE = Path(__file__).resolve().parents[1]

from gsd_daemon import probe
from gsd_daemon.model import ProjectStatus

STATE_FULL = """---
pipeline: gsd-path/v2
project: demo
milestone: demo-ms    # set by define
phase: build          # v2 tokens
status: active
branch: gsd-path/M001
archive: null
integration_default: pull-request
integration: direct
integration_source: milestone
---

# Project State

## Log
- 2026-09-01 — build — started
"""

STATE_LEGACY = """---
pipeline: gsd-path/v2
project: legacy
milestone: null
phase: define
status: active
branch: null
archive: null
---

# Project State
"""

PLAN = """# Plan — demo

## Wave 1 — risk burn-down

Goal: prove it

## Wave 2 — walking skeleton

Goal: ship it

## Surface contract
"""

ROADMAP = """# Roadmap — demo

## Milestones

### M001 — demo-ms

Goal: first
Status: active
Archive: null

### M002 — next-ms

Goal: second
Status: pending

### M003 — old-ms

Goal: done
Status: shipped
"""

NEXT_STATE = """---
pipeline: gsd-path/v2
project: demo
milestone: next-ms
phase: research
status: active
branch: null
archive: null
---
"""

RUNTIME_STUB = """import json
print(json.dumps({
    "schema": "gsd-path/status/v1",
    "state": {},
    "route": {},
    "git": {"branch": "gsd-path/M001", "head": "abc123", "dirty": False},
    "pending_answers": [{"id": "Q001"}],
    "next_skill": "gsd-path-ship",
}))
"""

LAUNCHER_RUNTIME_STUB = """import json
print(json.dumps({
    "schema": "gsd-path/status/v1",
    "state": {"project": "demo", "milestone": "demo-ms", "phase": "build",
              "status": "active", "branch": "gsd-path/M001"},
    "route": {},
    "git": {"branch": "gsd-path/M001", "head": "def456", "dirty": False},
    "pending_answers": [{"id": "Q001"}],
    "next_skill": "gsd-path-ship",
}))
"""


def make_task(project_dir: Path, task_id: str, slug: str, wave: int, status: str,
              title: str = None, files=("src/a.py",)) -> Path:
    tasks_dir = project_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    title = title or f"Task {task_id}"
    files_block = "\n".join(f"  - {path}" for path in files)
    path = tasks_dir / f"{task_id}-{slug}.md"
    path.write_bytes(
        f"""---
id: {task_id}
title: {title}
wave: {wave}
deps: []
status: {status}     # orchestrator-owned
agent: null
base: null
worktree: null
task_branch: null
files:
{files_block}
---

# {task_id} — {title}
""".encode("utf-8"),
    )
    return path


def make_project(root: Path, state: str = STATE_FULL, with_next: bool = True) -> Path:
    project_dir = root / ".project"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "STATE.md").write_bytes(state.encode("utf-8"))
    make_task(project_dir, "T001", "first-task", wave=1, status="done", title="First task")
    make_task(project_dir, "T002", "second-task", wave=1, status="in-progress", title="Second task",
              files=("src/b.py", "src/c.py"))
    make_task(project_dir, "T003", "third-task", wave=2, status="pending", title="Third task")
    (project_dir / "plan").mkdir(exist_ok=True)
    (project_dir / "plan" / "PLAN.md").write_bytes(PLAN.encode("utf-8"))
    (project_dir / "ROADMAP.md").write_bytes(ROADMAP.encode("utf-8"))
    if with_next:
        (project_dir / "next").mkdir(exist_ok=True)
        (project_dir / "next" / "STATE.md").write_bytes(NEXT_STATE.encode("utf-8"))
    return root


def make_declared_runtime(root: Path, home: Path) -> None:
    """Pinned-runtime install shape: shared store + declaration + real launcher.

    The store's pipeline_state is a payload stub; everything between it and
    the daemon (runtime.json resolution, manifest validation, the subprocess
    hop) is the real installed launcher from scripts/status_runtime.py.
    """
    stub = LAUNCHER_RUNTIME_STUB.encode("utf-8")
    manifest = {"version": "test",
                "files": {"pipeline_state.py": hashlib.sha256(stub).hexdigest()}}
    digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    runtime = home / ".gsd-path" / "runtimes" / digest
    runtime.mkdir(parents=True)
    (runtime / "pipeline_state.py").write_bytes(stub)
    (runtime / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    gsd = root / ".gsd-path"
    gsd.mkdir(parents=True, exist_ok=True)
    (gsd / "runtime.json").write_bytes(
        (json.dumps({"schema": "gsd-path/runtime/v1", "version": "test", "digest": digest},
                    sort_keys=True) + "\n").encode("utf-8"))
    shutil.copyfile(SOURCE / "scripts" / "status_runtime.py", gsd / "status_runtime.py")


class ParseStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "demo"
        make_project(self.root)

    def test_parse_state_full(self) -> None:
        state = probe.parse_state_file(self.root / ".project" / "STATE.md")
        self.assertEqual(state["pipeline"], "gsd-path/v2")
        self.assertEqual(state["project"], "demo")
        self.assertEqual(state["milestone"], "demo-ms")
        self.assertEqual(state["phase"], "build")
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["branch"], "gsd-path/M001")
        self.assertIsNone(state["archive"])
        self.assertEqual(state["integration_default"], "pull-request")
        self.assertEqual(state["integration"], "direct")
        self.assertEqual(state["integration_source"], "milestone")

    def test_parse_state_legacy_minimal(self) -> None:
        path = Path(self.tmp.name) / "legacy.md"
        path.write_bytes(STATE_LEGACY.encode("utf-8"))
        state = probe.parse_state_file(path)
        self.assertEqual(state["project"], "legacy")
        self.assertEqual(state["phase"], "define")
        self.assertNotIn("integration", state)
        self.assertNotIn("integration_default", state)
        self.assertNotIn("integration_source", state)

    def test_parse_state_tolerates_garbage(self) -> None:
        path = Path(self.tmp.name) / "garbage.md"
        path.write_bytes("not frontmatter at all\n---\npipeline: gsd-path/v2\n".encode("utf-8"))
        self.assertEqual(probe.parse_state_file(path), {})
        self.assertEqual(probe.parse_state_file(path.with_name("missing.md")), {})
        malformed = Path(self.tmp.name) / "malformed.md"
        malformed.write_bytes("---\n!!!not yaml!!!\npipeline: gsd-path/v2\n: : :\n---\n".encode("utf-8"))
        self.assertEqual(probe.parse_state_file(malformed).get("pipeline"), "gsd-path/v2")

    def test_is_project_root(self) -> None:
        self.assertTrue(probe.is_project_root(self.root))
        self.assertFalse(probe.is_project_root(Path(self.tmp.name)))

    def test_windows_state_read_retries_a_replace_in_progress(self) -> None:
        state = self.root / ".project" / "STATE.md"
        real = Path.read_text
        attempts = []

        def read_text(path, *args, **kwargs):
            attempts.append(path)
            if len(attempts) < 3:
                raise PermissionError(13, "Access is denied")
            return real(path, *args, **kwargs)

        # Replace only probe's os: patching os.name itself breaks pathlib on POSIX.
        with mock.patch.object(probe, "os", SimpleNamespace(name="nt")), \
                mock.patch.object(probe.time, "sleep"), \
                mock.patch.object(Path, "read_text", read_text):
            self.assertTrue(probe.is_project_root(self.root))
        self.assertEqual(len(attempts), 3)
        with mock.patch.object(probe, "os", SimpleNamespace(name="posix")), \
                mock.patch.object(Path, "read_text", side_effect=PermissionError(13, "denied")):
            self.assertEqual(probe.parse_state_file(state), {})


class ParseTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "demo"
        make_project(self.root)

    def test_parse_task_file(self) -> None:
        task = probe.parse_task_file(self.root / ".project" / "tasks" / "T002-second-task.md")
        self.assertEqual(task.id, "T002")
        self.assertEqual(task.title, "Second task")
        self.assertEqual(task.wave, 1)
        self.assertEqual(task.status, "in-progress")
        self.assertEqual(task.files, ["src/b.py", "src/c.py"])

    def test_parse_task_inline_list_fields(self) -> None:
        project_dir = self.root / ".project"
        path = make_task(project_dir, "T009", "inline", wave=3, status="pending")
        text = path.read_text(encoding="utf-8").replace(
            "files:\n  - src/a.py", "files: [src/x.py, src/y.py]"
        )
        path.write_bytes(text.encode("utf-8"))
        task = probe.parse_task_file(path)
        self.assertEqual(task.files, ["src/x.py", "src/y.py"])

    def test_parse_plan(self) -> None:
        waves = probe.parse_plan(self.root / ".project" / "plan" / "PLAN.md")
        self.assertEqual(waves, {1: "risk burn-down", 2: "walking skeleton"})

    def test_parse_plan_missing(self) -> None:
        self.assertEqual(probe.parse_plan(self.root / "nope.md"), {})

    def test_parse_roadmap(self) -> None:
        milestones = probe.parse_roadmap(self.root / ".project" / "ROADMAP.md")
        extra = {"depends": [], "integrated": None, "manifest": None, "duration_s": None, "tokens": None}
        self.assertEqual(milestones, [
            dict({"number": "M001", "slug": "demo-ms", "status": "active", "archive": None, "goal": "first"}, **extra),
            dict({"number": "M002", "slug": "next-ms", "status": "pending", "archive": None, "goal": "second"}, **extra),
            dict({"number": "M003", "slug": "old-ms", "status": "shipped", "archive": None, "goal": "done"}, **extra),
        ])

    def test_parse_roadmap_depends_and_integrated(self) -> None:
        path = Path(self.tmp.name) / "roadmap2.md"
        path.write_bytes(
            "### M002 — two\n\nGoal: second thing\nDepends on: [M001, M000]\nStatus: shipped\n"
            "Archive: .project/archive/002-two\nIntegrated: 158ab3a6554e3d6be083e4a752583763a5d682a5\n".encode("utf-8"),
        )
        milestone = probe.parse_roadmap(path)[0]
        self.assertEqual(milestone["depends"], ["M001", "M000"])
        self.assertEqual(milestone["integrated"], "158ab3a6554e3d6be083e4a752583763a5d682a5")
        self.assertEqual(milestone["goal"], "second thing")

    def test_parse_manifest(self) -> None:
        path = Path(self.tmp.name) / "MANIFEST.md"
        path.write_bytes(
            "# Archive — 004-x\n\nMilestone: x\nShipped: 2026-09-08\nFinal verdict: all criteria met\n"
            "Waves: 14  Tasks: 18 done / 18 total  Review cycles used: 1/2/3/2\nCarried forward: 3 DOCS-AUDIT ruling(s)\n".encode("utf-8"),
        )
        self.assertEqual(probe.parse_manifest(path), {
            "shipped": "2026-09-08", "verdict": "all criteria met", "waves": 14,
            "tasks_done": 18, "tasks_total": 18, "cycles_avg": 2.0, "carried": 3,
        })
        self.assertIsNone(probe.parse_manifest(path.with_name("missing.md")))

    def test_parse_phase_log_collapses_repeats(self) -> None:
        path = Path(self.tmp.name) / "STATE-log.md"
        path.write_bytes(
            "## Log\n- 2026-08-26 — define — started\n- 2026-08-26 — define — charter approved\n"
            "- 2026-08-27 — research — started\n- 2026-09-10 — build — started\n".encode("utf-8"),
        )
        self.assertEqual(probe.parse_phase_log(path), [
            {"phase": "define", "date": "2026-08-26"},
            {"phase": "research", "date": "2026-08-27"},
            {"phase": "build", "date": "2026-09-10"},
        ])
        self.assertEqual(probe.parse_phase_log(path.with_name("missing.md")), [])

    def test_parse_phase_log_scopes_to_current_milestone(self) -> None:
        path = Path(self.tmp.name) / "STATE-log2.md"
        path.write_bytes(
            "## Log\n- 2026-08-26 — inspect — initialized\n- 2026-08-26 — define — started\n"
            "- 2026-08-27 — build — started\n- 2026-08-30 — shipped — done\n"
            "- 2026-09-01 — define — next milestone\n- 2026-09-02 — plan — started\n".encode("utf-8"),
        )
        self.assertEqual(probe.parse_phase_log(path), [
            {"phase": "define", "date": "2026-09-01"},
            {"phase": "plan", "date": "2026-09-02"},
        ])

    def test_parse_phase_log_keeps_each_phase_once_dating_current_by_latest(self) -> None:
        path = Path(self.tmp.name) / "STATE-log3.md"
        path.write_bytes(
            "## Log\n- 2026-09-01 — define — started\n- 2026-09-02 — plan — started\n"
            "- 2026-09-03 — build — started\n- 2026-09-04 — ship — started\n"
            "- 2026-09-05 — plan — patch\n- 2026-09-06 — build — patch\n".encode("utf-8"),
        )
        self.assertEqual(probe.parse_phase_log(path), [
            {"phase": "define", "date": "2026-09-01"},
            {"phase": "plan", "date": "2026-09-02"},
            {"phase": "build", "date": "2026-09-06"},
            {"phase": "ship", "date": "2026-09-04"},
        ])

    def test_section_paragraph_and_latest_lesson(self) -> None:
        charter = Path(self.tmp.name) / "CHARTER.md"
        charter.write_bytes("# Charter\n\nReview panel: off\n\n## Vision\n\nFirst line\ncontinues here.\n\nSecond paragraph.\n\n## Scope\n- x\n".encode("utf-8"))
        self.assertEqual(probe._section_paragraph(charter, "Vision"), "First line continues here.")
        self.assertIsNone(probe._section_paragraph(charter, "Missing"))
        lessons = Path(self.tmp.name) / "LESSONS.md"
        lessons.write_bytes("- 001-a — first lesson\n- 002-b — latest lesson\n\n".encode("utf-8"))
        self.assertEqual(probe.parse_latest_lesson(lessons), "002-b — latest lesson")
        self.assertIsNone(probe.parse_latest_lesson(lessons.with_name("nope.md")))

    def test_parse_roadmap_archive_path(self) -> None:
        path = Path(self.tmp.name) / "roadmap.md"
        path.write_bytes(
            "### M001 — done-ms\n\nStatus: shipped\nArchive: .project/archive/001-done-ms\n".encode("utf-8"),
        )
        milestones = probe.parse_roadmap(path)
        self.assertEqual(milestones[0]["archive"], ".project/archive/001-done-ms")
        self.assertIsNone(milestones[0]["duration_s"])
        self.assertIsNone(milestones[0]["tokens"])

    def test_parse_roadmap_missing(self) -> None:
        self.assertEqual(probe.parse_roadmap(self.root / "nope.md"), [])


class ProbeProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "demo"

    def test_full_probe(self) -> None:
        make_project(self.root)
        status = probe.probe_project(self.root)
        self.assertEqual(status.project, "demo")
        self.assertEqual(status.milestone, "demo-ms")
        self.assertEqual(status.phase, "build")
        self.assertEqual(status.status, "active")
        self.assertEqual(status.branch, "gsd-path/M001")
        self.assertIsNone(status.archive)
        self.assertEqual(status.integration, "direct")
        self.assertEqual(status.tasks_total, 3)
        self.assertEqual(status.tasks_done, 1)
        self.assertEqual(status.current_wave, 1)
        self.assertEqual(status.waves, {1: "risk burn-down", 2: "walking skeleton"})
        self.assertEqual(len(status.roadmap_milestones), 3)
        self.assertEqual(status.phase_log, [{"phase": "build", "date": "2026-09-01"}])
        self.assertIsNone(status.vision)
        self.assertIsNone(status.intent)
        self.assertIsNone(status.lesson)
        self.assertEqual(status.next_milestone, {
            "milestone": "next-ms",
            "phase": "research",
            "status": "active",
        })
        self.assertEqual(status.status_source, "parse-only")
        self.assertEqual(status.pending_answers, [])
        self.assertIsNone(status.next_skill)
        self.assertIsNotNone(status.state_mtime)
        self.assertIsNotNone(status.last_activity_iso)

    def test_current_wave_null_when_all_done(self) -> None:
        make_project(self.root)
        tasks_dir = self.root / ".project" / "tasks"
        for path in tasks_dir.iterdir():
            path.write_bytes(
                path.read_text(encoding="utf-8").replace("status: in-progress", "status: done")
                .replace("status: pending", "status: done").encode("utf-8"),
            )
        status = probe.probe_project(self.root)
        self.assertIsNone(status.current_wave)
        self.assertEqual(status.tasks_done, 3)

    def test_no_tasks_current_wave_null(self) -> None:
        make_project(self.root)
        for path in (self.root / ".project" / "tasks").iterdir():
            path.unlink()
        status = probe.probe_project(self.root)
        self.assertIsNone(status.current_wave)
        self.assertEqual(status.tasks_total, 0)

    def test_legacy_state_no_integration(self) -> None:
        make_project(self.root, state=STATE_LEGACY, with_next=False)
        status = probe.probe_project(self.root)
        self.assertEqual(status.project, "legacy")
        self.assertIsNone(status.integration)
        self.assertIsNone(status.next_milestone)

    def test_git_info_non_repo(self) -> None:
        make_project(self.root)
        status = probe.probe_project(self.root)
        self.assertIsNotNone(status.git)
        self.assertIsNone(status.git["branch"])
        self.assertIsNone(status.git["head"])
        self.assertIsNone(status.git["dirty"])

    def test_runtime_enrichment(self) -> None:
        make_project(self.root)
        runtime_dir = self.root / ".gsd-path" / "runtime"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "pipeline_state.py").write_bytes(RUNTIME_STUB.encode("utf-8"))
        status = probe.probe_project(self.root)
        self.assertEqual(status.status_source, "runtime")
        self.assertEqual(status.pending_answers, [{"id": "Q001"}])
        self.assertEqual(status.next_skill, "gsd-path-ship")
        self.assertEqual(status.git["head"], "abc123")

    def test_runtime_git_dirty_has_dashboard_boolean_shape(self) -> None:
        make_project(self.root)
        runtime = self.root / ".gsd-path/runtime"
        runtime.mkdir(parents=True)
        for dirty, expected in (([], False), ([".project/STATE.md"], True),
                                (False, False), (True, True), (None, None)):
            with self.subTest(dirty=dirty):
                stub = RUNTIME_STUB.replace('"dirty": False', '"dirty": ' + repr(dirty))
                (runtime / "pipeline_state.py").write_bytes(stub.encode("utf-8"))
                status = probe.probe_project(self.root)
                self.assertEqual(status.status_source, "runtime")
                self.assertIs(status.to_dict()["git"]["dirty"], expected)

    def test_runtime_failure_falls_back(self) -> None:
        make_project(self.root)
        runtime_dir = self.root / ".gsd-path" / "runtime"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "pipeline_state.py").write_bytes("raise SystemExit(1)\n".encode("utf-8"))
        status = probe.probe_project(self.root)
        self.assertEqual(status.status_source, "parse-only")

    def test_enrich_disabled_skips_runtime(self) -> None:
        make_project(self.root)
        runtime_dir = self.root / ".gsd-path" / "runtime"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "pipeline_state.py").write_bytes(RUNTIME_STUB.encode("utf-8"))
        status = probe.probe_project(self.root, enrich=False)
        self.assertEqual(status.status_source, "parse-only")
        self.assertEqual(status.pending_answers, [])

    def test_round_trip(self) -> None:
        make_project(self.root)
        status = probe.probe_project(self.root)
        restored = ProjectStatus.from_dict(json.loads(json.dumps(status.to_dict(), sort_keys=True)))
        self.assertEqual(restored.to_dict(), status.to_dict())


class DeclaredRuntimeTests(unittest.TestCase):
    """The project launcher is the probe's first hop for pinned-runtime projects."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.root = base / "demo"
        self.home = base / "home"
        self.home.mkdir()
        make_project(self.root)
        environment = mock.patch.dict(os.environ, {"HOME": str(self.home),
                                                   "USERPROFILE": str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)

    def test_launcher_payload_enriches_projection(self) -> None:
        make_declared_runtime(self.root, self.home)
        status = probe.probe_project(self.root)
        self.assertEqual(status.status_source, "runtime")
        self.assertEqual(status.workflow, {"state": "active", "label": "In build"})
        self.assertEqual(status.project, "demo")
        self.assertEqual(status.branch, "gsd-path/M001")
        self.assertEqual(status.git["head"], "def456")
        self.assertEqual(status.next_skill, "gsd-path-ship")

    def test_unavailable_runtime_store_fails_soft(self) -> None:
        make_declared_runtime(self.root, self.home)
        shutil.rmtree(self.home / ".gsd-path" / "runtimes")
        status = probe.probe_project(self.root)
        self.assertEqual(status.status_source, "parse-only")
        self.assertEqual(status.workflow["state"], "unverified")
        self.assertEqual(status.health, "amber")

    def test_failing_launcher_does_not_run_legacy_runtime(self) -> None:
        gsd = self.root / ".gsd-path"
        (gsd / "runtime").mkdir(parents=True)
        (gsd / "runtime" / "pipeline_state.py").write_bytes(RUNTIME_STUB.encode("utf-8"))
        (gsd / "status_runtime.py").write_bytes("raise SystemExit(2)\n".encode("utf-8"))
        status = probe.probe_project(self.root)
        self.assertEqual(status.status_source, "parse-only")
        self.assertEqual(status.workflow["state"], "unverified")

    def test_failing_launcher_without_legacy_fails_soft(self) -> None:
        gsd = self.root / ".gsd-path"
        gsd.mkdir(parents=True)
        (gsd / "status_runtime.py").write_bytes("raise SystemExit(2)\n".encode("utf-8"))
        status = probe.probe_project(self.root)
        self.assertEqual(status.status_source, "parse-only")
        self.assertEqual(status.workflow["state"], "unverified")


WAVE_REVIEW = """# Review — wave 1, cycle 1

<!-- reviewer comment
spanning lines -->

Wave verdict: pass
Cycle: 1
Depth: full
Tasks reviewed: 3

## T001 — first: pass

- ✅ criterion — evidence

3/3 tasks pass; intent coverage SC1–SC3
"""

WAVE_REVIEW_BLOCKED = """# Review — wave 2, cycle 2

Wave verdict: blocked
Cycle: 2
Depth: verify-only

T206 missing escalation cap evidence
"""

FINAL_REVIEW = """# Final Review — demo

Reviewed HEAD: 9a0b1c2d3e4f
Overall verdict: blocked

## Success criteria

### SC1 — daemon discovers v2 projects under watched parents

- **Verdict**: met
- **Check**: `gsd-path-daemon scan`
- **Observed**: 1 project

### SC4 — Windows tray parity verified on a real machine

- **Verdict**: not-met
- **Check**: `none`
- **Observed**: no Windows machine
"""

GAP_REVIEW = """# Gap Review — 1: cross-wave config drift

Reviewed HEAD: 9a0b1c2d3e4f
Gap verdict: pass
Risk: cross-wave config drift

## Finding

- **Found**: no drift observed
"""

PATCH_FINDINGS = """# Patch Findings

Overall verdict: pass

all patch findings resolved
"""

ANSWERS_MD = """# GSD Path Discussion — Answers

## Answer A001 — 2026-09-10 — poll interval

- **Thread**: T001
- **Turn**: D001
- **Supersedes**: none
- **Question**: Default poll interval: 5s vs 10s for large monorepo parents?
- **Status**: final
- **Conclusion**: 5s
- **Next owner**: gsd-path-define
- **Target artifact**: .project/intent/INTENT.md
- **Follow-up**: required

## Answer A002 — 2026-09-10 — disposed

- **Thread**: T002
- **Turn**: D002
- **Supersedes**: none
- **Question**: disposed question
- **Status**: final
- **Next owner**: gsd-path-plan
- **Target artifact**: .project/plan/PLAN.md
- **Follow-up**: required

## Disposition X001 — 2026-09-10

- **Answer**: A002
- **Status**: applied
- **Owner**: gsd-path-plan
- **Artifact**: .project/plan/PLAN.md
- **Evidence**: updated

## Answer A003 — 2026-09-11 — windows scope

- **Thread**: T003
- **Turn**: D003
- **Supersedes**: none
- **Question**: Is Windows verification in scope for M001 or deferred to M002?
- **Status**: NEEDS-USER
- **Next owner**: gsd-path-plan
- **Target artifact**: .project/plan/PLAN.md
- **Follow-up**: required

## Answer A004 — 2026-09-11 — working

- **Thread**: T003
- **Turn**: D004
- **Supersedes**: none
- **Question**: still being worked
- **Status**: working
- **Next owner**: gsd-path-build
- **Target artifact**: none
- **Follow-up**: required
"""


class ReviewParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.review_dir = Path(self.tmp.name) / "review"
        self.review_dir.mkdir()

    def test_parse_reviews(self) -> None:
        (self.review_dir / "wave-1.cycle1.md").write_bytes(WAVE_REVIEW.encode("utf-8"))
        (self.review_dir / "wave-2.cycle2.md").write_bytes(WAVE_REVIEW_BLOCKED.encode("utf-8"))
        (self.review_dir / "FINAL.md").write_bytes(FINAL_REVIEW.encode("utf-8"))
        (self.review_dir / "final-gap-1.md").write_bytes(GAP_REVIEW.encode("utf-8"))
        (self.review_dir / "PATCH-FINDINGS.md").write_bytes(PATCH_FINDINGS.encode("utf-8"))
        reviews = probe.parse_reviews(self.review_dir)
        by_file = {review["file"]: review for review in reviews}
        self.assertEqual([review["file"] for review in reviews],
                         sorted(by_file, key=probe._natural_key))
        wave1 = by_file["wave-1.cycle1.md"]
        self.assertEqual(wave1["kind"], "wave")
        self.assertEqual(wave1["verdict"], "pass")
        self.assertEqual(wave1["cycle"], 1)
        self.assertEqual(wave1["depth"], "full")
        self.assertEqual(wave1["note"], "3/3 tasks pass; intent coverage SC1–SC3")
        wave2 = by_file["wave-2.cycle2.md"]
        self.assertEqual(wave2["verdict"], "blocked")
        self.assertEqual(wave2["cycle"], 2)
        self.assertEqual(wave2["depth"], "verify-only")
        final = by_file["FINAL.md"]
        self.assertEqual(final["kind"], "final")
        self.assertEqual(final["verdict"], "blocked")
        gap = by_file["final-gap-1.md"]
        self.assertEqual(gap["kind"], "gap")
        self.assertEqual(gap["verdict"], "pass")
        patch = by_file["PATCH-FINDINGS.md"]
        self.assertEqual(patch["kind"], "patch-findings")
        self.assertEqual(patch["verdict"], "pass")

    def test_parse_reviews_tolerates_garbage(self) -> None:
        (self.review_dir / "wave-9.cycle1.md").write_bytes("no verdicts here\n".encode("utf-8"))
        (self.review_dir / "notes.txt").write_bytes("not markdown\n".encode("utf-8"))
        reviews = probe.parse_reviews(self.review_dir)
        self.assertEqual(len(reviews), 1)
        self.assertIsNone(reviews[0]["verdict"])
        self.assertIsNone(reviews[0]["cycle"])
        self.assertIsNone(reviews[0]["depth"])
        self.assertEqual(reviews[0]["note"], "no verdicts here")

    def test_parse_reviews_missing_dir(self) -> None:
        self.assertEqual(probe.parse_reviews(Path(self.tmp.name) / "nope"), [])

    def test_parse_final_criteria(self) -> None:
        path = self.review_dir / "FINAL.md"
        path.write_bytes(FINAL_REVIEW.encode("utf-8"))
        criteria = probe.parse_final_criteria(path)
        self.assertEqual(criteria, [
            {"id": "SC1", "text": "daemon discovers v2 projects under watched parents",
             "verdict": "met"},
            {"id": "SC4", "text": "Windows tray parity verified on a real machine",
             "verdict": "not-met"},
        ])

    def test_parse_final_criteria_missing(self) -> None:
        self.assertIsNone(probe.parse_final_criteria(self.review_dir / "FINAL.md"))


class LedgerParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "verify-ledger.jsonl"

    def test_parse_verify_ledger(self) -> None:
        lines = []
        for index in range(25):
            lines.append(json.dumps({
                "command": f"cmd-{index}",
                "commit": f"sha{index:05d}",
                "result": "pass" if index % 2 else "fail",
                "recorded_at": f"2026-09-11T10:{index:02d}:00+00:00",
                "extra": "ignored-key",
            }))
        lines.insert(3, "not json at all")
        lines.insert(5, json.dumps([1, 2, 3]))
        self.path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        ledger = probe.parse_verify_ledger(self.path)
        self.assertEqual(len(ledger), 20)
        self.assertEqual(ledger[0]["command"], "cmd-24")
        self.assertEqual(ledger[-1]["command"], "cmd-5")
        self.assertEqual(ledger[0], {
            "command": "cmd-24",
            "commit": "sha00024",
            "result": "fail",
            "recorded_at": "2026-09-11T10:24:00+00:00",
        })

    def test_parse_verify_ledger_missing(self) -> None:
        self.assertEqual(probe.parse_verify_ledger(self.path), [])


class AnswersParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ANSWERS.md"
        self.path.write_bytes(ANSWERS_MD.encode("utf-8"))

    def test_parse_pending_answers(self) -> None:
        pending = probe.parse_pending_answers(self.path)
        self.assertEqual([item["id"] for item in pending], ["A001", "A003"])
        first = pending[0]
        self.assertEqual(first["question"],
                         "Default poll interval: 5s vs 10s for large monorepo parents?")
        self.assertEqual(first["owner"], "gsd-path-define")
        self.assertEqual(first["status"], "final")
        self.assertEqual(first["thread"], "T001")
        self.assertEqual(first["target"], ".project/intent/INTENT.md")
        self.assertEqual(pending[1]["status"], "NEEDS-USER")

    def test_parse_pending_answers_missing(self) -> None:
        self.assertEqual(probe.parse_pending_answers(Path(self.tmp.name) / "nope.md"), [])

    def test_collect_answers_prefers_runtime(self) -> None:
        runtime_pending = [{"answer": "A001", "owner": "gsd-path-define",
                            "status": "final", "target": ".project/intent/INTENT.md"},
                           {"answer": "A099", "owner": "gsd-path-plan",
                            "status": "NEEDS-USER", "target": ".project/plan/PLAN.md"}]
        answers = probe._collect_answers(self.path, runtime_pending)
        self.assertEqual([item["id"] for item in answers], ["A001", "A099"])
        self.assertEqual(answers[0]["question"],
                         "Default poll interval: 5s vs 10s for large monorepo parents?")
        self.assertEqual(answers[0]["thread"], "T001")
        self.assertIsNone(answers[1]["question"])

    def test_collect_answers_falls_back_to_direct_parse(self) -> None:
        answers = probe._collect_answers(self.path, None)
        self.assertEqual([item["id"] for item in answers], ["A001", "A003"])


class UsageParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "usage.jsonl"

    def test_parse_usage(self) -> None:
        entries = [
            {"task": "T001", "model": "kimi-k2", "family": "kimi", "tokens_in": 1000,
             "tokens_out": 500, "cost": 0.10, "recorded_at": "2026-09-10T10:00:00+00:00",
             "phase": "build"},
            {"task": "T001", "model": "kimi-k2", "family": "kimi", "tokens_in": 1000,
             "tokens_out": 500, "cost": 0.10, "phase": "build"},
            {"task": "T002", "model": "claude-opus-4.5", "family": "claude", "tokens_in": 2000,
             "tokens_out": 1000, "cost": 0.40, "phase": "plan"},
            {"task": "T003"},
            {"model": "kimi-k2", "family": "kimi", "tokens_in": 500, "tokens_out": 0,
             "cost": 0.05},
        ]
        lines = [json.dumps(entry) for entry in entries] + ["garbage line"]
        self.path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        usage = probe.parse_usage(self.path)
        self.assertEqual(usage["tokens_in"], 4500)
        self.assertEqual(usage["tokens_out"], 2000)
        self.assertAlmostEqual(usage["cost"], 0.65)
        self.assertEqual(usage["models"][0]["model"], "kimi-k2")
        self.assertEqual(usage["models"][0]["family"], "kimi")
        self.assertAlmostEqual(usage["models"][0]["share"], 3500 / 6500, places=4)
        self.assertEqual(usage["models"][1]["model"], "claude-opus-4.5")
        by_phase = {item["phase"]: item["tokens"] for item in usage["by_phase"]}
        self.assertEqual(by_phase["build"], 3000)
        self.assertEqual(by_phase["plan"], 3000)
        self.assertEqual(by_phase["unknown"], 500)
        self.assertEqual(usage["by_task"][0], {"task": "T001", "model": "kimi-k2",
                                               "tokens": 3000})
        self.assertEqual(usage["by_task"][1], {"task": "T002", "model": "claude-opus-4.5",
                                               "tokens": 3000})

    def test_parse_usage_by_task_complete(self) -> None:
        lines = [json.dumps({"task": f"T{i:03d}", "tokens_in": i, "tokens_out": 0})
                 for i in range(15)]
        self.path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        usage = probe.parse_usage(self.path)
        self.assertEqual(len(usage["by_task"]), 15)
        self.assertEqual(usage["by_task"][0]["task"], "T014")

    def test_parse_usage_missing(self) -> None:
        self.assertIsNone(probe.parse_usage(self.path))

    def test_parse_usage_empty_file(self) -> None:
        self.path.write_bytes("".encode("utf-8"))
        usage = probe.parse_usage(self.path)
        self.assertEqual(usage["tokens_in"], 0)
        self.assertEqual(usage["models"], [])


class TimeInPhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "demo"
        self.history = Path(self.tmp.name) / "history.jsonl"

    def _probe(self, **kwargs):
        with mock.patch.dict(os.environ, {"GSD_DAEMON_HISTORY": str(self.history)}):
            return probe.probe_project(self.root, **kwargs)

    def test_time_in_phase_from_history(self) -> None:
        make_project(self.root)
        at = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        events = [
            {"type": "phase-changed", "root": str(self.root), "detail": "x -> y",
             "at": "2026-09-01T00:00:00+00:00"},
            {"type": "tasks-changed", "root": str(self.root), "detail": "1/2",
             "at": at},
            {"type": "phase-changed", "root": str(self.root), "detail": "plan -> build",
             "at": at},
            {"type": "phase-changed", "root": "/somewhere/else", "detail": "a -> b",
             "at": at},
        ]
        self.history.write_bytes("".join(json.dumps(e) + "\n" for e in events).encode("utf-8"))
        before = datetime.now(timezone.utc)
        status = self._probe()
        after = datetime.now(timezone.utc)
        expected = (before - datetime.fromisoformat(at)).total_seconds()
        self.assertIsNotNone(status.time_in_phase_s)
        self.assertGreaterEqual(status.time_in_phase_s, int(expected))
        self.assertLessEqual(status.time_in_phase_s,
                             int((after - datetime.fromisoformat(at)).total_seconds()) + 1)

    def test_time_in_phase_from_state_log(self) -> None:
        make_project(self.root)  # STATE_FULL: phase build, log line 2026-09-01 — build — started
        status = self._probe()
        expected = (datetime.now(timezone.utc)
                    - datetime(2026, 9, 1, tzinfo=timezone.utc)).total_seconds()
        self.assertIsNotNone(status.time_in_phase_s)
        self.assertAlmostEqual(status.time_in_phase_s, expected, delta=5)

    def test_time_in_phase_null_without_evidence(self) -> None:
        make_project(self.root, state=STATE_LEGACY, with_next=False)  # phase define, no log
        status = self._probe()
        self.assertIsNone(status.time_in_phase_s)


class ProbeNewFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "demo"
        self.history = Path(self.tmp.name) / "history.jsonl"

    def _probe(self, **kwargs):
        with mock.patch.dict(os.environ, {"GSD_DAEMON_HISTORY": str(self.history)}):
            return probe.probe_project(self.root, **kwargs)

    def test_missing_sources_yield_null_or_empty(self) -> None:
        make_project(self.root)
        status = self._probe()
        self.assertEqual(status.reviews, [])
        self.assertIsNone(status.criteria)
        self.assertEqual(status.ledger, [])
        self.assertEqual(status.answers, [])
        self.assertIsNone(status.usage)
        for milestone in status.roadmap_milestones:
            self.assertIn("duration_s", milestone)
            self.assertIn("tokens", milestone)
            self.assertIn("archive", milestone)

    def test_full_probe_with_new_sources(self) -> None:
        make_project(self.root)
        project_dir = self.root / ".project"
        review_dir = project_dir / "review"
        review_dir.mkdir()
        (review_dir / "wave-1.cycle1.md").write_bytes(WAVE_REVIEW.encode("utf-8"))
        (review_dir / "FINAL.md").write_bytes(FINAL_REVIEW.encode("utf-8"))
        build_dir = project_dir / "build"
        build_dir.mkdir()
        (build_dir / "verify-ledger.jsonl").write_bytes(
            (json.dumps({"command": "make test", "commit": "abc1234", "result": "pass",
                        "recorded_at": "2026-09-11T12:00:00+00:00"}) + "\n").encode("utf-8"),
        )
        (build_dir / "usage.jsonl").write_bytes(
            (json.dumps({"task": "T001", "model": "kimi-k2", "family": "kimi",
                        "tokens_in": 100, "tokens_out": 50, "cost": 0.01,
                        "phase": "build"}) + "\n").encode("utf-8"),
        )
        discuss_dir = project_dir / "discuss"
        discuss_dir.mkdir()
        (discuss_dir / "ANSWERS.md").write_bytes(ANSWERS_MD.encode("utf-8"))
        status = self._probe()
        self.assertEqual(len(status.reviews), 2)
        self.assertEqual(len(status.criteria), 2)
        self.assertEqual(status.ledger[0]["command"], "make test")
        self.assertEqual([item["id"] for item in status.answers], ["A001", "A003"])
        self.assertEqual(status.usage["tokens_in"], 100)
        data = status.to_dict()
        for key in ("reviews", "criteria", "ledger", "answers", "time_in_phase_s", "usage"):
            self.assertIn(key, data)
        restored = ProjectStatus.from_dict(json.loads(json.dumps(data, sort_keys=True)))
        self.assertEqual(restored.to_dict(), data)


if __name__ == "__main__":
    unittest.main()


class AttentionContextTests(unittest.TestCase):
    def test_runtime_answer_uses_merged_question(self):
        status = ProjectStatus(root="/sample", pending_answers=[{"answer": "A012"}],
                               answers=[{"id": "A012", "question": "Which API?"}])
        self.assertEqual(probe.compute_attention(status)[0],
                         {"kind": "question", "label": "Which API?", "ref": "A012"})
