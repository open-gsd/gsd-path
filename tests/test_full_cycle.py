"""Full-cycle disk contract: one milestone from define through ship and
integration, where every phase's artifacts are produced by the test the way an
agent would write them, and every gate script the contracts mandate is run
against the previous phase's output, in order, through the real CLIs and git
hooks.

Closes trust gaps G2 (router/state), G3 (phase SOP composition), and most of
G4 (build helper orchestration) from docs/trust-validation/TRUST-VALIDATION-SPEC.md
without an AI host. Live child-spawn (G5/G6) is covered by tests/dogfood.py.
"""

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
- SC1 — `render("x")` returns a greeting.

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

## Finding: domain finding

- **Claim**: Greetings are plain strings.
- **Source**: https://example.test/domain
- **Confidence**: high
- **Why it matters here**: It settles the render contract.
"""

SYNTHESIS = """# Synthesis

## Settled
- Greetings are plain strings.

## Decisions
- **Decision**: render returns `Hello, <name>`.
- **Runner-up**: none
- **Evidence**: evidence-domain.md
- **Confidence**: high

## For the planner
- Wave 1: implement render.

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

- Return `Hello, <name>` from render.

## Interface contract

None

## Intent coverage

- SC1 — `render("x")` returns a greeting.

## Acceptance criteria

1. `render("x")` returns `Hello, x`.

## Verify

