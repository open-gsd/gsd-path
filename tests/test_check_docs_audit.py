import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import check_docs_audit

AUDIT = """# Docs Audit

Repo root: /repo
Audited: 2026-08-21
Audited HEAD: none
Alignment mode: no

## Summary

| Verdict | Count |
|---------|-------|
| verified | {verified} |
| stale | 1 |
| aspirational | 0 |
| unverifiable | 0 |
| descriptive docs (no testable claims) | 1 |

Worst drift: README promises a flag that does not exist.

## Doc: README.md

| Claim | Type | Verdict | Evidence |
|-------|------|---------|----------|
| "Run `app 3` prints `3`" | command | verified | `app 3` → `3` |
| "`--json` prints JSON" | feature | stale | `app 3 --json` → `3`, no json in `app.py` (`grep json app.py \\| wc -l` → 0) |

## Descriptive docs

- CONTRIBUTING.md

## User rulings

| Queue # | Ruling | User's words | Planned |
|---------|--------|--------------|---------|

## Remediation queue

| # | Doc | Claim | Verdict | Class | Suggested action |
|---|-----|-------|---------|-------|------------------|
| 1 | README.md | "`--json` prints JSON" | stale | fix-doc | drop the flag from README |
"""

RULING_HEADER = """| Queue # | Ruling | User's words | Planned |
|---------|--------|--------------|---------|
"""


def with_rulings(text: str, *rows: str) -> str:
    return text.replace(RULING_HEADER, RULING_HEADER + "".join(row + "\n" for row in rows))


class CheckDocsAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        for name in ("README.md", "CONTRIBUTING.md", "node_modules/x/README.md",
                     ".project/archive/001-old/MANIFEST.md", ".project/intent/INTENT.md",
                     ".claude/skills/gsd-path/SKILL.md"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A", "-f"], cwd=self.repo, check=True)
        self.write(AUDIT.format(verified=1))

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, text, path=check_docs_audit.DEFAULT_AUDIT):
        path = self.repo / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            text.replace("Repo root: /repo", f"Repo root: {self.repo.resolve()}"),
            encoding="utf-8",
        )

    def run_gate(self, *args):
        result = subprocess.run(
            ["python3", str(Path(check_docs_audit.__file__)), "--repo", str(self.repo), *args],
            capture_output=True, text=True,
        )
        return result.returncode, result.stdout, result.stderr

    def test_valid_audit_passes_with_derived_inventory(self):
        code, out, err = self.run_gate()
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result["docs"], ["README.md"])
        self.assertEqual(result["descriptive"], ["CONTRIBUTING.md"])
        self.assertEqual(result["verdicts"], {"verified": 1, "stale": 1, "aspirational": 0, "unverifiable": 0})
        self.assertEqual(result["queue"], 1)
        self.assertEqual(result["rulings"], 0)

    def test_user_rulings_have_a_fixed_format(self):
        invalid = with_rulings(
            AUDIT.format(verified=1),
            '| 1 | maybe | "keep it" | no |',
        )
        self.write(invalid)
        self.assertIn("invalid ruling", self.run_gate()[2])

        invalid_planned = with_rulings(
            AUDIT.format(verified=1),
            '| 1 | fix-code | "implement it" | someday |',
        )
        self.write(invalid_planned)
        self.assertIn("Planned must be no or a T###", self.run_gate()[2])

    def test_prior_user_rulings_and_planned_values_are_preserved(self):
        prior = self.repo / "prior-audit.txt"
        self.write(
            with_rulings(AUDIT.format(verified=1), '| 1 | fix-code | "implement the flag" | no |'),
            "prior-audit.txt",
        )

        code, _, error = self.run_gate("--prior-audit", str(prior))
        self.assertEqual(1, code)
        self.assertIn("preserve every prior row", error)

        self.write(
            with_rulings(
                AUDIT.format(verified=1),
                '| 1 | fix-code | "implement the flag" | T001 |',
            )
        )
        code, _, error = self.run_gate("--prior-audit", str(prior))
        self.assertEqual(1, code)
        self.assertIn("Planned value", error)

        self.write(
            with_rulings(
                AUDIT.format(verified=1),
                '| 1 | fix-code | "implement the flag" | no |',
                '| 2 | accept-drift | "keep the promise" | n/a (accept-drift) |',
            )
        )
        code, output, error = self.run_gate("--prior-audit", str(prior))
        self.assertEqual(0, code, error)
        self.assertEqual(2, json.loads(output)["rulings"])

    def test_carried_rows_repeat_prior_verified_rows_outside_the_changed_set(self):
        fresh = '| "Run `app 3` prints `3`" | command | verified | `app 3` → `3` |'
        prior_row = '| "Run `app 3` prints `3`" | feature | verified | `app.py:3` → `3` |'
        carried_row = prior_row.replace("| verified | ", "| verified | unchanged: ")
        prior_audit = AUDIT.format(verified=1).replace(fresh, prior_row)
        carried = AUDIT.format(verified=1).replace(fresh, carried_row)
        cases = (
            (carried, prior_audit, ["--changed"], "--changed requires --prior-audit"),
            (carried, prior_audit, ["--prior-audit"], "require --prior-audit and --changed"),
            (carried, AUDIT.format(verified=1), ["--prior-audit", "--changed"], "does not repeat a prior verified row"),
            (carried, prior_audit, ["--prior-audit", "--changed"], None),
            (carried, prior_audit, ["--prior-audit", "--changed", "app.py"], "changed since the prior audit: app.py"),
            (carried, prior_audit, ["--prior-audit", "--changed", "README.md"], "changed since the prior audit: README.md"),
            (
                carried.replace("`app.py:3` → `3`", "src/parsers/"),
                prior_audit.replace("`app.py:3` → `3`", "src/parsers/"),
                ["--prior-audit", "--changed", "src/parsers/core.py"],
                "changed since the prior audit: src/parsers/core.py",
            ),
            (
                carried.replace("| feature | verified |", "| command | verified |"),
                prior_audit.replace("| feature | verified |", "| command | verified |"),
                ["--prior-audit", "--changed"],
                "only verified non-command claims carry forward",
            ),
        )
        for audit, prior, flags, expected in cases:
            with self.subTest(flags=flags, expected=expected):
                self.write(audit)
                self.write(prior, "prior-audit.txt")
                (self.repo / "changed.txt").write_text("\n".join(flags[2:]) + "\n", encoding="utf-8")
                args = []
                if "--prior-audit" in flags:
                    args += ["--prior-audit", str(self.repo / "prior-audit.txt")]
                if "--changed" in flags:
                    args += ["--changed", str(self.repo / "changed.txt")]
                code, _, error = self.run_gate(*args)
                if expected is None:
                    self.assertEqual(0, code, error)
                else:
                    self.assertEqual(1, code)
                    self.assertIn(expected, error)

    def test_derived_inventory_excludes_vendored_archive_skills_and_project_unless_alignment(self):
        inventory = check_docs_audit.derive_inventory(self.repo, check_docs_audit.DEFAULT_AUDIT, alignment=False)
        self.assertEqual(inventory, ["CONTRIBUTING.md", "README.md"])
        aligned = check_docs_audit.derive_inventory(self.repo, check_docs_audit.DEFAULT_AUDIT, alignment=True)
        self.assertEqual(aligned, [".project/intent/INTENT.md", "CONTRIBUTING.md", "README.md"])

    def test_inventory_command_includes_untracked_non_ignored_markdown(self):
        (self.repo / "NOTES.md").write_text("notes\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("IGNORED.md\n", encoding="utf-8")
        (self.repo / "IGNORED.md").write_text("ignored\n", encoding="utf-8")

        code, out, err = self.run_gate("--emit-inventory")

        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), ["CONTRIBUTING.md", "NOTES.md", "README.md"])

    def test_explicit_inventory_wins(self):
        (self.repo / "inventory.txt").write_text("README.md\nCONTRIBUTING.md\nDOCS.md\n", encoding="utf-8")
        code, _, err = self.run_gate("--inventory", str(self.repo / "inventory.txt"))
        self.assertEqual(code, 1)
        self.assertIn("not audited: DOCS.md", err)

    def test_summary_counts_must_match_rows(self):
        self.write(AUDIT.format(verified=2))
        code, _, err = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn("verified count 2 does not match 1", err)

    def test_header_is_unique_and_bound_to_the_repo_and_date(self):
        valid = AUDIT.format(verified=1)
        cases = (
            (valid.replace("Audited: 2026-08-21", "Audited: yesterday"), "ISO date"),
            (valid.replace("Repo root: /repo", "Repo root: /wrong"), "does not match"),
            (valid.replace("Audited HEAD: none", "Audited HEAD: abc123"), "40-hex commit or none"),
            (
                valid.replace(
                    "Repo root: /repo", "Repo root: /repo\nRepo root: /repo"
                ),
                "exactly one Repo root",
            ),
        )
        for audit, expected in cases:
            with self.subTest(expected=expected):
                self.write(audit)
                code, _, error = self.run_gate()
                self.assertEqual(1, code)
                self.assertIn(expected, error)

    def test_rejects_doc_sections_that_normalize_to_the_same_path(self):
        duplicate = AUDIT.format(verified=2).replace(
            "## Descriptive docs",
            """## Doc: `README.md`

| Claim | Type | Verdict | Evidence |
|-------|------|---------|----------|
| "The command runs" | command | verified | `app 3` returned `3` |

## Descriptive docs""",
        )
        self.write(duplicate)

        code, _, error = self.run_gate()

        self.assertEqual(1, code)
        self.assertIn("duplicate normalized Doc section", error)

    def test_rejects_placeholder_evidence_but_allows_angle_brackets_in_prose(self):
        self.write(AUDIT.format(verified=1).replace("`app 3` → `3`", "<file:line>"))
        code, _, err = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn("placeholder", err)
        self.write(AUDIT.format(verified=1).replace("`app 3` → `3`", "ran `app <n>` → `3`"))
        self.assertEqual(self.run_gate()[0], 0)

    def test_doc_section_requires_a_claim_row(self):
        audit = AUDIT.format(verified=1)
        claim_table = """| Claim | Type | Verdict | Evidence |
|-------|------|---------|----------|
| "Run `app 3` prints `3`" | command | verified | `app 3` → `3` |
| "`--json` prints JSON" | feature | stale | `app 3 --json` → `3`, no json in `app.py` (`grep json app.py \\| wc -l` → 0) |
"""
        self.write(audit.replace(claim_table, "| Claim | Type | Verdict | Evidence |\n|-------|------|---------|----------|\n"))

        code, _, error = self.run_gate()

        self.assertEqual(1, code)
        self.assertIn("requires at least one claim row", error)

    def test_literal_none_is_not_claim_evidence_or_action(self):
        audit = AUDIT.format(verified=1)
        for original, label in (
            ("`app 3` → `3`", "evidence"),
            ("drop the flag from README", "action"),
        ):
            with self.subTest(label=label):
                self.write(audit.replace(original, "NoNe"))
                code, _, error = self.run_gate()
                self.assertEqual(1, code)
                self.assertIn("placeholder or empty", error)

    def test_rejects_doc_listed_as_both_claims_and_descriptive(self):
        self.write(AUDIT.format(verified=1).replace("- CONTRIBUTING.md", "- CONTRIBUTING.md\n- README.md"))
        code, _, err = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn("both", err)

    def test_remediation_queue_must_cover_every_non_verified_claim(self):
        self.write(AUDIT.format(verified=1).replace("| 1 | README.md | \"`--json` prints JSON\" | stale | fix-doc | drop the flag from README |\n", ""))
        code, _, err = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn("Remediation queue has 0 rows for 1", err)

    def test_remediation_queue_rows_bind_exact_claims_with_contiguous_numbers(self):
        audit = AUDIT.format(verified=1).replace(
            '| "`--json` prints JSON" | feature | stale | `app 3 --json` → `3`, no json in `app.py` (`grep json app.py \\| wc -l` → 0) |',
            '| "`--json` prints JSON" | feature | stale | `app 3 --json` → `3`, no json in `app.py` (`grep json app.py \\| wc -l` → 0) |\n'
            '| "Output is colored" | feature | aspirational | No color option exists in `app.py`. |',
        ).replace("| aspirational | 0 |", "| aspirational | 1 |")
        duplicate = audit.replace(
            '| 1 | README.md | "`--json` prints JSON" | stale | fix-doc | drop the flag from README |',
            '| 1 | README.md | "`--json` prints JSON" | stale | fix-doc | drop the flag from README |\n'
            '| 2 | README.md | "`--json` prints JSON" | stale | fix-doc | duplicate row |',
        )
        self.write(duplicate)

        code, _, err = self.run_gate()

        self.assertEqual(code, 1)
        self.assertIn("bind each non-verified", err)

        non_contiguous = audit.replace(
            '| 1 | README.md | "`--json` prints JSON" | stale | fix-doc | drop the flag from README |',
            '| 2 | README.md | "`--json` prints JSON" | stale | fix-doc | drop the flag from README |\n'
            '| 3 | README.md | "Output is colored" | aspirational | fix-doc | document status |',
        )
        self.write(non_contiguous)
        self.assertIn("contiguous", self.run_gate()[2])

    def test_invalid_verdict_type_or_class(self):
        self.write(AUDIT.format(verified=1).replace("| command | verified |", "| vibe | verified |"))
        self.assertIn("invalid claim type", self.run_gate()[2])
        self.write(AUDIT.format(verified=1).replace("| stale | fix-doc |", "| stale | maybe |"))
        self.assertIn("invalid class", self.run_gate()[2])

    def test_missing_audit(self):
        (self.repo / check_docs_audit.DEFAULT_AUDIT).unlink()
        code, _, err = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn("missing real audit file", err)


if __name__ == "__main__":
    unittest.main()
