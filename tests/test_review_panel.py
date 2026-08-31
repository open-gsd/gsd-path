import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import review_panel


def family_artifact(family: str, model: str, findings: str, kind: str = "plan") -> str:
    heading = f"# Plan panel — {family}" if kind == "plan" else f"# Panel — wave 1, cycle 1"
    return f"""{heading}

- Family: {family}
- Model: {model}

## Findings

{findings}
"""


class ReviewPanelParseTests(unittest.TestCase):
    def test_default_is_off(self) -> None:
        parsed = review_panel.parse_sources("# Plan\n", "# Intent\n")
        self.assertEqual(parsed["mode"], "off")
        self.assertEqual(parsed["source"], "default")

    def test_plan_wins_over_intent(self) -> None:
        parsed = review_panel.parse_sources(
            "## Config\n- review_panel: off\n",
            "Review panel: detected\n",
        )
        self.assertEqual(parsed, {"mode": "off", "families": (), "source": "plan"})

    def test_intent_used_when_plan_omits_key(self) -> None:
        parsed = review_panel.parse_sources(
            "## Config\n- max_review_cycles: 3\n",
            "Review panel: claude,gpt\n",
        )
        self.assertEqual(parsed["mode"], "named")
        self.assertEqual(parsed["families"], ("claude", "gpt"))
        self.assertEqual(parsed["source"], "intent")

    def test_charter_used_when_plan_and_intent_omit_key(self) -> None:
        parsed = review_panel.parse_sources(
            "## Config\n- max_review_cycles: 3\n",
            "# Intent\n",
            "Review panel: detected\n",
        )
        self.assertEqual(
            parsed, {"mode": "detected", "families": (), "source": "charter"}
        )

    def test_intent_wins_over_charter(self) -> None:
        parsed = review_panel.parse_sources(
            "# Plan\n",
            "Review panel: off\n",
            "Review panel: detected\n",
        )
        self.assertEqual(parsed, {"mode": "off", "families": (), "source": "intent"})

    def test_plan_wins_over_charter(self) -> None:
        parsed = review_panel.parse_sources(
            "## Config\n- review_panel: claude,gpt\n",
            "# Intent\n",
            "Review panel: detected\n",
        )
        self.assertEqual(parsed["source"], "plan")
        self.assertEqual(parsed["families"], ("claude", "gpt"))

    def test_named_unknown_family_errors(self) -> None:
        with self.assertRaises(review_panel.ReviewPanelError):
            review_panel.parse_review_panel_value("claude,banana")

    def test_named_cap_errors(self) -> None:
        with self.assertRaises(review_panel.ReviewPanelError):
            review_panel.parse_review_panel_value("claude,gpt,grok,composer")

    def test_named_new_families_parse(self) -> None:
        parsed = review_panel.parse_review_panel_value("kimi,qwen")
        self.assertEqual(parsed, {"mode": "named", "families": ("kimi", "qwen")})

    def test_plan_review_panel_enabled(self) -> None:
        self.assertFalse(review_panel.plan_review_panel_enabled("# Plan\n"))
        self.assertFalse(
            review_panel.plan_review_panel_enabled("- review_panel: off\n")
        )
        self.assertTrue(
            review_panel.plan_review_panel_enabled("- review_panel: detected\n")
        )
        self.assertTrue(
            review_panel.plan_review_panel_enabled("- review_panel: not-a-mode\n")
        )


