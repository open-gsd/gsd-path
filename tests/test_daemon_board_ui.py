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
from gsd_daemon.model import ProjectStatus
from gsd_daemon.serve import serve_in_thread


def sample_projects():
    roadmap = [
        {"number": "M003", "slug": "core", "status": "shipped", "archive": ".project/archive/003-core"},
        {"number": "M004", "slug": "daemon", "status": "active", "archive": None},
        {"number": "M005", "slug": "notify", "status": "pending", "archive": None},
    ]
    return [
        ProjectStatus(root="/sample/gsd", project="GSD Path", milestone="daemon", phase="build",
                      status="active", branch="gsd-path/M004", tasks_done=6, tasks_total=9, current_wave=2,
                      waves={1: "parsers", 2: "watcher", 3: "tray"}, roadmap_milestones=roadmap,
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
        # One card per project, blocked first, then active, then shipped.
        self.assertEqual(self.js("[...document.querySelectorAll('.card .title b')].map(b=>b.textContent).join('|')"),
                         "Atlas API|Field Notes|GSD Path|Done Thing")
        # Done / here / ahead stack from ROADMAP.md.
        gsd = "[...document.querySelectorAll('.card')].find(c=>c.dataset.root==='/sample/gsd')"
        self.assertEqual(self.js(f"[...{gsd}.querySelectorAll('.ms')].map(m=>m.className.split(' ')[1]+':'+m.querySelector('.k').textContent).join('|')"),
                         "done:M003|now:M004|ahead:M005")
        text = self.js(f"{gsd}.innerText")
        for expected in ("core", "daemon", "notify", "build · wave 2", "6 of 9 tasks", "5h 0m in build",
                         "✓ wave 1 parsers", "● wave 2 watcher", "○ wave 3 tray", "gsd-path/M004 · 0e9a3b1 · dirty", "In build"):
            self.assertIn(expected, text)
        # No next steps, commands or attention copy anywhere on the board.
        board = self.js("document.querySelector('.board').innerText")
        for gone in ("gsd-path-build", "forensics", "Copy", "Next step", "ship blocked", "Needs"):
            self.assertNotIn(gone, board)
        # Lookahead milestone from next/STATE.md, number from the branch when ROADMAP.md is empty.
        atlas = "[...document.querySelectorAll('.card')].find(c=>c.dataset.root.startsWith('/sample/atlas'))"
        self.assertEqual(self.js(f"[...{atlas}.querySelectorAll('.ms .k')].map(k=>k.textContent).join('|')"), "M002|next")
        self.assertIn("api-v3 · define", self.js(f"{atlas}.innerText"))
        self.assertIn("Blocked", self.js(f"{atlas}.querySelector('.pill').textContent"))
        self.assertIn("end of roadmap", self.js("[...document.querySelectorAll('.card')].find(c=>c.dataset.root==='/sample/notes').innerText"))
        self.assertIn("Shipped", self.js("[...document.querySelectorAll('.card')].find(c=>c.dataset.root==='/sample/done').querySelector('.pill').textContent"))
        # Toolbar summary and connection.
        self.assertEqual(self.js("document.querySelector('.summary').textContent"), "4 projects · 2 in progress · 1 blocked · 1 shipped")
        self.assertIn("Connected", self.js("document.querySelector('.connection').textContent"))
        # Deep link from the tray selects and reveals the card; the selection survives polling.
        self.js("location.hash = 'project=' + encodeURIComponent('/sample/notes')")
        self.assertEqual(self.js("(async()=>{await new Promise(r=>setTimeout(r,50));await refresh();return document.querySelector('.card.sel').dataset.root})()"), "/sample/notes")
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
        self.assertEqual(self.js("document.querySelectorAll('.card').length"), '4')
        # Narrow frame: no horizontal overflow.
        self.assertEqual(self.js("""new Promise(resolve => {
          const f = document.createElement('iframe');
          f.id = 'narrow'; f.style = 'width:390px;height:600px;border:0';
          f.src = location.href.split('#')[0];
          f.onload = () => resolve(String(f.contentDocument.documentElement.scrollWidth));
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
