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
ARCHIVE_UNPROVEN_READ_REASON = (
    "commands run in archive context must be provably read-only; only "
    "recognized read commands and the bundled pipeline helpers may run there"
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
# Options whose value git writes to or runs as a command: one unknown word is
# already enough, so a parameter in or after them is never accepted.
GIT_PARAMETER_DENIED_OPTIONS = GIT_READ_WRITE_OPTIONS | {
    "--upload-pack", "--receive-pack", "--exec", "-c", "--config-env",
}


# -c/--config keys whose value git executes as a program. A literal value is
# as dangerous as a parameter here: git -c core.fsmonitor=<path> status runs
# the configured program while the subcommand stays nominally read-only.
GIT_EXECUTED_CONFIG_KEYS = frozenset({
    "core.fsmonitor", "core.editor", "sequence.editor", "core.sshcommand",
    "core.askpass", "core.pager", "core.gitproxy", "interactive.difffilter",
})
GIT_EXECUTED_CONFIG_SECTIONS = {
    "filter": (".clean", ".smudge", ".process", ".command"),
    "diff": (".command", ".textconv", ".external"),
    "merge": (".driver",),
    "remote": (".uploadpack", ".receivepack"),
    "gpg": (".program",),
    "credential": (".helper",),
    "pager": ("",),
}
# Keys whose value is a path or URL git loads code through: an included file
# can set every key above, and a rewritten URL can retarget the transport.
# No value of these is a disabling form.
GIT_LOADED_CONFIG_KEYS = frozenset({"core.hookspath", "include.path"})
GIT_LOADED_CONFIG_SECTIONS = {
    "includeif": (".path",),
    "url": (".insteadof", ".pushinsteadof"),
}
GIT_CONFIG_DISABLING_VALUES = frozenset({"", "false"})


def config_key_in(key, keys, sections):
    if key in keys:
        return True
    section, _, remainder = key.partition(".")
    return bool(remainder) and key.endswith(tuple(sections.get(section, ())))


def loaded_config_key(key):
    """Whether a config key's value is a path or URL git loads code through."""
    return config_key_in(key, GIT_LOADED_CONFIG_KEYS, GIT_LOADED_CONFIG_SECTIONS)


def executed_config_key(key):
    """Whether a config key's value is a program git runs or code it loads."""
    return loaded_config_key(key) or config_key_in(
        key, GIT_EXECUTED_CONFIG_KEYS, GIT_EXECUTED_CONFIG_SECTIONS
    )


# Real read-only git options that are a strict prefix of a denied option name.
GIT_SAFE_PREFIX_OPTIONS = frozenset({"--text"})


def git_option_in(token, options):
    """Whether a token names one of the options, by full name or any long-option prefix.

    git accepts each unique prefix of a long option; matching every prefix is
    stricter than git and so only fails closed. A prefix that is itself the
    exact name of a read-only option is that option, not an abbreviation.
    """
    name = token.split("=", 1)[0]
    if name in GIT_SAFE_PREFIX_OPTIONS and name not in options:
        return False
    if name.startswith("--") and len(name) > 2:
        return any(option.startswith(name) for option in options)
    return name in options
GIT_CONFIG_READ_MODES = frozenset({
    "--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color",
    "--get-colorbool", "-l", "--list", "--unset", "--unset-all",
})
GIT_CONFIG_READ_SUBCOMMANDS = frozenset({"get", "unset", "list"})
GIT_CONFIG_DENIED_MODES = frozenset({"--rename-section", "--remove-section", "--edit"})
GIT_CONFIG_DENIED_SUBCOMMANDS = frozenset({"rename-section", "remove-section", "edit"})
GIT_CONFIG_VALUE_OPTIONS = frozenset({
    "--file", "--blob", "--type", "--default", "--comment", "--value", "--url",
})
GIT_CONFIG_EDIT_SHORT_OPTION = re.compile(r"-[A-Za-z]*e[A-Za-z]*")
# An unquoted word the shell can turn into several arguments: a glob, or a
# brace list or range.
PLAIN_QUOTED_SEGMENT = re.compile(r"'[^']*'|\"[^\"]*\"")
ANSI_QUOTE_START = re.compile(r"\$['\"]")
GIT_CONFIG_EXPANDING_WORD = re.compile(r"[*?\[]|\{.*(?:,|\.\.)")


def denied_git_config_argument(arguments):
    """The git config argument that persists or runs a program git executes.

    A section rename can carry a key into an executed section and --edit runs
    the editor, so both are denied outright. Otherwise only a set denies: an
    executed key with a value operand after it and no read or unset mode.
    Only a trailing redirection is dropped: the operator, its target and a
    file descriptor digit written against it. A separate digit (5 >file) and a
    quoted operator are operands.
    """
    arguments = list(arguments)
    while (
        len(arguments) >= 2
        and getattr(arguments[-2], "redirection", False)
        and not arguments[-2].isdigit()
    ):
        del arguments[-2:]
        if (
            arguments
            and getattr(arguments[-1], "redirection", False)
            and arguments[-1].isdigit()
        ):
            del arguments[-1]
    separator = arguments.index("--") if "--" in arguments else len(arguments)
    options = arguments[:separator]
    for token in options:
        if (
            git_option_in(token, GIT_CONFIG_DENIED_MODES)
            or GIT_CONFIG_EDIT_SHORT_OPTION.fullmatch(token)
            or token.casefold() in GIT_CONFIG_DENIED_SUBCOMMANDS
        ):
            return token
    if options[:1] and options[0].casefold() in GIT_CONFIG_READ_SUBCOMMANDS:
        return None
    for position, token in enumerate(options):
        # A mode word that is the value of the option before it is no mode.
        if token in GIT_CONFIG_READ_MODES and not (
            position
            and (
                options[position - 1] == "-f"
                or git_option_in(options[position - 1], GIT_CONFIG_VALUE_OPTIONS)
            )
        ):
            return None
    operands = [
        token for token in options if not token.startswith("-")
    ] + arguments[separator + 1:]
    for token in operands[:-1]:
        if executed_config_key(token.casefold()):
            return token
    return None


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
ZSH_EXPANSION_FLAG_SYNTAX = re.compile(r"\$[=~^+]")
CMD_PARAMETER_SYNTAX = re.compile(
    r"%([A-Za-z_][A-Za-z0-9_]*)%|!([A-Za-z_][A-Za-z0-9_]*)!"
)
# The shell reassigns these on every cd, so a tracked value is stale.
SHELL_DIRECTORY_VARIABLES = frozenset({"PWD", "OLDPWD"})
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
    "update-ref-order": (
        "git update-ref deletion after another Git command can follow a symbolic "
        "ref that command changed; run it as its own command or add --no-deref"
    ),
    "branch-move": (
        "git branch -m renames a branch the pipeline resumes by name "
        "(STATE.branch); create a new branch instead"
    ),
    "update-ref": (
        "git update-ref on a Path-owned ref destroys or forges the trust the "
        "recovery protocol inspects"
    ),
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
# Programs that run the command in their arguments, with the options of each
# that take a separate value. The guard checks the command they run.
EXEC_PREFIX_VALUE_OPTIONS = {
    "nice": frozenset({"-n", "--adjustment"}),
    "nohup": frozenset(),
    "setsid": frozenset(),
    "stdbuf": frozenset({"-i", "-o", "-e", "--input", "--output", "--error"}),
    "sudo": frozenset({
        "-u", "-g", "-h", "-p", "-C", "-T", "-U", "-r", "-t",
        "--user", "--group", "--host", "--prompt", "--close-from",
        "--command-timeout", "--other-user", "--role", "--type",
    }),
    "time": frozenset({"-f", "--format"}),
    "timeout": frozenset({"-s", "-k", "--signal", "--kill-after"}),
    "watch": frozenset({"-n", "-q", "--interval", "--equexit"}),
}
# Runner options that write, edit or enter a file or directory by themselves.
EXEC_PREFIX_FILE_OPTIONS = {
    "sudo": frozenset({"-e", "-D", "-R", "--edit", "--chdir", "--chroot"}),
    "time": frozenset({"-o", "--output"}),
    "watch": frozenset({"-s", "--shotsdir"}),
}
# The short option letters of each runner that take no value.
EXEC_PREFIX_FLAG_LETTERS = {
    "nice": "",
    "nohup": "",
    "setsid": "cfw",
    "stdbuf": "",
    "sudo": "AbBEHiKklnNPSsVv",
    "time": "ahlpqvV",
    "timeout": "fpv",
    "watch": "bcCdegprtwx",
}
EXEC_PREFIX_INTERVAL_OPTIONS = frozenset({"-n", "--interval"})
RUNNER_DURATION = re.compile(
    r"(?:(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?|inf(?:inity)?)[smhd]?", re.IGNORECASE
)
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


def segment_directories(tokens, working_directories, contexts=None):
    """Yield each command segment with the working directories in effect for it."""
    current_directories = list(working_directories)
    for position, segment in enumerate(command_segments(tokens)):
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
        tracked = {}
        if contexts is not None and position < len(contexts):
            tracked = {
                name: value
                for name, value in contexts[position].items()
                if name not in SHELL_DIRECTORY_VARIABLES
            }
        expanded = expand_environment_parameters(target, tracked, tracked_only=True)
        # An unquoted empty expansion leaves no word: the shell changes to HOME.
        if (
            (target and not expanded)
            or SHELL_PARAMETER_SYNTAX.search(expanded)
            or CMD_PARAMETER_SYNTAX.search(expanded)
        ):
            raise ValueError(
                f"cd target {target} cannot be resolved by the guard; "
                "run that command first and cd to the literal result"
            )
        if (
            (SHELL_PARAMETER_SYNTAX.search(target) or CMD_PARAMETER_SYNTAX.search(target))
            and any(character.isspace() or character in "*?[]" for character in expanded)
        ):
            raise ValueError(
                f"cd target {target} may split or glob; pass a literal path"
            )
        if is_absolute_path(expanded):
            current_directories = [expanded]
        else:
            bases = current_directories or ["."]
            current_directories = [f"{base}/{expanded}" for base in bases]


def command_can_destroy_files(invocation):
    if invocation is None:
        return False
    executable, arguments = invocation
    executable = executable.removesuffix(".exe")
    return executable in DESTRUCTIVE_SHELL_COMMANDS or (
        executable == "find" and "-delete" in arguments
    )


def _deletion_overlaps(candidate, root):
    """Whether a recursive delete of `candidate` could remove `root`.

    A candidate inside the root deletes its contents, and a candidate that
    CONTAINS the root deletes it wholesale (`rm -r` of a parent directory), so
    both directions deny. Existing-path identity covers case variants that a
    lexical comparison misses on case-insensitive filesystems.
    """
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        pass
    try:
        root.relative_to(candidate)
        return True
    except ValueError:
        pass
    return _within_existing_root(candidate, root) or _within_existing_root(root, candidate)


def _strictly_inside(candidate, root):
    if candidate == root:
        return False
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return any(_same_existing_path(ancestor, root) for ancestor in candidate.parents)


def destructive_state_root_reason(operands, working_directories):
    """Why a destructive operand is pipeline state, or None when outside it.

    Delete restrictions cover the pipeline's state directories, not only the
    repository (#468): the guard's home tree, the configured worktree root,
    and every pinned workspace root sit outside any repository, so the path
    kinds alone would call them external. Unresolvable workspace state denies
    rather than guesses.
    """
    directories = working_directories or [os.getcwd()]
    commons = set()
    checkouts = set()
    for directory in directories:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--show-toplevel", "--git-common-dir"],
            capture_output=True, encoding="utf-8", errors="replace", check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
        lines = result.stdout.splitlines()
        if result.returncode == 0 and len(lines) == 2:
            checkouts.add(Path(lines[0]).resolve(strict=False))
            common = Path(lines[1])
            if not common.is_absolute():
                common = Path(directory) / common
            commons.add(common.resolve(strict=False))
    try:
        roots = _workspace_roots_for_commons(commons)
    except ValueError as error:
        return f"pipeline workspace state cannot be resolved: {error}"
    for operand in operands:
        for candidate in target_paths(operand, directories, Path(os.getcwd())):
            for root in roots:
                # A managed worktree under a state root is the agent's own
                # checkout; deletes inside it are ordinary product work.
                if _deletion_overlaps(candidate, root) and not any(
                    _strictly_inside(candidate, checkout) and _strictly_inside(checkout, root)
                    for checkout in checkouts
                ):
                    return f"destructive target is pipeline state: {operand}"
    return None


def _closed_repo_root(working_directories):
    """The closed-milestone repository for these working directories, if any."""
    for directory in working_directories or [os.getcwd()]:
        root = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
            capture_output=True, encoding="utf-8", errors="replace", check=False,
        )
        if root.returncode != 0:
            continue
        repo = Path(root.stdout.strip())
        if closed_milestone_reason(repo):
            return repo
    return None


