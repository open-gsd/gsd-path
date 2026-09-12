import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon import discovery

STATE_V2 = """---
pipeline: gsd-path/v2
project: demo
milestone: null
phase: define
status: active
branch: null
archive: null
---

# Project State
"""

STATE_NO_MARKER = """---
pipeline: something/else
project: demo
phase: define
status: active
---
"""


def make_project(root: Path, state: str = STATE_V2) -> Path:
    project_dir = root / ".project"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "STATE.md").write_text(state, encoding="utf-8")
    return root


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name) / "work"
        self.parent.mkdir()

    def scan(self, **kwargs) -> list:
        return discovery.scan([str(self.parent)], **kwargs)

    def test_finds_project_at_depth_one(self) -> None:
        project = make_project(self.parent / "alpha")
        self.assertEqual(self.scan(), [str(project)])

    def test_finds_projects_at_depth(self) -> None:
        deep = make_project(self.parent / "a" / "b" / "c" / "deep-proj")
        shallow = make_project(self.parent / "shallow")
        self.assertEqual(self.scan(), [str(deep), str(shallow)])

    def test_parent_itself_can_be_project(self) -> None:
        make_project(self.parent)
        self.assertEqual(self.scan(), [str(self.parent)])

    def test_requires_v2_marker(self) -> None:
        make_project(self.parent / "legacy", state=STATE_NO_MARKER)
        make_project(self.parent / "no-frontmatter", state="# no frontmatter\n")
        make_project(self.parent / "valid")
        self.assertEqual(self.scan(), [str(self.parent / "valid")])

    def test_max_depth(self) -> None:
        make_project(self.parent / "a" / "b" / "c" / "d" / "too-deep")
        self.assertEqual(self.scan(max_depth=4), [])
        self.assertEqual(self.scan(max_depth=5), [str(self.parent / "a" / "b" / "c" / "d" / "too-deep")])

    def test_excludes_exact_and_prefix(self) -> None:
        keep = make_project(self.parent / "keep")
        excluded_root = make_project(self.parent / "archive")
        nested = make_project(self.parent / "archive" / "nested")
        results = self.scan(excludes=[str(excluded_root)])
        self.assertEqual(results, [str(keep)])
        self.assertNotIn(str(nested), results)

    def test_no_descend_below_project_root(self) -> None:
        outer = make_project(self.parent / "outer")
        make_project(self.parent / "outer" / "inner")
        self.assertEqual(self.scan(), [str(outer)])

    def test_skips_hidden_and_vendor_dirs(self) -> None:
        make_project(self.parent / ".hidden" / "proj")
        make_project(self.parent / "pkg" / "node_modules" / "proj")
        make_project(self.parent / "env" / ".venv" / "proj")
        make_project(self.parent / "src" / "__pycache__" / "proj")
        make_project(self.parent / "repo" / ".git" / "proj")
        visible = make_project(self.parent / "visible")
        self.assertEqual(self.scan(), [str(visible)])

    def test_missing_and_excluded_parents_ignored(self) -> None:
        results = discovery.scan(
            [str(self.parent / "does-not-exist"), str(self.parent)],
            excludes=[str(self.parent)],
        )
        self.assertEqual(results, [])

    def test_state_md_without_project_dir_is_not_project(self) -> None:
        stray = self.parent / "stray"
        stray.mkdir()
        (stray / "STATE.md").write_text(STATE_V2, encoding="utf-8")
        self.assertEqual(self.scan(), [])


class WorktreeDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name) / "work"
        self.parent.mkdir()

    def _git(self, *args: str, cwd: Path) -> None:
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
            cwd=str(cwd),
            check=True,
            capture_output=True,
        )

    def make_repo_with_worktree(self) -> tuple:
        main = self.parent / "repo"
        main.mkdir()
        self._git("init", cwd=main)
        make_project(main)
        self._git("add", ".project/STATE.md", cwd=main)
        self._git("commit", "-m", "init", cwd=main)
        linked = self.parent / "repo-linked"
        self._git("worktree", "add", str(linked), cwd=main)
        return main, linked

    def test_linked_worktree_deduped_to_main_checkout(self) -> None:
        main, linked = self.make_repo_with_worktree()
        self.assertTrue((main / ".git").is_dir())
        self.assertTrue((linked / ".git").is_file())
        self.assertEqual(discovery.scan([str(self.parent)]), [str(main)])

    def test_unrelated_projects_not_deduped(self) -> None:
        main, _linked = self.make_repo_with_worktree()
        other = make_project(self.parent / "other")
        results = discovery.scan([str(self.parent)])
        self.assertEqual(results, [str(other), str(main)])

    def test_git_failure_treats_each_root_as_own_group(self) -> None:
        main, linked = self.make_repo_with_worktree()
        with mock.patch("subprocess.run", side_effect=OSError("git missing")):
            results = discovery.scan([str(self.parent)])
        self.assertEqual(results, [str(main), str(linked)])


if __name__ == "__main__":
    unittest.main()
