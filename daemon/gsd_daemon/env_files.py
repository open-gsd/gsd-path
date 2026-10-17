"""Read and change a project's ``.env`` files for the native app.

The app lists names only. A value leaves this module in one place, ``reveal``,
for one name. A save changes only the named lines and keeps every other byte.
No message or log made here holds a value.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import subprocess_platform
from .model import is_path_card

FILES = (".env", ".env.local", ".env.development", ".env.production")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
LINE = re.compile(r"(?P<prefix>\s*(?:export\s+)?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)\Z", re.S)
# A value made of these characters needs no quotes in any dotenv reader.
PLAIN = re.compile(r"[A-Za-z0-9_./:@%+,-]*\Z")
ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "$": "$"}
QUOTED = {"'": re.compile(r"'([^']*)'"), '"': re.compile(r'"((?:\\.|[^"\\])*)"', re.S)}
# After the closing quote: spaces and a comment, then the end of the line.
TAIL = re.compile(r"[ \t]*(?:#[^\r\n]*)?[\r\n]*\Z")


def _path(root, name: str) -> Path:
    if name not in FILES:
        raise ValueError(f"the file must be one of: {', '.join(FILES)}")
    path = Path(root) / name
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"{name} is a link or not a regular file; it is not opened")
    return path


def _lines(path: Path) -> List[str]:
    try:
        return path.read_bytes().decode("utf-8").splitlines(keepends=True)
    except FileNotFoundError:
        return []
    except UnicodeDecodeError:
        raise ValueError(f"{path.name} is not UTF-8 text") from None


def _decode(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return re.sub(r"\\(.)", lambda found: ESCAPES.get(found.group(1), found.group(0)), raw[1:-1], flags=re.S)
    return re.split(r"\s+#", raw, maxsplit=1)[0]  # an unquoted value ends at " #"


def _encode(value: str) -> str:
    if PLAIN.match(value):
        return value
    if "'" not in value and "\n" not in value and "\r" not in value:
        return f"'{value}'"  # single quotes: every reader takes the text as it is
    escaped = value
    for char, code in (("\\", "\\\\"), ('"', '\\"'), ("$", "\\$"), ("\n", "\\n"), ("\r", "\\r"), ("\t", "\\t")):
        escaped = escaped.replace(char, code)
    return f'"{escaped}"'


def _quoted(lines: List[str], index: int, start: int, variable: str, name: str) -> Optional[Tuple[int, str]]:
    """(line after the value, value) for the quoted value at ``lines[index][start:]``.
    None when other text follows the closing quote on that line."""
    quote = lines[index][start]
    text = ""
    for end in range(index, len(lines)):
        text += lines[end][start if end == index else 0:]
        match = QUOTED[quote].match(text)
        if not match:
            continue
        if TAIL.match(text, match.end()):
            body = match.group(1)
            if quote == '"':
                body = re.sub(r"\\(.)", lambda found: ESCAPES.get(found.group(1), found.group(0)), body, flags=re.S)
            return end + 1, body
        if end == index:
            return None
        break
    raise ValueError(f"{name}: the quoted value of {variable} does not close at the end of a line")


def _parse(lines: List[str], name: str) -> List[Tuple[int, int, str, str, str]]:
    """(first line, line after the last, prefix, name, value) for each variable.
    A quoted value can span lines."""
    found = []
    index = 0
    while index < len(lines):
        match = LINE.match(lines[index].rstrip("\r\n"))
        end = index + 1
        if match and not lines[index].lstrip().startswith("#"):
            raw = match.group("value")
            span = _quoted(lines, index, match.start("value"), match.group("name"), name) if raw[:1] in QUOTED else None
            end, value = span or (end, _decode(raw))
            found.append((index, end, match.group("prefix"), match.group("name"), value))
        index = end
    return found


def _git_state(root, name: str) -> str:
    def git(*args) -> Optional[int]:
        try:
            return subprocess_platform.run(["git", "-C", str(root), *args], check=False,
                                           capture_output=True, text=True).returncode
        except (OSError, subprocess.SubprocessError):
            return None
    if git("ls-files", "--error-unmatch", "--", name) == 0:
        return "tracked"
    return "ignored" if git("check-ignore", "-q", "--", name) == 0 else "untracked"


def list_file(root, name: str) -> dict:
    path = _path(root, name)
    values: Dict[str, str] = {}
    for _start, _end, _prefix, variable, value in _parse(_lines(path), name):
        values[variable] = value  # a repeated name: the last line wins, as in a shell
    return {"file": name, "exists": path.exists(), "git": _git_state(root, name),
            "vars": [{"name": variable, "empty": value == ""} for variable, value in values.items()]}


def reveal(root, name: str, variable: str) -> str:
    for _start, _end, _prefix, found, value in reversed(_parse(_lines(_path(root, name)), name)):
        if found == variable:
            return value
    raise ValueError(f"{name} has no variable with that name")


def save(root, name: str, changes, dry_run: bool = False) -> dict:
    """Apply ``[{"name", "value"} | {"name", "remove": true}]``. Returns the diff by name."""
    path = _path(root, name)
    if not isinstance(changes, list) or not all(isinstance(change, dict) for change in changes):
        raise ValueError("changes must be a list")
    names = [change.get("name") for change in changes]
    if not all(isinstance(variable, str) and NAME.match(variable) for variable in names):
        raise ValueError("a variable name has letters, digits, and _ only, and does not start with a digit")
    if len(set(names)) != len(names):
        raise ValueError("a variable is named more than once")

    lines = _lines(path)
    ending = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
    parsed = _parse(lines, name)
    diff = []
    for change in changes:
        variable = change["name"]
        at = [(start, end, prefix, old) for start, end, prefix, found, old in parsed if found == variable]
        if change.get("remove") is True:
            if not at:
                raise ValueError(f"{name} has no variable {variable} to remove")
            for start, end, _prefix, _old in at:
                lines[start:end] = [""] * (end - start)
            diff.append({"name": variable, "change": "remove"})
            continue
        value = change.get("value")
        if not isinstance(value, str):
            raise ValueError(f"{variable} needs a text value, or remove: true")
        if at:
            start, end, prefix, old = at[-1]
            if old == value:
                continue
            lines[start:end] = [f"{prefix}{variable}={_encode(value)}{ending}"] + [""] * (end - start - 1)
            diff.append({"name": variable, "change": "change"})
        else:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += ending
            lines.append(f"{variable}={_encode(value)}{ending}")
            diff.append({"name": variable, "change": "add"})
    if dry_run or not diff:
        return {"written": False, "diff": diff}

    mode = (path.stat().st_mode & 0o777) if path.exists() else 0o600
    handle, temporary = tempfile.mkstemp(prefix=name + ".", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as out:
            out.write("".join(lines).encode("utf-8"))
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return {"written": True, "diff": diff}


# -- routes ---------------------------------------------------------------------

class Refused(Exception):
    status = 403


def _project(handler, body: dict) -> str:
    # Env content leaves only a daemon whose writes need the token (the app's own daemon).
    if not handler.token:
        raise Refused("Environment editing needs the OpenGSD Path app. "
                      "Restart the monitor from the app, then try again.")
    root = body.get("root")
    if not is_path_card(handler.watcher.projects, root):
        raise ValueError("root is not a watched project")
    return root


def list_route(handler, body: dict) -> dict:
    return list_file(_project(handler, body), body.get("file"))


def reveal_route(handler, body: dict) -> dict:
    root = _project(handler, body)
    name = body.get("name")
    if not isinstance(name, str):
        raise ValueError("name is required")
    return {"value": reveal(root, body.get("file"), name)}


def save_route(handler, body: dict) -> dict:
    return save(_project(handler, body), body.get("file"), body.get("changes"), dry_run=bool(body.get("dry_run")))
