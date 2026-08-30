"""Full-cycle disk contract: one milestone from define through ship and
integration, where every phase's artifacts are produced by the test the way an
agent would write them, and every gate script the contracts mandate is run
against the previous phase's output, in order, through the real CLIs and git
hooks.

Closes trust gaps G2 (router/state), G3 (phase SOP composition), and most of
G4 (build helper orchestration) from docs/trust-validation/TRUST-VALIDATION-SPEC.md
without an AI host. Live child-spawn (G5/G6) is covered by tests/dogfood.py.
"""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import isolation

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TODAY = "2026-08-21"
BRANCH = "gsd-path/M001"
SLUG = "demo"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)


def script(name, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args], cwd=ROOT, text=True, capture_output=True, check=False
    )


STATE = """---
pipeline: gsd-path/v2
project: {slug}
milestone: {slug}
phase: {phase}
status: {status}
branch: {branch}
archive: {archive}
---

# Project State

## Log
- {today} — {phase} — {status}
"""

INTENT = """# Intent — demo

Lane: standard
Review panel: off

## Summary
Add a greeting renderer.

## Success criteria
1. `render("x")` returns a greeting.

## Scope: in
- src/app.py

## Scope: out (vetoes)
- none

## Constraints
- none

## Risks
- none

## Open questions
- [RESEARCH] Which domain applies?

## Corrections
- none
"""

RESEARCH = """# Research Handoff

Phase: research
Status: complete
Intent: `.project/intent/INTENT.md`

## Dispatch
- `domain` — dispatched → `.project/research/evidence-domain.md` — assigned question
- `stack` — skipped → none — intent settles the stack
- `pitfalls` — skipped → none — no risk was assigned
- `similar` — skipped → none — no comparison is needed

## Question assignments
- `[RESEARCH] Which domain applies?` → `domain`
"""

EVIDENCE = """# Evidence — domain

Dimension: domain
Questions assigned: Which domain applies?

## Finding: domain finding

- **Claim**: Greetings are plain strings.
- **Source**: https://example.test/domain
- **Confidence**: high
- **Why it matters here**: It settles the render contract.

## Assigned questions — answers

- Which domain applies? → Greetings are plain strings; source: https://example.test/domain

## Dead ends

- none
"""

SYNTHESIS = """# Synthesis

## Settled
- Greetings are plain strings.

## Decisions

### Greeting format

- **Decision**: render returns a greeting with the supplied name.
- **Runner-up**: Return the supplied name unchanged.
- **Evidence**: `.project/research/evidence-domain.md`
- **Confidence**: high — the research settles the return type.

## For the planner

- **Wave-1 blockers**: No blockers remain after research.
- **Walking skeleton**: One task implements and verifies the renderer.
- **Pitfalls → tasks**: T001 owns the renderer and its focused test.

## User rulings
- none

## Still unknown
- none
"""

PLAN = """# Plan

Project verify: `python3 tests/test_app.py`

## Config
- max_review_cycles: 2
- review_panel: off

## Wave 1 — demo

Goal: implement render
Review depth: full

## Intent coverage

| Criterion | Task | Acceptance |
|-----------|------|------------|
| SC1 | T001 | AC1 |

## Dependency notes
- none
"""

TASK = """---
id: T001
title: render greeting
wave: 1
deps: []
status: pending
agent: null
base: null
worktree: null
task_branch: null
files:
  - src/app.py
  - tests/test_app.py
---

# T001 — render greeting

## Context

The task changes `src/app.py` and `tests/test_app.py`.

## Approach

- Prefix the supplied name with `Hello, `.

## Interface contract

None

## Intent coverage

- SC1

## Acceptance criteria

1. `render("x")` returns `Hello, x`.

## Verify

```bash
python3 tests/test_app.py && python3 -m py_compile src/app.py
```

## Log

- {today} — created by planner
"""

WAVE_REVIEW = """# Review — wave 1, cycle 1

Wave verdict: pass
Cycle: 1
Depth: full
Tasks reviewed: 1

## T001 — render greeting: pass

- ✅ render works — focused Verify passed

## Intent coverage

### SC1 — `render("x")` returns a greeting.: pass

- ✅ Project verification exercised the implemented renderer.
"""

FINAL = """# Final Review — demo

Reviewed HEAD: {head}
Overall verdict: pass

## Success criteria

### SC1 — `render("x")` returns a greeting.

- **Verdict**: met
- **Check**: `python3 tests/test_app.py`
- **Observed**: focused tests passed
- **Reference**: tests/test_app.py
- **Finding**: none
- **Fix direction**: none
"""

