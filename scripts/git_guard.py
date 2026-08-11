#!/usr/bin/env python3
"""Git commit-msg and pre-commit guard for GSD Path projects.

Blocks a commit that modifies, deletes, or renames away any path under a
committed .project/archive/ tree, and blocks a ship commit (subject
`ship: ...`) that stages paths outside .project/. Adding new files to an
archive stays allowed: the ship transaction moves artifacts in.

Installed as .git/hooks/commit-msg:

    exec python3 "$(git rev-parse --show-toplevel)/.gsd-path/git_guard.py" commit-msg "$1"

Installed as .git/hooks/pre-commit:

    exec python3 "$(git rev-parse --show-toplevel)/.gsd-path/git_guard.py" pre-commit

A git failure skips the guard (exit 0) so a broken environment can never
brick commits; violations exit 1 with the offending paths on stderr.
"""

import subprocess
import sys
from pathlib import Path

ARCHIVE_PREFIX = ".project/archive/"
GUARD_MARKER = "gsd-path guard"


def staged_entries():
    output = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "-z", "--find-renames"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    tokens = output.split("\0")
    entries = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        if not status:
            index += 1
            continue
        code = status[0]
        if code in "RC":
            entries.append((code, tokens[index + 1], tokens[index + 2]))
            index += 3
        else:
            entries.append((code, tokens[index + 1], None))
            index += 2
    return entries


def subject_of(message_file):
    for line in Path(message_file).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def is_ship_commit(subject):
    return subject.strip().casefold().startswith("ship:")


def violations(entries, subject):
    found = []
    for code, old, new in entries:
        if code in "MDTR" and old.startswith(ARCHIVE_PREFIX):
            label = f"{code} {old}" + (f" -> {new}" if new else "")
            found.append(f"{label}: committed archives are read-only")
    if is_ship_commit(subject):
        for code, old, new in entries:
            for path in (old, new):
                if path and not path.startswith(".project/"):
                    found.append(
                        f"{code} {path}: a ship commit may only touch .project/"
                    )
    return found


def commit_subject(argv):
    if len(argv) <= 1:
        return ""
    if argv[1] == "pre-commit":
        # At pre-commit time .git/COMMIT_EDITMSG still holds the PREVIOUS
        # commit's message, so subject rules cannot be enforced here; the
        # commit-msg hook enforces them with the real message.
        return ""
    if argv[1] == "commit-msg" and len(argv) > 2:
        return subject_of(argv[2])
    return subject_of(argv[1])


def main(argv):
    try:
        entries = staged_entries()
        subject = commit_subject(argv)
    except Exception as error:
        print(f"gsd-path guard: skipped ({error})", file=sys.stderr)
        return 0
    found = violations(entries, subject)
    if found:
        print("gsd-path guard blocked the commit:", file=sys.stderr)
        for violation in found:
            print(f"  {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
