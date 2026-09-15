"""Reuse complete review evidence without another model review."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

if __package__:
    from scripts import _common
    from scripts import check_handoffs as contracts
    from scripts import build_state, isolation
else:
    import _common
    import check_handoffs as contracts
    import build_state
    import isolation


def _git(repo, *arguments):
    return subprocess.run(["git", "-C", str(repo), *arguments],
                          capture_output=True, text=True, check=True).stdout.strip()


def _reusable_wave(repo, expected_head):
    contracts._require_state(repo, "ship", "active", ".project")
    if _git(repo, "rev-parse", "HEAD") != expected_head:
        raise contracts.HandoffError("primary HEAD changed")
    intent = contracts._read(repo, ".project/intent/INTENT.md")
    if contracts._line_value(intent, "Lane:") != "quick":
        raise contracts.HandoffError("only a complete quick-lane wave can replace final review")
    plan = contracts._read(repo, ".project/plan/PLAN.md")
    depths, _ = contracts._plan_waves(plan)
    if depths != {1: "full"}:
        raise contracts.HandoffError("reuse requires one independently reviewed full wave")
    candidates = []
    for path in (repo / ".project/review").glob("wave-1.cycle*.md"):
        match = re.fullmatch(r"wave-1\.cycle([1-9]\d*)\.md", path.name)
        if match:
            candidates.append((int(match[1]), path))
    if not candidates:
        raise contracts.HandoffError("full wave review is missing")
    _, path = max(candidates)
    relative = path.relative_to(repo).as_posix()
    text = contracts._read(repo, relative)
    if contracts._line_value(text, "Review scope:") != "final":
        raise contracts.HandoffError("wave reviewer did not assess final scope")
    reviewed = contracts._reviewed_head(text, relative)
    _git(repo, "merge-base", "--is-ancestor", reviewed, expected_head)
    if _git(repo, "show", f"{expected_head}:{relative}") != text.strip():
        raise contracts.HandoffError("wave evidence differs from its committed version")
    bookkeeping = {
        ".project/STATE.md", relative, ".project/build/verify-ledger.jsonl",
        ".project/build/evidence.json",
    }
    changed = set(_git(repo, "diff", "--name-only", reviewed, expected_head).splitlines())
    if changed - bookkeeping:
        raise contracts.HandoffError("product or approved contracts changed after review")
    dirty = isolation.uncommitted_paths(repo)
    current_outputs = bookkeeping | {".project/review/FINAL.md", ".project/review/final-gap-1.md"}
    if dirty - current_outputs:
        raise contracts.HandoffError("review inputs have uncommitted changes")
    wave = contracts.validate_wave_evidence(repo, review=relative)
    criteria = contracts._success_criteria(intent)
    if wave["verdict"] != "pass" or set(wave["owned"]) != set(criteria):
        raise contracts.HandoffError("wave does not prove every success criterion")
    return relative, text, criteria, reviewed


def _final_view(relative, text, criteria, reviewed, head):
    coverage = contracts._section(text, "Intent coverage")
    headings = list(re.finditer(r"(?m)^### (SC[1-9]\d*) — (.+): pass\s*$", coverage))
    blocks = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(coverage)
        blocks[heading[1]] = coverage[heading.end():end]
    lines = ["# Final Review — reused full wave", "", f"Reviewed HEAD: {head}",
             "Overall verdict: pass", f"Source review: {relative}",
             f"Source commit: {reviewed}", "", "## Success criteria", ""]
    for criterion, title in criteria.items():
        block = blocks[criterion]
        evidence = " ".join(re.findall(r"(?m)^- ✅ (.+)$", block))
        fields = {}
        for field in ("Surface", "Check", "Observed"):
            if f"- **{field}**:" in block:
                fields[field] = contracts._raw_source_field(block, field, relative)
        if "Surface" in fields and not {"Check", "Observed"}.issubset(fields):
            raise contracts.HandoffError(f"{criterion} lacks its recorded surface walkthrough")
        lines += [f"### {criterion} — {title}", "", "- **Verdict**: met",
                  f"- **Check**: {fields.get('Check', 'none')}",
                  f"- **Observed**: {fields.get('Observed', evidence)}",
                  f"- **Reference**: {relative} — {criterion}",
                  "- **Finding**: none", "- **Fix direction**: none"]
        if "Surface" in fields:
            lines.append(f"- **Surface**: {contracts._unquoted(fields['Surface']).partition(',')[0]}")
        lines.append("")
    return "\n".join(lines)


def reuse_final(repo, expected_head):
    """Materialize a final view only when the existing proof still covers it."""
    repo = Path(repo).resolve()
    try:
        relative, text, criteria, reviewed = _reusable_wave(repo, expected_head)
        final = _final_view(relative, text, criteria, reviewed, expected_head)
        contracts.validate_final(repo, final_text=final)
        destination = repo / ".project/review/FINAL.md"
        if destination.is_symlink():
            raise contracts.HandoffError("FINAL.md must be a real file")
        if destination.exists() and destination.read_text() != final:
            raise contracts.HandoffError("existing final evidence needs explicit reconciliation")
        if not destination.exists():
            _common.atomic_write(destination, final)
        return {"reused": True, "path": str(destination), "source": relative,
                "source_commit": reviewed, "reviewed_head": expected_head}
    except (contracts.HandoffError, subprocess.CalledProcessError, OSError, KeyError) as error:
        return {"reused": False, "reason": str(error)}


def _gap_view(command, head, execution, waves):
    passed = execution["exit_code"] == 0
    return f"""# Gap Review — 1: project Verify

