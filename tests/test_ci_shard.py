import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests import ci_shard


class CiShardTests(unittest.TestCase):
    def test_windows_timings_balance_seven_shards(self):
        measured = json.loads(Path(__file__).with_name('windows_ci_seconds.json').read_text())
        shards = [ci_shard.modules(index, 7) for index in range(7)]
        self.assertEqual(sorted(name for shard in shards for name in shard), ci_shard.modules())
        loads = [sum(measured.get(name, ci_shard.DEFAULT) for name in shard) for shard in shards]
        # The longest module is the lower bound; permit the measured Node
        # step (263 seconds), which runs before Python on shard zero.
        loads[0] += 263
        self.assertLessEqual(max(loads), max(measured.values()) + 263)

    def test_shards_partition_every_test_module(self):
        names = ci_shard.modules()
        self.assertIn("test_ci_shard.py", names)
        shards = [ci_shard.modules(index, 4) for index in range(4)]
        self.assertEqual(sorted(name for shard in shards for name in shard), names)
        self.assertEqual(sum(len(shard) for shard in shards), len(set(names)))
        self.assertTrue(all(shards))
        # The slowest shard sets CI wall time; keep it near the average load.
        loads = [sum(ci_shard.SECONDS.get(name, ci_shard.DEFAULT) for name in shard) for shard in shards]
        self.assertLessEqual(max(loads), 1.2 * sum(loads) / len(loads))

    def test_run_fails_when_any_module_fails_and_reports_each_duration(self):
        # Two start directories: a loader reused across discoveries keeps the first top-level dir.
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            ok, bad = Path(first), Path(second)
            (ok / "test_shard_probe_ok.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n", encoding="utf-8")
            (bad / "test_shard_probe_bad.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_bad(self): self.fail('x')\n",
                encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                self.assertEqual(ci_shard.run(["test_shard_probe_ok.py"], ok), 0)
                self.assertEqual(ci_shard.run(["test_shard_probe_bad.py"], bad), 1)
            self.assertIn("test_shard_probe_bad.py", output.getvalue())

    def test_rejects_an_index_outside_the_shard_count(self):
        for index, total in ((4, 4), (-1, 4)):
            with self.subTest(index=index), self.assertRaises(SystemExit):
                ci_shard.modules(index, total)


if __name__ == "__main__":
    unittest.main()
