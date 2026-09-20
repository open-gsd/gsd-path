import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'daemon'))
from gsd_daemon.config import Config
from gsd_daemon.model import ProjectStatus
from gsd_daemon.serve import serve_in_thread


class ProjectFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        self.root.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.root / '.project').mkdir()
        self.state = self.root / '.project/STATE.md'
        self.state.write_text('# Initial\n\nstatus: active\n')
        self.git('add', '.')
        self.git('commit', '-m', 'Initial state')
        self.first = self.git('rev-parse', 'HEAD').strip()
        self.state.write_text('# Current\n\nstatus: blocked\n')
        self.git('commit', '-am', 'Record blocked state')
        self.latest = self.git('rev-parse', 'HEAD').strip()
        watcher = Mock(config=Config(parents=[], session_dirs=[]), projects={str(self.root): ProjectStatus(root=str(self.root))})
        self.server, _ = serve_in_thread(watcher, port=0, plugin=Mock())
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.watcher_stop.set)
        self.port = self.server.server_address[1]
        self.watcher = watcher
        self.watcher.sessions.records_for.return_value = []

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True)

    def request(self, action='list', headers=None, **fields):
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        self.addCleanup(conn.close)
        query = urlencode({'root': str(self.root), 'action': action, **fields})
        conn.request('GET', '/api/project-files?' + query, headers=headers or {})
        response = conn.getresponse()
        raw = response.read().decode()
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw
        return response.status, body

    def test_real_files_raw_and_revision_history(self):
        archive = self.root / '.project/archive/001/FINAL.md'
        archive.parent.mkdir(parents=True)
        archive.write_text('# Archived evidence\n')
        (self.root / 'README.md').write_text('# Repository\n')
        code, data = self.request()
        self.assertEqual(code, 200, data)
        self.assertEqual({f['path'] for f in data['files']}, {'.project/STATE.md', '.project/archive/001/FINAL.md', 'README.md'})
        code, data = self.request('read', path='.project/STATE.md')
        self.assertEqual(code, 200, data)
        self.assertEqual(data['text'], self.state.read_text())
        code, data = self.request('history', path='.project/STATE.md')
        self.assertEqual(code, 200, data)
        self.assertEqual([r['revision'] for r in data['revisions']], [self.latest, self.first])
        code, data = self.request('read', path='.project/STATE.md', revision=self.first)
        self.assertEqual(code, 200, data)
        self.assertEqual(data['text'], '# Initial\n\nstatus: active\n')
        self.assertIn('blocked', self.state.read_text())
        self.assertEqual(self.request('read', path='.project/archive/001/FINAL.md')[1]['text'], archive.read_text())

    def test_paths_origin_and_revision_are_confined(self):
        outside = self.root.parent / 'outside.md'
        outside.write_text('outside secret')
        (self.root / 'linked.md').symlink_to(outside)
        (self.root / '.project/link').symlink_to(self.root.parent, target_is_directory=True)
        for path in ['.', '../outside.md', str(outside), '.git/config', 'linked.md', '.project/link/outside.md']:
            with self.subTest(path=path):
                code, body = self.request('read', path=path)
                self.assertIn(code, (400, 403), body)
                self.assertNotIn('outside secret', str(body))
        self.assertEqual(self.request(root=str(self.root.parent))[0], 403)
        self.assertEqual(self.request(headers={'Host': f'evil.invalid:{self.port}'})[0], 403)
        self.assertEqual(self.request(headers={'Origin': 'https://evil.invalid'})[0], 403)
        self.assertEqual(self.request('read', path='.project/STATE.md', revision='HEAD~1')[0], 400)
        self.assertEqual(self.request('write', path='.project/STATE.md')[0], 400)

    @unittest.skipUnless(os.environ.get('GSD_UI_TEST'), 'requires Orca browser')
    def test_browser_live_file_versions_and_full_records(self):
        from tests.test_daemon_board_ui import BoardUITests
        self.state.write_text(self.state.read_text() + '\n[Invalid encoded link](a%FF.md)\n')
        self.orca = BoardUITests.orca.__get__(self)
        self.js = BoardUITests.js.__get__(self)
        self.page = self.orca('tab', 'create', '--url', f'http://127.0.0.1:{self.port}/')['browserPageId']
        tab = next(t for t in self.orca('tab', 'list')['tabs'] if t.get('browserPageId') == self.page)
        self.addCleanup(self.orca, 'tab', 'close', '--index', str(tab['index']))
        self.orca('wait', '--page', self.page, '--selector', '.pname')
        self.js("document.querySelector('.pname').click();document.querySelector('[data-open-file]').click()")
        self.orca('wait', '--page', self.page, '--selector', '.document h1')
        self.assertEqual(self.js("document.querySelector('.document h1').textContent"), 'Current')
        self.js("window.fileLinkErrors=[];window.addEventListener('error',event=>{fileLinkErrors.push(event.message);event.preventDefault()});document.querySelector('[data-document-link]').click()")
        self.assertEqual(self.js('JSON.stringify(fileLinkErrors)'), '[]')
        self.assertEqual(self.js("document.querySelector('.document h1').textContent"), 'Current')
        self.js("document.querySelector('[data-file-format=raw]').click()")
        self.assertIn('status: blocked', self.js("document.querySelector('.document pre').textContent"))
        self.js(f"document.querySelector('[data-file-revision]').value='{self.first}';document.querySelector('[data-file-revision]').dispatchEvent(new Event('change',{{bubbles:true}}))")
        self.orca('wait', '--page', self.page, '--text', 'status: active')
        self.assertIn(self.first, self.js('location.hash'))
        self.orca('reload', '--page', self.page)
        self.orca('wait', '--page', self.page, '--selector', '.document h1')
        self.assertEqual(self.js("document.querySelector('.document h1').textContent"), 'Initial')
        self.js("document.querySelector('[data-file-search]').value='STATE';document.querySelector('[data-file-search]').dispatchEvent(new Event('input',{bubbles:true}))")
        self.assertEqual(self.js("(async()=>{await refresh();return document.querySelector('[data-file-search]').value})()"), 'STATE')
        self.assertEqual(self.js("document.querySelectorAll('[data-select-file]').length"), '1')
        self.js("document.querySelector('.breadcrumb [data-root]').click();document.querySelector('[data-load-records]').click()")
        self.orca('wait', '--page', self.page, '--selector', '[data-section=coverage]')
        self.assertIn('missing', self.js("document.querySelector('[data-section=coverage]').textContent"))
        self.js("document.querySelector('[data-nav=board]').click()")
        self.assertEqual(self.js("document.querySelector('[data-search]').value"), '')
        self.assertEqual(self.js("document.querySelectorAll('.prow').length"), '1')

    def test_full_records_and_missing_coverage(self):
        build = self.root / '.project/build'
        build.mkdir()
        entries = [{'task': 'T001', 'tokens_in': n} for n in range(25)]
        (build / 'usage.jsonl').write_text('\n'.join(json.dumps(e) for e in entries) + '\nnot-json\n')
        (build / 'verify-ledger.jsonl').write_text('\n'.join(json.dumps(e) for e in entries))
        self.watcher.sessions.records_for.return_value = [{'tokens_in': n} for n in range(25)]
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        self.addCleanup(conn.close)
        conn.request('GET', '/api/project-data?' + urlencode({'root': str(self.root)}))
        response = conn.getresponse()
        data = json.loads(response.read())
        self.assertEqual(response.status, 200, data)
        self.assertEqual(data['usage_records'], entries)
        self.assertEqual(data['verify_records'], list(reversed(entries)))
        self.assertEqual(len(data['turns']), 25)
        sources = {s['path']: s for s in data['sources']}
        self.assertEqual(sources['.project/build/usage.jsonl']['invalid_lines'], [26])
        self.assertEqual(sources['.project/build/usage.jsonl']['status'], 'partial')
        self.assertEqual(sources['.project/intent/INTENT.md']['status'], 'missing')

    def test_markdown_preview_does_not_execute_html_or_fetch_images(self):
        import importlib.util
        if importlib.util.find_spec('markdown_it') is None:
            self.skipTest('Markdown renderer is installed with the daemon package')
        text = '---\ntitle: Preview <safe>\nstatus: active\n---\n# Heading\n\n<script>alert(1)</script>\n\n![pixel](https://example.invalid/pixel)\n\n[x](javascript:alert(1))\n\n[State](.project/STATE.md)\n\n| Name | State |\n| --- | --- |\n| Task | Done |\n'
        (self.root / 'README.md').write_text(text)
        code, body = self.request('read', path='README.md')
        self.assertEqual(code, 200, body)
        rendered = body['html']
        self.assertIn('<h1>Heading</h1>', rendered)
        self.assertIn('<table>', rendered)
        self.assertIn('<summary>Document metadata</summary>', rendered)
        self.assertIn('title: Preview &lt;safe&gt;', rendered)
        self.assertNotIn('<h2>title:', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('<img', rendered)
        self.assertNotIn('href="javascript:', rendered)
        self.assertIn('data-document-link=".project/STATE.md"', rendered)
        self.assertEqual(body['text'], text)

    def test_untracked_binary_missing_and_literal_path(self):
        (self.root / 'image.bin').write_bytes(b'abc\x00def')
        (self.root / 'a [draft].md').write_text('literal name')
        code, body = self.request('history', path='a [draft].md')
        self.assertEqual(code, 200, body)
        self.assertEqual(body['revisions'], [])
        self.assertEqual(body['status'], 'untracked')
        self.assertEqual(self.request('read', path='a [draft].md')[1]['text'], 'literal name')
        code, body = self.request('read', path='image.bin')
        self.assertEqual(code, 415, body)
        self.assertEqual(body['status'], 'unsupported')
        self.assertEqual(self.request('read', path='missing.md')[0], 404)


if __name__ == '__main__':
    unittest.main()
