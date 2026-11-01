#!/usr/bin/env python3
# gsd-path project runtime
"""Helpers shared by the gsd-path scripts.

Every consuming script binds the names it used before (for example
``run_git = _common.run_git``) so callers and tests that patch the name on the
consuming module keep working.
"""

from __future__ import annotations

import sys

# Runtime helpers must not modify their immutable installation.
sys.dont_write_bytecode = True

import atexit
import contextlib
import errno
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator, List, Optional, Sequence, Set, Tuple


# Chosen by what imports, not os.name, so tests can emulate Windows on POSIX.
try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
    import msvcrt

# Windows opens descriptors in text mode unless asked otherwise.
O_BINARY = getattr(os, "O_BINARY", 0)


def utf8_stdio() -> None:
    """Write stdout and stderr as UTF-8, as every caller of these CLIs reads them.

    A Windows pipe defaults to the locale code page (cp1252), so an em dash
    reaches the parent as byte 0x97. Streams a caller substituted are left alone.
    """
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")


# Every runtime script imports this module before producing output.
utf8_stdio()

PIPELINE_MARKER = "gsd-path/v2"
BOUND_BRANCH_RE = re.compile(r"^gsd-path/M(\d{3,})$")

FIELD_PATTERN = re.compile(r"^(?P<key>[a-z_]+):\s*(?P<value>.*)$")
INLINE_LIST_PATTERN = re.compile(r"^\[(?P<body>.*)\]$")
LIST_ITEM_PATTERN = re.compile(r"^\s*-\s+(?P<value>.*)$")
VERIFY_LEDGER_PATH = ".project/build/verify-ledger.jsonl"
VERIFY_RESULTS = ("pass", "fail")
VERIFY_LEDGER_SCHEMA = "gsd-path/verify-ledger/v2"
VERIFY_BLOCK_PATTERN = re.compile(r"```bash[ \t]*\n(?P<block>.*?)```", re.DOTALL)
# The owner citation a withdrawn task tombstone must carry in its Log (#483).
# One definition shared by every gate that reads the representation.
WITHDRAWN_CITATION = re.compile(
    r"^- Withdrawn — (?P<date>\d{4}-\d{2}-\d{2}): (?P<ruling>.+)$", re.MULTILINE)


def withdrawn_citations(task_text: str) -> list[str]:
    """The owner citations in a withdrawn task's Log, as `date: ruling`.

    The Log is the append-only record of rulings; a Withdrawn line in any
    other section is not the citation the gates accept (#483).
    """
    body = section_body(task_text, "Log")
    if body is None:
        return []
    return [f"{m.group('date')}: {m.group('ruling')}"
            for m in WITHDRAWN_CITATION.finditer(body)]

REVIEW_BULLET_HEADING_PATTERN = re.compile(r"^#{2,3} ")
REVIEW_BULLET_FIELD_LABEL_PATTERN = re.compile(r"^- \*\*[^*]+\*\*:")


def review_bullet_field_label_pattern(field: str) -> re.Pattern[str]:
    return re.compile(rf"^- \*\*{re.escape(field)}\*\*:[ \t]*(.*)$")


def _review_bullet_field_value(lines: Sequence[str], index: int, inline: str) -> str:
    if inline:
        return inline
    collected: list[str] = []
    for line in lines[index + 1 :]:
        if REVIEW_BULLET_FIELD_LABEL_PATTERN.match(line) or REVIEW_BULLET_HEADING_PATTERN.match(
            line
        ):
            break
        if line and not line[0].isspace():
            break
        stripped = line.strip()
        if stripped:
            collected.append(stripped)
    return "\n".join(collected)


def find_review_bullet_field_values(lines: Sequence[str], field: str) -> list[str]:
    pattern = review_bullet_field_label_pattern(field)
    values: list[str] = []
    for index, line in enumerate(lines):
        match = pattern.fullmatch(line)
        if match is None:
            continue
        values.append(_review_bullet_field_value(lines, index, match.group(1)))
    return values


def parse_review_bullet_field(lines: Sequence[str], field: str) -> str:
    """Parse one `- **Field**:` review bullet, including indented continuations."""
    values = find_review_bullet_field_values(lines, field)
    if len(values) != 1:
        raise ValueError(field)
    return values[0]


