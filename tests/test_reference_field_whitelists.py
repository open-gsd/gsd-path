"""Reference task-field whitelists must match the runtime's own field sets."""

import re
import unittest
from pathlib import Path

from scripts import isolation

ROOT = Path(__file__).resolve().parents[1]
WAVE_REFERENCE = ROOT / "skills/gsd-path/references/reviewer-wave.md"
CODER_REFERENCE = ROOT / "skills/gsd-path/references/coder.md"

WAVE_WHITELIST = re.compile(
    r"allow orchestrator-owned (?P<fields>.*?) plus append-only Log", re.S)
CODER_NEVER_EDIT = re.compile(r"Never edit (?P<fields>.*?)\.", re.S)
BACKTICKED = re.compile(r"`([a-z_]+)`")
NEGATION = re.compile(r"\b(exclude|except|never|not|but|block)\b")


def runtime_owned_fields():
    return set(isolation.MEMBER_ACTIVATION_FIELDS) | set(isolation.LANDING_MUTABLE_FIELDS)


class ReferenceFieldWhitelistTests(unittest.TestCase):
    def assert_permitting(self, fragment: str) -> None:
        # A negated mention ("exclude `member_base`") must not count as allowed.
        self.assertIsNone(
            NEGATION.search(fragment),
            f"whitelist sentence now negates a field: {fragment!r}")

    def test_wave_reference_permits_exactly_the_runtime_fields(self) -> None:
        match = WAVE_WHITELIST.search(WAVE_REFERENCE.read_text(encoding="utf-8"))
        self.assertIsNotNone(
            match, "reviewer-wave.md lost its orchestrator-owned whitelist sentence")
        self.assert_permitting(match.group("fields"))
        self.assertEqual(
            set(BACKTICKED.findall(match.group("fields"))),
            runtime_owned_fields(),
            "reviewer-wave.md's allowed task-file fields drifted from "
            "scripts/isolation.py (MEMBER_ACTIVATION_FIELDS | "
            "LANDING_MUTABLE_FIELDS); update the sentence to match the runtime",
        )

    def test_coder_reference_names_every_runtime_field(self) -> None:
        match = CODER_NEVER_EDIT.search(CODER_REFERENCE.read_text(encoding="utf-8"))
        self.assertIsNotNone(match, "coder.md lost its never-edit rule")
        self.assert_permitting(match.group("fields"))
        self.assertEqual(
            set(BACKTICKED.findall(match.group("fields"))),
            runtime_owned_fields(),
            "coder.md's never-edit field list drifted from scripts/isolation.py; "
            "update the rule to match the runtime",
        )


if __name__ == "__main__":
    unittest.main()
