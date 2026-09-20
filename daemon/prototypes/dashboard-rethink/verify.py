"""Browser smoke check. Run with the prototype server on localhost:8876."""
import json
import subprocess


def orca(*args):
    output = subprocess.check_output(['orca', *args, '--json'], text=True)
    response = json.loads(output)
    assert response['ok'], response
    return response['result']


page = orca('tab', 'create', '--url', 'http://127.0.0.1:8876')['browserPageId']

def js(expression):
    return orca('eval', '--page', page, '--expression', expression)['result']

try:
    orca('wait', '--page', page, '--selector', '.board tbody')
    assert js("document.querySelectorAll('.board tbody tr').length") == '5'
    js("document.querySelector('[data-filter=blocked]').click()")
    assert js("document.querySelectorAll('.board tbody tr').length") == '1'
    js("document.querySelector('[data-project=civic]').click()")
    assert 'verification gap' in js("document.querySelector('.context-note').textContent")
    assert js("!!document.querySelector('[data-open-file]')") == 'true', 'Project evidence must open its source file'
    js("document.querySelector('[data-open-file]').click()")
    assert 'STATE.md' in js("document.querySelector('.file-path').textContent")
    assert 'Civic Nest' in js("document.querySelector('.document').textContent")
    js("document.querySelector('[data-format=raw]').click()")
    assert '# Civic Nest' in js("document.querySelector('.document pre').textContent")
    js("document.querySelector('#revision').value='0';document.querySelector('#revision').dispatchEvent(new Event('change',{bubbles:true}))")
    assert 'status: active' in js("document.querySelector('.document pre').textContent")
    js("document.querySelector('[data-format=preview]').click()")
    assert js("!!document.querySelector('.document h1')") == 'true'
    js("document.querySelector('#file-search').value='MANIFEST';document.querySelector('#file-search').dispatchEvent(new Event('input',{bubbles:true}))")
    assert js("document.querySelectorAll('[data-file]').length") == '1'
    js("document.querySelector('[data-file]').click()")
    assert 'archive/' in js("document.querySelector('.file-path').textContent")
    js("document.querySelector('#file-search').value='missing-file';document.querySelector('#file-search').dispatchEvent(new Event('input',{bubbles:true}))")
    assert 'No matching files' in js("document.querySelector('.file-list').textContent")
    js("document.querySelector('#file-search').value='README';document.querySelector('#file-search').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('[data-file]').click()")
    assert '<script>' in js("document.querySelector('.document').textContent")
    assert js("document.querySelectorAll('.document script').length") == '0'
    js("document.querySelector('[data-page=projects]').click();document.querySelector('[data-filter=all]').click();document.querySelector('[data-view=timeline]').click()")
    assert js("document.querySelectorAll('.road-row').length") == '5'
    js("document.querySelector('[data-page=settings]').click()")
    assert js("document.querySelector('#save').disabled") == 'true'
    js("document.querySelector('#shipping').value='pr';document.querySelector('#shipping').dispatchEvent(new Event('input',{bubbles:true}))")
    assert js("document.querySelector('#save').disabled") == 'false'
    js("document.querySelector('#save').click()")
    assert js("document.querySelector('#feedback').textContent") == 'Saved in this prototype'
    js("document.querySelector('#shipping').value='direct';document.querySelector('#shipping').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#discard').click()")
    assert js("document.querySelector('#shipping').value") == 'pr'
    js("document.querySelector('#theme').click()")
    assert js("document.documentElement.dataset.theme") == 'dark'
    js("document.querySelector('[data-page=projects]').click();document.querySelector('[data-view=board]').click();document.querySelector('#search').value='no-match';document.querySelector('#search').dispatchEvent(new Event('input',{bubbles:true}))")
    assert js("document.querySelectorAll('.board tbody tr').length") == '0', 'Search must filter project rows'
    assert 'No matching projects' in js("document.querySelector('.empty').textContent")
    print('PASS: board, filters, detail, timeline, settings save/discard, theme, search, empty state, file preview/raw, revisions, archive, inert HTML')
finally:
    tabs = orca('tab', 'list')['tabs']
    tab = next(t for t in tabs if t.get('browserPageId') == page)
    orca('tab', 'close', '--index', str(tab['index']))
