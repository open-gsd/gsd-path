#!/usr/bin/env python3
"""Gate a GSD Path docs audit (.project/research/DOCS-AUDIT.md) against its contract.

Checks the rules the docs-audit contract states in prose: the header lines,
a Summary table whose counts match the body, one `## Doc:` section per doc
with testable claims where every claim row carries a valid type, a valid
verdict, and real evidence, a `## Descriptive docs` list for claimless docs,
the two sets disjoint and together equal to the frozen inventory, and a
remediation queue with one classified row per non-verified claim.

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
from pathlib import Path
from typing import Dict, List, Optional, Sequence

DEFAULT_AUDIT = ".project/research/DOCS-AUDIT.md"
TYPES = ("command", "feature", "structure", "status", "config", "integration")
VERDICTS = ("verified", "stale", "aspirational", "unverifiable")
CLASSES = ("fix-doc", "fix-code", "NEEDS-USER")
SUMMARY_ROWS = VERDICTS + ("descriptive docs (no testable claims)",)

HEADER_PATTERN = re.compile(r"^(Repo root|Audited|Alignment mode): (.+)$", re.M)
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
    if not value or PLACEHOLDER_PATTERN.match(value.strip("`\"")):
        raise AuditError(f"{label}: placeholder or empty value: {value!r}")


def _installed_skill(parts: Sequence[str]) -> bool:
    """True for files inside an installed GSD Path skill bundle (<host>/skills/gsd-path*/…)."""
    return any(
        parts[index] == "skills" and parts[index + 1].startswith("gsd-path")
        for index in range(len(parts) - 2)
    )


def derive_inventory(repo: Path, audit_relative: str, alignment: bool) -> List[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md", "**/*.md"],
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


def validate(repo: Path, audit_relative: str, inventory: Optional[Sequence[str]]) -> Dict[str, object]:
    audit = repo / audit_relative
    if not audit.is_file() or audit.is_symlink():
        raise AuditError(f"missing real audit file: {audit_relative}")
    text = audit.read_text(encoding="utf-8")

    header = dict(HEADER_PATTERN.findall(text))
    for key in ("Repo root", "Audited", "Alignment mode"):
        if key not in header:
            raise AuditError(f"missing header line: {key}")
        _not_placeholder(header[key], key)
    alignment_value = header["Alignment mode"].split("—")[0].strip().lower()
    if alignment_value not in ("yes", "no"):
        raise AuditError(f"Alignment mode must be yes or no, found: {header['Alignment mode']}")
    alignment = alignment_value == "yes"

    sections = _sections(text)
    for required in ("Summary", "Descriptive docs", "Remediation queue"):
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

    docs: Dict[str, List[Dict[str, str]]] = {}
    tallies = {verdict: 0 for verdict in VERDICTS}
    for title, body in sections.items():
        if not title.startswith("Doc: "):
            continue
        path = title[len("Doc: ") :].strip().strip("`")
        _not_placeholder(path, "Doc section path")
        claims = []
        for claim, kind, verdict, evidence in _table_rows(body, 4, f"Doc: {path}"):
            if kind not in TYPES:
                raise AuditError(f"Doc: {path}: invalid claim type: {kind}")
            if verdict not in VERDICTS:
                raise AuditError(f"Doc: {path}: invalid verdict: {verdict}")
            _not_placeholder(claim, f"Doc: {path}: claim")
            _not_placeholder(evidence, f"Doc: {path}: evidence for {claim}")
            tallies[verdict] += 1
            claims.append({"claim": claim, "type": kind, "verdict": verdict, "evidence": evidence})
        docs[path] = claims

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

    queue_body = sections["Remediation queue"]
    non_verified = sum(tallies[verdict] for verdict in VERDICTS if verdict != "verified")
    queue = _table_rows(queue_body, 6, "Remediation queue") if non_verified or "|" in queue_body else []
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

    return {
        "audit": audit_relative,
        "alignment": alignment,
        "docs": sorted(docs),
        "descriptive": descriptive,
        "claims": sum(len(claims) for claims in docs.values()),
        "verdicts": tallies,
        "queue": len(queue),
    }


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argument_parser.add_argument("--repo", type=Path, required=True)
    argument_parser.add_argument("--audit", default=DEFAULT_AUDIT, help="relative audit path (default: %(default)s)")
    argument_parser.add_argument("--inventory", help="file with one inventoried POSIX path per line, or - for stdin")
    return argument_parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    inventory = None
    if arguments.inventory is not None:
        source = sys.stdin if arguments.inventory == "-" else open(arguments.inventory, encoding="utf-8")
        with source:
            inventory = [line.strip() for line in source if line.strip()]
    try:
        result = validate(arguments.repo.resolve(), arguments.audit, inventory)
    except AuditError as error:
        print(f"docs audit validation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
