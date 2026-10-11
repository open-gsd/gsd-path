"""Two-repo full cycle: a coordinator milestone with one member task, from plan
approval through member landing, cross-repo project Verify, final review,
member close, ship, integration, and next-milestone member retirement.

Every step runs the real CLIs or runtime APIs against temp repos with bare
remotes, with the coordinator guard and member hooks installed, so member
pushes pass the member pre-push authorization checks for real.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import isolation, lean_verification
from tests.test_full_cycle import EVIDENCE, RESEARCH, SYNTHESIS

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TODAY = "2026-09-29"
BRANCH = "gsd-path/M001"
SLUG = "demo"
VERIFY = "test -f ../web/lib.py && python3 -c \"import sys; sys.path.insert(0, '../web'); import lib; assert lib.value == 2\""

STATE = """---
pipeline: gsd-path/v2
project: acme
milestone: {slug}
phase: {phase}
status: {status}
branch: {branch}
archive: {archive}
{default}---

# Project State

## Log
- {today} — {phase} — {status}
"""

INTENT = """# Intent — demo

Lane: standard
Review panel: off
Surfaces: none

## Summary
Raise the member library value.

## Success criteria
1. The web library value is 2.

## Scope: in
- web lib.py

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

PLAN = f"""# Plan

Project verify: `{VERIFY}`

## Config
- max_review_cycles: 2
- review_panel: off

## Wave 1 — demo

Goal: raise the value
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
title: raise value
wave: 1
deps: []
status: pending
agent: null
base: null
worktree: null
task_branch: null
repo: web
files:
  - lib.py
---

# T001 — raise value

## Context

The task changes `lib.py` in the web member.

## Approach

- Set `value` to 2.

## Interface contract

None

## Intent coverage

- SC1

## Acceptance criteria

1. `lib.value` is 2.

## Verify

```bash
python3 -c "import lib; assert lib.value == 2" && python3 -m py_compile lib.py
```

## Log

- {today} — created by planner
"""

WAVE_REVIEW = """# Review — wave 1, cycle 1

Wave verdict: pass
Cycle: 1
Depth: full
Tasks reviewed: 1

## T001 — raise value: pass

- ✅ lib.value is 2 — focused Verify passed

## Intent coverage

### SC1 — The web library value is 2.: pass

- ✅ Project verification exercised the member library.
"""

FINAL = """# Final Review — demo

Reviewed HEAD: {head}
Member reviewed HEAD: web {member}
Overall verdict: pass

## Success criteria

### SC1 — The web library value is 2.

- **Verdict**: met
- **Check**: `python3 -c "import lib"` in the web member
- **Observed**: lib.value is 2
- **Reference**: web lib.py
- **Finding**: none
- **Fix direction**: none
"""


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, encoding="utf-8", errors="replace", capture_output=True, check=False)


def script(name, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / name), *args], cwd=ROOT, encoding="utf-8",
                          errors="replace", capture_output=True, check=False)


