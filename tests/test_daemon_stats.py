"""Stats for the app's charts: built from data the daemon already records."""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon import stats
from gsd_daemon.config import Config
from gsd_daemon.model import ProjectStatus, TaskSummary
from gsd_daemon.serve import serve
from gsd_daemon.watcher import Watcher

PRICES = {"priced": {"input": 1.0, "cached": 0.5, "output": 2.0}}


def record(at, model, tokens_in=0, cached=0, out=0):
    return {"at": at, "model": model, "tokens_in": tokens_in, "tokens_cached": cached, "tokens_out": out}


class UsageByDayTests(unittest.TestCase):
    def test_tokens_and_cost_sum_per_day_in_date_order(self):
        result = stats.usage_by_day([
            record("2026-09-30T10:00:00Z", "priced", tokens_in=1_000_000),
            record("2026-09-29T23:59:00Z", "priced", out=500_000),
            record("2026-09-30T11:00:00Z", "priced", cached=2_000_000),
        ], PRICES)
        self.assertEqual(result["days"], [
            {"date": "2026-09-29", "tokens": 500_000, "turns": 1, "cost": 1.0},
            {"date": "2026-09-30", "tokens": 3_000_000, "turns": 2, "cost": 2.0},
        ])
        self.assertEqual(result["unpriced"], [])

    def test_a_model_without_a_price_counts_tokens_and_is_left_out_of_cost(self):
        result = stats.usage_by_day([
            record("2026-09-30T10:00:00Z", "priced", tokens_in=1_000_000),
            record("2026-09-30T11:00:00Z", "mystery", tokens_in=9),
            record("2026-10-01T11:00:00Z", "mystery", tokens_in=7),
        ], PRICES)
        self.assertEqual(result["days"][0], {"date": "2026-09-30", "tokens": 1_000_009, "turns": 2, "cost": 1.0})
        # A day with no priced turn has no cost: missing, never zero.
        self.assertEqual(result["days"][1], {"date": "2026-10-01", "tokens": 7, "turns": 1, "cost": None})
        self.assertEqual(result["unpriced"], ["mystery"])

    def test_no_records_is_missing(self):
        self.assertIsNone(stats.usage_by_day([], PRICES))

    def test_a_record_without_a_time_is_not_charted(self):
        self.assertIsNone(stats.usage_by_day([record(None, "priced", tokens_in=5)], PRICES))


class PhaseSecondsTests(unittest.TestCase):
    NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    def event(self, at, detail, root="/p", kind="phase-changed"):
        return {"type": kind, "root": root, "detail": detail, "at": at}

    def test_each_phase_lasts_until_the_next_change_and_the_last_until_now(self):
        events = [
            self.event("2026-10-01T10:00:00+00:00", "plan -> build"),
            self.event("2026-10-01T11:00:00+00:00", "build -> ship"),
            self.event("2026-10-01T11:30:00+00:00", "ship -> build"),
            self.event("2026-10-01T11:45:00+00:00", "x -> y", root="/other"),
            self.event("2026-10-01T11:50:00+00:00", "active -> blocked", kind="status-changed"),
        ]
        self.assertEqual(stats.phase_seconds(events, ["/p"], self.NOW),
                         [{"phase": "build", "seconds": 5400}, {"phase": "ship", "seconds": 1800}])

    def test_an_unreadable_phase_is_not_charted_and_ends_the_phase_before_it(self):
        events = [self.event("2026-10-01T09:00:00+00:00", "plan -> build"),
                  self.event("2026-10-01T10:00:00+00:00", "build -> None"),
                  self.event("2026-10-01T11:30:00+00:00", "None -> ship")]
        self.assertEqual(stats.phase_seconds(events, ["/p"], self.NOW),
                         [{"phase": "build", "seconds": 3600}, {"phase": "ship", "seconds": 1800}])
        self.assertIsNone(stats.phase_seconds(events[1:2], ["/p"], self.NOW))

    def test_all_projects_add_up(self):
        events = [self.event("2026-10-01T11:00:00+00:00", "plan -> build"),
                  self.event("2026-10-01T10:00:00+00:00", "plan -> build", root="/q")]
        self.assertEqual(stats.phase_seconds(events, ["/p", "/q"], self.NOW), [{"phase": "build", "seconds": 10800}])

    def test_cards_that_share_a_folder_keep_their_own_phase_time(self):
        core = "/p::gsd-core"
        events = [self.event("2026-10-01T10:00:00+00:00", "plan -> build"),  # older GSD Path event: no id
                  {**self.event("2026-10-01T11:00:00+00:00", "plan -> execute"), "id": core}]
        self.assertEqual(stats.phase_seconds(events, ["/p"], self.NOW), [{"phase": "build", "seconds": 7200}])
        self.assertEqual(stats.phase_seconds(events, [core], self.NOW), [{"phase": "execute", "seconds": 3600}])

    def test_no_recorded_change_is_missing(self):
        self.assertIsNone(stats.phase_seconds([], ["/p"], self.NOW))
        self.assertIsNone(stats.phase_seconds([self.event("bad time", "a -> b")], ["/p"], self.NOW))


