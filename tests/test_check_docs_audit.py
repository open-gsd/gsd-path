import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import check_docs_audit

AUDIT = """# Docs Audit

Repo root: /repo
Audited: 2026-08-21
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
| 1 | README.md | `--json` prints JSON | stale | fix-doc | drop the flag from README |
"""


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

    def write(self, text):
        path = self.repo / check_docs_audit.DEFAULT_AUDIT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

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

    def test_derived_inventory_excludes_vendored_archive_skills_and_project_unless_alignment(self):
        inventory = check_docs_audit.derive_inventory(self.repo, check_docs_audit.DEFAULT_AUDIT, alignment=False)
        self.assertEqual(inventory, ["CONTRIBUTING.md", "README.md"])
        aligned = check_docs_audit.derive_inventory(self.repo, check_docs_audit.DEFAULT_AUDIT, alignment=True)
        self.assertEqual(aligned, [".project/intent/INTENT.md", "CONTRIBUTING.md", "README.md"])

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

    def test_rejects_placeholder_evidence_but_allows_angle_brackets_in_prose(self):
        self.write(AUDIT.format(verified=1).replace("`app 3` → `3`", "<file:line>"))
        code, _, err = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn("placeholder", err)
        self.write(AUDIT.format(verified=1).replace("`app 3` → `3`", "ran `app <n>` → `3`"))
        self.assertEqual(self.run_gate()[0], 0)

    def test_rejects_doc_listed_as_both_claims_and_descriptive(self):
        self.write(AUDIT.format(verified=1).replace("- CONTRIBUTING.md", "- CONTRIBUTING.md\n- README.md"))
        code, _, err = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn("both", err)

    def test_remediation_queue_must_cover_every_non_verified_claim(self):
        self.write(AUDIT.format(verified=1).replace("| 1 | README.md | `--json` prints JSON | stale | fix-doc | drop the flag from README |\n", ""))
        code, _, err = self.run_gate()
        self.assertEqual(code, 1)
        self.assertIn("Remediation queue has 0 rows for 1", err)

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