def closed_destructive_scope_reason(arguments, working_directories):
    """Why a destructive command stays inside pipeline scope, or None outside it.

    A closed milestone accepts no new work, but a scratch file entirely outside
    the repository and every state root is no work (#468). The allowance needs
    every operand provably external to the closed repository — the path kinds
    check the lexical path, the symlink-resolved path, control aliases, and
    member checkouts — and the state-root check covers the directories that
    live outside the repository.
    """
    end = arguments.index("--") if "--" in arguments else len(arguments)
    operands = [
        argument for argument in arguments[:end] if argument and not argument.startswith("-")
    ] + [argument for argument in arguments[end + 1:] if argument]
    if not operands:
        return "destructive command names no target"
    repo = _closed_repo_root(working_directories)
    if repo is None:
        return "pipeline scope cannot be classified"
    control_roots = repository_control_roots(repo)
    try:
        import members  # the guard's runtime directory
        member_roots = [Path(member["checkout"]) for member in members.read_members(repo)]
    except Exception as error:
        return f"member scope cannot be resolved: {error}"
    for operand in operands:
        if target_kind(operand, working_directories, repo, control_roots) != "external":
            return f"destructive target stays inside the repository: {operand}"
        # A recursive delete of an ancestor removes the repository (and any
        # member checkout) even though the operand itself classifies external.
        for candidate in target_paths(operand, working_directories, repo):
            if _deletion_overlaps(candidate, repo.resolve()):
                return f"destructive target contains the repository: {operand}"
            for member_root in member_roots:
                if _deletion_overlaps(candidate, member_root.resolve(strict=False)):
                    return f"destructive target contains a member checkout: {operand}"
    return destructive_state_root_reason(operands, working_directories)


def literal_path(operand):
    if len(operand) >= 2 and operand[0] in "\"'" and operand[-1] == operand[0]:
        operand = operand[1:-1]
    # A space is safe here: the operand is one shlex unit, so it cannot carry a
    # second word; injection-relevant characters stay excluded.
    pattern = r"[A-Za-z0-9._/ -]+"
    if os.name == "nt":
        pattern = r"(?:[A-Za-z]:(?=[/\\]))?[A-Za-z0-9._/\\ -]+"
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
    # A here-document body survives tokenization only inside a wrapped payload
    # (bash -c '...'), where it is data, not commands; keep its text from
    # flipping the segment into archive context.
    def searchable(token):
        return strip_heredoc_bodies(token) if "\n" in token else token

    operands = [
        expand_environment_parameters(searchable(token), assignments)
        for token in segment
    ]
    if ancestors:
        resolved = command_invocation(operands)
        operands = [literal_destructive_operand(operand) for operand in resolved[1]]
    if any(path_in_archive(operand, directories, ancestors) for operand in operands):
        return True
    return unresolved_archive_expansion(
        " ".join(searchable(token) for token in segment), assignments
    )


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


def environment_parameter_value(match, assignments, tracked_only=False):
    name = match.group(1) or match.group(2)
    if name.startswith(SUBSTITUTION_PLACEHOLDER):
        return match.group(0)  # command substitution output is never resolved
    if name in assignments:
        return assignments[name]
    if tracked_only:
        return match.group(0)
    return os.environ.get(name, match.group(0))


def expand_environment_parameters(command, assignments=None, tracked_only=False):
    values = assignments or {}

    def substitute(match):
        return environment_parameter_value(match, values, tracked_only)

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
            # The same tracked expansion as segment_directories.
            target = expand_environment_parameters(
                directory_change_target(invocation[1]),
                {
                    name: value
                    for name, value in contexts[-1].items()
                    if name not in SHELL_DIRECTORY_VARIABLES
                },
                tracked_only=True,
            )
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
    segments = list(segment_directories(tokens, working_directories, contexts))
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


PARAMETER_MARKERS = frozenset("$%!")
SHELL_DESCRIPTOR_WORD = re.compile(r"[0-9]{2,}|\{\w+\}", re.ASCII)
SHELL_OPERATOR_PARTS = re.compile(
    r"[<>]\(|&>>?|<<<|<<|>>|>&|<&|<>|>\||[<>]|&&|\|\||\|&|[\s\S]"
)


class ShellToken(str):
    """A token that keeps, per parameter marker character, whether double quotes enclosed it.

    `redirection` is true for an unquoted redirection operator and for one
    ASCII file descriptor digit written against one (the 2 of 2>file, not of
    2 >file). zsh passes a longer or non-ASCII digit word on as an argument.
    `descriptor` is true for a longer digit word or a {name} word written
    against a redirection operator: bash reads it as a file descriptor, zsh
    as an argument.
    `body` holds the tokens of a process substitution on its operator token,
    once destructive_git_reason has folded them.
    `literal` is "bare" for a word written with no quote or escape, "quoted"
    for a word inside one pair of plain quotes, "mixed" for plain quoted and
    unquoted parts where no unquoted part can expand, and None when the shell
    may build the word in another way (escapes, an expanding unquoted part, a
    line continuation in the word or one that joins it to the next word).
    """

    double_quoted = ()
    redirection = False
    descriptor = False
    literal = None
    body = None


