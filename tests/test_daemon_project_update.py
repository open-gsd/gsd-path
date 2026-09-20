"""Exercise the dashboard Update action with the real runtime installer."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'daemon'))
from gsd_daemon.config import Config
from gsd_daemon.model import ProjectStatus
from gsd_daemon.plugin import PluginManager
from gsd_daemon.serve import serve_in_thread
from tests import test_daemon_board_ui as board_ui

SOURCE = Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.environ.get('GSD_UI_TEST'), 'requires Orca browser')
class ProjectUpdateTests(unittest.TestCase):
    orca = board_ui.BoardUITests.orca
    js = board_ui.BoardUITests.js

    def test_real_update_and_dark_menu(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repo = home / 'project'
            runtime = repo / '.gsd-path/runtime'
            runtime.mkdir(parents=True)
            shutil.copy2(SOURCE / 'scripts/pipeline_state.py', runtime / 'pipeline_state.py')
            shutil.copy2(SOURCE / 'scripts/status_runtime.py', runtime.parent / 'status_runtime.py')
            for args in [('init', '-b', 'main'), ('add', '.'), ('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'legacy')]:
                subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
            (home / 'src').symlink_to(SOURCE, target_is_directory=True)
            def runner(argv, cwd=None):
                result = subprocess.run(argv, cwd=cwd, env={**os.environ, 'HOME': str(home)}, capture_output=True, text=True)
                return result.returncode, result.stdout, result.stderr
            manager = PluginManager(home=home, user_home=home, runner=runner,
                                    git_runner=lambda argv, **kw: (0, ' M daemon/gsd_daemon/serve.py\n', '') if 'status' in argv else (1, '', 'Your local changes would be overwritten by merge'), environ={})
            watcher = mock.Mock(config=Config(parents=[], session_dirs=[]), projects={str(repo): ProjectStatus(root=str(repo), project='Legacy project')})
            watcher.poll_once.return_value = []
            server, _ = serve_in_thread(watcher, port=0, plugin=manager)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            self.addCleanup(server.watcher_stop.set)
            self.page = self.orca('tab', 'create', '--url', f'http://127.0.0.1:{server.server_address[1]}/?theme=dark#plugin')['browserPageId']
            tab = next(t for t in self.orca('tab', 'list')['tabs'] if t['browserPageId'] == self.page)
            self.addCleanup(self.orca, 'tab', 'close', '--index', str(tab['index']))
            self.orca('wait', '--page', self.page, '--text', 'Unknown — version metadata unavailable')
            # Some system accents use black AccentColorText, even in dark mode.
            self.js("document.documentElement.style.setProperty('--accent-fg', '#000');document.querySelector('.settings-menu summary').click()")
            refs = self.orca('snapshot', '--page', self.page)['refs']
            key = next(k for k,v in refs.items() if v.get('role') == 'button' and v.get('name') == 'Path settings')
            self.orca('hover', '--page', self.page, '--element', '@'+key)
            with self.subTest('dark hover'):
                self.assertEqual(self.js("getComputedStyle(document.querySelector('.settings-menu [data-nav=config]')).color"), self.js('getComputedStyle(document.body).color'))
            self.js("document.querySelector('.settings-menu summary').click()")
            self.js("[...document.querySelectorAll('tr')].find(r=>r.textContent.includes('Unknown —')).querySelectorAll('button')[1].click()")
            self.orca('wait', '--page', self.page, '--selector', '.plugin-controls:not([disabled])')
            self.assertIn('Update complete', self.js("document.querySelector('#plugin-feedback').textContent"))
            self.assertIn('Using local plugin source', self.js("document.querySelector('#plugin-feedback').textContent"))
            pin = json.loads((repo / '.gsd-path/runtime.json').read_text())
            self.assertEqual(pin['version'], json.loads((SOURCE / 'package.json').read_text())['version'])
            self.assertFalse(runtime.exists())
            self.assertNotIn('Unknown —', self.js('document.body.innerText'))
            # A second click upgrades the pinned runtime, preserving its declaration.
            self.js("[...document.querySelectorAll('tr')].find(r=>r.textContent.includes('project') && r.querySelectorAll('button').length===3).querySelectorAll('button')[1].click()")
            self.orca('wait', '--page', self.page, '--selector', '.plugin-controls:not([disabled])')
            self.assertIn('Update complete', self.js("document.querySelector('#plugin-feedback').textContent"))
            self.assertIn('Using local plugin source', self.js("document.querySelector('#plugin-feedback').textContent"))
            self.assertEqual(json.loads((repo / '.gsd-path/runtime.json').read_text()), pin)
