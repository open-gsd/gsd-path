#!/usr/bin/env python3
"""Git commit-msg and pre-commit guard for GSD Path projects.

Blocks a commit that changes any path under a committed .project/archive/
tree, and blocks a ship commit (subject `ship: ...`) that stages paths outside
.project/. A new archive may be populated only when STATE.md names it as the
current ship transaction; commit-msg then also requires a ship subject.

Installed as .git/hooks/commit-msg:

    exec python3 "$(git rev-parse --show-toplevel)/.gsd-path/git_guard.py" commit-msg "$1"

Installed as .git/hooks/pre-commit:

    exec python3 "$(git rev-parse --show-toplevel)/.gsd-path/git_guard.py" pre-commit

Inspection failures and violations both exit 1. The guard fails closed because
an unreadable index cannot prove archive immutability.
"""

import re
import subprocess
import sys
from pathlib import Path

ARCHIVE_PREFIX = ".project/archive/"
GUARD_MARKER = "gsd-path guard"
INTEGRATE_SUBJECT = re.compile(
    r"^integrate: (?P<milestone>M\d{3,}) — merge "
    r"(?P<branch>gsd-path/M\d{3,}) into (?P<target>\S+)$"
)
ABANDON_SUBJECT = re.compile(
    r"^build: abandon milestone (?P<slug>[a-z0-9][a-z0-9-]*)$"
)
ROADMAP_HEADING = re.compile(
    r"^### (?P<milestone>M\d{3,}) — (?P<slug>[a-z0-9][a-z0-9-]*)\s*$"
)
ARCHIVE_NAME = re.compile(
    r"^\.project/archive/(?P<number>\d{3,})-(?P<slug>[a-z0-9][a-z0-9-]*)$"
)
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
BOUND_BRANCH = re.compile(r"^gsd-path/M(?P<number>\d{3,})$")
LEGACY_STATE_FIELDS = {
    "pipeline",
    "project",
    "milestone",
    "phase",
    "status",
    "branch",
    "archive",
}
INTEGRATION_STATE_FIELDS = LEGACY_STATE_FIELDS | {
    "integration_default",
    "integration",
}
PROVENANCE_STATE_FIELDS = INTEGRATION_STATE_FIELDS | {"integration_source"}
INTEGRATION_MODES = {"direct", "pull-request"}
INTEGRATION_SOURCES = {"default", "milestone"}


def staged_entries():
    output = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "-z", "--find-renames"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    tokens = output.split("\0")
    entries = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        if not status:
            index += 1
            continue
        code = status[0]
        if code in "RC":
            entries.append((code, tokens[index + 1], tokens[index + 2]))
            index += 3
        else:
            entries.append((code, tokens[index + 1], None))
            index += 2
    return entries


def message_of(message_file):
    lines = [
        line.strip()
        for line in Path(message_file).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        return "", ""
    return lines[0], "\n".join(lines[1:])


def archive_root(path):
    if not path.startswith(ARCHIVE_PREFIX):
        return None
    name = path[len(ARCHIVE_PREFIX):].split("/", 1)[0]
    return f"{ARCHIVE_PREFIX}{name}" if name else None


def destination_path(entry):
    code, old, new = entry
    if code == "A":
        return old
    if code in "CR":
        return new
    return None


def committed_archive_roots():
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if head.returncode == 1:
        return set()  # unborn HEAD: the first commit has no committed tree
    head.check_returncode()
    output = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", ARCHIVE_PREFIX],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {
        root
        for path in output.splitlines()
        if (root := archive_root(path)) is not None
    }


