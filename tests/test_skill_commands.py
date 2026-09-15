"""Every helper command a skill documents must parse against the helper's CLI."""

import re
import subprocess
import sys
import unittest
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SKILLS = sorted([*ROOT.glob("skills/gsd-path*/SKILL.md"),
                 *ROOT.glob("skills/gsd-path/references/*.md")])

# `python3 <absolute helper.py> subcommand --flag ...` inside one code span or
# fenced block; a trailing `\` joins the next line.
COMMAND_RE = re.compile(r"python3 <absolute (?P<script>[a-z_]+\.py)>(?P<rest>[^`]*)")
FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
PLACEHOLDER_RE = re.compile(r"<[^<>]*>")


def documented_commands():
    for skill in SKILLS:
        text = skill.read_text(encoding="utf-8")
        for match in COMMAND_RE.finditer(text):
            rest = PLACEHOLDER_RE.sub(" ", match.group("rest").replace("\\\n", " "))
            tokens = rest.split()
            subcommand = tokens[0] if tokens and not tokens[0].startswith("-") else None
            flags = set(FLAG_RE.findall(rest))
            yield skill.relative_to(ROOT), match.group("script"), subcommand, flags


@lru_cache(maxsize=None)
def help_text(script, subcommand):
    argv = [sys.executable, str(SCRIPTS / script)]
    if subcommand:
        argv.append(subcommand)
    argv.append("--help")
    return subprocess.run(argv, capture_output=True, text=True)


class SkillCommandTest(unittest.TestCase):
    def test_every_documented_command_parses(self):
        for skill, script, subcommand, flags in documented_commands():
            with self.subTest(skill=str(skill), script=script, subcommand=subcommand):
                self.assertTrue((SCRIPTS / script).is_file(), f"{script} does not exist")
                result = help_text(script, subcommand)
                self.assertEqual(
                    result.returncode,
                    0,
                    f"{script} {subcommand or ''} --help failed: {result.stderr.strip()}",
                )
                known = set(FLAG_RE.findall(result.stdout))
                self.assertEqual(
                    flags - known,
                    set(),
                    f"{skill} documents flags {script} {subcommand or ''} does not accept",
                )


if __name__ == "__main__":
    unittest.main()