class WaveAndVerifyTests(unittest.TestCase):
    def test_tasks_group_by_wave(self):
        tasks = [TaskSummary("T1", wave=1, status="done"), TaskSummary("T2", wave=1, status="done"),
                 TaskSummary("T3", wave=2, status="active"), TaskSummary("T4", wave=None, status="done")]
        self.assertEqual(stats.tasks_per_wave(tasks), [{"wave": 1, "total": 2, "done": 2},
                                                        {"wave": 2, "total": 1, "done": 0}])
        self.assertIsNone(stats.tasks_per_wave([TaskSummary("T4", wave=None)]))

    def test_verify_history_is_oldest_first(self):
        ledger = [{"command": "b", "commit": "2", "result": "fail", "recorded_at": "2026-10-01T02:00:00Z"},
                  {"command": "a", "commit": "1", "result": "pass", "recorded_at": "2026-10-01T01:00:00Z"}]
        self.assertEqual([entry["result"] for entry in stats.verify_history(ledger)], ["pass", "fail"])
        self.assertIsNone(stats.verify_history([]))


class RouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        env = mock.patch.dict(os.environ, {"GSD_DAEMON_CONFIG": str(self.root / "daemon.json"),
                                           "GSD_DAEMON_HISTORY": str(self.root / "history.jsonl")})
        env.start()
        self.addCleanup(env.stop)
        self.watcher = Watcher(Config(parents=[], history=False, session_dirs=[], prices=PRICES))
        with mock.patch("threading.Thread.start"):
            self.server = serve(self.watcher, port=0, plugin=mock.Mock())
        self.full = str(self.root / "full")
        self.empty = str(self.root / "empty")
        self.watcher.projects = {
            self.full: ProjectStatus(root=self.full, project="full",
                                     tasks=[TaskSummary("T1", wave=1, status="done")],
                                     ledger=[{"command": "npm test", "commit": "abc", "result": "pass",
                                              "recorded_at": "2026-10-01T01:00:00Z"}]),
            self.empty: ProjectStatus(root=self.empty, project="empty"),
        }
        self.watcher.sessions.records_for = lambda root: (
            [record("2026-09-30T10:00:00Z", "priced", tokens_in=1_000_000)] if root == self.full else [])
        (self.root / "history.jsonl").write_text(json.dumps(
            {"type": "phase-changed", "root": self.full, "detail": "plan -> build",
             "at": "2026-09-30T10:00:00+00:00"}) + "\n", encoding="utf-8")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def get(self, path, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload

    def test_a_project_with_data_fills_every_chart(self):
        status, payload = self.get("/api/stats?root=" + self.full)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["scope"], self.full)
        self.assertEqual(payload["days"], [{"date": "2026-09-30", "tokens": 1_000_000, "turns": 1, "cost": 1.0}])
        self.assertEqual(payload["phases"][0]["phase"], "build")
        self.assertGreater(payload["phases"][0]["seconds"], 0)
        self.assertEqual(payload["waves"], [{"wave": 1, "total": 1, "done": 1}])
        self.assertEqual(payload["verify"][0]["result"], "pass")
        self.assertEqual(payload["missing"], {})

    def test_a_project_without_data_reports_missing_never_zero(self):
        status, payload = self.get("/api/stats?root=" + self.empty)
        self.assertEqual(status, 200, payload)
        for chart in ("days", "phases", "waves", "verify"):
            self.assertIsNone(payload[chart], chart)
            self.assertTrue(payload["missing"][chart], chart)
        self.assertEqual(payload["unpriced"], [])

    def test_all_projects_scope_merges_usage_and_leaves_waves_to_a_project(self):
        status, payload = self.get("/api/stats")
        self.assertEqual(status, 200, payload)
        self.assertIsNone(payload["scope"])
        self.assertEqual(payload["days"][0]["tokens"], 1_000_000)
        self.assertIsNone(payload["waves"])
        self.assertIn("project", payload["missing"]["waves"])
        self.assertEqual(payload["verify"][0]["project"], "full")

    def test_all_projects_scope_counts_a_shared_folder_once(self):
        card = self.full + "::gsd-core"
        self.watcher.projects[card] = ProjectStatus(root=self.full, id=card, flavor="gsd-core", project="full")
        status, payload = self.get("/api/stats")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["days"][0]["tokens"], 1_000_000)

    def test_an_unwatched_root_is_a_bad_request(self):
        status, payload = self.get("/api/stats?root=/etc")
        self.assertEqual(status, 400, payload)

    def test_a_foreign_host_is_refused(self):
        status, _ = self.get("/api/stats", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
