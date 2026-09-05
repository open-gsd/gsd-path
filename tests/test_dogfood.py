import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import dogfood
from tests.test_check_docs_audit import AUDIT


class DogfoodContractTests(unittest.TestCase):
    def test_live_audit_requires_correct_fixture_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "README.md").write_text(dogfood.FIXTURE_README)
            (repo / "CONTRIBUTING.md").write_text("Contribute here.\n")
            (repo / "count.py").write_text(dogfood.FIXTURE_SCRIPT)
            audit = repo / ".project/research/DOCS-AUDIT.md"
            audit.parent.mkdir(parents=True)
            wrong = AUDIT.format(verified=1).replace("Repo root: /repo", f"Repo root: {repo}")
            audit.write_text(wrong)
            self.assertFalse(all(ok for _, ok, _ in dogfood.check_audit(repo)))
            correct = wrong.replace("| stale | 1 |", "| stale | 0 |").replace("| aspirational | 0 |", "| aspirational | 1 |")
            correct = correct.replace("| feature | stale |", "| feature | aspirational |")
            correct = correct.replace("| stale | fix-doc |", "| aspirational | fix-doc |").replace("app.py", "count.py")
            audit.write_text(correct)
            results = dogfood.check_audit(repo)
            self.assertTrue(all(ok for _, ok, _ in results), results)

    def test_codex_guaranteed_tier_requires_only_git_hooks(self):
        self.assertEqual(
            "git-only",
            dogfood.RESOURCE_MANIFEST["hosts"]["codex"]["guard_tier"],
        )

    def test_every_declared_host_has_an_evidence_route(self):
        self.assertEqual(set(dogfood.DECLARED_HOSTS), set(dogfood.HOSTS))
        automated = {
            host
            for host, config in dogfood.HOSTS.items()
            if config["evidence_route"] == "automated"
        }
        self.assertEqual({"claude", "codex"}, automated)

    def test_unavailable_hosts_block_with_full_evidence_instruction(self):
        unavailable = set(dogfood.DECLARED_HOSTS) - {"claude", "codex"}
        for host in sorted(unavailable):
            with self.subTest(host=host):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    status = dogfood.main(["--host", host])

                self.assertEqual(3, status)
                self.assertIn(f"`{host}`", output.getvalue())
                self.assertIn("no verified headless dogfood adapter", output.getvalue())
                self.assertIn("LIVE-EVIDENCE-TEMPLATE.md", output.getvalue())


if __name__ == "__main__":
    unittest.main()
