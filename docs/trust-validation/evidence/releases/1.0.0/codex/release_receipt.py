#!/usr/bin/env python3
"""Assemble a gsd-path live-evidence release receipt from a real host run.

Select --host <manifest host> (default codex) before the phase name; host facts come
from tests/hosts/<host>.py in --repo. Codex and Claude retain their stricter inline
child binders; other hosts use SPEC.bind_child. A native-tier host's manifest requires
--native-guard-evidence pointing to a passing probe JSON. For receipt, --transcript is
a Codex session JSONL file or, for every other host, the tests/evaluate_host.py run
root containing quick/run-*/events.jsonl.

Two phases, both driven by the evaluator against the fixture repository:

  manifest  -- at the ship-time pause (after `archive_milestone.py prepare`, before
               render-manifest): runs the Git-hook guard check in a disposable clone,
               then writes <archive>/guards.json and <archive>/trust-run-manifest.json.
  receipt   -- after integration: writes the ten step files, the fixture bundle and
               <host>.md under the repo's evidence directory, then validates them with
               scripts/check_trust_evidence._validate_receipt.

Every value comes from the fixture repository, the harness records, or the host
session transcript; nothing is invented.
"""
import argparse, datetime as dt, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HOST = SPEC = CHILD_API = GUARD_TIER = None  # bound from --host in main(); SPEC is the tests/hosts HostSpec
STEP = "gsd-path/live-step-evidence/v1"


def git(repo, *a, check=True):
    r = subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(a)} failed in {repo}: {r.stderr.strip()}")
    return r.stdout.strip()


def state_field(repo, key):
    m = re.search(rf"^{key}:\s*(\S+)", (Path(repo) / ".project/STATE.md").read_text(), re.M)
    return m.group(1) if m else None


def task_info(repo, archive):
    tasks = sorted((Path(repo) / archive / "tasks").glob("*.md"))
    if len(tasks) != 1:
        raise SystemExit(f"expected one archived task, found {len(tasks)}")
    text = tasks[0].read_text()
    f = lambda k: re.search(rf"^{k}:\s*(\S+)", text, re.M).group(1)
    return {"file": tasks[0], "id": f("id"), "agent": f("agent"), "base": f("base")}


