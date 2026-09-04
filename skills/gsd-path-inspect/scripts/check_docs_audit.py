#!/usr/bin/env python3
"""Gate a GSD Path docs audit (.project/research/DOCS-AUDIT.md) against its contract.

Checks the rules the docs-audit contract states in prose: the header lines,
a Summary table whose counts match the body, one `## Doc:` section per doc
with testable claims where every claim row carries a valid type, a valid
verdict, and real evidence, a `## Descriptive docs` list for claimless docs,
the two sets disjoint and together equal to the frozen inventory, and a
remediation queue with one classified row per non-verified claim.
`## User rulings` is fixed-format durable memory. Pass the pre-rewrite audit
with `--prior-audit FILE`; every prior row, including its Planned value, must
remain an exact ordered prefix.

A re-audit may carry a prior `verified` row forward verbatim with its Evidence
prefixed `unchanged: `. Pass the paths that differ from the prior audit's
`Audited HEAD` with `--changed FILE` (one path per line); a carried row must
repeat a prior verified non-command row whose doc and evidence paths are all
outside that set. Without both `--prior-audit` and `--changed`, carried rows
are rejected.

The frozen inventory travels in the dispatch brief; pass it with
`--inventory FILE` (one POSIX path per line, `-` for stdin). Without it the
gate derives the inventory from tracked Markdown files, excluding `.git`,
`node_modules`, `.project/archive/**`, installed `*/skills/gsd-path*` bundles,
the audit itself, and — unless the
audit declares `Alignment mode: yes` — everything else under `.project/`.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence

DEFAULT_AUDIT = ".project/research/DOCS-AUDIT.md"
TYPES = ("command", "feature", "structure", "status", "config", "integration")
VERDICTS = ("verified", "stale", "aspirational", "unverifiable")
CLASSES = ("fix-doc", "fix-code", "NEEDS-USER")
RULINGS = ("fix-code", "fix-doc", "accept-drift")
SUMMARY_ROWS = VERDICTS + ("descriptive docs (no testable claims)",)

HEADER_PATTERN = re.compile(r"^(Repo root|Audited|Audited HEAD|Alignment mode): (.+)$", re.M)
HEAD_PATTERN = re.compile(r"[0-9a-f]{40}|none")
CARRIED = "unchanged: "  # Evidence prefix of a row carried forward from the prior audit
SECTION_PATTERN = re.compile(r"^## (.+?)\s*$", re.M)
PLACEHOLDER_PATTERN = re.compile(r"^<[^>]*>$")  # a cell left as the template placeholder


class AuditError(RuntimeError):
    """Raised when the audit is absent or violates its contract."""


def _cells(line: str) -> Optional[List[str]]:
    if not line.startswith("|"):
        return None
    cells = [cell.replace("\\|", "|").strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
    if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
        return None  # separator row
    return cells


def _sections(text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    matches = list(SECTION_PATTERN.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = match.group(1)
        if title in sections:
            raise AuditError(f"duplicate section: ## {title}")
        sections[title] = text[match.end() : end]
    return sections


def _table_rows(body: str, width: int, label: str) -> List[List[str]]:
    rows = []
    for line in body.splitlines():
        cells = _cells(line)
        if cells is None:
            continue
        if len(cells) != width:
            raise AuditError(f"{label}: expected {width} columns, found {len(cells)}: {line.strip()}")
        rows.append(cells)
    if not rows:
        raise AuditError(f"{label}: missing table")
    header, *rows = rows
    return rows


def _not_placeholder(value: str, label: str) -> None:
    normalized = value.strip().strip("`\"").strip()
    if (
        not normalized
        or normalized.casefold() == "none"
        or PLACEHOLDER_PATTERN.match(normalized)
    ):
        raise AuditError(f"{label}: placeholder or empty value: {value!r}")


def _installed_skill(parts: Sequence[str]) -> bool:
    """True for files inside an installed GSD Path skill bundle (<host>/skills/gsd-path*/…)."""
    return any(
        parts[index] == "skills" and parts[index + 1].startswith("gsd-path")
        for index in range(len(parts) - 2)
    )


def derive_inventory(repo: Path, audit_relative: str, alignment: bool) -> List[str]:
    listed = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.md",
            "**/*.md",
        ],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        raise AuditError("cannot derive inventory: git ls-files failed; pass --inventory")
    paths = set()
    for raw in listed.stdout.decode("utf-8").split("\0"):
        if not raw or raw == audit_relative:
            continue
        parts = raw.split("/")
        if parts[0] in (".git", "node_modules") or "node_modules" in parts:
            continue
        if _installed_skill(parts):
            continue
        if raw.startswith(".project/archive/"):
            continue
        if raw.startswith(".project/") and not alignment:
            continue
        paths.add(raw)
    return sorted(paths)


def _user_rulings(body: str, label: str) -> List[List[str]]:
    rows = _table_rows(body, 4, label)
    seen = set()
    for number, ruling, words, planned in rows:
        if not number.isdigit() or int(number) < 1:
            raise AuditError(f"{label}: Queue # must be a positive integer: {number}")
        if number in seen:
            raise AuditError(f"{label}: repeated Queue #: {number}")
        seen.add(number)
        if ruling not in RULINGS:
            raise AuditError(f"{label}: invalid ruling: {ruling}")
        _not_placeholder(words, f"{label} #{number} User's words")
        if ruling == "accept-drift":
            if planned != "n/a (accept-drift)":
                raise AuditError(
                    f"{label} #{number}: accept-drift must be planned n/a (accept-drift)"
                )
        elif planned != "no" and not re.fullmatch(r"T\d{3}", planned):
            raise AuditError(
                f"{label} #{number}: Planned must be no or a T### task id"
            )
    return rows


def _doc_claims(sections: Dict[str, str]) -> Dict[str, List[Dict[str, str]]]:
    docs: Dict[str, List[Dict[str, str]]] = {}
    for title, body in sections.items():
        if not title.startswith("Doc: "):
            continue
        path = title[len("Doc: ") :].strip().strip("`")
        _not_placeholder(path, "Doc section path")
        if path in docs:
            raise AuditError(f"duplicate normalized Doc section: {path}")
        claims = []
        claim_rows = _table_rows(body, 4, f"Doc: {path}")
        if not claim_rows:
            raise AuditError(f"Doc: {path}: requires at least one claim row")
        for claim, kind, verdict, evidence in claim_rows:
            if kind not in TYPES:
                raise AuditError(f"Doc: {path}: invalid claim type: {kind}")
            if verdict not in VERDICTS:
                raise AuditError(f"Doc: {path}: invalid verdict: {verdict}")
            _not_placeholder(claim, f"Doc: {path}: claim")
            _not_placeholder(evidence, f"Doc: {path}: evidence for {claim}")
            claims.append({"claim": claim, "type": kind, "verdict": verdict, "evidence": evidence})
        docs[path] = claims
    return docs


def _check_carried(
    docs: Dict[str, List[Dict[str, str]]],
    prior_sections: Optional[Dict[str, str]],
    changed: Optional[Sequence[str]],
) -> None:
    carried = [
        (path, claim)
        for path, claims in docs.items()
        for claim in claims
        if claim["evidence"].startswith(CARRIED)
    ]
    if not carried:
        return
    if changed is None:
        raise AuditError("carried (unchanged:) rows require --prior-audit and --changed")
    prior = {
        (path, claim["claim"], claim["type"]): claim["evidence"].removeprefix(CARRIED)
        for path, claims in _doc_claims(prior_sections or {}).items()
        for claim in claims
        if claim["verdict"] == "verified"
    }
    for path, claim in carried:
        label = f"Doc: {path}: carried row {claim['claim']}"
        evidence = claim["evidence"].removeprefix(CARRIED)
        if claim["verdict"] != "verified" or claim["type"] == "command":
            raise AuditError(f"{label}: only verified non-command claims carry forward")
        if prior.get((path, claim["claim"], claim["type"])) != evidence:
            raise AuditError(f"{label}: does not repeat a prior verified row")
        # Evidence is free text, so a substring match errs toward re-verifying.
        moved = sorted(p for p in changed if p == path or p in evidence)
        if moved:
            raise AuditError(f"{label}: doc or evidence changed since the prior audit: {', '.join(moved)}")


def validate(
    repo: Path,
    audit_relative: str,
    inventory: Optional[Sequence[str]],
    prior_text: Optional[str] = None,
    changed: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    audit = repo / audit_relative
    if not audit.is_file() or audit.is_symlink():
        raise AuditError(f"missing real audit file: {audit_relative}")
    text = audit.read_text(encoding="utf-8")

    header_rows = HEADER_PATTERN.findall(text)
    header = {}
    for key in ("Repo root", "Audited", "Audited HEAD", "Alignment mode"):
        values = [value for found_key, value in header_rows if found_key == key]
        if len(values) != 1:
            raise AuditError(f"header must contain exactly one {key} line")
        header[key] = values[0]
    declared_root = Path(header["Repo root"])
    if not declared_root.is_absolute() or declared_root.resolve() != repo.resolve():
        raise AuditError("Repo root does not match --repo")
    try:
        date.fromisoformat(header["Audited"])
    except ValueError as error:
        raise AuditError("Audited must be an ISO date") from error
    if not HEAD_PATTERN.fullmatch(header["Audited HEAD"]):
        raise AuditError("Audited HEAD must be a 40-hex commit or none")
    alignment_value = header["Alignment mode"].split("—")[0].strip().lower()
    if alignment_value not in ("yes", "no"):
        raise AuditError(f"Alignment mode must be yes or no, found: {header['Alignment mode']}")
    alignment = alignment_value == "yes"

    sections = _sections(text)
    for required in ("Summary", "Descriptive docs", "User rulings", "Remediation queue"):
        if required not in sections:
            raise AuditError(f"missing section: ## {required}")

    summary = {}
    for verdict, count in _table_rows(sections["Summary"], 2, "Summary"):
        if verdict not in SUMMARY_ROWS:
            raise AuditError(f"Summary: unknown row: {verdict}")
        if not count.isdigit():
            raise AuditError(f"Summary: count for {verdict} is not an integer: {count!r}")
        summary[verdict] = int(count)
    missing = [row for row in SUMMARY_ROWS if row not in summary]
    if missing:
        raise AuditError(f"Summary: missing rows: {', '.join(missing)}")

    docs = _doc_claims(sections)
    tallies = {verdict: 0 for verdict in VERDICTS}
    for claims in docs.values():
        for claim in claims:
            tallies[claim["verdict"]] += 1

    descriptive = []
    for line in sections["Descriptive docs"].splitlines():
        line = line.strip()
        if line.startswith("- "):
            path = line[2:].strip().strip("`")
            _not_placeholder(path, "Descriptive docs entry")
            if path in descriptive:
                raise AuditError(f"Descriptive docs: listed twice: {path}")
            descriptive.append(path)

    overlap = sorted(set(docs) & set(descriptive))
    if overlap:
        raise AuditError(f"docs listed both as claim sections and descriptive: {', '.join(overlap)}")

    expected = sorted(inventory) if inventory is not None else derive_inventory(repo, audit_relative, alignment)
    covered = sorted(set(docs) | set(descriptive))
    if covered != expected:
        unaudited = sorted(set(expected) - set(covered))
        extra = sorted(set(covered) - set(expected))
        detail = []
        if unaudited:
            detail.append(f"not audited: {', '.join(unaudited)}")
        if extra:
            detail.append(f"outside inventory: {', '.join(extra)}")
        raise AuditError("audit coverage does not equal the frozen inventory; " + "; ".join(detail))

    for verdict in VERDICTS:
        if summary[verdict] != tallies[verdict]:
            raise AuditError(f"Summary: {verdict} count {summary[verdict]} does not match {tallies[verdict]} claim rows")
    if summary["descriptive docs (no testable claims)"] != len(descriptive):
        raise AuditError(
            f"Summary: descriptive count {summary['descriptive docs (no testable claims)']} "
            f"does not match {len(descriptive)} listed docs"
        )

    rulings = _user_rulings(sections["User rulings"], "User rulings")
    prior_sections = _sections(prior_text) if prior_text is not None else None
    if prior_sections is not None:
        if "User rulings" not in prior_sections:
            raise AuditError("prior audit is missing section: ## User rulings")
        prior_rulings = _user_rulings(
            prior_sections["User rulings"], "Prior user rulings"
        )
        if rulings[: len(prior_rulings)] != prior_rulings:
            raise AuditError(
                "User rulings must preserve every prior row and Planned value in order"
            )
    _check_carried(docs, prior_sections, changed)

    queue_body = sections["Remediation queue"]
    non_verified = sum(tallies[verdict] for verdict in VERDICTS if verdict != "verified")
    queue = _table_rows(queue_body, 6, "Remediation queue") if non_verified or "|" in queue_body else []
    expected_queue = sorted(
        (doc, claim["claim"], claim["verdict"])
        for doc, claims in docs.items()
        for claim in claims
        if claim["verdict"] != "verified"
    )
    for number, doc, claim, verdict, klass, action in queue:
        if verdict not in VERDICTS or verdict == "verified":
            raise AuditError(f"Remediation queue #{number}: verdict must be non-verified, found: {verdict}")
        if klass not in CLASSES:
            raise AuditError(f"Remediation queue #{number}: invalid class: {klass}")
        if doc not in docs:
            raise AuditError(f"Remediation queue #{number}: unknown doc: {doc}")
        _not_placeholder(action, f"Remediation queue #{number}: action")
    if len(queue) != non_verified:
        raise AuditError(f"Remediation queue has {len(queue)} rows for {non_verified} non-verified claims")
    numbers = [row[0] for row in queue]
    if numbers != [str(number) for number in range(1, len(queue) + 1)]:
        raise AuditError("Remediation queue numbers must be contiguous and ordered from 1")
    actual_queue = sorted((doc, claim, verdict) for _, doc, claim, verdict, _, _ in queue)
    if actual_queue != expected_queue:
        raise AuditError(
            "Remediation queue must bind each non-verified doc, claim, and verdict exactly once"
        )

    return {
        "audit": audit_relative,
        "alignment": alignment,
        "docs": sorted(docs),
        "descriptive": descriptive,
        "claims": sum(len(claims) for claims in docs.values()),
        "verdicts": tallies,
        "queue": len(queue),
        "rulings": len(rulings),
    }


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argument_parser.add_argument("--repo", type=Path, required=True)
    argument_parser.add_argument("--audit", default=DEFAULT_AUDIT, help="relative audit path (default: %(default)s)")
    argument_parser.add_argument("--inventory", help="file with one inventoried POSIX path per line, or - for stdin")
    argument_parser.add_argument(
        "--prior-audit",
        type=Path,
        help="pre-rewrite audit whose User rulings must carry forward",
    )
    argument_parser.add_argument(
        "--changed",
        help="file with one path changed since the prior audit's Audited HEAD per line; permits unchanged: rows",
    )
    argument_parser.add_argument(
        "--emit-inventory",
        action="store_true",
        help="print the frozen tracked and untracked Markdown inventory, one path per line",
    )
    argument_parser.add_argument(
        "--alignment",
        action="store_true",
        help="include active .project Markdown when emitting an alignment inventory",
    )
    return argument_parser


def _path_lines(name: str) -> List[str]:
    source = sys.stdin if name == "-" else open(name, encoding="utf-8")
    with source:
        return [line.strip() for line in source if line.strip()]


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.changed is not None and arguments.prior_audit is None:
        print("docs audit validation failed: --changed requires --prior-audit", file=sys.stderr)
        return 1
    if arguments.emit_inventory:
        if arguments.inventory is not None or arguments.prior_audit is not None or arguments.changed is not None:
            print(
                "docs audit validation failed: --emit-inventory cannot use validation inputs",
                file=sys.stderr,
            )
            return 1
        try:
            inventory = derive_inventory(
                arguments.repo.resolve(), arguments.audit, arguments.alignment
            )
        except AuditError as error:
            print(f"docs audit validation failed: {error}", file=sys.stderr)
            return 1
        print("\n".join(inventory))
        return 0
    inventory = _path_lines(arguments.inventory) if arguments.inventory is not None else None
    prior_text = None
    if arguments.prior_audit is not None:
        if arguments.prior_audit.is_symlink() or not arguments.prior_audit.is_file():
            print(
                "docs audit validation failed: --prior-audit must be a real file",
                file=sys.stderr,
            )
            return 1
        prior_text = arguments.prior_audit.read_text(encoding="utf-8")
    changed = _path_lines(arguments.changed) if arguments.changed is not None else None
    try:
        result = validate(
            arguments.repo.resolve(), arguments.audit, inventory, prior_text, changed
        )
    except AuditError as error:
        print(f"docs audit validation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
