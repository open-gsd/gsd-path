#!/usr/bin/env python3
"""Live dogfood: run a real AI host against a fixture repo and check the
disk contract. Implements the "dispatch smoke + guards" bar from
docs/trust-validation/manual-dogfood-evidence-bar.md.

    python3 tests/dogfood.py --host claude          # needs `claude` on PATH + auth
    python3 tests/dogfood.py --host codex           # needs `codex` on PATH + auth
    python3 tests/dogfood.py --host claude --evidence docs/trust-validation/evidence

Installs GSD Path *locally* into a throwaway repo (never touches global
skill roots), invokes the docs-audit skill headlessly, then asserts:
  1. .project/research/DOCS-AUDIT.md exists
  2. it passes scripts/check_docs_audit.py (the contract's artifact gate)
  3. git pre-commit guard blocks a staged archive modification
  4. a commit outside the archive succeeds
Writes an evidence record (date, host, commands, pass/fail, paths, output)
and exits nonzero on any failed check.
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import check_docs_audit

INSTALLER = ROOT / "scripts" / "install.mjs"
RESOURCE_MANIFEST = json.loads(
    (ROOT / "scripts" / "skill-resources.json").read_text(encoding="utf-8")
)
DECLARED_HOSTS = tuple(RESOURCE_MANIFEST["hosts"])

HOSTS = {
    host: {
        "skill_root": config["local_root"],
        "evidence_route": "manual",
    }
    for host, config in RESOURCE_MANIFEST["hosts"].items()
}
HOSTS.update({
    "claude": {
        "skill_root": ".claude/skills",
        "evidence_route": "automated",
        "spawn_api": "Claude Code headless (`claude -p`), Agent tool for children",
        "command": lambda prompt: [
            "claude", "-p", prompt, "--dangerously-skip-permissions", "--output-format", "text",
        ],
    },
    "codex": {
        "skill_root": ".agents/skills",
        "evidence_route": "automated",
        "spawn_api": "Codex CLI headless (`codex exec --full-auto`), collaboration spawn for children",
        "command": lambda prompt: ["codex", "exec", "--full-auto", prompt],
    },
})

PROMPT = (
    "/gsd-path-docs-audit\n\nRun the GSD Path docs audit for this repository in "
    "standalone mode. Write .project/research/DOCS-AUDIT.md, then stop."
)

FIXTURE_README = """# Widget Counter

A tiny CLI that counts widgets.

## Usage

Run `python3 count.py 3` and it prints `3 widgets`.

## Status

The `--json` flag prints machine-readable output.
"""

FIXTURE_SCRIPT = """import sys
n = int(sys.argv[1]) if len(sys.argv) > 1 else 0
print(f"{n} widgets")
"""

STATE = """---
pipeline: gsd-path/v2
project: widget-counter
milestone: m001-count
phase: define
status: done
branch: null
archive: null
---

# Project State

## Log

