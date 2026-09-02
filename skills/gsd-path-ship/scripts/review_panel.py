#!/usr/bin/env python3
# gsd-path project runtime
"""Resolve optional GSD Path cross-model review panels without model reasoning.

The orchestrator inspects the host's advertised child-model slugs and passes
them here. This helper parses PLAN.md / INTENT.md / CHARTER.md (PLAN wins,
then INTENT, then CHARTER, else off), groups slugs into families, skips the
parent family, caps the panel at three, and merges family artifacts. It never
probes a host or overrides the canonical inherit reviewer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence


KNOWN_FAMILIES = (
    "claude",
    "gpt",
    "grok",
    "composer",
    "gemini",
    "deepseek",
    "kimi",
    "qwen",
)
FAMILY_ALIASES = {
    "claude": "claude",
    "opus": "claude",
    "sonnet": "claude",
    "haiku": "claude",
    "gpt": "gpt",
    "openai": "gpt",
    "grok": "grok",
    "composer": "composer",
    "gemini": "gemini",
    "deepseek": "deepseek",
    "kimi": "kimi",
    "moonshot": "kimi",
    "qwen": "qwen",
}
MAX_FAMILIES = 3
PLAN_LINE = re.compile(
    r"^-\s*review_panel:\s*(\S.*?)\s*(?:<!--.*-->)?\s*$", re.MULTILINE
)
INTENT_LINE = re.compile(
    r"^Review panel:\s*(\S.*?)\s*(?:<!--.*-->)?\s*$", re.MULTILINE
)
VERSION_NUMBERS = re.compile(r"\d+")
TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
FINDING_BLOCK = re.compile(
    r"^###\s+(?P<id>F\d+)\s*$"
    r"(?P<body>.*?)(?=^###\s+F\d+\s*$|\Z)",
    re.MULTILINE | re.DOTALL,
)
FIELD_LINE = re.compile(r"^-\s*(?P<key>[A-Za-z][A-Za-z ]*):\s*(?P<value>.*)\s*$")


class ReviewPanelError(RuntimeError):
    pass


def _first_token(value: str) -> str:
    return value.strip().split()[0].strip().strip("`")


def _split_families(value: str) -> tuple[str, ...]:
    tokens = [token.strip().casefold() for token in value.split(",") if token.strip()]
    if not tokens:
        raise ReviewPanelError("review_panel named list is empty")
    unknown = [token for token in tokens if token not in KNOWN_FAMILIES]
    if unknown:
        raise ReviewPanelError(
            f"unknown review_panel families: {', '.join(unknown)}"
        )
    seen = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    if len(seen) > MAX_FAMILIES:
        raise ReviewPanelError(
            f"review_panel names at most {MAX_FAMILIES} families"
        )
    return tuple(seen)


def parse_review_panel_value(raw: str) -> dict:
    value = raw.strip()
    if not value:
        raise ReviewPanelError("review_panel value is empty")
    token = _first_token(value).casefold()
    if token == "off":
        return {"mode": "off", "families": ()}
    if token == "detected":
        return {"mode": "detected", "families": ()}
    families = _split_families(value)
    return {"mode": "named", "families": families}


def extract_config_value(text: str, pattern: re.Pattern[str], source: str) -> Optional[str]:
    matches = pattern.findall(text)
    if not matches:
        return None
    if len(matches) > 1:
        raise ReviewPanelError(f"{source} has multiple review_panel values")
    return matches[0]


def parse_sources(
    plan_text: Optional[str],
    intent_text: Optional[str],
    charter_text: Optional[str] = None,
) -> dict:
    if plan_text is not None:
        plan_value = extract_config_value(plan_text, PLAN_LINE, "PLAN.md")
        if plan_value is not None:
            parsed = parse_review_panel_value(plan_value)
            parsed["source"] = "plan"
            return parsed
    if intent_text is not None:
        intent_value = extract_config_value(intent_text, INTENT_LINE, "INTENT.md")
        if intent_value is not None:
            parsed = parse_review_panel_value(intent_value)
            parsed["source"] = "intent"
            return parsed
    if charter_text is not None:
        charter_value = extract_config_value(charter_text, INTENT_LINE, "CHARTER.md")
        if charter_value is not None:
            parsed = parse_review_panel_value(charter_value)
            parsed["source"] = "charter"
            return parsed
    return {"mode": "off", "families": (), "source": "default"}


def read_optional(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    resolved = path.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise ReviewPanelError(f"path must be a real file: {resolved}")
    return resolved.read_text(encoding="utf-8")


def parse_files(
    plan: Optional[Path],
    intent: Optional[Path],
    charter: Optional[Path] = None,
) -> dict:
    return parse_sources(
        read_optional(plan), read_optional(intent), read_optional(charter)
    )


def plan_review_panel_enabled(plan_text: str) -> bool:
    """Archive-safe enabled check: anything other than absent/off is on."""
    try:
        parsed = parse_sources(plan_text, None)
    except ReviewPanelError:
        return True
    return parsed["mode"] != "off"


def family_of_slug(slug: str) -> Optional[str]:
    normalized = slug.strip().casefold()
    if not normalized or normalized == "inherit":
        return None
    tokens = TOKEN_SPLIT.split(normalized)
    for token in tokens:
        if token in FAMILY_ALIASES:
            return FAMILY_ALIASES[token]
    for token in tokens:
        stem = token.rstrip("0123456789")
        if stem and stem in FAMILY_ALIASES:
            return FAMILY_ALIASES[stem]
    return None


def version_key(slug: str) -> tuple[int, ...]:
    numbers = tuple(int(part) for part in VERSION_NUMBERS.findall(slug))
    return numbers if numbers else (0,)


def latest_slug(slugs: Sequence[str]) -> str:
    return max(slugs, key=lambda slug: (version_key(slug), len(slug), slug))


def group_advertised(slugs: Iterable[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {family: [] for family in KNOWN_FAMILIES}
    for slug in slugs:
        cleaned = slug.strip()
        if not cleaned:
            continue
        family = family_of_slug(cleaned)
        if family is None:
            continue
        if cleaned not in grouped[family]:
            grouped[family].append(cleaned)
    return {family: values for family, values in grouped.items() if values}


def split_csv(raw: Optional[str]) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def resolve_panel(
    config: dict,
    advertised: Sequence[str],
    parent_family: Optional[str] = None,
    parent_slug: Optional[str] = None,
) -> dict:
    inferred_parent = parent_family or (
        family_of_slug(parent_slug) if parent_slug else None
    )
    grouped = group_advertised(advertised)
    skipped = []
    selected = []

    if config["mode"] == "off":
        return {
            "mode": "off",
            "status": "off",
            "reason": "review_panel is off",
            "parent_family": inferred_parent,
            "selected": [],
            "skipped": [],
            "missing": [],
        }

    wanted = (
        list(config["families"])
        if config["mode"] == "named"
        else [family for family in KNOWN_FAMILIES if family in grouped]
    )
    missing = [family for family in wanted if family not in grouped]
    if config["mode"] == "named" and missing:
        raise ReviewPanelError(
            "named review_panel families are not advertised: " + ", ".join(missing)
        )

    for family in wanted:
        if family == inferred_parent:
            skipped.append({"family": family, "reason": "parent family"})
            continue
        slugs = grouped.get(family)
        if not slugs:
            skipped.append({"family": family, "reason": "not advertised"})
            continue
        selected.append({"family": family, "slug": latest_slug(slugs)})
        if len(selected) >= MAX_FAMILIES:
            overflow = wanted[wanted.index(family) + 1 :]
            for extra in overflow:
                if extra != inferred_parent and extra in grouped:
                    skipped.append({"family": extra, "reason": "cap"})
            break

    if selected:
        return {
            "mode": config["mode"],
            "status": "ready",
            "reason": "panel resolved",
            "parent_family": inferred_parent,
            "selected": selected,
            "skipped": skipped,
            "missing": missing if config["mode"] == "detected" else [],
        }

    if config["mode"] == "named":
        raise ReviewPanelError(
            "named review_panel would only repeat the parent family or is empty"
        )
    return {
        "mode": config["mode"],
        "status": "skipped",
        "reason": "no advertised cross-model families",
        "parent_family": inferred_parent,
        "selected": [],
        "skipped": skipped,
        "missing": missing,
    }


def _require_field(body: str, key: str, source: str) -> str:
    for line in body.splitlines():
        match = FIELD_LINE.fullmatch(line.strip())
        if match and match.group("key").casefold() == key.casefold():
            value = match.group("value").strip()
            if not value:
                raise ReviewPanelError(f"{source} has an empty {key} field")
            return value
    raise ReviewPanelError(f"{source} is missing the {key} field")


def parse_findings(text: str, source: str) -> list[dict]:
    findings = []
    for match in FINDING_BLOCK.finditer(text):
        body = match.group("body")
        severity = _require_field(body, "Severity", f"{source} {match.group('id')}").casefold()
        kind = _require_field(body, "Kind", f"{source} {match.group('id')}").casefold()
        criterion = _require_field(body, "Criterion", f"{source} {match.group('id')}")
        evidence = _require_field(body, "Evidence", f"{source} {match.group('id')}")
        found = _require_field(body, "Found", f"{source} {match.group('id')}")
        fix = _require_field(body, "Fix direction", f"{source} {match.group('id')}")
        if severity not in {"high", "medium", "low"}:
            raise ReviewPanelError(f"{source} {match.group('id')} has an invalid Severity")
        if kind not in {"criterion", "preference"}:
            raise ReviewPanelError(f"{source} {match.group('id')} has an invalid Kind")
        if kind == "criterion" and criterion.casefold() == "none":
            raise ReviewPanelError(
                f"{source} {match.group('id')} criterion findings must name a criterion"
            )
        findings.append(
            {
                "id": match.group("id"),
                "severity": severity,
                "kind": kind,
                "criterion": criterion,
                "evidence": evidence,
                "found": found,
                "fix": fix,
                "source": source,
            }
        )
    if not findings:
        findings_heading = re.search(r"^## Findings\s*$", text, re.MULTILINE)
        if findings_heading:
            rest = text[findings_heading.end() :]
            next_heading = re.search(r"^## ", rest, re.MULTILINE)
            section = rest[: next_heading.start()] if next_heading else rest
            if re.search(r"^-\s*none\s*$", section, re.MULTILINE):
                return []
        raise ReviewPanelError(f"{source} has no findings")
    return findings


def parse_family_artifact(path: Path, expected_kind: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ReviewPanelError(f"panel artifact must be a real file: {path}")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if expected_kind == "plan":
        if not lines or not lines[0].startswith("# Plan panel — "):
            raise ReviewPanelError(f"{path.name} heading must start with '# Plan panel — '")
    elif expected_kind == "wave":
        if not lines or not lines[0].startswith("# Panel — wave "):
            raise ReviewPanelError(f"{path.name} heading must start with '# Panel — wave '")
    else:
        raise ReviewPanelError(f"unknown panel kind: {expected_kind}")
    family = _require_field(text, "Family", path.name).casefold()
    model = _require_field(text, "Model", path.name)
    if family not in KNOWN_FAMILIES:
        raise ReviewPanelError(f"{path.name} has an unknown Family")
    if "## Findings" not in text:
        raise ReviewPanelError(f"{path.name} is missing ## Findings")
    findings = parse_findings(text, path.name)
    return {
        "path": str(path),
        "family": family,
        "model": model,
        "text": text.rstrip() + "\n",
        "findings": findings,
    }


def actionable(finding: dict) -> bool:
    return finding["kind"] == "criterion" and finding["severity"] == "high"


def detect_conflicts(findings: Sequence[dict]) -> list[dict]:
    by_criterion: dict[str, list[dict]] = {}
    for finding in findings:
        key = finding["criterion"].strip().casefold()
        if key in {"", "none"}:
            continue
        by_criterion.setdefault(key, []).append(finding)
    conflicts = []
    for criterion, group in by_criterion.items():
        severities = {item["severity"] for item in group}
        verdicts = {item["source"]: actionable(item) for item in group}
        # A conflict is two families disagreeing on whether the criterion
        # needs a fix; wording differences in Found are not conflicts.
        if len(set(verdicts.values())) > 1:
            conflicts.append(
                {
                    "criterion": group[0]["criterion"],
                    "families": [item["source"] for item in group],
                    "severities": sorted(severities),
                }
            )
    return conflicts


def render_finding(finding: dict) -> str:
    return (
        f"- {finding['severity']} / {finding['kind']} — {finding['criterion']}\n"
        f"  evidence: {finding['evidence']}\n"
        f"  found: {finding['found']}\n"
        f"  fix: {finding['fix']}\n"
        f"  source: {finding['source']}\n"
    )


def merge_artifacts(
    kind: str,
    inputs: Sequence[Path],
    output: Path,
    header_fields: Sequence[tuple[str, str]],
) -> dict:
    artifacts = [parse_family_artifact(path, kind) for path in inputs]
    families = [artifact["family"] for artifact in artifacts]
    if len(families) != len(set(families)):
        raise ReviewPanelError("panel merge repeats a family")
    findings = [finding for artifact in artifacts for finding in artifact["findings"]]
    action = [finding for finding in findings if actionable(finding)]
    warnings = [finding for finding in findings if not actionable(finding)]
    conflicts = detect_conflicts(findings)
    title = "# Plan panel" if kind == "plan" else "# Wave panel"
    lines = [title, ""]
    for key, value in header_fields:
        lines.append(f"{key}: {value}")
    lines.extend(
        [
            f"Families: {', '.join(families)}",
            f"Actionable: {len(action)}",
            f"Warnings: {len(warnings)}",
            f"Conflicts: {len(conflicts)}",
            "",
            "## Actionable",
            "",
        ]
    )
    if action:
        lines.extend(render_finding(finding) for finding in action)
    else:
        lines.append("- none")
        lines.append("")
    lines.extend(["## Warnings", ""])
    if warnings:
        lines.extend(render_finding(finding) for finding in warnings)
    else:
        lines.append("- none")
        lines.append("")
    lines.extend(["## Conflicts", ""])
    if conflicts:
        for conflict in conflicts:
            lines.append(
                f"- {conflict['criterion']} — families {', '.join(conflict['families'])}; "
                f"severities {', '.join(conflict['severities'])}"
            )
        lines.append("")
    else:
        lines.append("- none")
        lines.append("")
    lines.extend(["## By family", ""])
    for artifact in artifacts:
        lines.append(artifact["text"].rstrip())
        lines.append("")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "output": str(output.resolve()),
        "families": families,
        "actionable": len(action),
        "warnings": len(warnings),
        "conflicts": len(conflicts),
    }


def emit(payload: dict) -> int:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "command", choices=("parse", "resolve", "families", "merge", "validate-plan")
    )
    result.add_argument("--plan", type=Path)
    result.add_argument("--intent", type=Path)
    result.add_argument("--charter", type=Path)
    result.add_argument("--advertised", default="")
    result.add_argument("--parent-family")
    result.add_argument("--parent-slug")
    result.add_argument("--kind", choices=("plan", "wave"))
    result.add_argument("--inputs", default="")
    result.add_argument("--output", type=Path)
    result.add_argument("--wave")
    result.add_argument("--cycle")
    result.add_argument("--mode")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "families":
            grouped = group_advertised(split_csv(arguments.advertised))
            return emit(
                {
                    "families": {
                        family: {"slugs": slugs, "latest": latest_slug(slugs)}
                        for family, slugs in grouped.items()
                    }
                }
            )
        if arguments.command == "merge":
            if arguments.kind is None or arguments.output is None:
                raise ReviewPanelError("merge requires --kind and --output")
            inputs = [Path(part) for part in split_csv(arguments.inputs)]
            if not inputs:
                raise ReviewPanelError("merge requires --inputs")
            header = []
            if arguments.mode:
                header.append(("Mode", arguments.mode))
            if arguments.kind == "wave":
                if not arguments.wave or not arguments.cycle:
                    raise ReviewPanelError("wave merge requires --wave and --cycle")
                header.extend(
                    (("Wave", arguments.wave), ("Cycle", arguments.cycle))
                )
            return emit(merge_artifacts(arguments.kind, inputs, arguments.output, header))
        if arguments.plan is None and arguments.command in {"parse", "resolve", "validate-plan"}:
            if arguments.command != "parse" or (
                arguments.intent is None and arguments.charter is None
            ):
                raise ReviewPanelError(
                    f"{arguments.command} requires --plan, --intent, or --charter"
                )
        config = parse_files(arguments.plan, arguments.intent, arguments.charter)
        if arguments.command in {"parse", "validate-plan"}:
            return emit(config)
        resolved = resolve_panel(
            config,
            split_csv(arguments.advertised),
            arguments.parent_family,
            arguments.parent_slug,
        )
        return emit(resolved)
    except ReviewPanelError as error:
        json.dump({"status": "error", "error": str(error)}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
