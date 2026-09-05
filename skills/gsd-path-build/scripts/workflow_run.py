#!/usr/bin/env python3
"""Run canonical workflow helpers with fixed arguments and fail-stop receipts."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


class StepFailed(RuntimeError):
    pass


def run_workflow(repo: Path, action: str, project_dir: str, expected_head: str = None,
                 task_id: str = None, round_size: int = None) -> dict:
    steps = []
    scripts = Path(__file__).resolve().parent

    def step(script, *arguments):
        command = [sys.executable, "-B", str(scripts / script), *arguments]
        completed = subprocess.run(command, cwd=repo, capture_output=True, text=True)
        receipt = {"script": script, "command": command, "exit_code": completed.returncode,
                   "stdout": completed.stdout, "stderr": completed.stderr}
        steps.append(receipt)
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        if completed.returncode:
            raise StepFailed(script)
        try:
            receipt["result"] = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise StepFailed(f"{script} did not return JSON") from error
        return receipt["result"]

    common = ["--repo", str(repo), "--project-dir", project_dir]
    try:
        if action == "route":
            step("pipeline_state.py", "route", *common)
        elif action == "prepare-task":
            task = step("isolation.py", "isolate-task", "--repo", str(repo),
                        "--base", expected_head, "--task-id", task_id,
                        "--round-size", str(round_size))
            if task["mode"] == "serial":
                step("isolation.py", "isolate-verify", "--repo", str(repo),
                     "--base", expected_head, "--name", f"task-{task_id.lower()}-verify")
        elif action == "build-evidence":
            step("build_state.py", "verify-landed", *common, "--head", expected_head)
        else:
            pending = step("discussion_records.py", "pending", "--repo", str(repo))
            if pending["pending"]:
                raise StepFailed("pending discussion requires its owner disposition")
            step("check_handoffs.py", "plan", *common)
            head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"],
                                  cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
            step("check_task_briefs.py", "--repo", str(repo), "--base", head,
                 "--tasks-dir", f"{project_dir}/tasks")
            panel = ["validate-plan", "--plan", str(repo / project_dir / "plan/PLAN.md"),
                     "--intent", str(repo / project_dir / "intent/INTENT.md")]
            charter = repo / ".project/CHARTER.md"
            if charter.exists():
                panel += ["--charter", str(charter)]
            step("review_panel.py", *panel)
            if action == "approve-plan":
                step("pipeline_state.py", "approve", *common, "--kind", "plan",
                     "--expected-head", expected_head)
    except (StepFailed, OSError, subprocess.CalledProcessError) as error:
        return {"status": "blocked", "reason": str(error), "steps": steps,
                "next": "$gsd-path-forensics"}
    return {"status": "complete", "steps": steps}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("route", "gate-plan", "approve-plan", "build-evidence", "prepare-task"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--project-dir", choices=(".project", ".project/next"), default=".project")
    parser.add_argument("--expected-head")
    parser.add_argument("--task-id")
    parser.add_argument("--round-size", type=int)
    arguments = parser.parse_args(argv)
    if arguments.action in {"approve-plan", "build-evidence", "prepare-task"} and not arguments.expected_head:
        parser.error(f"{arguments.action} requires --expected-head")
    if arguments.action == "prepare-task" and (not arguments.task_id or arguments.round_size is None):
        parser.error("prepare-task requires --task-id and --round-size")
    result = run_workflow(arguments.repo.resolve(), arguments.action,
                          arguments.project_dir, arguments.expected_head,
                          arguments.task_id, arguments.round_size)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