- {today} — define — fixture state for dogfood
"""


def run(cmd, cwd, timeout=None, env=None):
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def git(repo, *args):
    return run(["git", *args], repo)


def make_fixture(repo, today):
    repo.mkdir(parents=True)
    (repo / "README.md").write_text(FIXTURE_README, encoding="utf-8")
    (repo / "count.py").write_text(FIXTURE_SCRIPT, encoding="utf-8")
    (repo / ".project" / "research").mkdir(parents=True)
    (repo / ".project" / "archive" / "001-seed").mkdir(parents=True)
    (repo / ".project" / "archive" / "001-seed" / "NOTE.md").write_text(
        "archived\n", encoding="utf-8"
    )
    (repo / ".project" / "STATE.md").write_text(STATE.format(today=today), encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "dogfood@example.invalid")
    git(repo, "config", "user.name", "Dogfood")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "fixture")


def check_audit(repo):
    audit = repo / ".project" / "research" / "DOCS-AUDIT.md"
    if not audit.is_file():
        return [("DOCS-AUDIT.md exists", False, str(audit))]
    code, out = run([sys.executable, str(ROOT / "scripts" / "check_docs_audit.py"), "--repo", str(repo)], repo)
    correct = False
    detail = "README's --json feature must be aspirational with count.py evidence"
    if code == 0:
        docs = check_docs_audit._doc_claims(check_docs_audit._sections(audit.read_text(encoding="utf-8")))
        claims = [claim for claim in docs.get("README.md", []) if "--json" in claim["claim"]]
        correct = bool(claims) and all(
            claim["verdict"] == "aspirational" and re.search(r"\bcount\.py\b", claim["evidence"])
            for claim in claims
        )
    return [
        ("DOCS-AUDIT.md exists", True, str(audit)),
        ("DOCS-AUDIT.md passes check_docs_audit.py", code == 0, out.strip()[-300:]),
        ("planted --json claim is correctly classified", correct, detail),
    ]


def audit_notes(repo):
    """Advisory signal, not a gate: the fixture README plants one aspirational claim (--json)."""
    text = (repo / ".project" / "research" / "DOCS-AUDIT.md").read_text(encoding="utf-8")
    verdicts = sorted(set(re.findall(r"\| (verified|stale|aspirational|unverifiable) \|", text)))
    return [f"verdicts seen: {', '.join(verdicts) or 'none'}"]


def check_guards(repo):
    findings = []
    note = repo / ".project" / "archive" / "001-seed" / "NOTE.md"
    note.write_text("tampered\n", encoding="utf-8")
    git(repo, "add", "-A", ".project/archive")
    code, out = git(repo, "commit", "-qm", "tamper archive")
    findings.append(("pre-commit blocks archive modification", code != 0, out.strip()[-300:]))
    git(repo, "reset", "-q", "--hard", "HEAD")
    (repo / "CHANGELOG.md").write_text("- dogfood\n", encoding="utf-8")
    git(repo, "add", "CHANGELOG.md")
    code, out = git(repo, "commit", "-qm", "outside archive")
    findings.append(("commit outside archive succeeds", code == 0, out.strip()[-300:]))
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", choices=sorted(HOSTS), required=True)
    parser.add_argument("--timeout", type=int, default=900, help="seconds for the host run")
    parser.add_argument("--evidence", type=Path, help="directory to write the evidence record into")
    parser.add_argument("--keep", action="store_true", help="keep the fixture repo")
    args = parser.parse_args(argv)
    host = HOSTS[args.host]
    if host["evidence_route"] == "manual":
        print(
            f"manual: `{args.host}` has no verified headless dogfood adapter; "
            "use docs/trust-validation/LIVE-EVIDENCE-TEMPLATE.md"
        )
        return 3
    if shutil.which(args.host) is None:
        print(f"skip: `{args.host}` not on PATH")
        return 3

    today = dt.date.today().isoformat()
    base = Path(tempfile.mkdtemp(prefix=f"gsd-dogfood-{args.host}-"))
    repo = base / "repo"
    make_fixture(repo, today)
    commands = []

    install_cmd = ["node", str(INSTALLER), f"--{args.host}", "--local", "--project", str(repo), "--hooks", "--no-color"]
    code, install_out = run(install_cmd, repo)
    commands.append({"command": " ".join(install_cmd), "exit": code, "output": install_out})
    findings = [
        ("install succeeded", code == 0, install_out.strip()[-300:]),
        ("skills installed locally", (repo / host["skill_root"] / "gsd-path-docs-audit" / "SKILL.md").is_file(), host["skill_root"]),
        ("guard files present", all((repo / p).exists() for p in [".gsd-path/guard_hook.py", ".gsd-path/git_guard.py", ".git/hooks/pre-commit"]), ".gsd-path/, .git/hooks/"),
    ]
    notes = []
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "install gsd-path")

    host_cmd = host["command"](PROMPT)
    host_out = ""
    if code == 0:
        try:
            code, host_out = run(host_cmd, repo, timeout=args.timeout, env={**os.environ, "CI": "1"})
        except subprocess.TimeoutExpired as error:
            code, host_out = 124, f"timeout after {args.timeout}s\n{error.stdout or ''}"
        commands.append({"command": " ".join(host_cmd[:3]) + " …", "exit": code, "output": host_out[-4000:]})
        findings.append(("host run exited 0", code == 0, host_out.strip()[-300:]))
        findings.extend(check_audit(repo))
        if findings[-1][1]:
            notes.extend(audit_notes(repo))
    findings.extend(check_guards(repo))

    passed = all(ok for _, ok, _ in findings)
    for check, ok, detail in findings:
        print(f"  {'✓' if ok else '✗'} {check}  {detail if not ok else ''}".rstrip())
    for note in notes:
        print(f"  · {note}")
    print(f"\n{args.host}: {'PASS' if passed else 'FAIL'}  ({repo if args.keep else 'fixture removed'})")

    if args.evidence:
        args.evidence.mkdir(parents=True, exist_ok=True)
        path = args.evidence / f"{today}-{args.host}.md"
        lines = [
            f"# Dogfood — {args.host} — {today}",
            "",
            f"- Verdict: **{'pass' if passed else 'fail'}**",
            f"- Spawn API: {host['spawn_api']}",
            f"- Fixture: `{repo}`",
            *[f"- Note: {note}" for note in notes],
            "",
            "| Check | Pass | Detail |",
            "|---|---|---|",
            *[f"| {c} | {'yes' if ok else 'no'} | {str(d).replace('|', '/')[:120]} |" for c, ok, d in findings],
            "",
            "## Commands",
            "",
            *[f"- `{c['command']}` → exit {c['exit']}" for c in commands],
            "",
            "## Host output (tail)",
            "",
            "```",
            host_out[-3000:],
            "```",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"evidence: {path}")

    if not args.keep:
        shutil.rmtree(base, ignore_errors=True)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
