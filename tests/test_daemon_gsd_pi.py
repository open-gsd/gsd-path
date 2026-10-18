import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon.flavors import probe_foreign

STATE = """# GSD State

**Active Milestone:** M002: Notes
**Active Slice:** S02: Search
**Phase:** {phase}

## Milestone Registry
- ✅ **M001:** Todo App
- 🔄 **M002:** Notes

## Blockers
- {blocker}

## Next Action
Execute T01 in S02.
"""

SCHEMA = """
CREATE TABLE milestones (id TEXT PRIMARY KEY, title TEXT, status TEXT, vision TEXT);
CREATE TABLE slices (milestone_id TEXT, id TEXT, title TEXT, status TEXT);
CREATE TABLE tasks (milestone_id TEXT, slice_id TEXT, id TEXT, title TEXT, status TEXT, files TEXT);
CREATE TABLE assessments (path TEXT PRIMARY KEY, milestone_id TEXT, status TEXT, scope TEXT, created_at TEXT);
CREATE TABLE verification_evidence (id INTEGER PRIMARY KEY, milestone_id TEXT, command TEXT, verdict TEXT, created_at TEXT);
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class GsdPiReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "app"
        self.base = self.root / ".gsd"
        write(self.base / "STATE.md", STATE.format(phase="executing", blocker="Needs an API key"))
        write(self.base / "PROJECT.md", "# Notes App\n\n## What This Is\n\nA notes app.\n")
        write(self.base / "state.json", json.dumps({"contract": "1.0.0", "next": {"command": "/gsd auto", "label": "Run S02"}}))

    def make_db(self, schema: str = SCHEMA, rows: bool = True) -> None:
        connection = sqlite3.connect(self.base / "gsd.db")
        connection.executescript(schema)
        if rows:
            connection.executescript("""
            INSERT INTO milestones VALUES ('M001', 'Todo App', 'complete', 'Track todos.'), ('M002', 'Notes', 'active', 'Keep notes.');
            INSERT INTO slices VALUES ('M001', 'S01', 'Store', 'complete'), ('M002', 'S01', 'Editor', 'complete'),
                                      ('M002', 'S02', 'Search', 'active');
            INSERT INTO tasks VALUES ('M001', 'S01', 'T01', 'Old task', 'complete', '[]'),
                ('M002', 'S01', 'T01', 'Edit a note', 'complete', '["app.js"]'),
                ('M002', 'S02', 'T01', 'Search titles', 'in_progress', '["search.js", "test.js"]'),
                ('M002', 'S02', 'T02', 'Search tags', 'blocked', '[]');
            INSERT INTO assessments VALUES ('.gsd/phases/01/01-01-ASSESSMENT.md', 'M002', 'pass', 'run-uat', '1'),
                ('.gsd/phases/02/02-01-ASSESSMENT.md', 'M002', 'fail', 'run-uat', '2'),
                ('.gsd/old.md', 'M001', 'pass', 'run-uat', '0');
            INSERT INTO verification_evidence VALUES (1, 'M002', 'npm test', '12/12 pass', '2026-10-01T00:00:00Z'),
                (2, 'M002', 'npm run e2e', 'fail', '2026-10-02T00:00:00Z'), (3, 'M001', 'old', 'pass', '2026-01-01T00:00:00Z');
            """)
        connection.commit()
        connection.close()

    def probe(self) -> dict:
        return probe_foreign(self.root, "gsd-pi").to_dict()

    def test_reads_the_database_and_state(self) -> None:
        self.make_db()
        card = self.probe()
        self.assertEqual(card["phases"], ["discuss", "research", "plan", "execute", "verify"])
        self.assertEqual(card["record_files"][0], {"path": ".gsd/STATE.md", "label": "State"})
        self.assertEqual((card["project"], card["vision"], card["milestone"]), ("Notes App", "A notes app.", "Notes"))
        self.assertEqual((card["status"], card["phase"], card["current_wave"]), ("executing", "execute", 2))
        self.assertEqual(card["waves"], {"1": "S01 Editor", "2": "S02 Search"})
        self.assertEqual([(t["id"], t["wave"], t["status"], t["files"]) for t in card["tasks"]], [
            ("S01-T01", 1, "done", ["app.js"]), ("S02-T01", 2, "active", ["search.js", "test.js"]),
            ("S02-T02", 2, "blocked", [])])
        self.assertEqual((card["tasks_done"], card["tasks_total"]), (1, 3))
        self.assertEqual([(m["number"], m["slug"], m["status"], m["goal"]) for m in card["roadmap_milestones"]], [
            ("M001", "Todo App", "shipped", "Track todos."), ("M002", "Notes", "active", "Keep notes.")])
        self.assertEqual([(r["file"], r["verdict"]) for r in card["reviews"]], [
            (".gsd/phases/01/01-01-ASSESSMENT.md", "pass"), (".gsd/phases/02/02-01-ASSESSMENT.md", "fail")])
        self.assertEqual([(e["command"], e["result"]) for e in card["ledger"]], [("npm run e2e", "fail"), ("npm test", "12/12 pass")])
        self.assertEqual((card["intent"], card["next_skill"]), ("Execute T01 in S02.", "/gsd auto"))
        self.assertEqual(card["workflow"], {"state": "active", "label": "In execute"})
        kinds = {(item["kind"], item["label"]) for item in card["attention"]}
        self.assertIn(("blocked", "Needs an API key"), kinds)
        self.assertIn(("blocked", "S02-T02 — Search tags"), kinds)
        self.assertIn(("failed", ".gsd/phases/02/02-01-ASSESSMENT.md — fail"), kinds)
        self.assertEqual(card["health"], "red")

    def test_reading_a_wal_database_leaves_the_project_untouched(self) -> None:
        self.make_db(schema="PRAGMA journal_mode=WAL;" + SCHEMA)
        before = sorted(p.name for p in self.base.iterdir())
        self.assertEqual(self.probe()["milestone"], "Notes")
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), before)

    def test_reads_commits_of_an_open_wal_writer(self) -> None:
        self.make_db(schema="PRAGMA journal_mode=WAL;" + SCHEMA)
        writer = sqlite3.connect(self.base / "gsd.db")
        self.addCleanup(writer.close)
        writer.execute("INSERT INTO tasks VALUES ('M002', 'S02', 'T03', 'Search body', 'pending', '[]')")
        writer.commit()
        self.assertIn("S02-T03", [t["id"] for t in self.probe()["tasks"]])

    def test_reading_a_leftover_wal_is_not_project_activity(self) -> None:
        # A writer that stopped without a checkpoint leaves gsd.db-wal and gsd.db-shm behind.
        # The first reader then rebuilds the shared index; the watch must not take that as activity.
        import shutil
        from gsd_daemon import flavors, probe
        self.make_db(schema="PRAGMA journal_mode=WAL;" + SCHEMA)
        writer = sqlite3.connect(self.base / "gsd.db")
        writer.execute("INSERT INTO tasks VALUES ('M002', 'S02', 'T03', 'Search body', 'pending', '[]')")
        writer.commit()
        left = self.root.parent / "left" / ".gsd"
        shutil.copytree(self.base, left)  # copied while the writer is open: -wal and -shm included
        writer.close()
        self.base = left
        self.root = left.parent
        old = probe.tree_mtime(left, flavors.SKIP["gsd-pi"]) - 100
        for path in [left, *left.iterdir()]:
            os.utime(path, (old, old))
        self.assertIn("S02-T03", [t["id"] for t in self.probe()["tasks"]])
        self.assertGreater((left / "gsd.db-shm").stat().st_mtime, old)  # the read rebuilt the index
        self.assertEqual(probe.tree_mtime(left, flavors.SKIP["gsd-pi"]), old)

    def test_older_schema_without_optional_columns_or_tables(self) -> None:
        self.make_db("""
        CREATE TABLE milestones (id TEXT PRIMARY KEY, title TEXT, status TEXT);
        CREATE TABLE slices (milestone_id TEXT, id TEXT, title TEXT, status TEXT);
        CREATE TABLE tasks (milestone_id TEXT, slice_id TEXT, id TEXT, title TEXT, status TEXT);
        INSERT INTO milestones VALUES ('M002', 'Notes', 'active');
        INSERT INTO slices VALUES ('M002', 'S02', 'Search', 'active');
        INSERT INTO tasks VALUES ('M002', 'S02', 'T01', 'Search titles', 'pending');
        """, rows=False)
        card = self.probe()
        self.assertEqual((card["milestone"], card["tasks_total"], card["reviews"], card["ledger"]), ("Notes", 1, [], []))
        self.assertEqual(card["tasks"][0]["files"], [])

    def test_empty_database_falls_back_to_legacy_markdown(self) -> None:
        self.make_db(rows=False)
        (self.base / "STATE.md").unlink()
        m1 = self.base / "milestones" / "M001"
        write(m1 / "M001-ROADMAP.md", "# M001: Todo App\n\n- [x] **S01: Store** `risk:low`\n")
        write(m1 / "M001-SUMMARY.md", "done\n")
        m2 = self.base / "milestones" / "M002"
        write(m2 / "M002-ROADMAP.md", "# M002: Notes\n\n**Vision:** Keep notes.\n\n## Slices\n\n"
                                      "- [x] **S01: Editor** `risk:low`\n- [ ] **S02: Search** `risk:high`\n")
        write(m2 / "slices" / "S01" / "S01-PLAN.md", "- [x] **T01: Edit a note** `est:1h`\n")
        write(m2 / "slices" / "S02" / "S02-PLAN.md", "- [ ] **T01: Search titles** `est:1h`\n- [ ] **T02: Search tags**\n")
        write(m2 / "slices" / "S02" / "tasks" / "T01-SUMMARY.md", "done\n")
        card = self.probe()
        self.assertEqual([(m["number"], m["status"], m["goal"]) for m in card["roadmap_milestones"]], [
            ("M001", "shipped", None), ("M002", "active", "Keep notes.")])
        self.assertEqual([(t["id"], t["status"]) for t in card["tasks"]], [
            ("S01-T01", "done"), ("S02-T01", "done"), ("S02-T02", "pending")])
        # No STATE.md phase: the open slice still has work.
        self.assertEqual((card["current_wave"], card["phase"], card["workflow"]["label"]), (2, "execute", "In execute"))

    def test_legacy_markdown_with_every_slice_closed_is_in_verify(self) -> None:
        (self.base / "STATE.md").unlink()
        m2 = self.base / "milestones" / "M002"
        write(m2 / "M002-ROADMAP.md", "# M002: Notes\n\n- [x] **S01: Editor**\n- [x] **S02: Search**\n")
        write(m2 / "slices" / "S02" / "S02-PLAN.md", "- [x] **T01: Search titles**\n")
        card = self.probe()
        self.assertEqual((card["current_wave"], card["phase"], card["workflow"]["label"]), (None, "verify", "In verify"))

    def test_state_registry_is_the_last_source(self) -> None:
        card = self.probe()
        self.assertEqual([(m["number"], m["status"]) for m in card["roadmap_milestones"]], [("M001", "shipped"), ("M002", "active")])
        self.assertEqual((card["milestone"], card["tasks_total"]), ("Notes", 0))

    def test_phase_words_decide_the_state(self) -> None:
        cases = {"complete": "shipped", "blocked": "blocked", "paused": "idle",
                 "researching": "active", "completing-milestone": "active"}
        for phase, state in cases.items():
            with self.subTest(phase=phase):
                write(self.base / "STATE.md", STATE.format(phase=phase, blocker="None"))
                self.assertEqual(self.probe()["workflow"]["state"], state)
        # The STATE.md phase wins over what the files suggest (no tasks here would read as plan).
        for phase, step in {"researching": "research", "executing": "execute", "summarizing": "verify",
                            "needs-discussion": "discuss", "replanning-slice": "plan"}.items():
            with self.subTest(phase=phase):
                write(self.base / "STATE.md", STATE.format(phase=phase, blocker="None"))
                card = self.probe()
                self.assertEqual((card["phase"], card["health"]), (step, "green"))

    def test_shipped_project_shows_its_last_milestone_and_skips_old_worktrees(self) -> None:
        self.make_db()
        connection = sqlite3.connect(self.base / "gsd.db")
        connection.execute("UPDATE milestones SET status = 'complete'")
        connection.commit()
        connection.close()
        write(self.base / "STATE.md", "# GSD State\n\n**Active Milestone:** None\n**Phase:** complete\n")
        write(self.base / "PROJECT.md", "# Project\n")  # gsd-pi's generic title
        card = self.probe()
        self.assertEqual((card["workflow"]["state"], card["milestone"], card["project"]), ("shipped", "Notes", None))
        # gsd-pi's old layout kept whole checkouts in .gsd/worktrees: a change there is not project activity.
        from gsd_daemon import flavors, probe
        (self.base / "worktrees" / "M002").mkdir(parents=True)
        before = probe.tree_mtime(self.base, flavors.SKIP["gsd-pi"])
        write(self.base / "worktrees" / "M002" / "app.js", "x\n")
        import os
        os.utime(self.base / "worktrees" / "M002" / "app.js", (before + 100, before + 100))
        self.assertEqual(probe.tree_mtime(self.base, flavors.SKIP["gsd-pi"]), before)

    def test_project_without_milestones_is_not_started(self) -> None:
        write(self.base / "STATE.md", "# GSD State\n\n**Active Milestone:** None\n**Phase:** pre-planning\n")
        card = self.probe()
        self.assertEqual((card["workflow"]["state"], card["milestone"], card["roadmap_milestones"]), ("idle", None, []))


if __name__ == "__main__":
    unittest.main()
