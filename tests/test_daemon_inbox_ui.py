"""Opt-in browser acceptance test: GSD_UI_TEST=1 python3 -m unittest discover -s tests -p test_daemon_inbox_ui.py.

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
    return [
        ProjectStatus(root="/sample/gsd", project="GSD Path", milestone="M004", phase="build",
                      status="active", tasks_done=6, tasks_total=9, current_wave=2,
                      next_skill="gsd-path-build"),
        ProjectStatus(root="/sample/atlas'&tab=usage", project="Atlas API", milestone="M002",
                      phase="decide", status="active", health="amber", next_skill="gsd-path-discuss",
                      attention=[{"kind": "question", "label": "API version strategy", "ref": "A012"}, {"kind": "failed", "label": "Build failed", "ref": "T002"}],
                      answers=[{"id": "A012", "question": "Keep the current response format?",
                                "owner": "gsd-path-decide", "status": "NEEDS-USER"}],
                      ledger=[{"command": "python3 -m unittest test_api", "result": "pass"}, {"command": "unknown_check"}]),
        ProjectStatus(root="/sample/notes", project="Field Notes", phase="research", status="active"),
    ]


@unittest.skipUnless(os.environ.get("GSD_UI_TEST"), "requires Orca embedded browser")
class InboxUITests(unittest.TestCase):
    def orca(self, *args):
        result = subprocess.run([os.environ.get("ORCA_CLI_COMMAND", "orca"), *args, "--json"],
                                capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload)
        return payload["result"]

    def js(self, expression):
        return self.orca("eval", "--page", self.page, "--expression", expression)["result"]

    def test_inbox_navigation_and_live_states(self):
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
        self.assertEqual(self.js("document.querySelector('.intro h1').textContent"), "Projects")
        self.js("document.documentElement.dataset.theme = 'light'")
        self.assertEqual(self.js("getComputedStyle(document.body).backgroundColor"), "rgb(247, 248, 250)")
        self.js("document.documentElement.dataset.theme = 'dark'")
        self.assertEqual(self.js("getComputedStyle(document.body).backgroundColor"), "rgb(12, 13, 16)")
        self.assertEqual(self.js("getComputedStyle(document.querySelector('.brand')).fontSize"), "16px")
        self.assertEqual(self.js("getComputedStyle(document.querySelector('.intro h1')).fontSize"), "16px")
        self.assertEqual(self.js("getComputedStyle(document.querySelector('.project-item')).paddingTop"), "8px")
        self.assertEqual(self.js("document.querySelector('.inbox-detail h2').textContent"), "API version strategy")
        self.assertIn("Keep the current response format?", self.js("document.querySelector('.inbox-detail').innerText"))
        self.assertIn("python3 -m unittest test_api", self.js("document.querySelector('.inbox-detail').innerText"))
        self.assertEqual(self.js("document.querySelectorAll('.attention-item').length"), '2')
        self.assertEqual(self.js("[...document.querySelectorAll('.evidence-row')].find(e=>e.textContent.includes('unknown_check')).querySelector('strong').className"), 'dim')
        # Use the native dashboard's minimum window dimensions, with real expanded content.
        self.js("""new Promise(resolve => {
          const f = document.createElement('iframe');
          f.id = 'scroll-check'; f.style = 'width:900px;height:600px;border:0';
          f.src = location.href;
          f.onload = async () => { await f.contentWindow.refresh(); resolve('ready'); };
          document.body.append(f);
        })""")
        self.assertEqual(self.js("""(() => {
          const w = document.querySelector('#scroll-check').contentWindow;
          w.document.querySelector('.more').open = true;
          const pane = w.document.querySelector('.inbox-detail');
          pane.scrollTop = pane.scrollHeight;
          return pane.scrollTop > 0;
        })()"""), 'true')
        self.assertEqual(self.js("""(async () => {
          const w = document.querySelector('#scroll-check').contentWindow;
          const before = w.document.querySelector('.inbox-detail').scrollTop;
          await w.refresh();
          const pane = w.document.querySelector('.inbox-detail');
          return w.document.querySelector('.more').open && pane.scrollTop === before;
        })()"""), 'true')
        self.js("document.querySelector('#scroll-check').remove()")
        self.js("document.querySelector('[data-filter=running]').click()")
        self.assertNotIn("Atlas API", self.js("document.querySelector('.inbox-list').innerText"))
        self.assertIn("Field Notes", self.js("document.querySelector('.inbox-list').innerText"))
        self.js("document.querySelector('[data-filter=attention]').click()")
        self.assertIn("Atlas API", self.js("document.querySelector('.inbox-list').innerText"))
        self.assertNotIn("Field Notes", self.js("document.querySelector('.inbox-list').innerText"))
        self.js("document.querySelector('[data-action=discussion]').click()")
        self.assertIn("A012", self.js("document.querySelector('.inbox-detail').innerText"))
        self.assertIn("tab=activity", self.js("location.hash"))
        self.orca("reload", "--page", self.page)
        self.orca("wait", "--page", self.page, "--text", "A012")
        self.assertIn("Atlas API", self.js("document.querySelector('.inbox-detail').innerText"))
        self.js("CState.filter='all'; cSel('/sample/notes')")
        self.orca("reload", "--page", self.page)
        self.orca("wait", "--page", self.page, "--text", "Field Notes")
        self.assertEqual(self.js("document.querySelector('.project-item.sel strong').textContent"), "Field Notes")
        self.assertEqual(self.js("(async()=>{document.querySelector('.inbox-detail').focus();await refresh();return document.activeElement.className})()"), "inbox-detail")
        self.assertIn("/sample/notes", self.js("document.querySelector('.inbox-detail').innerText"))
        self.assertEqual(self.js("document.querySelector('.topnav') === null"), 'true')
        self.assertEqual(self.js("document.querySelector('.topbar').getBoundingClientRect().bottom <= document.querySelector('.inbox').getBoundingClientRect().top"), 'true')
        self.assertEqual(self.js("document.querySelector('.settings-menu').open"), 'false')
        self.js("document.querySelector('.settings-menu summary').click()")
        self.assertEqual(self.js("(async()=>{await refresh();return document.querySelector('.settings-menu').open})()"), 'true')
        # Removing the selected project must clear stale details on the next poll.
        watcher.projects = {}
        self.js("refresh()")
        self.orca("wait", "--page", self.page, "--text", "No projects yet")
        self.js("document.querySelector('[data-nav=folders]').click()")
        self.assertIn("Add folder", self.js("document.body.innerText"))
        self.js("document.querySelector('[data-nav=plugin]').click()")
        self.orca("wait", "--page", self.page, "--text", "Plugin")
        server.shutdown()
        server.server_close()
        self.js("refresh()")
        self.orca("wait", "--page", self.page, "--text", "Offline")


if __name__ == "__main__":
    unittest.main()