def double_quoted_markers(command):
    """Return, per parameter marker in order, whether plain double quotes enclose it.

    None means the command uses quoting outside the plain constructs this scan
    models (plain single quotes, plain double quotes, unquoted text), so no
    marker in it can be proven quoted.
    """
    flags = []
    quote = None
    comment = False
    braces = 0
    previous = " "
    index = 0
    while index < len(command):
        character = command[index]
        following = command[index + 1 : index + 2]
        if comment:
            if character in "\r\n":
                comment = False
            elif character in "'\"\\`":
                return None
        elif quote == "'":
            if character == "'":
                quote = None
        elif character == "\\":
            if following and following in PARAMETER_MARKERS:
                # The shell executes the escaped marker as literal text; the
                # token keeps the bare marker, so the pair is never provable.
                flags.append(False)
            previous = character
            index += 2
            continue
        elif character == "`" or (character == "$" and following == "("):
            return None
        elif character == "$" and following == "{":
            braces += 1
        elif character == "}" and braces:
            braces -= 1
        elif character in "'\"" and braces:
            return None
        elif character == '"':
            quote = None if quote else '"'
        elif quote is None:
            if character == "'":
                quote = "'"
            elif character == "$" and following and following in "'\"":
                return None
            elif character == "<" and following == "<":
                return None
            elif character == "#" and previous in " \t\r\n;&|()<>":
                comment = True
        if character in PARAMETER_MARKERS:
            flags.append(quote == '"' and not comment)
        previous = character
        index += 1
    return flags if quote is None and not braces else None


def zsh_expansion_flag(text):
    """Whether the text holds an unbraced zsh expansion flag ($=x, $~x, $^x, $+x).

    These match no parameter syntax, so without this check they never enter
    the parameter proof at all — while zsh word-splits them exactly like the
    forms the proof denies. Any other unmatched $ is inert literal text.
    """
    return ZSH_EXPANSION_FLAG_SYNTAX.search(text)


def parameters_double_quoted(token):
    """Whether every parameter in the token expands inside double quotes to one word.

    Only plain $name and ${name} qualify: flags, operators, subscripts,
    positional and special parameters can split even inside double quotes.
    A backslash-escaped marker stays one flag short of proven: the shell
    executes the literal text while the guard's token still shows the bare
    marker, so nothing about its expansion is provable.
    """
    flags = getattr(token, "double_quoted", ())
    positions = [
        index for index, character in enumerate(token) if character in PARAMETER_MARKERS
    ]
    if len(flags) != len(positions):
        return False
    quoted = dict(zip(positions, flags))
    plain = {
        match.start(): match.end() for match in NAMED_SHELL_PARAMETER_SYNTAX.finditer(token)
    }
    if any(
        character == "$" and index not in plain for index, character in enumerate(token)
    ) or any(token[end : end + 1] == "[" for end in plain.values()):
        return False
    return all(
        quoted[match.start()] and quoted.get(match.end() - 1, True)
        for syntax in (SHELL_PARAMETER_SYNTAX, CMD_PARAMETER_SYNTAX)
        for match in syntax.finditer(token)
    )


def shell_tokens(command, direct=True):
    """Tokenize a command; `direct` is False for a string that a second shell parses.

    Only a directly parsed command keeps quote flags: an outer shell expands
    parameters before the inner parse, so inner quotes prove nothing.
    """
    breaks = set()
    if LINE_CONTINUATION.search(command):
        mark = next(
            character for character in map(chr, range(0xE000, 0xF900))
            if character not in command
        )
        marked = strip_heredoc_bodies(
            LINE_CONTINUATION.sub(lambda match: match.group(1) + mark, command)
        )
        command = strip_heredoc_bodies(LINE_CONTINUATION.sub(r"\1 ", command))
        breaks = (
            {index for index, character in enumerate(marked) if character == mark}
            if marked.replace(mark, " ") == command
            else None
        )
    else:
        command = strip_heredoc_bodies(command)
    joins = set()
    for index in breaks or ():
        left, right = index - 1, index + 1
        while left >= 0 and marked[left] == mark:
            left -= 1
        while right < len(marked) and marked[right] == mark:
            right += 1
        if left >= 0 and marked[left].strip() and marked[right:right + 1].strip():
            joins.add(index)
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|;&()<>\n\r")
    lexer.whitespace = " \t"
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = []
    previous_end = 0
    try:
        for token in lexer:
            end = lexer.instream.tell() - len(lexer._pushback_chars)
            if command[end - 1:end] in (" ", "\t"):
                end -= 1
            word_start = previous_end
            while word_start < end and command[word_start] in " \t":
                word_start += 1
            previous_end = end
            word = command[word_start:end]
            literal = None
            if (
                breaks is not None
                and "\\" not in word
                and not ANSI_QUOTE_START.search(word)
                and breaks.isdisjoint(range(word_start, end))
                and end not in joins
                and word_start - 1 not in joins
                and PLAIN_QUOTED_SEGMENT.sub(lambda match: match.group(0)[1:-1], word) == token
            ):
                unquoted = PLAIN_QUOTED_SEGMENT.sub("", word)
                if (
                    "'" not in unquoted
                    and '"' not in unquoted
                    and not GIT_CONFIG_EXPANDING_WORD.search(unquoted)
                ):
                    literal = "mixed"
            for quote in ("", "'", '"'):
                start = end - len(token) - 2 * len(quote)
                if (
                    breaks is not None
                    and start >= 0
                    and command[start:end] == quote + token + quote
                    and (start == 0 or command[start - 1] in " \t|;&()<>\n\r")
                    and breaks.isdisjoint(range(start, end))
                    and end not in joins
                    and start - 1 not in joins
                ):
                    literal = "quoted" if quote else "bare"
                    break
            start = end - len(token)
            before = command[start - 1:start] if start > 0 else ""
            escaped = (start - len(command[:start].rstrip("\\"))) % 2 == 1
            redirection = command[start:end] == token and (
                (
                    set(token) <= SHELL_WRITE_REDIRECTION_CHARS
                    and ("<" in token or ">" in token)
                    and not escaped
                )
                or (
                    len(token) == 1
                    and token in "0123456789"
                    and command[end:end + 1] in ("<", ">")
                    and (not before or before in " \t|;&()<>\n\r")
                )
            )
            descriptor = (
                command[start:end] == token
                and SHELL_DESCRIPTOR_WORD.fullmatch(token) is not None
                and command[end:end + 1] in ("<", ">")
                and (not before or before in " \t|;&()<>\n\r")
            )
            # The shell reads a control operator and a redirection operator
            # written against each other as two operators.
            parts = [token]
            if (
                command[start:end] == token
                and set(token) <= set("|;&()<>\n\r")
                and ("<" in token or ">" in token)
                and not escaped
            ):
                parts = []
                for part in SHELL_OPERATOR_PARTS.findall(token):
                    if "<" in part or ">" in part or not parts or (
                        "<" in parts[-1] or ">" in parts[-1]
                    ):
                        parts.append(part)
                    else:
                        parts[-1] += part
            for part in parts:
                part = ShellToken(part)
                part.redirection = redirection if len(parts) == 1 else (
                    ("<" in part or ">" in part)
                    and set(part) <= SHELL_WRITE_REDIRECTION_CHARS
                )
                part.descriptor = descriptor
                part.literal = literal
                tokens.append(part)
    except ValueError as error:
        raise ValueError(
            f"shell command cannot be tokenized ({error}); balance the quotes "
            "or write the content with an editor tool"
        ) from None
    if not tokens:
        raise ValueError("shell command is empty")
    flags = double_quoted_markers(command) if direct else None
    if flags is None or len(flags) != sum(
        character in PARAMETER_MARKERS for token in tokens for character in token
    ):
        return tokens
    marked = []
    for token in tokens:
        count = sum(character in PARAMETER_MARKERS for character in token)
        redirection, descriptor, literal = (
            token.redirection, token.descriptor, token.literal
        )
        token = ShellToken(token)
        token.redirection, token.descriptor, token.literal = (
            redirection, descriptor, literal
        )
        token.double_quoted, flags = tuple(flags[:count]), flags[count:]
        marked.append(token)
    return marked


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
    segments = list(command_segments(wrapped))
    if wrapped and (
        not segments
        or not all(
            archive_command_is_read_only(shlex.join(segment), segment, True)
            for segment in segments
        )
    ):
        raise ValueError(
            f"{wrapper} runs {wrapped[0]} on operands the guard cannot check; "
            f"only read commands may follow {wrapper}, or pass the paths as literals"
        )


def runner_value_option(prefix, token):
    """The option in a runner option word whose value is the next word, if any.

    Raises for an option that writes, edits or enters a file or directory. A
    long option matches by each prefix, as getopt accepts it. A short word is
    read as getopt reads it: flag letters, then the first value option letter,
    whose value is the rest of the word or, with no rest, the next word.
    """
    value_options = EXEC_PREFIX_VALUE_OPTIONS[prefix]
    file_options = EXEC_PREFIX_FILE_OPTIONS.get(prefix, frozenset())
    denial = ValueError(
        f"{prefix} {token} writes, edits or enters a file or directory that the "
        "guard cannot check; run the command without this option and redirect "
        "its output instead"
    )
    if token.startswith("--"):
        name = token.split("=", 1)[0]
        if any(option.startswith(name) for option in file_options):
            raise denial
        option = next((option for option in value_options if option.startswith(name)), None)
        return option if "=" not in token else None
    for position, letter in enumerate(token[1:], start=1):
        option = f"-{letter}"
        if option in file_options:
            raise denial
        if option in value_options:
            return option if position == len(token) - 1 else None
        if letter not in EXEC_PREFIX_FLAG_LETTERS[prefix]:
            return None
    return None