class MemberFullCycleTests(unittest.TestCase):
    def write(self, relative, content, root=None):
        path = (root or self.repo) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

    def state(self, phase, status, archive="null"):
        self.write(".project/STATE.md", STATE.format(slug=SLUG, phase=phase, status=status, branch=BRANCH,
                                                     archive=archive, today=TODAY, default=self.default_line))

    def commit(self, message):
        git(self.repo, "add", "-A")
        result = git(self.repo, "commit", "-q", "-m", message)
        self.assertEqual(result.returncode, 0, result.stderr)
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def gate(self, name, *args, expect=0):
        result = script(name, *args)
        self.assertEqual(result.returncode, expect, f"{name} {' '.join(args)}\n{result.stdout}{result.stderr}")
        return json.loads(result.stdout) if result.stdout.strip().startswith("{") else result.stdout

    def transition(self, event, expect_phase, expect_status, *, set_phase=None, set_status=None):
        arguments = ["transition", "--repo", str(self.repo), "--event", event, "--expect-pipeline", "gsd-path/v2",
                     "--expect-project", "acme", "--expect-milestone", SLUG, "--expect-phase", expect_phase,
                     "--expect-status", expect_status, "--expect-branch", BRANCH, "--expect-archive", "null"]
        if set_phase is not None:
            arguments.extend(("--set-phase", set_phase))
        if set_status is not None:
            arguments.extend(("--set-status", set_status))
        return self.gate("pipeline_state.py", *arguments)

    def test_two_repo_milestone_from_plan_to_member_retirement(self):
        self.cycle()

    def test_two_repo_milestone_with_a_master_member_and_a_trunk_coordinator(self):
        self.cycle(member_default="master", coordinator_default="trunk")

    def cycle(self, member_default="main", coordinator_default="main"):
        # A STATE file without default_branch means main, as in a project from before the field.
        self.default_line = "" if coordinator_default == "main" else f"default_branch: {coordinator_default}\n"
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            environment = mock.patch.dict(os.environ, {
                "GSD_PATH_WORKTREE_ROOT": str(base / "workspace"),
                "GIT_AUTHOR_NAME": "Cycle", "GIT_AUTHOR_EMAIL": "cycle@example.invalid",
                "GIT_COMMITTER_NAME": "Cycle", "GIT_COMMITTER_EMAIL": "cycle@example.invalid"})
            environment.start()
            self.addCleanup(environment.stop)
            repo = self.repo = base / "acme"
            member = base / "web"
            origin = base / "acme-origin.git"
            member_origin = base / "web-origin.git"
            for bare, default in ((origin, coordinator_default), (member_origin, member_default)):
                self.assertEqual(git(base, "init", "--bare", "-q", "-b", default, str(bare)).returncode, 0)

            # --- member: an existing GitHub repo (rewritten to a local bare remote)
            git(base, "init", "-q", "-b", member_default, str(member))
            self.write("lib.py", "value = 1\n", member)
            git(member, "add", "-A")
            git(member, "commit", "-q", "-m", "web: existing library")
            git(member, "remote", "add", "origin", "https://github.com/acme/web.git")
            self.assertEqual(git(member, "push", "-q", str(member_origin), member_default).returncode, 0)
            git(member, "fetch", "-q", str(member_origin),
                f"{member_default}:refs/remotes/origin/{member_default}")
            git(member, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{member_default}")

            # --- coordinator with guard hooks, planning a member task
            git(base, "init", "-q", "-b", coordinator_default, str(repo))
            self.write("README.md", "acme program\n")
            self.commit("fixture: coordinator")
            hooks = subprocess.run(["node", str(SCRIPTS / "install.mjs"), "--claude", "--local", "--project",
                                    str(repo), "--hooks", "--no-color"], cwd=repo, capture_output=True, text=True)
            self.assertEqual(hooks.returncode, 0, hooks.stdout + hooks.stderr)
            self.commit("router: install guard hooks")
            git(repo, "remote", "add", "origin", str(origin))
            self.assertEqual(git(repo, "push", "-q", "-u", "origin", coordinator_default).returncode, 0)
            git(repo, "remote", "set-head", "origin", "--auto")
            git(repo, "switch", "-q", "-c", BRANCH)
            self.state("plan", "active")
            self.write(".project/intent/INTENT.md", INTENT)
            self.write(".project/research/RESEARCH.md", RESEARCH)
            self.write(".project/research/evidence-domain.md", EVIDENCE)
            self.write(".project/research/SYNTHESIS.md", SYNTHESIS)
            self.commit("define: intent, research, and synthesis")
            self.gate("members.py", "add", "--repo", str(repo), "--name", "web", "--checkout", str(member))
            installed = subprocess.run([sys.executable, str(SCRIPTS / "install.py"), "--member-of", str(repo),
                                        "--project", str(member)], capture_output=True, text=True)
            self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
            self.write(".project/plan/PLAN.md", PLAN)
            self.write(".project/tasks/T001-raise.md", TASK.format(today=TODAY))
            self.gate("check_handoffs.py", "plan", "--repo", str(repo))
            plan_head = self.commit("plan: draft")
            approval = self.gate("pipeline_state.py", "approve", "--repo", str(repo), "--kind", "plan",
                                 "--expected-head", plan_head)

            # --- build: the start locks the member and creates its bound branch
            self.transition("build started", "plan", "done", set_phase="build", set_status="active")
            self.assertTrue((repo / ".project/build/members.json").is_file())
            start = isolation.checkpoint(repo, approval["commit"], "build: start", "Why: build started", [".project"])
            coordinator_base = start["commit"]
            isolated = isolation.isolate_member_task(repo, "web", "T001")
            bound_checkout = Path(isolation.member_bound_checkout(repo, "web")["checkout"])
            isolation.activate_member_task(repo, "web", "T001", "cycle-coder", ".project/tasks/T001-raise.md",
                                           coordinator_base)
            self.write("lib.py", "value = 2\n", Path(isolated["worktree"]))
            landed = isolation.land_member(repo, "web", "T001", "raise value", ".project/tasks/T001-raise.md",
                                           coordinator_base, isolated["member_base"])
            isolation.retire_member_task(repo, "web", "T001")
            member_tip = git(member, "rev-parse", "refs/heads/gsd-path/acme-M001").stdout.strip()
            self.assertEqual(member_tip, landed["landing"])
            self.write(".project/review/wave-1.cycle1.md", WAVE_REVIEW)
            self.gate("check_handoffs.py", "wave", "--repo", str(repo), "--review", ".project/review/wave-1.cycle1.md")
            wave = isolation.checkpoint(repo, landed["commit"], "build: wave 1 reviewed",
                                        f"Why: wave review passed\nWave: 1\nTasks: T001\nBase: {landed['commit']}",
                                        [".project"])
            self.transition("build done; final review pending", "build", "active", set_phase="ship",
                            set_status="active")
            reviewed = isolation.checkpoint(repo, wave["commit"], "build: final review",
                                            "Why: build done; final review pending", [".project"])["commit"]

            # --- ship: project Verify sees ../web, final review binds the member head
            verified = lean_verification.verify_project(repo, reviewed)
            self.assertTrue(verified["passed"], verified["execution"])
            self.assertEqual(verified["execution"]["members"], {"web": member_tip})
            self.write(".project/review/FINAL.md", FINAL.format(head=reviewed, member=member_tip))
            self.gate("check_handoffs.py", "final", "--repo", str(repo))
            prepared = self.gate("archive_milestone.py", "prepare", "--repo", str(repo), "--slug", SLUG)
            self.gate("archive_milestone.py", "render-manifest", "--repo", str(repo))
            self.gate("archive_milestone.py", "preflight", "--repo", str(repo))
            # The member keeps its GitHub origin; from here Git talks to a local bare remote.
            git(member, "config", f"url.{member_origin}.insteadOf", "https://github.com/acme/web.git")
            bound_ref = "refs/heads/gsd-path/acme-M001"
            denied_push = git(member, "push", "-q", "origin", f"{bound_ref}:{bound_ref}")
            self.assertNotEqual(denied_push.returncode, 0)
            self.assertIn("not authorized by acme", denied_push.stderr)
            self.assertNotEqual(git(member_origin, "show-ref", "--verify", "--quiet", bound_ref).returncode, 0)
            closed = self.gate("archive_milestone.py", "close-members", "--repo", str(repo))
            self.assertEqual(closed["status"], "integrated")
            merge = closed["members"][0]["merge"]
            self.assertEqual(git(member_origin, "rev-list", "--parents", "-n", "1", member_default).stdout.split()[1:],
                             [git(member_origin, "rev-parse", f"{member_default}~1").stdout.strip(), member_tip])
            self.assertEqual(git(member_origin, "log", "-1", "--format=%s", member_default).stdout.strip(),
                             f"integrate: acme M001 — merge gsd-path/acme-M001 into {member_default}")
            self.gate("pipeline_state.py", "record-shipment", "--repo", str(repo), "--archive", prepared["archive"],
                      "--event", "archive preflight passed; shipment recorded")
            git(repo, "add", "-A")
            ship = git(repo, "commit", "-q", "-m", f"ship: M001 — {SLUG}", "-m", closed["body"].rstrip("\n"))
            self.assertEqual(ship.returncode, 0, ship.stderr)
            ship_sha = git(repo, "rev-parse", "HEAD").stdout.strip()
            shipped = self.gate("archive_milestone.py", "validate", "--repo", str(repo))
            self.assertEqual(shipped["members"][0]["merge"], merge)

            # --- integrate the coordinator; validation covers the member
            integrated = self.gate("archive_milestone.py", "integrate", "--repo", str(repo), "--slug", SLUG)
            self.assertEqual(integrated["members"][0]["merge"], merge)

            # --- next milestone retires the member bound branch everywhere
            denied_delete = git(member, "push", "-q", "origin", f":{bound_ref}")
            self.assertNotEqual(denied_delete.returncode, 0)
            self.assertIn("deletion is not authorized by acme", denied_delete.stderr)
            self.assertEqual(git(member_origin, "rev-parse", "--verify", "--quiet", bound_ref).stdout.strip(),
                             member_tip)
            self.gate("pipeline_git.py", "bind-next", "--repo", str(repo), "--branch", "gsd-path/M002",
                      "--previous-branch", BRANCH, "--ship", ship_sha,
                      "--remote-default", f"origin/{coordinator_default}",
                      "--base", integrated["integrate"], "--landing", integrated["integrate"])
            self.assertEqual(git(member_origin, "rev-parse", "--verify", "--quiet",
                                 "refs/heads/gsd-path/acme-M001").stdout, "")
            self.assertNotEqual(git(member, "show-ref", "--verify", "--quiet", bound_ref).returncode, 0)
            self.assertFalse(bound_checkout.exists())
            worktrees = git(member, "worktree", "list", "--porcelain").stdout.splitlines()
            self.assertNotIn(f"worktree {bound_checkout}", worktrees)
            self.assertEqual(git(member, "for-each-ref", "refs/gsd-path/authorizations/").stdout, "")
            self.assertEqual(git(member_origin, "rev-parse", member_default).stdout.strip(), merge)
            self.assertEqual(git(origin, "rev-parse", coordinator_default).stdout.strip(), integrated["integrate"])
            others = {"main", "master", "trunk"} - {member_default}
            self.assertEqual([name for name in others
                              if git(member_origin, "show-ref", "--verify", "--quiet", f"refs/heads/{name}").returncode == 0], [])
            self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", git(member_origin, "rev-parse",
                                                              "refs/tags/milestone/acme-001-demo").stdout.strip()))


if __name__ == "__main__":
    unittest.main()
