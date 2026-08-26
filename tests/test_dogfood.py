import contextlib
import io
import unittest

from tests import dogfood


class DogfoodContractTests(unittest.TestCase):
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