def nonliteral_runner_option(token):
    literal = getattr(token, "literal", "bare")
    return (
        SHELL_PARAMETER_SYNTAX.search(token)
        or CMD_PARAMETER_SYNTAX.search(token)
        or zsh_expansion_flag(token)
        or literal is None
        or (literal == "bare" and GIT_CONFIG_EXPANDING_WORD.search(token))
    )


def unresolved_runner_word(token):
    return (
        SHELL_PARAMETER_SYNTAX.search(token)
        or CMD_PARAMETER_SYNTAX.search(token)
        or zsh_expansion_flag(token)
    ) and not parameters_double_quoted(token)


POWERSHELL_ASSIGNMENT_TARGET = re.compile(r"^\$(?:env:)?[A-Za-z_][A-Za-z0-9_]*$")
POWERSHELL_LITERAL_VALUE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:/\\ +,-]*")
POWERSHELL_STATIC_CALL = re.compile(r"\[(?P<type>[^\]()]+)\]::")
POWERSHELL_PURE_TYPES = frozenset(
    {
        "math", "string", "int", "int32", "long", "int64", "double", "bool",
        "byte", "char", "decimal", "single", "guid", "datetime", "timespan",
        "version",
        "system.math", "system.string", "system.int32", "system.int64",
        "system.double", "system.boolean", "system.guid", "system.datetime",
        "system.timespan", "system.version",
    }
)
POWERSHELL_DYNAMIC_COMMANDS = frozenset(
    {
        "invoke-expression", "iex", "invoke-command", "icm", "add-type",
        "start-process", "saps", "sap", "start-job", "new-object",
    }
)


def powershell_assignment_invocation(segment, unwrap_runners=True):
    """The invocation a validated PowerShell assignment runs, or None.

    ``$name = literal`` and ``$env:NAME = literal`` set a process-local
    variable or environment entry. PowerShell runs a bare-word value as a
    pipeline, so the value is judged as the command it would run. The value
    must be plain literals; anything richer — expansions, substitutions,
    member access — keeps the unresolvable denial rather than guessing at
    expression semantics. An environment name that changes where Git reads
    its configuration is refused exactly like the shell form (#468).
    """
    if len(segment) < 3 or segment[1] != "=":
        return None
    if POWERSHELL_ASSIGNMENT_TARGET.fullmatch(segment[0]) is None:
        return None
    name = segment[0].removeprefix("$")
    folded = name.casefold()
    if ":" in name:
        variable, _, scope = name.partition(":")
        if variable != "env":
            return None
        if scope.casefold() in {"home", "xdg_config_home"} or scope.casefold().startswith("git_"):
            raise ValueError(
                f"{name} changes where Git reads its configuration, which the guard "
                "cannot validate; run git without it"
            )
    elif folded in {"home", "xdg_config_home"} or folded.startswith("git_"):
        return None  # shell-style names keep their shell semantics, not PowerShell's
    if any(POWERSHELL_LITERAL_VALUE.fullmatch(token) is None for token in segment[2:]):
        return None
    # A value naming a write or dynamic command runs it; deny without resolving paths.
    command_names = SHELL_WRITE_COMMANDS | POWERSHELL_DYNAMIC_COMMANDS
    if any(token.casefold().removesuffix(".exe") in command_names for token in segment[2:]):
        return None
    return command_invocation(segment[2:], unwrap_runners)


def powershell_expression_reason(tokens, depth=0):
    """Why a PowerShell expression form stays denied, or None when safe.

    PowerShell expression statements are not executables: assignments are
    process-local, while .NET static member calls run arbitrary code
    (``[System.IO.File]::WriteAllText`` writes a file the write-target
    classification never sees). The guard allows the provably pure type
    members and denies every other static call — wherever the token appears,
    including inside a script block or a wrapped ``-Command`` payload — plus
    every dynamic-execution command (aliases included) inside a block or as
    the executable, and the call operator (#468).
    """
    previous = None
    for token in tokens:
        if token == "&" and (
            previous is None
            or previous.endswith("{")
            or set(previous) <= set("|;&()\n\r")
        ):
            return "the PowerShell call operator target cannot be resolved"
        previous = token
    for segment in command_segments(tokens):
        wrapped = wrapped_command_tokens(segment, expand_parameters=False)
        if wrapped is not None:
            if depth >= 4:
                return "nested command payloads exceed the guard's inspection depth"
            reason = powershell_expression_reason(wrapped, depth + 1)
            if reason:
                return reason
            continue
        invocation = command_invocation(list(segment))
        if invocation is None:
            continue
        executable = invocation[0]
        if executable in POWERSHELL_DYNAMIC_COMMANDS:
            return f"dynamic execution cannot be inspected by the guard: {executable}"
        block_depth = 0
        for token in segment:
            match = POWERSHELL_STATIC_CALL.search(token)
            if match is not None and match.group("type").strip().casefold() not in POWERSHELL_PURE_TYPES:
                return (f"static member call is not on the guard's read-only type "
                        f"whitelist: {token}")
            word = token.lstrip("{")
            block_depth += len(token) - len(word)
            if block_depth and word.rstrip("}").casefold() in POWERSHELL_DYNAMIC_COMMANDS:
                return f"dynamic execution cannot be inspected by the guard: {token}"
            block_depth = max(0, block_depth - (len(word) - len(word.rstrip("}"))))
    return None


def command_invocation(segment, unwrap_runners=True):
    """`unwrap_runners` is False where a command runner itself must be judged."""
    index = 0
    # The shell word `time` is already removed; its only option can remain.
    while unwrap_runners and index < len(segment) and segment[index] == "-p":
        index += 1
    while True:
        while index < len(segment) and SHELL_ASSIGNMENT_PATTERN.match(segment[index]):
            validate_shell_assignment(segment[index])
            index += 1
        if index >= len(segment):
            return None
        executable = segment[index].replace("\\", "/").rsplit("/", 1)[-1].casefold()
        prefix = executable.removesuffix(".exe")
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
                if SHELL_PARAMETER_SYNTAX.search(token) or zsh_expansion_flag(token):
                    raise ValueError(
                        f"env word {token} cannot be resolved by the guard; env "
                        "assignments must be literal NAME=VALUE words and the "
                        "program a literal name"
                    )
                break
        elif unwrap_runners and prefix in EXEC_PREFIX_VALUE_OPTIONS:
            index += 1
            while index < len(segment):
                token = segment[index]
                if token == "--":
                    index += 1
                    break
                if not token.startswith("-") or token == "-":
                    break
                index += 1
                if nonliteral_runner_option(token):
                    raise ValueError(
                        f"{prefix} option {token} cannot be resolved by the guard; "
                        f"{prefix} options must be literal words"
                    )
                option = runner_value_option(prefix, token)
                if option is None or index >= len(segment):
                    continue
                value = segment[index]
                index += 1
                if prefix == "watch" and option in EXEC_PREFIX_INTERVAL_OPTIONS:
                    if not RUNNER_DURATION.fullmatch(value):
                        raise ValueError(
                            f"watch interval {value} cannot be resolved by the guard; "
                            "the interval must be a literal number"
                        )
                elif unresolved_runner_word(value):
                    raise ValueError(
                        f"{prefix} option value {value} cannot be resolved by the "
                        f"guard; {prefix} option values must be literal words"
                    )
            if prefix == "timeout" and index < len(segment):
                if not RUNNER_DURATION.fullmatch(segment[index]):
                    raise ValueError(
                        f"timeout duration {segment[index]} cannot be resolved by the "
                        "guard; the duration must be a literal number"
                    )
                index += 1
        else:
            break
    arguments = segment[index + 1 :]
    if SHELL_PARAMETER_SYNTAX.search(executable):
        assignment = powershell_assignment_invocation(list(segment[index:]), unwrap_runners)
        if assignment is not None:
            return assignment
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


def require_resolved_git_word(word, mixed=True):
    """Deny a git word the shell can turn into other or several arguments."""
    literal = getattr(word, "literal", "bare")
    if (
        literal is None
        or (literal == "mixed" and not mixed)
        or (literal == "bare" and GIT_CONFIG_EXPANDING_WORD.search(word))
    ):
        raise ValueError(
            f"git argument {word} cannot be resolved by the guard; "
            "pass a literal value"
        )


