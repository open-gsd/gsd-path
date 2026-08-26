import unittest

from tests import dogfood


class DogfoodContractTests(unittest.TestCase):
    def test_every_declared_host_has_an_evidence_route(self):
        self.assertEqual(set(dogfood.DECLARED_HOSTS), set(dogfood.HOSTS))
        self.assertEqual("automated", dogfood.HOSTS["claude"]["evidence_route"])
        self.assertEqual("automated", dogfood.HOSTS["codex"]["evidence_route"])
        self.assertEqual("manual", dogfood.HOSTS["cursor"]["evidence_route"])


if __name__ == "__main__":
    unittest.main()
