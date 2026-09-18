import io
import json
import unittest
from unittest import mock

from scripts import check_update


class VersionComparisonTests(unittest.TestCase):
    def test_is_newer(self):
        self.assertTrue(check_update.is_newer("1.1.0", "1.0.0"))
        self.assertTrue(check_update.is_newer("2.0.0", "1.9.9"))
        self.assertTrue(check_update.is_newer("1.0.1", "1.0.0"))
        self.assertFalse(check_update.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(check_update.is_newer("1.0.0", "1.1.0"))
        self.assertFalse(check_update.is_newer("not-a-version", "1.0.0"))
        self.assertFalse(check_update.is_newer("1.0.0", "1.0.0-beta"))
        self.assertFalse(check_update.is_newer(None, "1.0.0"))

    def test_notice_is_silent_without_version_stamp(self):
        # The repo checkout has no ../VERSION next to scripts/, so notice()
        # must swallow the lookup failure and return None without networking.
        with mock.patch.object(check_update, "latest_version") as fetch:
            fetch.side_effect = AssertionError("must not be reached")
            self.assertIsNone(check_update.notice())

    def test_notice_reports_newer_version(self):
        with mock.patch.object(check_update, "latest_version", return_value="9.9.9"):
            with mock.patch.object(
                check_update.Path, "read_text", return_value="1.0.0\n"
            ):
                line = check_update.notice()
        self.assertIn("GSD Path 9.9.9 is available (installed 1.0.0)", line)
        self.assertIn("npx @opengsd/gsd-path@latest --update", line)

    def test_fetches_version_from_organization_package(self):
        with mock.patch.object(check_update.Path, "read_text", side_effect=OSError):
            with mock.patch.object(check_update, "_write_cache"):
                with mock.patch.object(check_update.urllib.request, "urlopen",
                                       return_value=io.BytesIO(b'{"version":"1.2.3"}')) as fetch:
                    self.assertEqual("1.2.3", check_update.latest_version())
        self.assertEqual(fetch.call_args.args[0],
                         "https://registry.npmjs.org/@opengsd%2Fgsd-path/latest")

    def test_cache_hit_avoids_network(self):
        cached = json.dumps({"checked_at": 10_000, "latest": "3.2.1"})
        with mock.patch.object(check_update.time, "time", return_value=10_100):
            with mock.patch.object(check_update.Path, "read_text", return_value=cached):
                with mock.patch.object(check_update.urllib.request, "urlopen") as urlopen:
                    self.assertEqual("3.2.1", check_update.latest_version())
        urlopen.assert_not_called()

    def test_fetch_failure_is_negative_cached(self):
        with mock.patch.object(check_update.Path, "read_text", side_effect=OSError):
            with mock.patch.object(check_update, "_write_cache") as write_cache:
                with mock.patch.object(
                    check_update.urllib.request, "urlopen", side_effect=OSError
                ):
                    self.assertIsNone(check_update.latest_version())
        write_cache.assert_called_once()
        self.assertIsNone(write_cache.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
