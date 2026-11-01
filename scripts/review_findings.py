#!/usr/bin/env python3
# gsd-path project runtime
"""Compute the wave review finding sets for build step 7 without model reasoning.

The orchestrator names the wave and cycle. This helper reads PLAN.md Config
(`max_review_cycles`, `finding_skeptics`, `wave_budget`), the cycle's lens or
canonical review files, and every skeptic file for this wave. It groups
blocking findings by canonical criterion locator (`t001_ac2`, `sc3`,
`t001_files`, `t001_interface_contract`), collapses true duplicate
observations, selects the groups that need a skeptic, carries refutations
forward across cycles, batches fix-task groups by repo and disjoint file
scope, keeps structural blockers out of skeptic accounting, and reports
whether the cycle cap is reached. It never decides the wave verdict.
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import sys

# Runtime helpers must not modify their immutable installation.
sys.dont_write_bytecode = True
from pathlib import Path
from typing import Dict, List, Optional, Sequence

try:
    from . import _common
except ImportError:  # installed standalone helper
    import _common

DEFAULT_PROJECT_DIR = ".project"
DEFAULT_MAX_REVIEW_CYCLES = 3
CONFIG_KEYS = ("max_review_cycles", "wave_budget", "review_panel", "finding_skeptics")
CONFIG_LINE = re.compile(r"^-\s*(?P<key>[A-Za-z0-9_-]+):\s*(?P<value>.*?)\s*$")
PLAN_WAVE_HEADING = re.compile(r"(?m)^## Wave (?P<wave>\d+) — (?P<title>.+)$")
TASK_FILE_NAME = re.compile(r"^(?P<id>T\d{3})-[a-z0-9][a-z0-9-]*\.md$")
WAVE_TASK_HEADING = re.compile(
    r"^## (?P<task>T\d{3}) — (?P<title>.+): (?P<verdict>pass|fail)$"
)
WAVE_SC_HEADING = re.compile(r"^### (?P<sc>SC[1-9]\d*) — (?P<rest>.+)$")
NUMBERED_ITEM = re.compile(r"^(\d+)\.\s+(\S.*)$")
SKEPTIC_FILE_NAME = re.compile(
    r"^wave-(?P<wave>[1-9]\d*)\.cycle(?P<cycle>[1-9]\d*)\.skeptic-(?P<locator>[a-z0-9_]+)\.md$"
)
SKEPTIC_OBSERVATION = re.compile(r"^### Observation (?P<n>\d+) — (?P<lens>contract|adversarial|both)$")
SKEPTIC_OBSERVATION_VERDICT = re.compile(r"^### Observation (?P<n>\d+): (?P<verdict>refuted|stands)$")
FAIL_MARKER = "- ❌ "


class ReviewFindingsError(Exception):
    """Raised when an input cannot be read as the templates define it."""


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _strip_comments(text: str) -> str:
    # Code-span-preserving, shared with every criteria comparison (#548).
    return _common.strip_html_comments(text)


def _section(text: str, heading: str) -> Optional[str]:
    match = re.search(rf"(?m)^## {re.escape(heading)}\s*$", text)
    if not match:
        return None
    rest = text[match.end() :]
    following = re.search(r"(?m)^## ", rest)
    return rest[: following.start()] if following else rest


def _read(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ReviewFindingsError(f"{label} is not readable: {path} ({error.strerror})")


# --- PLAN.md ---------------------------------------------------------------


def parse_config(plan_text: str) -> Dict[str, object]:
    """Read and validate the PLAN.md Config keys this helper owns."""

    section = _section(_strip_comments(plan_text), "Config")
    if section is None:
        raise ReviewFindingsError("PLAN.md has no ## Config section")
    seen: Dict[str, str] = {}
    for line in section.splitlines():
        match = CONFIG_LINE.match(line.strip())
        if not match:
            continue
        key, value = match.group("key"), match.group("value")
        if key not in CONFIG_KEYS:
            raise ReviewFindingsError(
                f"PLAN.md Config key `{key}` is unknown; expected one of {', '.join(CONFIG_KEYS)}"
            )
        if key in seen:
            raise ReviewFindingsError(f"PLAN.md Config repeats `{key}`")
        seen[key] = value
    cycles_raw = seen.get("max_review_cycles", str(DEFAULT_MAX_REVIEW_CYCLES))
    if not cycles_raw.isdigit() or int(cycles_raw) < 1:
        raise ReviewFindingsError(
            f"PLAN.md Config `max_review_cycles` must be a positive integer, got `{cycles_raw}`"
        )
    skeptics = seen.get("finding_skeptics", "off")
    if skeptics not in {"off", "on"}:
        raise ReviewFindingsError(
            f"PLAN.md Config `finding_skeptics` must be `off` or `on`, got `{skeptics}`"
        )
    budget = seen.get("wave_budget", "none")
    if not budget:
        raise ReviewFindingsError("PLAN.md Config `wave_budget` must be `none` or a resource cap")
    return {
        "max_review_cycles": int(cycles_raw),
        "finding_skeptics": skeptics,
        "wave_budget": budget,
    }


def wave_depth(plan_text: str, wave: int) -> str:
    headings = list(PLAN_WAVE_HEADING.finditer(plan_text))
    for index, heading in enumerate(headings):
        if int(heading.group("wave")) != wave:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(plan_text)
        depth = re.search(r"(?m)^Review depth:\s*(\S+)", plan_text[heading.end() : end])
        if not depth or depth.group(1) not in {"full", "deep", "verify-only"}:
            raise ReviewFindingsError(f"PLAN.md Wave {wave} has an invalid Review depth")
        return depth.group(1)
    raise ReviewFindingsError(f"PLAN.md has no Wave {wave}")


# --- task files ------------------------------------------------------------


def _frontmatter_list(frontmatter: str, key: str) -> List[str]:
    inline = re.search(rf"(?m)^{key}:\s*\[(?P<body>.*)\]\s*(?:#.*)?$", frontmatter)
    if inline:
        return [part.strip().strip("\"'") for part in inline.group("body").split(",") if part.strip()]
    block = re.search(rf"(?m)^{key}:\s*(?:#.*)?$\n(?P<items>(?:[ \t]+-\s+.*\n?)*)", frontmatter)
    if not block:
        return []
    return [
        _normalize(re.sub(r"\s+#.*$", "", item.strip()[1:])).strip("\"'")
        for item in block.group("items").splitlines()
        if item.strip().startswith("-")
    ]


def _numbered_items(section: Optional[str]) -> List[str]:
    """Numbered criteria; each also carries its text without sub-bullet markers (issue #392)."""
    if section is None:
        return []
    bare = _numbered_texts(_common.without_sub_bullet_markers(section))
    return [_common.Criterion(text, other) for text, other in zip(_numbered_texts(section), bare)]


def _numbered_texts(section: str) -> List[str]:
    items: List[str] = []
    open_item = False
    for line in _strip_comments(section).splitlines():
        match = NUMBERED_ITEM.match(line.strip())
        if match:
            items.append(_normalize(match.group(2)))
            open_item = True
        elif open_item and line[:1].isspace() and line.strip():
            items[-1] = _normalize(items[-1] + " " + line.strip())
        elif line.strip():
            open_item = False
    return items


def _bullets(section: Optional[str]) -> List[str]:
    if section is None:
        return []
    return [
        _normalize(line.strip()[1:])
        for line in _strip_comments(section).splitlines()
        if line.strip().startswith("- ")
    ]


def load_wave_tasks(project: Path, wave: int) -> Dict[str, dict]:
    tasks_dir = project / "tasks"
    if not tasks_dir.is_dir():
        raise ReviewFindingsError(f"tasks directory missing: {tasks_dir}")
    tasks: Dict[str, dict] = {}
    for path in sorted(tasks_dir.iterdir()):
        named = TASK_FILE_NAME.fullmatch(path.name)
        if not named:
            continue
        text = _read(path, f"task {path.name}")
        parts = text.split("---", 2)
        if len(parts) < 3:
            raise ReviewFindingsError(f"task {path.name} has no frontmatter")
        frontmatter = parts[1]
        task_wave = re.search(r"(?m)^wave:\s*(\d+)", frontmatter)
        if not task_wave or int(task_wave.group(1)) != wave:
            continue
        body = parts[2]
        member = re.search(r"(?m)^repo:[ \t]*(?P<name>[^\s#]+)", frontmatter)
        tasks[named.group("id")] = {
            "id": named.group("id"),
            "path": str(path),
            "repo": member.group("name").strip("\"'") if member else None,  # None is the coordinator
            "files": _frontmatter_list(frontmatter, "files"),
            "acceptance": _numbered_items(_section(body, "Acceptance criteria")),
            "interface": [
                item for item in _bullets(_section(body, "Interface contract")) if item != "None"
            ],
            "owned": [
                item for item in _bullets(_section(body, "Intent coverage")) if item != "None"
            ],
        }
    if not tasks:
        raise ReviewFindingsError(f"PLAN.md Wave {wave} has no task files")
    return tasks


# --- lens files ------------------------------------------------------------


def review_paths(project: Path, wave: int, cycle: int, depth: str) -> Dict[str, Path]:
    review = project / "review"
    if depth == "deep":
        return {
            lens: review / f"wave-{wave}.cycle{cycle}.{lens}.md"
            for lens in ("contract", "adversarial")
        }
    return {"canonical": review / f"wave-{wave}.cycle{cycle}.md"}


def _fail_items(lines: Sequence[str]) -> List[str]:
    """Collect `- ❌` items with their indented continuation lines."""

    items: List[str] = []
    open_item = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(FAIL_MARKER):
            items.append(stripped[len(FAIL_MARKER) :])
            open_item = True
        elif open_item and line.startswith("  ") and stripped and not stripped.startswith("- "):
            items[-1] += " " + stripped
        elif stripped.startswith("- ") or stripped.startswith("#"):
            open_item = False
    return [_normalize(item) for item in items]


def _criterion_of(observation: str) -> str:
    return _normalize(observation.split(" — ", 1)[0])


def parse_lens(text: str, lens: str, tasks: Dict[str, dict]) -> dict:
    """Return the lens verdict and every blocking observation with its locator."""

    verdict = re.search(r"(?m)^Wave verdict:\s*(\S+)", text)
    if not verdict or verdict.group(1) not in {"pass", "blocked"}:
        raise ReviewFindingsError(f"{lens} lens has no valid Wave verdict")
    lines = _strip_comments(text).splitlines()
    findings: List[dict] = []
    problems: List[str] = []
    task_headings = [
        (index, match) for index, line in enumerate(lines)
        if (match := WAVE_TASK_HEADING.fullmatch(line.strip()))
    ]
    for start, heading in task_headings:
        task_id = heading.group("task")
        end = next(
            (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
            len(lines),
        )
        if task_id not in tasks:
            problems.append(f"{lens} lens reviews {task_id}, which is not a wave task")
            continue
        task = tasks[task_id]
        block = lines[start + 1 : end]
        zones = {"criteria": [], "warnings": [], "violations": []}
        zone = "criteria"
        for line in block:
            label = line.strip().casefold()
            if label.startswith("warnings (non-blocking)"):
                zone = "warnings"
                continue
            if label.startswith("contract violations (blocking)"):
                zone = "violations"
                continue
            zones[zone].append(line)
        for observation in _fail_items(zones["criteria"]):
            # Issue #392: match as the wave gate does, then report the task's own text.
            criteria = task["acceptance"] + task["interface"]
            quoted = _common.quoted_criterion(observation, criteria)
            if quoted is None:
                problems.append(
                    f"{lens} lens {task_id} finding names no task criterion: "
                    f"{_criterion_of(observation)}"
                )
                continue
            criterion = criteria[quoted[0]]
            if quoted[0] < len(task["acceptance"]):
                locator = f"{task_id.lower()}_ac{quoted[0] + 1}"
            else:
                locator = f"{task_id.lower()}_interface_contract"
            findings.append(
                {"locator": locator, "criterion": criterion, "task": task_id,
                 "lens": lens, "observation": observation}
            )
        for observation in _fail_items(zones["violations"]):
            findings.append(
                {"locator": f"{task_id.lower()}_files", "criterion": _criterion_of(observation),
                 "task": task_id, "lens": lens, "observation": observation}
            )
    coverage = _section("\n".join(lines), "Intent coverage")
    if coverage is not None:
        coverage_lines = coverage.splitlines()
        sc_headings = [
            (index, match) for index, line in enumerate(coverage_lines)
            if (match := WAVE_SC_HEADING.fullmatch(line.strip()))
        ]
        for position, (start, heading) in enumerate(sc_headings):
            text_part, _sep, sc_verdict = heading.group("rest").rpartition(":")
            if sc_verdict.strip() != "fail":
                continue
            sc_id = heading.group("sc")
            end = sc_headings[position + 1][0] if position + 1 < len(sc_headings) else len(coverage_lines)
            observations = _fail_items(coverage_lines[start + 1 : end])
            if not observations:
                problems.append(f"{lens} lens {sc_id} fails without a ❌ observation")
                continue
            owners = [task_id for task_id, task in tasks.items() if sc_id in task["owned"]]
            for observation in observations:
                findings.append(
                    {"locator": sc_id.lower(), "criterion": _normalize(text_part),
                     "task": ", ".join(owners), "tasks": owners, "lens": lens,
                     "observation": observation}
                )
    return {"verdict": verdict.group(1), "findings": findings, "problems": problems}


# --- skeptic files ---------------------------------------------------------


def parse_skeptic(path: Path, wave: int, expected_observations: Optional[Sequence[str]] = None) -> dict:
    """Validate one skeptic file against the template; return its verdict and observations."""

    named = SKEPTIC_FILE_NAME.fullmatch(path.name)
    if not named or int(named.group("wave")) != wave:
        raise ReviewFindingsError(f"skeptic file name does not belong to wave {wave}: {path.name}")
    text = _strip_comments(_read(path, f"skeptic {path.name}"))
    locator = re.search(r"(?m)^- Criterion locator:\s*(\S+)\s*$", text)
    if not locator or locator.group(1) != named.group("locator"):
        raise ReviewFindingsError(f"{path.name} Criterion locator does not match its filename")
    verdict_section = _section(text, "Verdict")
    verdict = _normalize(verdict_section or "")
    if verdict not in {"refuted", "stands"}:
        raise ReviewFindingsError(f"{path.name} Verdict must be `refuted` or `stands`")
    observations: List[str] = []
    lines = (_section(text, "Observations") or "").splitlines()
    starts = [(index, int(match.group("n"))) for index, line in enumerate(lines)
              if (match := SKEPTIC_OBSERVATION.match(line.strip()))]
    observation_numbers = {number for _, number in starts}
    if len(observation_numbers) != len(starts):
        raise ReviewFindingsError(f"{path.name} has duplicate observation numbers")
    for position, (start, _) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        observations.append(_normalize(" ".join(lines[start + 1 : end])))
    if not observations or any(not item for item in observations):
        raise ReviewFindingsError(f"{path.name} records no observation text")
    if expected_observations is not None and not {
        _normalize(item) for item in expected_observations
    } <= set(observations):
        raise ReviewFindingsError(f"{path.name} omits dispatched observations")
    observation_verdicts = [
        (int(match.group("n")), match.group("verdict"))
        for line in (_section(text, "Observation verdicts") or "").splitlines()
        if (match := SKEPTIC_OBSERVATION_VERDICT.match(line.strip()))
    ]
    verdict_numbers = {number for number, _ in observation_verdicts}
    if len(verdict_numbers) != len(observation_verdicts) or verdict_numbers != observation_numbers:
        raise ReviewFindingsError(
            f"{path.name} must have exactly one matching verdict per observation number"
        )
    if verdict == "refuted" and any(item != "refuted" for _, item in observation_verdicts):
        raise ReviewFindingsError(
            f"{path.name} records Verdict refuted while an observation stands"
        )
    return {
        "path": str(path),
        "cycle": int(named.group("cycle")),
        "locator": named.group("locator"),
        "verdict": verdict,
        "observations": observations,
    }


def load_skeptics(project: Path, wave: int, cycle: int) -> tuple:
    """Return (skeptics by cycle then locator, structural blockers for invalid files)."""

    review = project / "review"
    by_cycle: Dict[int, Dict[str, dict]] = {}
    blockers: List[dict] = []
    if not review.is_dir():
        return by_cycle, blockers
    for path in sorted(review.iterdir()):
        named = SKEPTIC_FILE_NAME.fullmatch(path.name)
        if not named or int(named.group("wave")) != wave or int(named.group("cycle")) > cycle:
            continue
        try:
            parsed = parse_skeptic(path, wave)
        except ReviewFindingsError as error:
            blockers.append({"kind": "invalid-skeptic", "path": str(path), "detail": str(error)})
            continue
        by_cycle.setdefault(parsed["cycle"], {})[parsed["locator"]] = parsed
    return by_cycle, blockers


# --- grouping and dispositions ---------------------------------------------


def group_findings(findings: Sequence[dict]) -> List[dict]:
    """Group by locator; collapse only observations whose text is identical."""

    groups: Dict[str, dict] = {}
    for finding in findings:
        group = groups.setdefault(
            finding["locator"],
            {"locator": finding["locator"], "criterion": finding["criterion"],
             "tasks": [], "lenses": [], "observations": []},
        )
        for task_id in finding.get("tasks", [finding["task"]]):
            if task_id and task_id not in group["tasks"]:
                group["tasks"].append(task_id)
        if finding["lens"] not in group["lenses"]:
            group["lenses"].append(finding["lens"])
        if all(item["text"] != finding["observation"] for item in group["observations"]):
            group["observations"].append({"lens": finding["lens"], "text": finding["observation"]})
    return [groups[key] for key in sorted(groups)]


def _earlier_lens_locators(project: Path, wave: int, cycle: int, depth: str, tasks: Dict[str, dict]) -> Dict[str, int]:
    first_seen: Dict[str, int] = {}
    for earlier in range(1, cycle):
        for lens, path in review_paths(project, wave, earlier, depth).items():
            if not path.is_file():
                continue
            try:
                parsed = parse_lens(path.read_text(encoding="utf-8"), lens, tasks)
            except (ReviewFindingsError, OSError):
                continue
            for finding in parsed["findings"]:
                first_seen.setdefault(finding["locator"], earlier)
    return first_seen


def _fix_batches(groups: Sequence[dict], tasks: Dict[str, dict]) -> List[dict]:
    """One batch per repo and disjoint file scope: groups whose task files overlap in one repo share a batch.

    A member batch names its `repo`; a coordinator batch has no such key.
    """

    batches: List[dict] = []
    for group in groups:
        owners = [tasks.get(task_id, {}) for task_id in group["tasks"]]
        for repo in sorted({task.get("repo") or "" for task in owners}) or [""]:
            files = sorted({path for task in owners if (task.get("repo") or "") == repo
                            for path in task.get("files", [])})
            merged = {"locators": [group["locator"]], "files": files, **({"repo": repo} if repo else {})}
            keep: List[dict] = []
            for batch in batches:
                if batch.get("repo") == merged.get("repo") and _common.overlapping_paths(batch["files"], files):
                    merged["locators"] = batch["locators"] + merged["locators"]
                    merged["files"] = sorted(set(batch["files"]) | set(merged["files"]))
                else:
                    keep.append(batch)
            keep.append(merged)
            batches = keep
    return batches


def compute(
    repo: Path,
    project_dir: str,
    wave: int,
    cycle: int,
    helper_failures: Sequence[str] = (),
) -> dict:
    project = repo / project_dir
    plan_path = project / "plan" / "PLAN.md"
    plan_text = _read(plan_path, "PLAN.md")
    config = parse_config(plan_text)
    depth = wave_depth(plan_text, wave)
    tasks = load_wave_tasks(project, wave)
    structural: List[dict] = [
        {"kind": "helper-failure", "path": None, "detail": item} for item in helper_failures
    ]
    findings: List[dict] = []
    verdicts: Dict[str, Optional[str]] = {}
    for lens, path in review_paths(project, wave, cycle, depth).items():
        if not path.is_file():
            structural.append({"kind": "missing-artifact", "path": str(path), "detail": f"{lens} review file is missing"})
            verdicts[lens] = None
            continue
        try:
            parsed = parse_lens(_read(path, f"{lens} review"), lens, tasks)
        except ReviewFindingsError as error:
            structural.append({"kind": "invalid-artifact", "path": str(path), "detail": str(error)})
            verdicts[lens] = None
            continue
        verdicts[lens] = parsed["verdict"]
        findings.extend(parsed["findings"])
        for problem in parsed["problems"]:
            structural.append({"kind": "invalid-artifact", "path": str(path), "detail": problem})
        if parsed["verdict"] == "blocked" and not parsed["findings"] and not parsed["problems"]:
            structural.append({"kind": "invalid-artifact", "path": str(path), "detail": f"{lens} lens is blocked without a ❌ finding"})

    skeptics_by_cycle, skeptic_blockers = load_skeptics(project, wave, cycle)
    structural.extend(skeptic_blockers)
    panel = None
    panel_path = project / "review" / f"wave-{wave}.cycle{cycle}.panel.md"
    if panel_path.is_file():
        actionable = re.search(r"(?m)^Actionable:\s*(\d+)\s*$", _read(panel_path, "panel"))
        if not actionable:
            structural.append({"kind": "invalid-artifact", "path": str(panel_path), "detail": "panel file has no Actionable count"})
        else:
            panel = {"path": str(panel_path), "actionable": int(actionable.group(1))}

    skeptics_active = config["finding_skeptics"] == "on" and depth == "deep"
    first_seen = _earlier_lens_locators(project, wave, cycle, depth, tasks)
    earlier_refuted: Dict[str, dict] = {}
    for earlier in sorted(skeptics_by_cycle):
        if earlier >= cycle:
            continue
        for locator, skeptic in skeptics_by_cycle[earlier].items():
            if skeptic["verdict"] == "refuted":
                earlier_refuted.setdefault(locator, skeptic)
    current_skeptics = skeptics_by_cycle.get(cycle, {})

    groups = group_findings(findings)
    for group in groups:
        locator = group["locator"]
        group["first_seen_cycle"] = first_seen.get(locator, cycle)
        group["repeat"] = locator in first_seen
        group["skeptic"] = None
        earlier = earlier_refuted.get(locator)
        current = current_skeptics.get(locator)
        if current is not None:
            try:
                parse_skeptic(Path(current["path"]), wave,
                              [item["text"] for item in group["observations"]])
            except ReviewFindingsError as error:
                structural.append({"kind": "invalid-skeptic", "path": current["path"], "detail": str(error)})
                current = None
        if not skeptics_active:
            group["disposition"] = "fix"
        elif earlier is not None:
            texts = {item["text"] for item in group["observations"]}
            group["skeptic"] = {"cycle": earlier["cycle"], "verdict": "refuted", "path": earlier["path"]}
            if texts <= set(earlier["observations"]):
                group["disposition"] = "refuted-earlier"
            else:
                group["disposition"] = "fix"
                group["new_evidence"] = sorted(texts - set(earlier["observations"]))
        elif current is not None:
            group["skeptic"] = {"cycle": cycle, "verdict": current["verdict"], "path": current["path"]}
            group["disposition"] = "refuted" if current["verdict"] == "refuted" else "fix"
        else:
            group["disposition"] = "needs-skeptic"

    refuted = [g["locator"] for g in groups if g["disposition"] in {"refuted", "refuted-earlier"}]
    fix_groups = [g for g in groups if g["disposition"] == "fix"]
    skeptic_groups = [g["locator"] for g in groups if g["disposition"] == "needs-skeptic"]
    lens_blocked = any(value != "pass" for value in verdicts.values())
    cap_reached = cycle >= config["max_review_cycles"]
    return {
        "status": "ok",
        "wave": wave,
        "cycle": cycle,
        "depth": depth,
        "config": config,
        "lens_verdicts": verdicts,
        "blocked": lens_blocked or bool(structural),
        "cap_reached": cap_reached,
        "skeptics_active": skeptics_active,
        "groups": groups,
        "skeptic_groups": skeptic_groups,
        "refuted_groups": refuted,
        "carried_refutations": [
            {"locator": locator, "cycle": skeptic["cycle"], "path": skeptic["path"]}
            for locator, skeptic in sorted(earlier_refuted.items())
        ],
        "fix_groups": [g["locator"] for g in fix_groups],
        "fix_batches": _fix_batches(fix_groups, tasks),
        "structural_blockers": structural,
        "all_refuted": bool(refuted) and not fix_groups and not skeptic_groups and not structural and not cap_reached,
        "panel": panel,
    }


def emit(payload: dict) -> int:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def repair_evidence(repo: Path, project_dir: str, wave: int, cycle: int, task_id: str) -> dict:
    """Bind a carried finding batch to a proven, independently verified repair."""
    try:
        from . import _common, build_state, isolation
    except ImportError:  # installed standalone helper
        import _common
        import build_state
        import isolation

    try:
        repo = isolation.require_directory(repo, "repository")
        project = repo / isolation.relative_posix(project_dir)
        if not re.fullmatch(r"T\d{3}", task_id or ""):
            raise ReviewFindingsError("--task must name a repair task id")
        paths = list((project / "tasks").glob(f"{task_id}-*.md"))
        if len(paths) != 1:
            raise ReviewFindingsError("repair task must resolve to exactly one task file")
        repair_path = paths[0]
        text = _read(repair_path, "repair task")
        fields, error = isolation.task_frontmatter(text)
        if error or fields is None or fields.get("status") != "done":
            raise ReviewFindingsError(error or "repair task must be done")
        head = isolation.current_sha(repo)
        proof = isolation.verify_landed_task_files(
            repo, [repair_path], f"{project_dir}/tasks", head
        )["tasks"][0]
        if proof["verdict"] != "recovered":
            raise ReviewFindingsError("repair requires a proven landing")
        base = proof["base"]  # in the coordinator, where the source review is
        findings = _section(text, "Review findings") or ""
        headings = list(re.finditer(r"(?m)^### ([a-z0-9_]+)\s*$", findings))
        locators = [heading.group(1) for heading in headings]
        if not locators or len(set(locators)) != len(locators):
            raise ReviewFindingsError("repair needs unique carried finding locators")
        source = compute(repo, project_dir, wave, cycle)
        if source["structural_blockers"]:
            raise ReviewFindingsError("source findings have structural blockers")
        member = fields.get("repo")  # a finding in two repos has one batch per repo with the same locators
        batches = [batch for batch in source["fix_batches"]
                   if batch.get("repo") == member and set(batch["locators"]) == set(locators)]
        if len(batches) != 1:
            raise ReviewFindingsError("repair must carry one eligible source finding batch")
        # A member task's product is in the member repository: its commits, its bound branch, its Verify rows.
        where, tip = repo, []  # the coordinator product is judged in the working tree
        if member:
            where, _, lock = isolation._member_context(repo, member)
            tip = [f"refs/heads/{lock['branch']}"]

        def entry(landing: dict, path: Path, paths: List[str]) -> dict:
            """A proven landing as the receipt shows it; a member landing adds its commits in the member."""
            item = {"task": landing["task_id"], "base": landing["base"], "commit": landing["commit"], "files": paths}
            if member:
                item.update(member_base=isolation.task_frontmatter(_read(path, "task"))[0]["member_base"],
                            member_commit=landing["landing"])
            return item

        def at(item: dict, point: str = "commit") -> str:
            return item.get(f"member_{point}", item[point])

        groups = [group for group in source["groups"] if group["locator"] in locators]
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(findings)
            block = _normalize(findings[heading.end():end])
            group = next(group for group in groups if group["locator"] == heading.group(1))
            if ("Criterion: " + group["criterion"] not in block
                    or any(item["text"] not in block for item in group["observations"])):
                raise ReviewFindingsError("repair does not carry the exact criterion and observations")
        frontmatter = text.split("---", 2)[1]
        files = _frontmatter_list(frontmatter, "files")
        sources = load_wave_tasks(project, wave)
        originals = sorted({task for group in groups for task in group["tasks"] if sources[task]["repo"] == member})
        # A repair names the files it needs. They can be fewer than the batch files, and a plan repair
        # can add a fix site that the source tasks did not declare.
        if (task_id in originals or not set(originals) <= set(_frontmatter_list(frontmatter, "deps"))
                or not files):
            raise ReviewFindingsError("repair dependencies/files do not match its source batch")
        repair = {"task_file": repair_path.relative_to(repo).as_posix(), **entry(proof, repair_path, files),
                  **({"member": member} if member else {})}

        def differ(start: str, end: List[str], paths: List[str]) -> bool:
            return bool(isolation.run_git(where, "diff", "--quiet", start, *end, "--", *paths).returncode)

        def before(start: str, end: str) -> bool:
            return not isolation.run_git(where, "merge-base", "--is-ancestor", start, end).returncode

        @functools.lru_cache(maxsize=None)
        def linked() -> tuple:
            """Landed repairs of the same findings that `deps` join to this repair, in landing order.

            A linked task is done, is in the same repo, carries a finding of this repair in its
            `## Review findings`, and depends on this repair or on a linked task, or the reverse.
            """
            tasks, carried = {task_id: (repair_path, fields)}, {}
            for path in (project / "tasks").glob("T*-*.md"):
                other = _read(path, "task")
                other_fields = isolation.task_frontmatter(other)[0] or {}
                tasks[str(other_fields.get("id"))] = (path, other_fields)
                blocks = re.split(r"(?m)^### ([a-z0-9_]+)\s*$", _section(other, "Review findings") or "")
                carried[str(other_fields.get("id"))] = {
                    (locator, _normalize(line)) for locator, block in zip(blocks[1::2], blocks[2::2])
                    for line in re.findall(r"(?m)^Criterion:(.*)$", block)}

            def traced(finding: tuple, seen: frozenset = frozenset()) -> set:
                """The finding as it started: its locator and criterion in the review of the source tasks.

                A finding on an acceptance criterion of a fix task (`fix-tasks` copies the carried criteria
                there) is the finding with the same criterion that this fix task carries. Two findings with
                the same criterion text and other locators stay two findings.
                """
                owner = re.fullmatch(r"t(\d{3})_ac\d+", finding[0])
                sources = () if not owner else {
                    item for item in carried.get(f"T{owner.group(1)}", ()) if item[1] == finding[1]} - seen
                return {origin for item in sources for origin in traced(item, seen | {finding})} or {finding}

            def origins(other: str) -> set:
                return {origin for finding in carried.get(other, ()) for origin in traced(finding)}

            repairs = {other: task for other, task in tasks.items() if other == task_id or (
                task[1].get("status") == "done" and task[1].get("repo") == member
                and origins(task_id) & origins(other))}
            joined, more = set(), {task_id}
            while more:
                joined |= more
                more = {other for other, (_, other_fields) in repairs.items() if other not in joined and (
                    joined & set(other_fields.get("deps") or [])
                    or any(other in (repairs[item][1].get("deps") or []) for item in joined))}
            others = sorted(joined - {task_id})
            proofs = isolation.verify_landed_task_files(
                repo, [repairs[other][0] for other in others], f"{project_dir}/tasks", head)["tasks"] if others else []
            links = []
            for landing in proofs:
                path, other_fields = repairs[landing["task_id"]]
                if landing["verdict"] == "recovered":
                    links.append({"task_file": path.relative_to(repo).as_posix(),
                                  **entry(landing, path, list(other_fields.get("files") or []))})
            return tuple(sorted(links, key=lambda link: int(isolation.git_output(where, "rev-list", "--count", at(link)))))

        def linked_changes(start: str, end: List[str], paths: List[str]) -> Optional[List[dict]]:
            """The linked repairs whose landings are every change to `paths` from `start` to `end`, else None."""
            if not differ(start, end, paths):
                return []
            links = [link for link in linked()
                     if before(start, f"{at(link)}^") and (not end or before(at(link), end[0]))]
            for link in links:
                if differ(start, [f"{at(link)}^"], paths):
                    return None
                start = at(link)
            return None if differ(start, end, paths) else links

        original_paths = [Path(sources[task]["path"]) for task in originals]
        original_proofs = isolation.verify_landed_task_files(
            repo, original_paths, f"{project_dir}/tasks", head
        )["tasks"]
        landed, earlier = [], set()
        for landing in original_proofs:
            links = None
            if landing["verdict"] == "recovered":
                original = entry(landing, Path(sources[landing["task_id"]]["path"]), sources[landing["task_id"]]["files"])
                if before(at(original), at(repair, "base")):
                    links = linked_changes(at(original), [at(repair, "base")], original["files"])
            if links is None:
                raise ReviewFindingsError("repair base contains unlinked changes to original product")
            landed.append(original)
            earlier.update(link["task"] for link in links)
        source_paths = list(review_paths(project, wave, cycle, source["depth"]).values())
        source_paths.extend(Path(group["skeptic"]["path"]) for group in groups if group["skeptic"])
        for path in set(source_paths):
            relative = path.relative_to(repo).as_posix()
            at_base = isolation.run_git(repo, "show", f"{base}:{relative}")
            if at_base.returncode or at_base.stdout != _read(path, "source review"):
                raise ReviewFindingsError("source review must be unchanged and precede the repair")
        # A later linked repair supersedes this one: the last one is the product at the tip, and its
        # landing and its Verify are the evidence. The reviewer applies every patch of the chain, so the
        # files of every later linked repair must also change only through the landings of the chain.
        later = linked_changes(at(repair), tip, files)
        chain_files = sorted({*files, *(path for link in later or [] for path in link["files"])})
        last = later[-1] if later else repair
        verification = build_state.verify_lookup(
            str(repo), _common.task_verify_command(_read(repo / last["task_file"], "repair task")), at(last), member)
        if not verification["reuse"]:
            raise ReviewFindingsError("repair has no reusable passing Verify at its landing")
        if later is None or (later and linked_changes(at(repair), tip, chain_files) is None):
            raise ReviewFindingsError("product changed after the repair landing")
        # A parallel landing can have a parent that is newer than the repair base. The reviewer builds the
        # product from the base, so no other landing between the two can change a file of the chain.
        if differ(at(repair, "base"), [f"{at(repair)}^"], chain_files):
            raise ReviewFindingsError("product changed between the repair base and the repair landing")
        return {
            "status": "ok", "command": "repair-evidence", "head": head,
            "source": {"wave": wave, "cycle": cycle}, "groups": groups,
            "originals": landed, "repair": repair,
            **({"earlier_repairs": [link for link in linked() if link["task"] in earlier]} if earlier else {}),
            **({"later_repairs": later, "chain_files": chain_files} if later else {}),
            "verification": verification,
            "verdict": "evidence-ready; reviewer judges the original unchanged criteria",
        }
    except (isolation.IsolationError, build_state.BuildStateError, ValueError) as error:
        raise ReviewFindingsError(str(error)) from error


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("collect", "repair-evidence"))
    result.add_argument("--repo", type=Path, required=True, help="absolute repository root")
    result.add_argument("--project-dir", default=DEFAULT_PROJECT_DIR)
    result.add_argument("--wave", type=int, required=True)
    result.add_argument("--cycle", type=int, required=True)
    result.add_argument("--task", help="landed repair task for repair-evidence")
    result.add_argument(
        "--helper-failure",
        action="append",
        default=[],
        help="a bundled helper non-zero exit for this cycle; repeatable; recorded as a structural blocker",
    )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.wave < 1 or arguments.cycle < 1:
            raise ReviewFindingsError("--wave and --cycle must be positive integers")
        if arguments.command == "repair-evidence":
            return emit(repair_evidence(arguments.repo, arguments.project_dir,
                                        arguments.wave, arguments.cycle, arguments.task))
        return emit(
            compute(
                arguments.repo,
                arguments.project_dir,
                arguments.wave,
                arguments.cycle,
                arguments.helper_failure,
            )
        )
    except ReviewFindingsError as error:
        json.dump({"status": "error", "error": str(error)}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