# Sample paths the pipeline must commit. A product rule such as an unanchored
# `build/` would otherwise drop them silently from every commit.
PROJECT_PROBE_PATHS = (
    ".project/STATE.md",
    ".project/LESSONS.md",
    ".project/REPOSITORY.md",
    ".project/MEMBERS.md",
    ".project/CHARTER.md",
    ".project/ROADMAP.md",
    ".project/SYNTHESIS.md",
    VERIFY_LEDGER_PATH,
    ".project/build/members.json",
    ".project/build/evidence.json",
    ".project/archive/001-probe/build/evidence.json",
    ".project/archive/001-probe/build/verify-ledger.jsonl",
    ".project/intent/probe.md",
    ".project/research/probe.md",
    ".project/plan/probe.md",
    ".project/plan/PLAN.md",
    ".project/tasks/probe.md",
    ".project/review/probe.md",
    ".project/discuss/probe.md",
    ".project/next/probe.md",
)


def project_ignore_error(repo: Path) -> Optional[str]:
    """Why ignore rules would drop pipeline state from commits, or None."""
    result = subprocess.run(
        ("git", "-C", str(repo), "check-ignore", "-v", "-n", "-z", "--no-index", "--stdin"),
        input="\0".join(PROJECT_PROBE_PATHS) + "\0",
        encoding="utf-8",
        errors="surrogateescape",
        capture_output=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        return f"could not check ignore rules: {result.stderr.strip()}"
    fields = result.stdout.split("\0")
    hits = []
    for index in range(0, len(fields) - 3, 4):
        source, line, pattern, path = fields[index:index + 4]
        # A `!` match re-includes the path; only a plain match excludes it.
        if pattern and not pattern.startswith("!"):
            hits.append(f"{source}:{line}:{pattern} excludes {path}")
    if not hits:
        return None
    return ("ignore rules exclude GSD Path state that must be committed: "
            + "; ".join(hits)
            + ". Anchor the product rule (for example `/build/`) in a task that owns it.")


_DEFAULT_BRANCH_RE = re.compile(
    r"[^\s#\"'\\~^:?*\[\x00-\x1f\x7f-][^\s#\"'\\~^:?*\[\x00-\x1f\x7f]*"
)
_RESERVED_BRANCH_PREFIXES = ("gsd-path/", "gsd-path-integrate/", "gsd-path-task/")


def valid_default_branch(name: str) -> bool:
    """A git branch name that STATE frontmatter can hold and Path does not reserve."""
    return (
        bool(_DEFAULT_BRANCH_RE.fullmatch(name))
        and name != "null"
        and not name.startswith(_RESERVED_BRANCH_PREFIXES)
        and not name.endswith(("/", ".", ".lock"))
        and not any(part in name for part in ("..", "//", "/.", "@{"))
    )


def origin_default_branch(repo: Path) -> str:
    """The origin default branch that initialization records; an unset origin/HEAD means main."""
    result = run_git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    prefix = "refs/remotes/origin/"
    remote_ref = result.stdout.strip()
    if result.returncode != 0 or not remote_ref.startswith(prefix):
        return "main"
    return remote_ref.removeprefix(prefix)


def section_body(text: str, heading: str) -> Optional[str]:
    """The text under `## <heading>` up to the next `## `, or None when absent."""
    match = re.search(
        rf"(?ms)^## {re.escape(heading)}\s*\n(?P<body>.*?)(?=^## |\Z)", text
    )
    return match.group("body") if match else None


def contract_shapes(body: str) -> Set[str]:
    """The whitespace-normalized `- ` entries of an Interface contract body.

    HTML comments are dropped and continuation lines join their entry. A
    body that says only `None` has no shapes.
    """
    cleaned = re.sub(r"(?s)<!--.*?-->", "", body).strip()
    if " ".join(cleaned.split()) in {"", "None", "- None"}:
        return set()
    entries = re.split(r"(?m)^-[ \t]+", cleaned)
    return {shape for shape in (" ".join(entry.split()) for entry in entries) if shape}


def overlapping_paths(left: Sequence[str], right: Sequence[str]) -> List[str]:
    """Return the sorted paths that two task `files` lists both cover.

    An entry covers itself and the paths below it. For a declared directory
    and a path below it, the result names the lower path. The callers have no
    task base, so this does not ask if an entry is a file: the task-brief
    lint rejects a path below a file at the base.
    """
    return sorted(
        {
            max(one, other, key=len)
            for one in left
            for other in right
            if one == other or one.startswith(other + "/") or other.startswith(one + "/")
        }
    )


# The `- ` of an indented sub-bullet line. A line that would then read as a
# numbered item (`- 2. text`) keeps its marker, so both readings of a source
# have the same criteria.
SUB_BULLET_MARKER = re.compile(r"(?m)^([ \t]+)-[ \t]+(?![ \t]*\d+\.\s)")


def without_sub_bullet_markers(source: str) -> str:
    """`source` with the `- ` marker of each indented sub-bullet line removed."""
    return SUB_BULLET_MARKER.sub(r"\1", source)


class Criterion(str):
    """A criterion as its parser joins it, with the `- ` markers of its sub-bullet lines.

    `bare` is the same criterion parsed from `without_sub_bullet_markers(source)`.
    The joined text cannot tell a marker from a minus sign; the source lines can.
    """

    bare: str

    def __new__(cls, text: str, bare: str) -> "Criterion":
        criterion = super().__new__(cls, text)
        criterion.bare = bare
        return criterion


def quotes_criterion(quote: str, criterion: str) -> bool:
    """Whether a review quote is `criterion`, for every reader.

    Only whitespace is collapsed. The quote must equal the criterion with all
    the markers of its sub-bullet lines or with none of them; every other
    character, a hyphen inside a line too, is compared.
    """
    forms = (criterion, getattr(criterion, "bare", criterion))
    return " ".join(quote.split()) in {" ".join(form.split()) for form in forms}


_COMMENT_OR_CODE_SPAN = re.compile(
    r"(?<!`)(?<!\\)(`+)(?!`)(?:(?!\1)[^\n])*?\1|<!--.*?-->", re.DOTALL
)


def strip_html_comments(text: str) -> str:
    """Remove HTML comments, keeping inline code spans verbatim.

    A criterion may quote a Path marker comment as inline code; the naive
    ``<!--.*?-->`` regex ate it on whichever side was stripped, so gates
    that stripped one side and read the other raw compared different
    texts (#548). One span-preserving stripper on every side keeps
    verbatim quotes equal everywhere; a comment outside a code span
    still strips. An opener never starts inside a longer backtick run or
    behind an escaped backtick, matching CommonMark's span openers.
    """
    return _COMMENT_OR_CODE_SPAN.sub(
        lambda match: match.group(0) if match.group(1) else "", text
    )


def strip_code_spans(text: str) -> str:
    """Remove inline code spans, keeping HTML comments intact."""
    return _COMMENT_OR_CODE_SPAN.sub(
        lambda match: "" if match.group(1) else match.group(0), text
    )


def quoted_criterion(item: str, criteria: Sequence[str]) -> Optional[Tuple[int, int]]:
    """Index of the criterion quoted at the start of `item`, and where the quote ends.

    A criterion can contain ` — ` itself, so each separator and the end of
    `item` is a candidate, the longest quote first. A criterion as written
    wins over any criterion read without its sub-bullet markers.
    """
    ends = [match.start() for match in re.finditer("(?= —(?: |$))|$", item)][::-1]
    for bare in (False, True):
        for end in ends:
            quote = " ".join(item[:end].split())
            for index, criterion in enumerate(criteria):
                form = getattr(criterion, "bare", criterion) if bare else criterion
                if quote == " ".join(form.split()):
                    return index, end
    return None


def task_verify_command(task_text: str) -> str:
    """The Verify shell text, excluding the closing fence's separator newline."""
    body = section_body(task_text, "Verify")
    block = VERIFY_BLOCK_PATTERN.search(body) if body is not None else None
    return block.group("block").removesuffix("\n") if block else ""


def fix_verify(commands: Iterable[str]) -> str:
    """The Verify of a fix task: each distinct source Verify in its own subshell, under `set -e`."""
    return "set -e\n" + "\n".join(f"(\n{command}\n)" for command in dict.fromkeys(commands))


def latest_verify_entry(entries: list, command: str, commit: str,
                        repo: Optional[str] = None) -> Optional[dict]:
    """Rows are keyed by (command, repo, commit); a row without `repo` is a coordinator row."""
    for entry in reversed(entries):
        if (entry.get("schema") == VERIFY_LEDGER_SCHEMA and entry.get("repo") == repo
                and entry["command"] == command and entry["commit"] == commit):
            return entry
    return None


def verify_ledger_entries(path: Path) -> list:
    """Parsed verify-ledger rows; raises ValueError on a malformed line."""
    if not path.exists():
        return []
    return parse_verify_ledger(path.read_text(encoding="utf-8"))


def read_user_text(path: Path) -> str:
    """Read a user-edited text file with CRLF normalized to LF."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def parse_verify_ledger(text: str) -> list:
    entries = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{VERIFY_LEDGER_PATH} line {number} is not JSON: {error}") from error
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("command"), str)
            or not isinstance(entry.get("commit"), str)
            or entry.get("result") not in VERIFY_RESULTS
            or not isinstance(entry.get("recorded_at"), str)
            or ("repo" in entry and not isinstance(entry["repo"], str))
        ):
            raise ValueError(f"{VERIFY_LEDGER_PATH} line {number} has invalid fields")
        entries.append(entry)
    return entries


def _run_exact(
    argv: Sequence[str], *, cwd: Optional[Path] = None, input: Optional[str] = None
) -> subprocess.CompletedProcess[str]:
    """subprocess.run with UTF-8 text and no newline translation.

    Text-mode pipes on Windows turn "\\n" into "\\r\\n" on the way in, so text
    handed to git hash-object would no longer match the committed blob.
    """
    completed = subprocess.run(
        argv,
        cwd=cwd,
        input=None if input is None else input.encode("utf-8", "surrogateescape"),
        capture_output=True,
        check=False,
    )
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        completed.stdout.decode("utf-8", "surrogateescape"),
        completed.stderr.decode("utf-8", "surrogateescape"),
    )


def run_command(
    *arguments: str, cwd: Optional[Path] = None
) -> subprocess.CompletedProcess[str]:
    return _run_exact(resolve_argv(arguments), cwd=cwd)


def run_git(
    repo: Path, *arguments: str, input: Optional[str] = None
) -> subprocess.CompletedProcess[str]:
    return _run_exact(git_command(repo, *arguments), input=input)


def _patch_ids(repo: Path, commits: Sequence[str]) -> list[Optional[str]]:
    """`git patch-id --stable` per commit, in order; None for an empty commit."""
    log = run_git(repo, "log", "--no-walk=unsorted", "-p", "--binary", "--no-color",
                  "--no-ext-diff", *commits)
    if log.returncode != 0:
        raise ValueError("could not read commit patches")
    ids = run_git(repo, "patch-id", "--stable", input=log.stdout)
    if ids.returncode != 0:
        raise ValueError("could not compute patch ids")
    by_commit = {commit: patch for patch, commit in (line.split() for line in ids.stdout.splitlines())}
    return [by_commit.get(commit) for commit in commits]


def rebase_landing_problem(repo: Path, ship: str, landing: str) -> Optional[str]:
    """Why landing is not a forge rebase merge of ship, or None when it is (#418).

    A rebase merge replays ship's own commits onto the default branch. Proof:
    the first-parent run that ends at landing has one non-merge commit per
    non-merge commit of landing..ship, with equal patch ids in the same order;
    when that run starts at ship's fork point, landing's tree equals ship's.
    """
    listed = run_git(repo, "rev-list", "--reverse", "--topo-order", "--no-merges", f"{landing}..{ship}")
    if listed.returncode != 0:
        return "could not list the ship commits"
    originals = listed.stdout.split()
    if not originals:
        return "landing already contains the ship commit"
    walked = run_git(repo, "rev-list", "--first-parent", "--parents", "-n", str(len(originals)), landing)
    rows = [line.split() for line in walked.stdout.splitlines()][::-1]
    if walked.returncode != 0 or len(rows) != len(originals) or any(len(row) != 2 for row in rows):
        return "landing is not a linear run of rebased commits"
    try:
        if _patch_ids(repo, originals) != _patch_ids(repo, [row[0] for row in rows]):
            return "rebased commits do not replay the ship commits in order"
    except ValueError as error:
        return str(error)
    fork = run_git(repo, "merge-base", ship, landing).stdout.strip()
    trees = run_git(repo, "rev-parse", f"{ship}^{{tree}}", f"{landing}^{{tree}}").stdout.split()
    if rows[0][1] == fork and (len(trees) != 2 or trees[0] != trees[1]):
        return "rebased tree differs from the ship tree"
    return None


def git_command(repo: Path, *arguments: str) -> tuple[str, ...]:
    """Git argv for repo, including WSL drvfs workarounds when needed.

    core.quotepath=false keeps non-ASCII paths raw in path listings so
    they compare equal to the UTF-8 paths tasks declare (#545).
    """
    return (
        "git",
        "-C",
        str(repo),
        "-c",
        "core.quotepath=false",
        *git_drvfs_config_flags(repo),
        *arguments,
    )


def git_drvfs_config_flags(repo: Path) -> tuple[str, ...]:
    """Disable index preload on 9p/drvfs mounts where git commit races on index.lock (#207)."""
    if os.name != "posix":
        return ()
    try:
        root = repo.resolve()
        mounts = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ()
    best = ""
    fstype = ""
    for line in mounts:
        parts = line.split()
        if len(parts) < 3:
            continue
        mount_point, mount_type = parts[1], parts[2]
        if mount_type not in {"9p", "drvfs"}:
            continue
        if root == Path(mount_point) or root.is_relative_to(mount_point):
            if len(mount_point) >= len(best):
                best, fstype = mount_point, mount_type
    if not fstype:
        return ()
    return ("-c", "core.preloadindex=false", "-c", "index.threads=1")


def git_index_lock_retryable(stderr: str) -> bool:
    text = stderr.casefold()
    return "index.lock" in text and "file exists" in text


# OS files that are never pipeline artifacts when git ignores them.
# ponytail: .DS_Store only (#149); add Thumbs.db and the like when reported.
OS_JUNK_NAMES = frozenset({".DS_Store"})


def is_ignored_junk(path: Path) -> bool:
    """True for an OS junk file that git ignores and does not track."""
    if path.name not in OS_JUNK_NAMES or path.is_symlink() or not path.is_file():
        return False
    return run_git(path.parent, "check-ignore", "-q", "--", path.name).returncode == 0


def git_visible_entries(directory: Path) -> set:
    """Top-level names under directory that git tracks or would add (not ignored)."""
    result = run_git(directory, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", ".")
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed in {directory}: {result.stderr.strip()}")
    return {path.split("/", 1)[0] for path in result.stdout.split("\0") if path}


RUNTIME_PIN_PATH = ".gsd-path/runtime.json"
RUNTIME_PIN_ALLOWANCE = (
    "only runtime-pin commits (.gsd-path/runtime.json) may follow the reviewed HEAD"
)


def reviewed_head_covers(repo: Path, reviewed: str, head: str) -> bool:
    """True when a review of `reviewed` still covers `head`.

    That is the same commit, or `reviewed` is an ancestor of `head` and every
    commit on the first-parent path in ``reviewed..head`` is a non-merge commit
    whose only change is ``.gsd-path/runtime.json``. An empty commit does not
    qualify. Any other path, any merge commit, an unresolvable SHA, or a
    non-ancestor returns False.
    """
    if not reviewed or not head:
        return False
    resolved_repo = Path(repo)
    resolved: List[str] = []
    for value in (reviewed, head):
        result = run_git(
            resolved_repo, "rev-parse", "--verify", "--quiet", f"{value}^{{commit}}"
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False
        resolved.append(result.stdout.strip())
    reviewed_sha, head_sha = resolved
    if reviewed_sha == head_sha:
        return True
    if (
        run_git(resolved_repo, "merge-base", "--is-ancestor", reviewed_sha, head_sha).returncode
        != 0
    ):
        return False
    listing = run_git(
        resolved_repo,
        "rev-list",
        "--first-parent",
        "--parents",
        f"{reviewed_sha}..{head_sha}",
    )
    if listing.returncode != 0:
        return False
    for line in listing.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2:
            return False
        commit_sha, parent_sha = fields[0], fields[1]
        changed = run_git(
            resolved_repo,
            "diff",
            "--name-only",
            "--no-renames",
            "--no-ext-diff",
            parent_sha,
            commit_sha,
        )
        if changed.returncode != 0:
            return False
        if {path for path in changed.stdout.splitlines() if path} != {RUNTIME_PIN_PATH}:
            return False
    return True


def atomic_replace(path: Path, temporary_path: Path, content: str) -> None:
    temporary_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = None
    try:
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_BINARY,
            0o666,
        )
        # Bytes, so Windows text mode never turns "\n" into "\r\n".
        handle = os.fdopen(descriptor, "wb")
        descriptor = None
        with handle:
            handle.write(content.encode("utf-8"))
        replace(temporary_path, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()


def atomic_write(path: Path, content: str) -> None:
    atomic_replace(path, path.parent / f".{path.name}.gsd-path-tmp", content)


def strip_yaml_comment(value: str) -> str:
    quote = None
    previous_significant = None
    inline_list = value.lstrip().startswith("[")
    index = 0
    while index < len(value):
        character = value[index]
        if quote == '"':
            if character == "\\" and index + 1 < len(value):
                index += 2
                continue
            if character == quote:
                quote = None
        elif quote == "'":
            if (
                character == quote
                and index + 1 < len(value)
                and value[index + 1] == quote
            ):
                index += 2
                continue
            if character == quote:
                quote = None
        else:
            if character in {"'", '"'} and (
                previous_significant is None
                or (inline_list and previous_significant in {"[", ","})
            ):
                quote = character
            elif character == "#" and (
                index == 0 or value[index - 1].isspace()
            ):
                return value[:index].rstrip()
        if quote is None and not character.isspace():
            previous_significant = character
        index += 1
    return value.strip()


def unquote(value: str) -> str:
    cleaned = strip_yaml_comment(value).strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in {"'", '"'}
    ):
        return cleaned[1:-1]
    return cleaned


# --- Platform helpers --------------------------------------------------------
# Each helper keeps the POSIX behavior the scripts had before and adds the
# native Windows equivalent. Windows has no fcntl, cannot open a directory as
# a descriptor, and treats os.kill(pid, 0) as a Ctrl+C, not a probe.

# Sharing violation and access denied: another process briefly holds the file.
_WINDOWS_BUSY_ERRORS = (5, 32)
_REPLACE_ATTEMPTS = 20


def replace(source: Path, destination: Path) -> None:
    """os.replace, retried while a Windows reader briefly holds the destination."""
    if os.name != "nt":
        os.replace(source, destination)
        return
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError as error:
            if (getattr(error, "winerror", None) not in _WINDOWS_BUSY_ERRORS
                    or attempt == _REPLACE_ATTEMPTS - 1):
                raise
            time.sleep(min(0.01 * 2 ** attempt, 0.25))


def fsync_directory(path: Path) -> None:
    """Persist a directory entry change; Windows cannot open a directory to fsync it."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def exclusive_lock(
    path: Path, *, blocking: bool = True, timeout: Optional[float] = None
) -> Iterator[BinaryIO]:
    """Hold an exclusive lock on the file at path, creating it when absent.

    A non-blocking attempt that loses raises BlockingIOError; a blocking one
    that outlives timeout raises TimeoutError. Windows msvcrt LK_LOCK gives up
    after ten seconds, so both platforms poll a non-blocking lock instead.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = None if timeout is None else time.monotonic() + timeout
    with open(path, "a+b") as handle:
        if fcntl is None:
            # msvcrt locks bytes from the current position; keep one to lock.
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
        delay = 0.01
        while True:
            try:
                if fcntl is None:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                elif blocking and deadline is None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if not blocking:
                    raise BlockingIOError(errno.EAGAIN, f"lock is held: {path}") from error
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for lock: {path}") from error
                time.sleep(delay)
                delay = min(delay * 2, 0.25)
        try:
            yield handle
        finally:
            if fcntl is None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


_WAIT_OBJECT_0 = 0x0
_WAIT_ABANDONED = 0x80
_WAIT_TIMEOUT = 0x102


@contextlib.contextmanager
def directory_mutex(
    directory: Path, *, blocking: bool = True, timeout: Optional[float] = None
) -> Iterator[None]:
    """Windows-only exclusive lock keyed on a directory's resolved path.

    POSIX flocks the directory itself. Windows cannot lock a directory, and a
    lock file inside it would be committed, so this holds a named kernel mutex
    in the session namespace. A holder that dies releases it (WAIT_ABANDONED).
    Contention raises BlockingIOError (non-blocking) or TimeoutError.
    """
    import ctypes
    import hashlib
    from ctypes import wintypes

    identity = os.path.normcase(str(directory.resolve()))
    name = "Local\\gsd-path-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            # Wait in short slices so Ctrl+C still interrupts a blocked caller.
            result = kernel32.WaitForSingleObject(handle, 0 if not blocking else 200)
            if result in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
                break
            if result != _WAIT_TIMEOUT:
                raise ctypes.WinError(ctypes.get_last_error())
            if not blocking:
                raise BlockingIOError(errno.EAGAIN, f"lock is held: {directory}")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for lock: {directory}")
        try:
            yield
        finally:
            kernel32.ReleaseMutex(handle)
    finally:
        kernel32.CloseHandle(handle)


def process_alive(pid: int) -> bool:
    """Whether pid names a running process, without signalling it.

    Windows os.kill(pid, 0) sends CTRL_C_EVENT, so Windows asks the kernel.
    status_runtime and install carry verbatim copies (they cannot import this
    module); tests/test_common_platform.py keeps them identical.
    """
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError as error:
            return error.errno == errno.EPERM
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        # ERROR_ACCESS_DENIED: a protected process exists but refuses the query.
        return ctypes.get_last_error() == 5
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def popen_group(argv: Sequence[str], **kwargs) -> subprocess.Popen:
    """Start argv as the leader of a new process group that kill_tree can end."""
    if os.name == "nt":
        kwargs["creationflags"] = (kwargs.get("creationflags", 0)
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(list(argv), **kwargs)


# Windows creation flags for a background process that outlives its caller.
_CREATE_NO_WINDOW = 0x08000000
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def popen_detached(argv: Sequence[str], **kwargs) -> subprocess.Popen:
    """Start a background process that survives its caller's exit.

    POSIX starts a new session. Windows hosts may run commands in a job object
    that kills its members when the command returns, so this breaks away when
    the job allows it, and gives the process a hidden console that its console
    children inherit instead of flashing new windows.
    """
    if os.name != "nt":
        return subprocess.Popen(list(argv), start_new_session=True, **kwargs)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW
    try:
        return subprocess.Popen(list(argv), creationflags=flags | _CREATE_BREAKAWAY_FROM_JOB, **kwargs)
    except PermissionError:
        # The job forbids breakaway; the process still runs, bound to that job.
        return subprocess.Popen(list(argv), creationflags=flags, **kwargs)


def kill_tree(process: subprocess.Popen) -> None:
    """Forcibly end a popen_group process and every descendant it started."""
    if os.name == "nt":
        subprocess.run(
            ("taskkill", "/T", "/F", "/PID", str(process.pid)),
            capture_output=True,
            check=False,
        )
        if process.poll() is None:
            process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class ShellNotFound(RuntimeError):
    pass


def _is_wsl_launcher(path: str) -> bool:
    folded = os.path.normcase(os.path.abspath(path))
    system_root = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
    windows_apps = os.path.normcase(os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps"))
    return folded.startswith(system_root + os.sep) or (
        bool(os.environ.get("LOCALAPPDATA")) and folded.startswith(windows_apps + os.sep))


def find_bash() -> str:
    """The bash that runs Verify commands; on Windows, Git for Windows' bash.exe.

    Windows puts the WSL launcher at System32\\bash.exe, ahead of PATH, so a
    bare "bash" would run the command in another OS. GSD_PATH_BASH overrides.
    """
    if os.name != "nt":
        return "bash"
    override = os.environ.get("GSD_PATH_BASH")
    if override:
        if not os.path.isfile(override):
            raise ShellNotFound(f"GSD_PATH_BASH is not a file: {override}")
        return override
    candidates = []
    found = shutil.which("bash")
    if found:
        candidates.append(found)
    git = shutil.which("git")
    if git:
        # <Git>\cmd\git.exe or <Git>\bin\git.exe -> <Git>\bin\bash.exe
        candidates.append(os.path.join(os.path.dirname(os.path.dirname(git)), "bin", "bash.exe"))
    for variable in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            parts = ("Programs", "Git") if variable == "LOCALAPPDATA" else ("Git",)
            candidates.append(os.path.join(base, *parts, "bin", "bash.exe"))
    for candidate in candidates:
        if os.path.isfile(candidate) and not _is_wsl_launcher(candidate):
            return candidate
    raise ShellNotFound(
        "Verify commands need bash; install Git for Windows or set GSD_PATH_BASH "
        "to its bin\\bash.exe (the System32 WSL launcher is never used)"
    )


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _command_script_dir() -> str:
    """A temp directory for command scripts that cannot dirty the running tree.

    TMPDIR/TEMP/TMP may point into the tree being verified, and a script file
    there shows up in git status and blocks landings (#448), so fall back to a
    system directory when the environment temp sits inside the current tree.
    """
    candidate = os.path.realpath(tempfile.gettempdir())
    tree = os.path.realpath(os.getcwd())
    if candidate != tree and not candidate.startswith(tree + os.sep):
        return candidate
    for fallback in (
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp"),
        "/var/tmp",
        "/tmp",
    ):
        resolved = os.path.realpath(fallback)
        if os.path.isdir(resolved) and resolved != tree and not resolved.startswith(tree + os.sep):
            return resolved
    raise OSError("no temp directory outside the current worktree for a command script")


def bash_argv(command: str) -> List[str]:
    if os.name != "nt":
        return [find_bash(), "-c", command]
    # Git for Windows' bash (MSYS2) cuts an argument that carries a double
    # quote near 8 KB before bash sees it, so a long Verify dies mid-script
    # or silently passes when the cut lands in comments (#448). Run the exact
    # bytes from a temp file outside every worktree instead.
    bash = find_bash()
    descriptor, path = tempfile.mkstemp(
        prefix="gsd-path-command-", suffix=".sh", dir=_command_script_dir()
    )
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(command)
    atexit.register(_remove_quietly, path)
    return [bash, path]


# cmd.exe re-parses the arguments of a .cmd or .bat target, so these would
# let an argument escape its quoting.
_CMD_METACHARACTERS = frozenset('%^&|<>"!\r\n')


def resolve_argv(argv: Sequence[str]) -> List[str]:
    """argv with its program resolved the way a shell would find it.

    Windows CreateProcess only appends .exe, so npm-installed CLIs such as
    claude.cmd or codex.cmd are found through PATHEXT here. POSIX is unchanged.
    """
    arguments = list(argv)
    if os.name != "nt" or not arguments:
        return arguments
    program = shutil.which(arguments[0])
    if program is None:
        raise FileNotFoundError(f"command not found: {arguments[0]}")
    if program.lower().endswith((".cmd", ".bat")):
        for argument in arguments[1:]:
            if _CMD_METACHARACTERS.intersection(argument):
                raise ValueError(
                    f"argument {argument!r} is unsafe to pass to {program}; "
                    "cmd.exe would reinterpret it"
                )
    return [program, *arguments[1:]]


def split_command(text: str) -> List[str]:
    """Split a command string with POSIX quoting.

    Agents write these in a POSIX shell (Git Bash on Windows), so single and
    double quotes group as in sh. On Windows backslash is not an escape, so a
    path such as C:\\Python312\\python.exe keeps its separators.
    """
    if os.name != "nt":
        return shlex.split(text)
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    lexer.commenters = ""
    return list(lexer)


def rmtree_force(path: Path) -> None:
    """shutil.rmtree that also removes read-only files, such as git objects on Windows."""

    def clear_readonly(function, target, _error) -> None:
        os.chmod(target, 0o700)
        function(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=clear_readonly)
    else:
        shutil.rmtree(path, onerror=clear_readonly)