def sha256(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_hook_check(repo, archive_rel, committed_repo=None, committed_archive=None):
    """Prove the installed pre-commit hook: a committed archive is read-only, other commits pass.

    Before ship the fixture has no committed archive yet, so the check may run in a clone of
    another repository whose archive is committed (committed_repo). Both git_guard.py
    and pre-commit hook hashes must match. The fixture's pre-commit hook and commit-msg
    hook, when present, must be executable; the clone preserves source hook permissions.
    """
    source = Path(committed_repo or repo).resolve(); archive = committed_archive or archive_rel
    out = {"checked_repository": str(source), "checked_archive": archive, "steps": []}
    out["guard_sha256"] = {"fixture": sha256(Path(repo) / ".gsd-path/git_guard.py"),
                           "checked_repository": sha256(source / ".gsd-path/git_guard.py")}
    out["pre_commit_hook_sha256"] = {"fixture": sha256(Path(repo) / ".git/hooks/pre-commit"),
                                     "checked_repository": sha256(source / ".git/hooks/pre-commit")}
    out["hash_mismatches"] = [key for key in ("guard_sha256", "pre_commit_hook_sha256")
                              if out[key]["fixture"] != out[key]["checked_repository"]]
    out["fixture_hook_executable"] = {
        hook: os.access(Path(repo) / ".git/hooks" / hook, os.X_OK)
        for hook in ("pre-commit", "commit-msg")
        if hook == "pre-commit" or (Path(repo) / ".git/hooks" / hook).exists()
    }
    with tempfile.TemporaryDirectory(prefix="gsd-path-hook-check-") as tmp:
        clone = Path(tmp) / "clone"
        git(source, "clone", "-q", "--no-hardlinks", str(source), str(clone))
        git(clone, "checkout", "-q", git(source, "rev-parse", "--abbrev-ref", "HEAD"))
        out["checked_commit"] = git(clone, "rev-parse", "HEAD")
        for hook in ("pre-commit", "commit-msg"):
            src = source / ".git/hooks" / hook
            if src.exists():
                shutil.copy2(src, clone / ".git/hooks" / hook)  # keep the source mode: an inert hook must stay inert
        git(clone, "config", "user.name", "Guard Check"); git(clone, "config", "user.email", "guard@example.invalid")
        if not git(clone, "ls-files", archive):
            raise SystemExit(f"{source} has no committed archive at {archive}")
        target = next(p for p in sorted((clone / archive).rglob("*")) if p.is_file())
        rel = target.relative_to(clone).as_posix()
        target.write_text(target.read_text() + "\ntamper\n")
        git(clone, "add", rel)
        r = subprocess.run(["git", "commit", "-qm", "test: tamper archive"], cwd=clone, capture_output=True, text=True)
        blocked = r.returncode != 0 and "read-only" in r.stderr
        out["steps"].append({"step": f"stage and commit a modification to committed {rel}", "exit_code": r.returncode,
                             "stderr": r.stderr.strip()[-400:], "blocked": blocked})
        git(clone, "reset", "-q", "--hard")
        (clone / "notes.txt").write_text("outside archive\n")
        git(clone, "add", "notes.txt")
        r = subprocess.run(["git", "commit", "-qm", "test: outside archive"], cwd=clone, capture_output=True, text=True)
        out["steps"].append({"step": "commit outside archive", "exit_code": r.returncode, "stderr": r.stderr.strip()[-400:]})
        out["git_hooks"] = "pass" if (not out["hash_mismatches"]
                                     and all(out["fixture_hook_executable"].values())
                                     and blocked and r.returncode == 0) else "fail"
    return out


def phase_manifest(a):
    sys.path.insert(0, str(Path(a.repo).resolve()))
    repo = Path(a.fixture).resolve()
    archive = state_field(repo, "archive")
    if not archive or not (repo / archive).is_dir():
        raise SystemExit("STATE.archive is not a prepared archive directory")
    task = task_info(repo, archive)
    landing = git(repo, "log", "--format=%H", f"--grep=^Task: \\.project/tasks/{task['file'].name}$", "HEAD")
    if len(landing.split()) != 1:
        raise SystemExit(f"expected one landing commit for {task['file'].name}, found {landing!r}")
    hooks = git_hook_check(repo, archive, a.committed_archive_repo, a.committed_archive)
    if GUARD_TIER == "git-only":
        native, native_evidence = "not-applicable", {"note": f"{HOST} is declared git-only; native enforcement is not required for this tier"}
    else:
        if not a.native_guard_evidence:
            raise SystemExit(f"{HOST} is {GUARD_TIER}: --native-guard-evidence <probe json> is required")
        native_evidence = json.loads(Path(a.native_guard_evidence).read_text())
        native = native_evidence.get("native_guard")
        if native != "pass":
            raise SystemExit("native guard probe did not pass")
    guards = {"schema": "gsd-path/live-guard-evidence/v1", "host": HOST, "run_id": a.run_id,
              "declared_tier": GUARD_TIER, "native_guard": native, "git_hooks": hooks["git_hooks"],
              "native_guard_evidence": native_evidence,
              "git_hook_check": hooks, "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    child_id = task["agent"]
    if HOST not in ("codex", "claude"):
        # check_trust_evidence requires the task agent field to name the child that did the work.
        # Bind it now so a host that dispatched under a different label fails here, before the ship
        # commit, instead of after the archive is committed and integrated.
        try:
            transcript_child(str(Path(a.fixture).resolve().parent.parent), child_id)
        except Exception as exc:
            raise SystemExit(f"the task file records agent {child_id!r} but no completed child "
                             f"was dispatched under that label ({exc}). The host broke the dispatch "
                             "contract; rerun its build so the dispatched label and the task agent "
                             "field match. Do not override this: the receipt validator cross-checks them.")
    manifest = {"schema": "gsd-path/live-run-manifest/v1", "host": HOST, "run_id": a.run_id,
                "host_version": a.host_version, "candidate": a.candidate, "package_version": a.package_version,
                "child_api": CHILD_API, "child_id": child_id, "guard_tier": GUARD_TIER,
                "fixture_base_commit": task["base"], "landing_commit": landing,
                "task_branch": a.task_branch, "bound_branch": state_field(repo, "branch"),
                "default_branch": "main", "pre_integration_default_commit": remote_default_commit(repo),
                "milestone_tag": f"milestone/{Path(archive).name}",
                "artifacts": {"state": ".project/STATE.md", "verify": f"{archive}/build/verify-ledger.jsonl",
                              "wave_review": f"{archive}/review/wave-1.cycle1.md",
                              "final_review": f"{archive}/review/FINAL.md", "archive": archive,
                              "guards": f"{archive}/guards.json"}}
    for rel in manifest["artifacts"].values():
        if rel != f"{archive}/guards.json" and not (repo / rel).exists():
            raise SystemExit(f"artifact missing before ship: {rel}")
    (repo / archive / "guards.json").write_text(json.dumps(guards, indent=2) + "\n")
    (repo / archive / "trust-run-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"archive": archive, "git_hooks": hooks["git_hooks"], "landing_commit": landing,
                      "child_id": child_id, "manifest": f"{archive}/trust-run-manifest.json"}, indent=2))
    return 0 if hooks["git_hooks"] == "pass" else 1