```bash
python3 tests/test_app.py
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
"""

FINAL = """# Final Review — demo

Reviewed HEAD: {head}
Overall verdict: pass

## Success criteria

### SC1 — render works

- **Verdict**: met
- **Check**: `python3 tests/test_app.py`
- **Observed**: focused tests passed
- **Reference**: tests/test_app.py
- **Finding**: none
- **Fix direction**: none
"""

GAP = """# Gap Review — 1: project verify

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

    def write_manifest(self, archive):
        contents = sorted(
            p.relative_to(archive).as_posix() for p in archive.rglob("*") if p.is_file() and p.name != "MANIFEST.md"
        )
        listing = "\n".join(f"- {p}" for p in contents)
        (archive / "MANIFEST.md").write_text(
            f"""# Archive — {archive.name}

Milestone: {SLUG}
Shipped: {TODAY}
Final verdict: all criteria met; project verify passed
Waves: 1  Tasks: 1 done / 1 total  Review cycles used: 1
Carried forward: none

## Success criteria at ship

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
| render works | met | tests/test_app.py |

## Contents

{listing}

## Notes

- none
""",
            encoding="utf-8",
        )

    def install_hooks(self):
        result = subprocess.run(
            ["node", str(SCRIPTS / "install.mjs"), "--claude", "--local", "--project", str(self.repo), "--hooks", "--no-color"],
            cwd=self.repo, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_define_to_integrated_ship(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.repo = Path(temporary) / "repo"
            repo.mkdir()
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.email", "cycle@example.invalid")
            git(repo, "config", "user.name", "Cycle")

            # --- router init (greenfield → define) + guard hooks on a bound branch
            self.write("src/app.py", "def render(name):\n    return name\n")
            self.write("tests/test_app.py", "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))\nfrom src.app import render\nassert render('x') == 'Hello, x'\n")
            self.write("src/__init__.py", "")
            self.state("define", "active")
            self.install_hooks()
            baseline = self.commit("router: initialize project")
            git(repo, "update-ref", "refs/remotes/origin/main", baseline)
            git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
            self.assertEqual(git(repo, "checkout", "-q", "-b", BRANCH).returncode, 0)
            self.assertEqual(self.gate("discussion_records.py", "pending", "--repo", str(repo))["pending"], [])

            # --- define
            self.write(".project/intent/INTENT.md", INTENT)
            self.state("define", "done")
            self.commit("define: intent")

            # --- research → handoff gate
            self.write(".project/research/RESEARCH.md", RESEARCH)
            self.write(".project/research/evidence-domain.md", EVIDENCE)
            self.state("research", "done")
            handoff = self.gate("check_handoffs.py", "research", "--repo", str(repo))
            self.assertEqual(handoff["dispatched"], ["domain"])
            self.commit("research: handoff")

            # --- decide
            self.write(".project/research/SYNTHESIS.md", SYNTHESIS)
            self.state("decide", "done")
            self.commit("decide: synthesis")

            # --- plan → task brief gate against the layer base
            self.write(".project/plan/PLAN.md", PLAN)
            self.write(".project/tasks/T001-demo.md", TASK.format(today=TODAY))
            self.state("plan", "done")
            base = self.commit("plan: wave 1")
            briefs = self.gate("check_task_briefs.py", "--repo", str(repo), "--base", base)
            self.assertEqual(briefs["tasks"], 1)

            # --- build: isolate → implement → land → retire, then wave review
            self.state("build", "active")
            base = self.commit("build: start")
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
            verify = subprocess.run([sys.executable, "tests/test_app.py"], cwd=repo, capture_output=True, text=True)
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.write(".project/review/wave-1.cycle1.md", WAVE_REVIEW)
            self.state("build", "done")
            self.commit("build: wave 1 reviewed")

            # --- ship: final review at reviewed HEAD, archive transaction, ship commit via hooks
            self.state("ship", "active")
            reviewed = self.commit("ship: start final review")
            self.write(".project/review/FINAL.md", FINAL.format(head=reviewed))
            self.write(".project/review/final-gap-1.md", GAP.format(head=reviewed))
            prepared = self.gate("archive_milestone.py", "prepare", "--repo", str(repo), "--slug", SLUG)
            archive = repo / prepared["archive"]
            self.assertTrue(archive.is_dir())
            self.write_manifest(archive)
            self.gate("archive_milestone.py", "preflight", "--repo", str(repo))
            self.state("shipped", "done", archive=prepared["archive"])
            git(repo, "add", "-A")
            ship = git(repo, "commit", "-q", "-m", f"ship: M001 — {SLUG}", "-m",
                       f"Archive: {prepared['archive']}\nReviewed-HEAD: {reviewed}")
            self.assertEqual(ship.returncode, 0, ship.stderr)
            ship_sha = git(repo, "rev-parse", "HEAD").stdout.strip()
            self.gate("archive_milestone.py", "validate", "--repo", str(repo))
            self.assertFalse((repo / ".project" / "plan").exists(), "ship moves plan into the archive")

            # --- integrate onto main, tag, publish origin refs → validate-integrated
            git(repo, "checkout", "-q", "--detach", "refs/remotes/origin/main")
            merge = git(repo, "merge", "--no-ff", "-m", f"integrate: M001 — merge {BRANCH} into main", "-m",
                        f"Archive: {prepared['archive']}\nShip: {ship_sha}\nDefault: main\nBranch: {BRANCH}", ship_sha)
            self.assertEqual(merge.returncode, 0, merge.stderr)
            merge_sha = git(repo, "rev-parse", "HEAD").stdout.strip()
            git(repo, "checkout", "-q", BRANCH)
            git(repo, "tag", "-a", "-m", "milestone", f"milestone/{archive.name}", merge_sha)
            git(repo, "update-ref", "refs/remotes/origin/main", merge_sha)
            git(repo, "update-ref", f"refs/remotes/origin/{BRANCH}", ship_sha)
            tag_obj = git(repo, "rev-parse", f"refs/tags/milestone/{archive.name}").stdout.strip()
            git(repo, "update-ref", f"refs/remotes/origin/tags/milestone/{archive.name}", tag_obj)
            integrated = self.gate("archive_milestone.py", "validate-integrated", "--repo", str(repo), "--slug", SLUG)
            self.assertEqual(integrated["integrate"], merge_sha)
            self.assertEqual(integrated["commit"], ship_sha)

            # --- next milestone binds at integrated main and retires the old branch
            bound = self.gate(
                "pipeline_git.py", "bind-next", "--repo", str(repo), "--branch", "gsd-path/M002",
                "--previous-branch", BRANCH, "--ship", ship_sha, "--remote-default", "origin/main", "--base", merge_sha,
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
