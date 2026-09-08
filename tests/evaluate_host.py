#!/usr/bin/env python3
"""Drive a host with a headless command through the quick scenario for release evidence.

    python3 -B tests/evaluate_host.py prepare --host claude --directory /abs/new --candidate .
    python3 -B tests/evaluate_host.py run --host claude --directory /abs/new [--resume ID --prompt-file F]
    python3 -B tests/evaluate_host.py child --host claude --directory /abs/new --child-id build_T001

Host setup, capabilities, resume behavior, and live verification limits are recorded
in tests/hosts/<host>.py SPEC and its docstrings.

Live execution is explicit and opt-in; tests/test_host_*.py never invokes a host.
The evaluator answers owner gates with follow-up prompts via --prompt-file. Nothing here grades
the run or assembles the complete release receipt: the evaluator supplies guard
evidence and the archive JSON files requested by RELEASE_ADDENDUM.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.dogfood import FIXTURE_SCRIPT  # noqa: E402
from tests.evaluate_features import SCENARIOS  # noqa: E402
from tests.hosts import load  # noqa: E402

RELEASE_ADDENDUM = """
RELEASE-EVIDENCE ADDENDUM (overrides scenario step 5 and refines step 4):
- This run also produces the release receipt for this host. Keep every canonical
  artifact exactly as the pinned skill writes it.
- Dispatch every child through the host's declared child API with the logical task
  name as its identifier, and record that same name in the task file agent field,
  as the dispatch contract requires. When the host offers a way to list child
  status, call it once after the coder reports completion.
- Step 4 changes: run the ship phase up to and including
  `archive_milestone.py prepare`, then STOP before render-manifest and report
  the archive path, STATE.archive, the task base and landing commits, the
  isolation branch and worktree that the task used, and this session id. The
  evaluator will place two JSON files inside the archive root, then tell you to
  resume with render-manifest, preflight, record-shipment, the ship commit,
  validate, integrate, and validate-integrated. After integration report the
  exact `git worktree list --porcelain` output.
- Skip scenario step 5 entirely; the evaluator owns guard evidence.
"""


def sh(args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def prepare(host, directory, candidate):
    spec = load(host)
    directory, candidate = Path(directory).resolve(), Path(candidate).resolve()
    if directory.exists():
        raise SystemExit("evaluation directory already exists; choose a new path")
    if sh(["git", "status", "--porcelain"], candidate):
        raise SystemExit("commit candidate changes before preparing a reproducible evaluation")
    revision = sh(["git", "rev-parse", "HEAD"], candidate)
    directory.mkdir(parents=True)
    plugin = directory / "plugin"
    sh(["git", "clone", "--quiet", "--no-hardlinks", str(candidate), str(plugin)], directory)
    spec_ = SCENARIOS["quick"]
    arm = directory / "quick"; repo = arm / "repo"; repo.mkdir(parents=True)
    g = lambda *a: sh(["git", *a], repo)
    g("init", "-q", "-b", "main"); g("config", "user.name", "Feature Evaluation"); g("config", "user.email", "evaluation@example.invalid")
    (repo / "README.md").write_text("# Feature evaluation fixture\n"); (repo / "count.py").write_text(FIXTURE_SCRIPT)
    g("add", "."); g("commit", "-qm", "fixture: initial product")
    remote = arm / "origin.git"; sh(["git", "clone", "--quiet", "--bare", str(repo), str(remote)], arm); g("remote", "add", "origin", str(remote))
    install_cmd = ["node", str(plugin / "scripts/install.mjs"), spec.install_flag, "--local", "--project", str(repo), "--hooks", "--no-color"]
    output = sh(install_cmd, repo)
    g("add", "."); g("commit", "-qm", "fixture: install pinned candidate"); g("push", "-q", "-u", "origin", "main")
    (arm / "install.json").write_text(json.dumps({"candidate": revision, "head": g("rev-parse", "HEAD"), "exit_code": 0,
                                                  "command": " ".join(install_cmd), "output": output}, indent=2) + "\n")
    skill = repo / spec.skill_root / "gsd-path" / "SKILL.md"
    prompt = f"""{spec.invocation}

Use ONLY the pinned local skill at {skill} and its sibling bundles. This is a
feature evaluation, not an update of the plugin. Use real native children and
canonical helpers. Do not change installed skills or hand-repair pipeline state.
No testing token/time limit is set. Do not invent limits, approvals or receipts.
Stop at reviewable owner gates. Remote actions are limited to the existing local
origin; any GitHub action needs separate explicit owner approval of its target.
Do not read evaluator tests or other scenario workspaces.

{spec_['request']}

Scenario steps:
""" + "\n".join(f"{i}. {s}" for i, s in enumerate(spec_["steps"], 1)) + f"""

At each named checkpoint, stop and identify the canonical artifacts for capture.
Use python3 {plugin / 'tests/evaluate_codex.py'} activity --arm {arm} --category
<implementation|verification|review> -- <command> for measured shell work. That
wrapper starts in the primary repo: select a sidecar cwd explicitly when needed.
""" + RELEASE_ADDENDUM
    (arm / "prompt.txt").write_text(prompt)
    (directory / "manifest.json").write_text(json.dumps({"schema": "gsd-path/feature-evaluation/v1", "candidate": revision,
                                                        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                                        "scenarios": ["quick"], "host": host}, indent=2) + "\n")
    return {"host": host, "candidate": revision, "repo": str(repo), "verified_live": spec.verified_live}


def run(host, directory, resume=None, prompt_file=None):
    spec = load(host)
    arm = Path(directory).resolve() / "quick"
    run_dir = arm / ("run-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")); run_dir.mkdir()
    prompt_path = run_dir / "prompt.txt"  # lives in the run dir: a host whose CLI writes files targets prompt_path.parent
    prompt_path.write_text(Path(prompt_file or arm / "prompt.txt").read_text())
    args = spec.command(prompt_path, resume)
    started = time.monotonic(); started_at = dt.datetime.now(dt.timezone.utc).isoformat(); lines = []
    with (run_dir / "stderr.txt").open("w") as err, (run_dir / "events.jsonl").open("w") as events:
        proc = subprocess.Popen(args, cwd=arm / "repo", stdin=subprocess.PIPE if spec.prompt_on_stdin else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=err, text=True)
        if spec.prompt_on_stdin:
            proc.stdin.write(prompt_path.read_text()); proc.stdin.close()
        for line in proc.stdout:
            line = line.rstrip("\n"); lines.append(line)
            events.write(json.dumps({"elapsed_seconds": time.monotonic() - started, "raw": line}) + "\n"); events.flush()
        code = proc.wait()
    parsed = spec.parse_events(lines)
    result = {"host": host, "command": args, "exit_code": code, "started_at": started_at,
              "elapsed_seconds": time.monotonic() - started, "head": sh(["git", "rev-parse", "HEAD"], arm / "repo"), **parsed}
    (run_dir / "run.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="action", required=True)
    for name in ("prepare", "run", "child"):
        s = sub.add_parser(name); s.add_argument("--host", required=True); s.add_argument("--directory", required=True)
        if name == "prepare": s.add_argument("--candidate", default=str(ROOT))
        if name == "run": s.add_argument("--resume"); s.add_argument("--prompt-file")
        if name == "child": s.add_argument("--child-id", required=True)
    a = p.parse_args(argv)
    if a.action == "prepare": out = prepare(a.host, a.directory, a.candidate)
    elif a.action == "run": out = run(a.host, a.directory, a.resume, a.prompt_file)
    else: out = load(a.host).bind_child(Path(a.directory).resolve(), a.child_id)
    print(json.dumps(out, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
