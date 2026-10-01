#!/usr/bin/env python3
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import _common

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReviewedHeadCoversTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("git", "-C", str(repo), *args),
            capture_output=True,
            text=True,
            check=False,
        )

    def init_repo(self, repo: Path) -> None:
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.email", "test@example.com")
        self.git(repo, "config", "user.name", "Test")
        (repo / ".gsd-path").mkdir(parents=True)
        (repo / ".gsd-path" / "runtime.json").write_text('{"digest":"base"}\n', encoding="utf-8")
        (repo / "product.txt").write_text("product\n", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-q", "-m", "initial")

    def reviewed_head(self, repo: Path) -> str:
        return self.git(repo, "rev-parse", "HEAD").stdout.strip()

    def pin_runtime(self, repo: Path, digest: str) -> None:
        (repo / ".gsd-path" / "runtime.json").write_text(
            f'{{"digest":"{digest}"}}\n', encoding="utf-8"
        )
        self.git(repo, "add", ".gsd-path/runtime.json")
        self.git(repo, "commit", "-q", "-m", f"pin {digest}")

    def covers(self, repo: Path, reviewed: str, head: str = "HEAD") -> bool:
        head_sha = self.git(repo, "rev-parse", head).stdout.strip()
        return _common.reviewed_head_covers(repo, reviewed, head_sha)

    def test_equal_shas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            reviewed = self.reviewed_head(repo)
            self.assertTrue(self.covers(repo, reviewed))

    def test_single_runtime_pin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            reviewed = self.reviewed_head(repo)
            self.pin_runtime(repo, "one")
            self.assertTrue(self.covers(repo, reviewed))

    def test_two_consecutive_runtime_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            reviewed = self.reviewed_head(repo)
            self.pin_runtime(repo, "one")
            self.pin_runtime(repo, "two")
            self.assertTrue(self.covers(repo, reviewed))

    def test_empty_commit_after_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            reviewed = self.reviewed_head(repo)
            self.git(repo, "commit", "-q", "--allow-empty", "-m", "empty")
            self.assertFalse(self.covers(repo, reviewed))

    def test_empty_commit_between_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            reviewed = self.reviewed_head(repo)
            self.pin_runtime(repo, "one")
            self.git(repo, "commit", "-q", "--allow-empty", "-m", "empty")
            self.pin_runtime(repo, "two")
            self.assertFalse(self.covers(repo, reviewed))

    def test_pin_with_extra_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            reviewed = self.reviewed_head(repo)
            (repo / ".gsd-path" / "runtime.json").write_text('{"digest":"x"}\n', encoding="utf-8")
            (repo / "product.txt").write_text("changed\n", encoding="utf-8")
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-q", "-m", "pin and product")
            self.assertFalse(self.covers(repo, reviewed))

    def test_non_pin_path_between_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            reviewed = self.reviewed_head(repo)
            self.pin_runtime(repo, "one")
            (repo / "product.txt").write_text("changed\n", encoding="utf-8")
            self.git(repo, "add", "product.txt")
            self.git(repo, "commit", "-q", "-m", "product")
            self.pin_runtime(repo, "two")
            self.assertFalse(self.covers(repo, reviewed))

    def test_nested_runtime_json_is_not_pin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            reviewed = self.reviewed_head(repo)
            nested = repo / "sub" / ".gsd-path"
            nested.mkdir(parents=True)
            (nested / "runtime.json").write_text('{"digest":"nested"}\n', encoding="utf-8")
            self.git(repo, "add", "sub")
            self.git(repo, "commit", "-q", "-m", "nested pin")
            self.assertFalse(self.covers(repo, reviewed))

    def test_non_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            reviewed = self.reviewed_head(repo)
            self.git(repo, "checkout", "-q", "-b", "side")
            (repo / "side.txt").write_text("side\n", encoding="utf-8")
            self.git(repo, "add", "side.txt")
            self.git(repo, "commit", "-q", "-m", "side")
            other = self.reviewed_head(repo)
            self.git(repo, "checkout", "-q", "main")
            self.assertFalse(self.covers(repo, other, reviewed))

    def test_reviewed_after_head(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            reviewed = self.reviewed_head(repo)
            self.pin_runtime(repo, "one")
            self.assertFalse(self.covers(repo, self.reviewed_head(repo), reviewed))

    def test_merge_commit_on_first_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            reviewed = self.reviewed_head(repo)
            self.git(repo, "checkout", "-q", "-b", "side")
            (repo / "side.txt").write_text("side\n", encoding="utf-8")
            self.git(repo, "add", "side.txt")
            self.git(repo, "commit", "-q", "-m", "side")
            self.git(repo, "checkout", "-q", "main")
            self.git(repo, "merge", "-q", "--no-ff", "side", "-m", "merge side")
            self.assertFalse(self.covers(repo, reviewed))

    def test_unresolvable_shas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.init_repo(repo)
            reviewed = self.reviewed_head(repo)
            self.assertFalse(_common.reviewed_head_covers(repo, "", reviewed))
            self.assertFalse(_common.reviewed_head_covers(repo, reviewed, ""))
            self.assertFalse(_common.reviewed_head_covers(repo, "not-a-commit", reviewed))


if __name__ == "__main__":
    unittest.main()