class ReviewPanelResolveTests(unittest.TestCase):
    ADVERTISED = (
        "inherit",
        "claude-opus-4-7-thinking-xhigh",
        "claude-opus-5-thinking-high",
        "composer-2.5-fast",
        "cursor-grok-4.5-high-fast",
        "cursor-grok-4.6-high-fast",
        "gpt-5.4-medium",
        "gpt-5.6-sol-medium",
    )

    def test_groups_latest_per_family(self) -> None:
        grouped = review_panel.group_advertised(self.ADVERTISED)
        self.assertEqual(
            review_panel.latest_slug(grouped["claude"]),
            "claude-opus-5-thinking-high",
        )
        self.assertEqual(
            review_panel.latest_slug(grouped["gpt"]), "gpt-5.6-sol-medium"
        )
        self.assertEqual(
            review_panel.latest_slug(grouped["grok"]),
            "cursor-grok-4.6-high-fast",
        )
        self.assertNotIn("inherit", [slug for slugs in grouped.values() for slug in slugs])

    def test_detected_skips_parent_and_caps(self) -> None:
        resolved = review_panel.resolve_panel(
            {"mode": "detected", "families": ()},
            self.ADVERTISED,
            parent_slug="cursor-grok-4.6-high-fast",
        )
        self.assertEqual(resolved["status"], "ready")
        families = [item["family"] for item in resolved["selected"]]
        self.assertEqual(families, ["claude", "gpt", "composer"])
        self.assertNotIn("grok", families)
        self.assertTrue(
            any(item["family"] == "grok" and item["reason"] == "parent family" for item in resolved["skipped"])
        )

    def test_named_missing_family_errors(self) -> None:
        with self.assertRaises(review_panel.ReviewPanelError):
            review_panel.resolve_panel(
                {"mode": "named", "families": ("claude", "gpt")},
                ("cursor-grok-4.6-high-fast",),
            )

    def test_named_parent_only_errors(self) -> None:
        with self.assertRaises(review_panel.ReviewPanelError):
            review_panel.resolve_panel(
                {"mode": "named", "families": ("grok",)},
                self.ADVERTISED,
                parent_family="grok",
            )

    def test_detected_without_cross_model_skips(self) -> None:
        resolved = review_panel.resolve_panel(
            {"mode": "detected", "families": ()},
            ("cursor-grok-4.6-high-fast",),
            parent_family="grok",
        )
        self.assertEqual(resolved["status"], "skipped")

    def test_new_family_slugs_classify(self) -> None:
        cases = {
            "gemini-2.5-pro": "gemini",
            "deepseek-v3.2-exp": "deepseek",
            "kimi-k2-thinking": "kimi",
            "moonshot-v1-128k": "kimi",
            "qwen3-coder-plus": "qwen",
        }
        for slug, family in cases.items():
            with self.subTest(slug=slug):
                self.assertEqual(review_panel.family_of_slug(slug), family)

    def test_exact_match_beats_digit_stem(self) -> None:
        self.assertEqual(review_panel.family_of_slug("composer2-claude"), "claude")
        self.assertEqual(review_panel.family_of_slug("gpt4"), "gpt")

    def test_detected_caps_new_families_in_known_order(self) -> None:
        resolved = review_panel.resolve_panel(
            {"mode": "detected", "families": ()},
            (
                "qwen3-coder-plus",
                "kimi-k2-thinking",
                "deepseek-v3.2-exp",
                "gemini-2.5-pro",
            ),
            parent_family="claude",
        )
        self.assertEqual(resolved["status"], "ready")
        families = [item["family"] for item in resolved["selected"]]
        self.assertEqual(families, ["gemini", "deepseek", "kimi"])
        self.assertTrue(
            any(
                item["family"] == "qwen" and item["reason"] == "cap"
                for item in resolved["skipped"]
            )
        )

    def test_off_does_not_inspect_slugs(self) -> None:
        resolved = review_panel.resolve_panel(
            {"mode": "off", "families": ()}, ()
        )
        self.assertEqual(resolved["status"], "off")


class ReviewPanelMergeTests(unittest.TestCase):
    def write(self, directory: Path, name: str, content: str) -> Path:
        path = directory / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_merge_splits_actionable_and_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            claude = self.write(
                root,
                "claude.md",
                family_artifact(
                    "claude",
                    "claude-opus-5-thinking-high",
                    """### F1
- Severity: high
- Kind: criterion
- Criterion: T001 acceptance 1
- Evidence: src/app.py:12
- Found: missing auth check
- Fix direction: reject unauthenticated requests
""",
                ),
            )
            gpt = self.write(
                root,
                "gpt.md",
                family_artifact(
                    "gpt",
                    "gpt-5.6-sol-medium",
                    """### F1
- Severity: low
- Kind: criterion
- Criterion: T001 acceptance 1
- Evidence: src/app.py:12
- Found: auth is present
- Fix direction: none
""",
                ),
            )
            output = root / "PLAN-PANEL.md"
            result = review_panel.merge_artifacts(
                "plan",
                (claude, gpt),
                output,
                (("Mode", "detected"),),
            )
            text = output.read_text(encoding="utf-8")
            self.assertEqual(result["actionable"], 1)
            self.assertEqual(result["warnings"], 1)
            self.assertEqual(result["conflicts"], 1)
            self.assertIn("Mode: detected", text)
            self.assertIn("# Plan panel — claude", text)
            self.assertIn("# Plan panel — gpt", text)

    def test_merge_allows_empty_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.write(
                root,
                "claude.md",
                family_artifact("claude", "claude-opus-5-thinking-high", "- none\n"),
            )
            output = root / "PLAN-PANEL.md"
            result = review_panel.merge_artifacts("plan", (source,), output, ())
            self.assertEqual(result["actionable"], 0)
            self.assertIn("- none", output.read_text(encoding="utf-8"))


class ReviewPanelCliTests(unittest.TestCase):
    def test_resolve_cli_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = Path(temporary) / "PLAN.md"
            plan.write_text("## Config\n- review_panel: detected\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()) as captured:
                code = review_panel.main(
                    [
                        "resolve",
                        "--plan",
                        str(plan),
                        "--advertised",
                        "claude-opus-5-thinking-high,gpt-5.6-sol-medium",
                        "--parent-family",
                        "grok",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn('"status": "ready"', captured.getvalue())

    def test_named_missing_cli_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = Path(temporary) / "PLAN.md"
            plan.write_text("## Config\n- review_panel: claude,gpt\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                code = review_panel.main(
                    [
                        "resolve",
                        "--plan",
                        str(plan),
                        "--advertised",
                        "cursor-grok-4.6-high-fast",
                    ]
                )
            self.assertEqual(code, 2)

    def test_parse_cli_reads_charter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            charter = Path(temporary) / "CHARTER.md"
            charter.write_text("Review panel: detected\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()) as captured:
                code = review_panel.main(["parse", "--charter", str(charter)])
            self.assertEqual(code, 0)
            self.assertIn('"source": "charter"', captured.getvalue())
            self.assertIn('"mode": "detected"', captured.getvalue())


if __name__ == "__main__":
    unittest.main()