Reviewed HEAD: {head}
Gap verdict: {'pass' if passed else 'blocked'}
Risk: project Verify
Waves checked: {', '.join(str(wave) for wave in waves)}

## Checked evidence

- **Check**: `{command}`
- **Observed**: Exit {execution['exit_code']}; exact stdout and stderr are in the command/commit ledger entry.
- **Reference**: .project/build/verify-ledger.jsonl — {head}, command above

## Finding

- **Found**: Project Verify {'passed' if passed else 'failed'} at the reviewed commit.
- **Fix direction**: {'none' if passed else 'Resolve the recorded command failure before shipping.'}
"""


def _require_ship_inputs(repo, expected_head):
    contracts._require_state(repo, "ship", "active", ".project")
    if _git(repo, "rev-parse", "HEAD") != expected_head:
        raise contracts.HandoffError("primary HEAD changed")
    unexpected = sorted(path.name for path in (repo / ".project").iterdir()
                        if path.name not in isolation.PROJECT_ENTRIES)
    if unexpected:
        raise contracts.HandoffError("unsupported .project artifacts: " + ", ".join(unexpected))
    dirty = isolation.uncommitted_paths(repo)
    outputs = {".project/STATE.md", ".project/build/verify-ledger.jsonl",
               ".project/build/evidence.json"}
    adoption_path = isolation.REBASE_ADOPTION_PATH
    if adoption_path in dirty:
        build_state.verify_landed_tasks(str(repo), ".project", expected_head)
        outputs.add(adoption_path)
    if any(path not in outputs and not path.startswith(".project/review/") for path in dirty):
        raise contracts.HandoffError("verification inputs have uncommitted changes")


def _retire_execution(repo, head, execution):
    worktree = Path(execution["worktree"])
    if worktree.exists():
        isolation.clean_verify(repo, worktree, head, execution["branch"])
    isolation.retire(repo, worktree, execution["branch"], force=False)


def verify_project(repo, expected_head):
    """Execute project Verify in isolation, retaining output for retry reuse."""
    repo = Path(repo).resolve()
    _require_ship_inputs(repo, expected_head)
    plan = contracts._read(repo, ".project/plan/PLAN.md")
    command = contracts._line_value(plan, "Project verify:")
    _, waves = contracts._plan_waves(plan)
    lookup = build_state.verify_lookup(str(repo), command, expected_head)
    entry = lookup["entry"]
    relative = ".project/review/final-gap-1.md"
    destination = repo / relative
    if destination.is_symlink():
        raise contracts.HandoffError("project verification evidence must be a real file")
    expected_destination = hashlib.sha256(destination.read_bytes()).hexdigest() if destination.exists() else None
    execution = entry.get("execution") if entry else None
    if entry and execution is None:
        raise contracts.HandoffError("recorded verification lacks output; preserve and reconcile its evidence")
    if execution is not None:
        for journal in isolation.collect_artifact_recoveries(repo):
            if (journal["source_worktree"] == execution["worktree"]
                    and journal["branch"] == execution["branch"]
                    and journal["base"] == expected_head
                    and journal["source"] == relative
                    and journal["destination"] == relative):
                isolation.collect_artifact(
                    repo, Path(execution["worktree"]), expected_head, execution["branch"],
                    relative, relative, journal["expected_destination"],
                )
        _retire_execution(repo, expected_head, execution)
        view = _gap_view(command, expected_head, execution, waves)
        if not destination.exists() or destination.read_text() != view:
            _common.atomic_write(destination, view)
        return {"passed": entry["result"] == "pass", "reused": True,
                "path": str(destination), "execution": execution}
    sidecar = isolation.isolate_verify(repo, expected_head, "project-verify")
    worktree = Path(sidecar["worktree"])
    completed = subprocess.run(["bash", "-c", command], cwd=worktree,
                               text=True, capture_output=True)
    execution = {"exit_code": completed.returncode, "stdout": completed.stdout,
                 "stderr": completed.stderr, "worktree": str(worktree), "branch": sidecar["branch"]}
    passed = completed.returncode == 0
    build_state.verify_record(str(repo), command, expected_head,
                              "pass" if passed else "fail", execution=execution)
    isolation.clean_verify(repo, worktree, expected_head, sidecar["branch"])
    _common.atomic_write(worktree / relative, _gap_view(command, expected_head, execution, waves))
    collection = isolation.collect_artifact(repo, worktree, expected_head, sidecar["branch"],
                                            relative, relative, expected_destination)
    isolation.retire(repo, worktree, sidecar["branch"], force=False)
    return {"passed": passed, "reused": False, "path": str(destination),
            "execution": execution, "collection": collection}


def prepare_final(repo, expected_head):
    verification = verify_project(repo, expected_head)
    if not verification["passed"]:
        return {"status": "blocked", "verification": verification,
                "reason": "project Verify failed; use its recorded output"}
    final = reuse_final(repo, expected_head)
    if not final["reused"] and (Path(repo) / ".project/review/FINAL.md").exists():
        try:
            valid = contracts.validate_final(Path(repo))
            if valid["verdict"] == "pass":
                final = {"reused": True, "path": str(Path(repo) / ".project/review/FINAL.md"),
                         "reviewed_head": expected_head, "source": "existing final review"}
        except contracts.HandoffError:
            pass
    return {"status": "complete", "verification": verification, "final": final,
            "next": "final-gate" if final["reused"] else "review-final"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_final(args.repo.resolve(), args.expected_head)
    except (contracts.HandoffError, isolation.IsolationError, build_state.BuildStateError,
            OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
