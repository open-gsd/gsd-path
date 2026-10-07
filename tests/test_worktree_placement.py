import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import integration, isolation, install
from tests import test_isolation


class WorktreePlacementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.managed = self.root / "managed"
        environment = mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(self.managed)})
        environment.start()
        self.addCleanup(environment.stop)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.base = test_isolation.IsolationTests().init_bound_repo(self.repo)

    def test_managed_lifecycle_keeps_primary_and_pins_location(self):
        serial = isolation.isolate_task(self.repo, self.base, "T001", 1)
        self.assertEqual(serial["worktree"], str(self.repo))
        task = isolation.isolate_task(self.repo, self.base, "T001", 2)
        path = Path(task["worktree"])
        self.assertTrue(path.is_relative_to(self.managed), path)
        self.assertEqual(test_isolation.git(path, "branch", "--show-current"), task["task_branch"])
        with mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(self.root / "changed")}):
            self.assertEqual(isolation.sidecar_root(self.repo, "task", "T001"), path)
            verify = isolation.isolate_verify(self.repo, self.base, "review")
            sidecar = Path(verify["worktree"])
            self.assertEqual(sidecar.parent.parent, path.parent.parent)
            (sidecar / "generated.txt").write_bytes("review output".encode("utf-8"))
            isolation.clean_verify(self.repo, sidecar, self.base, verify["branch"])
            self.assertFalse((sidecar / "generated.txt").exists())
            isolation.retire(self.repo, sidecar, verify["branch"], False)
            isolation.retire(self.repo, path, task["task_branch"], False)
        self.assertFalse(path.exists())
        self.assertTrue(self.repo.is_dir())

    def test_default_root_inside_unrelated_home_repository(self):
        test_isolation.git(self.root, "init", "-b", "dotfiles")
        with mock.patch.object(Path, "home", return_value=self.root), mock.patch.dict(
            os.environ, {"GSD_PATH_WORKTREE_ROOT": ""}
        ):
            verify = isolation.isolate_verify(self.repo, self.base, "review")
            task = isolation.isolate_task(self.repo, self.base, "T001", 2)
            _, integration_path = integration.integration_names(self.repo, "001-demo")
            verify_path = Path(verify["worktree"])
            self.assertTrue(verify_path.is_relative_to(self.root / ".gsd-path/projects"))
            for path in (Path(task["worktree"]), integration_path):
                self.assertEqual(path.parent.parent, verify_path.parent.parent)
            self.assertEqual(test_isolation.git(verify_path, "rev-parse", "HEAD"), self.base)
            isolation.retire(self.repo, verify_path, verify["branch"], False)
            isolation.retire(self.repo, Path(task["worktree"]), task["task_branch"], False)
        self.assertEqual(test_isolation.git(self.repo, "rev-parse", "HEAD"), self.base)

    def test_release_workspace_lets_a_new_root_apply_after_retirement(self):
        task = isolation.isolate_task(self.repo, self.base, "T001", 2)
        path = Path(task["worktree"])
        kept = isolation.isolate_task(self.repo, self.base, "T002", 2)
        isolation.retire(self.repo, path, task["task_branch"], False)

        # A remaining sidecar keeps the pin.
        moved = self.root / "moved"
        with mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(moved)}):
            self.assertEqual(
                isolation.sidecar_root(self.repo, "task", "T003"),
                Path(kept["worktree"]).parent / "T003",
            )
        isolation.retire(self.repo, Path(kept["worktree"]), kept["task_branch"], False)

        # Once the last sidecar retires, the new root applies again.
        with mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(moved)}):
            fresh = isolation.isolate_task(self.repo, self.base, "T003", 2)
        self.assertTrue(Path(fresh["worktree"]).is_relative_to(moved), fresh["worktree"])

    def test_rejects_managed_root_in_own_primary_or_linked_checkout(self):
        linked = self.root / "linked"
        test_isolation.git(self.repo, "worktree", "add", "-b", "other", str(linked), self.base)
        for checkout in (self.repo, linked):
            root = checkout / "nested/managed"
            with self.subTest(root=root), mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(root)}):
                with self.assertRaises(isolation.IsolationError) as raised:
                    isolation.isolate_verify(self.repo, self.base, "review")
                self.assertIn(str(root), str(raised.exception))
                self.assertFalse(root.exists())
                self.assertFalse((self.repo / ".git/gsd-path/workspaces").exists())

    def test_legacy_cleanup_survives_new_managed_allocations(self):
        legacy = self.repo.parent / f"{self.repo.name}.gsd-path" / "verify" / "old"
        with mock.patch.object(isolation, "sidecar_root", return_value=legacy):
            old = isolation.isolate_verify(self.repo, self.base, "old")
        new = isolation.isolate_verify(self.repo, self.base, "new")
        self.assertTrue(Path(new["worktree"]).is_relative_to(self.managed))
        self.assertEqual(isolation.sidecar_root(self.repo, "verify", "old"), legacy)
        isolation.clean_verify(self.repo, legacy, self.base, old["branch"])
        isolation.retire(self.repo, legacy, old["branch"], False)
        self.assertFalse(legacy.exists())

    def test_invalid_receipt_never_reselects_workspace(self):
        isolation.isolate_verify(self.repo, self.base, "review")
        receipt, = (self.repo / ".git/gsd-path/workspaces").glob("*.json")
        receipt.write_bytes("null".encode("utf-8"))
        with mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(self.root / "changed")}):
            with self.assertRaisesRegex(isolation.IsolationError, "invalid worktree placement receipt"):
                isolation.isolate_verify(self.repo, self.base, "another")

    def test_same_named_repositories_have_distinct_managed_locations(self):
        other = self.root / "elsewhere" / "repo"
        other.mkdir(parents=True)
        base = test_isolation.IsolationTests().init_bound_repo(other)
        first = isolation.isolate_verify(self.repo, self.base, "review")
        second = isolation.isolate_verify(other, base, "review")
        paths = [Path(item["worktree"]) for item in (first, second)]
        self.assertTrue(all(path.is_relative_to(self.managed) for path in paths))
        self.assertNotEqual(*paths)

    def test_integration_uses_same_workspace_and_keeps_legacy_registration(self):
        verify = isolation.isolate_verify(self.repo, self.base, "review")
        branch, path = integration.integration_names(self.repo, "001-demo")
        self.assertTrue(path.is_relative_to(self.managed), path)
        self.assertEqual(path.parent.parent, Path(verify["worktree"]).parent.parent)
        legacy = self.repo.parent / f".{self.repo.name}-gsd-path-integrate-M001"
        test_isolation.git(self.repo, "worktree", "add", "-b", branch, str(legacy), self.base)
        self.assertEqual(integration.integration_names(self.repo, "001-demo")[1], legacy)
        integration.remove_registered_worktree(self.repo, branch, legacy)
        self.assertFalse(legacy.exists())

    def test_runtime_package_creates_managed_sidecars(self):
        source = Path(__file__).resolve().parents[1]
        manifest = json.loads((source / "scripts/skill-resources.json").read_text(encoding="utf-8"))
        runtime = self.root / "runtime"
        runtime.mkdir()
        for name in install.PROJECT_RUNTIME_SCRIPTS:
            if f"scripts/{name}" in manifest["package_files"]:
                shutil.copy2(source / "scripts" / name, runtime / name)
        result = subprocess.run(
            [sys.executable, "-B", str(runtime / "isolation.py"), "isolate-verify",
             "--repo", str(self.repo), "--base", self.base, "--name", "runtime"],
            cwd=runtime, encoding="utf-8", errors="replace", capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        worktree = Path(json.loads(result.stdout)["worktree"])
        self.assertTrue(worktree.is_relative_to(self.managed))
        self.assertEqual(test_isolation.git(worktree, "rev-parse", "HEAD"), self.base)


if __name__ == "__main__":
    unittest.main()
