"""Opt-in browser acceptance test: GSD_UI_TEST=1 python3 -m unittest discover -s tests -p test_daemon_board_ui.py.

Uses Orca's embedded browser and the real daemon HTTP handler with sample status.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
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
                      tasks=[TaskSummary(id="T001", title="state parser", wave=1, status="done", files=["daemon/probe.py"]),
                             TaskSummary(id="T005", title="poll loop", wave=2, status="done", files=["daemon/watcher.py", "tests/test_watcher.py"]),
                             TaskSummary(id="T006", title="notify hook", wave=2, status="pending")],
                      criteria=[{"id": "SC1", "text": "Status endpoint lists every project", "verdict": "met"},
                                {"id": "SC2", "text": "Tray opens the project page", "verdict": "met"},
                                {"id": "SC3", "text": "Notifications fire on block", "verdict": "not-met"}],
                      ledger=[{"command": "make test", "commit": "abc1234", "result": "pass", "recorded_at": "2026-09-12T14:32:00+00:00"},
                              {"command": "make lint", "commit": "9f8e7d6", "result": "fail", "recorded_at": "2026-09-12T13:10:00+00:00"}],
                      reviews=[{"file": "wave-1.cycle1.md", "kind": "wave", "verdict": "pass", "cycle": 1, "depth": "full", "note": "no findings"},
                               {"file": "wave-2.cycle2.md", "kind": "wave", "verdict": "revise", "cycle": 2, "depth": "verify-only", "note": "retry path missing"}],
                      integration="direct", health="amber", attention=[{"kind": "stale", "label": "no activity for 2d", "ref": None}],
                      phase_log=[{"phase": "define", "date": "2026-09-09"}, {"phase": "plan", "date": "2026-09-09"},
                                 {"phase": "build", "date": "2026-09-10"}],
                      vision="See every gsd-path project's state without a terminal.",
                      intent="Operators stop polling STATE.md by hand.",
                      lesson="003-core — Land task evidence through the isolation helper.",
                      spend={"turns": 90, "prompts": 12, "tokens_in": 9000000, "tokens_cached": 5000000, "tokens_out": 100000,
                             "cost": 26.1, "unpriced": ["claude-sonnet-5"], "priced_turns": 84, "duration_s": 5400.0, "timed_turns": 84,
                             "models": [{"model": "gpt-6-astra", "host": "codex", "turns": 84, "tokens": 14000000, "cost": 24.6},
                                        {"model": "claude-sonnet-5", "host": "claude", "turns": 6, "tokens": 100000, "cost": None}],
                             "agents": [{"agent": "$gsd-path-build · T006", "models": ["gpt-6-astra"], "turns": 60, "tokens": 10000000, "cost": 18.0, "duration_s": 3720.0},
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
        history = Path(tempfile.mkdtemp()) / "history.jsonl"
        history.write_text("\n".join(json.dumps(e) for e in [
            {"type": "phase-changed", "root": "/sample/gsd", "detail": "plan -> build", "at": "2026-09-10T09:12:00+00:00"},
            {"type": "tasks-changed", "root": "/sample/gsd", "detail": "6/9 done (was 5/9)", "at": "2026-09-12T14:30:00+00:00"},
            {"type": "phase-changed", "root": "/sample/notes", "detail": "define -> research", "at": "2026-09-12T14:31:00+00:00"},
        ]) + "\n", encoding="utf-8")
        env = mock.patch.dict("os.environ", {"GSD_DAEMON_HISTORY": str(history)})
        env.start()
        self.addCleanup(env.stop)
        server, _ = serve_in_thread(watcher, port=0, plugin=plugin)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.watcher_stop.set)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        self.page = self.orca("tab", "create", "--url", url)["browserPageId"]
        self.orca("wait", "--page", self.page, "--text", "Atlas API")
        # Appearance: light by default; light and dark palettes both resolve.
        self.assertEqual(self.js("document.documentElement.dataset.theme"), "light")
        self.js("document.documentElement.dataset.theme = 'light'")
        self.assertEqual(self.js("getComputedStyle(document.body).backgroundColor"), "rgb(251, 252, 253)")
        self.js("document.documentElement.dataset.theme = 'dark'")
        self.assertEqual(self.js("getComputedStyle(document.body).backgroundColor"), "rgb(16, 18, 20)")
        self.js("applyTheme()")
        # Board: one table row per project; blocked first, then active, then shipped.
        names = "[...document.querySelectorAll('.prow .pname span:last-child')].map(b=>b.textContent).join('|')"
        self.assertEqual(self.js(names), "Atlas API|Field Notes|GSD Path|Done Thing")
        self.assertEqual(self.js("[...document.querySelectorAll('.topbar > .segc button')].map(b=>b.textContent+(b.getAttribute('aria-pressed')==='true'?'*':'')).join('|')"),
                         "All4*|Active3|Shipped1")
        gsd_row = "document.querySelector('.prow[data-root=\"/sample/gsd\"]')"
        self.assertEqual(self.js(f"{gsd_row}.querySelector('.route').getAttribute('aria-label')"), "M003 ✓  M004 ●  M005 ○")
        self.assertEqual(self.js(f"[...{gsd_row}.querySelectorAll('.route i')].map(i=>i.className).join('|')"), "done|now|ahead")
        self.assertEqual(self.js(f"[...{gsd_row}.cells].slice(2).map(c=>c.textContent.trim()).join('|')"),
                         "M004daemon|build|6/9|$26.10|90|—|In build")
        self.assertEqual(self.js(f"[...{gsd_row}.querySelectorAll('.meter i')].map(i=>i.className[0]||'-').join('')"), "ddddddn-")
        self.assertEqual(self.js(f"{gsd_row}.querySelector('.dot').title"), "health amber · no activity for 2d")
        atlas_row = "document.querySelector('.prow.blocked')"
        self.assertEqual(self.js(f"{atlas_row}.querySelector('.route').getAttribute('aria-label')"), "M002 ■  next ○")
        self.assertEqual(self.js(f"{atlas_row}.querySelector('.meter.blocked i.now').title"), "ship")
        self.assertEqual(self.js("document.querySelector('.prow.shipped .state').textContent"), "Shipped")
        self.assertEqual(self.js("document.querySelectorAll('.prow.shipped .meter i.done').length"), '8')
        # No next steps, commands or attention copy anywhere on the board.
        board = self.js("document.querySelector('.board').innerText")
        for gone in ("gsd-path-build", "forensics", "Copy", "Next step", "ship blocked", "Needs you"):
            self.assertNotIn(gone, board)
        # Filters and search narrow the table; the search field keeps focus through polling.
        self.js("document.querySelector('[data-filter=shipped]').click()")
        self.assertEqual(self.js(names), "Done Thing")
        self.js("document.querySelector('[data-filter=all]').click()")
        self.js("(()=>{const q=document.querySelector('[data-search]');q.focus();q.value='atl';q.dispatchEvent(new Event('input',{bubbles:true}))})()")
        self.assertEqual(self.js(names), "Atlas API")
        self.assertEqual(self.js("(async()=>{await refresh();const a=document.activeElement;return a.matches('[data-search]')+':'+a.value+':'+a.selectionStart})()"), "true:atl:3")
        self.js("(()=>{const q=document.querySelector('[data-search]');q.value='zzz';q.dispatchEvent(new Event('input',{bubbles:true}))})()")
        self.assertEqual(self.js("document.querySelector('.board .empty').textContent"), "No projects match this filter.")
        self.js("(()=>{const q=document.querySelector('[data-search]');q.value='';q.dispatchEvent(new Event('input',{bubbles:true}));q.blur()})()")
        self.assertEqual(self.js("document.querySelectorAll('.prow').length"), '4')
        # A row opens the project page: facts, phase track, milestones, usage; switcher and hash deep link.
        self.js(f"{gsd_row}.cells[3].click()")
        self.assertEqual(self.js("location.hash"), "#project=%2Fsample%2Fgsd")
        self.assertEqual(self.js("document.querySelectorAll('.project').length"), '1')
        self.assertEqual(self.js("[...document.querySelectorAll('.switcher option')].map(o=>o.textContent+(o.selected?'*':'')).join('|')"),
                         "Atlas API|Field Notes|GSD Path*|Done Thing")
        page = "document.querySelector('.project')"
        self.assertEqual(self.js(f"[...{page}.querySelectorAll('.facts div')].map(d=>d.querySelector('dt').textContent+'='+d.querySelector('dd').textContent).join('|')"),
                         "State=In build|Health=amber · no activity for 2d|Milestone=M004|Branch=gsd-path/M004|Head=0e9a3b1 · dirty|Integration=direct|Updated=—|Cost=$26.10|Turns=90")
        self.assertEqual(self.js(f"[...{page}.querySelectorAll('.milestones tr.ms')].map(m=>m.classList[1]+':'+m.querySelector('.k').textContent).join('|')"),
                         "done:M003|now:M004|ahead:M005")
        self.assertEqual(self.js(f"[...{page}.querySelectorAll('.phases div')].map(d=>(d.className||'-')+':'+d.title).join('|')"),
                         "done:inspect|done:define · 2026-09-09|done:research|done:decide|done:roadmap|done:plan · 2026-09-09|now:build · 2026-09-10|-:ship")
        text = self.js(f"{page}.innerText")
        for expected in ("core", "daemon", "notify", "M004 daemon · build · wave 2", "6 of 9 tasks · entered build 2026-09-10 · 5h 0m",
                         "✓ wave 1 parsers", "● wave 2 watcher", "○ wave 3 tray",
                         # briefing details
                         "See every gsd-path project's state without a terminal.", "shipped 2026-09-06",
                         "12 of 12 tasks · 3 waves · 1.3 review cycles avg · integrated 158ab3a · 2 rulings carried · all criteria met",
                         "$1.50 · 6 turns", "$24.60 · 84 turns",
                         "Parsers and the status endpoint.", "after M003", "Native tray and dashboard for the daemon.",
                         "Operators stop polling STATE.md by hand.", "state parser", "poll loop", "notify hook", "2 watcher",
                         "2 of 3 criteria met", "verify pass 14:32:00", "Desktop notifications.", "after M004",
                         "003-core — Land task evidence through the isolation helper.",
                         # usage: models, agents; unpriced model excluded from cost
                         "gpt-6-astra", "$24.60", "claude-sonnet-5",
                         "$gsd-path-build · T006", "$gsd-path-build · reviewer", "No price configured for claude-sonnet-5",
                         # criteria, task files, reviews, verify ledger, activity
                         "Status endpoint lists every project", "Notifications fire on block", "daemon/watcher.py",
                         "retry path missing", "verify-only", "make lint", "9f8e7d6", "plan -> build", "6/9 done (was 5/9)"):
            self.assertIn(expected, text)
        self.assertNotIn("define -> research", text)  # another project's change
        self.assertEqual(self.js(f"[...{page}.querySelectorAll('.stats div')].map(d=>d.querySelector('dt').textContent+'='+d.querySelector('dd').textContent).join('|')"),
                         "Cost=$26.10|Turns=90|Prompts=12|Tokens in=9.0M|Cached=5.0M|Tokens out=100k|Cache hit=36%|Agent time=1h 30m|Cost / turn=$0.31|Time / turn=64s")
        self.assertEqual(self.js(f"[...{page}.querySelectorAll('.agents tr')].slice(1).map(r=>r.cells[3].textContent).join('|')"), "1h 2m|—")
        self.assertEqual(self.js(f"[...{page}.querySelectorAll('.models tr')].slice(1).map(r=>r.cells[1].textContent).join('|')"), "codex|claude")
        self.assertEqual(self.js(f"[...{page}.querySelectorAll('.milestones tr.ms .meta')].filter(m=>m.textContent.endsWith('tokens')).map(m=>m.textContent).join('|')"),
                         "1.0M tokens|14.1M tokens")
        self.assertEqual(self.js(f"[...{page}.querySelectorAll('.criteria td.st span')].map(v=>v.className).join('|')"), "verdict-met|verdict-met|verdict-not-met")
        self.assertEqual(self.js(f"[...{page}.querySelectorAll('.reviews tr')].slice(1).map(r=>r.title+':'+r.cells[3].textContent).join('|')"),
                         "wave-1.cycle1.md:pass|wave-2.cycle2.md:revise")
        self.assertEqual(self.js(f"[...{page}.querySelectorAll('.ledger tr')].slice(1).map(r=>r.cells[0].textContent+' '+r.cells[3].textContent).join('|')"),
                         "2026-09-12 14:32 pass|2026-09-12 13:10 fail")
        self.assertEqual(self.js(f"[...{page}.querySelectorAll('.activity tr')].slice(1).map(r=>r.cells[1].textContent).join('|')"), "tasks-changed|phase-changed")
        self.assertEqual(self.js(f"[...{page}.querySelectorAll('.crit i')].map(i=>i.className).join('|')"), "met|met|not-met")
        # Turn ledger is folded by default and lists the latest turns.
        self.assertEqual(self.js("document.querySelector('details.turns').open"), 'false')
        self.assertIn("14:32:07", self.js("document.querySelector('details.turns table').textContent"))
        self.assertIn("41s", self.js("document.querySelector('details.turns table').textContent"))
        # The page survives polling and the switcher moves between projects.
        self.assertEqual(self.js("(async()=>{await refresh();return document.querySelectorAll('.project').length})()"), '1')
        self.js("(()=>{const s=document.querySelector('.switcher');s.value=\"/sample/atlas'&tab=usage\";s.dispatchEvent(new Event('change',{bubbles:true}))})()")
        self.assertIn("api-v3", self.js("document.querySelector('.project').innerText"))
        self.assertIn("define · pending", self.js("document.querySelector('.project').innerText"))
        self.assertEqual(self.js("[...document.querySelectorAll('.milestones .k')].map(k=>k.textContent).join('|')"), "M002|next")
        self.assertEqual(self.js("document.querySelector('.facts dd').textContent"), "Blocked")
        # Cold deep link (the tray) opens the page directly; Back returns to the board.
        self.js("location.hash = 'project=' + encodeURIComponent('/sample/notes')")
        self.orca("wait", "--page", self.page, "--text", "end of roadmap")
        self.assertEqual(self.js("document.querySelector('.project').dataset.root"), "/sample/notes")
        self.js("document.querySelector('[data-nav=board]').click()")
        self.assertEqual(self.js("document.querySelectorAll('.prow').length"), '4')
        self.assertEqual(self.js("location.hash"), "")
        # Toolbar connection.
        self.assertIn("Updated", self.js("document.querySelector('.connection').textContent"))
        # Settings menu: survives polling, Escape closes it, Plugin and Watched folders remain reachable.
        self.assertEqual(self.js("document.querySelector('.settings-menu').open"), 'false')
        self.js("document.querySelector('.settings-menu summary').click()")
        self.assertEqual(self.js("(async()=>{await refresh();return document.querySelector('.settings-menu').open})()"), 'true')
        # Appearance choice: applied, remembered, and the menu stays open.
        self.js("document.querySelector('[data-theme-choice=dark]').click()")
        self.assertEqual(self.js("document.documentElement.dataset.theme+':'+localStorage.getItem('gsd-theme')+':'+document.querySelector('.settings-menu').open"), "dark:dark:true")
        self.assertEqual(self.js("document.querySelector('[data-theme-choice=dark]').getAttribute('aria-pressed')"), "true")
        self.js("document.querySelector('[data-theme-choice=system]').click()")
        self.assertEqual(self.js("String('theme' in document.documentElement.dataset)"), "false")
        self.js("document.querySelector('[data-theme-choice=light]').click()")
        self.assertEqual(self.js("document.documentElement.dataset.theme"), "light")
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
          f.src = location.href.split('#')[0] + '?theme=dark#project=%2Fsample%2Fgsd';
          f.onload = () => setTimeout(() => resolve(f.contentDocument.documentElement.scrollWidth + ':' + f.contentDocument.documentElement.dataset.theme), 300);
          document.body.append(f);
        })"""), '390:dark')
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
