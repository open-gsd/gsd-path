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
STATUS_INTEGRATION_MODES = frozenset({"direct", "pull-request"})
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
GIT_READ_WRITE_OPTIONS = frozenset({"--output", "--ext-diff", "--textconv"})
ARCHIVE_READ_EXECUTION_OPTIONS = {"rg": frozenset({"--pre"})}
AMBIGUOUS_SHELL_SYNTAX = re.compile(r"[\r\n|;&<>`]|\$\(|@\(")
SUBSTITUTION_PLACEHOLDER = "COMMAND_SUBSTITUTION_"
SUBSTITUTION_PLACEHOLDER_SYNTAX = re.compile(
    r"\$\{" + SUBSTITUTION_PLACEHOLDER + r"(\d+)\}"
)
LINE_CONTINUATION = re.compile(r"(?<!\\)((?:\\\\)*)\\\r?\n")
HEREDOC_PATTERN = re.compile(
    r"<<(?P<dash>-?)\s*(?:'(?P<single>[^']+)'|\"(?P<double>[^\"]+)\""
    r"|\\?(?P<bare>[A-Za-z_][A-Za-z0-9_]*))"
)
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
            if isinstance(value, str):
                local_working_directories.append(value)
            elif isinstance(value, list):
                strings = [item for item in value if isinstance(item, str)]
                if len(strings) != len(value):
                    raise ValueError("working directories cannot be validated")
                local_working_directories.extend(strings)
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
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        state = candidate / ".project" / "STATE.md"
        if (
            candidate.is_dir()
            and not candidate.is_symlink()
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
        text=True,
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
    candidate = Path(path)
    if not candidate.is_absolute():
        base = Path(working_directories[0]) if working_directories else repo
        if not base.is_absolute():
            base = repo / base
        candidate = base / candidate
    return Path(os.path.abspath(candidate)), candidate.resolve(strict=False)


@lru_cache(maxsize=None)
def repository_control_roots(repo):
    roots = [(repo / ".git").resolve(strict=False)]
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=repo,
        text=True,
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


def target_kind(path, working_directories, repo, control_roots=None):
    lexical, resolved = target_paths(path, working_directories, repo)
    repo = repo.resolve()
    if control_roots is None:
        control_roots = repository_control_roots(repo)
    aliases = (
        _canonical_control_alias(lexical, repo, control_roots),
        _canonical_control_alias(resolved, repo, control_roots),
    )
    kinds = {
        path_kind(candidate, repo, control_roots)
        for candidate in (lexical, resolved, *aliases)
    }
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
        _, target = target_paths(path, working_directories, repository_root())
        directory = target if target.is_dir() else target.parent
        while not directory.exists() and directory != directory.parent:
            directory = directory.parent
        root = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        if root.returncode == 0:
            reason = closed_milestone_reason(Path(root.stdout.strip()))
            if reason:
                return reason
    return None


def enforce_pipeline_reentry(paths, working_directories):
    reason = closed_target_reason((path, working_directories) for path in paths)
    if reason:
        deny(reason)
    classified = pipeline_target_kinds((path, working_directories) for path in paths)
    if classified is None:
        return
    repo, state, kinds = classified
    for path, kind in kinds:
        if kind == "protected":
            deny(f"{CONTROL_FILE_REASON} {path}")
    kinds = [kind for _, kind in kinds]
    if all(kind == "external" for kind in kinds):
        return
    try:
        status = project_status(repo)
    except (OSError, ValueError, json.JSONDecodeError):
        deny(REENTRY_FAILURE_REASON)
    route = status.get("route")
    state_data = status.get("state") if isinstance(status.get("state"), dict) else {}
    routed_build = (
        state_data.get("phase") == "build"
        and isinstance(route, dict)
        and route.get("action") == "run-phase"
        and route.get("phase") == "build"
    )
    if routed_build:
        return
    if all(kind in {"external", "artifact"} for kind in kinds):
        return
    phase = state_data.get("phase", "unknown")
    if isinstance(route, dict) and route.get("action") != "run-phase":
        next_step = f"{route.get('action', 'route')}: {route.get('reason', 'no reason')}"
    else:
        next_step = status.get("next_skill") or "gsd-path"
    deny(
        f"GSD Path is {phase}; direct product-file changes require the routed "
        f"build phase. Review {status.get('path', state)}; next: {next_step}"
    )


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


def path_values(value):
    yield value
    if value.startswith("-") and "=" in value:
        yield value.split("=", 1)[1]


def is_absolute_path(path):
    normalized = path.replace("\\", "/")
    return normalized.startswith("/") or bool(re.match(r"^[A-Za-z]:/", normalized))


def contains_existing_archive(path, working_directories):
    try:
        target = Path(path).resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    search_paths = [target, Path.cwd(), *(Path(value) for value in working_directories)]
    for search_path in search_paths:
        if os.name != "nt" and re.match(r"^[A-Za-z]:[/\\]", str(search_path)):
            continue
        try:
            resolved = search_path.resolve(strict=False)
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
                resolved = Path(combined).resolve(strict=False)
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
            resolved = Path(value).resolve(strict=False)
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


def command_references_archive(tokens, working_directories):
    for segment, directories in segment_directories(tokens, working_directories):
        invocation = command_invocation(segment)
        ancestors = command_can_destroy_files(invocation)
        operands = segment
        if ancestors:
            operands = [literal_destructive_operand(operand) for operand in invocation[1]]
        if any(path_in_archive(operand, directories, ancestors) for operand in operands):
            return True
        wrapped = wrapped_command_tokens(segment, expand_parameters=False)
        if wrapped is not None and command_references_archive(wrapped, directories):
            return True
    return False


def shell_write_targets(tokens, working_directories):
    """Yield (target, directories) for every path a shell command may write."""
    for segment, directories in segment_directories(tokens, working_directories):
        for index, token in enumerate(segment[:-1]):
            if ">" not in token or not set(token) <= SHELL_WRITE_REDIRECTION_CHARS:
                continue
            target = segment[index + 1]
            if token.endswith("&") and (target.isdigit() or target == "-"):
                continue
            yield target, directories
        wrapped = wrapped_command_tokens(segment)
        if wrapped is not None:
            yield from shell_write_targets(wrapped, directories)
            continue
        invocation = command_invocation(segment)
        if invocation is None:
            continue
        command, arguments = invocation
        in_place = command in IN_PLACE_EDITORS and (
            has_short_option(arguments, "i")
            or any(argument.startswith("--in-place") for argument in arguments)
        )
        if command.removesuffix(".exe") in SHELL_WRITE_COMMANDS or in_place:
            for argument in arguments:
                if argument and not argument.startswith("-"):
                    yield argument, directories


def protected_shell_write_reason(tokens, working_directories):
    assignments = shell_assignment_values(tokens)
    targets = []
    for target, directories in shell_write_targets(tokens, working_directories):
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
    return None


def environment_parameter_value(match, assignments):
    name = match.group(1) or match.group(2)
    if name.startswith(SUBSTITUTION_PLACEHOLDER):
        return match.group(0)  # command substitution output is never resolved
    return assignments.get(name, os.environ.get(name, ""))


def expand_environment_parameters(command, assignments=None):
    values = assignments or {}

    def substitute(match):
        return environment_parameter_value(match, values)

    expanded = NAMED_SHELL_PARAMETER_SYNTAX.sub(substitute, command)
    return CMD_PARAMETER_SYNTAX.sub(substitute, expanded)


def shell_assignment_values(tokens):
    values = {}
    for segment in command_segments(tokens):
        variable_command = segment[0].casefold() in VARIABLE_COMMANDS
        for token in segment:
            if not SHELL_ASSIGNMENT_PATTERN.match(token):
                if variable_command:
                    continue
                break
            name, value = token.split("=", 1)
            values[name] = expand_environment_parameters(value, values)
    return values


def unresolved_archive_expansion(command, tokens, working_directories):
    expanded = expand_environment_parameters(command, shell_assignment_values(tokens))
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


def split_command_substitutions(command):
    """Replace every $(...) and `...` with a placeholder; return (outer, inner)."""
    if "@(" in command:
        raise ValueError(
            "@( expansion cannot be validated; write the list as literal arguments"
        )
    if "$(" not in command and "`" not in command:
        return command, []
    outer, inner, index = [], [], 0
    while index < len(command):
        if command.startswith("$(", index):
            end = substitution_end(command, index + 2)
            inner.append(command[index + 2 : end])
        elif command[index] == "`":
            end = index + 1
            while end < len(command) and command[end] != "`":
                end += 2 if command[end] == "\\" else 1
            if end >= len(command):
                raise ValueError("backtick command substitution is not closed")
            inner.append(command[index + 1 : end])
        elif command[index] == "\\":
            outer.append(command[index : index + 2])
            index += 2
            continue
        else:
            outer.append(command[index])
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
        for match in HEREDOC_PATTERN.finditer(line):
            delimiter = (
                match.group("single") or match.group("double") or match.group("bare")
            )
            strip = "\t\r" if match.group("dash") else "\r"
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


def git_command(segment):
    invocation = command_invocation(segment)
    if invocation is None:
        return None
    executable, arguments = invocation
    if executable not in {"git", "git.exe"}:
        return None
    for argument in arguments:
        if SHELL_PARAMETER_SYNTAX.search(argument):
            raise ValueError(
                f"git argument {argument} cannot be resolved by the guard; pass a "
                "literal value (for commit messages use -F <file>)"
            )
    index = 0
    git_options = []
    while index < len(arguments) and arguments[index].startswith("-"):
        token = arguments[index]
        if token.startswith("-c") and token != "-c" and not token.startswith("--"):
            option, value = "-c", token[2:]
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


def git_alias(command, git_options):
    result = subprocess.run(
        ["git", *git_options, "config", "--get", f"alias.{command}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise ValueError("git alias configuration cannot be validated")
    alias = result.stdout.strip()
    if not alias or alias.startswith("!"):
        raise ValueError("git alias configuration cannot be validated")
    return alias


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


def destructive_git_reason(tokens, resolved_aliases=frozenset()):
    for segment in command_segments(tokens):
        wrapped = wrapped_command_tokens(segment)
        if wrapped is not None:
            reason = destructive_git_reason(wrapped, resolved_aliases)
            if reason is not None:
                return reason
        invocation = git_command(segment)
        if invocation is None:
            continue
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
        alias = git_alias(command, git_options)
        if alias is not None:
            if command in resolved_aliases:
                raise ValueError(
                    f"git alias {command} refers to itself; run the underlying "
                    "git command directly"
                )
            reason = destructive_git_reason(
                ["git", *git_options, *shell_tokens(alias), *arguments],
                resolved_aliases | {command},
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
                return GIT_REASONS[command]
            if (
                "--move" in arguments
                or has_short_option(arguments, "m")
                or has_short_option(arguments, "M")
            ):
                return GIT_REASONS["branch-move"]
        if command == "update-ref":
            if update_ref_deletes(arguments):
                return GIT_REASONS[command]
        if command == "worktree" and arguments[:1] == ["remove"]:
            if "--force" in arguments or has_short_option(arguments[1:], "f"):
                return GIT_REASONS[command]
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
        capture_output=True, text=True,
    )
    if not re.fullmatch(r"gsd-path/M\d{3,}", branch.stdout.strip()):
        return None
    result = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).with_name("git_guard.py")),
         "closed-milestone"], cwd=repo, capture_output=True, text=True,
    )
    if result.returncode:
        return result.stderr.strip() or "closed milestone inspection failed"
    return None


