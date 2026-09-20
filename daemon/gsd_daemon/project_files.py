"""Read-only access to watched project files and committed file revisions."""
from __future__ import annotations

import html
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Optional


class FileAccessError(ValueError):
    def __init__(self, message, code=400, status='failed'):
        super().__init__(message)
        self.code = code
        self.status = status


def _path(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise FileAccessError('A relative project file path is required.')
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or any(p in ('..', '.git') for p in path.parts):
        raise FileAccessError('File path must stay inside the selected project.', 403)
    return path.as_posix()


def _git(root, *args):
    return subprocess.run(['git', '--literal-pathspecs', '-C', str(root), *args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_NO_REPLACE_OBJECTS': '1'})


def _git_output(root, *args):
    result = _git(root, *args)
    if result.returncode:
        raise FileAccessError(result.stderr.decode('utf-8', 'replace').strip() or 'Git read failed.')
    return result.stdout


def _read_current(root, relative):
    """Walk with directory descriptors so a swapped parent symlink cannot escape."""
    if os.open not in os.supports_dir_fd or not hasattr(os, 'O_NOFOLLOW'):
        raise FileAccessError('Secure local file reading is unsupported on this platform.', 415, 'unsupported')
    parts = PurePosixPath(relative).parts
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = following
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file_fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise FileAccessError('Only regular files without hard links can be viewed.', 403)
            return stream.read(), info.st_mtime
    except FileNotFoundError:
        raise FileAccessError('File is not present in the working tree.', 404, 'missing')
    except OSError as error:
        raise FileAccessError('Cannot read this file safely: ' + str(error), 403)
    finally:
        os.close(fd)


def _group(path):
    return 'Archived milestone' if path.startswith('.project/archive/') else 'Project records' if path.startswith('.project/') else 'Repository'


def file_index(root):
    names = set()
    errors = []
    result = _git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard')
    if result.returncode == 0:
        names.update(n.decode('utf-8', 'surrogateescape') for n in result.stdout.split(b'\0') if n)
    else:
        errors.append({'source': 'repository', 'status': 'unavailable', 'error': result.stderr.decode('utf-8', 'replace').strip()})
    project = root / '.project'
    if not project.is_symlink() and project.is_dir():
        def failed(error):
            errors.append({'source': '.project', 'status': 'failed', 'error': str(error)})
        for parent, dirs, files in os.walk(project, followlinks=False, onerror=failed):
            dirs[:] = [d for d in dirs if d != '.git' and not (Path(parent) / d).is_symlink()]
            names.update((Path(parent) / f).relative_to(root).as_posix() for f in files)
    entries = []
    for name in sorted(names):
        try:
            relative = _path(name)
            path = root / relative
            if any(part.is_symlink() for part in [path, *list(path.parents)[:len(PurePosixPath(relative).parts)-1]]):
                continue
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                continue
            entries.append({'path': relative, 'group': _group(relative), 'bytes': info.st_size, 'modified': info.st_mtime})
        except (OSError, FileAccessError) as error:
            errors.append({'source': name, 'status': 'missing' if isinstance(error, FileNotFoundError) else 'failed', 'error': str(error)})
    return {'files': entries, 'coverage': errors, 'history_source': 'git',
            'scope': 'Git-tracked and non-ignored repository files, plus .project records. Symlinks, hard links and .git internals are excluded.'}


def file_history(root, relative):
    head = _git(root, 'rev-parse', '--verify', 'HEAD')
    if head.returncode:
        return {'path': relative, 'revisions': [], 'status': 'unavailable', 'reason': 'No committed Git history is available.'}
    output = _git_output(root, 'log', '-z', '--format=%H%x00%aI%x00%s', '--', relative)
    parts = output.decode('utf-8', 'replace').split('\0')
    revisions = [{'revision': parts[i], 'at': parts[i+1], 'label': parts[i+2], 'path': relative}
                 for i in range(0, len(parts)-2, 3)]
    return {'path': relative, 'revisions': revisions, 'status': 'loaded' if revisions else 'untracked',
            'reason': 'Committed versions of this path. Uncommitted edits are visible only in Working tree.'}


def _markdown(text):
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        return None, 'Markdown preview dependency is unavailable; raw text is still complete.'
    parser = MarkdownIt('commonmark', {'html': False}).enable(['table', 'strikethrough'])
    def image_text(renderer, tokens, index, options, env):
        return '<span class="file-image-note">[Image: ' + html.escape(tokens[index].content) + ']</span>'
    def link(renderer, tokens, index, options, env):
        token = tokens[index]
        href = token.attrGet('href') or ''
        # Viewer documents never navigate the host page or load local resources.
        if not href.startswith(('https://', 'http://')):
            token.attrSet('data-document-link', href)
            token.attrSet('href', '#')
        else:
            token.attrSet('target', '_blank')
            token.attrSet('rel', 'noopener noreferrer')
        return renderer.renderToken(tokens, index, options, env)
    parser.add_render_rule('image', image_text)
    parser.add_render_rule('link_open', link)
    metadata = re.match(r'\A---[ \t]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)', text, re.DOTALL)
    if metadata:
        # Keep frontmatter visible on demand without interpreting YAML as Markdown.
        header = '<details data-section="document-metadata"><summary>Document metadata</summary><pre>' + html.escape(metadata.group(1)) + '</pre></details>'
        return header + parser.render(text[metadata.end():]), None
    return parser.render(text), None


def read_file(root, relative, revision: Optional[str] = None):
    modified = None
    if revision:
        if not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', revision):
            raise FileAccessError('Use a full commit ID from the file history.')
        if _git(root, 'merge-base', '--is-ancestor', revision, 'HEAD').returncode:
            raise FileAccessError('Revision is not part of this project history.', 403)
        entry = _git_output(root, 'ls-tree', '-z', revision, '--', relative)
        if not entry:
            raise FileAccessError('File does not exist at this revision.', 404, 'missing')
        metadata, name = entry.rstrip(b'\0').split(b'\t', 1)
        mode, kind, blob = metadata.split()
        if mode not in (b'100644', b'100755') or kind != b'blob' or name.decode('utf-8', 'surrogateescape') != relative:
            raise FileAccessError('Only regular text files can be viewed.', 403)
        data = _git_output(root, 'cat-file', 'blob', blob.decode('ascii'))
    else:
        data, modified = _read_current(root, relative)
    try:
        text = data.decode('utf-8-sig')
        if '\0' in text:
            raise UnicodeError()
    except UnicodeError:
        raise FileAccessError('Binary or non-UTF-8 content cannot be previewed.', 415, 'unsupported')
    rendered, warning = _markdown(text) if relative.lower().endswith(('.md', '.markdown')) else (None, None)
    return {'path': relative, 'group': _group(relative), 'revision': revision, 'modified': modified,
            'bytes': len(data), 'text': text, 'html': rendered, 'preview_warning': warning, 'status': 'loaded'}


def request_files(projects, request):
    allowed = {'root', 'action', 'path', 'revision'}
    if set(request) - allowed:
        raise FileAccessError('Unknown file request fields.')
    raw_root = request.get('root')
    roots = {str(project.root) for project in projects.values()}
    if raw_root not in roots:
        raise FileAccessError('Select a watched project.', 403)
    root = Path(raw_root).resolve(strict=True)
    action = request.get('action', 'list')
    if action == 'list':
        return file_index(root)
    relative = _path(request.get('path'))
    if action == 'history':
        return file_history(root, relative)
    if action == 'read':
        return read_file(root, relative, request.get('revision'))
    raise FileAccessError('File API is read-only: use list, read, or history.')
