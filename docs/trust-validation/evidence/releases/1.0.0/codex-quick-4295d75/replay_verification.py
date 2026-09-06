#!/usr/bin/env python3
"""Replay a shipped gsd-path milestone's verification claims against its actual code.

For every archived milestone in <repo>/.project/archive/*:
  1. FINAL.md Reviewed HEAD must be an ancestor of HEAD, and the product files
     (everything outside .project/) must be byte-identical between Reviewed HEAD
     and HEAD. Otherwise the review verified different code than what shipped.
  2. Every verify-ledger entry is re-executed at its recorded commit in a fresh
     temporary clone. Exit code must agree with the recorded result; when the
     ledger or a retained task receipt recorded stdout/stderr, those must match too.
  3. The independent widget oracle runs against HEAD (counter fixtures only).
Prints JSON; exit 1 on any mismatch.
"""
import hashlib, json, re, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, sys.argv[2] if len(sys.argv) > 2 else ".")
from tests.widget_acceptance import evaluate  # noqa: E402


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)


def run_at(repo, commit, command):
    """Run a command in a temporary clone without modifying the source repository."""
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
        wt = Path(tmp) / "wt"
        git(repo, "clone", "-q", "--no-hardlinks", "--no-checkout", str(repo), str(wt)).check_returncode()
        git(wt, "checkout", "-q", "--detach", commit).check_returncode()
        return subprocess.run(command, shell=True, cwd=wt, capture_output=True, text=True)


def receipt_matches(repo, commit, receipt):
    for path, expected in receipt.get("sha256", {}).items():
        if Path(path).parts[0] == ".project":
            continue
        content = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=repo, capture_output=True)
        if content.returncode or hashlib.sha256(content.stdout).hexdigest() != expected:
            return False
    return receipt.get("commit", commit) == commit


def replay(repo, receipt_paths=None):
    repo = Path(repo).resolve()
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    out = {"repo": str(repo), "head": head, "milestones": [], "oracle": None, "mismatches": []}
    if receipt_paths is None:
        receipt_paths = sorted(Path(__file__).resolve().parent.glob("task-verify*.json"))
    receipts = [(Path(path), json.loads(Path(path).read_text())) for path in receipt_paths]
    archives = sorted(path for path in (repo / ".project/archive").glob("*") if path.is_dir())
    if not archives:
        out["mismatches"].append("no milestone directories found under .project/archive")
    for archive in archives:
        final = (archive / "review/FINAL.md").read_text()
        reviewed = re.search(r"^Reviewed HEAD:\s*([0-9a-f]{40})", final, re.M).group(1)
        verdict = re.search(r"^Overall verdict:\s*(\S+)", final, re.M).group(1)
        m = {"archive": archive.name, "reviewed_head": reviewed, "final_verdict": verdict, "ledger": []}
        m["reviewed_is_ancestor"] = git(repo, "merge-base", "--is-ancestor", reviewed, head).returncode == 0
        drift = git(repo, "diff", "--name-only", reviewed, head, "--", ".", ":(exclude).project").stdout.split()
        m["product_drift_since_review"] = drift
        if not m["reviewed_is_ancestor"] or drift:
            out["mismatches"].append(f"{archive.name}: reviewed HEAD {reviewed[:7]} does not match shipped product")
        # Walkthroughs: every ```jsonl block in a wave review records command/exit/stdout/stderr.
        m["walkthroughs"] = []
        for review in sorted((archive / "review").glob("wave-*.md")):
            text = review.read_text()
            at = re.search(r"^Reviewed HEAD:\s*([0-9a-f]{40})", text, re.M).group(1)
            for block in re.findall(r"```jsonl\n(.*?)```", text, re.S):
                for line in block.splitlines():
                    w = json.loads(line)
                    r = run_at(repo, at, w["command"])
                    agrees = (r.returncode, r.stdout, r.stderr) == (w["exit"], w["stdout"], w["stderr"])
                    m["walkthroughs"].append({"review": review.name, "command": w["command"], "agrees": agrees,
                                              **({} if agrees else {"replay": [r.returncode, r.stdout, r.stderr]})})
                    if not agrees:
                        out["mismatches"].append(f"{archive.name}: {review.name} recorded {w['command']!r} differs from replay at {at[:7]}")
        ledger = archive / "build/verify-ledger.jsonl"
        for line in ledger.read_text().splitlines() if ledger.exists() else []:
            e = json.loads(line)
            r = run_at(repo, e["commit"], e["command"])
            expect_pass = e["result"] == "pass"
            entry = {"command": e["command"], "commit": e["commit"], "recorded": e["result"],
                     "replay_exit": r.returncode, "exit_agrees": (r.returncode == 0) == expect_pass}
            ex = e.get("execution")
            if ex is None:
                candidates = [(path, receipt) for path, receipt in receipts
                              if receipt.get("command") == e["command"]]
                matches = [(path, receipt) for path, receipt in candidates
                           if receipt_matches(repo, e["commit"], receipt)]
                if len(matches) == 1:
                    path, ex = matches[0]
                    entry["output_source"] = path.name
                elif candidates:
                    out["mismatches"].append(f"{archive.name}: no unique task receipt matches {e['command']!r} at {e['commit'][:7]}")
            else:
                entry["output_source"] = "ledger.execution"
            if ex is not None:
                entry["exit_agrees"] = entry["exit_agrees"] and r.returncode == ex["exit_code"]
                # unittest prints wall time ("Ran 4 tests in 0.502s"); timing is not a verification claim.
                untimed = lambda s: re.sub(r" in \d+\.\d+s", " in <t>s", s.strip())
                entry["stdout_agrees"] = untimed(ex.get("stdout", "")) == untimed(r.stdout)
                entry["stderr_agrees"] = untimed(ex.get("stderr", "")) == untimed(r.stderr)
                if not entry["stderr_agrees"]:
                    entry["stderr_replay"] = r.stderr
            else:
                entry["output_comparison"] = "skipped: no matching execution receipt"
            if not all(v for k, v in entry.items() if k.endswith("_agrees")):
                out["mismatches"].append(f"{archive.name}: ledger replay differs for {e['command']!r} at {e['commit'][:7]}")
            m["ledger"].append(entry)
        out["milestones"].append(m)
    if (repo / "count.py").exists():
        out["oracle"] = evaluate(repo)
        if out["oracle"]["verdict"] != "pass":
            out["mismatches"].append("independent widget oracle failed at HEAD")
    else:
        out["oracle"] = {"verdict": "skipped", "reason": "count.py is absent"}
    out["verdict"] = "pass" if not out["mismatches"] else "fail"
    return out


if __name__ == "__main__":
    result = replay(sys.argv[1], [sys.argv[3]] if len(sys.argv) > 3 else None)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["verdict"] == "pass" else 1)
