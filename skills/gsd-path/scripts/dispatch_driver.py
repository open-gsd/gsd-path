#!/usr/bin/env python3
"""Deterministic dispatch driver for one build wave.

Composes the canonical helpers in the build contract's order: recover, ready,
brief lint, task isolation, child dispatch, Verify, landing, verify ledger,
retire. Every action re-derives its state from Git, the task files, and the
dispatch records under the Git common directory, so a call may be repeated
after a crash or a tool timeout. The driver never edits task frontmatter,
commits, or creates a checkout itself: isolation.py and build_state.py own
those. Children are spawned through an owner-supplied command that reads the
brief on stdin; the owner therefore owns the child's permission posture.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Callable, Dict, List, Optional

try:
    from scripts import _common, build_state, isolation, review_findings, review_panel, workflow_run
    from scripts import check_handoffs as contracts
except ImportError:  # bundled copy inside a skill's scripts directory
    import _common
    import build_state
    import check_handoffs as contracts
    import isolation
    import review_findings
    import review_panel
    import workflow_run

if os.name == "nt":
    import msvcrt
else:
    import fcntl

RESULT_LINE = re.compile(r"(?im)^RESULT:\s*(?P<task>\S+)\s+(?P<verdict>ready|blocked)\s*$")
QUESTION_MARK = "NEEDS-ORCHESTRATOR:"
ANSWER_MARK = "Orchestrator answer:"
OUTPUT_TAIL_LINES = 20
POLL_SECONDS = 1  # ponytail: fixed poll cadence; make it an owner value if it ever matters


class DriverStop(RuntimeError):
    """A typed stop: the receipt carries the reason; the parent decides."""

    def __init__(self, reason: str, **details: object) -> None:
        super().__init__(reason)
        self.details = details


STOP_ERRORS = (DriverStop, isolation.IsolationError, build_state.BuildStateError,
               contracts.HandoffError, review_findings.ReviewFindingsError)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tail(text: str) -> str:
    return "\n".join(text.splitlines()[-OUTPUT_TAIL_LINES:])


# --- dispatch records ------------------------------------------------------


def milestone_slug(primary: Path) -> str:
    """The bound branch as a path segment; every record and ledger is scoped to one milestone."""
    return isolation.require_bound(primary).replace("/", "-")


def records_root(primary: Path) -> Path:
    return isolation.common_git_dir(primary) / "gsd-path" / "dispatch" / milestone_slug(primary)


def budget_ledger(primary: Path) -> Path:
    return isolation.common_git_dir(primary) / "gsd-path" / "budget" / f"{milestone_slug(primary)}.json"


def attempts_used(root: Path, task_id: str) -> int:
    """Dispatches of this task in this milestone, excluding question redispatches."""
    return sum(1 for path in (root / task_id).glob("attempt-*/state.json")
               if load_state(path).get("origin") == "dispatch")


def acquire_lock(primary: Path) -> BinaryIO:
    root = records_root(primary)
    root.mkdir(parents=True, exist_ok=True)
    handle = open(root / "driver.lock", "a+b")
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        handle.close()
        if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            raise DriverStop("another dispatch_driver invocation holds the lock") from error
        raise
    return handle


def attempt_number(path: Path) -> int:
    return int(path.name.split("-")[1])


def load_state(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: Dict[str, object]) -> None:
    _common.atomic_write(path, json.dumps(state, indent=2, sort_keys=True) + "\n")


def update_state(state: Dict[str, object], **changes: object) -> None:
    path = Path(str(state["_path"]))
    save_state(path, dict(load_state(path), **changes))
    state.update(changes)


def latest_states(root: Path) -> List[Dict[str, object]]:
    """The newest attempt record of every task, in task-id order."""
    states = []
    if root.is_dir():
        for task_dir in sorted(root.iterdir()):
            attempts = sorted(task_dir.glob("attempt-*/state.json"),
                              key=lambda path: attempt_number(path.parent))
            if attempts:
                state = dict(load_state(attempts[-1]), _path=str(attempts[-1]))
                exit_path = attempts[-1].with_name("exit.json")
                if exit_path.is_file():
                    state.update(load_state(exit_path))
                states.append(state)
    return states


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


# --- child process ---------------------------------------------------------


def final_message(stdout: str) -> str:
    """The child's final text from Claude JSON, Codex JSONL, or plain text."""
    try:
        document = json.loads(stdout)
        if isinstance(document, dict):
            return str(document.get("result", ""))
    except json.JSONDecodeError:
        pass
    text = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if isinstance(item, dict) and event.get("type") == "item.completed" \
                and item.get("type") == "agent_message":
            text = str(item.get("text", ""))
    return stdout if text is None else text


def child_main(state_path: Path) -> int:
    """Run the owner's child command under the isolate; record its exit in a separate receipt."""
    state = load_state(state_path)
    attempt_dir = state_path.parent
    with open(attempt_dir / "brief.md", "rb") as brief, \
            open(attempt_dir / "stdout", "wb") as out, open(attempt_dir / "stderr", "wb") as err:
        process = subprocess.Popen(state["command"], cwd=state["worktree"], stdin=brief,
                                   stdout=out, stderr=err, start_new_session=True)
        try:
            exit_code: Optional[int] = process.wait(timeout=state.get("child_timeout"))
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            exit_code, timed_out = None, True
    save_state(attempt_dir / "exit.json",
               dict(finished_at=now(), exit_code=exit_code, timed_out=timed_out))
    return 0


def brief_text(state: Dict[str, object], role_brief: Path, task_template: Path) -> str:
    worktree = Path(str(state["worktree"]))
    task_id = state["task_id"]
    agents = worktree / "AGENTS.md"
    workflow = worktree / "WORKFLOW.md"
    lines = [
        f"You are the coder for GSD Path task {task_id}.",
        f"Read the coder role brief first and follow it exactly, including its terminal "
        f"`RESULT: {task_id} ready|blocked` line: {role_brief}",
        f"Work only in this worktree root: {worktree}",
        f"Task file: {worktree / str(state['task_file'])}",
        f"Task template: {task_template}",
        f"INTENT.md: {worktree / '.project/intent/INTENT.md'}",
        f"AGENTS.md: {agents if agents.exists() else 'absent'}",
        f"WORKFLOW.md: {workflow if workflow.exists() else 'absent'}",
        f"Recorded base: {state['base']}",
        f"Dispatch mode: {state['mode']} ("
        + ("the primary worktree on the bound branch" if state["mode"] == "serial"
           else "an isolated task worktree; never touch the primary") + ").",
        "Next consumer: the build orchestrator reruns Verify in an isolated checkout and lands "
        "the task. Gate: Verify passes and only the task's declared files plus its Log changed.",
        "Never delegate to another agent. Never stage, commit, or otherwise mutate Git.",
    ]
    if state.get("answered"):
        lines.append(f"The task Log now records an `{ANSWER_MARK}` to your earlier question; "
                     "continue from it.")
    return "\n".join(lines) + "\n"


