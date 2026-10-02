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


def numbered_audit(items, ruling_numbers=(), queue_note=None):
    docs = {"README.md": [("baseline claim", "verified")]}
    for _, doc, claim, verdict in items:
        docs.setdefault(doc, []).append((claim, verdict))

    tallies = {"verified": 0, "stale": 0, "aspirational": 0, "unverifiable": 0}
    lines = [
        "# Docs Audit",
        "",
        "Repo root: /repo",
        "Audited: 2026-08-21",
        "Audited HEAD: none",
        "Alignment mode: no",
        "",
    ]
    for doc, claims in docs.items():
        lines += [f"## Doc: {doc}", "", "| Claim | Type | Verdict | Evidence |", "|-------|------|---------|----------|"]
        for claim, verdict in claims:
            tallies[verdict] += 1
            lines.append(f"| {claim} | feature | {verdict} | {doc}:1 |")
        lines.append("")

    lines += ["## Summary", "", "| Verdict | Count |", "|---------|-------|"]
    lines += [f"| {verdict} | {count} |" for verdict, count in tallies.items()]
    descriptive = [doc for doc in ("README.md", "CONTRIBUTING.md") if doc not in docs]
    lines += [f"| descriptive docs (no testable claims) | {len(descriptive)} |", "", "## Descriptive docs", ""]
    lines += [f"- {doc}" for doc in descriptive]

    lines += ["", "## User rulings", "", RULING_HEADER.rstrip()]
    for number in ruling_numbers:
        lines.append(f'| {number} | fix-doc | "ok" | T001 |')

    lines += ["", "## Remediation queue", ""]
    if queue_note is None:
        lines += [
            "| # | Doc | Claim | Verdict | Class | Suggested action |",
            "|---|-----|-------|---------|-------|------------------|",
        ]
        for number, doc, claim, verdict in items:
            lines.append(f"| {number} | {doc} | {claim} | {verdict} | fix-doc | edit |")
    elif queue_note:
        lines.append(queue_note)
    return "\n".join(lines) + "\n"


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
            path.write_bytes("x\n".encode("utf-8"))
        subprocess.run(["git", "add", "-A", "-f"], cwd=self.repo, check=True)
        self.write(AUDIT.format(verified=1))

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, text, path=check_docs_audit.DEFAULT_AUDIT):
        path = self.repo / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            text.replace("Repo root: /repo", f"Repo root: {self.repo.resolve()}").encode("utf-8"),
        )

    def run_gate(self, *args):
        result = subprocess.run(
            ["python3", str(Path(check_docs_audit.__file__)), "--repo", str(self.repo), *args],
            capture_output=True, encoding="utf-8", errors="replace",
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
            (carried, carried, ["--prior-audit", "--changed"], None),
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
                (self.repo / "changed.txt").write_bytes(("\n".join(flags[2:]) + "\n").encode("utf-8"))
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
        (self.repo / "NOTES.md").write_bytes("notes\n".encode("utf-8"))
        (self.repo / ".gitignore").write_bytes("IGNORED.md\n".encode("utf-8"))
        (self.repo / "IGNORED.md").write_bytes("ignored\n".encode("utf-8"))

        code, out, err = self.run_gate("--emit-inventory")

        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), ["CONTRIBUTING.md", "NOTES.md", "README.md"])

    def test_inventory_command_excludes_the_installed_path_router_alias(self):
        for name in ('.agents/skills/path/SKILL.md',
                     '.agents/skills/path/references/coder.md',
                     '.agents/skills/pathology/SKILL.md', 'docs/path.md'):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes('A documented claim.\n'.encode("utf-8"))
        code, out, err = self.run_gate('--emit-inventory')
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), ['.agents/skills/pathology/SKILL.md',
                                          'CONTRIBUTING.md', 'README.md', 'docs/path.md'])

    def test_explicit_inventory_wins(self):
        (self.repo / "inventory.txt").write_bytes("README.md\nCONTRIBUTING.md\nDOCS.md\n".encode("utf-8"))
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

    def test_sidecar_audit_names_the_primary_repo_root(self):
        with tempfile.TemporaryDirectory() as primary:
            primary = Path(primary).resolve()
            self.write(AUDIT.format(verified=1).replace("Repo root: /repo", f"Repo root: {primary}"))
            code, _, err = self.run_gate("--primary", str(primary))
            self.assertEqual(code, 0, err)
            code, _, err = self.run_gate()
            self.assertEqual(code, 1)
            self.assertIn("Repo root does not match", err)
            self.write(AUDIT.format(verified=1))
            code, _, err = self.run_gate("--primary", str(primary))
            self.assertEqual(code, 1)
            self.assertIn("Repo root does not match", err)

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

    def check_numbered_audit(self, items, ruling_numbers=(), prior=None):
        self.write(numbered_audit(items, ruling_numbers))
        args = []
        if prior is not None:
            self.write(prior, "prior-audit.txt")
            args += ["--prior-audit", str(self.repo / "prior-audit.txt")]
        return self.run_gate(*args)

    def test_remediation_queue_rows_bind_exact_claims(self):
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

        code, _, error = self.run_gate()

        self.assertEqual(1, code)
        self.assertIn("bind each non-verified", error)

    def test_remediation_queue_numbers_may_be_sparse_and_must_increase(self):
        code, _, error = self.check_numbered_audit(
            (
                (3, "README.md", "first stale claim", "stale"),
                (8, "README.md", "second stale claim", "aspirational"),
            )
        )
        self.assertEqual(0, code, error)

        invalid_sequences = (
            ((3, "README.md", "first stale claim", "stale"), (3, "README.md", "second stale claim", "aspirational")),
            ((8, "README.md", "first stale claim", "stale"), (4, "README.md", "second stale claim", "aspirational")),
        )
        for items in invalid_sequences:
            with self.subTest(items=items):
                code, _, error = self.check_numbered_audit(items)
                self.assertEqual(1, code)
                self.assertIn("unique and strictly increasing", error)

        code, _, error = self.check_numbered_audit(((0, "README.md", "first stale claim", "stale"),))
        self.assertEqual(1, code)
        self.assertIn("positive integers", error)

    def test_persisting_queue_item_keeps_its_prior_number(self):
        prior = numbered_audit(((4, "README.md", "old claim", "stale"),), (4,))
        code, _, error = self.check_numbered_audit(
            (
                (4, "README.md", "old claim", "stale"),
                (5, "CONTRIBUTING.md", "new claim", "stale"),
            ),
            (4,),
            prior,
        )
        self.assertEqual(0, code, error)

        code, _, error = self.check_numbered_audit(
            ((6, "README.md", "old claim", "stale"),), (4,), prior
        )
        self.assertEqual(1, code)
        self.assertIn("persisting item must keep its prior queue number #4", error)

    def test_new_queue_items_are_allocated_above_all_prior_numbers(self):
        prior_queue_max = numbered_audit(
            (
                (2, "README.md", "old claim", "stale"),
                (9, "CONTRIBUTING.md", "retired queue claim", "stale"),
            ),
            (2,),
        )
        code, _, error = self.check_numbered_audit(
            (
                (2, "README.md", "old claim", "stale"),
                (10, "CONTRIBUTING.md", "new claim", "stale"),
            ),
            (2,),
            prior_queue_max,
        )
        self.assertEqual(0, code, error)

        code, _, error = self.check_numbered_audit(
            (
                (2, "README.md", "old claim", "stale"),
                (8, "CONTRIBUTING.md", "new claim", "stale"),
            ),
            (2,),
            prior_queue_max,
        )
        self.assertEqual(1, code)
        self.assertIn("above every prior queue number and User rulings Queue #", error)

        prior_ruling_max = numbered_audit(
            ((2, "README.md", "old claim", "stale"),), (2, 9)
        )
        code, _, error = self.check_numbered_audit(
            (
                (2, "README.md", "old claim", "stale"),
                (10, "CONTRIBUTING.md", "new claim", "stale"),
            ),
            (2, 9),
            prior_ruling_max,
        )
        self.assertEqual(0, code, error)

    def test_retired_ruled_numbers_cannot_be_reused_for_a_new_claim(self):
        prior = numbered_audit(((2, "README.md", "current claim", "stale"),), (2, 7))
        code, _, error = self.check_numbered_audit(
            (
                (2, "README.md", "current claim", "stale"),
                (7, "CONTRIBUTING.md", "new claim", "stale"),
            ),
            (2, 7),
            prior,
        )
        self.assertEqual(1, code)
        self.assertIn("Queue # 7 is already retired", error)

    def test_empty_table_free_prior_queue_allows_new_items_above_ruling_maximum(self):
        for queue_note in ("", "No remediation needed."):
            with self.subTest(queue_note=queue_note):
                prior = numbered_audit((), (12,), queue_note=queue_note)
                code, _, error = self.check_numbered_audit(
                    ((13, "README.md", "new claim", "stale"),), (12,), prior
                )
                self.assertEqual(0, code, error)

                code, _, error = self.check_numbered_audit(
                    ((12, "README.md", "new claim", "stale"),), (12,), prior
                )
                self.assertEqual(1, code)
                self.assertIn("Queue # 12 is already retired", error)

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
