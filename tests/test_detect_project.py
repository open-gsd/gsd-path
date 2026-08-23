import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import detect_project


SCRIPT = ROOT / "scripts" / "detect_project.py"


class DetectProjectTests(unittest.TestCase):
    def classify(self, repo: Path) -> dict:
        return detect_project.classify(repo)

    def command(self, repo: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "classify", "--repo", str(repo)],
            text=True,
            capture_output=True,
            check=False,
        )

    def git(self, repo: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    def test_empty_directory_is_greenfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "greenfield")
            self.assertEqual(payload["route"], "define")
            self.assertEqual(payload["signals"], [])

    def test_git_init_license_and_title_readme_are_greenfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.git(repo, "init", "-q", "-b", "main")
            (repo / "LICENSE").write_text("MIT\n", encoding="utf-8")
            (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
            (repo / ".gitignore").write_text("node_modules\n", encoding="utf-8")
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "greenfield")
            self.assertEqual(payload["signals"], [])

    def test_setext_title_readme_is_greenfield(self) -> None:
        examples = (
            "Demo\n====\n",
            "Demo project\ncontinued\n====\n",
        )
        for contents in examples:
            with self.subTest(contents=contents):
                with tempfile.TemporaryDirectory() as temporary:
                    repo = Path(temporary)
                    (repo / "README.md").write_text(contents, encoding="utf-8")
                    payload = self.classify(repo)
                    self.assertEqual(payload["verdict"], "greenfield")
                    self.assertEqual(payload["signals"], [])

    def test_title_readme_with_unclosed_comment_is_greenfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "README.md").write_text(
                "# Demo\n<!-- scaffold note\n",
                encoding="utf-8",
            )
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "greenfield")
            self.assertEqual(payload["signals"], [])

    def test_extensionless_readme_with_body_is_brownfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "README").write_text(
                "Demo\n====\n\nAn existing project.\n",
                encoding="utf-8",
            )
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "brownfield")
            self.assertEqual(
                payload["signals"],
                [{"kind": "docs", "path": "README"}],
            )

    def test_managed_pipeline_artifacts_are_greenfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.git(repo, "init", "-q", "-b", "main")
            managed_files = {
                "AGENTS.md": "# Agents\n\nInstructions.\n",
                "WORKFLOW.md": "# Workflow\n\nSteps.\n",
                ".claude/CLAUDE.md": "# Claude\n\nInstalled bridge.\n",
                ".cursor/agents/gsd-path.md": "# Agent\n\nInstalled agent.\n",
                ".gsd-path/guard_hook.py": "print('managed')\n",
                ".gsd-path/git_guard.py": "print('managed')\n",
                ".codex/skills/gsd-path-define/SKILL.md": "# Skill\n\nRules.\n",
                ".codex/skills/gsd-path-define/helper.py": "print('managed')\n",
                ".codex/disabled-gsd-skills/gsd-path-old/SKILL.md": (
                    "# Old\n\nRules.\n"
                ),
                ".claude/disabled-gsd-skills-1/gsd-path-old/helper.py": (
                    "print('old')\n"
                ),
                ".agent-tools/gsd-path-define/SKILL.md": "# Skill\n\nRules.\n",
                ".agent-tools/gsd-path-define/helper.py": "print('managed')\n",
                "agents/gsd-path.md": "# Agent\n\nInstalled agent.\n",
            }
            for relative, contents in managed_files.items():
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents, encoding="utf-8")
            self.git(repo, "add", ".")
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "greenfield")
            self.assertEqual(payload["signals"], [])

    def test_additional_readme_headings_are_body(self) -> None:
        examples = (
            "# Demo\n#existing-project\n",
            "# Demo\n## Existing project\n",
        )
        for contents in examples:
            with self.subTest(contents=contents):
                with tempfile.TemporaryDirectory() as temporary:
                    repo = Path(temporary)
                    (repo / "README.md").write_text(contents, encoding="utf-8")
                    payload = self.classify(repo)
                    self.assertEqual(payload["verdict"], "brownfield")
                    self.assertEqual(
                        payload["signals"],
                        [{"kind": "docs", "path": "README.md"}],
                    )

    def test_nonparagraph_setext_forms_are_body(self) -> None:
        examples = (
            "> Existing project\n====\n",
            "- Existing project\n---\n",
            "```python\n---\n",
            "Demo\n\n====\n",
            "Demo\n<!-- scaffold -->\n====\n",
            "Demo\n====\nOther\n====\n",
        )
        for contents in examples:
            with self.subTest(contents=contents):
                with tempfile.TemporaryDirectory() as temporary:
                    repo = Path(temporary)
                    (repo / "README.md").write_text(contents, encoding="utf-8")
                    payload = self.classify(repo)
                    self.assertEqual(payload["verdict"], "brownfield")
                    self.assertEqual(
                        payload["signals"],
                        [{"kind": "docs", "path": "README.md"}],
                    )

    def test_project_documents_with_body_are_brownfield(self) -> None:
        for name in ("CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md"):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temporary:
                    repo = Path(temporary)
                    (repo / name).write_text(
                        f"# {Path(name).stem}\n\nExisting project details.\n",
                        encoding="utf-8",
                    )
                    payload = self.classify(repo)
                    self.assertEqual(payload["verdict"], "brownfield")
                    self.assertEqual(
                        payload["signals"],
                        [{"kind": "docs", "path": name}],
                    )

    def test_license_documents_with_body_are_greenfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            for name in ("LICENSE.md", "LICENCE.markdown", "COPYING.mdx"):
                (repo / name).write_text(
                    "# License\n\nPermission is granted.\n",
                    encoding="utf-8",
                )
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "greenfield")
            self.assertEqual(payload["signals"], [])

    def test_package_manifest_is_brownfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "package.json").write_text("{}\n", encoding="utf-8")
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "brownfield")
            self.assertEqual(payload["route"], "inspect")
            self.assertEqual(
                payload["signals"],
                [{"kind": "manifest", "path": "package.json"}],
            )

    def test_source_file_is_brownfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "src").mkdir()
            (repo / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "brownfield")
            self.assertEqual(
                payload["signals"],
                [{"kind": "source", "path": "src/main.py"}],
            )

    def test_source_named_like_managed_skill_is_brownfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            source = repo / "skills" / "gsd-path-tool.py"
            source.parent.mkdir()
            source.write_text("print(1)\n", encoding="utf-8")
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "brownfield")
            self.assertEqual(
                payload["signals"],
                [{"kind": "source", "path": "skills/gsd-path-tool.py"}],
            )

    def test_readme_with_body_is_brownfield_docs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "README.md").write_text(
                "# Widget\n\nA widget that already exists.\n",
                encoding="utf-8",
            )
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "brownfield")
            self.assertEqual(
                payload["signals"],
                [{"kind": "docs", "path": "README.md"}],
            )

    def test_docs_architecture_is_brownfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "docs").mkdir()
            (repo / "docs" / "architecture.md").write_text(
                "# Architecture\n\nThe API lives in src/.\n",
                encoding="utf-8",
            )
            payload = self.classify(repo)
            self.assertEqual(
                payload["signals"],
                [{"kind": "docs", "path": "docs/architecture.md"}],
            )

    def test_node_modules_manifest_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            nested = repo / "node_modules" / "left-pad"
            nested.mkdir(parents=True)
            (nested / "package.json").write_text("{}\n", encoding="utf-8")
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "greenfield")

    def test_empty_project_dir_does_not_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / ".project").mkdir()
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "greenfield")

    def test_symlinked_project_directory_is_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            repo = workspace / "repo"
            target = workspace / "target"
            repo.mkdir()
            target.mkdir()
            (repo / ".project").symlink_to(target, target_is_directory=True)
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "orphan")
            self.assertEqual(payload["orphan_paths"], [".project"])

    def test_project_child_symlink_is_reported_lexically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            repo = workspace / "repo"
            target = workspace / "target"
            project = repo / ".project"
            project.mkdir(parents=True)
            target.mkdir()
            (project / "external").symlink_to(target, target_is_directory=True)
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "orphan")
            self.assertEqual(payload["orphan_paths"], [".project/external"])

    def test_symlinked_state_file_is_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            repo = workspace / "repo"
            project = repo / ".project"
            target = workspace / "STATE.md"
            project.mkdir(parents=True)
            target.write_text("---\npipeline: gsd-path/v2\n---\n")
            (project / "STATE.md").symlink_to(target)
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "orphan")
            self.assertEqual(payload["orphan_paths"], [".project/STATE.md"])

    def test_state_directory_is_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / ".project" / "STATE.md").mkdir(parents=True)
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "orphan")
            self.assertEqual(payload["orphan_paths"], [".project/STATE.md"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_state_fifo_is_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            state = repo / ".project" / "STATE.md"
            state.parent.mkdir()
            os.mkfifo(state)
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "orphan")
            self.assertEqual(payload["orphan_paths"], [".project/STATE.md"])

    @unittest.skipUnless(
        hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"),
        "nonblocking FIFO creation is unavailable",
    )
    def test_state_fifo_replacement_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            state = repo / ".project" / "STATE.md"
            state.parent.mkdir()
            state.write_text(
                "---\npipeline: gsd-path/v2\n---\n",
                encoding="utf-8",
            )
            state_evidence = state.resolve()
            real_open = detect_project.os.open
            replaced = False

            def replacing_open(path, flags, *, dir_fd=None):
                nonlocal replaced
                final_state = (
                    (dir_fd is None and Path(path) == state_evidence)
                    or (dir_fd is not None and path == state.name)
                )
                if final_state and not replaced:
                    if not flags & os.O_NONBLOCK:
                        raise AssertionError("state evidence open must be nonblocking")
                    state.unlink()
                    os.mkfifo(state)
                    replaced = True
                if dir_fd is None:
                    return real_open(path, flags)
                return real_open(path, flags, dir_fd=dir_fd)

            with mock.patch.object(
                detect_project.os,
                "open",
                side_effect=replacing_open,
            ):
                with self.assertRaisesRegex(
                    detect_project.DetectError,
                    "state evidence changed while reading",
                ):
                    self.classify(repo)

    def test_project_without_state_is_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / ".project" / "intent").mkdir(parents=True)
            (repo / ".project" / "intent" / "INTENT.md").write_text("# Intent\n")
            (repo / "src" / "main.py").parent.mkdir()
            (repo / "src" / "main.py").write_text("print(1)\n")
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "orphan")
            self.assertEqual(payload["route"], "recover-orphan")
            self.assertEqual(
                payload["orphan_paths"],
                [".project/intent/INTENT.md"],
            )
            self.assertEqual(payload["signals"], [])

    def test_state_file_is_owned_not_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                "---\npipeline: gsd-path/v2\nphase: define\n---\n",
                encoding="utf-8",
            )
            (repo / "package.json").write_text("{}\n", encoding="utf-8")
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "owned")
            self.assertEqual(payload["pipeline"], "gsd-path/v2")
            self.assertEqual(payload["route"], "existing-state")
            self.assertEqual(payload["signals"], [])

    def test_git_tracks_deleted_source_as_git_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.git(repo, "init", "-q", "-b", "main")
            self.git(repo, "config", "user.email", "dev@example.test")
            self.git(repo, "config", "user.name", "Dev")
            (repo / "app.py").write_text("print(1)\n", encoding="utf-8")
            self.git(repo, "add", "app.py")
            self.git(repo, "commit", "-q", "-m", "add app")
            (repo / "app.py").unlink()
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "brownfield")
            self.assertEqual(
                payload["signals"],
                [{"kind": "git", "path": "app.py"}],
            )

    def test_worktree_traversal_failure_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)

            def failing_walk(
                path,
                *,
                followlinks,
                onerror,
            ):
                del followlinks
                assert callable(onerror)
                onerror(PermissionError(13, "denied", str(Path(path) / "blocked")))
                return ()

            with mock.patch.object(
                detect_project.os,
                "walk",
                side_effect=failing_walk,
            ):
                with self.assertRaisesRegex(
                    detect_project.DetectError,
                    "cannot traverse filesystem evidence",
                ):
                    self.classify(repo)

    def test_worktree_stat_failure_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            source = repo / "main.py"
            source.write_text("print(1)\n", encoding="utf-8")
            source_evidence = source.resolve()
            real_lstat = detect_project.os.lstat

            def failing_lstat(path):
                if Path(path) == source_evidence:
                    raise PermissionError(13, "denied", str(path))
                return real_lstat(path)

            with mock.patch.object(
                detect_project.os,
                "lstat",
                side_effect=failing_lstat,
            ):
                with self.assertRaisesRegex(
                    detect_project.DetectError,
                    "cannot inspect filesystem evidence",
                ):
                    self.classify(repo)

    def test_git_rejects_unsafe_tracked_paths(self) -> None:
        for raw in (b"../README.md\0", b"/README.md\0"):
            with self.subTest(raw=raw):
                with tempfile.TemporaryDirectory() as temporary:
                    repo = Path(temporary)
                    (repo / ".git").mkdir()
                    result = subprocess.CompletedProcess(
                        ["git", "ls-files"],
                        0,
                        stdout=raw,
                        stderr=b"",
                    )
                    with mock.patch.object(
                        detect_project.subprocess,
                        "run",
                        return_value=result,
                    ):
                        with self.assertRaisesRegex(
                            detect_project.DetectError,
                            "git ls-files returned unsafe path",
                        ):
                            self.classify(repo)

    def test_git_rejects_windows_drive_tracked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / ".git").mkdir()
            result = subprocess.CompletedProcess(
                ["git", "ls-files"],
                0,
                stdout=b"D:/outside.md\0",
                stderr=b"",
            )
            with mock.patch.object(
                detect_project.subprocess,
                "run",
                return_value=result,
            ):
                with mock.patch.object(detect_project.os, "sep", "\\"):
                    with self.assertRaisesRegex(
                        detect_project.DetectError,
                        "git ls-files returned unsafe path",
                    ):
                        self.classify(repo)

    @unittest.skipIf(os.name == "nt", "POSIX filename semantics required")
    def test_git_preserves_literal_backslashes_in_tracked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            repo = workspace / "repo"
            repo.mkdir()
            self.git(repo, "init", "-q", "-b", "main")
            (workspace / "README.md").write_text(
                "# Outside\n\nExisting project.\n",
                encoding="utf-8",
            )
            tracked = repo / r"..\README.md"
            tracked.write_text("# Local\n", encoding="utf-8")
            self.git(repo, "add", "--", tracked.name)
            tracked.unlink()
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "greenfield")
            self.assertEqual(payload["signals"], [])

    @unittest.skipIf(os.name == "nt", "symlink creation requires POSIX")
    def test_tracked_markdown_symlink_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            repo = workspace / "repo"
            repo.mkdir()
            self.git(repo, "init", "-q", "-b", "main")
            external = workspace / "README.md"
            external.write_text(
                "# External\n\nExisting project.\n",
                encoding="utf-8",
            )
            (repo / "README.md").symlink_to(external)
            self.git(repo, "add", "README.md")
            with self.assertRaisesRegex(
                detect_project.DetectError,
                "symlinked Markdown evidence",
            ):
                self.classify(repo)

    @unittest.skipIf(os.name == "nt", "symlink creation requires POSIX")
    def test_tracked_markdown_below_symlinked_directory_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            repo = workspace / "repo"
            external = workspace / "external"
            tracked = repo / "docs" / "README.md"
            tracked.parent.mkdir(parents=True)
            external.mkdir()
            self.git(repo, "init", "-q", "-b", "main")
            tracked.write_text("# Local\n", encoding="utf-8")
            self.git(repo, "add", "docs/README.md")
            tracked.unlink()
            tracked.parent.rmdir()
            (external / "README.md").write_text(
                "# External\n\nExisting project.\n",
                encoding="utf-8",
            )
            (repo / "docs").symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(
                detect_project.DetectError,
                "symlinked Markdown evidence",
            ):
                self.classify(repo)

    @unittest.skipIf(os.name == "nt", "symlink creation requires POSIX")
    def test_markdown_symlink_replacement_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            repo = workspace / "repo"
            repo.mkdir()
            readme = repo / "README.md"
            external = workspace / "external.md"
            readme.write_text("# Local\n", encoding="utf-8")
            external.write_text(
                "# External\n\nExisting project.\n",
                encoding="utf-8",
            )
            readme_evidence = readme.resolve()
            real_open = detect_project.os.open
            replaced = False

            def replacing_open(path, flags, *, dir_fd=None):
                nonlocal replaced
                final_readme = (
                    (dir_fd is None and Path(path) == readme_evidence)
                    or (dir_fd is not None and path == readme.name)
                )
                if final_readme and not replaced:
                    readme.unlink()
                    readme.symlink_to(external)
                    replaced = True
                if dir_fd is None:
                    return real_open(path, flags)
                return real_open(path, flags, dir_fd=dir_fd)

            with mock.patch.object(
                detect_project.os,
                "open",
                side_effect=replacing_open,
            ):
                with self.assertRaisesRegex(
                    detect_project.DetectError,
                    "cannot read Markdown evidence",
                ):
                    self.classify(repo)

    @unittest.skipIf(os.name == "nt", "directory descriptor semantics required")
    def test_markdown_parent_replacement_stays_anchored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            repo = workspace / "repo"
            docs = repo / "docs"
            moved = workspace / "moved-docs"
            external = workspace / "external-docs"
            readme = docs / "README.md"
            docs.mkdir(parents=True)
            external.mkdir()
            readme.write_text("# Local\n", encoding="utf-8")
            (external / "README.md").write_text(
                "# External\n\nExisting project.\n",
                encoding="utf-8",
            )
            real_open = detect_project.os.open
            replaced = False

            def replacing_open(path, flags, *, dir_fd=None):
                nonlocal replaced
                final_readme = (
                    (dir_fd is None and Path(path) == readme)
                    or (dir_fd is not None and path == readme.name)
                )
                if final_readme and not replaced:
                    docs.rename(moved)
                    docs.symlink_to(external, target_is_directory=True)
                    replaced = True
                if dir_fd is None:
                    return real_open(path, flags)
                return real_open(path, flags, dir_fd=dir_fd)

            with mock.patch.object(
                detect_project.os,
                "open",
                side_effect=replacing_open,
            ):
                payload = self.classify(repo)
            self.assertTrue(replaced)
            self.assertEqual(payload["verdict"], "greenfield")
            self.assertEqual(payload["signals"], [])

    def test_cli_emits_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            result = self.command(repo)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["verdict"], "greenfield")
            self.assertEqual(payload["route"], "define")

    def test_unreadable_markdown_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "README.md").write_bytes(b"# Demo\n\n\xff\n")
            result = self.command(repo)
            self.assertEqual(result.returncode, 2)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "error")
            self.assertIn("cannot read Markdown evidence", payload["error"])

    def test_git_ls_files_failure_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / ".git").mkdir()
            result = self.command(repo)
            self.assertEqual(result.returncode, 2)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "error")
            self.assertIn("git ls-files failed", payload["error"])

    def test_missing_repo_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            result = self.command(missing)
            self.assertEqual(result.returncode, 2)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "error")

    def test_product_source_under_gsd_path_named_dir_is_brownfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            source = repo / "src" / "gsd-path-app" / "main.py"
            source.parent.mkdir(parents=True)
            source.write_text("print(1)\n", encoding="utf-8")
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "brownfield")
            self.assertEqual(
                payload["signals"],
                [{"kind": "source", "path": "src/gsd-path-app/main.py"}],
            )

    def test_comment_sharing_line_with_heading_is_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "README.md").write_text(
                "<!-- scaffold --># Demo\n",
                encoding="utf-8",
            )
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "brownfield")
            self.assertEqual(
                payload["signals"],
                [{"kind": "docs", "path": "README.md"}],
            )

    def test_deleted_tracked_readme_with_body_is_git_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self.git(repo, "init", "-q", "-b", "main")
            self.git(repo, "config", "user.email", "dev@example.test")
            self.git(repo, "config", "user.name", "Dev")
            (repo / "README.md").write_text(
                "# Widget\n\nAn existing project.\n",
                encoding="utf-8",
            )
            self.git(repo, "add", "README.md")
            self.git(repo, "commit", "-q", "-m", "docs")
            (repo / "README.md").unlink()
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "brownfield")
            self.assertEqual(
                payload["signals"],
                [{"kind": "git", "path": "README.md"}],
            )

    def test_git_index_override_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            repo = workspace / "repo"
            other = workspace / "other"
            repo.mkdir()
            other.mkdir()
            self.git(repo, "init", "-q", "-b", "main")
            self.git(other, "init", "-q", "-b", "main")
            (other / "app.py").write_text("print(1)\n", encoding="utf-8")
            self.git(other, "add", "app.py")
            env = os.environ.copy()
            env["GIT_DIR"] = str(other / ".git")
            env["GIT_WORK_TREE"] = str(other)
            with mock.patch.dict(os.environ, env, clear=False):
                payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "greenfield")
            self.assertEqual(payload["signals"], [])

    def test_initialize_writes_state_for_greenfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            template = (
                ROOT / "skills" / "gsd-path" / "templates" / "state.md"
            )
            payload = detect_project.initialize(repo, template)
            self.assertEqual(payload["verdict"], "greenfield")
            self.assertTrue(payload["wrote_state"])
            state = (repo / ".project" / "STATE.md").read_text(encoding="utf-8")
            self.assertIn("phase: define", state)
            self.assertIn("pipeline: gsd-path/v2", state)

    def test_initialize_rejects_symlinked_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            repo = workspace / "repo"
            target = workspace / "target"
            repo.mkdir()
            target.mkdir()
            (repo / "package.json").write_text("{}\n", encoding="utf-8")
            (repo / ".project").symlink_to(target, target_is_directory=True)
            payload = detect_project.classify(repo)
            self.assertEqual(payload["verdict"], "orphan")


if __name__ == "__main__":
    unittest.main()