GAP = """# Gap Review — 1: project Verify command

Reviewed HEAD: {head}
Gap verdict: pass
Risk: project Verify command
Waves checked: 1

## Checked evidence

- **Check**: `python3 tests/test_app.py`
- **Observed**: project verification passed.
- **Reference**: `tests/test_app.py`

## Finding

- **Found**: The project Verify command passed at the reviewed HEAD.
- **Fix direction**: none
"""


class FullCycleTests(unittest.TestCase):
    def write(self, relative, content):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def state(self, phase, status, archive="null"):
        self.write(".project/STATE.md", STATE.format(
            slug=SLUG, phase=phase, status=status, branch=BRANCH, archive=archive, today=TODAY
        ))

    def commit(self, message):
        git(self.repo, "add", "-A")
        result = git(self.repo, "commit", "-q", "-m", message)
        self.assertEqual(result.returncode, 0, result.stderr)
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def gate(self, name, *args, expect=0):
        result = script(name, *args)
        self.assertEqual(result.returncode, expect, f"{name} {' '.join(args)}\n{result.stdout}{result.stderr}")
        return json.loads(result.stdout) if result.stdout.strip().startswith("{") else result.stdout

    def transition(
        self,
        event,
        expect_phase,
        expect_status,
        *,
        set_phase=None,
        set_status=None,
        expect_archive="null",
    ):
        arguments = [
            "transition",
            "--repo",
            str(self.repo),
            "--event",
            event,
            "--expect-pipeline",
            "gsd-path/v2",
            "--expect-project",
            SLUG,
            "--expect-milestone",
            SLUG,
            "--expect-phase",
            expect_phase,
            "--expect-status",
            expect_status,
            "--expect-branch",
            BRANCH,
            "--expect-archive",
            expect_archive,
        ]
        if set_phase is not None:
            arguments.extend(("--set-phase", set_phase))
        if set_status is not None:
            arguments.extend(("--set-status", set_status))
        return self.gate("pipeline_state.py", *arguments)

    def install_hooks(self):
        result = subprocess.run(
            ["node", str(SCRIPTS / "install.mjs"), "--claude", "--local", "--project", str(self.repo), "--hooks", "--no-color"],
            cwd=self.repo, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_define_to_integrated_ship(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.repo = Path(temporary) / "repo"
            origin = Path(temporary) / "origin.git"
            repo.mkdir()
            origin.mkdir()
            git(repo, "init", "-q", "-b", "main")
            bare = git(origin, "init", "--bare", "-q", "-b", "main")
            self.assertEqual(bare.returncode, 0, bare.stderr)
            git(repo, "config", "user.email", "cycle@example.invalid")
            git(repo, "config", "user.name", "Cycle")

            # --- router init (greenfield → define) + guard hooks on a bound branch
            self.write("src/app.py", "def render(name):\n    return name\n")
            self.write("tests/test_app.py", "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))\nfrom src.app import render\nassert render('x') == 'Hello, x'\n")
            self.write("src/__init__.py", "")
            self.state("define", "active")
            self.commit("router: initialize project")
            self.install_hooks()
            baseline = self.commit("router: install guard hooks")
            self.assertEqual(git(repo, "remote", "add", "origin", str(origin)).returncode, 0)
            published = git(repo, "push", "-q", "-u", "origin", "main")
            self.assertEqual(published.returncode, 0, published.stderr)
            self.assertEqual(git(repo, "remote", "set-head", "origin", "--auto").returncode, 0)
            bound = self.gate(
                "pipeline_git.py", "bind-initial", "--repo", str(repo), "--branch", BRANCH,
                "--remote-default", "origin/main", "--base", baseline,
            )
            self.assertEqual(bound["status"], "bound")
            self.assertEqual(self.gate("discussion_records.py", "pending", "--repo", str(repo))["pending"], [])

            # --- define
            self.write(".project/intent/INTENT.md", INTENT)
            self.transition("milestone intent approved", "define", "active", set_status="done")
            self.commit("define: intent")

            # --- research → handoff gate
            self.transition(
                "research started",
                "define",
                "done",
                set_phase="research",
                set_status="active",
            )
            self.write(".project/research/RESEARCH.md", RESEARCH)
            self.write(".project/research/evidence-domain.md", EVIDENCE)
            handoff = self.gate("check_handoffs.py", "research", "--repo", str(repo))
            self.assertEqual(handoff["dispatched"], ["domain"])
            self.transition(
                "research handoff validated: .project/research/RESEARCH.md",
                "research",
                "active",
                set_status="done",
            )
            self.commit("research: handoff")

            # --- decide
            self.transition(
                "decision synthesis started",
                "research",
                "done",
                set_phase="decide",
                set_status="active",
            )
            self.write(".project/research/SYNTHESIS.md", SYNTHESIS)
            decide = self.gate("check_handoffs.py", "decide", "--repo", str(repo))
            self.assertEqual(decide["decisions"], ["Greeting format"])
            self.transition(
                "validated synthesis: .project/research/SYNTHESIS.md",
                "decide",
                "active",
                set_status="done",
            )
            self.commit("decide: synthesis")

            # --- plan → intent/task graph gate, then task brief gate against the layer base
            self.transition(
                "planning started",
                "decide",
                "done",
                set_phase="plan",
                set_status="active",
            )
            self.write(".project/plan/PLAN.md", PLAN)
            self.write(".project/tasks/T001-demo.md", TASK.format(today=TODAY))
            plan = self.gate("check_handoffs.py", "plan", "--repo", str(repo))
            self.assertEqual(plan["criteria"], ["SC1"])
            self.assertEqual(plan["rows"], 1)
            plan_head = git(repo, "rev-parse", "HEAD").stdout.strip()
            approval = self.gate(
                "pipeline_state.py",
                "approve",
                "--repo",
                str(repo),
                "--kind",
                "plan",
                "--expected-head",
                plan_head,
            )
            base = approval["commit"]
            briefs = self.gate("check_task_briefs.py", "--repo", str(repo), "--base", base)
            self.assertEqual(briefs["tasks"], 1)

            # --- build: isolate → implement → land → retire, then wave review
            self.transition(
                "build started",
                "plan",
                "done",
                set_phase="build",
                set_status="active",
            )
            build_entry = isolation.checkpoint(
                repo,
                base,
                "build: start",
                "Why: build started",
                [".project"],
            )
            base = build_entry["commit"]
            isolated = isolation.isolate_task(repo, base, "T001", 1)
            self.assertEqual(isolated["mode"], "serial")
            self.write("src/app.py", "def render(name):\n    return f'Hello, {name}'\n")
            dispatched_task = (
                TASK.format(today=TODAY)
                .replace("status: pending", "status: in-progress")
                .replace("agent: null", "agent: cycle-coder")
                .replace("base: null", f"base: {base}")
                .replace("worktree: null", f"worktree: {isolated['worktree']}")
            )
            self.write(".project/tasks/T001-demo.md", dispatched_task)
            landed = isolation.land(
                repo,
                repo,
                base,
                "T001",
                "render greeting",
                ".project/tasks/T001-demo.md",
                ["src/app.py", "tests/test_app.py"],
            )
            self.assertEqual(landed["subject"], "T001: render greeting")
            self.assertEqual(git(repo, "branch", "--show-current").stdout.strip(), BRANCH)
            verify = subprocess.run([sys.executable, "-B", "tests/test_app.py"], cwd=repo, capture_output=True, text=True)
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.write(".project/review/wave-1.cycle1.md", WAVE_REVIEW)
            wave = self.gate(
                "check_handoffs.py", "wave", "--repo", str(repo),
                "--review", ".project/review/wave-1.cycle1.md",
            )
            self.assertEqual(wave["owned"], ["SC1"])
            wave_checkpoint = isolation.checkpoint(
                repo,
                landed["commit"],
                "build: wave 1 reviewed",
                (
                    "Why: wave review passed\n"
                    "Wave: 1\n"
                    "Tasks: T001\n"
                    f"Base: {landed['commit']}"
                ),
                [".project"],
            )
            self.transition(
                "build done; final review pending",
                "build",
                "active",
                set_phase="ship",
                set_status="active",
            )
            ship_entry = isolation.checkpoint(
                repo,
                wave_checkpoint["commit"],
                "build: final review",
                "Why: build done; final review pending",
                [".project"],
            )

            # --- ship: final review at reviewed HEAD, archive transaction, ship commit via hooks
            reviewed = ship_entry["commit"]
            self.write(".project/review/FINAL.md", FINAL.format(head=reviewed))
            first_sidecar = isolation.isolate_verify(repo, reviewed, "review-gap-1")
            first_source = Path(first_sidecar["worktree"])
            self.write(
                first_source / ".project/review/final-gap-1.md",
                GAP.format(head=reviewed).replace("Gap verdict: pass", "Gap verdict: invalid"),
            )
            first_collection = isolation.collect_artifact(
                repo,
                first_source,
                reviewed,
                first_sidecar["branch"],
                ".project/review/final-gap-1.md",
                ".project/review/final-gap-1.md",
            )
            self.assertFalse(first_collection["replaced"])
            isolation.retire(repo, first_source, first_sidecar["branch"], False)
            invalid = script("check_handoffs.py", "final", "--repo", str(repo))
            self.assertNotEqual(invalid.returncode, 0)

            destination = repo / ".project/review/final-gap-1.md"
            expected_destination = hashlib.sha256(destination.read_bytes()).hexdigest()
            retry_sidecar = isolation.isolate_verify(repo, reviewed, "review-gap-1")
            retry_source = Path(retry_sidecar["worktree"])
            self.write(retry_source / ".project/review/final-gap-1.md", GAP.format(head=reviewed))
            retry_collection = isolation.collect_artifact(
                repo,
                retry_source,
                reviewed,
                retry_sidecar["branch"],
                ".project/review/final-gap-1.md",
                ".project/review/final-gap-1.md",
                expected_destination,
            )
            self.assertTrue(retry_collection["replaced"])
            self.assertEqual(retry_collection["previous_sha256"], expected_destination)
            isolation.retire(repo, retry_source, retry_sidecar["branch"], False)
            final = self.gate("check_handoffs.py", "final", "--repo", str(repo))
            self.assertEqual(final["reviewed_head"], reviewed)
            self.assertEqual(final["gaps"], [1])
            prepared = self.gate("archive_milestone.py", "prepare", "--repo", str(repo), "--slug", SLUG)
            archive = repo / prepared["archive"]
            self.assertTrue(archive.is_dir())
            manifest = self.gate("archive_milestone.py", "render-manifest", "--repo", str(repo))
            self.assertEqual(manifest["archive"], prepared["archive"])
            self.assertTrue((archive / "MANIFEST.md").is_file())
            self.gate("archive_milestone.py", "preflight", "--repo", str(repo))
            shipment = self.gate(
                "pipeline_state.py",
                "record-shipment",
                "--repo",
                str(repo),
                "--archive",
                prepared["archive"],
                "--event",
                "archive preflight passed; shipment recorded",
            )
            self.assertEqual(shipment["state"]["phase"], "shipped")
            git(repo, "add", "-A")
            ship = git(repo, "commit", "-q", "-m", f"ship: M001 — {SLUG}", "-m",
                       f"Archive: {prepared['archive']}\nReviewed-HEAD: {reviewed}")
            self.assertEqual(ship.returncode, 0, ship.stderr)
            ship_sha = git(repo, "rev-parse", "HEAD").stdout.strip()
            self.gate("archive_milestone.py", "validate", "--repo", str(repo))
            self.assertFalse((repo / ".project" / "plan").exists(), "ship moves plan into the archive")

            # --- integrate through the named-worktree transaction; a retry converges
            integrated = self.gate(
                "archive_milestone.py", "integrate", "--repo", str(repo), "--slug", SLUG,
            )
            merge_sha = integrated["integrate"]
            self.assertEqual(integrated["commit"], ship_sha)
            self.assertEqual(git(repo, "branch", "--show-current").stdout.strip(), BRANCH)
            retry = self.gate(
                "archive_milestone.py", "integrate", "--repo", str(repo), "--slug", SLUG,
            )
            self.assertEqual(retry, integrated)
            integration_branch = git(
                repo, "show-ref", "--verify", "--quiet", "refs/heads/gsd-path-integrate/M001",
            )
            self.assertNotEqual(integration_branch.returncode, 0)
            worktrees = git(repo, "worktree", "list", "--porcelain")
            self.assertEqual(worktrees.stdout.count("worktree "), 1)

            # --- next milestone binds at integrated main and retires the old branch
            bound = self.gate(
                "pipeline_git.py", "bind-next", "--repo", str(repo), "--branch", "gsd-path/M002",
                "--previous-branch", BRANCH, "--ship", ship_sha, "--remote-default", "origin/main", "--base", merge_sha,
                "--landing", merge_sha,
            )
            self.assertEqual(bound["branch"], "gsd-path/M002")
            self.assertEqual(git(repo, "branch", "--show-current").stdout.strip(), "gsd-path/M002")

            # --- guards hold on shipped history: archive tamper is rejected by pre-commit
            (archive / "MANIFEST.md").write_text("tampered\n", encoding="utf-8")
            git(repo, "add", "-A")
            tamper = git(repo, "commit", "-q", "-m", "tamper")
            self.assertNotEqual(tamper.returncode, 0)
            self.assertIn("read-only", tamper.stderr)
            git(repo, "reset", "-q", "--hard", "HEAD")
            # and a ship-subject commit touching non-project paths is rejected by commit-msg
            self.write("src/extra.py", "x = 1\n")
            git(repo, "add", "-A")
            impure = git(repo, "commit", "-q", "-m", "ship: M002 — impure")
            self.assertNotEqual(impure.returncode, 0)


if __name__ == "__main__":
    unittest.main()