def spawn(root: Path, state: Dict[str, object], options: argparse.Namespace,
          brief: Callable[[Dict[str, object]], str]) -> Dict[str, object]:
    """Create the next attempt record, write the brief the callback builds, and start the wrapper."""
    task_dir = root / str(state["task_id"])
    attempt = max((attempt_number(path) for path in task_dir.glob("attempt-*")), default=0) + 1
    attempt_dir = task_dir / f"attempt-{attempt}"
    attempt_dir.mkdir(parents=True)
    stale = ("pid", "finished_at", "exit_code", "timed_out", "reason", "question", "commit", "answer",
             "usage_recorded")
    state = {key: value for key, value in state.items()
             if not key.startswith("_") and key not in stale}
    state.update({"attempt": attempt, "command": shlex.split(options.child_command),
                  "child_timeout": options.child_timeout, "outcome": None,
                  "dispatched_at": now(), "origin": "question" if state.get("answered") else "dispatch"})
    state_path = attempt_dir / "state.json"
    (attempt_dir / "brief.md").write_text(brief(state), encoding="utf-8")
    save_state(state_path, state)
    wrapper = subprocess.Popen(
        [sys.executable, "-B", str(Path(__file__).resolve()), "_child", "--state", str(state_path)],
        cwd=state["worktree"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    state["_path"] = str(state_path)
    update_state(state, pid=wrapper.pid)
    return state


# --- finishing a task ------------------------------------------------------


def log_delta(primary: Path, state: Dict[str, object]) -> str:
    base_text = isolation.git_text(primary, "show", f"{state['base']}:{state['task_file']}")
    text = (Path(str(state["worktree"])) / str(state["task_file"])).read_text(encoding="utf-8")
    return isolation.task_log_delta(base_text, text)


def append_log(task_path: Path, line: str) -> None:
    text = task_path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    _common.atomic_write(task_path, text + line + "\n")


def snapshot_tree(primary: Path) -> str:
    """Tree of the primary's complete working tree via a temporary index; the real index is untouched."""
    with tempfile.TemporaryDirectory() as temporary:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / "index"))
        for arguments in (("read-tree", "HEAD"), ("add", "-A"), ("write-tree",)):
            completed = subprocess.run(("git", "-C", str(primary), *arguments), env=env,
                                       text=True, capture_output=True)
            if completed.returncode:
                raise DriverStop(f"git {' '.join(arguments)} failed: {completed.stderr.strip()}")
        return completed.stdout.strip()


