import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import check_trust_evidence


class TrustEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        self.guard_tiers = {
            "alpha": "native-fail-closed",
            "beta": "git-only",
        }
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "skill-resources.json").write_text(
            json.dumps(
                {
                    "hosts": {
                        "alpha": {
                            "local_root": ".alpha/skills",
                            "guard_tier": self.guard_tiers["alpha"],
                        },
                        "beta": {
                            "local_root": ".beta/skills",
                            "guard_tier": self.guard_tiers["beta"],
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        (self.repo / "package.json").write_text(
            json.dumps({"version": "1.2.3"}), encoding="utf-8"
        )
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "trust@example.invalid")
        self.git("config", "user.name", "Trust")
        self.git("add", "-A")
        self.git("commit", "-qm", "candidate")
        self.candidate = self.git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments):
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.repo,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result

    def receipt(
        self,
        host,
        details=True,
        write_artifacts=True,
        shared_artifact=False,
        **overrides,
    ):
        fields = {
            "schema": "gsd-path/live-evidence/v1",
            "host": host,
            "package": "1.2.3",
            "pipeline": "gsd-path/v2",
            "candidate": self.candidate,
            "verdict": "pass",
            "child_spawn": "pass",
            "state": "pass",
            "task_verify": "pass",
            "wave_review": "pass",
            "final_review": "pass",
            "archive": "pass",
            "integration": "pass",
            "guard_tier": self.guard_tiers[host],
        }
        fields.update(overrides)
        lines = [
            "---",
            *[f"{key}: {value}" for key, value in fields.items()],
            "---",
            "",
            f"# {host} live evidence",
            "",
        ]
        if details:
            lines.extend(
                f"- {label}: verified {host} metadata"
                for label in check_trust_evidence.METADATA_DETAILS
            )
            lines.extend(
                f"- {label}: {host}/"
                f"{'install' if shared_artifact else check_trust_evidence.ARTIFACT_STEPS[label]}.json"
                for label in check_trust_evidence.ARTIFACT_DETAILS
            )
        path = (
            self.repo
            / "docs"
            / "trust-validation"
            / "evidence"
            / "releases"
            / "1.2.3"
            / f"{host}.md"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        if details and write_artifacts:
            for step in check_trust_evidence.ARTIFACT_STEPS.values():
                artifact_step = "install" if shared_artifact else step
                artifact = self.artifact(host, artifact_step)
                artifact.parent.mkdir(parents=True, exist_ok=True)
                if artifact.exists():
                    continue
                artifact.write_text(
                    json.dumps(
                        {
                            "schema": check_trust_evidence.STEP_SCHEMA,
                            "host": host,
                            "step": step,
                            "command": f"run {step} for {host}",
                            "result": "pass",
                            "output": f"observed {step} output for {host}",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )

    def commit_receipts(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "trust evidence")

    def test_accepts_complete_current_evidence(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()

        result = check_trust_evidence.validate_repository(self.repo)

        self.assertEqual(["alpha", "beta"], result["hosts"])
        self.assertEqual(self.candidate, result["candidate"])

    def test_rejects_missing_host_receipt(self):
        self.receipt("alpha")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "missing.*beta"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_partial_or_top_level_only_evidence(self):
        self.receipt("alpha", child_spawn="unverifiable")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "child_spawn"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_frontmatter_only_receipt(self):
        self.receipt("alpha", details=False)
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "missing reproducible evidence detail"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_missing_evidence_artifact(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.artifact("alpha", "install").unlink()
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "invalid evidence artifact"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_empty_evidence_artifact(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.artifact("alpha", "install").write_text("", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "invalid evidence artifact"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_untracked_release_input(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()
        (self.repo / "untracked.txt").write_text("not tested\n", encoding="utf-8")

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "clean worktree"):
            check_trust_evidence.validate_repository(self.repo)

    def artifact(self, host, step):
        return (
            self.repo
            / "docs"
            / "trust-validation"
            / "evidence"
            / "releases"
            / "1.2.3"
            / host
            / f"{step}.json"
        )

    def test_rejects_one_artifact_reused_for_every_step(self):
        self.receipt("alpha", shared_artifact=True)
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "own artifact"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_unstructured_step_evidence(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.artifact("alpha", "install").write_text("{}\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "schema"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_guard_tier_that_disagrees_with_manifest(self):
        self.receipt("alpha", guard_tier="git-only")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "guard_tier"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_ignored_untracked_evidence(self):
        (self.repo / ".gitignore").write_text(
            "docs/trust-validation/evidence/\n", encoding="utf-8"
        )
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "ignore evidence")
        self.candidate = self.git("rev-parse", "HEAD").stdout.strip()
        self.receipt("alpha")
        self.receipt("beta")

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "not tracked"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_artifacts_older_than_candidate(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()
        (self.repo / "candidate.txt").write_text("new candidate\n", encoding="utf-8")
        self.git("add", "candidate.txt")
        self.git("commit", "-qm", "new candidate")
        self.candidate = self.git("rev-parse", "HEAD").stdout.strip()
        self.receipt("alpha", write_artifacts=False)
        self.receipt("beta", write_artifacts=False)
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "not added or updated"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_unstaged_release_input(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()
        (self.repo / "package.json").write_text('{"version": "9.9.9"}\n', encoding="utf-8")

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "clean worktree"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_staged_release_input(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()
        (self.repo / "staged.txt").write_text("not tested\n", encoding="utf-8")
        self.git("add", "staged.txt")

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "clean worktree"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_non_evidence_changes_after_candidate(self):
        self.receipt("alpha")
        self.receipt("beta")
        (self.repo / "product.py").write_text("changed\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "non-evidence"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_active_validation_spec_change_after_candidate(self):
        self.receipt("alpha")
        self.receipt("beta")
        spec = self.repo / "docs" / "trust-validation" / "TRUST-VALIDATION-SPEC.md"
        spec.write_text("changed release contract\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "non-evidence"):
            check_trust_evidence.validate_repository(self.repo)


if __name__ == "__main__":
    unittest.main()
