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
AMBIGUOUS_SHELL_SYNTAX = re.compile(r"[\r\n|;&<>`]|\$\(|@\(")
GIT_REASONS = {
    "reset": "git reset --hard discards work the build recovery protocol needs",
    "clean": "git clean -f deletes untracked evidence and retained task worktrees",
    "push": "force pushes rewrite build-branch history the pipeline resumes from",
    "branch": "git branch -D destroys task branches the recovery protocol inspects",
}
GIT_GLOBAL_OPTIONS_WITH_VALUES = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
)


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


def path_values(value):
    yield value
    if value.startswith("-") and "=" in value:
        yield value.split("=", 1)[1]


def is_absolute_path(path):
    normalized = path.replace("\\", "/")
    return normalized.startswith("/") or bool(re.match(r"^[A-Za-z]:/", normalized))


def path_in_archive(path, working_directories=()):
    for value in path_values(path):
        if in_archive(value):
            return True
        if is_absolute_path(value):
            continue
        for working_directory in working_directories:
            if in_archive(f"{working_directory}/{value}"):
                return True
    return False


def command_references_archive(tokens, working_directories):
    return any(path_in_archive(token, working_directories) for token in tokens)


def patch_paths(payload):
    for match in PATCH_PATH_PATTERN.finditer(payload):
        yield (match.group(1) or match.group(2)).strip()


def shell_tokens(command):
    if "\n" in command or "\r" in command:
        raise ValueError("shell command contains a line separator")
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|;&")
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    if not tokens:
        raise ValueError("shell command is empty")
    return tokens


def command_segments(tokens):
    segment = []
    for token in tokens:
        if token and set(token) <= set("|;&"):
            if segment:
                yield segment
                segment = []
        else:
            segment.append(token)
    if segment:
        yield segment


def git_command(segment):
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
            if "=" in token and not token.startswith("="):
                index += 1
                continue
            if token in {"-i", "--ignore-environment"}:
                index += 1
                continue
            break
    if index >= len(segment):
        return None
    executable = segment[index].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if executable not in {"git", "git.exe"}:
        return None
    index += 1
    while index < len(segment) and segment[index].startswith("-"):
        option = segment[index].split("=", 1)[0]
        index += 1
        if option in GIT_GLOBAL_OPTIONS_WITH_VALUES and "=" not in segment[index - 1]:
            index += 1
    if index >= len(segment):
        return None
    return segment[index].casefold(), segment[index + 1:]


def has_short_option(arguments, option):
    return any(
        argument.startswith("-")
        and not argument.startswith("--")
        and option in argument[1:]
        for argument in arguments
    )


def destructive_git_reason(tokens):
    for segment in command_segments(tokens):
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
    if not archive_context:
        return True
    if AMBIGUOUS_SHELL_SYNTAX.search(command):
        return False
    executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
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
    if not is_read_tool(tool):
        for path in paths:
            if path_in_archive(path, working_directories):
                deny(ARCHIVE_REASON)
        for payload in patch_payloads:
            for path in patch_paths(payload):
                if path_in_archive(path, working_directories):
                    deny(ARCHIVE_REASON)
    archive_working_directory = any(in_archive(path) for path in working_directories)
    if archive_working_directory and not commands:
        deny(ARCHIVE_REASON)
    for command in commands:
        tokens = shell_tokens(command)
        archive_context = (
            archive_working_directory
            or bool(ARCHIVE_REFERENCE.search(command))
            or command_references_archive(tokens, working_directories)
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
