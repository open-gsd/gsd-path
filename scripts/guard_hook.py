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

ARCHIVE_REASON = (
    "committed GSD Path archives under .project/archive/ are read-only; "
    "only the bundled archive helper may write there during a ship transaction"
)
ARCHIVE_MARKER = ".project/archive"
INVALID_INPUT_REASON = "GSD Path guard could not validate the tool request"
# Stay inside one shell command segment so `git status && rm x` cannot
# join tokens across `|`, `;`, or `&`.
SEGMENT = r"[^|;&]*"
# Program names and the archive path match case-insensitively: on APFS and
# Windows `RM .Project/Archive` works. Flags stay case-sensitive so a safe
# `git branch -d` is never confused with `-D`.
GIT = r"\b(?i:git)\b"
ARCHIVE_PATH = r"(?i:\.project/archive)"
COMMAND_RULES = (
    (
        re.compile(rf"{GIT}{SEGMENT}\breset\b{SEGMENT}\s--hard\b"),
        "git reset --hard discards work the build recovery protocol needs",
    ),
    (
        re.compile(rf"{GIT}{SEGMENT}\bclean\b{SEGMENT}(\s-[A-Za-z]*f|\s--force\b)"),
        "git clean -f deletes untracked evidence and retained task worktrees",
    ),
    (
        re.compile(rf"{GIT}{SEGMENT}\bpush\b{SEGMENT}(\s--force(-with-lease)?\b|\s-f\b)"),
        "force pushes rewrite build-branch history the pipeline resumes from",
    ),
    (
        re.compile(rf"{GIT}{SEGMENT}\bbranch\b{SEGMENT}\s-D\b"),
        "git branch -D destroys task branches the recovery protocol inspects",
    ),
    (
        re.compile(rf"\b(?i:rm|rmdir|mv|cp|tee)\b{SEGMENT}{ARCHIVE_PATH}"),
        ARCHIVE_REASON,
    ),
    (
        re.compile(rf"{GIT}{SEGMENT}\bcheckout\b{SEGMENT}{ARCHIVE_PATH}"),
        ARCHIVE_REASON,
    ),
    (
        re.compile(rf"{GIT}{SEGMENT}\brestore\b{SEGMENT}{ARCHIVE_PATH}"),
        ARCHIVE_REASON,
    ),
    (
        re.compile(rf">>?\s*\S*{ARCHIVE_PATH}"),
        ARCHIVE_REASON,
    ),
)


def collect(node, paths, commands):
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = key.lower()
            if isinstance(value, str):
                if lowered in PATH_KEYS:
                    paths.append(value)
                elif lowered in COMMAND_KEYS:
                    commands.append(value)
            elif isinstance(value, list):
                # Argv-style values ({"command": ["bash", "-lc", "..."]})
                # must be inspected like their joined string form.
                strings = [item for item in value if isinstance(item, str)]
                if strings and lowered in PATH_KEYS:
                    paths.extend(strings)
                elif strings and lowered in COMMAND_KEYS:
                    commands.append(" ".join(strings))
                collect(value, paths, commands)
            else:
                collect(value, paths, commands)
    elif isinstance(node, list):
        for value in node:
            collect(value, paths, commands)


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


def is_read_tool(tool):
    tokens = {token.casefold() for token in TOOL_TOKEN_PATTERN.findall(tool)}
    return bool(tokens & READ_VERBS) and not tokens & WRITE_VERBS


def in_archive(path):
    # Casefold: APFS and Windows resolve `.Project/Archive` to the archive.
    normalized = normalize_posix(path).casefold()
    marker = "/" + ARCHIVE_MARKER
    if marker not in normalized:
        return False
    idx = normalized.index(marker)
    suffix = normalized[idx + len(marker):]
    return suffix == "" or suffix.startswith("/")


def patch_paths(command):
    for match in PATCH_PATH_PATTERN.finditer(command):
        yield (match.group(1) or match.group(2)).strip()


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
    paths, commands = [], []
    collect(event, paths, commands)
    if not is_read_tool(tool):
        for path in paths:
            if in_archive(path):
                deny(ARCHIVE_REASON)
        for command in commands:
            for path in patch_paths(command):
                if in_archive(path):
                    deny(ARCHIVE_REASON)
    for command in commands:
        for pattern, reason in COMMAND_RULES:
            if pattern.search(command):
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