def git_command(segment, assignments=None):
    invocation = command_invocation(segment)
    if invocation is None:
        return None
    executable, arguments = invocation
    if executable not in {"git", "git.exe"}:
        return None
    resolved_arguments = []
    parameter_arguments = []
    unproven_parameters = []
    argument_index = 0
    while argument_index < len(arguments):
        argument = arguments[argument_index]
        attached_directory = argument.startswith("-C") and len(argument) > 2
        if argument == "-C" and argument_index + 1 < len(arguments):
            argument_index += 1
            directory = arguments[argument_index]
            require_resolved_git_word(directory)
            expanded = expand_environment_parameters(directory, assignments)
            if (
                SHELL_PARAMETER_SYNTAX.search(expanded)
                or CMD_PARAMETER_SYNTAX.search(expanded)
                or zsh_expansion_flag(expanded)
            ):
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
            require_resolved_git_word(argument)
            directory = argument[2:]
            expanded = expand_environment_parameters(directory, assignments)
            if (
                SHELL_PARAMETER_SYNTAX.search(expanded)
                or CMD_PARAMETER_SYNTAX.search(expanded)
                or zsh_expansion_flag(expanded)
            ):
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
            parameter = (
                SHELL_PARAMETER_SYNTAX.search(argument)
                or CMD_PARAMETER_SYNTAX.search(argument)
                or zsh_expansion_flag(argument)
            )
            if parameter:
                parameter_arguments.append(argument)
                literal = re.split(r"[$%!]", argument, maxsplit=1)[0]
                expanded = expand_environment_parameters(argument, assignments)
                if (
                    not literal
                    or (literal.startswith("-") and "=" not in literal)
                    or git_option_in(literal, GIT_PARAMETER_DENIED_OPTIONS)
                    or git_option_in(arguments[argument_index - 1], GIT_PARAMETER_DENIED_OPTIONS)
                    or (literal.startswith("-c") and literal != "-c")
                    or "::" in literal
                    or not parameters_double_quoted(argument)
                    or SUBSTITUTION_PLACEHOLDER in argument
                    or SUBSTITUTION_PLACEHOLDER in expanded
                ):
                    unproven_parameters.append(argument)
            expanded = expand_environment_parameters(argument, assignments)
            resolved_arguments.append(argument if expanded == argument else expanded)
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
        if option != "-C":
            require_resolved_git_word(token)
        if option in GIT_GLOBAL_OPTIONS_WITH_VALUES and value is None:
            if index >= len(arguments):
                raise ValueError(f"git option {option} lacks a value")
            value = arguments[index]
            if option != "-C":
                require_resolved_git_word(value)
            index += 1
        if option not in {"-C", "-c", "--config-env"} and git_option_in(
            option, GIT_PARAMETER_DENIED_OPTIONS
        ):
            # A denied global option executes a program git runs
            # (--upload-pack/--exec/...); it must never slip past as a
            # pre-subcommand token the subcommand checks never see (#468).
            # -c/--config-env keep their dedicated config-key checks below.
            raise ValueError(
                f"git option {option} cannot be verified by the guard"
            )
        if option in {"-c", "--config-env"}:
            config_key, _, config_value = str(value).partition("=")
            config_key = config_key.casefold()
            if config_key.startswith("alias."):
                raise ValueError(
                    f"git -c {config_key} defines an alias the guard cannot inspect; "
                    "run the underlying git command directly"
                )
            if executed_config_key(config_key) and not (
                option == "-c"
                and not loaded_config_key(config_key)
                and config_value.casefold() in GIT_CONFIG_DISABLING_VALUES
            ):
                raise ValueError(
                    f"git -c {config_key} configures a program git executes; "
                    "the guard cannot allow it"
                )
            if config_key == "clean.requireforce":
                raise ValueError(
                    "git -c clean.requireForce disables the git clean safety check; "
                    "run git clean with explicit paths instead"
                )
        if option in GIT_GLOBAL_OPTIONS_WITH_VALUES:
            git_options.extend((option, str(value)))
    if index >= len(arguments):
        if parameter_arguments:
            raise ValueError(
                f"git argument {parameter_arguments[0]} cannot be resolved by the guard; "
                "pass a literal value (for commit messages use -F <file>)"
            )
        return None
    require_resolved_git_word(arguments[index], mixed=False)
    subcommand = arguments[index].casefold()
    if subcommand == "config":
        for argument in arguments[index + 1:]:
            literal = getattr(argument, "literal", None)
            if not getattr(argument, "redirection", False) and (
                literal in (None, "mixed")
                or (
                    literal == "bare"
                    and (argument.startswith("#") or GIT_CONFIG_EXPANDING_WORD.search(argument))
                )
            ):
                raise ValueError(
                    f"git argument {argument} cannot be resolved by the guard; "
                    "pass a literal value"
                )
        denied = denied_git_config_argument(arguments[index + 1:])
        if denied is not None:
            raise ValueError(
                f"git config {denied} persists a program git executes; "
                "the guard cannot allow it"
            )
    read_only_subcommands = ARCHIVE_READ_GIT_COMMANDS | CLOSED_READ_GIT_COMMANDS
    if subcommand in read_only_subcommands:
        # Read-only subcommands still write through --output. A parameter
        # passes only inside plain double quotes, where its expansion stays
        # one word; an unquoted one can word-split into an option, and
        # command substitution output is never known.
        parameter_arguments = unproven_parameters
    if parameter_arguments:
        raise ValueError(
            f"git argument {parameter_arguments[0]} cannot be resolved by the guard; "
            "pass a literal value (for commit messages use -F <file>)"
        )
    return subcommand, arguments[index + 1:], git_options


def wrapped_command_tokens(segment, expand_parameters=True):
    invocation = command_invocation(segment)
    if invocation is None:
        return None
    executable, arguments = invocation
    if executable == "eval":
        return shell_tokens(" ".join(arguments), direct=False) if arguments else None
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
                return shell_tokens(arguments[index + 1], direct=False)
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
                    return shell_tokens(payload[0], direct=False)
                return [str(argument) for argument in payload]
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
        try:
            result = subprocess.run(
                ["git", *git_options, "config", "--get", f"alias.{command}"],
                cwd=directory,
                encoding="utf-8", errors="replace",
                capture_output=True,
                check=False,
            )
        except OSError:
            raise ValueError("git alias configuration cannot be validated") from None
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


def _update_ref_operands(arguments):
    """The (first ref operand, options) of an update-ref command, or (None, ...)."""
    operands, options = [], set()
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "-m":  # its value is not an option, also when it is -d
            index += 2
            continue
        if argument.startswith("-"):
            options.add(argument)
            index += 1
            continue
        operands.append(argument)
        index += 1
    if not operands or not _literal_target(operands[0]):
        return None, options
    return operands[0], options


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
        has_short_option(arguments, "d")  # also a cluster such as -dm
        or "--delete" in arguments
        or any(git_option_in(argument, {"--stdin"}) for argument in arguments)
        or zero_value
    )


PATH_OWNED_REF_PREFIXES = (
    "gsd-path/",
    "gsd-path-task/",
    "gsd-path-verify/",
    "gsd-path-integrate/",
)
# Git ignores an alias that has the name of one of its own commands, so these
# need no alias inspection. Each has been a Git command since Git 2.31, the
# oldest Git that has the rev-parse --path-format option the pipeline uses.
# Deprecated commands stay out: newer Git lets an alias replace them
# (whatchanged, pack-redundant). A name that is absent only fails closed.
GIT_BUILT_IN_COMMANDS = frozenset({
    "add", "am", "annotate", "apply", "archive", "bisect", "blame", "branch",
    "bugreport", "bundle", "cat-file", "check-attr", "check-ignore",
    "check-mailmap", "check-ref-format", "checkout", "checkout-index", "cherry",
    "cherry-pick", "clean", "clone", "column", "commit", "commit-graph",
    "commit-tree", "config", "count-objects", "credential", "credential-store",
    "describe", "diff", "diff-files", "diff-index", "diff-tree", "difftool",
    "fast-export", "fast-import", "fetch", "fetch-pack", "fmt-merge-msg",
    "for-each-ref", "for-each-repo", "format-patch", "fsck", "gc",
    "get-tar-commit-id", "grep", "hash-object", "help", "index-pack", "init",
    "interpret-trailers", "log", "ls-files", "ls-remote", "ls-tree", "mailinfo",
    "mailsplit", "maintenance", "merge", "merge-base", "merge-file",
    "merge-index", "merge-tree", "mergetool", "mktag", "mktree",
    "multi-pack-index", "mv", "name-rev", "notes", "pack-objects", "pack-refs",
    "patch-id", "prune", "prune-packed", "pull", "push", "range-diff",
    "read-tree", "rebase", "receive-pack", "reflog", "remote", "repack",
    "replace", "rerere", "reset", "restore", "rev-list", "rev-parse", "revert",
    "rm", "send-pack", "shortlog", "show", "show-branch", "show-index",
    "show-ref", "sparse-checkout", "stage", "stash", "status", "stripspace",
    "submodule", "switch", "symbolic-ref", "tag", "unpack-file",
    "unpack-objects", "update-index", "update-ref", "update-server-info",
    "upload-archive", "upload-pack", "var", "verify-commit", "verify-pack",
    "verify-tag", "version", "worktree", "write-tree",
})


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


def registered_worktree_records(output, separator="\0"):
    records = {}
    for record in output.split(separator * 2):
        fields = [field for field in record.split(separator) if field]
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
        listing = ("worktree", "list", "--porcelain")
        try:
            output, separator = _git_output(git_options, directory, *listing, "-z"), "\0"
        except ValueError:
            # Git before 2.36 has no -z here; pipeline_git.worktree_list_porcelain
            # retries the same way. A line then ends each field.
            output, separator = _git_output(git_options, directory, *listing), "\n"
        records = registered_worktree_records(output, separator)
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
    # git stash drop and clear are denied too; refs/stash holds each stash.
    if lowered.startswith("refs/gsd-path/") or lowered == "refs/stash":
        return True
    if lowered.startswith("refs/remotes/"):
        # The remote-tracking ref of a Path branch can be the last ref to its
        # commits. A remote name can contain a slash, so try each split.
        parts = name.split("/")[2:]
        return any(
            ref_is_path_owned("refs/heads/" + "/".join(parts[index:]), owned_branches)
            for index in range(1, len(parts))
        )
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

    # Loose refs that differ only in case are one file on macOS and Windows.
    return any(
        canonical(name).casefold() == canonical(branch).casefold()
        for branch in owned_branches
    )


