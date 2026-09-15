"""Prepare and measure matched Codex runs without grading their own prose.

Live execution is explicit. This module is not invoked by the ordinary suite.
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
from tests.dogfood import FIXTURE_SCRIPT
from tests.widget_acceptance import evaluate
from scripts import check_trust_evidence

REQUIREMENTS = """Implement the widget-counter CLI in count.py. Without arguments print
0 widgets. An integer argument prints that count followed by ' widgets'.
Add --json, accepted before or after the count, producing exactly a JSON object
with integer field widgets. The default count is zero; negative integers are
valid. Invalid input must exit nonzero with a useful stderr error.
Preserve plain text output. Add your own useful tests. No new dependencies.
Do not read another comparison arm or the evaluator's acceptance tests.
Record failures honestly. Per-task token budget 4000; session budget 30000,
as required by the owner. Do not invent additional time or retry limits.
"""


def command(arguments: list, cwd: Path) -> str:
    return subprocess.run(arguments, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def prepare(directory: Path, candidate: Path) -> dict:
    if directory.exists():
        raise ValueError("evaluation directory already exists; use a new directory")
    if command(["git", "status", "--porcelain"], candidate):
        raise ValueError("commit candidate changes before preparing a reproducible evaluation")
    revision = command(["git", "rev-parse", "HEAD"], candidate)
    directory.mkdir(parents=True)
    plugin = directory / "plugin"
    command(["git", "clone", "--quiet", "--no-hardlinks", str(candidate), str(plugin)], directory)
    seed = directory / "seed"
    seed.mkdir()
    command(["git", "init", "-q", "-b", "main"], seed)
    command(["git", "config", "user.name", "Evaluation"], seed)
    command(["git", "config", "user.email", "evaluation@example.invalid"], seed)
    (seed / "count.py").write_text(FIXTURE_SCRIPT)
    (seed / "README.md").write_text("# Widget Counter\n\nRun `python3 count.py 3` to print `3 widgets`.\n")
    command(["git", "add", "."], seed)
    command(["git", "commit", "-qm", "fixture: widget counter"], seed)
    fixture = command(["git", "rev-parse", "HEAD"], seed)
    for mode in ("path", "direct"):
        setup_started = time.monotonic()
        arm = directory / mode
        arm.mkdir()
        remote = arm / "origin.git"
        repo = arm / "repo"
        command(["git", "clone", "--quiet", "--bare", str(seed), str(remote)], directory)
        command(["git", "clone", "--quiet", str(remote), str(repo)], directory)
        command(["git", "config", "user.name", "Evaluation"], repo)
        command(["git", "config", "user.email", "evaluation@example.invalid"], repo)
        if mode == "path":
            install_command = ["node", str(plugin / "scripts/install.mjs"), "--codex", "--local",
                               "--project", str(repo), "--hooks", "--no-color"]
            install_output = command(install_command, repo)
            write_json(arm / "install.json", {"command": install_command, "output": install_output,
                       "exit_code": 0, "candidate": revision, "install_root": str(repo)})
            command(["git", "add", "."], repo)
            command(["git", "commit", "-qm", "fixture: install candidate"], repo)
            command(["git", "push", "origin", "main"], repo)
        prompt = REQUIREMENTS
        if mode == "path":
            prompt = (f"Explicitly invoke the candidate skill at {repo / '.agents/skills/gsd-path/SKILL.md'}. "
                      "Read that exact file first. Resolve bundled phase contracts and helpers from this "
                      "candidate installation; global skills with the same names are not the candidate.\n\n"
                      + prompt + "\nUse the standard lane, full review, no optional panel, and direct integration to the existing local origin. Use real native children and canonical helpers. Stop at owner approval gates with reviewable artifacts; never invent approvals or phase receipts.\n")
        else:
            prompt += "\nImplement directly with normal Codex tools; do not initialize GSD Path. Commit the finished product and tests.\n"
        prompt += ("\nUse ordinary tools in the correct worktree. The evaluator records native events "
                   "and elapsed execution time externally; do not wrap commands for measurement or "
                   "invent activity categories or durations.\n")
        (arm / "prompt.txt").write_text(prompt)
        write_json(arm / "setup.json", {"elapsed_seconds": time.monotonic() - setup_started})
    manifest = {"candidate": revision, "fixture": fixture, "created_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    write_json(directory / "manifest.json", manifest)
    return manifest


def activity(arm: Path, category: str, arguments: list) -> int:
    started = time.monotonic()
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    result = subprocess.run(arguments, cwd=arm / "repo")
    event = {"category": category, "command": arguments, "started_at": stamp,
             "duration_seconds": time.monotonic() - started, "exit_code": result.returncode,
             "category_source": "caller-declared", "duration_source": "subprocess-clock"}
    with (arm / "activities.jsonl").open("a") as output:
        output.write(json.dumps(event) + "\n")
    return result.returncode


def run(arm: Path, model: str, reasoning: str, sandbox: str, resume: str = None, prompt_file: Path = None) -> dict:
    settings = {"model": model, "reasoning": reasoning, "sandbox": sandbox,
                "cli": command(["codex", "--version"], arm)}
    for existing in arm.parent.glob("*/settings.json"):
        if json.loads(existing.read_text()) != settings:
            raise ValueError("comparison settings differ from an existing arm")
    write_json(arm / "settings.json", settings)
    run_dir = arm / ("run-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    run_dir.mkdir()
    arguments = ["codex", "exec", "--sandbox", sandbox, "--add-dir", str(arm)]
    if resume:
        arguments += ["resume", resume]
    arguments += ["--ignore-user-config", "--model", model, "-c", f'model_reasoning_effort="{reasoning}"', "--json"]
    arguments += ["-"]
    prompt = (prompt_file or arm / "prompt.txt").read_text()
    (run_dir / "prompt.txt").write_text(prompt)
    started = time.monotonic()
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    with (run_dir / "stderr.txt").open("w") as errors, (run_dir / "events.jsonl").open("w") as events:
        process = subprocess.Popen(arguments, cwd=arm / "repo", stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=errors, text=True)
        process.stdin.write(prompt)
        process.stdin.close()
        for line in process.stdout:
            events.write(json.dumps({"elapsed_seconds": time.monotonic() - started, "raw": line.rstrip("\n")}) + "\n")
            events.flush()
        code = process.wait()
    result = {**settings, "command": arguments, "exit_code": code, "started_at": started_at,
              "elapsed_seconds": time.monotonic() - started,
              "head": command(["git", "rev-parse", "HEAD"], arm / "repo")}
    write_json(run_dir / "run.json", result)
    return result


def report(directory: Path, receipt: Path = None) -> dict:
    result = {"manifest": json.loads((directory / "manifest.json").read_text()), "arms": {}}
    for mode in ("path", "direct"):
        arm = directory / mode
        runs = [json.loads(path.read_text()) for path in sorted(arm.glob("run-*/run.json"))]
        observed = []
        usage = []
        for path in sorted(arm.glob("run-*/events.jsonl")):
            for line in path.read_text().splitlines():
                try:
                    event = json.loads(json.loads(line)["raw"])
                except (ValueError, KeyError):
                    continue
                if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                    usage.append(event["usage"])
        activity_path = arm / "activities.jsonl"
        if activity_path.exists():
            observed = [json.loads(line) for line in activity_path.read_text().splitlines()]
        repo = arm / "repo"
        product = evaluate(repo)
        result["arms"][mode] = {
            "setup": json.loads((arm / "setup.json").read_text()) if (arm / "setup.json").exists() else None,
            "product": product, "head": command(["git", "rev-parse", "HEAD"], repo),
            "dirty": bool(command(["git", "status", "--porcelain"], repo)),
            "elapsed_seconds": sum(run["elapsed_seconds"] for run in runs) if runs else None,
            "delivery_elapsed_seconds": (
                (dt.datetime.fromisoformat(runs[-1]["started_at"]) - dt.datetime.fromisoformat(runs[0]["started_at"])).total_seconds()
                + runs[-1]["elapsed_seconds"] if runs else None),
            "activities": observed, "usage": usage or None,
            "activity_seconds": {category: sum(event["duration_seconds"] for event in observed if event["category"] == category)
                                 if any(event["category"] == category for event in observed) else None
                                 for category in ("implementation", "verification", "review")},
            "failed_commands": sum(event["exit_code"] != 0 for event in observed),
            "pipeline": "unverifiable" if mode == "path" else "not-applicable",
            "measurement": "partial" if runs else "unavailable", "runs": runs,
        }
    if receipt is not None:
        plugin = directory / "plugin"
        manifest = json.loads((plugin / "scripts/skill-resources.json").read_text())
        version = json.loads((plugin / "package.json").read_text())["version"]
        host = manifest["hosts"]["codex"]
        try:
            check_trust_evidence._validate_receipt(receipt.resolve(), "codex", version,
                host["guard_tier"], host["child_apis"], result["manifest"]["candidate"])
        except check_trust_evidence.EvidenceError as error:
            result["arms"]["path"]["pipeline"] = "fail"
            result["arms"]["path"]["pipeline_error"] = str(error)
        else:
            result["arms"]["path"]["pipeline"] = "pass"
        result["arms"]["path"]["receipt"] = str(receipt.resolve())
    arms = result["arms"].values()
    if any(arm["product"]["verdict"] == "fail" or arm["pipeline"] == "fail"
           or any(run["exit_code"] != 0 for run in arm["runs"]) for arm in arms):
        result["exit_code"] = 1
    elif result["arms"]["path"]["pipeline"] != "pass" or any(not arm["runs"] for arm in arms):
        result["exit_code"] = 3
    else:
        result["exit_code"] = 0
    write_json(directory / "comparison.json", result)
    lines = ["# Codex delivery comparison", "", "Observed fixture results only; no optimality claim.", "",
             "| Arm | Product | Agent elapsed seconds | Measurement | Pipeline |",
             "|---|---|---|---|---|"]
    for mode, arm in result["arms"].items():
        lines.append(f"| {mode} | {arm['product']['verdict']} | {arm['elapsed_seconds']} | {arm['measurement']} | {arm['pipeline']} |")
    lines += ["", "Activity categories are caller-declared; durations are measured subprocess time. Unwrapped work is unclassified.",
              "Summed activity durations can overlap. Missing usage and category durations are unavailable, not zero.",
              "Pipeline trust requires the separate canonical milestone receipt validator; CLI exit and product correctness do not establish it."]
    (directory / "comparison.md").write_text("\n".join(lines) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    prep = actions.add_parser("prepare")
    prep.add_argument("--directory", type=Path, required=True)
    prep.add_argument("--candidate", type=Path, required=True)
    execute = actions.add_parser("run")
    execute.add_argument("--arm", type=Path, required=True)
    execute.add_argument("--model", required=True)
    execute.add_argument("--reasoning", required=True)
    execute.add_argument("--sandbox", choices=("read-only", "workspace-write", "danger-full-access"), required=True)
    execute.add_argument("--resume")
    execute.add_argument("--prompt-file", type=Path)
    measure = actions.add_parser("activity")
    measure.add_argument("--arm", type=Path, required=True)
    measure.add_argument("--category", choices=("implementation", "verification", "review"), required=True)
    measure.add_argument("command", nargs=argparse.REMAINDER)
    summary = actions.add_parser("report")
    summary.add_argument("--directory", type=Path, required=True)
    summary.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare(args.directory.resolve(), args.candidate.resolve())
    elif args.action == "run":
        result = run(args.arm.resolve(), args.model, args.reasoning, args.sandbox, args.resume, args.prompt_file)
    elif args.action == "activity":
        arguments = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not arguments:
            parser.error("activity requires a command after --")
        return activity(args.arm.resolve(), args.category, arguments)
    else:
        result = report(args.directory.resolve(), args.receipt)
    print(json.dumps(result, indent=2))
    return result.get("exit_code", 0)


if __name__ == "__main__":
    raise SystemExit(main())
