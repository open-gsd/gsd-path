#!/usr/bin/env python3
"""Cross-host pre-tool-use guard for GSD Path projects.

Reads one hook event as JSON on stdin and enforces the two pipeline
invariants a prompt contract cannot guarantee:

- committed archives under .project/archive/ are read-only (only the bundled
  helpers pipeline_state.py and archive_milestone.py in the guard-owned runtime
  directory may name that path in a single plain python or python3 command), and
- destructive git commands that break build recovery are refused.

Allow: exit 0 with no output, except Cursor (whose fail-closed hooks treat
empty stdout as a failure) also gets {"permission": "allow"} on stdout.
Deny: exit 2, a one-line reason on stderr,
and a denial JSON on stdout carrying every supported host's decision keys
(exit code 2 satisfies Claude Code, Codex, Qwen, Kimi, Grok, Cursor, and
Kiro; the JSON covers hosts that read a decision object instead).
Malformed input or an internal failure denies the tool call.
"""

import ast
from fnmatch import fnmatchcase
from functools import lru_cache
import json
import os
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

PATH_KEYS = frozenset(
    {
        "file_path",
        "filepath",
        "path",
        "file",
        "notebook_path",
        "target_file",
        "relative_path",
        "target_notebook",
        "notebook",
        "directory",
    }
)
MUTATION_OPERAND_KEYS = frozenset(
    {
        "destination",
        "destination_directory",
        "destination_file",
        "destination_path",
        "from",
        "from_file",
        "from_path",
        "old_file",
        "old_path",
        "source",
        "source_directory",
        "source_file",
        "source_notebook",
        "source_path",
        "target_path",
        "to",
        "to_file",
        "to_path",
    }
)
WORKING_DIRECTORY_KEYS = frozenset({"working_directory", "workdir", "cwd"})
COMMAND_KEYS = frozenset({"command", "cmd", "script"})
PATCH_KEYS = frozenset({"patch", "patch_body", "patch_text", "diff"})
PATCH_PATH_PATTERN = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File: (.+)$|^\*\*\* Move to: (.+)$",
    re.MULTILINE,
)
UNIFIED_DIFF_PATH_PATTERN = re.compile(
    r"^(?:---|\+\+\+) ([^\t\r\n]+)$", re.MULTILINE
)
GIT_DIFF_PATH_PATTERN = re.compile(
    r'^diff --git ("(?:\\.|[^"])*"|\S+) ("(?:\\.|[^"])*"|\S+)$',
    re.MULTILINE,
)
GIT_RENAME_PATH_PATTERN = re.compile(
    r"^(?:rename from|rename to) (.+)$", re.MULTILINE
)

# A tool skips path checks only when its name carries a read-only verb and
# no write-capable verb: `get_and_write` must still be path-checked.
READ_VERBS = frozenset(
    {"read", "grep", "glob", "search", "view", "list", "get", "cat", "open"}
)
WRITE_VERBS = frozenset(
    {
        "write",
        "save",
        "copy",
        "touch",
        "edit",
        "create",
        "delete",
        "remove",
        "update",
        "set",
        "put",
        "post",
        "patch",
        "move",
        "rename",
        "append",
        "insert",
        "replace",
    }
)
AMBIGUOUS_WRITE_VERBS = frozenset({"create", "update", "set", "put", "post"})
DIRECT_FILE_WRITE_VERBS = WRITE_VERBS - AMBIGUOUS_WRITE_VERBS
FILE_TARGET_TOKENS = frozenset({"file", "path", "notebook"})
TOOL_TOKEN_PATTERN = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
SHELL_ASSIGNMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