def _literal_target(value):
    return bool(value) and not any(character in value for character in "*?[]{}~")


def _positional_targets(arguments):
    targets = []
    after_separator = False
    for argument in arguments:
        if after_separator:
            targets.append(argument)
        elif argument == "--":
            after_separator = True
        elif not argument.startswith("-"):
            targets.append(argument)
    return targets


PLAIN_REDIRECTION_OPERATORS = frozenset({">", ">>", "<", ">&", "&>", "&>>"})


def _opens_process_substitution(token):
    return token in ("<(", ">(") and getattr(token, "literal", None) != "quoted"


def _fold_process_substitutions(tokens):
    """The tokens with each process substitution body moved onto its operator."""
    folded = []
    body = None
    depth = 0
    for token in tokens:
        opens = _opens_process_substitution(token) and (
            getattr(token, "body", None) is None
        )
        if depth == 0:
            if opens:
                depth, body = 1, []
                operator = ShellToken(token)
                operator.literal = getattr(token, "literal", None)
                operator.body = body
                token = operator
            folded.append(token)
            continue
        if opens:
            depth += 1
        elif token and set(token) <= set("|;&()\n\r") and (
            getattr(token, "literal", None) != "quoted"
        ):
            for index, character in enumerate(token):
                depth += (character == "(") - (character == ")")
                if depth == 0:
                    if token[index + 1:]:
                        folded.append(ShellToken(token[index + 1:]))
                    if token[:index]:
                        body.append(token[:index])
                    break
            if depth == 0:
                continue
        body.append(token)
    return folded


def _runs_git_or_wrapper(segment, assignments):
    words, _exact = _without_redirections(segment)
    return (
        wrapped_command_tokens(words if len(words) > 1 else segment) is not None
        or git_command(words, assignments) is not None
    )


def _holds_git_command(tokens, assignments):
    """Whether the tokens run Git or a wrapper, at each process substitution depth."""
    for segment in command_segments(tokens):
        words = []
        for token in [*segment, None]:
            if token is not None and not _opens_process_substitution(token):
                if not getattr(token, "descriptor", False):
                    words.append(token)
                continue
            if words and _runs_git_or_wrapper(words, assignments):
                return True
            words = []
            if getattr(token, "body", None) and _holds_git_command(
                token.body, assignments
            ):
                return True
    return False


def _without_descriptor(token):
    word = ShellToken(token)
    word.redirection = getattr(token, "redirection", False)
    word.literal = getattr(token, "literal", None)
    return word


def _without_redirections(words):
    """The words of a simple command without the redirections the shell parsed.

    Each redirection operator goes with the word after it and one file
    descriptor digit written against it. The second result is false when one
    of them is not plain: an operator outside PLAIN_REDIRECTION_OPERATORS or
    a target that is not one literal word. A process substitution operator is
    removed too and is never plain.
    """
    kept = []
    exact = True
    index = 0
    while index < len(words):
        word = words[index]
        if _opens_process_substitution(word):
            exact = False
            index += 1
            continue
        if not getattr(word, "redirection", False):
            kept.append(word)
            index += 1
            continue
        if word.isdigit():
            index += 1
            word = words[index] if index < len(words) else ""
        target = words[index + 1] if index + 1 < len(words) else ""
        exact = exact and not (
            word not in PLAIN_REDIRECTION_OPERATORS
            or getattr(target, "redirection", False)
            or getattr(target, "literal", None) not in ("bare", "quoted")
            or not _literal_target(target)
            or any(character in target for character in "$`<>()&|#")
        )
        index += 2
    return kept, exact


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


def _update_ref_names(target, refs, context, no_deref):
    """The ref names a deletion of this operand touches, or None when unresolved.

    Git reads an update-ref operand as a full name below the git directory,
    never as a branch short name. It follows each symbolic ref to the ref it
    deletes; with --no-deref it deletes the named symbolic ref itself. A name
    outside refs/ (HEAD, a symbolic ref at the top of the git directory) is
    unresolved: an ordinary command such as git switch changes its target.
    """
    if not target.startswith("refs/"):
        return None
    names = [target]
    while True:
        symbolic = _symbolic_ref_target(context, names[-1])
        if symbolic is None:
            return names if names[-1] in refs else None
        if no_deref:
            return names
        if symbolic in names:
            return None
        names.append(symbolic)


def _workspace_roots(contexts):
    return _workspace_roots_for_commons({context["common"] for context in contexts})


