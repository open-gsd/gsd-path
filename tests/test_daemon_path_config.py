import http.client
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'daemon'))
from gsd_daemon.config import Config
from gsd_daemon.serve import serve_in_thread
from gsd_daemon.watcher import Watcher
from scripts import runtime_store
from tests.test_pipeline_state import state_text


class DashboardConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.repo = self.home / 'project'
        (self.repo / '.project').mkdir(parents=True)
        subprocess.run(['git', 'init', '-b', 'gsd-path/M001', str(self.repo)], check=True, capture_output=True)
        (self.repo / '.project/STATE.md').write_text(state_text(phase='define', status='active', branch='gsd-path/M001'))
        env = patch.dict(os.environ, {'HOME': str(self.home), 'USERPROFILE': str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        pin = runtime_store.publish(ROOT)
        (self.repo / '.gsd-path').mkdir()
        (self.repo / '.gsd-path/runtime.json').write_text(runtime_store.pin_text(pin))
        (self.repo / '.gsd-path/status_runtime.py').write_bytes((ROOT / 'scripts/status_runtime.py').read_bytes())
        watcher = Watcher(Config(parents=[str(self.home)], session_dirs=[], history=False))
        watcher.poll_once(scan_sessions=False)
        self.server, _ = serve_in_thread(watcher, port=0, plugin=Mock(src_dir=ROOT))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.watcher_stop.set)
        self.port = self.server.server_address[1]

    def request(self, method, body=None, origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        path = '/api/path-config'
        if method == 'GET':
            from urllib.parse import urlencode
            path += '?' + urlencode(body or {})
        conn.request(method, path, json.dumps(body) if method == 'POST' else None, headers)
        response = conn.getresponse()
        raw = response.read().decode()
        conn.close()
        return response.status, raw

    def test_settings_round_trip_through_selected_runtime(self):
        code, body = self.request('GET', {'scope': 'project', 'root': str(self.repo)})
        self.assertEqual(code, 200, body)
        code, body = self.request('POST', {'scope': 'project', 'root': str(self.repo),
                                         'key': 'integration', 'value': 'pull-request'})
        self.assertEqual(code, 200, body)
        self.assertIn('integration_default: pull-request', (self.repo / '.project/STATE.md').read_text())
        code, body = self.request('GET', {'scope': 'project', 'root': str(self.repo)})
        self.assertEqual(json.loads(body)['settings']['integration']['value'], 'pull-request')

    def test_user_defaults_and_request_boundaries(self):
        body = {'scope': 'user', 'key': 'review_panel', 'value': 'detected'}
        code, response = self.request('POST', body, origin='https://example.com')
        self.assertEqual(code, 403, response)
        self.assertFalse((self.home / '.gsd-path/config.json').exists())
        code, response = self.request('POST', body)
        self.assertEqual(code, 200, response)
        self.assertEqual(json.loads((self.home / '.gsd-path/config.json').read_text())['review_panel'], 'detected')
        code, response = self.request('POST', {**body, 'scope': 'project', 'root': str(self.home)})
        self.assertEqual(code, 400, response)
        code, response = self.request('POST', {**body, 'key': 'phase', 'value': 'build'})
        self.assertEqual(code, 400, response)

    @unittest.skipUnless(os.environ.get('GSD_UI_TEST'), 'requires Orca embedded browser')
    def test_browser_save_reload_and_project_lock(self):
        from tests.test_daemon_board_ui import BoardUITests
        self.orca = BoardUITests.orca.__get__(self)
        self.js = BoardUITests.js.__get__(self)
        self.page = self.orca('tab', 'create', '--url', f'http://127.0.0.1:{self.port}/#config')['browserPageId']
        tab = next(t for t in self.orca('tab', 'list')['tabs'] if t['browserPageId'] == self.page)
        self.addCleanup(self.orca, 'tab', 'close', '--index', str(tab['index']))
        self.orca('wait', '--page', self.page, '--load', 'networkidle')
        self.assertEqual(self.js("!!document.querySelector('[data-config-key=integration]')"), 'true')
        # Dense desktop controls need usable targets without overlapping neighbors.
        controls = json.loads(self.js("""JSON.stringify([...document.querySelectorAll(
            '.topbar button, .settings-menu summary, .path-config input, .path-config select, .path-config button, .path-config summary'
        )].filter(e => e.getClientRects().length).map(e => {
            const r = e.getBoundingClientRect();
            return {name: e.getAttribute('aria-label') || e.textContent || e.dataset.configKey,
                    width: r.width, height: r.height};
        }))"""))
        for control in controls:
            with self.subTest(control=control['name']):
                self.assertGreaterEqual(control['width'], 40)
                self.assertGreaterEqual(control['height'], 40)
        self.assertNotEqual(self.js("getComputedStyle(document.querySelector('[data-save-config=integration]')).backgroundColor"),
                            self.js("getComputedStyle(document.querySelector('[data-reset-config=integration]')).backgroundColor"))
        self.js("document.querySelector('[data-config-key=integration]').value='pull-request'; document.querySelector('[data-config-key=integration]').dispatchEvent(new Event('input', {bubbles:true})); document.querySelector('[data-save-config=integration]').click()")
        self.orca('wait', '--page', self.page, '--text', 'Saved')
        self.orca('reload', '--page', self.page)
        self.orca('wait', '--page', self.page, '--selector', '[data-config-key=integration]')
        self.assertEqual(self.js("document.querySelector('[data-config-key=integration]').value"), 'pull-request')
        self.assertEqual(json.loads((self.home / '.gsd-path/config.json').read_text())['integration'], 'pull-request')
        self.js("document.querySelector('[data-config-key=\"models.roles.coder.model\"]').value='example'; document.querySelector('[data-config-key=\"models.roles.coder.model\"]').dispatchEvent(new Event('input', {bubbles:true})); render()")
        self.assertEqual(self.js("document.querySelector('[data-config-key=\"models.roles.coder.model\"]').value"), 'example')
        self.js("document.querySelector('[data-save-config=\"models.roles.coder.model\"]').click()")
        self.orca('wait', '--page', self.page, '--text', 'Saved')
        self.assertEqual(json.loads((self.home / '.gsd-path/config.json').read_text())['models']['roles']['coder']['model'], 'example')
        (self.repo / '.project/STATE.md').write_text(state_text(phase='build', status='active'))
        self.js(f"document.querySelector('[data-config-scope]').value={json.dumps(str(self.repo))}; document.querySelector('[data-config-scope]').dispatchEvent(new Event('change', {{bubbles:true}}))")
        self.orca('wait', '--page', self.page, '--text', 'Shipping mode is locked')
        self.assertEqual(self.js("document.querySelector('[data-config-key=integration]').disabled"), 'true')


if __name__ == '__main__':
    unittest.main()
