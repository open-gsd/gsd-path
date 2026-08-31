#!/usr/bin/env python3
"""Cross-host pre-tool-use guard for GSD Path projects.

Reads one hook event as JSON on stdin and enforces the two pipeline
invariants a prompt contract cannot guarantee:

- committed archives under .project/archive/ are read-only, and
- destructive git commands that break build recovery are refused.

Allow: exit 0 with no output. Deny: exit 2, a one-line reason on stderr,
and a denial JSON on stdout carrying every supported host's decision keys
(exit code 2 satisfies Claude Code, Codex, Qwen, Kimi, Grok, Cursor, and
Kiro; the JSON covers hosts that read a decision object instead).
Malformed input or an internal failure denies the tool call.
"""

import ast
from fnmatch import fnmatchcase
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
    "only the bundled archive helper may write there during a ship transaction"
)
ARCHIVE_MARKER = ".project/archive"
INVALID_INPUT_REASON = "GSD Path guard could not validate the tool request"
REENTRY_FAILURE_REASON = (
    "GSD Path status could not be verified; review .project/STATE.md and invoke "
    "gsd-path-forensics before changing product files"
)
CONTROL_FILE_REASON = (
    "GSD Path routing controls cannot be changed by direct write, edit, or patch tools"
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
SHELL_EXPANSION_SYNTAX = re.compile(r"`|\$\(|@\(")
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
    "update-ref": "git update-ref deletion destroys refs the recovery protocol inspects",
}
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
COMMAND_WRAPPERS = frozenset({"command", "exec"})
UNVALIDATED_EXECUTION_COMMANDS = frozenset(
    {
        ".",
        "builtin",
        "call",
        "declare",
        "eval",
        "export",
        "local",
        "readonly",
        "set",
        "setenv",
        "source",
        "start",
        "typeset",
        "unset",
        "unsetenv",
        "xargs",
        "xargs.exe",
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
                if lowered in PATH_KEYS:
                    paths.append((value, context))
                elif lowered in COMMAND_KEYS:
                    commands.append((value, context))
                elif lowered in PATCH_KEYS:
                    patch_payloads.append((value, context))
            elif isinstance(value, list):
                strings = [item for item in value if isinstance(item, str)]
                if strings and lowered in PATH_KEYS:
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
                    context,
                )
            else:
                collect(
                    value,
                    paths,
                    working_directories,
                    commands,
                    patch_payloads,
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
    if parts[0].endswith(":"):
        # Windows drive prefix (e.g. C:)
        return "/" + "/".join(parts)
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


def enforce_pipeline_reentry(paths, working_directories):
    repo = repository_root()
    state = repo / ".project" / "STATE.md"
    if not os.path.lexists(state):
        return
    control_roots = repository_control_roots(repo)
    kinds = [
        target_kind(path, working_directories, repo, control_roots) for path in paths
    ]
    if "protected" in kinds:
        deny(CONTROL_FILE_REASON)
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


def path_in_archive(path, working_directories=()):
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
            if in_archive(resolved.as_posix()) or contains_existing_archive(
                resolved, working_directories
            ):
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
    if not operands or operands[-1] == "-":
        raise ValueError("directory change cannot be validated")
    return operands[-1]


def command_references_archive(tokens, working_directories):
    current_directories = list(working_directories)
    for segment in command_segments(tokens):
        if any(path_in_archive(token, current_directories) for token in segment):
            return True
        wrapped = wrapped_command_tokens(segment)
        if wrapped is not None and command_references_archive(
            wrapped, current_directories
        ):
            return True
        invocation = command_invocation(segment)
        if invocation is None:
            continue
        command, arguments = invocation
        if command == "popd":
            raise ValueError("directory stack changes cannot be validated")
        if command not in DIRECTORY_CHANGE_COMMANDS:
            continue
        target = directory_change_target(arguments)
        if SHELL_PARAMETER_SYNTAX.search(target):
            raise ValueError("directory change cannot be validated")
        if is_absolute_path(target):
            current_directories = [target]
        else:
            bases = current_directories or [""]
            current_directories = [f"{base}/{target}" for base in bases]
    return False


def environment_parameter_value(match, assignments):
    name = match.group(1) or match.group(2)
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
        for token in segment:
            if not SHELL_ASSIGNMENT_PATTERN.match(token):
                break
            name, value = token.split("=", 1)
            values[name] = expand_environment_parameters(value, values)
    return values


def unresolved_archive_expansion(command, tokens, working_directories):
    expanded = expand_environment_parameters(command, shell_assignment_values(tokens))
    if ARCHIVE_REFERENCE.search(expanded):
        return True
    if SHELL_PARAMETER_SYNTAX.search(expanded) or CMD_PARAMETER_SYNTAX.search(
        expanded
    ):
        return True
    return False


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
    if "\n" in command or "\r" in command:
        raise ValueError("shell command contains a line separator")
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|;&()<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    if not tokens:
        raise ValueError("shell command is empty")
    return tokens


def command_segments(tokens):
    segment = []
    for token in tokens:
        if token and set(token) <= set("|;&()"):
            if segment:
                yield segment
                segment = []
        else:
            segment.append(token)
    if segment:
        yield segment


def validate_shell_assignment(assignment):
    name = assignment.partition("=")[0].casefold()
    if name in {"home", "xdg_config_home"} or name.startswith("git_"):
        raise ValueError("Git configuration environment cannot be validated")


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
                    raise ValueError("env working directory cannot be validated")
                index += 1
                if "=" not in token:
                    if index >= len(segment):
                        raise ValueError("env option lacks a value")
                    index += 1
                continue
            if token.startswith("-"):
                raise ValueError("env invocation cannot be validated")
            break
    if index >= len(segment):
        return None
    executable = segment[index].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if SHELL_PARAMETER_SYNTAX.search(executable):
        raise ValueError("shell executable cannot be validated")
    if executable in SHELL_CONTROL_WORDS:
        raise ValueError("shell control syntax cannot be validated")
    if executable in {"find", "find.exe"} and any(
        argument.casefold() in FIND_EXECUTION_ACTIONS
        for argument in segment[index + 1:]
    ):
        raise ValueError("find execution action cannot be validated")
    if executable in UNVALIDATED_EXECUTION_COMMANDS:
        raise ValueError("shell execution command cannot be validated")
    return executable, segment[index + 1:]


def git_command(segment):
    invocation = command_invocation(segment)
    if invocation is None:
        return None
    executable, arguments = invocation
    if executable not in {"git", "git.exe"}:
        return None
    if any(SHELL_PARAMETER_SYNTAX.search(argument) for argument in arguments):
        raise ValueError("git invocation cannot be validated")
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
                raise ValueError("git global option lacks a value")
            value = arguments[index]
            index += 1
        if option in {"-c", "--config-env"}:
            config_key = str(value).split("=", 1)[0].casefold()
            if config_key.startswith("alias."):
                raise ValueError("git alias configuration cannot be validated")
            if config_key == "clean.requireforce":
                raise ValueError("git clean safety configuration cannot be validated")
        if option in GIT_GLOBAL_OPTIONS_WITH_VALUES:
            git_options.extend((option, str(value)))
    if index >= len(arguments):
        return None
    return arguments[index].casefold(), arguments[index + 1:], git_options


def wrapped_command_tokens(segment):
    invocation = command_invocation(segment)
    if invocation is None:
        return None
    executable, arguments = invocation
    if executable in COMMAND_WRAPPERS:
        if executable == "command" and arguments[:1] == ["-p"]:
            arguments = arguments[1:]
        if not arguments or arguments[0].startswith("-"):
            raise ValueError("command wrapper cannot be validated")
        return arguments
    if executable in POSIX_SHELL_WRAPPERS:
        for index, argument in enumerate(arguments):
            if (
                argument.startswith("-")
                and not argument.startswith("--")
                and "c" in argument[1:]
            ):
                if index + 1 >= len(arguments):
                    raise ValueError("shell wrapper lacks command payload")
                return shell_tokens(arguments[index + 1])
        raise ValueError("shell wrapper cannot be validated")
    if executable in POWERSHELL_WRAPPERS or executable in {"cmd", "cmd.exe"}:
        switches = {"-c", "-command", "/c", "/k"}
        for index, argument in enumerate(arguments):
            if argument.casefold() in switches:
                if index + 1 >= len(arguments):
                    raise ValueError("shell wrapper lacks command payload")
                payload = arguments[index + 1:]
                if executable in {"cmd", "cmd.exe"}:
                    payload = [
                        expand_environment_parameters(argument)
                        for argument in payload
                    ]
                if len(payload) == 1:
                    return shell_tokens(payload[0])
                return payload
        raise ValueError("shell wrapper cannot be validated")
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
                raise ValueError("git alias configuration cannot be validated")
        alias = git_alias(command, git_options)
        if alias is not None:
            if command in resolved_aliases:
                raise ValueError("recursive git alias cannot be validated")
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
        if command == "update-ref":
            if update_ref_deletes(arguments):
                return GIT_REASONS[command]
    return None


def archive_command_is_read_only(command, tokens, archive_context=False):
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
    if tokens[1].casefold() not in ARCHIVE_READ_GIT_COMMANDS:
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
    collect(event, paths, working_directories, commands, patch_payloads)
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
        path_in_archive(path) for path in working_directories
    )
    if archive_working_directory and not commands and not read_tool:
        deny(ARCHIVE_REASON)
    for command, command_working_directories in commands:
        if SHELL_EXPANSION_SYNTAX.search(command):
            raise ValueError("dynamic shell execution cannot be validated")
        tokens = shell_tokens(command)
        archive_context = (
            any(path_in_archive(path) for path in command_working_directories)
            or bool(ARCHIVE_REFERENCE.search(command))
            or command_references_archive(tokens, command_working_directories)
            or unresolved_archive_expansion(
                command, tokens, command_working_directories
            )
        )
        if not archive_command_is_read_only(command, tokens, archive_context):
            deny(ARCHIVE_REASON)
        reason = destructive_git_reason(tokens)
        if reason is not None:
            deny(reason)


def main():
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("hook event must be an object")
        evaluate(event)
    except SystemExit:
        raise
    except Exception:
        deny(INVALID_INPUT_REASON)


if __name__ == "__main__":
    main()
