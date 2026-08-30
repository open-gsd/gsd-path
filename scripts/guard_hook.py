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
# A tool skips path checks only when its name carries a read-only verb and
# no write-capable verb: `get_and_write` must still be path-checked.
READ_VERBS = frozenset({"read", "grep", "search", "view", "list", "get", "cat"})
WRITE_VERBS = frozenset(
    {
        "write",
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


def collect(node, paths, working_directories, commands, patch_payloads):
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = key.lower()
            if isinstance(value, str):
                if lowered in PATH_KEYS:
                    paths.append(value)
                elif lowered in WORKING_DIRECTORY_KEYS:
                    working_directories.append(value)
                elif lowered in COMMAND_KEYS:
                    commands.append(value)
                elif lowered in PATCH_KEYS:
                    patch_payloads.append(value)
            elif isinstance(value, list):
                strings = [item for item in value if isinstance(item, str)]
                if strings and lowered in PATH_KEYS:
                    paths.extend(strings)
                elif strings and lowered in WORKING_DIRECTORY_KEYS:
                    working_directories.extend(strings)
                elif lowered in COMMAND_KEYS:
                    if not strings or len(strings) != len(value):
                        raise ValueError("command argv cannot be validated")
                    commands.append(shlex.join(strings))
                elif strings and lowered in PATCH_KEYS:
                    patch_payloads.extend(strings)
                collect(value, paths, working_directories, commands, patch_payloads)
            else:
                collect(value, paths, working_directories, commands, patch_payloads)
    elif isinstance(node, list):
        for value in node:
            collect(value, paths, working_directories, commands, patch_payloads)


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


def is_direct_write_tool(tool, has_file_targets=False):
    tokens = tool_tokens(tool)
    if tokens & DIRECT_FILE_WRITE_VERBS:
        return (
            len(tokens) == 1
            or bool(tokens & FILE_TARGET_TOKENS)
            or has_file_targets
        )
    if tokens == {"create"}:
        return True
    return bool((tokens & AMBIGUOUS_WRITE_VERBS) and (tokens & FILE_TARGET_TOKENS))


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
        raise ValueError("repository root cannot be resolved")
    return Path(result.stdout.strip()).resolve()


def project_status(repo):
    script_root = Path(__file__).resolve().parent
    candidates = (
        script_root / "runtime" / "pipeline_state.py",
        script_root / "pipeline_state.py",
    )
    script = next((path for path in candidates if path.is_file()), None)
    if script is None:
        raise ValueError("project status runtime is unavailable")
    result = subprocess.run(
        [sys.executable, "-B", str(script), "status", "--repo", str(repo)],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("project status failed")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict) or payload.get("schema") != "gsd-path/status/v1":
        raise ValueError("project status returned an invalid payload")
    return payload


def pipeline_control_path(path, working_directories, repo):
    repo = repo.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        base = Path(working_directories[0]) if working_directories else repo
        if not base.is_absolute():
            base = repo / base
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    return any(
        resolved == root or root in resolved.parents
        for root in (repo / ".project", repo / ".gsd-path")
    )


def enforce_pipeline_reentry(paths, working_directories):
    repo = repository_root()
    state = repo / ".project" / "STATE.md"
    if not os.path.lexists(state):
        return
    try:
        status = project_status(repo)
    except (OSError, ValueError, json.JSONDecodeError):
        deny(REENTRY_FAILURE_REASON)
    route = status.get("route")
    state_data = status.get("state") if isinstance(status.get("state"), dict) else {}
    if (
        state_data.get("phase") == "build"
        and isinstance(route, dict)
        and route.get("action") == "run-phase"
        and route.get("phase") == "build"
    ):
        return
    if all(pipeline_control_path(path, working_directories, repo) for path in paths):
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
    if is_patch_tool(tool):
        patch_payloads.extend(commands)
        raw_input = event.get("tool_input", event.get("toolInput"))
        if isinstance(raw_input, str):
            patch_payloads.append(raw_input)
        commands = []
    read_tool = is_read_tool(tool)
    extracted_patch_paths = []
    if not read_tool:
        for path in paths:
            if path_in_archive(path, working_directories):
                deny(ARCHIVE_REASON)
        extracted_patch_paths = [
            path for payload in patch_payloads for path in patch_paths(payload)
        ]
        if is_patch_tool(tool) and not paths and not extracted_patch_paths:
            raise ValueError("patch targets cannot be validated")
        for path in extracted_patch_paths:
            if path_in_archive(path, working_directories):
                deny(ARCHIVE_REASON)
        if is_direct_write_tool(tool, bool(paths or extracted_patch_paths)):
            write_paths = [*paths, *extracted_patch_paths]
            if not write_paths:
                raise ValueError("write targets cannot be validated")
            enforce_pipeline_reentry(write_paths, working_directories)
    archive_working_directory = any(
        path_in_archive(path) for path in working_directories
    )
    if archive_working_directory and not commands and not read_tool:
        deny(ARCHIVE_REASON)
    for command in commands:
        if SHELL_EXPANSION_SYNTAX.search(command):
            raise ValueError("dynamic shell execution cannot be validated")
        tokens = shell_tokens(command)
        archive_context = (
            archive_working_directory
            or bool(ARCHIVE_REFERENCE.search(command))
            or command_references_archive(tokens, working_directories)
            or unresolved_archive_expansion(command, tokens, working_directories)
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