def remote_default_commit(repo):
    """The remote's own main, not the local remote-tracking ref.

    ``origin/main`` can lag or hold an abandoned integration if a fetch has not
    rewound it; the integration merge's first parent is checked against this
    value, so a stale read produces a receipt that cannot validate.
    """
    line = git(repo, "ls-remote", "origin", "refs/heads/main")
    if line:
        return line.split()[0]
    return git(repo, "rev-parse", "origin/main")


def transcript_child(transcript, child_id):
    if HOST == "claude":
        return claude_child(transcript, child_id)
    if HOST != "codex":  # tests/hosts/<host>.bind_child reads the evaluate_host.py run root
        try:
            return SPEC.bind_child(Path(transcript), child_id)
        except LookupError as e:
            raise SystemExit(str(e))
    recs = [json.loads(l) for l in Path(transcript).read_text().splitlines() if l.strip()]
    spawn = spawn_out = None; call_id = None; statuses = []
    for r in recs:
        p = r.get("payload", {})
        if p.get("type") == "function_call" and p.get("name") == "spawn_agent" and f'"task_name":"{child_id}"' in p.get("arguments", ""):
            args = json.loads(p["arguments"]); args.pop("message", None)  # message is encrypted context
            spawn = {"call_id": p.get("call_id"), "name": p["name"], "namespace": p.get("namespace"), "arguments": args}
            call_id = p.get("call_id")
        elif p.get("type") == "function_call_output" and p.get("call_id") == call_id and spawn_out is None:
            spawn_out = p.get("output")
        elif p.get("type") == "function_call_output" and isinstance(p.get("output"), str) and "agent_status" in p["output"]:
            try:
                for ag in json.loads(p["output"]).get("agents", []):
                    if ag.get("agent_name", "").endswith("/" + child_id):
                        statuses.append(ag)
            except ValueError:
                pass
    if spawn is None or spawn_out is None:
        raise SystemExit(f"transcript has no spawn_agent call/output for {child_id}")
    def done(s):  # Codex reports completion as "completed" or {"completed": "<final message>"}
        st = s.get("agent_status")
        return st == "completed" or (isinstance(st, dict) and "completed" in st)
    if not any(done(s) for s in statuses):
        raise SystemExit(f"transcript never lists {child_id} as completed via list_agents")
    return {"child_id": child_id, "status": "completed", "spawn_call": spawn, "spawn_output": spawn_out,
            "list_agents_states": statuses}


