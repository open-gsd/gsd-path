#!/usr/bin/env python3
"""Run canonical workflow helpers with fixed arguments and fail-stop receipts."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from scripts import _common, isolation
except ImportError:  # bundled copy inside a skill's scripts directory
    import _common
    import isolation


class StepFailed(RuntimeError):
    pass


def _table_rows(body):
    """Cells of a Markdown table's data rows (header and separator skipped)."""
    lines = [line.strip() for line in (body or "").splitlines() if line.strip().startswith("|")]
    return [[cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip("|"))] for line in lines[2:]]

INSPECTION_SPECS = (("inspect_codebase", "codebase-mapper", "codebase", "evidence-codebase.md"),
                    ("inspect_docs", "docs-auditor", "docs-audit", "DOCS-AUDIT.md"))


def _task_member(repo: Path, project_dir: str, task_id: str):
    """The `repo:` member a task names, or None for a coordinator task."""
    for path in sorted((repo / project_dir / "tasks").glob(f"{task_id}-*.md")):
        fields, error = isolation.task_frontmatter(path.read_text(encoding="utf-8"))
        if error:
            raise StepFailed(error)
        return fields.get("repo")
    return None


def run_workflow(repo: Path, action: str, project_dir: str, expected_head: str = None,
                 task_id: str = None, round_size: int = None, inspection: Path = None,
                 mapper_reviewed: bool = False, kind: str = None,
                 rerun: bool = False) -> dict:
    steps = []
    outputs = {}
    scripts = Path(__file__).resolve().parent
    helpers = scripts

    def step(script, *arguments, raw=False):
        command = [sys.executable, "-B", str(helpers / script), *arguments]
        completed = subprocess.run(command, cwd=repo, capture_output=True, encoding="utf-8", errors="replace")
        receipt = {"script": script, "command": command, "exit_code": completed.returncode,
                   "stdout": completed.stdout, "stderr": completed.stderr}
        steps.append(receipt)
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        if completed.returncode:
            raise StepFailed(script)
        if raw:
            return completed.stdout
        try:
            receipt["result"] = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise StepFailed(f"{script} did not return JSON") from error
        return receipt["result"]

    common = ["--repo", str(repo), "--project-dir", project_dir]
    next_step = "$gsd-path-forensics"

    def gate_plan():
        if step("discussion_records.py", "pending", "--repo", str(repo))["pending"]:
            raise StepFailed("pending discussion requires its owner disposition")
        step("check_handoffs.py", "plan", *common)
        head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"],
                              cwd=repo, capture_output=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
        step("check_task_briefs.py", "--repo", str(repo), "--base", head,
             "--tasks-dir", f"{project_dir}/tasks", "--project-dir", project_dir)
        panel = ["validate-plan", "--plan", str(repo / project_dir / "plan/PLAN.md"),
                 "--intent", str(repo / project_dir / "intent/INTENT.md")]
        charter = repo / ".project/CHARTER.md"
        if charter.exists():
            panel += ["--charter", str(charter)]
        return step("review_panel.py", *panel)

    try:
        if os.path.lexists(repo / ".gsd-path/runtime.json"):
            resolved = subprocess.run(
                [sys.executable, "-B", str(repo / ".gsd-path/status_runtime.py"),
                 "--repo", str(repo), "--runtime-path"],
                cwd=repo, capture_output=True, encoding="utf-8", errors="replace")
            if resolved.returncode:
                sys.stderr.write(resolved.stderr)
                raise StepFailed(resolved.stderr.strip())
            helpers = Path(resolved.stdout.strip())
        if action == "route":
            step("pipeline_state.py", "route", *common)
        elif action == "prepare-inspect":
            state = step("pipeline_state.py", "validate", *common)["state"]
            if project_dir != ".project" or state["phase"] != "inspect" or state["status"] != "active":
                raise StepFailed("initial inspection requires the active inspect track")
            specs = INSPECTION_SPECS
            if any((repo / project_dir / "research" / spec[3]).exists() or
                   (repo / project_dir / "research" / spec[3]).is_symlink() for spec in specs):
                raise StepFailed("prior inspection evidence requires the re-inspection contract")
            branch = subprocess.run(["git", "branch", "--show-current"], cwd=repo,
                                    capture_output=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
            if branch != state["branch"]:
                raise StepFailed("current branch differs from the recorded inspection branch")
            pending = step("discussion_records.py", "pending", "--repo", str(repo))
            if pending["pending"]:
                raise StepFailed("pending discussion requires its owner disposition")
            inventory = step("check_docs_audit.py", "--repo", str(repo), "--emit-inventory", raw=True)
            resources = scripts.parent
            if not (resources / "references").is_dir():
                resources = resources / "skills/gsd-path"
            for _, role, template, _ in specs:
                for path in (resources / "references" / f"{role}.md", resources / "templates" / f"{template}.md"):
                    if not path.is_file():
                        raise StepFailed(f"missing inspection resource: {path}")
            staging = Path(tempfile.mkdtemp(prefix="gsd-path-inspect-"))
            inventory_file = staging / "inventory.txt"
            inventory_file.write_bytes(inventory.encode("utf-8"))
            assignments = []
            for task_name, role, template, filename in specs:
                isolated = step("isolation.py", "isolate-verify", "--repo", str(repo),
                                "--base", expected_head, "--name", task_name.replace("_", "-"))
                role_path = resources / "references" / f"{role}.md"
                template_path = resources / "templates" / f"{template}.md"
                output = f"{project_dir}/research/{filename}"
                brief_file = staging / f"{task_name}.md"
                brief = (f"Logical task: {task_name}\nRead and follow role: {role_path}\n"
                         f"Template: {template_path}\nRepository and command cwd: {isolated['worktree']}\n"
                         f"Recorded baseline and Audited HEAD: {isolated['base']}\n"
                         f"Write only: {Path(isolated['worktree']) / output}\n"
                         f"Write header Repo root: {repo}\n"
                         "Use only this supplied sidecar for project commands; do not create worktrees.\n"
                         "The parent owns gates, collection, retirement, and phase state.\n"
                         "Exclude .git, node_modules, .project/archive, and installed GSD Path and path skill bundles.\n")
                if task_name == "inspect_docs":
                    brief += ("Alignment mode: false. No prior audit or changed set.\n"
                              "Frozen inventory follows; use it exactly, without rediscovery:\n" + inventory)
                brief_file.write_bytes(brief.encode("utf-8"))
                assignments.append({**isolated, "task_name": task_name, "role": str(role_path),
                                    "template": str(template_path), "output": output,
                                    "brief_file": str(brief_file)})
            receipt_file = staging / "inspection.json"
            outputs["inspection"] = {"repo": str(repo), "base": expected_head,
                                     "inventory_file": str(inventory_file),
                                     "inventory_sha256": hashlib.sha256(inventory_file.read_bytes()).hexdigest(),
                                     "assignments": assignments, "receipt_file": str(receipt_file)}
            _common.atomic_write(receipt_file, json.dumps(outputs["inspection"], sort_keys=True) + "\n")
        elif action == "finish-inspect":
            if not mapper_reviewed or inspection is None or project_dir != ".project":
                raise StepFailed("finish-inspect requires the prepared active track and mapper review")
            prepared = json.loads(inspection.read_text(encoding="utf-8"))
            if prepared["repo"] != str(repo) or prepared["base"] != expected_head:
                raise StepFailed("inspection receipt does not match repository and expected HEAD")
            assignments = {a["task_name"]: a for a in prepared["assignments"]}
            if len(prepared["assignments"]) != len(INSPECTION_SPECS) or set(assignments) != {s[0] for s in INSPECTION_SPECS}:
                raise StepFailed("inspection receipt must name both original assignments")
            for task_name, _, _, filename in INSPECTION_SPECS:
                assignment = assignments[task_name]
                if assignment["base"] != expected_head or assignment["output"] != f".project/research/{filename}":
                    raise StepFailed("inspection assignment changed its baseline or output")
            inventory_file = Path(prepared["inventory_file"])
            if hashlib.sha256(inventory_file.read_bytes()).hexdigest() != prepared["inventory_sha256"]:
                raise StepFailed("frozen inspection inventory changed")
            state = step("pipeline_state.py", "validate", *common)["state"]
            if state["phase"] != "inspect" or state["status"] != "active":
                raise StepFailed("inspection completion requires inspect/active")
            branch = subprocess.run(["git", "branch", "--show-current"], cwd=repo,
                                    capture_output=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
            if state["branch"] != branch:
                raise StepFailed("current branch differs from the recorded inspection branch")
            pending = step("discussion_records.py", "pending", "--repo", str(repo))
            if pending["pending"]:
                raise StepFailed("pending discussion requires its owner disposition")
            docs = assignments["inspect_docs"]
            step("check_docs_audit.py", "--repo", docs["worktree"], "--primary", str(repo),
                 "--audit", docs["output"], "--inventory", str(inventory_file))
            if f"Audited HEAD: {expected_head}" not in (Path(docs["worktree"]) / docs["output"]).read_text(encoding="utf-8").splitlines():
                raise StepFailed("audit does not name the supplied inspection baseline")
            for task_name, _, _, _ in INSPECTION_SPECS:
                assignment = assignments[task_name]
                step("isolation.py", "collect-artifact", "--repo", str(repo),
                     "--source", assignment["worktree"], "--base", expected_head,
                     "--branch", assignment["branch"], "--source-path", assignment["output"],
                     "--destination-path", assignment["output"])
                step("isolation.py", "retire", "--repo", str(repo), "--worktree", assignment["worktree"],
                     "--branch", assignment["branch"])
            expected = [part for key, value in state.items()
                        for part in (f"--expect-{key}", "null" if value is None else str(value))]
            step("pipeline_state.py", "transition", *common, *expected,
                 "--set-phase", "inspect", "--set-status", "done", "--event", "inspection artifacts passed")
        elif action == "lint-round":
            head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"],
                                  cwd=repo, capture_output=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
            step("check_task_briefs.py", "--repo", str(repo), "--base", head,
                 "--tasks-dir", f"{project_dir}/tasks", "--project-dir", project_dir)
            step("check_handoffs.py", "plan", *common)
        elif action == "prepare-task" and _task_member(repo, project_dir, task_id):
            # A member task works in a sidecar of its member; its Verify runs there at finish.
            step("isolation.py", "isolate-member-task", "--repo", str(repo),
                 "--member", _task_member(repo, project_dir, task_id), "--task-id", task_id)
        elif action == "prepare-task":
            task = step("isolation.py", "isolate-task", "--repo", str(repo),
                        "--base", expected_head, "--task-id", task_id,
                        "--round-size", str(round_size))
            if task["mode"] == "serial":
                name = f"task-{task_id.lower()}-verify"
                stale = isolation.sidecar_root(repo, "verify", name)
                if os.path.lexists(stale / ".git"):
                    # An earlier prepare-task left this sidecar. Only one that is proven untouched is replaced.
                    steps.append({"script": "isolation.py", "result": isolation.retire_stale_verify(
                        repo, stale, isolation.verify_branch_name(name))})
                step("isolation.py", "isolate-verify", "--repo", str(repo),
                     "--base", expected_head, "--name", name)
        elif action == "build-evidence":
            proof = step("build_state.py", "verify-landed", *common, "--head", expected_head)
            # The landing proof has one canonical home; lean final-review reuse allows only this path.
            evidence = repo / project_dir / "build" / "evidence.json"
            _common.atomic_write(evidence, json.dumps(proof, indent=2, sort_keys=True) + "\n")
            steps.append({"script": "workflow_run.py", "evidence": str(evidence)})
        elif action == "prepare-final":
            if project_dir != ".project":
                raise StepFailed("final review requires the active milestone")
            pending = step("discussion_records.py", "pending", "--repo", str(repo))
            if pending["pending"]:
                raise StepFailed("pending discussion requires its owner disposition")
            step("build_state.py", "verify-landed", *common, "--head", expected_head)
            rerun_flag = ("--rerun",) if rerun else ()
            step("lean_verification.py", "--repo", str(repo), "--expected-head", expected_head, *rerun_flag)
        elif action == "preauthorize":
            # A block here is not a failure: the gate asks its owner as usual.
            next_step = "ask the owner at this gate"
            if project_dir != ".project" or kind not in {"intent", "plan"}:
                raise StepFailed("pre-approval covers only intent or plan on the active track")
            routed = step("pipeline_state.py", "route", *common)
            if routed["route"].get("action") != "run-phase" or "recovery" in routed:
                raise StepFailed("pre-approval needs an ordinary phase route")
            if step("discussion_records.py", "pending", "--repo", str(repo))["pending"]:
                raise StepFailed("pending discussion requires its owner disposition")
            track = repo / project_dir
            intent = (track / "intent/INTENT.md").read_text(encoding="utf-8")
            lane = re.search(r"(?m)^Lane:\s*(.+)$", intent)
            if not lane or lane.group(1).split("<!--", 1)[0].strip().strip("`") != "quick":
                raise StepFailed("pre-approval covers only the quick lane")
            intent = re.sub(r"(?s)<!--.*?-->", "", intent)
            if re.search(r"(?m)^\s*-\s*\[(RESEARCH|NEEDS-USER)\]", _common.section_body(intent, "Open questions") or ""):
                raise StepFailed("INTENT.md has open RESEARCH or NEEDS-USER questions")
            audit_path = track / "research/DOCS-AUDIT.md"
            if audit_path.exists():
                audit = audit_path.read_text(encoding="utf-8")
                queue = _table_rows(_common.section_body(audit, "Remediation queue"))
                ruled = set()
                for row in _table_rows(_common.section_body(audit, "User rulings")):
                    if len(row) != 4 or row[1] not in {"fix-code", "fix-doc", "accept-drift"}:
                        continue
                    words = row[2].strip().strip('`"').strip()
                    if words and words.casefold() != "none" and not re.fullmatch(r"<[^>]*>", words):
                        ruled.add(row[0])
                if any(len(row) == 6 and row[4] == "NEEDS-USER" and row[0] not in ruled for row in queue):
                    raise StepFailed("DOCS-AUDIT.md has NEEDS-USER rows without a user ruling")
            if kind == "intent":
                # Malformed or incomplete spec-probe tables are not a pre-approvable draft.
                step("check_handoffs.py", "intent", *common)
            if kind == "plan":
                if gate_plan()["mode"] != "off":
                    raise StepFailed("pre-approval requires review_panel off")
                plan = re.sub(r"(?s)<!--.*?-->", "", (track / "plan/PLAN.md").read_text(encoding="utf-8"))
                config = _common.section_body(plan, "Config") or ""
                skeptics = re.search(r"(?m)^[ \t]*-[ \t]*finding_skeptics:[ \t]*(\S+)", config)
                if skeptics and skeptics.group(1) != "off":
                    raise StepFailed("pre-approval requires finding_skeptics off")
                # Quick-lane limit from project policy (gsd-path-plan Quick mode): one wave, at most two tasks.
                if (len(re.findall(r"(?m)^## Wave \d+ — ", plan)) != 1
                        or len(list((track / "tasks").glob("T[0-9][0-9][0-9]-*.md"))) > 2):
                    raise StepFailed("pre-approval requires one wave and at most two tasks")
            step("pipeline_state.py", "pre-approve", "--repo", str(repo), "--use", kind)
        else:
            gate_plan()
            if action == "approve-plan":
                step("pipeline_state.py", "approve", *common, "--kind", "plan",
                     "--expected-head", expected_head)
    except (StepFailed, isolation.IsolationError, OSError, subprocess.CalledProcessError,
            ValueError, KeyError, TypeError) as error:
        return {"status": "blocked", "reason": str(error), "steps": steps,
                "next": next_step}
    return {"status": "complete", "steps": steps, **outputs}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("route", "gate-plan", "approve-plan", "build-evidence", "lint-round", "prepare-task", "prepare-final", "prepare-inspect", "finish-inspect", "preauthorize"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--project-dir", choices=(".project", ".project/next"), default=".project")
    parser.add_argument("--expected-head")
    parser.add_argument("--task-id")
    parser.add_argument("--round-size", type=int)
    parser.add_argument("--inspection", type=Path)
    parser.add_argument("--mapper-reviewed", action="store_true")
    parser.add_argument("--kind", choices=("intent", "plan"))
    parser.add_argument("--rerun", action="store_true",
                        help="prepare-final: re-execute project Verify at the same head after a "
                             "host-caused failure, appending a new ledger entry")
    arguments = parser.parse_args(argv)
    if arguments.action in {"approve-plan", "build-evidence", "prepare-task", "prepare-final", "prepare-inspect", "finish-inspect"} and not arguments.expected_head:
        parser.error(f"{arguments.action} requires --expected-head")
    if arguments.action == "prepare-task" and (not arguments.task_id or arguments.round_size is None):
        parser.error("prepare-task requires --task-id and --round-size")
    if arguments.action == "preauthorize" and not arguments.kind:
        parser.error("preauthorize requires --kind")
    if arguments.rerun and arguments.action != "prepare-final":
        parser.error(f"--rerun applies only to prepare-final, not {arguments.action}")
    result = run_workflow(arguments.repo.resolve(), arguments.action,
                          arguments.project_dir, arguments.expected_head,
                          arguments.task_id, arguments.round_size, arguments.inspection,
                          arguments.mapper_reviewed, arguments.kind, arguments.rerun)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
