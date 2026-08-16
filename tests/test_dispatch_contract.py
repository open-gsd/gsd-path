"""Cross-check: every logical task name mandated by a skill contract must be
permitted by every platform dispatch adapter.

The skills mandate deterministic logical task names (for example
``logical task name `roadmap``` or the review templates
``review_wave_<wave>_cycle_<cycle>`` with the ``_contract`` / ``_adversarial``
lens suffixes). Each platform adapter under ``platforms/*/dispatch.md`` must
list every one of those names, otherwise a runtime following that adapter
would reject or mangle a dispatch the skill requires.
"""

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Matches "task name `X`", "logical task name `X`", and the multi-line
# "deterministic logical task\n   name `X`" phrasings once whitespace is
# collapsed.
TASK_NAME_PATTERN = re.compile(r"(?:logical\s+)?task\s+name\s+`([^`]+)`")

LENS_SUFFIXES = ("_contract", "_adversarial")


def mandated_task_names():
    """Extract every logical task name mandated by any skill's SKILL.md."""
    names = set()
    for skill_md in sorted(PROJECT_ROOT.glob("skills/gsd-path*/SKILL.md")):
        text = re.sub(r"\s+", " ", skill_md.read_text(encoding="utf-8"))
        names.update(TASK_NAME_PATTERN.findall(text))
    return names


def base_task_names(names):
    """Strip the review lens suffixes so lens forms map to their base name."""
    bases = set()
    for name in names:
        for suffix in LENS_SUFFIXES:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        bases.add(name)
    return bases


def dispatch_adapters():
    """Every platform dispatch adapter that exists (codex/zed were removed)."""
    return sorted((PROJECT_ROOT / "platforms").glob("*/dispatch.md"))


class DispatchContractTests(unittest.TestCase):
    def test_parser_extracts_the_known_anchor_names(self):
        names = mandated_task_names()
        # Anchors that must exist in the skill contracts; if the phrasing in a
        # SKILL.md changes so that the parser misses them, this fails loudly
        # instead of letting the adapter checks pass vacuously.
        self.assertIn("roadmap", names)
        self.assertIn("review_wave_<wave>_cycle_<cycle>", names)
        self.assertIn("review_wave_<wave>_cycle_<cycle>_contract", names)
        self.assertIn("review_wave_<wave>_cycle_<cycle>_adversarial", names)
        self.assertIn("review_plan_panel_<family>", names)
        self.assertIn("review_wave_<wave>_cycle_<cycle>_panel_<family>", names)
        self.assertIn("inspect_codebase", names)
        self.assertIn("inspect_docs", names)

    def test_adapters_exist_including_the_shared_profile(self):
        adapters = dispatch_adapters()
        self.assertTrue(adapters, "no platform dispatch adapters found")
        self.assertIn(
            PROJECT_ROOT / "platforms" / "shared-agents" / "dispatch.md", adapters
        )

    def test_every_mandated_task_name_appears_in_every_adapter(self):
        bases = base_task_names(mandated_task_names())
        self.assertTrue(bases, "no logical task names extracted from skills")
        for adapter in dispatch_adapters():
            adapter_text = adapter.read_text(encoding="utf-8")
            for name in sorted(bases):
                self.assertIn(
                    name,
                    adapter_text,
                    f"{adapter.parent.name}/dispatch.md is missing mandated "
                    f"logical task name {name!r}",
                )

    def test_every_adapter_states_host_isolation_none(self):
        for adapter in dispatch_adapters():
            adapter_text = adapter.read_text(encoding="utf-8")
            self.assertIn(
                "Host isolation: none.",
                adapter_text,
                f"{adapter.parent.name}/dispatch.md is missing the host "
                "isolation contract",
            )

    def test_every_adapter_permits_the_review_lens_suffixes(self):
        for adapter in dispatch_adapters():
            adapter_text = adapter.read_text(encoding="utf-8")
            for suffix in LENS_SUFFIXES:
                self.assertIn(
                    suffix,
                    adapter_text,
                    f"{adapter.parent.name}/dispatch.md is missing the review "
                    f"lens suffix {suffix!r}",
                )


if __name__ == "__main__":
    unittest.main()
