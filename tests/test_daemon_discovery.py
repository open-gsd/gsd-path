import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
