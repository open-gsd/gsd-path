import contextlib
import io
import unittest

from tests import dogfood


class DogfoodContractTests(unittest.TestCase):
    def test_every_declared_host_has_an_evidence_route(self):
        self.assertEqual(set(dogfood.DECLARED_HOSTS), set(dogfood.HOSTS))
        self.assertEqual("automated", dogfood.HOSTS["claude"]["evidence_route"])
        self.assertEqual("automated", dogfood.HOSTS["codex"]["evidence_route"])
        self.assertEqual("manual", dogfood.HOSTS["cursor"]["evidence_route"])

    def test_manual_host_blocks_with_full_evidence_instruction(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = dogfood.main(["--host", "cursor"])

        self.assertEqual(3, status)
        self.assertIn("no verified headless dogfood adapter", output.getvalue())
        self.assertIn("LIVE-EVIDENCE-TEMPLATE.md", output.getvalue())


if __name__ == "__main__":
    unittest.main()
