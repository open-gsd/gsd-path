"""Run one shard of the Python suite; Windows CI splits it across jobs.

    python -m tests.ci_shard INDEX TOTAL

Every test module runs in exactly one shard. Slowest modules go first, each to
the lightest shard. Each module is discovered as `unittest discover -s tests`
would, and its time is printed so tests/windows_ci_seconds.json can be updated
when shards drift.
"""
import json
import sys
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
# Windows Python 3.12 timings from CI run 40084295374 (2026-10-24).
# ponytail: one measured run; refresh from shard output when workloads drift.
SECONDS = json.loads((TESTS / "windows_ci_seconds.json").read_text(encoding="utf-8"))
DEFAULT = 5


def modules(index=0, total=1):
    if not 0 <= index < total:
        raise SystemExit("usage: python -m tests.ci_shard INDEX TOTAL (0 <= INDEX < TOTAL)")
    names = sorted(path.name for path in TESTS.glob("test*.py"))
    shards, loads = [[] for _ in range(total)], [0] * total
    for name in sorted(names, key=lambda item: (-SECONDS.get(item, DEFAULT), item)):
        lightest = loads.index(min(loads))
        shards[lightest].append(name)
        loads[lightest] += SECONDS.get(name, DEFAULT)
    return sorted(shards[index])


def run(names, directory=TESTS):
    failed, timings = False, []
    for name in names:
        start = time.monotonic()
        # A fresh loader per module: a reused one keeps the first top-level dir.
        suite = unittest.TestLoader().discover(str(directory), pattern=name)
        failed = not unittest.TextTestRunner().run(suite).wasSuccessful() or failed
        timings.append((time.monotonic() - start, name))
    for seconds, name in sorted(timings, reverse=True):
        print(f"{seconds:8.1f}s  {name}")
    return 1 if failed else 0


def main(argv=None):
    index, total = (int(value) for value in (sys.argv[1:] if argv is None else argv))
    return run(modules(index, total))


if __name__ == "__main__":
    raise SystemExit(main())