def _workspace_roots_for_commons(commons):
    roots = [(Path.home() / ".gsd-path").resolve()]
    configured = os.environ.get("GSD_PATH_WORKTREE_ROOT")
    if configured:
        configured_root = Path(configured).expanduser()
        if not configured_root.is_absolute():
            raise ValueError("GSD_PATH_WORKTREE_ROOT must be absolute")
        roots.append(configured_root.resolve())
    for common in commons:
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
    # The shell expands a leading ~ and a glob in an option value such as the
    # -C directory; the guard has only the literal text.
    if any(
        value[:1] == "~" or any(character in value for character in "*?[]{}")
        for value in git_options[1::2]
    ):
        return unresolved
    contexts = git_target_contexts(git_options, working_directories)
    branches, task_worktrees = path_owned_records(_frontmatter_roots(contexts))

    if command == "branch":
        # Each word that is not an option is read as a branch name. Git does
        # the same after --color; after an option with a separate value
        # (--sort key) this only adds a name to check.
        targets = _positional_targets(arguments)
        if not targets or not all(_literal_target(target) for target in targets):
            return unresolved
        remote = has_short_option(arguments, "r") or any(
            git_option_in(argument, {"--remotes"}) for argument in arguments
        )
        for target in targets:
            # Git reads the name in exactly one namespace, with no other form.
            ref = f"refs/{'remotes' if remote else 'heads'}/{target}"
            if ref_is_path_owned(ref, branches) or ref_is_path_owned(
                f"refs/heads/{target}", branches
            ):
                return GIT_REASONS["branch"]
            if any(ref not in _git_refs(context) for context in contexts):
                return unresolved
        return None

    if command == "update-ref":
        operands, options = [], set()
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument == "-m":  # its value is not an option, also when it is -d
                index += 2
                continue
            if argument.startswith("-"):
                options.add(argument)
                index += 1
                continue
            operands.append(argument)
            index += 1
        deletion_flag = "-d" in options
        expected_counts = {1, 2} if deletion_flag else {2, 3}
        if len(operands) not in expected_counts or not _literal_target(operands[0]):
            return unresolved
        if not deletion_flag and not (operands[1] == "" or not operands[1].strip("0")):
            return unresolved
        if deletion_flag and len(operands) == 2 and not _literal_target(operands[1]):
            return unresolved
        if not deletion_flag and len(operands) == 3 and not _literal_target(operands[2]):
            return unresolved
        # Dereferencing a symbolic ref must not erase ownership of its name.
        if ref_is_path_owned(operands[0], branches):
            return GIT_REASONS["update-ref"]
        for context in contexts:
            names = _update_ref_names(
                operands[0], _git_refs(context), context, "--no-deref" in options
            )
            if names is None:
                return unresolved
            if any(ref_is_path_owned(name, branches) for name in names):
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
        # Git tries a unique path suffix first, then the path, and compares
        # without case on macOS and Windows. Both readings must agree.
        matches = {resolved_target} & set(registered)
        suffix = tuple(
            part.casefold() for part in Path(targets[0]).parts if part not in {"", "."}
        )
        if suffix and not Path(targets[0]).is_absolute() and ".." not in suffix:
            by_suffix = [
                path for path in registered
                if tuple(part.casefold() for part in path.parts[-len(suffix):]) == suffix
            ]
            if len(by_suffix) == 1:
                matches.add(by_suffix[0])
        if len(matches) != 1:
            return unresolved
        resolved_target = matches.pop()
        if not resolved_target.is_dir():
            return unresolved
        branch = registered[resolved_target]
        primary = next(iter(registered))
        if (
            resolved_target in recorded_paths
            or (branch is not None and ref_is_path_owned(branch, branches))
            or any(
                resolved_target == root or resolved_target.is_relative_to(root)
                for root in (*managed_roots, primary.parent / f"{primary.name}.gsd-path")
            )
            or (
                resolved_target.parent == primary.parent
                and resolved_target.name.startswith(f".{primary.name}-gsd-path-integrate-")
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
        return False
    return False


def ownership_cwd_is_uncertain(tokens, working_directories=None):
    """Whether a scoped delete follows a cd whose shell control flow is unclear."""
    cwd_wrappers = COMMAND_WRAPPERS | {
        "eval", "source", ".",
        # These change what a later cd does, or run a cd later.
        "alias", "trap", "enable", "disable",
    }
    segments = []
    current = []
    separator = None
    depth = 0
    comment = False
    for token in tokens:
        # Most shells run nothing from a # word to the end of the line, but
        # the guard reads that text as commands. A cd there can run or not.
        if comment and "\n" in token:
            if not set(token) <= set("|;&()\n\r"):
                return True
            comment = False
        elif comment and token.casefold() in DIRECTORY_CHANGE_COMMANDS:
            return True
        if token and set(token) <= set("|;&()\n\r"):
            if "()" in token:
                return True  # a function definition: its body runs only on a call
            if current:
                segments.append((current, separator, depth))
                current = []
            if "(" in token:
                depth += token.count("(")
            if ")" in token:
                depth = max(0, depth - token.count(")"))
            separator = token.strip()
        else:
            comment = comment or (
                token.startswith("#") and getattr(token, "literal", None) != "quoted"
            )
            current.append(token)
    if current:
        segments.append((current, separator, depth))

    uncertain = False
    conditional = False
    current_directories = list(working_directories or [os.getcwd()])
    initial_symlink = any(
        _path_has_symlink_component(directory) for directory in current_directories
    )
    for index, (segment, previous_separator, group_depth) in enumerate(segments):
        plain, _exact = _without_redirections(segment)
        redirected = len(plain) != len(segment)
        segment = plain
        if not segment:
            continue
        if env_wrapper_changes_git_context(segment):
            return True
        if segment[0] == "function":
            return True
        if any(token.casefold() in SHELL_CONTROL_WORDS for token in segment):
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
        if command in DIRECTORY_CHANGE_COMMANDS:
            target = directory_change_target(arguments)
            absolute = is_absolute_path(target)
            dotted = target.replace("\\", "/")
            next_directories = (
                [target]
                if absolute
                else [f"{directory}/{target}" for directory in current_directories]
            )
            if (
                # Only a plain `cd <directory>` has the same effect in each shell.
                segment[0] != "cd"
                or redirected
                or arguments not in ([target], ["--", target])
                # A shell with CDPATH looks for a plain relative name in other
                # directories first; ./name and ../name are not looked up there.
                or not (
                    absolute
                    or dotted in {".", ".."}
                    or dotted.startswith(("./", "../"))
                )
                or any(character in target for character in "*?[]{}$")
                or group_depth > 0
                or previous_separator in {"&&", "||", "&"}
                or next_separator in {"||", "&"}
                or (previous_separator is not None and "|" in previous_separator)
                or (next_separator is not None and "|" in next_separator)
                or conditional
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

GIT_CONTEXT_NAME = re.compile(r"GIT_\w+|HOME|XDG_CONFIG_HOME")
# export, declare, typeset, local, readonly and unset of these names are
# denied where the guard reads assignments.
VARIABLE_SETTING_COMMANDS = frozenset(
    {"read", "getopts", "mapfile", "readarray", "integer", "float", "vared"}
)
LOOP_VARIABLE_WORDS = frozenset({"for", "select"})


def command_sets_git_context_name(tokens):
    """Whether a command that the guard does not track sets a Git context variable."""
    words = []
    for token in [*tokens, ";"]:
        if not (token and set(token) <= set("|;&()\n\r")):
            words.append(token)
            continue
        words, _exact = _without_redirections(words)
        while words and (
            words[0].casefold() in SHELL_CONTROL_WORDS - LOOP_VARIABLE_WORDS
            or words[0] in COMMAND_WRAPPERS
            or SHELL_ASSIGNMENT_PATTERN.match(words[0])
        ):
            del words[0]
        command, operands, words = "".join(words[:1]), words[1:], []
        if command in LOOP_VARIABLE_WORDS:
            operands = operands[:1]
        elif command in {"printf", "print"}:
            operands = [
                name for option, name in zip(operands, operands[1:]) if option == "-v"
            ] + [option[2:] for option in operands if option.startswith("-v")]
        elif command not in VARIABLE_SETTING_COMMANDS:
            continue
        if any(GIT_CONTEXT_NAME.fullmatch(operand) for operand in operands):
            return True
    return False


def destructive_git_reason(
    tokens,
    resolved_aliases=frozenset(),
    initial_assignments=None,
    working_directories=None,
    cwd_reliable=True,
    git_context_reliable=True,
    earlier_git=False,
    fold=True,
):
    # A process substitution has two readings: the tokens as they stand, and
    # the tokens with each substitution body folded onto its operator.
    folded = _fold_process_substitutions(tokens) if fold else tokens
    if len(folded) != len(tokens):
        reason = destructive_git_reason(
            tokens,
            resolved_aliases,
            initial_assignments=initial_assignments,
            working_directories=working_directories,
            cwd_reliable=cwd_reliable,
            git_context_reliable=git_context_reliable,
            earlier_git=earlier_git,
            fold=False,
        )
        if reason is not None:
            return reason
    tokens = folded
    cwd_reliable = cwd_reliable and not ownership_cwd_is_uncertain(
        tokens, working_directories
    )
    git_context_reliable = (
        git_context_reliable and not command_sets_git_context_name(tokens)
    )
    this_git = False
    for segment, directories, assignments, _prefix in shell_segment_contexts(
        tokens, working_directories or [os.getcwd()], initial_assignments
    ):
        # Whether a Git command or a wrapped command ran before this segment.
        earlier_git = earlier_git or this_git
        # A dollar expansion can introduce literal percent/bang text; the second
        # expansion pass must not silently reinterpret it as a different path.
        cwd_reliable = cwd_reliable and not any(
            CMD_PARAMETER_SYNTAX.search(NAMED_SHELL_PARAMETER_SYNTAX.sub(
                lambda match: environment_parameter_value(match, assignments), token
            ))
            for token in segment
        )
        # A descriptor word is a file descriptor in bash and an argument in
        # zsh; a process substitution runs a second command. Each reading is
        # checked, and a scoped deletion in one of them is denied.
        descriptor = any(getattr(token, "descriptor", False) for token in segment)
        if descriptor:
            readings = [
                [token for token in segment if not getattr(token, "descriptor", False)],
                [
                    _without_descriptor(token)
                    if getattr(token, "descriptor", False) else token
                    for token in segment
                ],
            ]
        else:
            readings = [token.body for token in segment if getattr(token, "body", None)]
        for reading in readings:
            reason = destructive_git_reason(
                reading,
                resolved_aliases,
                initial_assignments=assignments,
                working_directories=directories,
                cwd_reliable=False,
                git_context_reliable=git_context_reliable,
                earlier_git=earlier_git,
            )
            if reason is not None:
                return reason
        nested_git = (
            descriptor or any(_opens_process_substitution(token) for token in segment)
        ) and _holds_git_command(segment, assignments)
        if descriptor:
            this_git = nested_git
            continue
        # A redirection can stand at each position of a simple command.
        words, exact = _without_redirections(segment)
        segment_git_context_reliable = (
            git_context_reliable
            and not env_wrapper_changes_git_context(words)
            and not assignments_change_git_context(assignments)
        )
        wrapped = wrapped_command_tokens(words if len(words) > 1 else segment)
        if wrapped is not None:
            reason = destructive_git_reason(
                wrapped,
                resolved_aliases,
                initial_assignments=assignments,
                working_directories=directories,
                cwd_reliable=cwd_reliable and exact,
                git_context_reliable=segment_git_context_reliable,
                earlier_git=earlier_git,
            )
            if reason is not None:
                return reason
        invocation = git_command(words, assignments)
        this_git = nested_git or wrapped is not None or invocation is not None
        if invocation is None:
            continue
        command, arguments, git_options = invocation
        # Git matches its own commands by exact case, but alias names in any case.
        built_in = (
            command_invocation(words)[1][-len(arguments) - 1] in GIT_BUILT_IN_COMMANDS
        )
        if not segment_git_context_reliable and not built_in:
            return GIT_REASONS["git-environment"]
        # A scoped deletion needs literal words: the shell can change a variable
        # in ways the guard does not track (read, +=, for, printf -v).
        resolvable = cwd_reliable and exact and not any(
            SHELL_PARAMETER_SYNTAX.search(token) for token in segment
        )
        directories = [native_path_text(directory) for directory in directories]
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
        # A directory that an earlier segment creates does not exist yet.
        alias = None
        if not built_in or all(os.path.isdir(directory) for directory in directories):
            alias = git_alias(command, git_options, directories)
        if alias is not None:
            if command in resolved_aliases:
                raise ValueError(
                    f"git alias {command} refers to itself; run the underlying "
                    "git command directly"
                )
            # Git passes each word of an alias on as an argument; it runs no shell.
            alias_words = shell_tokens(alias, direct=False)
            for word in alias_words:
                word.redirection = False
            reason = destructive_git_reason(
                ["git", *git_options, *alias_words, *arguments],
                resolved_aliases | {command},
                initial_assignments=assignments,
                working_directories=directories,
                # Non-shell Git aliases do not expand environment parameters.
                cwd_reliable=resolvable and not (
                    NAMED_SHELL_PARAMETER_SYNTAX.search(alias)
                    or CMD_PARAMETER_SYNTAX.search(alias)
                ),
                git_context_reliable=segment_git_context_reliable,
                earlier_git=earlier_git,
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
            # Git accepts each unique prefix of a long option (--del, --forc).
            deletes = (
                any(git_option_in(argument, {"--delete"}) for argument in arguments)
                or has_short_option(arguments, "d")
                or has_short_option(arguments, "D")
            )
            forces = (
                any(git_option_in(argument, {"--force"}) for argument in arguments)
                or has_short_option(arguments, "f")
                or has_short_option(arguments, "D")
            )
            if deletes and forces:
                if not segment_git_context_reliable:
                    return GIT_REASONS["git-environment"]
                if not resolvable:
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
                if not segment_git_context_reliable:
                    return GIT_REASONS["git-environment"]
                if not resolvable:
                    return GIT_REASONS["unresolved-target"].format(
                        action="git update-ref deletion"
                    )
                # The guard reads each symbolic ref now; an earlier Git command
                # of this command line can point it at a Path-owned ref later.
                # (-m can take the text --no-deref as its value.)
                if earlier_git and (
                    "--no-deref" not in arguments or "-m" in arguments
                ):
                    return GIT_REASONS["update-ref-order"]
                reason = owned_target_reason(
                    command, arguments, git_options, directories
                )
                if reason is not None:
                    return reason
            else:
                # Creating or rewriting a ref under a Path-owned namespace is
                # as destructive as deleting one: refs/gsd-path/ holds
                # orchestrator-owned authorizations (member task bases, runtime
                # hotfixes), so an agent writing there forges the trust those
                # refs prove (#480). Deny by the ref name alone — creation
                # needs no repository state to resolve.
                created, _options = _update_ref_operands(arguments)
                if created is not None and ref_is_path_owned(created, set()):
                    return GIT_REASONS["update-ref"]
        if command == "worktree" and arguments[:1] == ["remove"]:
            if any(
                git_option_in(argument, {"--force"}) for argument in arguments
            ) or has_short_option(arguments[1:], "f"):
                if not segment_git_context_reliable:
                    return GIT_REASONS["git-environment"]
                if not resolvable:
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
    command, tokens, archive_context=False, git_commands=ARCHIVE_READ_GIT_COMMANDS,
    source=None,
):
    """`source` is the unexpanded (segment, assignments) whose tokens keep their quote flags."""
    if archive_context and AMBIGUOUS_SHELL_SYNTAX.search(command):
        return False
    if not archive_context:
        return True
    invocation = command_invocation(tokens, unwrap_runners=False)
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
    git = git_command(*(source or (tokens,)))
    if git is None:
        return False
    subcommand, git_arguments, _options = git
    if subcommand not in git_commands:
        return False
    return not any(
        git_option_in(token, GIT_READ_WRITE_OPTIONS) for token in git_arguments
    )


def archive_write_attempt(segment, source=None):
    """Whether a segment denied in archive context attempts a write there."""
    if any(
        token
        and (set(token) <= SHELL_WRITE_REDIRECTION_CHARS
             or re.fullmatch(r"\d*[<>]+&?", token))
        for token in segment
    ):
        return True
    invocation = command_invocation(segment)
    if invocation is None:
        return False
    executable, arguments = invocation
    executable = executable.removesuffix(".exe")
    if executable in SHELL_WRITE_COMMANDS:
        return True
    if executable in IN_PLACE_EDITORS and (
        has_short_option(arguments, "i")
        or any(argument.startswith("--in-place") for argument in arguments)
    ):
        return True
    git = git_command(*(source or (segment,)))
    if git is None:
        return False
    subcommand, git_arguments, _options = git
    return subcommand not in ARCHIVE_READ_GIT_COMMANDS or any(
        git_option_in(token, GIT_READ_WRITE_OPTIONS) for token in git_arguments
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


REMOTE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FETCH_DESTINATION = re.compile(r"^refs/remotes/[^\s]+/")


FETCH_BEHAVIOR_KEYS = (
    "remote.{remote}.uploadpack", "fetch.uploadpack",
    "remote.{remote}.prune", "fetch.prune",
    "remote.{remote}.pruneTags", "fetch.pruneTags",
    "remote.{remote}.mirror", "remote.{remote}.tagopt",
)


def _configured_fetch_read_only(repo, remote) -> bool:
    """The configured remote fetches into remote-tracking refs only.

    Repo config can change what a bare `git fetch REMOTE` does, so the
    guard proves it instead of assuming it: the remote has a URL (an
    unconfigured name makes git fetch from a local directory of that
    name); none of uploadpack (runs a program), prune/pruneTags (delete
    refs), mirror (rewrites every ref) or tagopt (forces tag fetches) is
    set at any scope; and every `remote.<name>.fetch` refspec writes only
    under refs/remotes/ (a hand-added `+refs/heads/main:refs/heads/retired`
    moves a local branch). Default tag auto-follow still creates missing
    tags that point at fetched commits; it never moves an existing ref.
    """
    def config(*arguments):
        try:
            return subprocess.run(
                ["git", "config", *arguments], cwd=repo, capture_output=True,
                encoding="utf-8", errors="replace", check=False,
            )
        except OSError:
            return None

    url = config("--get", f"remote.{remote}.url")
    if url is None or url.returncode != 0 or not url.stdout.strip():
        return False
    for key in FETCH_BEHAVIOR_KEYS:
        result = config("--get", key.format(remote=remote))
        if result is None or result.returncode != 1:
            return False
    refspecs = config("--get-all", f"remote.{remote}.fetch")
    if refspecs is None or refspecs.returncode not in (0, 1):
        return False
    for line in refspecs.stdout.splitlines():
        destination = line.rsplit(":", 1)[-1].strip()
        if not FETCH_DESTINATION.match(destination):
            return False
    return True


def _closed_fetch_allowed(git, segment, directories) -> bool:
    """A read-only fetch on a closed milestone (#468).

    `git fetch [REMOTE]` is allowed only once these properties are PROVEN,
    never assumed:
    (1) the raw segment is `git (-C DIR)* fetch`: no other global option
    precedes the subcommand (walked on raw tokens, consuming each -C with
    its value, so neither valueless flags like -p nor a -C value named
    fetch can slip past; --upload-pack/--exec additionally raise in
    git_command);
    (2) the remote's configuration fetches read-only (see
    _configured_fetch_read_only).
    Any refspec or option on the command line stays denied.
    """
    if git is None:
        return False
    subcommand, arguments, _options = git
    if subcommand != "fetch":
        return False
    words = [str(token) for token in segment]
    index = 1
    while words[index:index + 1] == ["-C"]:
        index += 2
    if words[index:index + 1] != ["fetch"]:
        return False
    remote = arguments[0] if arguments else None
    if remote is not None and not REMOTE_NAME.fullmatch(remote):
        return False
    if len(arguments) > 1:
        return False
    if remote is None:
        # No argument fetches the current branch's remote, else origin.
        remote = "origin"
        if directories:
            branch = _git_output([], directories[0], "branch", "--show-current")
            if branch:
                configured_branch_remote = subprocess.run(
                    ["git", "config", "--get", f"branch.{branch}.remote"],
                    cwd=directories[0], capture_output=True, encoding="utf-8",
                    errors="replace", check=False,
                ).stdout.strip()
                if configured_branch_remote:
                    remote = configured_branch_remote
    return all(
        _configured_fetch_read_only(Path(directory), remote)
        for directory in directories or [Path.cwd()]
    )


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
        if executable in DIRECTORY_CHANGE_COMMANDS or _closed_fetch_allowed(
            git, segment, directories
        ):
            continue
        plain = checked_segment[:next((i for i, token in enumerate(checked_segment) if is_redirection(token)), len(checked_segment))]
        if executable in {"echo", "printf"} or closed_git_listing(plain) or archive_command_is_read_only(
            shlex.join(plain), plain, True, CLOSED_READ_GIT_COMMANDS
        ):
            continue
        if command_can_destroy_files(invocation) and closed_destructive_scope_reason(
            list(invocation[1]), directories
        ) is None:
            # A literal delete entirely outside the repository and every state
            # root is scratch cleanup, not new work on the closed milestone (#468).
            continue
        return closed
    return None


def runtime_hotfix_invocation(tokens):
    """True when any simple command, prefixed or wrapped, runs isolation.py runtime-hotfix."""
    for segment in command_segments(tokens):
        names = [token.replace("\\", "/").rsplit("/", 1)[-1] for token in segment]
        if "isolation.py" in names and "runtime-hotfix" in names[names.index("isolation.py") + 1:]:
            return True
        try:
            wrapped = wrapped_command_tokens(segment, expand_parameters=False)
        except ValueError:  # the shape checks below refuse what cannot be unwrapped
            continue
        if wrapped is not None and runtime_hotfix_invocation(wrapped):
            return True
    return False


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
        # runtime-hotfix is an operator-only recovery (#480): its receipt is
        # the owner authorization a landing later trusts, so an agent running
        # the command self-authorizes. Deny by subcommand name regardless of
        # the script's path.
        if runtime_hotfix_invocation(tokens):
            return (
                "isolation.py runtime-hotfix records the owner authorization a "
                "landing trusts; it is operator-only — request the hotfix from "
                "the orchestrator instead of running it"
            )
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
        if destructive:
            state_reason = destructive_state_root_reason(
                [operand for _, operands in destructive for operand in operands],
                working_directories,
            )
            if state_reason:
                return state_reason
        expression_reason = powershell_expression_reason(tokens)
        if expression_reason:
            return expression_reason
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
                shlex.join(resolved_segment), resolved_segment, archive_context,
                source=(segment, assignments),
            ) and not (
                archive_context
                and bundled_helper
            ):
                if archive_write_attempt(resolved_segment, (segment, assignments)):
                    return ARCHIVE_REASON
                return ARCHIVE_UNPROVEN_READ_REASON
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
