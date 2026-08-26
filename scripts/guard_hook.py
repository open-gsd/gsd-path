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
import re
import shlex
import sys
from pathlib import PurePosixPath

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
TOOL_TOKEN_PATTERN = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
SHELL_ASSIGNMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

ARCHIVE_REASON = (
    "committed GSD Path archives under .project/archive/ are read-only; "
    "only the bundled archive helper may write there during a ship transaction"
)
ARCHIVE_MARKER = ".project/archive"
INVALID_INPUT_REASON = "GSD Path guard could not validate the tool request"
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
SHELL_VARIABLE_SYNTAX = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[^}\r\n]+\})")
GIT_REASONS = {
    "reset": "git reset --hard discards work the build recovery protocol needs",
    "clean": "git clean -f deletes untracked evidence and retained task worktrees",
    "push": "force pushes rewrite build-branch history the pipeline resumes from",
    "branch": "git branch -D destroys task branches the recovery protocol inspects",
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


def collect(node, paths, working_directories, commands):
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
            elif isinstance(value, list):
                # Argv-style values ({"command": ["bash", "-lc", "..."]})
                # must be inspected like their joined string form.
                strings = [item for item in value if isinstance(item, str)]
                if strings and lowered in PATH_KEYS:
                    paths.extend(strings)
                elif strings and lowered in WORKING_DIRECTORY_KEYS:
                    working_directories.extend(strings)
                elif strings and lowered in COMMAND_KEYS:
                    commands.append(" ".join(strings))
                collect(value, paths, working_directories, commands)
            else:
                collect(value, paths, working_directories, commands)
    elif isinstance(node, list):
        for value in node:
            collect(value, paths, working_directories, commands)


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


def path_in_archive(path, working_directories=()):
    for value in path_values(path):
        if in_archive(value) or expansion_can_match_archive(value):
            return True
        if is_absolute_path(value):
            continue
        for working_directory in working_directories:
            resolved = f"{working_directory}/{value}"
            if in_archive(resolved) or expansion_can_match_archive(resolved):
                return True
    return False


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
        if invocation is None or invocation[0] != "cd":
            continue
        operands = [
            argument
            for argument in invocation[1]
            if argument != "--" and not argument.startswith("-")
        ]
        if not operands:
            continue
        target = operands[-1]
        if is_absolute_path(target):
            current_directories = [target]
        else:
            bases = current_directories or [""]
            current_directories = [f"{base}/{target}" for base in bases]
    return False


def unresolved_archive_expansion(command, working_directories):
    if not (
        SHELL_EXPANSION_SYNTAX.search(command)
        or SHELL_VARIABLE_SYNTAX.search(command)
    ):
        return False
    lowered = command.replace("\\", "/").casefold()
    return (
        ".project" in lowered
        or "archive" in lowered
        or any(
            "/.project" in normalize_posix(path).casefold()
            for path in working_directories
        )
    )


def patch_paths(payload):
    for match in PATCH_PATH_PATTERN.finditer(payload):
        yield (match.group(1) or match.group(2)).strip()


def shell_tokens(command):
    if "\n" in command or "\r" in command:
        raise ValueError("shell command contains a line separator")
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|;&()")
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


def command_invocation(segment):
    index = 0
    while index < len(segment) and SHELL_ASSIGNMENT_PATTERN.match(segment[index]):
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
                index += 1
                continue
            option = token.split("=", 1)[0]
            if option in ENV_OPTIONS_WITHOUT_VALUES:
                index += 1
                continue
            if option in ENV_OPTIONS_WITH_VALUES:
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
    if SHELL_VARIABLE_SYNTAX.search(executable):
        raise ValueError("shell executable cannot be validated")
    return executable, segment[index + 1:]


def git_command(segment):
    invocation = command_invocation(segment)
    if invocation is None:
        return None
    executable, arguments = invocation
    if executable not in {"git", "git.exe"}:
        return None
    if any(SHELL_VARIABLE_SYNTAX.search(argument) for argument in arguments):
        raise ValueError("git invocation cannot be validated")
    index = 0
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
        if option in {"-c", "--config-env"} and str(value).casefold().startswith(
            "alias."
        ):
            raise ValueError("git alias configuration cannot be validated")
    if index >= len(arguments):
        return None
    return arguments[index].casefold(), arguments[index + 1:]


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
            if argument.startswith("-") and "c" in argument[1:]:
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
                return shell_tokens(arguments[index + 1])
        raise ValueError("shell wrapper cannot be validated")
    return None


def has_short_option(arguments, option):
    return any(
        argument.startswith("-")
        and not argument.startswith("--")
        and option in argument[1:]
        for argument in arguments
    )


def destructive_git_reason(tokens):
    for segment in command_segments(tokens):
        wrapped = wrapped_command_tokens(segment)
        if wrapped is not None:
            reason = destructive_git_reason(wrapped)
            if reason is not None:
                return reason
        invocation = git_command(segment)
        if invocation is None:
            continue
        command, arguments = invocation
        if command == "reset" and "--hard" in arguments:
            return GIT_REASONS[command]
        if command == "clean":
            force = "--force" in arguments or has_short_option(arguments, "f")
            if force:
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
    return None


def archive_command_is_read_only(command, tokens, archive_context=False):
    if archive_context and (
        AMBIGUOUS_SHELL_SYNTAX.search(command)
        or SHELL_VARIABLE_SYNTAX.search(command)
    ):
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
    paths, working_directories, commands = [], [], []
    collect(event, paths, working_directories, commands)
    patch_payloads = []
    if is_patch_tool(tool):
        patch_payloads.extend(commands)
        raw_input = event.get("tool_input", event.get("toolInput"))
        if isinstance(raw_input, str):
            patch_payloads.append(raw_input)
        commands = []
    read_tool = is_read_tool(tool)
    if not read_tool:
        for path in paths:
            if path_in_archive(path, working_directories):
                deny(ARCHIVE_REASON)
        for payload in patch_payloads:
            for path in patch_paths(payload):
                if path_in_archive(path, working_directories):
                    deny(ARCHIVE_REASON)
    archive_working_directory = any(in_archive(path) for path in working_directories)
    if archive_working_directory and not commands and not read_tool:
        deny(ARCHIVE_REASON)
    for command in commands:
        tokens = shell_tokens(command)
        archive_context = (
            archive_working_directory
            or bool(ARCHIVE_REFERENCE.search(command))
            or command_references_archive(tokens, working_directories)
            or unresolved_archive_expansion(command, working_directories)
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
