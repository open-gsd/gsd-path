"""Opt-in browser acceptance test: GSD_UI_TEST=1 python3 -m unittest discover -s tests -p test_daemon_board_ui.py.

Uses Orca's embedded browser and the real daemon HTTP handler with sample status.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))
from gsd_daemon.config import Config
from gsd_daemon.model import ProjectStatus, TaskSummary
from gsd_daemon.serve import serve_in_thread


def sample_projects():
    roadmap = [
        {"number": "M003", "slug": "core", "status": "shipped", "archive": ".project/archive/003-core",
         "goal": "Parsers and the status endpoint.", "depends": [], "integrated": "158ab3a6554e3d6be083e4a752583763a5d682a5",
         "manifest": {"shipped": "2026-09-06", "verdict": "all criteria met", "waves": 3, "tasks_done": 12,
                      "tasks_total": 12, "cycles_avg": 1.3, "carried": 2}},
        {"number": "M004", "slug": "daemon", "status": "active", "archive": None,
         "goal": "Native tray and dashboard for the daemon.", "depends": ["M003"], "integrated": None, "manifest": None},
        {"number": "M005", "slug": "notify", "status": "pending", "archive": None,
         "goal": "Desktop notifications.", "depends": ["M004"], "integrated": None, "manifest": None},
    ]
    return [
        ProjectStatus(root="/sample/gsd", project="GSD Path", milestone="daemon", phase="build",
                      status="active", branch="gsd-path/M004", tasks_done=6, tasks_total=9, current_wave=2,
                      waves={1: "parsers", 2: "watcher", 3: "tray"}, roadmap_milestones=roadmap,
                      tasks=[TaskSummary(id="T001", title="state parser", wave=1, status="done"),
                             TaskSummary(id="T005", title="poll loop", wave=2, status="done"),
                             TaskSummary(id="T006", title="notify hook", wave=2, status="pending")],
                      criteria=[{"id": "SC1", "text": "a", "verdict": "met"}, {"id": "SC2", "text": "b", "verdict": "met"},
                                {"id": "SC3", "text": "c", "verdict": "not-met"}],
                      ledger=[{"command": "make test", "commit": "abc1234", "result": "pass", "recorded_at": "2026-09-12T14:32:00+00:00"}],
                      phase_log=[{"phase": "define", "date": "2026-09-09"}, {"phase": "plan", "date": "2026-09-09"},
                                 {"phase": "build", "date": "2026-09-10"}],
                      vision="See every gsd-path project's state without a terminal.",
                      intent="Operators stop polling STATE.md by hand.",
                      lesson="003-core — Land task evidence through the isolation helper.",
                      spend={"turns": 90, "prompts": 12, "tokens_in": 9000000, "tokens_cached": 5000000, "tokens_out": 100000,
                             "cost": 26.1, "unpriced": ["claude-sonnet-5"],
                             "models": [{"model": "gpt-6-astra", "host": "codex", "turns": 84, "tokens": 14000000, "cost": 24.6},
                                        {"model": "claude-sonnet-5", "host": "claude", "turns": 6, "tokens": 100000, "cost": None}],
                             "agents": [{"agent": "$gsd-path-build · T006", "models": ["gpt-6-astra"], "turns": 60, "tokens": 10000000, "cost": 18.0},
                                        {"agent": "$gsd-path-build · reviewer", "models": ["claude-sonnet-5"], "turns": 6, "tokens": 100000, "cost": None}],
                             "milestones": {"M003": {"turns": 6, "tokens": 1000000, "cost": 1.5}, "M004": {"turns": 84, "tokens": 14100000, "cost": 24.6}},
                             "recent": [{"at": "2026-09-12T14:32:07+00:00", "agent": "$gsd-path-build · T006", "model": "gpt-6-astra", "host": "codex",
                                         "tokens_in": 214830, "tokens_cached": 171200, "tokens_out": 4226, "cost": 0.68, "duration_s": 41.0}]},
                      time_in_phase_s=3600 * 5, git={"branch": "gsd-path/M004", "head": "0e9a3b1abcdef", "dirty": True},
                      next_skill="gsd-path-build"),
        ProjectStatus(root="/sample/atlas'&tab=usage", project="Atlas API", milestone="api-v2", phase="ship",
                      status="blocked", branch="gsd-path/M002", health="red", next_skill="gsd-path-forensics",
                      attention=[{"kind": "blocked", "label": "ship blocked", "ref": None}],
                      next_milestone={"milestone": "api-v3", "phase": "define", "status": "pending"}),
        ProjectStatus(root="/sample/notes", project="Field Notes", milestone="bootstrap", phase="research",
                      status="active", branch="gsd-path/M001"),
        ProjectStatus(root="/sample/done", project="Done Thing", milestone="graph", phase="shipped",
                      status="shipped", archive=".project/archive/001-graph"),
    ]


@unittest.skipUnless(os.environ.get("GSD_UI_TEST"), "requires Orca embedded browser")
class BoardUITests(unittest.TestCase):
    def orca(self, *args):
        result = subprocess.run([os.environ.get("ORCA_CLI_COMMAND", "orca"), *args, "--json"],
                                capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload)
        return payload["result"]

    def js(self, expression):
        return self.orca("eval", "--page", self.page, "--expression", expression)["result"]

    def test_status_board(self):
        projects = sample_projects()
        watcher = Mock(config=Config(parents=["/sample"]))
        watcher.projects = {p.root: p for p in projects}
        plugin = Mock()
        plugin.latest_version.return_value = None
        plugin.detect_global.return_value = {}
        plugin.detect_project.return_value = {}
        server, _ = serve_in_thread(watcher, port=0, plugin=plugin)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.watcher_stop.set)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        self.page = self.orca("tab", "create", "--url", url)["browserPageId"]
        self.orca("wait", "--page", self.page, "--text", "Atlas API")
        # Theme: light and dark palettes both resolve.
        self.js("document.documentElement.dataset.theme = 'light'")
        self.assertEqual(self.js("getComputedStyle(document.body).backgroundColor"), "rgb(247, 248, 250)")
        self.js("document.documentElement.dataset.theme = 'dark'")
        self.assertEqual(self.js("getComputedStyle(document.body).backgroundColor"), "rgb(12, 13, 16)")
        # Board: one compact row per project grouped by state; blocked first, then active, then shipped.
        self.assertEqual(self.js("[...document.querySelectorAll('.prow .name span:last-child')].map(b=>b.textContent).join('|')"),
                         "Atlas API|Field Notes|GSD Path|Done Thing")
        self.assertEqual(self.js("[...document.querySelectorAll('.group')].map(g=>g.textContent).join('|')"),
                         "Needs attention · 1|In progress · 2|Shipped · 1")
        gsd_row = "document.querySelector('.prow[data-root=\"/sample/gsd\"]')"
        self.assertEqual(self.js(f"{gsd_row}.querySelector('.stack').textContent"), "M003 ✓  M004 ●  M005 ○")
        self.assertEqual(self.js(f"{gsd_row}.querySelector('.here').textContent"),
                         "build · wave 2 · 6 of 9 tasks · 2/3 criteria · last shipped M003 2026-09-06 — Native tray and dashboard for the daemon.")
        self.assertEqual(self.js(f"{gsd_row}.querySelector('.spend').textContent"), "$24.60 · 84 turns")
        self.assertEqual(self.js("document.querySelector('.prow.shipped .here') === null"), 'true')
        self.assertEqual(self.js("document.querySelectorAll('.card').length"), '0')
        # No next steps, commands or attention copy anywhere on the board.
        board = self.js("document.querySelector('.board').innerText")
        for gone in ("gsd-path-build", "forensics", "Copy", "Next step", "ship blocked", "Needs you"):
            self.assertNotIn(gone, board)
        # A row opens the project page: full briefing card, back button, project switcher, hash deep link.
        self.js(f"{gsd_row}.click()")
        self.assertEqual(self.js("location.hash"), "#project=%2Fsample%2Fgsd")
        self.assertEqual(self.js("document.querySelectorAll('.card').length"), '1')
        self.assertEqual(self.js("[...document.querySelectorAll('.switcher button')].map(b=>b.textContent+(b.classList.contains('sel')?'*':'')).join('|')"),
                         "Atlas API|Field Notes|GSD Path*|Done Thing")
        gsd = "document.querySelector('.card')"
        self.assertEqual(self.js(f"[...{gsd}.querySelectorAll('.ms')].map(m=>m.className.split(' ')[1]+':'+m.querySelector('.k').textContent).join('|')"),
                         "done:M003|now:M004|ahead:M005")
        text = self.js(f"{gsd}.innerText")
        for expected in ("core", "daemon", "notify", "build · wave 2", "6 of 9 tasks", "entered build 2026-09-10 · 5h 0m",
                         "✓ wave 1 parsers", "● wave 2 watcher", "○ wave 3 tray", "gsd-path/M004 · 0e9a3b1 · dirty", "In build",
                         # briefing details
                         "See every gsd-path project's state without a terminal.", "shipped 2026-09-06",
                         "12 of 12 tasks · 3 waves · 1.3 review cycles avg · integrated 158ab3a · 2 rulings carried · $1.50 · 6 turns",
                         "Parsers and the status endpoint.", "after M003", "Native tray and dashboard for the daemon.",
                         "Operators stop polling STATE.md by hand.", "T001 state parser ✓", "T005 poll loop ✓", "T006 notify hook ○",
                         "2 of 3 criteria met", "verify pass 14:32:00", "Desktop notifications.", "after M004",
                         "latest lesson · 003-core — Land task evidence through the isolation helper.",
                         # usage: cost, turns, models, agents; unpriced model excluded from cost
                         "USAGE · M004", "$24.60", "84", "14.1M", "$26.10", "gpt-6-astra", "84 turns · 14.0M · $24.60",
                         "claude-sonnet-5", "6 turns · 100k · —", "$gsd-path-build · T006", "$gsd-path-build · reviewer",
                         "No price configured for claude-sonnet-5"):
            self.assertIn(expected, text)
        self.assertEqual(self.js(f"[...{gsd}.querySelectorAll('.phase-log div')].map(d=>d.className+':'+d.textContent).join('|')"),
                         ":def09-09|:plan09-09|now:build09-10")
        self.assertEqual(self.js(f"[...{gsd}.querySelectorAll('.crit i')].map(i=>i.className).join('|')"), "met|met|not-met")
        # Turn ledger is folded by default and lists the latest turns.
        self.assertEqual(self.js("document.querySelector('details.turns').open"), 'false')
        self.assertIn("14:32:07", self.js("document.querySelector('details.turns table').textContent"))
        self.assertIn("41s", self.js("document.querySelector('details.turns table').textContent"))
        # The page survives polling and the switcher moves between projects.
        self.assertEqual(self.js("(async()=>{await refresh();return document.querySelectorAll('.card').length})()"), '1')
        self.js("[...document.querySelectorAll('.switcher button')].find(b=>b.textContent==='Atlas API').click()")
        self.assertIn("api-v3 · define", self.js("document.querySelector('.card').innerText"))
        self.assertEqual(self.js("[...document.querySelector('.card').querySelectorAll('.ms .k')].map(k=>k.textContent).join('|')"), "M002|next")
        self.assertIn("Blocked", self.js("document.querySelector('.card .pill').textContent"))
        # Cold deep link (the tray) opens the page directly; Back returns to the board.
        self.js("location.hash = 'project=' + encodeURIComponent('/sample/notes')")
        self.orca("wait", "--page", self.page, "--text", "end of roadmap")
        self.assertEqual(self.js("document.querySelector('.card').dataset.root"), "/sample/notes")
        self.js("document.querySelector('[data-nav=board]').click()")
        self.assertEqual(self.js("document.querySelectorAll('.prow').length"), '4')
        self.assertEqual(self.js("location.hash"), "")
        # Toolbar summary and connection.
        self.assertEqual(self.js("document.querySelector('.summary').textContent"), "4 projects · 2 in progress · 1 blocked · 1 shipped")
        self.assertIn("Connected", self.js("document.querySelector('.connection').textContent"))
        # Settings menu: survives polling, Escape closes it, Plugin and Watched folders remain reachable.
        self.assertEqual(self.js("document.querySelector('.settings-menu').open"), 'false')
        self.js("document.querySelector('.settings-menu summary').click()")
        self.assertEqual(self.js("(async()=>{await refresh();return document.querySelector('.settings-menu').open})()"), 'true')
        self.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
        self.assertEqual(self.js("document.querySelector('.settings-menu').open"), 'false')
        self.js("document.querySelector('[data-nav=folders]').click()")
        self.assertIn("Add folder", self.js("document.body.innerText"))
        self.assertIn("/sample", self.js("document.querySelector('.folder-row').textContent"))
        self.js("document.querySelector('[data-nav=plugin]').click()")
        self.orca("wait", "--page", self.page, "--text", "Plugin")
        self.assertEqual(self.js("(async()=>{await loadPlugin();render();return document.querySelector('.box h4').textContent})()"), "Global hosts")
        self.js("document.querySelector('[data-nav=board]').click()")
        self.assertEqual(self.js("document.querySelectorAll('.prow').length"), '4')
        # Narrow frame: no horizontal overflow on the board and on a project page.
        self.assertEqual(self.js("""new Promise(resolve => {
          const f = document.createElement('iframe');
          f.id = 'narrow'; f.style = 'width:390px;height:600px;border:0';
          f.src = location.href.split('#')[0] + '#project=%2Fsample%2Fgsd';
          f.onload = () => setTimeout(() => resolve(String(f.contentDocument.documentElement.scrollWidth)), 300);
          document.body.append(f);
        })"""), '390')
        self.js("document.querySelector('#narrow').remove()")
        # Removing every project must clear the board on the next poll.
        watcher.projects = {}
        self.js("refresh()")
        self.orca("wait", "--page", self.page, "--text", "No projects yet")
        server.shutdown()
        server.server_close()
        self.js("refresh()")
        self.orca("wait", "--page", self.page, "--text", "Offline")


if __name__ == "__main__":
    unittest.main()