ARCHIVE_REASON = (
    "committed GSD Path archives under .project/archive/ are read-only; "
    "only the bundled pipeline helpers may write there during a ship transaction"
)
DESTRUCTIVE_SHAPE_REASON = (
    "destructive commands must run alone with literal paths; split compound, "
    "substituted, or expanded destructive commands into single commands"
)
ARCHIVE_MARKER = ".project/archive"
INVALID_INPUT_REASON = "GSD Path guard could not validate the tool request"
CONTROL_PATHS = ".git, .project/STATE.md, .project/next, .gsd-path"
PROTECTED_SHELL_WRITE_REASON = (
    f"GSD Path routing controls ({CONTROL_PATHS}) change only through the "
    "pipeline helpers; the shell command writes"
)
REENTRY_FAILURE_REASON = (
    "GSD Path status could not be verified; review .project/STATE.md and invoke "
    "gsd-path-forensics before changing product files"
)
CONTROL_FILE_REASON = (
    "GSD Path routing controls cannot be changed by direct write, edit, or patch "
    "tools; use the pipeline helpers (pipeline_state.py) for"
)
STATUS_ACTIONS = frozenset(
    {
        "bind-initial",
        "block",
        "resume-checkpoint",
        "resume-next-handoff",
        "resume-promotion",
        "resume-shipment",
        "resume-undo",
        "run-phase",
        "validate-integrated",
        "wait",
    }
)
STATUS_PHASES = frozenset(
    {
        "inspect",
        "define",
        "research",
        "decide",
        "roadmap",
        "plan",
        "build",
        "ship",
        "shipped",
    }
)
STATUS_VALUES = frozenset({"active", "done", "blocked"})
STATUS_STATE_FIELDS = frozenset(
    {
        "pipeline",
        "project",
        "milestone",
        "phase",
        "status",
        "branch",
        "archive",
        "integration_default",
        "integration",
        "integration_source",
    }
)
STATUS_INTEGRATION_MODES = frozenset({"direct", "pull-request", "external-landing"})
STATUS_INTEGRATION_SOURCES = frozenset({"default", "milestone"})
STATUS_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
STATUS_BRANCH = re.compile(r"^gsd-path/M(\d{3,})$")
STATUS_ARCHIVE = re.compile(r"^\.project/archive/(\d{3,})-([a-z0-9][a-z0-9-]*)/?$")
STATUS_TRANSITIONS = {
    "inspect": frozenset({"inspect", "define"}),
    "define": frozenset({"define", "research", "plan"}),
    "research": frozenset({"research", "decide"}),
    "decide": frozenset({"decide", "roadmap", "plan"}),
    "roadmap": frozenset({"roadmap", "define"}),
    "plan": frozenset({"plan", "build"}),
    "build": frozenset({"build"}),
    "ship": frozenset({"ship", "plan"}),
    "shipped": frozenset({"ship"}),
}
ARCHIVE_REFERENCE = re.compile(r"(?i:\.project[\\/]archive)")
ARCHIVE_READ_COMMANDS = frozenset(
    {
        "cat",
        "head",
        "tail",
        "grep",
        "rg",
        "sed",
        "ls",
        "stat",
        "wc",
        "file",
        "readlink",
        "realpath",
        "test",
        "get-content",
        "get-childitem",
        "get-item",
        "get-acl",
        "select-string",
        "test-path",
    }
)
ARCHIVE_READ_GIT_COMMANDS = frozenset({"status", "diff", "log", "show", "ls-files"})
CLOSED_READ_GIT_COMMANDS = ARCHIVE_READ_GIT_COMMANDS | {
    "rev-parse", "ls-remote", "ls-tree", "show-ref", "merge-base",
}
# Subcommands that also have write forms: only these listing options keep them read-only.
CLOSED_LISTING_GIT_OPTIONS = {
    "cat-file": frozenset({"-p", "-t", "-s", "-e"}),
    "branch": frozenset({"-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose", "-l", "--list", "--show-current", "--no-color"}),
    "worktree list": frozenset({"--porcelain", "-v", "--verbose", "-z"}),
    "symbolic-ref": frozenset({"-q", "--quiet", "--short"}),
}
GIT_READ_WRITE_OPTIONS = frozenset({"--output", "--ext-diff", "--textconv"})
ARCHIVE_READ_EXECUTION_OPTIONS = {"rg": frozenset({"--pre"})}
AMBIGUOUS_SHELL_SYNTAX = re.compile(r"[\r\n|;&<>`]|\$\(|@\(")
SUBSTITUTION_PLACEHOLDER = "COMMAND_SUBSTITUTION_"
SUBSTITUTION_PLACEHOLDER_SYNTAX = re.compile(
    r"\$\{" + SUBSTITUTION_PLACEHOLDER + r"(\d+)\}"
)
LINE_CONTINUATION = re.compile(r"(?<!\\)((?:\\\\)*)\\\r?\n")
SHELL_WRITE_REDIRECTION_CHARS = frozenset("<>&|")
SHELL_PARAMETER_SYNTAX = re.compile(
    r"\$(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]+|[-*@#?$!]|\{[^}\r\n]+\})"
)
NAMED_SHELL_PARAMETER_SYNTAX = re.compile(
    r"\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\})"
)
CMD_PARAMETER_SYNTAX = re.compile(
    r"%([A-Za-z_][A-Za-z0-9_]*)%|!([A-Za-z_][A-Za-z0-9_]*)!"
)
DIRECTORY_CHANGE_COMMANDS = frozenset(
    {"cd", "chdir", "pushd", "set-location", "sl"}
)
GIT_REASONS = {
    "reset": "git reset --hard discards work the build recovery protocol needs",
    "clean": "git clean -f deletes untracked evidence and retained task worktrees",
    "push": "force pushes rewrite build-branch history the pipeline resumes from",
    "branch": "git branch -D destroys task branches the recovery protocol inspects",
    "unresolved-target": (
        "{action} needs a literal target the guard can resolve; name the branch, "
        "ref, or registered worktree directly"
    ),
    "git-environment": (
        "env changes Git's repository or alias configuration context; run the Git "
        "command without resetting or unsetting Git-related environment variables"
    ),
    "branch-move": (
        "git branch -m renames a branch the pipeline resumes by name "
        "(STATE.branch); create a new branch instead"
    ),
    "update-ref": "git update-ref deletion destroys refs the recovery protocol inspects",
    "worktree": (
        "git worktree remove --force discards uncommitted task work the recovery "
        "protocol needs; commit or stash it, then remove without --force"
    ),
    "stash": (
        "git stash drop and git stash clear destroy stashed work the recovery "
        "protocol may need; apply or keep the stash"
    ),
    "checkout": (
        "git checkout -- . and git restore . discard every uncommitted change; "
        "name the files to restore instead"
    ),
}
WHOLE_TREE_PATHSPECS = frozenset({".", "./", ":/"})
GIT_GLOBAL_OPTIONS_WITH_VALUES = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
)
ENV_OPTIONS_WITH_VALUES = frozenset({"-C", "-u", "--chdir", "--unset"})
ENV_OPTIONS_WITHOUT_VALUES = frozenset(
    {"-0", "-i", "-v", "--debug", "--ignore-environment", "--null"}
)
POSIX_SHELL_WRAPPERS = frozenset({"bash", "dash", "fish", "ksh", "sh", "zsh"})
POWERSHELL_WRAPPERS = frozenset(
    {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
)
COMMAND_WRAPPERS = frozenset({"builtin", "call", "command", "exec"})
SCRIPT_FILE_REASON = (
    "{executable} runs the script file {argument}, which the guard cannot "
    "inspect; run its commands directly"
)
ENV_BUILTIN_REASON = "{executable} cannot be validated; assign with NAME=VALUE instead"
SHELL_FILE_REASON = (
    "{executable} reads commands from a file or stdin the guard cannot inspect; "
    "run the commands directly or use {executable} -c '<commands>'"
)
MISSING_COMMAND_STRING_REASON = "{executable} {option} lacks a command string"
UNVALIDATED_EXECUTION_REASONS = {
    ".": SCRIPT_FILE_REASON,
    "source": SCRIPT_FILE_REASON,
    "readonly": "readonly changes shell assignment behavior the guard cannot validate; "
    "avoid readonly declarations",
    "start": "start launches a detached process the guard cannot inspect; run the program directly",
    "setenv": ENV_BUILTIN_REASON,
    "unsetenv": ENV_BUILTIN_REASON,
}
VARIABLE_COMMANDS = frozenset(
    {"declare", "export", "local", "readonly", "set", "typeset", "unset"}
)
XARGS_COMMANDS = frozenset({"xargs", "xargs.exe"})
XARGS_OPTIONS_WITH_VALUES = frozenset(
    {
        "-I",
        "-J",
        "-L",
        "-n",
        "-P",
        "-R",
        "-S",
        "-s",
        "-E",
        "-d",
        "-a",
        "-l",
        "--replace",
        "--max-args",
        "--max-lines",
        "--max-procs",
        "--max-chars",
        "--delimiter",
        "--eof",
        "--arg-file",
        "--process-slot-var",
    }
)
DESTRUCTIVE_SHELL_COMMANDS = frozenset(
    {
        "del",
        "erase",
        "mi",
        "move",
        "move-item",
        "mv",
        "rd",
        "remove-item",
        "ri",
        "rm",
        "rmdir",
        "rsync",
        "shred",
        "trash",
        "unlink",
    }
)
SHELL_WRITE_COMMANDS = DESTRUCTIVE_SHELL_COMMANDS | frozenset(
    {
        "cp",
        "install",
        "ln",
        "mkdir",
        "tee",
        "touch",
        "truncate",
    }
)
IN_PLACE_EDITORS = frozenset({"perl", "sed"})
SED_SAFE_OPTIONS = frozenset(
    {
        "--debug",
        "--help",
        "--null-data",
        "--posix",
        "--quiet",
        "--regexp-extended",
        "--sandbox",
        "--separate",
        "--silent",
        "--unbuffered",
        "--version",
        "-E",
        "-n",
        "-r",
        "-s",
        "-u",
    }
)
FIND_EXECUTION_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
SHELL_CONTROL_WORDS = frozenset(
    {
        "!",
        "case",
        "coproc",
        "do",
        "done",
        "elif",
        "else",
        "esac",
        "fi",
        "for",
        "function",
        "if",
        "in",
        "select",
        "then",
        "time",
        "until",
        "while",
        "{",
        "}",
    }
)


def collect(
    node,
    paths,
    working_directories,
    commands,
    patch_payloads,
    path_keys=PATH_KEYS,
    inherited_working_directories=(),
):
    if isinstance(node, dict):
        local_working_directories = []
        for key, value in node.items():
            if key.lower() not in WORKING_DIRECTORY_KEYS:
                continue
            # Cursor sends "cwd": "" when it has no directory; treat that as absent.
            if isinstance(value, str):
                if value:
                    local_working_directories.append(value)
            elif isinstance(value, list):
                strings = [item for item in value if isinstance(item, str)]
                if len(strings) != len(value):
                    raise ValueError("working directories cannot be validated")
                local_working_directories.extend(item for item in strings if item)
        if len(local_working_directories) > 1:
            raise ValueError("working directory is ambiguous")
        working_directories.extend(local_working_directories)
        context = tuple(local_working_directories) or inherited_working_directories
        for key, value in node.items():
            lowered = key.lower()
            if isinstance(value, str):
                if lowered in path_keys:
                    paths.append((value, context))
                elif lowered in COMMAND_KEYS:
                    commands.append((value, context))
                elif lowered in PATCH_KEYS:
                    patch_payloads.append((value, context))
            elif isinstance(value, list):
                strings = [item for item in value if isinstance(item, str)]
                if strings and lowered in path_keys:
                    paths.extend((item, context) for item in strings)
                elif lowered in COMMAND_KEYS:
                    if not strings or len(strings) != len(value):
                        raise ValueError("command argv cannot be validated")
                    commands.append((shlex.join(strings), context))
                elif strings and lowered in PATCH_KEYS:
                    patch_payloads.extend((item, context) for item in strings)
                collect(
                    value,
                    paths,
                    working_directories,
                    commands,
                    patch_payloads,
                    path_keys,
                    context,
                )
            else:
                collect(
                    value,
                    paths,
                    working_directories,
                    commands,
                    patch_payloads,
                    path_keys,
                    context,
                )
    elif isinstance(node, list):
        for value in node:
            collect(
                value,
                paths,
                working_directories,
                commands,
                patch_payloads,
                path_keys,
                inherited_working_directories,
            )


def is_link_like(path):
    """A symlink, or on Windows any name-surrogate reparse point such as a junction.

    Path.is_symlink() is false for a junction, which still redirects the path.
    """
    try:
        status = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(status.st_mode) or bool(
        getattr(status, "st_reparse_tag", 0) & 0x20000000  # IO_REPARSE_TAG name surrogate
    )


def normalize_posix(path):
    text = path.replace("\\", "/").strip()
    if not text:
        return "/"
    parts = []
    for part in PurePosixPath(text).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def tool_tokens(tool):
    return {token.casefold() for token in TOOL_TOKEN_PATTERN.findall(tool)}


def is_read_tool(tool):
    tokens = tool_tokens(tool)
    return bool(tokens & READ_VERBS) and not tokens & WRITE_VERBS


def is_patch_tool(tool):
    return "patch" in tool_tokens(tool)


def has_patch_headers(payload):
    return bool(
        PATCH_PATH_PATTERN.search(payload)
        or UNIFIED_DIFF_PATH_PATTERN.search(payload)
        or GIT_DIFF_PATH_PATTERN.search(payload)
        or GIT_RENAME_PATH_PATTERN.search(payload)
    )


def is_direct_write_tool(tool, has_file_targets=False):
    if has_file_targets:
        return not is_read_tool(tool)
    tokens = tool_tokens(tool)
    if tokens & DIRECT_FILE_WRITE_VERBS:
        return (
            len(tokens) == 1
            or bool(tokens & FILE_TARGET_TOKENS)
            or has_file_targets
        )
    if tokens == {"create"}:
        return True
    return bool(
        (tokens & AMBIGUOUS_WRITE_VERBS)
        and ((tokens & FILE_TARGET_TOKENS) or has_file_targets)
    )


@lru_cache(maxsize=None)
def repository_root():
    candidate = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=candidate,
        encoding="utf-8", errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        state = candidate / ".project" / "STATE.md"
        if (
            candidate.is_dir()
            and not is_link_like(candidate)
            and os.path.lexists(state)
        ):
            return candidate
        raise ValueError("repository root cannot be resolved")
    return Path(result.stdout.strip()).resolve()


def project_status(repo):
    script_root = Path(__file__).resolve().parent
    launcher = script_root / "status_runtime.py"
    if not launcher.is_file():
        raise ValueError("project status runtime is unavailable")
    result = subprocess.run(
        [sys.executable, "-B", str(launcher), "--repo", str(repo)],
        cwd=repo,
        encoding="utf-8", errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("project status failed")
    payload = json.loads(result.stdout)
    if not valid_status_payload(payload, repo):
        raise ValueError("project status returned an invalid payload")
    return payload


def valid_status_payload(payload, repo):
    if not isinstance(payload, dict) or payload.get("schema") != "gsd-path/status/v1":
        return False
    state = payload.get("state")
    route = payload.get("route")
    status_path = payload.get("path")
    next_skill = payload.get("next_skill")
    if (
        payload.get("advance") is not False
        or not isinstance(state, dict)
        or not valid_status_state(state)
        or not isinstance(route, dict)
        or route.get("action") not in STATUS_ACTIONS
        or not isinstance(route.get("reason"), str)
        or not route["reason"]
        or not isinstance(status_path, str)
        or not Path(status_path).is_absolute()
        or Path(status_path).resolve(strict=False)
        != (repo / ".project" / "STATE.md").resolve(strict=False)
    ):
        return False
    action = route["action"]
    if action == "run-phase":
        phase = route.get("phase")
        return (
            isinstance(phase, str)
            and phase in STATUS_TRANSITIONS[state["phase"]]
            and state["branch"] is not None
            and next_skill == f"gsd-path-{phase}"
        )
    if "phase" in route:
        return False
    if action == "bind-initial":
        return (
            state["branch"] is None
            and isinstance(route.get("branch"), str)
            and valid_status_branch(route["branch"]) is not None
            and next_skill == "gsd-path"
        )
    if state["branch"] is None:
        return False
    if action == "validate-integrated" and not (
        state["phase"] == "shipped" and state["status"] == "done"
    ):
        return False
    if action == "wait" and not (
        state["phase"] == "plan" and state["status"] == "done"
    ):
        return False
    if action == "resume-undo":
        expected = "gsd-path-undo"
    elif action == "wait":
        expected = None
    else:
        expected = "gsd-path"
    return next_skill == expected


def valid_status_state(state):
    if set(state) != STATUS_STATE_FIELDS:
        return False
    milestone = state["milestone"]
    branch = state["branch"]
    archive = state["archive"]
    integration_default = state["integration_default"]
    integration = state["integration"]
    integration_source = state["integration_source"]
    archive_match = (
        STATUS_ARCHIVE.fullmatch(archive or "")
        if isinstance(archive, (str, type(None)))
        else None
    )
    if (
        state["pipeline"] != "gsd-path/v2"
        or not isinstance(state["project"], str)
        or STATUS_SLUG.fullmatch(state["project"]) is None
        or not (
            milestone is None
            or isinstance(milestone, str)
            and STATUS_SLUG.fullmatch(milestone) is not None
        )
        or not isinstance(state["phase"], str)
        or state["phase"] not in STATUS_PHASES
        or not isinstance(state["status"], str)
        or state["status"] not in STATUS_VALUES
        or integration_default not in STATUS_INTEGRATION_MODES
        or integration not in STATUS_INTEGRATION_MODES
        or integration_source not in STATUS_INTEGRATION_SOURCES
        or (
            integration_source == "default"
            and integration != integration_default
        )
        or not (
            branch is None
            or isinstance(branch, str)
            and valid_status_branch(branch) is not None
        )
        or not (archive is None or archive_match is not None)
    ):
        return False
    if state["phase"] == "shipped" and (
        state["status"] != "done" or archive is None
    ):
        return False
    if archive is not None and state["phase"] not in {"build", "ship", "shipped"}:
        return False
    if state["phase"] in {"ship", "shipped"} and branch is None:
        return False
    if archive_match is not None:
        branch_match = valid_status_branch(branch)
        return (
            milestone == archive_match.group(2)
            and branch_match is not None
            and int(branch_match.group(1)) == int(archive_match.group(1))
        )
    return True


def valid_status_branch(value):
    match = STATUS_BRANCH.fullmatch(value) if isinstance(value, str) else None
    return match if match is not None and int(match.group(1)) >= 1 else None


def target_paths(path, working_directories, repo):
    repo = repo.resolve()
    candidate = Path(native_path_text(path))
    if not candidate.is_absolute():
        base = Path(working_directories[0]) if working_directories else repo
        if not base.is_absolute():
            base = repo / base
        candidate = base / candidate
    return Path(os.path.abspath(candidate)), resolve_lenient(candidate)


def resolve_lenient(path):
    """Path.resolve(strict=False) that still follows links on Windows.

    Python 3.9 raises OSError on Windows for names it cannot open (rep*) and
    for some links to missing files; the archive checks must not skip those
    (a symlinked archive path would be allowed), so fall back to
    os.path.realpath, which resolves what it can and keeps the remainder.
    """
    try:
        return path.resolve(strict=False)
    except OSError:
        if os.name != "nt":
            raise
        return Path(os.path.realpath(path))


@lru_cache(maxsize=None)
def repository_control_roots(repo):
    roots = [(repo / ".git").resolve(strict=False)]
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=repo,
        encoding="utf-8", errors="replace",
        capture_output=True,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        common = Path(result.stdout.strip())
        if not common.is_absolute():
            common = repo / common
        roots.append(common.resolve(strict=False))
    return tuple(roots)


def _same_existing_path(left, right):
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def _within_existing_root(candidate, root):
    return any(
        _same_existing_path(ancestor, root)
        for ancestor in (candidate, *candidate.parents)
    )


def _canonical_control_alias(candidate, repo, control_roots):
    roots = (*control_roots, repo / ".project", repo / ".gsd-path")
    suffix = []
    current = candidate
    while current != current.parent:
        for root in roots:
            if _same_existing_path(current, root):
                return root.joinpath(*reversed(suffix))
        suffix.append(current.name)
        current = current.parent
    return candidate


def path_kind(candidate, repo, control_roots=()):
    if any(
        candidate == root
        or root in candidate.parents
        or _within_existing_root(candidate, root)
        for root in control_roots
    ):
        return "protected"
    if candidate != repo and repo not in candidate.parents:
        return "external"
    relative = candidate.relative_to(repo)
    parts = relative.parts
    if parts in {
        (".project",),
        (".project", "STATE.md"),
        (".project", "next"),
        (".project", "next", "STATE.md"),
    }:
        return "protected"
    protected_paths = (
        repo / ".project",
        repo / ".project" / "STATE.md",
        repo / ".project" / "next",
        repo / ".project" / "next" / "STATE.md",
    )
    if any(_same_existing_path(candidate, path) for path in protected_paths):
        return "protected"
    managed_root = repo / ".gsd-path"
    if (parts and parts[0] == ".gsd-path") or _within_existing_root(
        candidate, managed_root
    ):
        return "protected"
    if parts and parts[0] == ".project":
        return "artifact"
    return "product"


def member_target_kind(candidate, repo):
    """'product' when the path lies in a verified member of this coordinator.

    A member follows its coordinator's phase. A stale member of this
    coordinator raises MembersError, so the caller denies the write.
    """
    directory = candidate if candidate.is_dir() else candidate.parent
    while not directory.is_dir() and directory != directory.parent:
        directory = directory.parent
    found = subprocess.run(
        ["git", "-C", str(directory), "rev-parse", "--path-format=absolute",
         "--show-toplevel", "--git-common-dir"],
        encoding="utf-8", errors="replace", capture_output=True, check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    lines = found.stdout.splitlines()
    if found.returncode != 0:
        if found.stderr.strip().startswith("fatal: not a git repository"):
            return None
        raise RuntimeError(found.stderr.strip() or "Git inspection failed")
    if len(lines) != 2:
        raise RuntimeError("Git inspection returned an unexpected result")
    toplevel, common = Path(lines[0]), Path(lines[1])
    if not os.path.lexists(common / "gsd-path" / "member.json"):
        return None
    import members  # the guard's runtime directory; only paths in a member need it
    coordinator = members.marker_coordinator(toplevel)
    if coordinator is None:
        return None
    if coordinator.resolve() != repo.resolve():
        for member in members.read_members(repo):
            try:
                listed_common = members._common_dir(Path(member["checkout"]))
            except (members.MembersError, OSError):
                continue
            if listed_common == common.resolve():
                raise members.MembersError(
                    "member marker names an old coordinator; "
                    "run members.py repair --repo <coordinator>"
                )
        return None
    members.member_role(toplevel)
    return "product"


def target_kind(path, working_directories, repo, control_roots=None):
    lexical, resolved = target_paths(path, working_directories, repo)
    repo = repo.resolve()
    if control_roots is None:
        control_roots = repository_control_roots(repo)
    aliases = (
        _canonical_control_alias(lexical, repo, control_roots),
        _canonical_control_alias(resolved, repo, control_roots),
    )
    resolved_kind = path_kind(resolved, repo, control_roots)
    kinds = {resolved_kind} | {
        path_kind(candidate, repo, control_roots)
        for candidate in (lexical, *aliases)
    }
    if resolved_kind == "external" and "protected" not in kinds:
        try:
            member_kind = member_target_kind(resolved, repo)
        except Exception as error:
            deny(
                f"member write refused: {error}; "
                "run members.py repair --repo <coordinator>"
            )
        if member_kind:
            kinds.add(member_kind)
    for kind in ("protected", "product", "artifact", "external"):
        if kind in kinds:
            return kind
    return "external"


def pipeline_target_kinds(targets):
    """Classify (path, working_directories) pairs; None when no pipeline is owned."""
    repo = repository_root()
    state = repo / ".project" / "STATE.md"
    if not os.path.lexists(state):
        return None
    control_roots = repository_control_roots(repo)
    return repo, state, [
        (path, target_kind(path, directories, repo, control_roots))
        for path, directories in targets
    ]


def closed_target_reason(targets):
    for path, working_directories in targets:
        for target in dict.fromkeys(target_paths(path, working_directories, repository_root())):
            directory = target if target.is_dir() and not is_link_like(target) else target.parent
            while not directory.exists() and directory != directory.parent:
                directory = directory.parent
            root = subprocess.run(
                ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
                capture_output=True, encoding="utf-8", errors="replace",
            )
            if root.returncode == 0:
                reason = closed_milestone_reason(Path(root.stdout.strip()))
                if reason:
                    return reason
    return None


def pipeline_product_phase_reason(classified):
    """Why product writes are denied outside the routed build phase, or None when allowed."""
    if classified is None:
        return None
    repo, state, kinds = classified
    for path, kind in kinds:
        if kind == "protected":
            return f"{CONTROL_FILE_REASON} {path}"
    kind_values = [kind for _, kind in kinds]
    if all(kind == "external" for kind in kind_values):
        return None
    if not any(kind == "product" for kind in kind_values):
        return None
    try:
        status = project_status(repo)
    except (OSError, ValueError, json.JSONDecodeError):
        return REENTRY_FAILURE_REASON
    route = status.get("route")
    state_data = status.get("state") if isinstance(status.get("state"), dict) else {}
    completion = status.get("completion")
    if (state_data.get("phase") == "shipped"
            and isinstance(completion, dict) and completion.get("status") == "verified"):
        return None
    routed_build = (
        state_data.get("phase") == "build"
        and isinstance(route, dict)
        and route.get("action") == "run-phase"
        and route.get("phase") == "build"
    )
    if routed_build:
        return None
    if all(kind in {"external", "artifact"} for kind in kind_values):
        return None
    phase = state_data.get("phase", "unknown")
    if isinstance(route, dict) and route.get("action") != "run-phase":
        next_step = f"{route.get('action', 'route')}: {route.get('reason', 'no reason')}"
    else:
        next_step = status.get("next_skill") or "gsd-path"
    return (
        f"GSD Path is {phase}; direct product-file changes require the routed "
        f"build phase. Review {status.get('path', state)}; next: {next_step}"
    )


def enforce_pipeline_reentry(paths, working_directories):
    reason = closed_target_reason((path, working_directories) for path in paths)
    if reason:
        deny(reason)
    reason = pipeline_product_phase_reason(
        pipeline_target_kinds((path, working_directories) for path in paths)
    )
    if reason:
        deny(reason)


def in_archive(path):
    # Casefold: APFS and Windows resolve `.Project/Archive` to the archive.
    normalized = normalize_posix(path).casefold()
    marker = "/" + ARCHIVE_MARKER
    if marker not in normalized:
        return False
    idx = normalized.index(marker)
    suffix = normalized[idx + len(marker):]
    return suffix == "" or suffix.startswith("/")


def component_can_match(pattern, target):
    match = re.search(r"\{([^{}]+)\}", pattern)
    if match is not None:
        return any(
            component_can_match(
                pattern[: match.start()] + option + pattern[match.end() :], target
            )
            for option in match.group(1).split(",")
        )
    return fnmatchcase(target, pattern)


def expansion_can_match_archive(path):
    components = [
        component.casefold()
        for component in PurePosixPath(normalize_posix(path)).parts
        if component != "/"
    ]
    return any(
        component_can_match(components[index], ".project")
        and component_can_match(components[index + 1], "archive")
        for index in range(len(components) - 1)
    )


# Git Bash (Claude Code's shell on Windows) names drive C: as /c or /cygdrive/c.
MSYS_DRIVE_PATH = re.compile(r"^/(?:cygdrive/)?([A-Za-z])(?=/|$)")


def native_path_text(value):
    """On Windows, the drive path that a Git Bash path such as /c/repo names.

    Python reads /c/repo as a folder named c at the root of the current drive,
    which would hide an archive from the containment checks.
    """
    if os.name != "nt":
        return value
    text = value.replace("\\", "/")
    match = MSYS_DRIVE_PATH.match(text)
    if match is None:
        return value
    return f"{match.group(1).upper()}:{text[match.end():] or '/'}"


def path_values(value):
    values = [value]
    if value.startswith("-") and "=" in value:
        values.append(value.split("=", 1)[1])
    for candidate in values:
        yield candidate
        # Deny when either reading of an ambiguous Windows path reaches an archive.
        native = native_path_text(candidate)
        if native != candidate:
            yield native


def is_absolute_path(path):
    normalized = path.replace("\\", "/")
    return normalized.startswith("/") or bool(re.match(r"^[A-Za-z]:/", normalized))


def contains_existing_archive(path, working_directories):
    try:
        target = resolve_lenient(Path(path))
    except (OSError, RuntimeError):
        return False
    search_paths = [target, Path.cwd(), *(Path(value) for value in working_directories)]
    for search_path in search_paths:
        if os.name != "nt" and re.match(r"^[A-Za-z]:[/\\]", str(search_path)):
            continue
        try:
            resolved = resolve_lenient(search_path)
        except (OSError, RuntimeError):
            continue
        for parent in (resolved, *resolved.parents):
            archive = parent / ".project" / "archive"
            if not archive.is_dir():
                continue
            try:
                archive = archive.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if target == archive or target in archive.parents:
                return True
    return False


def path_in_archive(path, working_directories=(), ancestors=True):
    """True when path is inside an existing archive, or (ancestors=True) contains one."""
    for value in path_values(path):
        if in_archive(value) or expansion_can_match_archive(value):
            return True
        bases = [""] if is_absolute_path(value) else list(working_directories) or [""]
        for working_directory in bases:
            combined = (
                value
                if is_absolute_path(value) or not working_directory
                else f"{working_directory}/{value}"
            )
            if in_archive(combined) or expansion_can_match_archive(combined):
                return True
            if os.name != "nt" and re.match(r"^[A-Za-z]:[/\\]", combined):
                continue
            try:
                resolved = resolve_lenient(Path(combined))
            except (OSError, RuntimeError):
                continue
            if in_archive(resolved.as_posix()) or (
                ancestors and contains_existing_archive(resolved, working_directories)
            ):
                return True
    return False


def working_directory_in_archive(path):
    """A working directory is archive context only when it is inside an archive.

    The repository root merely contains .project/archive/ once a milestone has
    shipped; treating it as archive context would deny every shell command in
    the project. Ancestor containment stays with path_in_archive for operands,
    so deleting the archive's parent is still refused.
    """
    for value in path_values(path):
        if in_archive(value) or expansion_can_match_archive(value):
            return True
        if os.name != "nt" and re.match(r"^[A-Za-z]:[/\\]", value):
            continue
        try:
            resolved = resolve_lenient(Path(value))
        except (OSError, RuntimeError):
            continue
        if in_archive(resolved.as_posix()):
            return True
    return False


def is_redirection(token):
    return bool(token) and set(token) <= {"<", ">"}


def directory_change_target(arguments):
    operands = []
    for index, argument in enumerate(arguments):
        if is_redirection(argument):
            break
        if (
            argument.isdigit()
            and index + 1 < len(arguments)
            and is_redirection(arguments[index + 1])
        ):
            break
        if (
            argument != "--"
            and not argument.startswith("-")
            and argument.casefold() != "/d"
        ):
            operands.append(argument)
    if not operands:
        raise ValueError("cd without a literal directory cannot be tracked by the guard")
    if operands[-1] == "-":
        raise ValueError(
            "cd - returns to a directory the guard cannot track; cd to a literal path"
        )
    return operands[-1]


def segment_directories(tokens, working_directories):
    """Yield each command segment with the working directories in effect for it."""
    current_directories = list(working_directories)
    for segment in command_segments(tokens):
        yield segment, current_directories
        invocation = command_invocation(segment)
        if invocation is None:
            continue
        command, arguments = invocation
        if command == "popd":
            raise ValueError(
                "popd returns to a directory the guard cannot track; cd to a literal path"
            )
        if command not in DIRECTORY_CHANGE_COMMANDS:
            continue
        target = directory_change_target(arguments)
        if SHELL_PARAMETER_SYNTAX.search(target):
            raise ValueError(
                f"cd target {target} cannot be resolved by the guard; "
                "run that command first and cd to the literal result"
            )
        if is_absolute_path(target):
            current_directories = [target]
        else:
            bases = current_directories or ["."]
            current_directories = [f"{base}/{target}" for base in bases]


def command_can_destroy_files(invocation):
    if invocation is None:
        return False
    executable, arguments = invocation
    executable = executable.removesuffix(".exe")
    return executable in DESTRUCTIVE_SHELL_COMMANDS or (
        executable == "find" and "-delete" in arguments
    )


def literal_path(operand):
    if len(operand) >= 2 and operand[0] in "\"'" and operand[-1] == operand[0]:
        operand = operand[1:-1]
    pattern = r"[A-Za-z0-9._/-]+"
    if os.name == "nt":
        pattern = r"(?:[A-Za-z]:(?=[/\\]))?[A-Za-z0-9._/\\-]+"
    return operand if re.fullmatch(pattern, operand) is not None else None


def literal_destructive_operand(operand):
    literal = literal_path(operand)
    if literal is None:
        raise ValueError(
            f"destructive operand {operand} cannot be validated; pass a literal path"
        )
    return literal


def segment_references_archive(segment, directories, assignments=None):
    invocation = command_invocation(segment)
    ancestors = command_can_destroy_files(invocation)
    operands = [expand_environment_parameters(token, assignments) for token in segment]
    if ancestors:
        resolved = command_invocation(operands)
        operands = [literal_destructive_operand(operand) for operand in resolved[1]]
    if any(path_in_archive(operand, directories, ancestors) for operand in operands):
        return True
    return unresolved_archive_expansion(" ".join(segment), assignments)


def copy_destinations(arguments, directories, assignments=None):
    operands, destination, no_target_directory = [], None, False
    arguments = iter(arguments)
    command_arguments = []
    for argument in arguments:
        if is_redirection(argument) or (
            ">" in argument and set(argument) <= SHELL_WRITE_REDIRECTION_CHARS
        ):
            if command_arguments and command_arguments[-1].isdigit():
                raise ValueError("cp numeric operand before redirection is ambiguous")
            if next(arguments, None) is None:
                raise ValueError("cp redirection lacks a target")
        else:
            command_arguments.append(argument)
    command_arguments = [expand_environment_parameters(argument, assignments) for argument in command_arguments]
    if any(SHELL_PARAMETER_SYNTAX.search(argument) or CMD_PARAMETER_SYNTAX.search(argument) for argument in command_arguments):
        raise ValueError("cp operand cannot be resolved by the guard; pass a literal path")
    arguments = iter(command_arguments)
    for argument in arguments:
        if argument == "--":
            operands.extend(arguments)
            break
        if argument in {"-t", "--target-directory", "-S", "--suffix"}:
            value = next(arguments, None)
            if value is None:
                raise ValueError(f"cp option {argument} lacks a value")
            if argument in {"-t", "--target-directory"}:
                destination = value
        elif argument.startswith("--target-directory="):
            destination = argument.split("=", 1)[1]
        elif argument.startswith("-t") and not argument.startswith("--"):
            destination = argument[2:]
        elif argument in {"-T", "--no-target-directory"}:
            no_target_directory = True
        elif not argument.startswith("-"):
            operands.append(argument)
    if destination is None:
        if len(operands) < 2:
            raise ValueError("cp source and destination cannot be resolved")
        destination = operands.pop()
    yield destination
    _, target = target_paths(destination, directories, repository_root())
    for source in operands:
        output = Path(destination)
        if not no_target_directory and target.is_dir():
            output /= os.path.basename(source.rstrip("/"))
        outputs = [output]
        if source.endswith("/") and output != Path(destination):
            outputs.append(Path(destination))
        yield from map(str, outputs)
        lexical, source_path = target_paths(source, directories, repository_root())
        if source_path.is_dir():
            # ponytail: reject ambiguous directory links instead of emulating cp flags.
            if is_link_like(lexical):
                raise ValueError("cp directory source is a symlink; pass a literal directory")

            def unreadable(error):
                raise ValueError(f"cp source tree cannot be inspected: {error}")

            for root, folders, files in os.walk(source_path, onerror=unreadable):
                for name in folders + files:
                    entry = Path(root) / name
                    if is_link_like(entry) and entry.is_dir():
                        raise ValueError("cp source contains a directory symlink; copy it separately")
                    for output in outputs:
                        yield str(output / entry.relative_to(source_path))


def sed_delimited_end(script, index, delimiter):
    while index < len(script):
        if script[index] == "\\":
            index += 2
        elif script[index] == delimiter:
            return index + 1
        else:
            index += 1
    return None


def sed_address_end(script, index):
    if index >= len(script):
        return index
    if script[index].isdigit():
        while index < len(script) and script[index].isdigit():
            index += 1
        if index < len(script) and script[index] == "~":
            index += 1
            while index < len(script) and script[index].isdigit():
                index += 1
    elif script[index] == "$":
        index += 1
    elif script[index] == "/":
        end = sed_delimited_end(script, index + 1, "/")
        return len(script) if end is None else end
    elif script[index] == "\\" and index + 1 < len(script):
        end = sed_delimited_end(script, index + 2, script[index + 1])
        return len(script) if end is None else end
    return index


def sed_script_is_read_only(script):
    """Accept only sed scripts whose commands cannot write or execute."""
    # Sed blocks require recursively validating their nested command grammar;
    # reject them until that grammar is modeled explicitly.
    safe_commands = frozenset("aAcCdDgGhHiIlLnNpPqQrstTxv=:")
    index = 0
    while index < len(script):
        while index < len(script) and (script[index].isspace() or script[index] == ";"):
            index += 1
        if index >= len(script):
            break
        address_start = index
        index = sed_address_end(script, index)
        if index < len(script) and script[index] == ",":
            index = sed_address_end(script, index + 1)
        if index > address_start and index < len(script) and script[index] == "!":
            index += 1
        while index < len(script) and script[index].isspace():
            index += 1
        if index >= len(script):
            break
        command = script[index]
        index += 1
        if command in {"w", "W", "e"}:
            return False
        if command == "#":
            newline = script.find("\n", index)
            index = len(script) if newline < 0 else newline + 1
            continue
        if command == "s":
            if index >= len(script):
                return False
            delimiter = script[index]
            index = sed_delimited_end(script, index + 1, delimiter)
            if index is None:
                return False
            index = sed_delimited_end(script, index, delimiter)
            if index is None:
                return False
            end = index
            while end < len(script) and script[end] not in ";\n":
                end += 1
            if any(flag in "wWe" for flag in script[index:end]):
                return False
            index = end
            continue
        if command == "y":
            if index >= len(script):
                return False
            delimiter = script[index]
            index = sed_delimited_end(script, index + 1, delimiter)
            if index is None:
                return False
            index = sed_delimited_end(script, index, delimiter)
            if index is None:
                return False
            continue
        if command not in safe_commands:
            return False
        while index < len(script) and script[index] not in ";\n":
            index += 1
    return True


def sed_arguments(arguments):
    """Return (in_place, input_files, script_is_read_only) for sed arguments."""
    in_place = False
    scripts = []
    inputs = []
    script_seen = False
    scripts_are_literal = True
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        index += 1
        if argument == "--":
            positional = arguments[index:]
            if not script_seen and positional:
                scripts.append(positional[0])
                positional = positional[1:]
                script_seen = True
            inputs.extend(positional)
            break
        if argument in {"-e", "--expression"}:
            if index >= len(arguments):
                return in_place, inputs, False
            scripts.append(arguments[index])
            script_seen = True
            index += 1
            continue
        if argument == "-f" or argument == "--file":
            if index >= len(arguments):
                return in_place, inputs, False
            script_seen = True
            scripts_are_literal = False
            index += 1
            continue
        if argument.startswith("--expression="):
            scripts.append(argument.split("=", 1)[1])
            script_seen = True
            continue
        if argument.startswith("--file="):
            script_seen = True
            scripts_are_literal = False
            continue
        if argument == "--in-place" or argument.startswith("--in-place="):
            in_place = True
            continue
        if argument.startswith("--"):
            if argument not in SED_SAFE_OPTIONS:
                scripts_are_literal = False
            continue
        if argument.startswith("-") and argument != "-":
            options = argument[1:]
            cursor = 0
            while cursor < len(options):
                option = options[cursor]
                cursor += 1
                if option == "i":
                    in_place = True
                    break
                if option == "e":
                    if cursor < len(options):
                        scripts.append(options[cursor:])
                        script_seen = True
                    elif index < len(arguments):
                        scripts.append(arguments[index])
                        script_seen = True
                        index += 1
                    else:
                        return in_place, inputs, False
                    break
                if option not in "nErsu":
                    scripts_are_literal = False
            continue
        if not script_seen:
            scripts.append(argument)
            script_seen = True
        else:
            inputs.append(argument)
    if not scripts or not scripts_are_literal:
        return in_place, inputs, False
    return in_place, inputs, all(sed_script_is_read_only(script) for script in scripts)


def shell_write_targets(tokens, working_directories, assignments=None):
    """Yield (target, directories, variables) for every path a shell command may write."""
    for segment, directories, segment_assignments, _ in shell_segment_contexts(
        tokens, working_directories, assignments
    ):
        for index, token in enumerate(segment[:-1]):
            if ">" not in token or not set(token) <= SHELL_WRITE_REDIRECTION_CHARS:
                continue
            target = segment[index + 1]
            if token.endswith("&") and (target.isdigit() or target == "-"):
                continue
            yield target, directories, segment_assignments
        wrapped = wrapped_command_tokens(segment)
        if wrapped is not None:
            yield from shell_write_targets(wrapped, directories, segment_assignments)
            continue
        invocation = command_invocation(segment)
        if invocation is None:
            continue
        command, arguments = invocation
        command = command.removesuffix(".exe")
        if command == "sed":
            in_place, inputs, _ = sed_arguments(arguments)
            if in_place:
                for target in inputs:
                    yield target, directories, segment_assignments
            continue
        in_place = command in IN_PLACE_EDITORS and (
            has_short_option(arguments, "i")
            or any(argument.startswith("--in-place") for argument in arguments)
        )
        if command == "cp":
            for destination in copy_destinations(arguments, directories, segment_assignments):
                yield destination, directories, segment_assignments
            continue
        if command in SHELL_WRITE_COMMANDS or in_place:
            for argument in arguments:
                if argument and not argument.startswith("-"):
                    yield argument, directories, segment_assignments


def shell_write_needs_build_phase_gate(targets):
    """Phase-gate shell product writes only on bound milestone branches in-tree."""
    repo = repository_root()
    branch = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if branch.returncode or not STATUS_BRANCH.fullmatch(branch.stdout.strip()):
        return False
    for path, working_directories in targets:
        for target in dict.fromkeys(target_paths(path, working_directories, repo)):
            directory = (
                target
                if target.is_dir() and not is_link_like(target)
                else target.parent
            )
            while not directory.exists() and directory != directory.parent:
                directory = directory.parent
            root = subprocess.run(
                ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
            if root.returncode != 0 or Path(root.stdout.strip()) != repo:
                return False
    return True


def protected_shell_write_reason(tokens, working_directories):
    targets = []
    for target, directories, assignments in shell_write_targets(tokens, working_directories):
        expanded = expand_environment_parameters(target, assignments)
        if SHELL_PARAMETER_SYNTAX.search(expanded) or CMD_PARAMETER_SYNTAX.search(
            expanded
        ):
            raise ValueError(
                f"write target {target} cannot be resolved by the guard; "
                "pass a literal path"
            )
        if expanded and expanded not in {"/dev/null", "NUL"}:
            targets.append((expanded, directories))
    reason = closed_target_reason(targets)
    if reason:
        return reason
    classified = pipeline_target_kinds(targets) if targets else None
    if classified is None:
        return None
    for target, kind in classified[2]:
        if kind == "protected":
            return f"{PROTECTED_SHELL_WRITE_REASON} {target}"
    if shell_write_needs_build_phase_gate(targets):
        return pipeline_product_phase_reason(classified)
    return None


def environment_parameter_value(match, assignments):
    name = match.group(1) or match.group(2)
    if name.startswith(SUBSTITUTION_PLACEHOLDER):
        return match.group(0)  # command substitution output is never resolved
    if name in assignments:
        return assignments[name]
    return os.environ.get(name, match.group(0))


def expand_environment_parameters(command, assignments=None):
    values = assignments or {}

    def substitute(match):
        return environment_parameter_value(match, values)

    expanded = NAMED_SHELL_PARAMETER_SYNTAX.sub(substitute, command)
    return CMD_PARAMETER_SYNTAX.sub(substitute, expanded)


def shell_segment_flow(tokens):
    """Return whether each segment is conditional or runs in a subshell."""
    flows = []
    segment = []
    conditional = False
    subshell_depth = 0
    control_depth = 0
    separators = set("|;&()\n\r")
    for token in tokens:
        if token and set(token) <= separators:
            if segment:
                flows.append(
                    (conditional or control_depth > 0, subshell_depth > 0 or token in {"|", "&"})
                )
                segment = []
            if token == "(":
                subshell_depth += 1
                conditional = True
            elif token == ")":
                subshell_depth = max(0, subshell_depth - 1)
                conditional = False
            elif token in {"&&", "||", "|", "&"}:
                conditional = True
            else:
                conditional = False
            continue
        word = token.casefold()
        if not segment and word in SHELL_CONTROL_WORDS:
            if word in {"if", "while", "until", "for", "select", "case", "coproc"}:
                control_depth += 1
            elif word in {"fi", "done", "esac"}:
                control_depth = max(0, control_depth - 1)
            if word in {"then", "else", "elif", "do", "in"}:
                conditional = True
            continue
        segment.append(token)
    if segment:
        flows.append((conditional or control_depth > 0, subshell_depth > 0))
    return flows


def shell_assignment_changes(segment, values):
    """Return variables changed by a persistent assignment or variable builtin."""
    index = 0
    prefix = []
    while index < len(segment) and SHELL_ASSIGNMENT_PATTERN.match(segment[index]):
        prefix.append(segment[index])
        index += 1
    executable = segment[index].casefold() if index < len(segment) else None
    updates = {}
    removes = set()
    if executable is None:
        assignments = prefix
    elif executable in {"export", "declare", "typeset"}:
        assignments = [*prefix, *segment[index + 1 :]]
    else:
        assignments = []
    for assignment in assignments:
        if SHELL_ASSIGNMENT_PATTERN.match(assignment):
            name, value = assignment.split("=", 1)
            updates[name] = expand_environment_parameters(value, {**values, **updates})
    if executable == "unset":
        removes = {
            name for name in segment[index + 1 :] if not name.startswith("-")
        }
    return updates, removes


def shell_assignment_contexts(tokens, initial=None, working_directories=None):
    """Return the persistent shell variables visible before each segment."""
    values = dict(initial or {})
    directories = list(working_directories or [os.getcwd()])
    if "PWD" not in values:
        values["PWD"] = (
            os.path.abspath(native_path_text(directories[0]))
            if len(directories) == 1 else "$PWD"
        )
    contexts = []
    segments = list(command_segments(tokens))
    flows = shell_segment_flow(tokens)
    if len(segments) != len(flows):
        raise ValueError("shell command segments cannot be aligned")
    for segment, (conditional, subshell) in zip(segments, flows):
        contexts.append(dict(values))
        updates, removes = shell_assignment_changes(segment, values)
        if subshell:
            continue
        for name in removes:
            if conditional:
                values[name] = f"${name}"
            else:
                # An unset variable expands to empty, never its inherited value.
                values[name] = ""
        for name, value in updates.items():
            values[name] = f"${name}" if conditional else value
        invocation = command_invocation(segment)
        if invocation is not None and invocation[0] in DIRECTORY_CHANGE_COMMANDS:
            target = directory_change_target(invocation[1])
            directories = (
                [target] if is_absolute_path(target)
                else [f"{directory}/{target}" for directory in directories]
            )
            values["OLDPWD"] = values.get("PWD", "$PWD")
            values["PWD"] = (
                os.path.abspath(native_path_text(directories[0]))
                if not conditional and len(directories) == 1 else "$PWD"
            )
            if conditional:
                values["OLDPWD"] = "$OLDPWD"
    return contexts, values


def shell_segment_contexts(tokens, working_directories, initial=None):
    """Yield each segment with its working directory and prior shell variables."""
    contexts, _ = shell_assignment_contexts(tokens, initial, working_directories)
    segments = list(segment_directories(tokens, working_directories))
    if len(segments) != len(contexts):
        raise ValueError("shell command segments cannot be aligned")
    for (segment, directories), assignments in zip(segments, contexts):
        prefix = {}
        for token in segment:
            if not SHELL_ASSIGNMENT_PATTERN.match(token):
                break
            name, value = token.split("=", 1)
            prefix[name] = expand_environment_parameters(value, assignments)
        yield segment, directories, assignments, prefix


def unresolved_archive_expansion(command, assignments=None):
    expanded = expand_environment_parameters(command, assignments)
    return ARCHIVE_REFERENCE.search(expanded) is not None


def substitution_end(command, start):
    depth, quote, index = 1, None, start
    while index < len(command):
        character = command[index]
        if quote:
            if character == "\\" and quote == '"':
                index += 2
                continue
            if character == quote:
                quote = None
        elif character == "\\":
            index += 2
            continue
        elif character in "'\"":
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError("command substitution $( is not closed")


def heredoc_requests(line):
    """Find literal here-document delimiters, excluding here-strings and quotes."""
    requests = []
    quote = None
    index = 0
    while index < len(line):
        character = line[index]
        if quote:
            if character == "\\" and quote == '"':
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character == "\\":
            index += 2
            continue
        if character == "#" and (
            index == 0
            or line[index - 1].isspace()
            or line[index - 1] in ";|&()<>"
        ):
            break
        if character in "'\"":
            quote = character
            index += 1
            continue
        if line.startswith("$(", index):
            index = substitution_end(line, index + 2) + 1
            continue
        if character == "`":
            end = index + 1
            while end < len(line) and line[end] != "`":
                end += 2 if line[end] == "\\" else 1
            index = min(end + 1, len(line))
            continue
        if line.startswith("<<<", index):
            index += 3
            continue
        if not line.startswith("<<", index):
            index += 1
            continue
        cursor = index + 2
        strip_tabs = cursor < len(line) and line[cursor] == "-"
        if strip_tabs:
            cursor += 1
        while cursor < len(line) and line[cursor] in " \t":
            cursor += 1
        delimiter = []
        delimiter_quote = None
        quoted = False
        while cursor < len(line):
            value = line[cursor]
            if delimiter_quote:
                if value == delimiter_quote:
                    delimiter_quote = None
                else:
                    delimiter.append(value)
                cursor += 1
                continue
            if value in "'\"":
                delimiter_quote = value
                quoted = True
                cursor += 1
                continue
            if value == "\\" and cursor + 1 < len(line):
                quoted = True
                delimiter.append(line[cursor + 1])
                cursor += 2
                continue
            if value.isspace() or value in ";|&()<>":
                break
            delimiter.append(value)
            cursor += 1
        if not delimiter:
            raise ValueError("here-document delimiter cannot be validated")
        requests.append(("".join(delimiter), strip_tabs, quoted))
        index = cursor
    return requests


def heredoc_modes(command):
    """Mark here-document bodies as data or shell-expanded input."""
    lines = command.splitlines(keepends=True)
    modes = ["shell"] * len(command)
    offsets = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    line_index = 0
    while line_index < len(lines):
        requests = heredoc_requests(lines[line_index].rstrip("\r\n"))
        line_index += 1
        for delimiter, strip_tabs, quoted in requests:
            found = False
            while line_index < len(lines):
                line = lines[line_index]
                content = line.rstrip("\r\n")
                if strip_tabs:
                    content = content.lstrip("\t")
                start = offsets[line_index]
                stop = start + len(line)
                mode = "literal" if quoted or content == delimiter else "heredoc"
                modes[start:stop] = [mode] * (stop - start)
                line_index += 1
                if content == delimiter:
                    found = True
                    break
            if not found:
                raise ValueError(f"here-document {delimiter} is not terminated")
    return modes


def split_command_substitutions(command):
    """Replace executable substitutions, leaving quoted text as shell data."""
    modes = heredoc_modes(command)
    outer, inner, index, quote = [], [], 0, None
    while index < len(command):
        mode = modes[index]
        character = command[index]
        if mode == "literal":
            outer.append(character)
            index += 1
            continue
        if mode == "heredoc":
            if character == "\\" and index + 1 < len(command) and command[index + 1] in "\\$`":
                outer.append(command[index : index + 2])
                index += 2
                continue
            if command.startswith("$(", index):
                end = substitution_end(command, index + 2)
                inner.append(command[index + 2 : end])
            elif character == "`":
                end = index + 1
                while end < len(command) and command[end] != "`":
                    end += 2 if command[end] == "\\" else 1
                if end >= len(command):
                    raise ValueError("backtick command substitution is not closed")
                inner.append(command[index + 1 : end])
            elif command.startswith("@(", index):
                raise ValueError(
                    "@( expansion cannot be validated; write the list as literal arguments"
                )
            else:
                outer.append(character)
                index += 1
                continue
            outer.append(f"${{{SUBSTITUTION_PLACEHOLDER}{len(inner) - 1}}}")
            index = end + 1
            continue
        if quote == "'":
            outer.append(character)
            if character == "'":
                quote = None
            index += 1
            continue
        if character == "\\":
            outer.append(command[index : index + 2])
            index += 2
            continue
        if quote is None and character == "'":
            quote = character
            outer.append(character)
            index += 1
            continue
        if character == '"':
            quote = None if quote == '"' else '"'
            outer.append(character)
            index += 1
            continue
        if command.startswith("$(", index):
            end = substitution_end(command, index + 2)
            inner.append(command[index + 2 : end])
        elif character == "`":
            end = index + 1
            while end < len(command) and command[end] != "`":
                end += 2 if command[end] == "\\" else 1
            if end >= len(command):
                raise ValueError("backtick command substitution is not closed")
            inner.append(command[index + 1 : end])
        elif command.startswith("@(", index):
            raise ValueError(
                "@( expansion cannot be validated; write the list as literal arguments"
            )
        else:
            outer.append(character)
            index += 1
            continue
        outer.append(f"${{{SUBSTITUTION_PLACEHOLDER}{len(inner) - 1}}}")
        index = end + 1
    return "".join(outer), inner


def describe_substitutions(text, substitutions):
    return SUBSTITUTION_PLACEHOLDER_SYNTAX.sub(
        lambda match: f"$({substitutions[int(match.group(1))]})", text
    )


def strip_heredoc_bodies(command):
    lines = command.split("\n")
    kept, index = [], 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        for delimiter, strip_tabs, _ in heredoc_requests(line):
            strip = "\t\r" if strip_tabs else "\r"
            while index < len(lines) and lines[index].strip(strip) != delimiter:
                index += 1
            if index >= len(lines):
                raise ValueError(f"here-document {delimiter} is not terminated")
            index += 1
    return "\n".join(kept)


def patch_paths(payload):
    for match in PATCH_PATH_PATTERN.finditer(payload):
        yield (match.group(1) or match.group(2)).strip()
    for match in UNIFIED_DIFF_PATH_PATTERN.finditer(payload):
        path = decode_patch_path(match.group(1), strip_prefix=True)
        if path != "/dev/null":
            yield path
    for match in GIT_DIFF_PATH_PATTERN.finditer(payload):
        for raw_path in match.groups():
            yield decode_patch_path(raw_path, strip_prefix=True)
    for match in GIT_RENAME_PATH_PATTERN.finditer(payload):
        yield decode_patch_path(match.group(1), strip_prefix=False)


def decode_patch_path(raw_path, strip_prefix):
    path = raw_path.strip()
    if path.startswith('"'):
        try:
            path = ast.literal_eval(path)
        except (SyntaxError, ValueError) as error:
            raise ValueError("quoted patch path cannot be validated") from error
        if not isinstance(path, str):
            raise ValueError("quoted patch path cannot be validated")
    elif '"' in path:
        raise ValueError("quoted patch path cannot be validated")
    if strip_prefix and path.startswith(("a/", "b/")):
        return path[2:]
    return path


def shell_tokens(command):
    command = strip_heredoc_bodies(LINE_CONTINUATION.sub(r"\1 ", command))
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|;&()<>\n\r")
    lexer.whitespace = " \t"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError as error:
        raise ValueError(
            f"shell command cannot be tokenized ({error}); balance the quotes "
            "or write the content with an editor tool"
        ) from None
    if not tokens:
        raise ValueError("shell command is empty")
    return tokens


def shell_parameter_quoting_uncertain(command):
    """Detect literal parameters whose quoting is lost by shell_tokens."""
    command = strip_heredoc_bodies(LINE_CONTINUATION.sub(r"\1 ", command))
    # These forms expand in cmd, but are literal directory text in POSIX shells.
    if CMD_PARAMETER_SYNTAX.search(command):
        return True
    quote = None
    index = 0
    while index < len(command):
        character = command[index]
        if quote == "'":
            if NAMED_SHELL_PARAMETER_SYNTAX.match(command, index):
                return True
            if character == "'":
                quote = None
        elif character == "\\":
            if NAMED_SHELL_PARAMETER_SYNTAX.match(command, index + 1):
                return True
            index += 1
        elif character in "'\"":
            if quote is None:
                quote = character
            elif character == quote:
                quote = None
        index += 1
    return False


def command_segments(tokens):
    """Yield simple commands with separators and leading control words removed."""
    segment = []
    for token in tokens:
        if token and set(token) <= set("|;&()\n\r"):
            if segment:
                yield segment
                segment = []
        elif segment or token.casefold() not in SHELL_CONTROL_WORDS:
            segment.append(token)
    if segment:
        yield segment


def validate_shell_assignment(assignment):
    name = assignment.partition("=")[0]
    folded = name.casefold()
    if folded in {"home", "xdg_config_home"} or folded.startswith("git_"):
        raise ValueError(
            f"{name} changes where Git reads its configuration, which the guard "
            "cannot validate; run git without it"
        )


def validate_variable_command(executable, arguments):
    for argument in arguments:
        if SHELL_ASSIGNMENT_PATTERN.match(argument):
            validate_shell_assignment(argument)
        elif executable == "set" or (executable == "unset" and argument.startswith("-")):
            continue
        elif argument.startswith(("-", "+")):
            raise ValueError(
                f"{executable} {argument}: variable options cannot be validated; "
                "assign with NAME=VALUE instead"
            )
        else:
            validate_shell_assignment(argument)


def first_argument(arguments):
    return arguments[0] if arguments else ""


def xargs_command(arguments):
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in XARGS_OPTIONS_WITH_VALUES:
            index += 2
        elif argument.startswith("-") and argument != "-":
            index += 1
        else:
            break
    return arguments[index:]


def require_read_command(wrapper, wrapped):
    if wrapped and not archive_command_is_read_only(" ".join(wrapped), wrapped, True):
        raise ValueError(
            f"{wrapper} runs {wrapped[0]} on operands the guard cannot check; "
            f"only read commands may follow {wrapper}, or pass the paths as literals"
        )


def command_invocation(segment):
    index = 0
    while index < len(segment) and SHELL_ASSIGNMENT_PATTERN.match(segment[index]):
        validate_shell_assignment(segment[index])
        index += 1
    if index >= len(segment):
        return None
    executable = segment[index].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if executable == "env":
        index += 1
        while index < len(segment):
            token = segment[index]
            if token == "--":
                index += 1
                break
            if SHELL_ASSIGNMENT_PATTERN.match(token):
                validate_shell_assignment(token)
                index += 1
                continue
            option = token.split("=", 1)[0]
            if option in ENV_OPTIONS_WITHOUT_VALUES:
                index += 1
                continue
            if option in ENV_OPTIONS_WITH_VALUES:
                if option in {"-C", "--chdir"}:
                    raise ValueError(
                        f"env {option} changes the working directory the guard "
                        "tracks; use cd with a literal path instead"
                    )
                index += 1
                if "=" not in token:
                    if index >= len(segment):
                        raise ValueError(f"env {option} lacks a value")
                    index += 1
                continue
            if token.startswith("-"):
                raise ValueError(
                    f"env {token} cannot be validated; use env NAME=VALUE <command>"
                )
            break
    if index >= len(segment):
        return None
    executable = segment[index].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    arguments = segment[index + 1 :]
    if SHELL_PARAMETER_SYNTAX.search(executable):
        raise ValueError(
            f"executable {segment[index]} cannot be resolved by the guard; "
            "name the program literally"
        )
    if executable in {"find", "find.exe"}:
        for position, argument in enumerate(arguments):
            if argument.casefold() in FIND_EXECUTION_ACTIONS:
                require_read_command(f"find {argument}", arguments[position + 1 :])
    if executable in XARGS_COMMANDS:
        require_read_command("xargs", xargs_command(arguments))
    if executable in VARIABLE_COMMANDS:
        validate_variable_command(executable, arguments)
    if executable in UNVALIDATED_EXECUTION_REASONS:
        raise ValueError(
            UNVALIDATED_EXECUTION_REASONS[executable].format(
                executable=segment[index], argument=first_argument(arguments)
            )
        )
    return executable, arguments


def git_command(segment, assignments=None):
    invocation = command_invocation(segment)
    if invocation is None:
        return None
    executable, arguments = invocation
    if executable not in {"git", "git.exe"}:
        return None
    resolved_arguments = []
    argument_index = 0
    while argument_index < len(arguments):
        argument = arguments[argument_index]
        attached_directory = argument.startswith("-C") and len(argument) > 2
        if argument == "-C" and argument_index + 1 < len(arguments):
            argument_index += 1
            directory = arguments[argument_index]
            expanded = expand_environment_parameters(directory, assignments)
            if SHELL_PARAMETER_SYNTAX.search(expanded) or CMD_PARAMETER_SYNTAX.search(expanded):
                raise ValueError(
                    f"git argument {directory} cannot be resolved by the guard; "
                    "pass a literal path"
                )
            if (
                (SHELL_PARAMETER_SYNTAX.search(directory) or CMD_PARAMETER_SYNTAX.search(directory))
                and any(character.isspace() or character in "*?[]" for character in expanded)
            ):
                raise ValueError(
                    f"git -C path {directory} may split or glob; pass a literal path"
                )
            resolved_arguments.extend((argument, expanded))
        elif attached_directory:
            directory = argument[2:]
            expanded = expand_environment_parameters(directory, assignments)
            if SHELL_PARAMETER_SYNTAX.search(expanded) or CMD_PARAMETER_SYNTAX.search(expanded):
                raise ValueError(
                    f"git argument {directory} cannot be resolved by the guard; "
                    "pass a literal path"
                )
            if (
                (SHELL_PARAMETER_SYNTAX.search(directory) or CMD_PARAMETER_SYNTAX.search(directory))
                and any(character.isspace() or character in "*?[]" for character in expanded)
            ):
                raise ValueError(
                    f"git -C path {directory} may split or glob; pass a literal path"
                )
            resolved_arguments.append(f"-C{expanded}")
        else:
            if SHELL_PARAMETER_SYNTAX.search(argument) or CMD_PARAMETER_SYNTAX.search(argument):
                raise ValueError(
                    f"git argument {argument} cannot be resolved by the guard; pass a "
                    "literal value (for commit messages use -F <file>)"
                )
            resolved_arguments.append(expand_environment_parameters(argument, assignments))
        argument_index += 1
    arguments = resolved_arguments
    index = 0
    git_options = []
    while index < len(arguments) and arguments[index].startswith("-"):
        token = arguments[index]
        if token[:2] in {"-c", "-C"} and len(token) > 2 and not token.startswith("--"):
            option, value = token[:2], token[2:]
        else:
            option = token.split("=", 1)[0]
            value = token.split("=", 1)[1] if "=" in token else None
        index += 1
        if option in GIT_GLOBAL_OPTIONS_WITH_VALUES and value is None:
            if index >= len(arguments):
                raise ValueError(f"git option {option} lacks a value")
            value = arguments[index]
            index += 1
        if option in {"-c", "--config-env"}:
            config_key = str(value).split("=", 1)[0].casefold()
            if config_key.startswith("alias."):
                raise ValueError(
                    f"git -c {config_key} defines an alias the guard cannot inspect; "
                    "run the underlying git command directly"
                )
            if config_key == "clean.requireforce":
                raise ValueError(
                    "git -c clean.requireForce disables the git clean safety check; "
                    "run git clean with explicit paths instead"
                )
        if option in GIT_GLOBAL_OPTIONS_WITH_VALUES:
            git_options.extend((option, str(value)))
    if index >= len(arguments):
        return None
    return arguments[index].casefold(), arguments[index + 1:], git_options


def wrapped_command_tokens(segment, expand_parameters=True):
    invocation = command_invocation(segment)
    if invocation is None:
        return None
    executable, arguments = invocation
    if executable == "eval":
        return shell_tokens(" ".join(arguments)) if arguments else None
    if executable in COMMAND_WRAPPERS:
        if executable == "command" and arguments[:1] in (["-v"], ["-V"]):
            return None
        if executable == "command" and arguments[:1] == ["-p"]:
            arguments = arguments[1:]
        if not arguments or arguments[0].startswith("-"):
            raise ValueError(
                f"{executable} {first_argument(arguments)}: only "
                f"`{executable} <program> [arguments]` can be validated"
            )
        return arguments
    if executable in POSIX_SHELL_WRAPPERS:
        for index, argument in enumerate(arguments):
            if (
                argument.startswith("-")
                and not argument.startswith("--")
                and "c" in argument[1:]
            ):
                if index + 1 >= len(arguments):
                    raise ValueError(
                        MISSING_COMMAND_STRING_REASON.format(
                            executable=executable, option=argument
                        )
                    )
                return shell_tokens(arguments[index + 1])
        raise ValueError(SHELL_FILE_REASON.format(executable=executable))
    if executable in POWERSHELL_WRAPPERS or executable in {"cmd", "cmd.exe"}:
        switches = {"-c", "-command", "/c", "/k"}
        for index, argument in enumerate(arguments):
            if argument.casefold() in switches:
                if index + 1 >= len(arguments):
                    raise ValueError(
                        MISSING_COMMAND_STRING_REASON.format(
                            executable=executable, option=argument
                        )
                    )
                payload = arguments[index + 1:]
                if executable in {"cmd", "cmd.exe"} and expand_parameters:
                    payload = [
                        expand_environment_parameters(argument)
                        for argument in payload
                    ]
                if len(payload) == 1:
                    return shell_tokens(payload[0])
                return payload
        raise ValueError(SHELL_FILE_REASON.format(executable=executable))
    return None


def has_short_option(arguments, option):
    return any(
        argument.startswith("-")
        and not argument.startswith("--")
        and option in argument[1:]
        for argument in arguments
    )


def git_alias(command, git_options, working_directories=None):
    aliases = set()
    for directory in working_directories or [os.getcwd()]:
        result = subprocess.run(
            ["git", *git_options, "config", "--get", f"alias.{command}"],
            cwd=directory,
            encoding="utf-8", errors="replace",
            capture_output=True,
            check=False,
        )
        if result.returncode == 1:
            aliases.add(None)
            continue
        if result.returncode != 0:
            raise ValueError("git alias configuration cannot be validated")
        alias = result.stdout.strip()
        if not alias or alias.startswith("!"):
            raise ValueError("git alias configuration cannot be validated")
        aliases.add(alias)
    if len(aliases) > 1:
        raise ValueError("git alias configuration is ambiguous across working directories")
    return next(iter(aliases), None)


def update_ref_deletes(arguments):
    operands = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in {"-m", "--message"}:
            index += 2
            continue
        if argument.startswith("--message=") or argument.startswith("-"):
            index += 1
            continue
        operands.append(argument)
        index += 1
    zero_value = len(operands) >= 2 and (
        operands[1] == "" or not operands[1].strip("0")
    )
    return (
        "-d" in arguments
        or "--delete" in arguments
        or any(argument.startswith("--stdin") for argument in arguments)
        or zero_value
    )


PATH_OWNED_REF_PREFIXES = (
    "gsd-path/",
    "gsd-path-task/",
    "gsd-path-verify/",
    "gsd-path-integrate/",
)


def _ownership_scalar(raw, path, key):
    value = raw.strip()
    if not value:
        return None
    if value.startswith('"'):
        quoted = re.match(r'^("(?:\\.|[^"\\])*\")(?:[ \t]+#.*)?$', value)
        if quoted is None:
            raise ValueError(f"{path.name} has an unreadable {key} value")
        try:
            value = json.loads(quoted.group(1))
        except json.JSONDecodeError:
            raise ValueError(f"{path.name} has an unreadable {key} value") from None
        if not isinstance(value, str):
            raise ValueError(f"{path.name} has a non-string {key} value")
        return value or None
    if value.startswith("'"):
        quoted = re.fullmatch(r"'((?:[^']|'')*)'(?:[ \t]+#.*)?", value)
        if quoted is None:
            raise ValueError(f"{path.name} has an unreadable {key} value")
        value = quoted.group(1).replace("''", "'")
        return value or None
    value = re.sub(r"[ \t]+#.*$", "", value).strip()
    if not value or value.casefold() in {"null", "~", "none"}:
        return None
    if value.casefold() in {"true", "false", "yes", "no", "on", "off"} or re.fullmatch(
        r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?", value
    ):
        raise ValueError(f"{path.name} has a non-string {key} value")
    if value[0] in "[{|>&*!" or ": " in value:
        raise ValueError(f"{path.name} has a non-scalar {key} value")
    return value


def ownership_frontmatter(path, keys, *, missing_ok=False):
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if missing_ok and not os.path.lexists(path):
            return {}
        raise ValueError(f"{path.name} ownership metadata cannot be read") from None
    except OSError as error:
        raise ValueError(f"{path.name} ownership metadata cannot be read: {error}") from None
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{path.name} ownership metadata is not a regular file")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"{path.name} ownership metadata cannot be read: {error}") from None
    if not lines or lines[0] != "---":
        raise ValueError(f"{path.name} has no readable frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise ValueError(f"{path.name} frontmatter is not terminated") from None

    values = {}
    pending_scalar = None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            if pending_scalar is not None:
                raise ValueError(
                    f"{path.name} has a non-scalar {pending_scalar} value"
                )
            continue
        pending_scalar = None
        match = re.fullmatch(r"(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?P<value>.*)", line)
        if match is None:
            raise ValueError(f"{path.name} has unreadable frontmatter")
        key = match.group("key")
        if key not in keys:
            continue
        if key in values:
            raise ValueError(f"{path.name} repeats ownership field {key}")
        value = _ownership_scalar(match.group("value"), path, key)
        values[key] = value
        if value is None and not match.group("value").strip():
            pending_scalar = key
    return values


def git_base_directories(git_options, working_directories):
    """Resolve target paths from each shell cwd after Git's ordered ``-C`` options."""
    result = []
    for directory in working_directories or [os.getcwd()]:
        current = Path(directory or os.getcwd()).resolve()
        index = 0
        while index < len(git_options):
            option = git_options[index]
            value = git_options[index + 1]
            if option == "-C":
                target = Path(value)
                current = (target if target.is_absolute() else current / target).resolve()
            index += 2
        result.append(current)
    return result


def _git_output(git_options, directory, *arguments):
    try:
        result = subprocess.run(
            ["git", *git_options, *arguments],
            cwd=directory,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        raise ValueError("git target repository cannot be resolved") from None
    if result.returncode != 0:
        raise ValueError("git target repository cannot be resolved")
    return result.stdout


def registered_worktree_records(output):
    records = {}
    for record in output.split("\0\0"):
        fields = [field for field in record.split("\0") if field]
        if not fields:
            continue
        paths = [field[len("worktree "):] for field in fields if field.startswith("worktree ")]
        branches = [field[len("branch "):] for field in fields if field.startswith("branch ")]
        if len(paths) != 1 or len(branches) > 1:
            raise ValueError("registered worktree metadata cannot be resolved")
        path = Path(paths[0])
        if not path.is_absolute():
            raise ValueError("registered worktree path is not absolute")
        resolved = path.resolve()
        if resolved in records:
            raise ValueError("registered worktree metadata is ambiguous")
        records[resolved] = branches[0] if branches else None
    if not records:
        raise ValueError("registered worktrees cannot be resolved")
    return records


def git_target_contexts(git_options, working_directories):
    contexts = []
    for directory, effective_directory in zip(
        working_directories or [os.getcwd()],
        git_base_directories(git_options, working_directories),
    ):
        root = Path(
            _git_output(git_options, directory, "rev-parse", "--show-toplevel").strip()
        ).resolve()
        records = registered_worktree_records(
            _git_output(
                git_options, directory, "worktree", "list", "--porcelain", "-z"
            )
        )
        if root not in records:
            raise ValueError("git target repository worktree cannot be resolved")
        common = Path(
            _git_output(git_options, directory, "rev-parse", "--git-common-dir").strip()
        )
        if not common.is_absolute():
            common = effective_directory / common
        contexts.append(
            {
                "root": root,
                "directory": directory,
                "effective_directory": effective_directory,
                "common": common.resolve(),
                "git_options": list(git_options),
                "worktrees": records,
            }
        )
    return contexts


def path_owned_records(roots):
    branches, worktrees = set(), set()
    for root in roots:
        project = root / ".project"
        if not os.path.lexists(project):
            continue
        if is_link_like(project) or not project.is_dir():
            raise ValueError(".project ownership metadata cannot be resolved")
        state = ownership_frontmatter(project / "STATE.md", {"branch"}, missing_ok=True)
        if state.get("branch"):
            branches.add(state["branch"])
        task_files = []

        def raise_walk_error(error):
            raise error

        try:
            for directory, child_directories, filenames in os.walk(
                project, onerror=raise_walk_error, followlinks=False
            ):
                if any(is_link_like(Path(directory) / name) for name in child_directories):
                    raise ValueError("task ownership metadata contains a linked directory")
                if Path(directory).name == "tasks":
                    task_files.extend(
                        Path(directory) / name
                        for name in filenames
                        if name.endswith(".md")
                    )
        except OSError as error:
            raise ValueError(f"task ownership metadata cannot be listed: {error}") from None
        task_files.sort()
        for task in task_files:
            fields = ownership_frontmatter(task, {"task_branch", "worktree"})
            if fields.get("task_branch"):
                branches.add(fields["task_branch"])
            recorded = fields.get("worktree")
            if recorded:
                path = Path(recorded).expanduser()
                if not path.is_absolute():
                    path = root / path
                try:
                    worktrees.add(path.resolve())
                except (OSError, RuntimeError):
                    raise ValueError("task worktree ownership path cannot be resolved") from None
    return branches, worktrees


def ref_is_path_owned(name, owned_branches):
    lowered = name.casefold()
    if lowered.startswith("refs/gsd-path/"):
        return True
    short = name
    if short.startswith("refs/heads/"):
        short = short[len("refs/heads/"):]
    elif short.startswith("heads/"):
        short = short[len("heads/"):]
    if short.casefold().startswith(PATH_OWNED_REF_PREFIXES):
        return True

    def canonical(value):
        if value.startswith("refs/heads/"):
            return value[len("refs/heads/"):]
        if value.startswith("heads/"):
            return value[len("heads/"):]
        return value

    return any(canonical(name) == canonical(branch) for branch in owned_branches)


def _literal_target(value):
    return bool(value) and not any(character in value for character in "*?[]{}~")


def _positional_targets(arguments, options_with_values=()):
    targets = []
    after_separator = False
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if after_separator:
            targets.append(argument)
        elif argument == "--":
            after_separator = True
        elif argument.startswith("-"):
            if argument in options_with_values:
                index += 1
        else:
            targets.append(argument)
        index += 1
    return targets


def _frontmatter_roots(contexts):
    return {
        path
        for context in contexts
        for path in context["worktrees"]
    }


def _git_refs(context):
    output = _git_output(
        context["git_options"],
        context["directory"],
        "for-each-ref",
        "--format=%(refname)",
    )
    return {line for line in output.splitlines() if line}


def _resolvable_branch_ref(target, refs):
    if target.startswith("refs/heads/"):
        candidate = target
    elif target.startswith("refs/"):
        return target if target in refs else None
    else:
        candidate = f"refs/heads/{target}"
    return candidate if candidate in refs else None


def _symbolic_ref_target(context, target):
    try:
        result = subprocess.run(
            ["git", *context["git_options"], "symbolic-ref", "--quiet", target],
            cwd=context["directory"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        raise ValueError("git ref target cannot be resolved") from None
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise ValueError("git ref target cannot be resolved")
    return result.stdout.strip()


def _resolvable_update_ref(target, refs, context, no_deref):
    candidate = target
    if target not in refs and not target.startswith("refs/"):
        short_candidate = f"refs/heads/{target}"
        if short_candidate in refs:
            candidate = short_candidate
    symbolic = _symbolic_ref_target(context, candidate)
    exists = candidate in refs or symbolic is not None
    if not exists:
        return None
    if no_deref:
        if not candidate.startswith("refs/"):
            return None
        return candidate
    resolved = symbolic or candidate
    return resolved if resolved in refs else None


def _workspace_roots(contexts):
    roots = [(Path.home() / ".gsd-path").resolve()]
    configured = os.environ.get("GSD_PATH_WORKTREE_ROOT")
    if configured:
        configured_root = Path(configured).expanduser()
        if not configured_root.is_absolute():
            raise ValueError("GSD_PATH_WORKTREE_ROOT must be absolute")
        roots.append(configured_root.resolve())
    for common in {context["common"] for context in contexts}:
        receipts = common / "gsd-path" / "workspaces"
        if not os.path.lexists(receipts):
            continue
        if is_link_like(receipts) or not receipts.is_dir():
            raise ValueError("pinned workspace receipts cannot be resolved")
        try:
            with os.scandir(receipts) as entries:
                receipt_files = sorted(
                    (Path(entry.path) for entry in entries if entry.name.endswith(".json")),
                    key=lambda path: path.name,
                )
        except OSError as error:
            raise ValueError(f"pinned workspace receipts cannot be listed: {error}") from None
        for receipt in receipt_files:
            try:
                metadata = receipt.lstat()
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError("receipt is not a regular file")
                data = json.loads(receipt.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise ValueError(
                    f"pinned workspace receipt cannot be read: {receipt.name}"
                ) from None
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("primary"), str)
                or not isinstance(data.get("root"), str)
                or not Path(data["primary"]).is_absolute()
                or not Path(data["root"]).is_absolute()
            ):
                raise ValueError(
                    f"pinned workspace receipt is malformed: {receipt.name}"
                )
            roots.append(Path(data["root"]).resolve())
    return roots


def owned_target_reason(command, arguments, git_options, working_directories):
    action = {
        "branch": "git branch -D",
        "update-ref": "git update-ref deletion",
        "worktree": "git worktree remove --force",
    }[command]
    unresolved = GIT_REASONS["unresolved-target"].format(action=action)
    contexts = git_target_contexts(git_options, working_directories)
    branches, task_worktrees = path_owned_records(_frontmatter_roots(contexts))

    if command == "branch":
        targets = _positional_targets(
            arguments,
            {"--format", "--sort", "--color", "--contains", "--no-contains", "--merged", "--no-merged"},
        )
        if not targets or not all(_literal_target(target) for target in targets):
            return unresolved
        for target in targets:
            for context in contexts:
                ref = _resolvable_branch_ref(target, _git_refs(context))
                if ref is None:
                    return unresolved
                if ref_is_path_owned(ref, branches):
                    return GIT_REASONS["branch"]
        return None

    if command == "update-ref":
        if any(argument.startswith("--stdin") for argument in arguments):
            return unresolved
        operands = []
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument in {"-m", "--message"}:
                index += 2
                continue
            if argument.startswith("--message=") or argument.startswith("-"):
                index += 1
                continue
            operands.append(argument)
            index += 1
        deletion_flag = "-d" in arguments or "--delete" in arguments
        expected_counts = {1, 2} if deletion_flag else {2, 3}
        if len(operands) not in expected_counts or not _literal_target(operands[0]):
            return unresolved
        if not deletion_flag and not (operands[1] == "" or not operands[1].strip("0")):
            return unresolved
        if deletion_flag and len(operands) == 2 and not _literal_target(operands[1]):
            return unresolved
        if not deletion_flag and len(operands) == 3 and not _literal_target(operands[2]):
            return unresolved
        no_deref = "--no-deref" in arguments
        # Dereferencing a symbolic ref must not erase ownership of its name.
        if ref_is_path_owned(operands[0], branches):
            return GIT_REASONS["update-ref"]
        for context in contexts:
            ref = _resolvable_update_ref(
                operands[0], _git_refs(context), context, no_deref
            )
            if ref is None:
                return unresolved
            if ref_is_path_owned(ref, branches):
                return GIT_REASONS["update-ref"]
        return None

    targets = _positional_targets(arguments[1:])
    if len(targets) != 1 or not _literal_target(targets[0]):
        return unresolved
    recorded_paths = set(task_worktrees)
    managed_roots = _workspace_roots(contexts)
    for context in contexts:
        target = Path(targets[0])
        if not target.is_absolute():
            target = context["effective_directory"] / target
        resolved_target = None
        try:
            resolved_target = target.resolve(strict=True)
        except (OSError, RuntimeError):
            pass
        registered = context["worktrees"]
        if resolved_target is not None and resolved_target in registered:
            matches = [resolved_target]
        else:
            suffix = tuple(part for part in Path(targets[0]).parts if part not in {"", "."})
            matches = [
                path for path in registered
                if suffix and tuple(path.parts[-len(suffix):]) == suffix
            ] if not Path(targets[0]).is_absolute() and ".." not in suffix else []
        if len(matches) != 1:
            return unresolved
        resolved_target = matches[0]
        if not resolved_target.is_dir():
            return unresolved
        branch = registered[resolved_target]
        if (
            "gsd-path" in str(resolved_target).casefold()
            or resolved_target in recorded_paths
            or (branch is not None and ref_is_path_owned(branch, branches))
            or any(
                resolved_target == root or resolved_target.is_relative_to(root)
                for root in managed_roots
            )
        ):
            return GIT_REASONS["worktree"]
    return None


def _path_has_symlink_component(value):
    path = Path(value)
    if not path.is_absolute():
        path = Path.cwd() / path
    current = Path(path.anchor)
    for component in path.parts[1:]:
        if component in {"", "."}:
            continue
        if component == "..":
            current = current.parent
            continue
        current = current / component
        try:
            if os.path.lexists(current) and is_link_like(current):
                return True
        except OSError:
            return True
    return False


def env_wrapper_changes_git_context(segment):
    """Whether an env wrapper makes ownership or alias lookup context uncertain."""
    index = 0
    while index < len(segment) and SHELL_ASSIGNMENT_PATTERN.match(segment[index]):
        index += 1
    if index >= len(segment):
        return False
    executable = segment[index].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if executable != "env":
        return False

    def affects_git_context(name):
        folded = name.upper()
        return folded.startswith("GIT_") or folded in {"HOME", "XDG_CONFIG_HOME"}

    index += 1
    while index < len(segment):
        token = segment[index]
        if token == "--":
            return False
        if token in {"-i", "--ignore-environment"}:
            return True
        if token.startswith("--unset="):
            if affects_git_context(token.split("=", 1)[1]):
                return True
            index += 1
            continue
        if token in {"-u", "--unset"}:
            if index + 1 >= len(segment):
                return False
            if affects_git_context(segment[index + 1]):
                return True
            index += 2
            continue
        if SHELL_ASSIGNMENT_PATTERN.match(token):
            if affects_git_context(token.partition("=")[0]):
                return True
            index += 1
            continue
        option = token.split("=", 1)[0]
        if option in ENV_OPTIONS_WITH_VALUES:
            index += 1 if "=" in token else 2
            continue
        if option in ENV_OPTIONS_WITHOUT_VALUES:
            index += 1
            continue
        if token.startswith("-"):
            return False
        return False
    return False


def ownership_cwd_is_uncertain(tokens, working_directories=None):
    """Whether a scoped delete follows a cd whose shell control flow is unclear."""
    conditional_words = SHELL_CONTROL_WORDS
    cwd_wrappers = COMMAND_WRAPPERS | {"eval", "source", "."}
    segments = []
    current = []
    separator = None
    depth = 0
    for token in tokens:
        if token and set(token) <= set("|;&()\n\r"):
            if current:
                segments.append((current, separator, depth))
                current = []
            if "(" in token:
                depth += token.count("(")
            if ")" in token:
                depth = max(0, depth - token.count(")"))
            separator = token
        else:
            current.append(token)
    if current:
        segments.append((current, separator, depth))

    uncertain = False
    conditional = False
    current_directories = list(working_directories or [os.getcwd()])
    cdpath_ambiguous = bool(os.environ.get("CDPATH"))
    initial_symlink = any(
        _path_has_symlink_component(directory) for directory in current_directories
    )
    for index, (segment, previous_separator, group_depth) in enumerate(segments):
        if env_wrapper_changes_git_context(segment):
            return True
        if any(token.casefold() in conditional_words for token in segment):
            conditional = True
        while segment and segment[0].casefold() in SHELL_CONTROL_WORDS:
            segment = segment[1:]
        invocation = command_invocation(segment)
        if invocation is None:
            continue
        command, arguments = invocation
        next_separator = (
            segments[index + 1][1] if index + 1 < len(segments) else None
        )
        if any(token.partition("=")[0] == "CDPATH" for token in segment):
            cdpath_ambiguous = True
        if command == "export" and any(
            token.partition("=")[0] == "CDPATH" for token in arguments
        ):
            cdpath_ambiguous = True
        if command in DIRECTORY_CHANGE_COMMANDS:
            target = directory_change_target(arguments)
            if SHELL_PARAMETER_SYNTAX.search(target):
                raise ValueError("cd target cannot be resolved by the guard")
            absolute = is_absolute_path(target)
            next_directories = (
                [target]
                if absolute
                else [f"{directory}/{target}" for directory in current_directories]
            )
            if (
                group_depth > 0
                or previous_separator in {"&&", "||", "&"}
                or next_separator in {"||", "&"}
                or (previous_separator is not None and "|" in previous_separator)
                or (next_separator is not None and "|" in next_separator)
                or conditional
                or (not absolute and cdpath_ambiguous)
                or initial_symlink
                or any(_path_has_symlink_component(path) for path in next_directories)
            ):
                uncertain = True
            current_directories = next_directories
            initial_symlink = False
        if command in cwd_wrappers and index + 1 < len(segments):
            uncertain = True
        if uncertain and index + 1 < len(segments):
            return True
        if any(token.casefold() in {"fi", "done", "esac"} for token in segment):
            conditional = False
    return False


def assignments_change_git_context(assignments):
    return any(
        name.upper().startswith("GIT_")
        or name.upper() in {"HOME", "XDG_CONFIG_HOME"}
        for name in assignments
    )

def destructive_git_reason(
    tokens,
    resolved_aliases=frozenset(),
    initial_assignments=None,
    working_directories=None,
    cwd_reliable=True,
    git_context_reliable=True,
):
    cwd_reliable = cwd_reliable and not ownership_cwd_is_uncertain(
        tokens, working_directories
    )
    for segment, directories, assignments, _prefix in shell_segment_contexts(
        tokens, working_directories or [os.getcwd()], initial_assignments
    ):
        # A dollar expansion can introduce literal percent/bang text; the second
        # expansion pass must not silently reinterpret it as a different path.
        cwd_reliable = cwd_reliable and not any(
            CMD_PARAMETER_SYNTAX.search(NAMED_SHELL_PARAMETER_SYNTAX.sub(
                lambda match: environment_parameter_value(match, assignments), token
            ))
            for token in segment
        )
        segment_git_context_reliable = (
            git_context_reliable
            and not env_wrapper_changes_git_context(segment)
            and not assignments_change_git_context(assignments)
        )
        wrapped = wrapped_command_tokens(segment)
        if wrapped is not None:
            reason = destructive_git_reason(
                wrapped,
                resolved_aliases,
                initial_assignments=assignments,
                working_directories=directories,
                cwd_reliable=cwd_reliable,
                git_context_reliable=segment_git_context_reliable,
            )
            if reason is not None:
                return reason
        invocation = git_command(segment, assignments)
        if invocation is None:
            continue
        if not segment_git_context_reliable:
            return GIT_REASONS["git-environment"]
        command, arguments, git_options = invocation
        if command == "config":
            alias_indexes = [
                index
                for index, argument in enumerate(arguments)
                if argument.casefold().startswith("alias.")
            ]
            if any(index + 1 < len(arguments) for index in alias_indexes):
                raise ValueError(
                    "git config alias.* defines an alias the guard cannot inspect; "
                    "run the underlying git command directly"
                )
        alias = git_alias(command, git_options, directories)
        if alias is not None:
            if command in resolved_aliases:
                raise ValueError(
                    f"git alias {command} refers to itself; run the underlying "
                    "git command directly"
                )
            reason = destructive_git_reason(
                ["git", *git_options, *shell_tokens(alias), *arguments],
                resolved_aliases | {command},
                initial_assignments=assignments,
                working_directories=directories,
                # Non-shell Git aliases do not expand environment parameters.
                cwd_reliable=cwd_reliable and not (
                    NAMED_SHELL_PARAMETER_SYNTAX.search(alias)
                    or CMD_PARAMETER_SYNTAX.search(alias)
                ),
                git_context_reliable=segment_git_context_reliable,
            )
            if reason is not None:
                return reason
            continue
        if command == "reset" and "--hard" in arguments:
            return GIT_REASONS[command]
        if command == "clean":
            force = "--force" in arguments or has_short_option(arguments, "f")
            interactive = "--interactive" in arguments or has_short_option(
                arguments, "i"
            )
            if force or interactive:
                return GIT_REASONS[command]
        if command == "push":
            force_option = any(
                argument == "--force"
                or argument.startswith("--force-with-lease")
                or argument == "--mirror"
                for argument in arguments
            ) or has_short_option(arguments, "f")
            force_refspec = any(
                argument.startswith("+") and len(argument) > 1
                for argument in arguments
            )
            if force_option or force_refspec:
                return GIT_REASONS[command]
        if command == "branch":
            deletes = (
                "--delete" in arguments
                or has_short_option(arguments, "d")
                or has_short_option(arguments, "D")
            )
            forces = (
                "--force" in arguments
                or has_short_option(arguments, "f")
                or has_short_option(arguments, "D")
            )
            if deletes and forces:
                if not cwd_reliable:
                    return GIT_REASONS["unresolved-target"].format(
                        action="git branch -D"
                    )
                reason = owned_target_reason(
                    command, arguments, git_options, directories
                )
                if reason is not None:
                    return reason
            if (
                "--move" in arguments
                or has_short_option(arguments, "m")
                or has_short_option(arguments, "M")
            ):
                return GIT_REASONS["branch-move"]
        if command == "update-ref":
            if update_ref_deletes(arguments):
                if not cwd_reliable:
                    return GIT_REASONS["unresolved-target"].format(
                        action="git update-ref deletion"
                    )
                reason = owned_target_reason(
                    command, arguments, git_options, directories
                )
                if reason is not None:
                    return reason
        if command == "worktree" and arguments[:1] == ["remove"]:
            if "--force" in arguments or has_short_option(arguments[1:], "f"):
                if not cwd_reliable:
                    return GIT_REASONS["unresolved-target"].format(
                        action="git worktree remove --force"
                    )
                reason = owned_target_reason(
                    "worktree", arguments, git_options, directories
                )
                if reason is not None:
                    return reason
        if command == "stash" and arguments[:1] in (["drop"], ["clear"]):
            return GIT_REASONS[command]
        if command in {"checkout", "restore"} and any(
            argument in WHOLE_TREE_PATHSPECS for argument in arguments
        ):
            touches_worktree = command == "checkout" or (
                "--worktree" in arguments
                or has_short_option(arguments, "W")
                or not ("--staged" in arguments or has_short_option(arguments, "S"))
            )
            if touches_worktree:
                return GIT_REASONS["checkout"]
    return None


PIPELINE_HELPERS = frozenset({"pipeline_state.py", "archive_milestone.py"})


def closed_milestone_reason(repo=None):
    repo = repo or repository_root()
    branch = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    if not re.fullmatch(r"gsd-path/M\d{3,}", branch.stdout.strip()):
        return None
    result = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).with_name("git_guard.py")),
         "closed-milestone"], cwd=repo, capture_output=True, encoding="utf-8", errors="replace",
    )
    if result.returncode:
        return result.stderr.strip() or "closed milestone inspection failed"
    return None


def bundled_helper_invocation(command, tokens, working_directories, helpers=PIPELINE_HELPERS):
    """Allow one plain ``python[3] [-B] <script>`` from the guard-owned runtime.

    The interpreter must be exactly python, python3, or py -3, and the script
    operand is the exact parsed token, with expansions and parent traversal refused.
    The resolved helper must be a regular file inside runtime/ beside this guard,
    or beside the guard itself in the repository layout. Resolve only in supplied
    tool working directories, falling back to cwd when none are supplied.
    """
    if any(char in command for char in "\n\r\\"):
        return False
    segments = list(command_segments(tokens))
    if len(segments) != 1 or segments[0] != tokens:
        return False
    if any(
        re.fullmatch(r"[<>&|]*[<>][<>&|]*|[0-9]+(?:[<>]|&>).*", token)
        for token in tokens
    ):
        return False
    _, substitutions = split_command_substitutions(command)
    if substitutions or wrapped_command_tokens(segments[0]) is not None:
        return False
    if tokens[:2] == ["py", "-3"]:
        rest = tokens[2:]
    elif tokens[0] in ("python", "python3"):
        rest = tokens[1:]
    else:
        return False
    if rest[:1] == ["-B"]:
        rest = rest[1:]
    if not rest:
        return False
    operand = rest[0]
    if (
        operand.startswith("~")
        or any(char in operand for char in "$`*?[]{}")
        or ".." in operand.split("/")
    ):
        return False
    here = Path(__file__).resolve().parent
    runtime = here / "runtime"
    if (here / "runtime.json").exists():
        try:
            from status_runtime import resolve_runtime
            runtime = resolve_runtime(here.parent)
        except (OSError, ValueError):
            return False
    elif not runtime.exists():
        runtime = here
    runtime = runtime.resolve()
    for base in working_directories or [os.getcwd()]:
        try:
            # A Git Bash /c/... operand names the C: drive, not a folder named c.
            script = (Path(base) / native_path_text(operand)).resolve()
            if (
                script.name in helpers
                and (script.is_relative_to(runtime) or (
                    script.name == "status_runtime.py" and script == here / "status_runtime.py"
                ))
                and script.is_file()
            ):
                return True
        except (OSError, RuntimeError):
            continue
    return False


def archive_command_is_read_only(
    command, tokens, archive_context=False, git_commands=ARCHIVE_READ_GIT_COMMANDS
):
    if archive_context and AMBIGUOUS_SHELL_SYNTAX.search(command):
        return False
    if not archive_context:
        return True
    invocation = command_invocation(tokens)
    if invocation is None:
        return True
    executable, arguments = invocation
    executable = executable.removesuffix(".exe")
    if executable in DIRECTORY_CHANGE_COMMANDS:
        return True
    if executable in {"export", "declare", "typeset", "unset"}:
        return True
    denied_options = ARCHIVE_READ_EXECUTION_OPTIONS.get(executable, ())
    if any(
        token == option or token.startswith(f"{option}=")
        for token in arguments
        for option in denied_options
    ):
        return False
    if executable == "sed":
        in_place, _inputs, script_is_read_only = sed_arguments(arguments)
        return not in_place and script_is_read_only
    if executable in ARCHIVE_READ_COMMANDS:
        return True
    if executable != "git":
        return False
    git = git_command(tokens)
    if git is None:
        return False
    subcommand, git_arguments, _options = git
    if subcommand not in git_commands:
        return False
    return not any(
        token in GIT_READ_WRITE_OPTIONS or token.startswith("--output=")
        for token in git_arguments
    )


def deny(reason):
    # One denial object per documented host schema: decision/reason (Grok,
    # Antigravity), permission + user/agentMessage (Cursor), permissionDecision
    # (Copilot), hookSpecificOutput (Claude Code, Codex, Qwen).
    print(
        json.dumps(
            {
                "decision": "deny",
                "reason": reason,
                "permission": "deny",
                "userMessage": reason,
                "agentMessage": reason,
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                },
            }
        )
    )
    print(f"gsd-path guard: {reason}", file=sys.stderr)
    sys.exit(2)


def evaluate(event):
    tool = event.get("tool_name") or event.get("toolName") or event.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        raise ValueError("hook event is missing its tool name")
    paths, working_directories, commands, patch_payloads = [], [], [], []
    path_keys = PATH_KEYS
    if is_direct_write_tool(tool):
        path_keys |= MUTATION_OPERAND_KEYS
    collect(
        event,
        paths,
        working_directories,
        commands,
        patch_payloads,
        path_keys,
    )
    raw_input = event.get("tool_input", event.get("toolInput"))
    raw_patch = isinstance(raw_input, str) and has_patch_headers(raw_input)
    if is_patch_tool(tool) or raw_patch:
        patch_payloads.extend(commands)
        if isinstance(raw_input, str):
            patch_payloads.append((raw_input, tuple(working_directories)))
        commands = []
    read_tool = is_read_tool(tool)
    extracted_patch_paths = []
    if not read_tool:
        for path, path_working_directories in paths:
            if path_in_archive(path, path_working_directories):
                deny(ARCHIVE_REASON)
        extracted_patch_paths = [
            (path, patch_working_directories)
            for payload, patch_working_directories in patch_payloads
            for path in patch_paths(payload)
        ]
        if patch_payloads and not paths and not extracted_patch_paths:
            raise ValueError("patch targets cannot be validated")
        for path, path_working_directories in extracted_patch_paths:
            if path_in_archive(path, path_working_directories):
                deny(ARCHIVE_REASON)
        if is_direct_write_tool(tool, bool(paths or extracted_patch_paths)):
            write_paths = [*paths, *extracted_patch_paths]
            if not write_paths:
                raise ValueError("write targets cannot be validated")
            grouped_paths = {}
            for path, path_working_directories in write_paths:
                grouped_paths.setdefault(path_working_directories, []).append(path)
            for path_working_directories, targets in grouped_paths.items():
                enforce_pipeline_reentry(targets, path_working_directories)
    archive_working_directory = any(
        working_directory_in_archive(path) for path in working_directories
    )
    if archive_working_directory and not commands and not read_tool:
        deny(ARCHIVE_REASON)
    for command, command_working_directories in commands:
        reason = command_denial(command, command_working_directories)
        if reason is not None:
            deny(reason)


def destructive_shell_invocations(tokens):
    for segment in command_segments(tokens):
        invocation = command_invocation(segment)
        if command_can_destroy_files(invocation):
            yield invocation
        wrapped = wrapped_command_tokens(segment, expand_parameters=False)
        if wrapped is not None:
            yield from destructive_shell_invocations(wrapped)


def closed_git_listing(tokens):
    """Whether a Git call uses only the allowed object-read or listing forms."""
    if len(tokens) < 2 or tokens[0] != "git":
        return False
    subcommand, arguments = tokens[1], tokens[2:]
    if subcommand == "worktree":
        if arguments[:1] != ["list"]:
            return False
        subcommand, arguments = "worktree list", arguments[1:]
    allowed = CLOSED_LISTING_GIT_OPTIONS.get(subcommand)
    if allowed is None:
        return False
    options = [argument for argument in arguments if argument.startswith("-")]
    positionals = len(arguments) - len(options)
    if any(option not in allowed for option in options):
        return False
    if subcommand == "branch":
        return not positionals or bool({"-l", "--list"} & set(options))
    if subcommand in {"cat-file", "symbolic-ref"}:
        return positionals == 1
    return not positionals


def closed_shell_execution_reason(
    command, tokens, working_directories, initial_assignments=None
):
    helpers = PIPELINE_HELPERS | {"pipeline_git.py", "status_runtime.py", "promote_lookahead.py", "pipeline_diagnose.py"}
    rest = tokens[3:] if tokens[1:2] == ["-B"] else tokens[2:]
    if rest[:1] == ["pending"]:
        helpers = helpers | {"discussion_records.py"}
    if bundled_helper_invocation(command, tokens, working_directories, helpers):
        return None
    for segment, directories, assignments, _prefix in shell_segment_contexts(
        tokens, working_directories, initial_assignments
    ):
        wrapped = wrapped_command_tokens(segment)
        if wrapped is not None:
            reason = closed_shell_execution_reason(
                shlex.join(wrapped), wrapped, directories, assignments
            )
            if reason:
                return reason
            continue
        metadata_closed = None
        git = git_command(segment, assignments)
        checked_segment = segment
        if git is not None:
            subcommand, arguments, options = git
            checked_segment = ["git", subcommand, *arguments]
            if options:
                roots = []
                for directory in directories:
                    result = subprocess.run(
                        ["git", *options, "rev-parse", "--show-toplevel", "--absolute-git-dir"],
                        cwd=directory, capture_output=True, encoding="utf-8", errors="replace",
                    )
                    if result.returncode:
                        raise ValueError("git target repository cannot be resolved")
                    root, metadata = result.stdout.splitlines()
                    roots.append(root)
                    metadata_closed = metadata_closed or closed_milestone_reason(Path(metadata))
                directories = roots
        closed = metadata_closed or closed_target_reason([(".", directories)])
        if not closed:
            continue
        invocation = command_invocation(segment)
        if invocation is None:
            continue
        executable, _ = invocation
        if executable in DIRECTORY_CHANGE_COMMANDS or checked_segment == ["git", "fetch", "origin"]:
            continue
        plain = checked_segment[:next((i for i, token in enumerate(checked_segment) if is_redirection(token)), len(checked_segment))]
        if executable in {"echo", "printf"} or closed_git_listing(plain) or archive_command_is_read_only(
            shlex.join(plain), plain, True, CLOSED_READ_GIT_COMMANDS
        ):
            continue
        return closed
    return None


def command_denial(command, working_directories, allow_destructive=True):
    """Return why a shell command is denied, or None when it may run."""
    working_directories = working_directories or [os.getcwd()]
    command = re.sub(r"(?i:(\.project)\\(archive))", r"\1/\2", command)
    outer, substitutions = split_command_substitutions(command)
    try:
        tokens = shell_tokens(outer)
        if tokens in (
            [*interpreter.split(), "-B", "-c", "import sys; raise SystemExit(sys.version_info < (3, 9))"]
            for interpreter in ("python3", "python", "py -3")
        ):
            return None
        bundled_helper = bundled_helper_invocation(command, tokens, working_directories)
        destructive = list(destructive_shell_invocations(tokens))
        if destructive and (
            not allow_destructive
            or substitutions
            or any(char in command for char in ";&|()\n\r`")
            or len(list(command_segments(tokens))) != 1
            or any(
                literal_path(operand) is None
                for _, operands in destructive
                for operand in operands
            )
        ):
            return DESTRUCTIVE_SHAPE_REASON
        reason = closed_shell_execution_reason(command, tokens, working_directories)
        if reason:
            return reason
        for inner in substitutions:
            reason = command_denial(inner, working_directories, allow_destructive=False)
            if reason is not None:
                return reason
        for segment, directories, assignments, prefix in shell_segment_contexts(
            tokens, working_directories
        ):
            resolved_segment = [
                expand_environment_parameters(token, assignments) for token in segment
            ]
            archive_context = (
                any(working_directory_in_archive(path) for path in directories)
                or segment_references_archive(segment, directories, assignments)
                or any(
                    ARCHIVE_REFERENCE.search(value)
                    or path_in_archive(value, directories, ancestors=False)
                    for value in prefix.values()
                )
            )
            if not archive_command_is_read_only(
                shlex.join(resolved_segment), resolved_segment, archive_context
            ) and not (
                archive_context
                and bundled_helper
            ):
                return ARCHIVE_REASON
        reason = destructive_git_reason(
            tokens, working_directories=working_directories,
            cwd_reliable=not shell_parameter_quoting_uncertain(outer),
        ) or protected_shell_write_reason(tokens, working_directories)
    except ValueError as error:
        raise ValueError(describe_substitutions(str(error), substitutions)) from None
    return reason and describe_substitutions(reason, substitutions)


def allow(event):
    if "cursor_version" in event:  # Cursor fails closed on empty stdout; see the module docstring
        print(json.dumps({"permission": "allow"}))


def main():
    # Hosts exchange hook input and output as UTF-8; a Windows pipe would
    # default to cp1252. In-process callers may substitute text streams.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        stdin = getattr(sys.stdin, "buffer", None)
        event = json.loads(stdin.read().decode("utf-8") if stdin is not None else sys.stdin.read())
        if not isinstance(event, dict):
            raise ValueError("hook event must be an object")
        evaluate(event)
        allow(event)
    except SystemExit:
        raise
    except ValueError as error:
        deny(f"{INVALID_INPUT_REASON}: {error}")
    except Exception:
        deny(INVALID_INPUT_REASON)


if __name__ == "__main__":
    main()
