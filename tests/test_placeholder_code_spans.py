"""Archive validators scan review values while their code spans stay intact."""

import tempfile
import unittest
from pathlib import Path

from scripts.archive_milestone import ArchiveError
from scripts.check_handoffs import HandoffError, _source_field
from scripts.discussion_validate import (
    completed_bullet_field,
    parse_final_review,
    validate_gap_reviews,
)

BT = "`"
HEAD = "0123456789abcdef0123456789abcdef01234567"

MULTI_SPAN = (
    f"{BT}git diff --stat a1b2c3d e4f5a6b{BT} then {BT}cmp{BT} of each fixture against "
    f"{BT}tests/fixtures/<same basename>{BT}; {BT}npm run check:contract{BT} in a sidecar"
)
MULTI_SPAN_BOTH_ENDS = (
    f"{BT}cmp a.json{BT} against {BT}tests/fixtures/<same basename>{BT} and "
    f"{BT}Array<string>{BT}"
)
UNQUOTED = f"{BT}npm test{BT} against <path to the suite>"
WHOLLY = f"{BT}<command>{BT}"

ACCEPTED = (MULTI_SPAN, MULTI_SPAN_BOTH_ENDS)
REJECTED = (UNQUOTED, WHOLLY)


def evidence_block(check):
    return (
        "## Checked evidence\n\n"
        f"- **Check**: {check}\n"
        "- **Observed**: All fixtures match.\n"
        "- **Reference**: scripts/check.mjs\n"
    )


def gate(check):
    return _source_field(evidence_block(check), "Check", "final-gap-1.md")


def archive(check):
    return completed_bullet_field(
        evidence_block(check).splitlines(), "Check", "final-gap-1.md"
    )


def write_archive(root: Path, check: str) -> Path:
    archive_dir = root / "001-example"
    (archive_dir / "review").mkdir(parents=True)
    (archive_dir / "intent").mkdir()
    (archive_dir / "intent" / "INTENT.md").write_text(
        "# Intent\n\n## Success criteria\n\n1. Fixtures match the platform.\n",
        encoding="utf-8",
    )
    (archive_dir / "review" / "FINAL.md").write_text(
        f"# Final Review\n\nReviewed HEAD: {HEAD}\nOverall verdict: pass\n\n"
        "## Success criteria\n\n"
        "### SC1 — Fixtures match the platform.\n\n"
        "- **Verdict**: met\n"
        f"- **Check**: {check}\n"
        "- **Observed**: All fixtures match.\n"
        "- **Reference**: none\n"
        "- **Finding**: none\n"
        "- **Fix direction**: none\n",
        encoding="utf-8",
    )
    (archive_dir / "review" / "final-gap-1.md").write_text(
        "# Gap Review — 1: fixtures versus consumers\n\n"
        f"Reviewed HEAD: {HEAD}\nGap verdict: pass\nRisk: fixtures versus consumers\n"
        "Waves checked: 1\n\n"
        + evidence_block(check)
        + "\n## Finding\n\n- **Found**: The fixtures match.\n- **Fix direction**: none\n",
        encoding="utf-8",
    )
    return archive_dir


class PlaceholderCodeSpanTest(unittest.TestCase):
    def test_multi_span_value_is_accepted_by_the_archive_reader(self):
        for value in ACCEPTED:
            with self.subTest(value=value):
                self.assertEqual(archive(value), value.strip(BT))

    def test_real_placeholders_are_rejected_by_the_archive_reader(self):
        for value in REJECTED:
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ArchiveError, "requires one completed Check field"
                ):
                    archive(value)

    def test_final_gate_and_archive_reader_agree(self):
        for value in ACCEPTED:
            with self.subTest(value=value):
                self.assertEqual(gate(value), archive(value))
        for value in REJECTED:
            with self.subTest(value=value):
                with self.assertRaises(HandoffError):
                    gate(value)
                with self.assertRaises(ArchiveError):
                    archive(value)

    def test_gap_review_with_multi_span_check_validates(self):
        for value in ACCEPTED:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                validate_gap_reviews(write_archive(Path(temporary), value), HEAD)

    def test_gap_review_with_real_placeholder_fails(self):
        for value in REJECTED:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaisesRegex(
                    ArchiveError, "requires one completed Check field"
                ):
                    validate_gap_reviews(write_archive(Path(temporary), value), HEAD)

    def test_final_criterion_with_multi_span_check_is_accepted(self):
        for value in ACCEPTED:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                head, criteria = parse_final_review(
                    write_archive(Path(temporary), value)
                )
                self.assertEqual(head, HEAD)
                self.assertEqual(
                    criteria,
                    [("Fixtures match the platform.", "met", value.strip(BT))],
                )

    def test_final_criterion_with_real_placeholder_is_rejected(self):
        for value in REJECTED:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaisesRegex(
                    ArchiveError, "criterion is incomplete"
                ):
                    parse_final_review(write_archive(Path(temporary), value))


if __name__ == "__main__":
    unittest.main()