def run_verify(command: str, cwd: Path) -> Dict[str, object]:
    completed = _common.run_command("bash", "-c", command, cwd=cwd)
    return {"exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def state_from_task(primary: Path, task_id: str) -> Dict[str, object]:
    """A finish-able state derived from the task frontmatter alone, for coders dispatched by hand."""
    tasks_dir = primary / ".project/tasks"
    for task_path in sorted(tasks_dir.glob("*.md")):
        fields, _ = isolation.task_frontmatter(task_path.read_text(encoding="utf-8"))
        if fields and str(fields.get("id")) == task_id:
            break
    else:
        raise DriverStop(f"task {task_id} has no task file")
    if fields.get("status") != "in-progress" or not fields.get("base"):
        raise DriverStop(f"task {task_id} is not an in-progress task with a recorded base")
    def value(key: str) -> Optional[str]:
        raw = fields.get(key)
        return None if raw in (None, "", "null") else str(raw)

    task_branch = value("task_branch")
    name = f"task-{task_id.lower()}-verify"
    sidecar = None if task_branch else {
        "worktree": str(isolation.sidecar_root(primary, "verify", name)),
        "branch": isolation.verify_branch_name(name)}
    return {"task_id": task_id, "title": str(fields.get("title")),
            "task_file": task_path.relative_to(primary).as_posix(), "files": list(fields.get("files") or []),
            "base": str(fields.get("base")), "worktree": value("worktree") or str(primary),
            "task_branch": task_branch, "mode": "parallel" if task_branch else "serial",
            "sidecar": sidecar}


def finish_task(primary: Path, state: Dict[str, object]) -> Dict[str, object]:
    """Verify in the isolate, land, record the ledger, retire. Returns the landing receipt."""
    worktree = Path(str(state["worktree"]))
    task_id = str(state["task_id"])
    task_file = str(state["task_file"])
    base = str(state["base"])
    task_path = worktree / task_file
    command = _common.task_verify_command(task_path.read_text(encoding="utf-8"))
    if not command:
        raise DriverStop("task has no Verify command", task=task_id)
    if state["mode"] == "serial":
        # ponytail: sidecar reproduction is git plumbing that belongs in isolation.py as the
        # inverse of clean_verify; lift it there when a second caller appears.
        sidecar = state["sidecar"]
        sidecar_path = Path(str(sidecar["worktree"]))
        tree = snapshot_tree(primary)
        isolation.git_output(sidecar_path, "read-tree", "-u", "--reset", tree)
        if isolation.git_output(sidecar_path, "write-tree") != tree:
            raise DriverStop("sidecar reproduction differs from the primary task diff", task=task_id)
        execution = run_verify(command, sidecar_path)
        location = f"sidecar {sidecar['branch']}"
        isolation.clean_verify(primary, sidecar_path, base, str(sidecar["branch"]))
        isolation.retire(primary, sidecar_path, str(sidecar["branch"]), False)
    else:
        execution = run_verify(command, worktree)
        location = f"isolate {state['task_branch']}"
    passed = execution["exit_code"] == 0
    execution.update({"worktree": str(worktree), "location": location})
    evidence_dir = (Path(str(state["_path"])).parent if state.get("_path")
                    else records_root(primary) / task_id / f"manual-{now().replace(':', '')}")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _common.atomic_write(evidence_dir / "verify.json",
                         json.dumps(execution, indent=2, sort_keys=True) + "\n")
    execution["evidence"] = str(evidence_dir / "verify.json")
    output = "\n".join(f"  {line}" for line in tail(execution["stdout"] + execution["stderr"]).splitlines())
    append_log(task_path, f"- {now()[:10]} — orchestrator Verify ({location}): "
                          f"{'pass' if passed else 'fail'}, exit {execution['exit_code']}"
                          + (f"; output tail:\n  ```\n{output}\n  ```" if output else ""))
    if not passed:
        if state["mode"] == "parallel":
            isolation.deactivate_task(worktree, task_id, str(state["task_branch"]))
        raise DriverStop("Verify failed in the isolate", task=task_id, execution=execution)
    landed = isolation.land(primary, worktree, base, task_id, str(state["title"]), task_file,
                            list(state["files"]))
    commit = str(landed["commit"])
    # Only a landing whose parent is the recorded base proves the verified tree.
    ledger = isolation.git_output(primary, "rev-parse", f"{commit}^") == base
    if ledger:
        build_state.verify_record(str(primary), command, commit, "pass", execution=execution)
    isolation.retire(primary, worktree, state.get("task_branch") or None, False)
    return {"task": task_id, "commit": commit, "mode": landed["mode"], "verify": execution,
            "ledger": ledger}


# --- shared by round and review --------------------------------------------


def summary(state: Dict[str, object]) -> Dict[str, object]:
    return {key: state.get(key) for key in
            ("task_id", "attempt", "mode", "worktree", "wave", "cycle", "verify_heavy", "dispatched_at")}


def recover_report(primary: Path, project_dir: str, receipt: Dict[str, object]) -> Dict[str, object]:
    report = isolation.recover(primary, Path(project_dir) / "tasks")
    receipt["steps"].append({"script": "isolation.py recover", "result": report})
    if report["verdict"] == "block":
        raise DriverStop("recovery blocked", recover=report)
    return report


def checkpoint_project(primary: Path, receipt: Dict[str, object], subject: str, body: str) -> Optional[str]:
    """Commit .project bookkeeping through the canonical checkpoint; None when nothing is dirty."""
    if not any(path.startswith(".project/") for path in isolation.uncommitted_paths(primary)):
        return None
    result = isolation.checkpoint(primary, isolation.current_sha(primary), subject, body, [".project"])
    receipt["steps"].append({"script": "isolation.py checkpoint", "result": result})
    return str(result.get("commit"))


def stop(receipt: Dict[str, object], error: BaseException) -> Dict[str, object]:
    receipt["status"] = "blocked"
    receipt["blocked"].append({"reason": str(error), "code": getattr(error, "code", None),
                               **getattr(error, "details", {})})
    receipt["next"] = "$gsd-path-forensics"
    return receipt


# --- the round -------------------------------------------------------------


class Round:
    def __init__(self, primary: Path, options: argparse.Namespace) -> None:
        self.primary = primary
        self.options = options
        self.project_dir = options.project_dir
        self.root = records_root(primary)
        self.proven: Dict[str, str] = {}  # task id -> landing commit proven by recover
        self.budgeted = (getattr(options, "task_limit", None) is not None
                         or budget_ledger(primary).is_file())
        self.receipt: Dict[str, object] = {
            "status": None, "wave": getattr(options, "wave", None), "landed": [],
            "dispatched": [], "in_flight": [], "questions": [], "blocked": [], "steps": [],
        }

    # token budget ---------------------------------------------------------

    def budget(self, action: str, *arguments: str) -> Dict[str, object]:
        """Run the bundled token_budget.py against this milestone's ledger; blocked is a stop."""
        command = [sys.executable, "-B", str(Path(__file__).resolve().parent / "token_budget.py"),
                   action, "--ledger", str(budget_ledger(self.primary)), *arguments]
        completed = subprocess.run(command, cwd=self.primary, capture_output=True, text=True)
        result = json.loads(completed.stdout) if completed.stdout.strip() else {}
        self.receipt["steps"].append({"script": f"token_budget.py {action}", "command": command,
                                      "exit_code": completed.returncode, "result": result,
                                      "stderr": completed.stderr})
        if completed.returncode:
            raise DriverStop(f"token budget {action}: {result.get('reason', completed.stderr.strip())}",
                             budget=result)
        return result

    def admit(self, task_id: str) -> None:
        if self.budgeted:
            self.budget("admit", "--task", task_id)

    def configure_budget(self) -> None:
        if getattr(self.options, "task_limit", None) is not None:
            self.budget("configure", "--task-limit", str(getattr(self.options, "task_limit", None)),
                        "--session-limit", str(getattr(self.options, "session_limit", None)),
                        "--authority", getattr(self.options, "budget_authority", None))

    # recovery -------------------------------------------------------------

    def recover(self) -> None:
        report = recover_report(self.primary, self.project_dir, self.receipt)
        for task in report["tasks"]:
            worktree = task.get("worktree")
            verdict = task["verdict"]
            if verdict in ("recovered", "attested"):
                self.proven[str(task.get("task_id"))] = str(task.get("commit"))
            if verdict == "recovered" and worktree and worktree["clean"] and task.get("task_branch"):
                isolation.retire(self.primary, Path(str(worktree["path"])),
                                 str(task["task_branch"]), False)
            elif (verdict == "recovered" and worktree is None and task.get("task_branch")) or (
                    verdict == "resume" and (task.get("landing_retry") or task.get("dispatch_retry"))):
                # ponytail: interrupted retirements and retries stay with the parent's documented
                # procedure; failed/blocked reconciliation surfaces through ready's typed error.
                raise DriverStop(f"task {task.get('task_id')} needs recovery: {verdict}", recover=task)

    # settle exited children ---------------------------------------------

    def isolate_live(self, state: Dict[str, object]) -> bool:
        """True while the isolate still holds the task as in-progress; the parent's recovery clears it."""
        task_path = Path(str(state["worktree"])) / str(state["task_file"])
        if not task_path.is_file():
            return False
        fields, _ = isolation.task_frontmatter(task_path.read_text(encoding="utf-8"))
        return fields is not None and fields.get("status") == "in-progress"

    def settle(self) -> bool:
        """Classify every exited child. Returns True when a landing or redispatch changed the round."""
        changed = False
        for state in latest_states(self.root):
            if state.get("wave") != self.receipt["wave"]:
                continue
            outcome = state.get("outcome")
            if outcome == "question":
                if state.get("answered"):
                    self.admit(str(state["task_id"]))
                    self.launch(dict(state, answered=True))
                    update_state(state, outcome="redispatched")
                    changed = True
                else:
                    self.receipt["questions"].append({**self.summary(state),
                                                      "question": state.get("question")})
            elif outcome == "blocked":
                if self.isolate_live(state):
                    self.receipt["blocked"].append({**self.summary(state),
                                                    "reason": state.get("reason"), "reported": True})
                else:
                    update_state(state, outcome="resolved")
            elif outcome is None:
                if str(state["task_id"]) in self.proven:  # landed, then interrupted before recording
                    update_state(state, outcome="landed", commit=self.proven[str(state["task_id"])])
                elif state.get("finished_at") is None:
                    if state.get("pid") and process_alive(int(state["pid"])):
                        self.receipt["in_flight"].append(self.summary(state))
                    else:
                        self.fail(state, "child wrapper exited without recording a result")
                else:
                    changed = self.classify(state) or changed
        return changed

    summary = staticmethod(summary)

    def fail(self, state: Dict[str, object], reason: str, **details: object) -> None:
        update_state(state, outcome="blocked", reason=reason)
        self.receipt["blocked"].append({**self.summary(state), "reason": reason, **details})

    def classify(self, state: Dict[str, object]) -> bool:
        attempt_dir = Path(str(state["_path"])).parent
        if self.budgeted and not state.get("usage_recorded"):
            self.budget("record", "--task", str(state["task_id"]), "--events", str(attempt_dir / "stdout"))
            update_state(state, usage_recorded=True)
        message = final_message((attempt_dir / "stdout").read_text(encoding="utf-8", errors="replace"))
        stderr = (attempt_dir / "stderr").read_text(encoding="utf-8", errors="replace")
        try:
            delta = log_delta(self.primary, state)
        except (isolation.IsolationError, FileNotFoundError) as error:
            self.fail(state, str(error), stdout_tail=tail(message), stderr_tail=tail(stderr))
            return False
        entries = [line for line in delta.splitlines() if line.strip()]
        answered_at = max((index for index, line in enumerate(entries) if ANSWER_MARK in line), default=-1)
        unanswered = entries[answered_at + 1:]
        matches = list(RESULT_LINE.finditer(message))
        verdict = matches[-1].group("verdict").lower() if matches else None
        named = matches[-1].group("task").lower() if matches else None
        if state.get("timed_out"):  # a failed child is a failure even when it wrote a question
            self.fail(state, "child exceeded the configured timeout", log_delta=delta.strip())
        elif state.get("exit_code") != 0:
            self.fail(state, f"child exited {state.get('exit_code')}", stderr_tail=tail(stderr),
                      stdout_tail=tail(message), log_delta=delta.strip())
        elif unanswered and QUESTION_MARK in unanswered[0]:
            update_state(state, outcome="question", question=unanswered[0], answered=False)
            self.receipt["questions"].append({**self.summary(state), "question": unanswered[0],
                                              "log_delta": delta.strip()})
        elif verdict != "ready" or named != str(state["task_id"]).lower():
            self.fail(state, "child returned blocked" if verdict == "blocked"
                      else "child returned no RESULT line", stdout_tail=tail(message),
                      log_delta=delta.strip())
        else:
            return self.finish(state)
        return False

    def finish(self, state: Dict[str, object]) -> bool:
        try:
            landing = finish_task(self.primary, state)
        except STOP_ERRORS as error:
            details = getattr(error, "details", {})
            self.fail(state, str(error), **{key: value for key, value in details.items()
                                             if key != "task"})
            return False
        update_state(state, outcome="landed", commit=landing["commit"])
        self.receipt["landed"].append(landing)
        return True

    def launch(self, state: Dict[str, object]) -> None:
        if state.get("wave") != self.receipt["wave"]:
            raise DriverStop("task is outside the requested wave", task=state["task_id"],
                             wave=state.get("wave"), requested_wave=self.receipt["wave"])
        fresh = spawn(self.root, state, self.options,
                      lambda fresh: brief_text(fresh, self.options.role_brief, self.options.task_template))
        self.receipt["dispatched"].append(self.summary(fresh))
        self.receipt["in_flight"].append(self.summary(fresh))

    # dispatch -------------------------------------------------------------

    def in_flight_states(self) -> List[Dict[str, object]]:
        return [state for state in latest_states(self.root)
                if state.get("outcome") is None and state.get("wave") == self.receipt["wave"]]

    def checkpoint_bookkeeping(self) -> None:
        open_ids = {state["task_id"] for state in latest_states(self.root)
                    if state.get("outcome") in (None, "question", "blocked")}
        orphaned = []
        for task_path in sorted((self.primary / ".project/tasks").glob("*.md")):
            fields, _ = isolation.task_frontmatter(task_path.read_text(encoding="utf-8"))
            if fields and fields.get("status") == "in-progress" and fields.get("id") not in open_ids:
                orphaned.append(str(fields.get("id")))
        if orphaned:
            raise DriverStop("in-progress tasks have no open dispatch record", tasks=orphaned)
        checkpoint_project(self.primary, self.receipt, "build: record dispatch bookkeeping",
                           "Why: commit the verify ledger and task state before the next dispatch round\n"
                           f"Base: {isolation.current_sha(self.primary)}")

    def dispatch_ready(self) -> bool:
        """Dispatch every selectable task. Returns True when the wave is complete."""
        in_flight = self.in_flight_states()
        if any(state["mode"] == "serial" for state in in_flight):
            return False
        ready = build_state.ready(str(self.primary), self.project_dir)
        self.receipt["steps"].append({"script": "build_state.py ready", "result": ready})
        wave = ready["current_wave"]
        if wave is not None and wave < self.receipt["wave"]:
            raise DriverStop(f"wave {wave} is still unfinished; run round --wave {wave} first")
        self.checkpoint_bookkeeping()
        if wave is None or wave > self.receipt["wave"]:
            return not in_flight
        active_ids = {state["task_id"] for state in in_flight}
        # ponytail: the one-heavy-Verify-at-a-time rule lives here; move it into
        # build_state.ready if the hand-dispatch path ever needs it too.
        heavy_busy = any(state.get("verify_heavy") for state in in_flight)
        capacity = self.options.capacity
        selected = []
        for task in ready["ready"]:
            if capacity is not None and len(in_flight) + len(selected) >= capacity:
                break
            if task["wave"] != self.receipt["wave"]:
                continue
            if task["id"] in active_ids or (task["verify_heavy"] and heavy_busy):
                continue
            heavy_busy = heavy_busy or task["verify_heavy"]
            selected.append(task)
        if not selected:
            return False
        for task in selected:
            used = attempts_used(self.root, task["id"])
            if used >= self.options.max_attempts:
                raise DriverStop(f"task {task['id']} reached the attempt limit ({self.options.max_attempts}) "
                                 "for this milestone; a person must rule", task=task["id"], attempts=used)
            self.admit(task["id"])
        head = isolation.current_sha(self.primary)
        self.runner("lint-round", head)
        round_size = len(selected) + len(in_flight)
        for task in selected:
            prepared = self.runner("prepare-task", head, task["id"], round_size)
            isolate = prepared[0]["result"]
            sidecar = prepared[1]["result"] if len(prepared) > 1 else None
            worktree = Path(str(isolate["worktree"]))
            isolation.activate_task(worktree, head, task["id"], f"build_{task['id'].lower()}",
                                    task["task_file"], isolate["task_branch"])
            self.launch({"task_id": task["id"], "title": task["title"], "task_file": task["task_file"],
                         "files": task["files"], "wave": task["wave"],
                         "verify_heavy": task["verify_heavy"], "base": head, "worktree": str(worktree),
                         "task_branch": isolate["task_branch"], "mode": isolate["mode"],
                         "sidecar": sidecar, "answered": False})
        return False

    def runner(self, action: str, head: str, task_id: Optional[str] = None,
               round_size: Optional[int] = None) -> List[Dict[str, object]]:
        result = workflow_run.run_workflow(self.primary, action, self.project_dir, head,
                                           task_id, round_size)
        self.receipt["steps"].extend(result["steps"])
        if result["status"] != "complete":
            raise DriverStop(f"{action} {task_id or ''}: {result['reason']}".rstrip())
        return result["steps"]

    def run(self) -> Dict[str, object]:
        deadline = time.monotonic() + self.options.wait if self.options.wait else None
        try:
            self.configure_budget()
            self.recover()
            changed = True
            while True:
                self.receipt["in_flight"] = []
                changed = self.settle() or changed
                if self.receipt["questions"] or self.receipt["blocked"]:
                    self.receipt["status"] = "question" if self.receipt["questions"] else "blocked"
                    return self.receipt
                # ready is expensive and its inputs only move when a landing or redispatch happened
                if changed and self.dispatch_ready():
                    self.receipt["status"] = "done"
                    return self.receipt
                changed = False
                live = self.in_flight_states()
                if deadline is None or time.monotonic() >= deadline or not live:
                    self.receipt["status"] = "in-flight" if live else "done"
                    return self.receipt
                time.sleep(POLL_SECONDS)
        except STOP_ERRORS as error:
            return stop(self.receipt, error)


# --- the wave review -------------------------------------------------------


def review_brief(state: Dict[str, object], options: argparse.Namespace, primary: Path,
                 tasks: List[Dict[str, object]], final_scope: bool, previous: Optional[Path]) -> str:
    wave, cycle, lens = state["wave"], state["cycle"], state.get("lens")
    agents = primary / "AGENTS.md"
    lines = [
        f"You are the reviewer for GSD Path wave {wave}, cycle {cycle}; logical task name "
        f"{state['task_id']}. Mode: wave" + (f"; lens: {lens}." if lens else "."),
        f"Read the reviewer role brief first and follow it exactly: {options.role_brief}",
        f"Template (use only this): {options.template}",
        f"AGENTS.md: {agents if agents.exists() else 'absent'}",
        f"Repository root, read-only: {primary}",
        f"Your verify sidecar root, the only place you may write or apply patches: {state['worktree']} "
        f"on branch {state['branch']} at the recorded review base {state['base']}.",
        f"Write exactly this output file: {Path(str(state['worktree'])) / str(state['relative'])}",
        f"Canonical path after the orchestrator collects it: {state['relative']}",
        f"INTENT.md: {primary / '.project/intent/INTENT.md'}",
        f"PLAN.md: {primary / '.project/plan/PLAN.md'}",
        "Tasks in this wave, each with its recorded base and proven landing commit; the "
        "orchestrator's recorded isolated Verify result is the `orchestrator Verify` entry in each Log:",
    ]
    for task in tasks:
        lines.append(f"- {task['task_id']}: {primary / str(task['task'])} — base {task['base']}, "
                     f"landing commit {task['commit']}")
    if previous is not None:
        lines.append(f"Previous cycle review to re-check: {previous}")
    if options.repair_evidence:
        lines.append(f"Repair evidence receipt (re-review after a proven repair): {options.repair_evidence}")
    if final_scope:
        lines.append(f"Final scope applies: record `Review scope: final` and `Reviewed HEAD: {state['base']}`, "
                     "check every INTENT success criterion and PLAN.md's Surface contract, and add "
                     "Surface, Check, and Observed fields to each surface criterion block.")
    lines += [
        "Do not re-run task Verify or PLAN.md's project Verify. Never edit the primary worktree. "
        "Never delegate to another agent. Never stage or commit.",
        "Terminal result: the `Wave verdict:` line of the file you wrote is your result; the "
        "orchestrator validates the file and reads it from there. Name that verdict in your final message.",
    ]
    return "\n".join(lines) + "\n"


class Review:
    """Step 6 of the build contract at `full` or `deep` depth: one reviewer per lens in its own
    verify sidecar, validated, collected, retired; findings grouped on blocked."""

    def __init__(self, primary: Path, options: argparse.Namespace) -> None:
        self.primary = primary
        self.options = options
        self.project_dir = options.project_dir
        self.wave, self.cycle = options.wave, options.cycle
        self.root = records_root(primary) / "reviews"
        self.receipt: Dict[str, object] = {"status": None, "wave": self.wave, "cycle": self.cycle,
                                           "lenses": {}, "in_flight": [], "blocked": [], "steps": []}

    def lens_name(self, key: str) -> str:
        return f"review_wave_{self.wave}_cycle_{self.cycle}" + ("" if key == "canonical" else f"_{key}")

    def current_states(self, keys: List[str]) -> Dict[str, Dict[str, object]]:
        names = {self.lens_name(key): key for key in keys}
        return {names[str(state["task_id"])]: state for state in latest_states(self.root)
                if str(state["task_id"]) in names}

    def wave_tasks(self) -> List[Dict[str, object]]:
        tasks = []
        for task in recover_report(self.primary, self.project_dir, self.receipt)["tasks"]:
            fields, _ = isolation.task_frontmatter((self.primary / str(task["task"])).read_text(encoding="utf-8"))
            if fields is None or contracts._task_wave((self.primary / str(task["task"])).read_text(encoding="utf-8"),
                                                     str(task.get("task_id"))) != self.wave:
                continue
            if task["verdict"] not in ("recovered", "attested"):
                raise DriverStop(f"task {task.get('task_id')} has no proven landing: {task['verdict']}",
                                 recover=task)
            tasks.append(task)
        if not tasks:
            raise DriverStop(f"wave {self.wave} has no tasks")
        return tasks

    def dispatch(self, lenses: Dict[str, str], depth: str, base: Optional[str] = None) -> None:
        dirty = sorted(isolation.uncommitted_paths(self.primary))
        if dirty:  # the review base must include every bookkeeping change
            raise DriverStop("review collection base requires a clean primary", paths=dirty)
        tasks = self.wave_tasks()
        plan_text = (self.primary / self.project_dir / "plan/PLAN.md").read_text(encoding="utf-8")
        intent = (self.primary / self.project_dir / "intent/INTENT.md").read_text(encoding="utf-8")
        try:
            lane = contracts._line_value(intent, "Lane:")
        except contracts.HandoffError:
            lane = None  # an INTENT without a lane line is never quick
        final_scope = depth == "full" and lane == "quick" and contracts._plan_waves(plan_text)[1] == [1]
        earlier = (review_findings.review_paths(self.primary / self.project_dir, self.wave, self.cycle - 1, depth)
                   if self.cycle > 1 else {})
        for previous in earlier.values():
            if not previous.is_file():
                raise DriverStop(f"previous cycle review is missing: {previous}")
        base = base or isolation.current_sha(self.primary)
        self.receipt["base"] = base
        for key, relative in lenses.items():
            name = f"wave-{self.wave}-cycle-{self.cycle}" + ("" if key == "canonical" else f"-{key}")
            sidecar = isolation.isolate_verify(self.primary, base, name)
            self.receipt["steps"].append({"script": "isolation.py isolate-verify", "result": sidecar})
            previous = earlier.get(key)
            state = {"task_id": self.lens_name(key), "lens": None if key == "canonical" else key,
                     "wave": self.wave, "cycle": self.cycle, "base": base,
                     "worktree": str(sidecar["worktree"]), "branch": str(sidecar["branch"]), "relative": relative}
            spawn(self.root, state, self.options,
                  lambda fresh, previous=previous: review_brief(fresh, self.options, self.primary, tasks,
                                                                 final_scope, previous))

    def collect(self, state: Dict[str, object]) -> None:
        """Validate in the sidecar, then copy to the canonical path, then retire: the contract's order."""
        sidecar = Path(str(state["worktree"]))
        relative = str(state["relative"])
        stderr = (Path(str(state["_path"])).parent / "stderr").read_text(encoding="utf-8", errors="replace")
        if state.get("timed_out") or state.get("exit_code") != 0:
            update_state(state, outcome="blocked", reason=f"reviewer child exited {state.get('exit_code')}",
                         stderr_tail=tail(stderr))
            return
        staged = sidecar / relative
        canonical = self.primary / relative
        if state.get("outcome") != "collected":
            if not staged.is_file():
                if (state.get("validated") and canonical.is_file()
                        and hashlib.sha256(canonical.read_bytes()).hexdigest() == state.get("validated_sha256")):
                    update_state(state, outcome="collected")
                else:
                    update_state(state, outcome="blocked", reason="reviewer wrote no review file", stderr_tail=tail(stderr))
                    return
            else:
                try:
                    validated = contracts.validate_wave_evidence(sidecar, self.project_dir, relative)
                except contracts.HandoffError as error:
                    update_state(state, outcome="blocked", reason=str(error), helper="check_handoffs.py wave")
                    return
                update_state(state, verdict=validated["verdict"], owned=validated.get("owned"), validated=True,
                             validated_sha256=hashlib.sha256(staged.read_bytes()).hexdigest())
                try:
                    collected = isolation.collect_artifact(self.primary, sidecar, str(state["base"]),
                                                           str(state["branch"]), relative, relative, None)
                except isolation.IsolationError as error:
                    update_state(state, outcome="blocked", reason=str(error), helper="isolation.py")
                    return
                update_state(state, outcome="collected")
                self.receipt["steps"].append({"script": "isolation.py collect-artifact", "result": collected})
        try:
            if sidecar.exists():
                isolation.clean_verify(self.primary, sidecar, str(state["base"]), str(state["branch"]))
            isolation.retire(self.primary, sidecar, str(state["branch"]), False)
        except isolation.IsolationError as error:
            update_state(state, cleanup_pending=True, cleanup_error=str(error))
            return
        update_state(state, cleanup_complete=True, cleanup_pending=False, cleanup_error=None)

    def input_failure(self, base: str) -> Optional[Dict[str, str]]:
        paths = review_findings.review_paths(self.primary / self.project_dir, self.wave,
                                            self.cycle, self.receipt["depth"])
        allowed = {path.relative_to(self.primary).as_posix() for path in paths.values()}
        head = isolation.current_sha(self.primary)
        committed = set(filter(None, isolation.git_text(
            self.primary, "diff", "--no-renames", "--name-only", "-z", base, head, "--").split("\0")))
        changed = committed | isolation.uncommitted_paths(self.primary)
        checkpoint = f"build: record wave {self.wave} cycle {self.cycle} review"
        history_matches = head == base or (
            isolation.git_output(self.primary, "show", "-s", "--format=%P", head) == base
            and isolation.git_output(self.primary, "show", "-s", "--format=%s", head) == checkpoint)
        if changed - allowed or not history_matches:
            return {"reason": "inputs changed after the review base; run a new cycle",
                    "helper": "dispatch_driver.py review"}
        return None

    def settle(self, states: Dict[str, Dict[str, object]]) -> None:
        """Advance every lens and render the receipt from the records; settle is their only writer."""
        self.receipt["in_flight"], self.receipt["blocked"], self.receipt["lenses"] = [], [], {}
        for key, state in states.items():
            if state.get("outcome") == "collected" and (
                    state.get("cleanup_pending") or not state.get("cleanup_complete")):
                self.collect(state)
            if state.get("outcome") is None:
                if state.get("finished_at") is not None:
                    self.collect(state)
                elif state.get("pid") and process_alive(int(state["pid"])):
                    self.receipt["in_flight"].append(summary(state))
                    continue
                else:
                    update_state(state, outcome="blocked", reason="child wrapper exited without recording a result")
            self.receipt["base"] = state.get("base")
            if state.get("outcome") == "collected":
                failure = self.input_failure(str(state["base"]))
                if failure:
                    self.receipt["blocked"].append({**summary(state), **failure})
                    continue
                canonical = self.primary / str(state["relative"])
                if (not canonical.is_file()
                        or hashlib.sha256(canonical.read_bytes()).hexdigest() != state.get("validated_sha256")):
                    self.receipt["blocked"].append({**summary(state),
                        "reason": "canonical review artifact changed after collection",
                        "helper": "isolation.py collect-artifact"})
                    continue
                if state.get("cleanup_pending"):
                    self.receipt["blocked"].append({**summary(state), "reason": state.get("cleanup_error"),
                                                    "helper": "isolation.py retire"})
                self.receipt["lenses"][key] = {"verdict": state.get("verdict"), "owned": state.get("owned"),
                                               "path": state.get("relative")}
            elif state.get("outcome") == "blocked":
                self.receipt["blocked"].append({**summary(state), "reason": state.get("reason"),
                                                "helper": state.get("helper"), "stderr_tail": state.get("stderr_tail")})

    def conclude(self) -> None:
        lenses: Dict[str, Dict[str, object]] = self.receipt["lenses"]
        passing = not self.receipt["blocked"] and all(entry.get("verdict") == "pass" for entry in lenses.values())
        failure = self.input_failure(str(self.receipt["base"])) if passing else None
        if passing and failure is None:
            if not self.receipt["panel_required"]:  # with a panel, the parent's single checkpoint follows it
                self.receipt["checkpoint"] = checkpoint_project(
                    self.primary, self.receipt, f"build: record wave {self.wave} cycle {self.cycle} review",
                    f"Why: persist the passing wave review verdict\nWave: {self.wave}")
            self.receipt["status"] = "pass"
            return
        helper_failures = [f"{item['helper']}: {item['reason']}" for item in self.receipt["blocked"]
                           if item.get("helper")]
        if failure:
            self.receipt.update(failure)
            helper_failures.append(f"{failure['helper']}: {failure['reason']}")
        try:
            self.receipt["findings"] = review_findings.compute(self.primary, self.project_dir, self.wave,
                                                               self.cycle, helper_failures)
        except review_findings.ReviewFindingsError as error:
            self.receipt["findings"] = {"status": "error", "error": str(error)}
        self.receipt["status"] = "blocked"

    def run(self) -> Dict[str, object]:
        deadline = time.monotonic() + self.options.wait if self.options.wait else None
        try:
            project = self.primary / self.project_dir
            plan_text = (project / "plan/PLAN.md").read_text(encoding="utf-8")
            depth = review_findings.wave_depth(plan_text, self.wave)
            self.receipt["depth"] = depth
            if depth == "verify-only":
                # ponytail: verify-only files are orchestrator-written judgment; the parent owns them.
                self.receipt.update(status="not-applicable",
                                    reason="verify-only reviews are orchestrator-written; the driver does not run them")
                return self.receipt
            self.receipt["panel_required"] = review_panel.plan_review_panel_enabled(plan_text)
            lenses = {key: path.relative_to(self.primary).as_posix() for key, path in
                      review_findings.review_paths(project, self.wave, self.cycle, depth).items()}
            states = self.current_states(list(lenses))
            missing = {key: relative for key, relative in lenses.items() if key not in states}
            if missing:
                base = None
                if states:
                    bases = {state["base"] for state in states.values()}
                    head = isolation.current_sha(self.primary)
                    if bases != {head}:
                        raise DriverStop(f"missing review lenses {', '.join(missing)}: HEAD moved to {head}; "
                                         f"recorded bases: {', '.join(sorted(bases))}")
                    base = head
                self.dispatch(missing, depth, base)
                states = self.current_states(list(lenses))
            while True:
                self.settle(states)
                if set(states) == set(lenses) and all(
                        state.get("outcome") in ("collected", "blocked") for state in states.values()):
                    self.conclude()
                    return self.receipt
                if deadline is None or time.monotonic() >= deadline:
                    self.receipt["status"] = "in-flight"
                    return self.receipt
                time.sleep(POLL_SECONDS)
                states = self.current_states(list(lenses))
        except STOP_ERRORS as error:
            return stop(self.receipt, error)


# --- other actions ---------------------------------------------------------


def answer(primary: Path, task_id: str, text: str) -> Dict[str, object]:
    states = [state for state in latest_states(records_root(primary)) if state["task_id"] == task_id]
    if not states or states[0].get("outcome") != "question":
        raise DriverStop(f"task {task_id} has no open question")
    state = states[0]
    task_path = Path(str(state["worktree"])) / str(state["task_file"])
    append_log(task_path, f"- {now()[:10]} — {ANSWER_MARK} {text}")
    update_state(state, answered=True, answer=text)
    return {"status": "answered", "task": task_id, "task_file": str(task_path),
            "next": "run `round` to redispatch the retained isolate"}


def require_files(parser: argparse.ArgumentParser, arguments: argparse.Namespace, *names: str) -> None:
    for name in names:
        value = getattr(arguments, name)
        if value is None or not Path(value).is_file():
            parser.error(f"--{name.replace('_', '-')} must name an existing file")
        setattr(arguments, name, Path(value).resolve())


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return number


def default_resource(name: str) -> Optional[Path]:
    candidate = Path(__file__).resolve().parent.parent / name
    return candidate if candidate.is_file() else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    round_parser = commands.add_parser("round", help="settle, land, and dispatch the current wave")
    round_parser.add_argument("--repo", type=Path, required=True)
    round_parser.add_argument("--project-dir", default=".project")
    round_parser.add_argument("--child-command", required=True,
                              help="owner-supplied command that reads the brief on stdin")
    round_parser.add_argument("--wait", type=float, help="seconds to keep polling before returning")
    round_parser.add_argument("--wave", type=int, required=True, help="wave selected by the parent")
    round_parser.add_argument("--child-timeout", type=float, help="per-child wall clock in seconds")
    round_parser.add_argument("--capacity", type=positive_int, help="owner's concurrent-child limit")
    round_parser.add_argument("--max-attempts", type=positive_int, default=2,
                              help="dispatches per task per milestone before a person must rule; "
                                   "default 2 is the build contract's one logged redispatch")
    round_parser.add_argument("--task-limit", type=positive_int, help="owner output-token limit per task")
    round_parser.add_argument("--session-limit", type=positive_int,
                              help="owner output-token limit for the milestone")
    round_parser.add_argument("--budget-authority", help="quoted owner policy for the limits")
    round_parser.add_argument("--role-brief", type=Path, default=default_resource("references/coder.md"))
    round_parser.add_argument("--task-template", type=Path, default=default_resource("templates/task.md"))
    review_parser = commands.add_parser("review", help="run one wave review cycle at full or deep depth")
    review_parser.add_argument("--repo", type=Path, required=True)
    review_parser.add_argument("--project-dir", default=".project")
    review_parser.add_argument("--wave", type=int, required=True)
    review_parser.add_argument("--cycle", type=positive_int, required=True)
    review_parser.add_argument("--child-command", required=True,
                               help="owner-supplied command that reads the brief on stdin")
    review_parser.add_argument("--wait", type=float, help="seconds to keep polling before returning")
    review_parser.add_argument("--child-timeout", type=float, help="per-child wall clock in seconds")
    review_parser.add_argument("--repair-evidence", type=Path,
                               help="review_findings.py repair-evidence receipt for a re-review")
    review_parser.add_argument("--role-brief", type=Path, default=default_resource("references/reviewer.md"))
    review_parser.add_argument("--template", type=Path, default=default_resource("templates/wave-review.md"))
    finish_parser = commands.add_parser(
        "finish", help="verify, land, record, and retire one in-progress task whose coder has returned")
    finish_parser.add_argument("--repo", type=Path, required=True)
    finish_parser.add_argument("--task-id", required=True)
    finish_parser.add_argument("--project-dir", default=".project")
    answer_parser = commands.add_parser("answer", help="record an orchestrator answer for a question")
    answer_parser.add_argument("--repo", type=Path, required=True)
    answer_parser.add_argument("--task-id", required=True)
    answer_parser.add_argument("--answer", required=True)
    status_parser = commands.add_parser("status", help="list dispatch records")
    status_parser.add_argument("--repo", type=Path, required=True)
    child_parser = commands.add_parser("_child", help=argparse.SUPPRESS)
    child_parser.add_argument("--state", type=Path, required=True)
    arguments = parser.parse_args(argv)

    if arguments.action == "_child":
        return child_main(arguments.state)
    primary = arguments.repo.resolve()
    lock = None
    try:
        if arguments.action in ("round", "review", "finish", "answer"):
            lock = acquire_lock(primary)
        if arguments.action == "review":
            require_files(parser, arguments, "role_brief", "template",
                          *(["repair_evidence"] if arguments.repair_evidence is not None else []))
            result = Review(primary, arguments).run()
        elif arguments.action == "round":
            budget_values = (arguments.task_limit, arguments.session_limit, arguments.budget_authority)
            if any(value is not None for value in budget_values) and None in budget_values:
                parser.error("--task-limit, --session-limit, and --budget-authority go together")
            require_files(parser, arguments, "role_brief", "task_template")
            result = Round(primary, arguments).run()
        elif arguments.action == "finish":
            current = Round(primary, arguments)
            current.recover()
            records = [state for state in latest_states(current.root)
                       if state["task_id"] == arguments.task_id]
            if arguments.task_id in current.proven:
                commit = current.proven[arguments.task_id]
                if records and records[0].get("outcome") is None:
                    update_state(records[0], outcome="landed", commit=commit)
                current.receipt["landed"].append(
                    {"task": arguments.task_id, "commit": commit, "recovered": True})
            elif records:
                record = records[0]
                if record.get("outcome") is not None:
                    raise DriverStop(f"task {arguments.task_id} dispatch record is {record['outcome']}; "
                                     "use round")
                if record.get("finished_at") is None:
                    raise DriverStop(f"task {arguments.task_id} still has a running child")
                current.classify(record)
            else:  # a coder dispatched by hand: derive the isolate from the task frontmatter
                current.receipt["landed"].append(
                    finish_task(primary, state_from_task(primary, arguments.task_id)))
            result = {**current.receipt, "status": "landed" if current.receipt["landed"] else "blocked"}
        elif arguments.action == "answer":
            result = answer(primary, arguments.task_id, arguments.answer)
        else:
            result = {"status": "ok", "dispatches": [
                {key: value for key, value in state.items() if key not in ("_path", "command")}
                for state in latest_states(records_root(primary))]}
    except STOP_ERRORS as error:
        result = {"status": "blocked", "reason": str(error), **getattr(error, "details", {})}
    finally:
        if lock is not None:
            lock.close()
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if result["status"] != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
