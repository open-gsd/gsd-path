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
Any internal failure allows: the guard must never break a host.
"""

import json
import re
import sys

PATH_KEYS = frozenset(
    {"file_path", "filepath", "path", "file", "notebook_path", "target_file"}
)
COMMAND_KEYS = frozenset({"command", "cmd", "script"})
WRITE_TOOLS = re.compile(r"edit|write|patch|create|delete|save|apply", re.IGNORECASE)

ARCHIVE_REASON = (
    "committed GSD Path archives under .project/archive/ are read-only; "
    "only the bundled archive helper may write there during a ship transaction"
)
# Stay inside one shell command segment so `git status && rm x` cannot
# join tokens across `|`, `;`, or `&`.
SEGMENT = r"[^|;&]*"
COMMAND_RULES = (
    (
        re.compile(rf"\bgit\b{SEGMENT}\breset\b{SEGMENT}\s--hard\b"),
        "git reset --hard discards work the build recovery protocol needs",
    ),
    (
        re.compile(rf"\bgit\b{SEGMENT}\bclean\b{SEGMENT}(\s-[A-Za-z]*f|\s--force\b)"),
        "git clean -f deletes untracked evidence and retained task worktrees",
    ),
    (
        re.compile(rf"\bgit\b{SEGMENT}\bpush\b{SEGMENT}(\s--force(-with-lease)?\b|\s-f\b)"),
        "force pushes rewrite build-branch history the pipeline resumes from",
    ),
    (
        re.compile(rf"\bgit\b{SEGMENT}\bbranch\b{SEGMENT}\s-D\b"),
        "git branch -D destroys task branches the recovery protocol inspects",
    ),
    (
        re.compile(rf"\b(rm|rmdir|mv)\b{SEGMENT}\.project/archive"),
        ARCHIVE_REASON,
    ),
    (
        re.compile(r">>?\s*\S*\.project/archive"),
        ARCHIVE_REASON,
    ),
)


def collect(node, paths, commands):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                lowered = key.lower()
                if lowered in PATH_KEYS:
                    paths.append(value)
                elif lowered in COMMAND_KEYS:
                    commands.append(value)
            else:
                collect(value, paths, commands)
    elif isinstance(node, list):
        for value in node:
            collect(value, paths, commands)


def in_archive(path):
    normalized = "/" + path.replace("\\", "/").strip("/") + "/"
    return "/.project/archive/" in normalized


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


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(event, dict):
        return
    tool = str(
        event.get("tool_name") or event.get("toolName") or event.get("tool") or ""
    )
    paths, commands = [], []
    collect(event, paths, commands)
    if WRITE_TOOLS.search(tool):
        for path in paths:
            if in_archive(path):
                deny(ARCHIVE_REASON)
    for command in commands:
        for pattern, reason in COMMAND_RULES:
            if pattern.search(command):
                deny(reason)


if __name__ == "__main__":
    main()
