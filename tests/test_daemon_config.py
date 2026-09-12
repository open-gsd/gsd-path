import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon import config as config_module
from gsd_daemon.config import Config


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "daemon.json"

    def test_defaults(self) -> None:
        cfg = Config()
        self.assertEqual(cfg.parents, [])
        self.assertEqual(cfg.excludes, [])
        self.assertEqual(cfg.max_depth, 6)
        self.assertEqual(cfg.poll_seconds, 5)
        self.assertTrue(cfg.notify)
        self.assertTrue(cfg.history)

    def test_load_missing_file_returns_defaults(self) -> None:
        cfg = Config.load(self.path)
        self.assertEqual(cfg, Config())

    def test_round_trip(self) -> None:
        cfg = Config(
            parents=[str(Path(self.tmp.name) / "work")],
            excludes=["~/archive"],
            max_depth=3,
            poll_seconds=9,
            notify=False,
            history=False,
        )
        saved = cfg.save(self.path)
        self.assertEqual(saved, self.path)
        loaded = Config.load(self.path)
        self.assertEqual(loaded.parents, [os.path.abspath(str(Path(self.tmp.name) / "work"))])
        self.assertEqual(loaded.excludes, [os.path.abspath(os.path.expanduser("~/archive"))])
        self.assertEqual(loaded.max_depth, 3)
        self.assertEqual(loaded.poll_seconds, 9)
        self.assertFalse(loaded.notify)
        self.assertFalse(loaded.history)

    def test_env_override(self) -> None:
        Config(parents=[self.tmp.name]).save(self.path)
        with mock.patch.dict(os.environ, {config_module.ENV_CONFIG: str(self.path)}):
            loaded = Config.load()
        self.assertEqual(loaded.parents, [os.path.abspath(self.tmp.name)])

    def test_explicit_path_beats_env(self) -> None:
        other = Path(self.tmp.name) / "other.json"
        Config(parents=["/tmp/from-explicit"]).save(other)
        Config(parents=["/tmp/from-env"]).save(self.path)
        with mock.patch.dict(os.environ, {config_module.ENV_CONFIG: str(self.path)}):
            loaded = Config.load(other)
        self.assertEqual(loaded.parents, ["/tmp/from-explicit"])

    def test_malformed_json_returns_defaults(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(Config.load(self.path), Config())

    def test_non_dict_json_returns_defaults(self) -> None:
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(Config.load(self.path), Config())

    def test_partial_json_keeps_defaults(self) -> None:
        self.path.write_text(json.dumps({"parents": [self.tmp.name]}), encoding="utf-8")
        loaded = Config.load(self.path)
        self.assertEqual(loaded.parents, [os.path.abspath(self.tmp.name)])
        self.assertEqual(loaded.max_depth, 6)
        self.assertTrue(loaded.notify)

    def test_save_is_atomic_and_creates_parents(self) -> None:
        nested = Path(self.tmp.name) / "deep" / "dir" / "daemon.json"
        Config().save(nested)
        self.assertTrue(nested.is_file())
        self.assertEqual(json.loads(nested.read_text(encoding="utf-8")), Config().to_dict())

    def test_add_and_remove_parent(self) -> None:
        cfg = Config()
        cfg.add_parent(self.tmp.name)
        cfg.add_parent(self.tmp.name + os.sep)
        self.assertEqual(cfg.parents, [os.path.abspath(self.tmp.name)])
        cfg.remove_parent(self.tmp.name)
        self.assertEqual(cfg.parents, [])


if __name__ == "__main__":
    unittest.main()


class SessionConfigTests(unittest.TestCase):
    def test_defaults_include_host_session_dirs_and_no_prices(self) -> None:
        config = Config()
        self.assertIn("~/.codex/sessions", config.session_dirs)
        self.assertIn("~/.claude/projects", config.session_dirs)
        self.assertEqual(config.prices, {})

    def test_prices_round_trip_and_reject_junk(self) -> None:
        config = Config.from_dict({"prices": {"gpt-6-astra": {"input": 1.25, "cached": "x", "output": 10},
                                              "bad": "nope", 7: {"input": 1}},
                                   "session_dirs": ["/tmp/sessions", 3]})
        self.assertEqual(config.prices, {"gpt-6-astra": {"input": 1.25, "output": 10.0}})
        self.assertEqual(config.session_dirs, ["/tmp/sessions"])
        self.assertEqual(Config.from_dict(config.to_dict()).prices, config.prices)