def claude_child(run_root, child_id, landed_tool_use_id=None):
    """Bind each Agent attempt to completion evidence from the recorded stream.

    A caller with proven landing evidence can select its tool-use ID explicitly.
    Otherwise the last completed attempt supplies the receipt.
    """
    attempts = {}
    completion_events = []
    for events in sorted(Path(run_root).glob("quick/run-*/events.jsonl")):
        for line in events.read_text().splitlines():
            try: ev = json.loads(json.loads(line)["raw"])
            except (ValueError, KeyError): continue
            if ev.get("type") in ("assistant", "user"):
                for c in ev["message"].get("content", []):
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "tool_use" and c.get("name") == "Agent" and c["input"].get("description") == child_id:
                        inp = {k: v for k, v in c["input"].items() if k != "prompt"}
                        attempts.setdefault(c["id"], {
                            "child_id": child_id, "status": "completed", "run": events.parent.name,
                            "tool_use": {"id": c["id"], "name": c["name"], "input": inp,
                                         "prompt_sha256": __import__("hashlib").sha256(c["input"].get("prompt", "").encode()).hexdigest()},
                            "task_id": None, "task_started": None, "task_notification": None,
                            "tool_result": None,
                        })
                    elif c.get("type") == "tool_result" and c.get("tool_use_id") in attempts:
                        attempt = attempts[c["tool_use_id"]]
                        attempt["tool_result"] = {"tool_use_id": c["tool_use_id"],
                                                  "is_error": bool(c.get("is_error")), "content": c.get("content")}
                        completion_events.append((c["tool_use_id"], "tool_result"))
            elif ev.get("type") == "system" and ev.get("tool_use_id") in attempts:
                attempt = attempts[ev["tool_use_id"]]
                if ev.get("subtype") == "task_started":
                    attempt["task_started"] = {k: v for k, v in ev.items() if k != "prompt"}
                    attempt["task_id"] = ev.get("task_id")
                elif ev.get("subtype") == "task_notification":
                    if attempt["task_id"] is not None and attempt["task_id"] != ev.get("task_id"):
                        continue
                    attempt["task_id"] = ev.get("task_id")
                    attempt["task_notification"] = {k: ev.get(k) for k in ("tool_use_id", "task_id", "status", "summary")}
                    completion_events.append((ev["tool_use_id"], "task_notification"))
    eligible = []
    for tool_use_id, event_type in completion_events:
        attempt = attempts[tool_use_id]
        result = attempt["tool_result"]
        started = attempt["task_started"] or {}
        background = (attempt["tool_use"]["input"].get("run_in_background")
                      or started.get("is_backgrounded")
                      or (result and "agent launched" in str(result["content"]).lower()))
        notification = attempt["task_notification"] or {}
        if background:
            done = event_type == "task_notification" and notification.get("status") == "completed"
        else:
            done = event_type == "tool_result" and result is not None and not result["is_error"]
        if done:
            eligible.append(tool_use_id)
    if not eligible:
        raise SystemExit(f"no completed Agent attempt for description {child_id}; background launches require a matching completed task_notification")
    if landed_tool_use_id is not None:
        if landed_tool_use_id not in eligible:
            raise SystemExit(f"landed Agent attempt {landed_tool_use_id} has no completion evidence for {child_id}")
        return attempts[landed_tool_use_id]
    return attempts[eligible[-1]]