def staged_file(path):
    return subprocess.run(
        ["git", "show", f":{path}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def staged_frontmatter():
    content = staged_file(".project/STATE.md")
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("staged STATE.md is missing YAML frontmatter")
    values = {}
    closed = False
    for line in lines[1:]:
        if line == "---":
            closed = True
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([a-z_]+):\s*([^#]*?)(?:\s+#.*)?", line)
        if match is None:
            raise ValueError(f"staged STATE.md has malformed frontmatter: {line}")
        key, value = match.groups()
        if key in values:
            raise ValueError(f"staged STATE.md repeats field: {key}")
        values[key] = value.strip().strip("\"'")
    if not closed:
        raise ValueError("staged STATE.md frontmatter is not closed")
    return values


def strict_ship_state(state, archive):
    fields = frozenset(state)
    if fields not in {
        frozenset(LEGACY_STATE_FIELDS),
        frozenset(INTEGRATION_STATE_FIELDS),
        frozenset(PROVENANCE_STATE_FIELDS),
    }:
        return False
    if fields != frozenset(LEGACY_STATE_FIELDS):
        if state.get("integration_default") not in INTEGRATION_MODES:
            return False
        if state.get("integration") not in INTEGRATION_MODES:
            return False
    if fields == frozenset(PROVENANCE_STATE_FIELDS):
        source = state.get("integration_source")
        if source not in INTEGRATION_SOURCES:
            return False
        if source == "default" and state.get("integration") != state.get(
            "integration_default"
        ):
            return False
    archive_match = ARCHIVE_NAME.fullmatch(archive or "")
    branch_match = BOUND_BRANCH.fullmatch(state.get("branch", ""))
    if archive_match is None or branch_match is None:
        return False
    return (
        state.get("pipeline") == "gsd-path/v2"
        and bool(SLUG.fullmatch(state.get("project", "")))
        and state.get("milestone") == archive_match.group("slug")
        and state.get("phase") == "shipped"
        and state.get("status") == "done"
        and state.get("archive") == archive
        and int(branch_match.group("number")) == int(archive_match.group("number"))
    )


def ship_contract_violations(entries, subject, body, new_archives, state):
    if not is_ship_commit(subject):
        return []
    found = []
    if len(new_archives) != 1:
        return ["a ship commit requires exactly one new current archive"]
    archive = next(iter(new_archives))
    match = ARCHIVE_NAME.fullmatch(archive)
    if match is None or state is None or not strict_ship_state(state, archive):
        found.append("ship commit staged STATE.md is not the strict shipped transaction")
        return found
    expected_subject = f"ship: M{int(match.group('number')):03d} — {match.group('slug')}"
    if subject != expected_subject:
        found.append(f"ship commit subject must be {expected_subject!r}")
    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if current_branch != state["branch"]:
        found.append("ship commit must run on staged STATE.branch")
    reviewed_head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    expected_body = f"Archive: {archive}\nReviewed-HEAD: {reviewed_head}"
    if body != expected_body:
        found.append("ship commit body does not match Archive and Reviewed-HEAD")
    changed_paths = {
        new if code in "CR" else old
        for code, old, new in entries
    }
    if ".project/STATE.md" not in changed_paths:
        found.append("ship commit must stage .project/STATE.md")
    if f"{archive}/MANIFEST.md" not in changed_paths:
        found.append("ship commit must add the current archive MANIFEST.md")
    return found


def staged_archive_target(values=None):
    values = staged_frontmatter() if values is None else values
    if "archive" not in values:
        raise ValueError("staged STATE.md must contain exactly one archive field")
    value = values["archive"]
    if value in {"", "null"}:
        return None
    root = archive_root(value)
    if root != value.rstrip("/"):
        raise ValueError(f"staged STATE.md archive is invalid: {value}")
    return root


def staged_abandon_target(new_archives, state):
    """Return archive, slug, and reason for a complete abandon commit."""
    if len(new_archives) != 1:
        return None
    target = next(iter(new_archives))
    archive_match = ARCHIVE_NAME.fullmatch(target)
    if archive_match is None:
        return None

    required_state = {
        "pipeline": "gsd-path/v2",
        "milestone": "null",
        "phase": "roadmap",
        "status": "active",
        "archive": "null",
    }
    if any(state.get(key) != value for key, value in required_state.items()):
        return None

    sections = []
    lines = staged_file(".project/ROADMAP.md").splitlines()
    for index, line in enumerate(lines):
        heading = ROADMAP_HEADING.fullmatch(line)
        if heading is None:
            continue
        end = next(
            (
                cursor
                for cursor in range(index + 1, len(lines))
                if ROADMAP_HEADING.fullmatch(lines[cursor]) is not None
            ),
            len(lines),
        )
        section = lines[index:end]
        if (
            section.count("Status: abandoned") == 1
            and section.count(f"Archive: {target}")
            + section.count(f"Archive: {target}/")
            == 1
        ):
            sections.append(heading)
    if len(sections) != 1:
        return None

    heading = sections[0]
    slug = heading.group("slug")
    branch = f"gsd-path/{heading.group('milestone')}"
    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if (
        slug != archive_match.group("slug")
        or state.get("branch") != branch
        or current_branch != branch
    ):
        return None
    reasons = [
        line[len("Reason:") :].strip()
        for line in staged_file(f"{target}/MANIFEST.md").splitlines()
        if line.startswith("Reason:")
    ]
    if len(reasons) != 1 or not reasons[0]:
        return None
    reason = " ".join(reasons[0].split())
    return target, slug, reason


def is_ship_commit(subject):
    return bool(subject and subject.strip().casefold().startswith("ship:"))


def is_abandon_commit(subject, abandon):
    match = ABANDON_SUBJECT.fullmatch(subject or "")
    return bool(match and abandon and match.group("slug") == abandon[1])


def abandon_contract_violations(subject, body, abandon):
    if not is_abandon_commit(subject, abandon):
        return []
    expected = f"Why: {abandon[2]}"
    if body != expected:
        return ["abandon commit body does not match the archived MANIFEST Reason"]
    return []


def default_branch():
    origin_head = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if origin_head.returncode == 0 and origin_head.stdout.strip().startswith("origin/"):
        return origin_head.stdout.strip()[len("origin/") :]
    configured = subprocess.run(
        ["git", "config", "--get", "init.defaultBranch"],
        capture_output=True,
        text=True,
        check=False,
    )
    if configured.returncode == 0 and configured.stdout.strip():
        return configured.stdout.strip()
    return "main"


def is_integration_merge(subject):
    match = INTEGRATE_SUBJECT.fullmatch(subject or "")
    if not match or match.group("branch") != f"gsd-path/{match.group('milestone')}":
        return False
    target = default_branch()
    if match.group("target") != target:
        return False
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    milestone = match.group("milestone")
    if branch not in {target, f"gsd-path-integrate/{milestone}"}:
        return False
    merge_head = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "MERGE_HEAD^{commit}"],
        capture_output=True,
        text=True,
        check=False,
    )
    bound_head = subprocess.run(
        [
            "git",
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/heads/{match.group('branch')}^{{commit}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return (
        merge_head.returncode == 0
        and bound_head.returncode == 0
        and merge_head.stdout.strip() == bound_head.stdout.strip()
    )


def violations(
    entries,
    subject,
    existing_archives=(),
    current_archive=None,
    integration_merge=False,
    abandon_commit=False,
):
    found = []
    existing = set(existing_archives)
    for code, old, new in entries:
        if code in "MDTR" and old.startswith(ARCHIVE_PREFIX):
            label = f"{code} {old}" + (f" -> {new}" if new else "")
            found.append(
                f"{label}: committed archives are read-only; "
                f"unstage it with git restore --staged -- {new or old}"
            )
    for entry in entries:
        destination = destination_path(entry)
        root = archive_root(destination or "")
        if root is None:
            continue
        code, old, new = entry
        label = f"{code} {old}" + (f" -> {new}" if new else "")
        if root in existing:
            found.append(
                f"{label}: committed archives are read-only; "
                f"unstage it with git restore --staged -- {destination}"
            )
        elif root != current_archive:
            found.append(
                f"{label}: only the current STATE.archive "
                f"({current_archive or 'unset'}) may be created; "
                f"unstage it with git restore --staged -- {destination}"
            )
        elif (
            subject is not None
            and not is_ship_commit(subject)
            and not integration_merge
            and not abandon_commit
        ):
            milestone, target = root[len(ARCHIVE_PREFIX):], default_branch()
            found.append(
                f"{label}: a new archive requires a ship commit, a "
                "milestone-abandon commit, or an integration merge with the "
                f"subject 'integrate: {milestone} — merge "
                f"gsd-path/{milestone} into {target}'"
            )
    if is_ship_commit(subject):
        for code, old, new in entries:
            for path in (old, new):
                if path and not path.startswith(".project/"):
                    found.append(
                        f"{code} {path}: a ship commit may only touch .project/; "
                        f"unstage it with git restore --staged -- {path}"
                    )
    return found


def commit_message(argv):
    if len(argv) <= 1:
        return "", ""
    if argv[1] == "pre-commit":
        # At pre-commit time .git/COMMIT_EDITMSG still holds the PREVIOUS
        # commit's message, so subject rules cannot be enforced here; the
        # commit-msg hook enforces them with the real message.
        return None, None
    if argv[1] == "commit-msg" and len(argv) > 2:
        return message_of(argv[2])
    return message_of(argv[1])


def main(argv):
    try:
        entries = staged_entries()
        subject, body = commit_message(argv)
        existing = committed_archive_roots()
        destinations = {
            root
            for entry in entries
            if (root := archive_root(destination_path(entry) or "")) is not None
        }
        new_archives = destinations - existing
        state = staged_frontmatter() if new_archives else None
        current_archive = staged_archive_target(state) if new_archives else None
        abandon = (
            staged_abandon_target(new_archives, state)
            if new_archives and current_archive is None
            else None
        )
        if abandon is not None:
            current_archive = abandon[0]
    except Exception as error:
        print(
            f"gsd-path guard: inspection failed; commit blocked ({error}); "
            "run git from inside the repository worktree, then retry the commit",
            file=sys.stderr,
        )
        return 1
    integration_merge = is_integration_merge(subject) if new_archives else False
    abandon_commit = is_abandon_commit(subject, abandon) if new_archives else False
    found = violations(
        entries,
        subject,
        existing,
        current_archive,
        integration_merge,
        abandon_commit,
    )
    found.extend(ship_contract_violations(entries, subject, body, new_archives, state))
    found.extend(abandon_contract_violations(subject, body, abandon))
    if found:
        print("gsd-path guard blocked the commit:", file=sys.stderr)
        for violation in found:
            print(f"  {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