def bundled_helper_invocation(command, tokens, working_directories, helpers=PIPELINE_HELPERS):
    """Allow one plain ``python[3] [-B] <script>`` from the guard-owned runtime.

    The interpreter token must be exactly python or python3, and the script
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
    if tokens[0] not in ("python", "python3"):
        return False
    rest = tokens[1:]
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
    if not runtime.exists():
        runtime = here
    runtime = runtime.resolve()
    for base in working_directories or [os.getcwd()]:
        try:
            script = (Path(base) / operand).resolve()
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


def archive_command_is_read_only(command, tokens, archive_context=False, git_commands=ARCHIVE_READ_GIT_COMMANDS):
    if archive_context and AMBIGUOUS_SHELL_SYNTAX.search(command):
        return False
    if not archive_context:
        return True
    executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    denied_options = ARCHIVE_READ_EXECUTION_OPTIONS.get(executable, ())
    if any(
        token == option or token.startswith(f"{option}=")
        for token in tokens[1:]
        for option in denied_options
    ):
        return False
    if executable in ARCHIVE_READ_COMMANDS:
        return True
    if executable != "git" or len(tokens) < 2:
        return False
    if tokens[1].casefold() not in git_commands:
        return False
    return not any(
        token in GIT_READ_WRITE_OPTIONS or token.startswith("--output=")
        for token in tokens[2:]
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


def closed_shell_execution_reason(command, tokens, working_directories):
    helpers = PIPELINE_HELPERS | {"pipeline_git.py", "status_runtime.py", "promote_lookahead.py", "pipeline_diagnose.py"}
    rest = tokens[3:] if tokens[1:2] == ["-B"] else tokens[2:]
    if rest[:1] == ["pending"]:
        helpers = helpers | {"discussion_records.py"}
    if bundled_helper_invocation(command, tokens, working_directories, helpers):
        return None
    for segment, directories in segment_directories(tokens, working_directories):
        wrapped = wrapped_command_tokens(segment)
        if wrapped is not None:
            reason = closed_shell_execution_reason(shlex.join(wrapped), wrapped, directories)
            if reason:
                return reason
            continue
        closed = closed_target_reason([(".", directories)])
        if not closed:
            continue
        invocation = command_invocation(segment)
        if invocation is None:
            continue
        executable, _ = invocation
        if executable in DIRECTORY_CHANGE_COMMANDS or segment == ["git", "fetch", "origin"]:
            continue
        plain = segment[:next((i for i, token in enumerate(segment) if is_redirection(token)), len(segment))]
        if executable in {"echo", "printf"} or archive_command_is_read_only(
            shlex.join(plain), plain, True, ARCHIVE_READ_GIT_COMMANDS | {"rev-parse", "ls-remote"}
        ):
            continue
        return closed
    return None


def command_denial(command, working_directories, allow_destructive=True):
    """Return why a shell command is denied, or None when it may run."""
    working_directories = working_directories or [os.getcwd()]
    outer, substitutions = split_command_substitutions(command)
    try:
        tokens = shell_tokens(outer)
        if tokens in (
            [interpreter, "-B", "-c", "import sys; raise SystemExit(sys.version_info < (3, 9))"]
            for interpreter in ("python3", "python")
        ):
            return None
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
            return ARCHIVE_REASON
        reason = closed_shell_execution_reason(command, tokens, working_directories)
        if reason:
            return reason
        for inner in substitutions:
            reason = command_denial(inner, working_directories, allow_destructive=False)
            if reason is not None:
                return reason
        archive_context = (
            any(working_directory_in_archive(path) for path in working_directories)
            or bool(ARCHIVE_REFERENCE.search(outer))
            or command_references_archive(tokens, working_directories)
            or unresolved_archive_expansion(outer, tokens, working_directories)
        )
        if not archive_command_is_read_only(command, tokens, archive_context) and not (
            archive_context and bundled_helper_invocation(command, tokens, working_directories)
        ):
            return ARCHIVE_REASON
        reason = destructive_git_reason(tokens) or protected_shell_write_reason(
            tokens, working_directories
        )
    except ValueError as error:
        raise ValueError(describe_substitutions(str(error), substitutions)) from None
    return reason and describe_substitutions(reason, substitutions)


def allow(event):
    if "cursor_version" in event:  # Cursor fails closed on empty stdout; see the module docstring
        print(json.dumps({"permission": "allow"}))


def main():
    try:
        event = json.load(sys.stdin)
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