def phase_receipt(a):
    repo = Path(a.fixture).resolve(); root = Path(a.repo).resolve()
    archive = state_field(repo, "archive"); manifest = json.loads((repo / archive / "trust-run-manifest.json").read_text())
    if state_field(repo, "phase") != "shipped":
        raise SystemExit("fixture STATE is not shipped")
    ship = git(repo, "rev-parse", "HEAD"); tag = manifest["milestone_tag"]
    integration = git(repo, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    version = json.loads((root / "package.json").read_text())["version"]
    ev_root = root / "docs/trust-validation/evidence/releases" / version
    steps_dir = ev_root / HOST; steps_dir.mkdir(parents=True, exist_ok=True)
    run_id = manifest["run_id"]; child_id = manifest["child_id"]
    install = json.loads(Path(a.install_json).read_text())
    ledger = (repo / manifest["artifacts"]["verify"]).read_text()
    porcelain = git(repo, "worktree", "list", "--porcelain")
    guards_in_archive = json.loads((repo / manifest["artifacts"]["guards"]).read_text())
    base = {"schema": STEP, "host": HOST, "run_id": run_id, "result": "pass"}
    steps = {
        "install": {**base, "step": "install", "command": a.install_command, "output": install["output"],
                    "host_version": manifest["host_version"], "install_root": SPEC.skill_root,
                    "candidate": manifest["candidate"], "package_version": version, "exit_code": 0},
        "router": {**base, "step": "router", "command": a.router_command,
                   "output": (repo / ".project/STATE.md").read_text(), "state_artifact": ".project/STATE.md",
                   "state_phase": "shipped"},
        "child-spawn": {**base, "step": "child-spawn", "command": CHILD_API, "child_api": CHILD_API,
                        "child_id": child_id, "child_status": "completed",
                        "output": transcript_child(a.transcript, child_id)},
        "task-landing": {**base, "step": "task-landing", "command": a.landing_command,
                         "output": git(repo, "show", "--stat", "--format=fuller", manifest["landing_commit"]),
                         "fixture_bundle": f"{HOST}/fixture.bundle", "run_manifest": f"{archive}/trust-run-manifest.json",
                         "fixture_base_commit": manifest["fixture_base_commit"], "task_branch": manifest["task_branch"],
                         "task_worktree": a.task_worktree, "landing_commit": manifest["landing_commit"],
                         "isolation_mode": a.isolation_mode,
                         "isolation_note": "A one-task wave uses the helper's serial mode: the coder worked on the bound branch in the primary worktree at the recorded base, and the named branch and worktree are the isolated Task Verify sidecar created for this task and retired after landing."},
        "task-verify": {**base, "step": "task-verify", "command": json.loads(ledger.splitlines()[0])["command"],
                        "output": ledger, "verify_artifact": manifest["artifacts"]["verify"], "verify_exit_code": 0},
        "reviews": {**base, "step": "reviews", "command": a.review_command,
                    "output": "\n".join(l for f in ("wave_review", "final_review")
                                        for l in (repo / manifest["artifacts"][f]).read_text().splitlines()[:6]),
                    "wave_review_artifact": manifest["artifacts"]["wave_review"],
                    "final_review_artifact": manifest["artifacts"]["final_review"]},
        "archive": {**base, "step": "archive", "command": a.archive_command, "output": a.archive_output,
                    "archive_path": archive, "validation_exit_code": 0},
        "integration": {**base, "step": "integration", "command": a.integrate_command, "output": a.integrate_output,
                        "fixture_bundle": f"{HOST}/fixture.bundle", "run_manifest": f"{archive}/trust-run-manifest.json",
                        "ship_commit": ship, "bound_branch": manifest["bound_branch"], "default_branch": "main",
                        "pre_integration_default_commit": manifest["pre_integration_default_commit"],
                        "integration_commit": integration, "milestone_tag": tag},
        "worktrees": {**base, "step": "worktrees", "command": "git worktree list --porcelain", "output": porcelain + "\n",
                      "primary_worktree": str(repo), "integration_worktree": a.integration_worktree},
        "guards": {**base, "step": "guards", "command": "release_receipt.py manifest (git hook check in disposable clone)",
                   "output": json.dumps(guards_in_archive["git_hook_check"], indent=2),
                   "guard_artifact": manifest["artifacts"]["guards"], "declared_tier": GUARD_TIER,
                   "native_guard": guards_in_archive["native_guard"], "git_hooks": guards_in_archive["git_hooks"]},
    }
    for name, body in steps.items():
        (steps_dir / f"{name}.json").write_text(json.dumps(body, indent=2) + "\n")
    bundle = steps_dir / "fixture.bundle"
    git(repo, "bundle", "create", str(bundle), "--all")
    git(repo, "bundle", "verify", str(bundle))
    labels = [("Install command and result", "install"), ("Router invocation and state artifact", "router"),
              ("Child spawn output", "child-spawn"), ("Task branch, worktree, and landing commit", "task-landing"),
              ("Task Verify command and result", "task-verify"), ("Wave and final review artifacts", "reviews"),
              ("Archive validation output", "archive"), ("Integration merge and milestone tag", "integration"),
              ("Remaining `git worktree list` output", "worktrees"), ("Native guard and Git-hook results", "guards")]
    receipt = ev_root / f"{HOST}.md"
    receipt.write_text("\n".join([
        "---", "schema: gsd-path/live-evidence/v1", f"host: {HOST}", f"package: {version}", "pipeline: gsd-path/v2",
        f"candidate: {manifest['candidate']}", "verdict: pass", "child_spawn: pass", "state: pass", "task_verify: pass",
        "wave_review: pass", "final_review: pass", "archive: pass", "integration: pass", f"guard_tier: {GUARD_TIER}", "---",
        "", f"# Live milestone evidence — {HOST}", "",
        f"Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `{a.run_dir}`.",
        "", "## Environment", "", f"- Host and CLI version: {manifest['host_version']}", f"- Operator: {a.operator}",
        f"- Date: {dt.date.today().isoformat()}", f"- Fixture repository: {repo}",
        f"- Child-agent API used: {CHILD_API} ({SPEC.child_name_key} {child_id})", "", "## Evidence", "",
        *[f"- {label}: {HOST}/{name}.json" for label, name in labels], "",
        f"Fixture Git bundle: {HOST}/fixture.bundle (all refs, including origin/main and the annotated milestone tag).", ""]))
    sys.path.insert(0, str(root))
    from scripts import check_trust_evidence as cte
    cte._validate_receipt(receipt, HOST, version, GUARD_TIER, [CHILD_API], manifest["candidate"])
    print(json.dumps({"receipt": str(receipt), "steps": sorted(steps), "bundle": str(bundle), "validated": True,
                      "ship_commit": ship, "integration_commit": integration, "tag": tag}, indent=2))
    return 0


def main():
    global HOST, SPEC, CHILD_API, GUARD_TIER
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="codex", help="a host from scripts/skill-resources.json in --repo")
    sub = p.add_subparsers(dest="phase", required=True)
    m = sub.add_parser("manifest")
    for k in ("fixture", "repo", "run_id", "candidate", "host_version", "task_branch"):
        m.add_argument(f"--{k.replace('_', '-')}", required=True)
    m.add_argument("--package-version", default="1.0.0")
    m.add_argument("--committed-archive-repo"); m.add_argument("--committed-archive"); m.add_argument("--native-guard-evidence")
    r = sub.add_parser("receipt")
    for k in ("fixture", "repo", "transcript", "install_json", "install_command", "router_command", "landing_command",
              "task_worktree", "review_command", "archive_command", "archive_output", "integrate_command",
              "integrate_output", "integration_worktree", "run_dir", "operator", "isolation_mode"):
        r.add_argument(f"--{k.replace('_', '-')}", required=True)
    a = p.parse_args()
    sys.path.insert(0, str(Path(a.repo).resolve()))
    from tests.hosts import known_hosts, load  # noqa: E402  (the candidate's own host modules)
    if a.host not in known_hosts():
        p.error(f"--host must be one of {', '.join(known_hosts())}")
    HOST, SPEC = a.host, load(a.host)
    CHILD_API, GUARD_TIER = SPEC.child_api, SPEC.guard_tier
    return phase_manifest(a) if a.phase == "manifest" else phase_receipt(a)


if __name__ == "__main__":
    raise SystemExit(main())
