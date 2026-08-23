import errno
import json
import os
import stat
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
ANCHORED_READ_AVAILABLE = (
    hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
)
DESCRIPTOR_TRAVERSAL_AVAILABLE = (
    ANCHORED_READ_AVAILABLE and os.listdir in getattr(os, "supports_fd", ())
)
ANCHORED_STATE_CREATE_AVAILABLE = (
    DESCRIPTOR_TRAVERSAL_AVAILABLE
    and os.mkdir in getattr(os, "supports_dir_fd", ())
    and os.unlink in getattr(os, "supports_dir_fd", ())
)


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

    def test_title_readme_with_three_space_comment_is_greenfield(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "README.md").write_text(
                "# Demo\n   <!-- scaffold -->\n",
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
            "Demo\n<!-- scaffold\nnote -->\n====\n",
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

    def test_indented_html_comments_are_markdown_body(self) -> None:
        for contents in ("    <!-- code -->\n", "\t<!-- code -->\n"):
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

    def test_name_surrogate_project_directory_is_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                "---\npipeline: gsd-path/v2\n---\n",
                encoding="utf-8",
            )
            real_lstat = detect_project.os.lstat
            project_evidence = project.resolve()
            project_status = real_lstat(project_evidence)
            name_surrogate = mock.Mock(
                st_mode=project_status.st_mode,
                st_reparse_tag=0xA0000003,
            )

            def junction_lstat(path):
                if Path(path) == project_evidence:
                    return name_surrogate
                return real_lstat(path)

            with mock.patch.object(
                detect_project.os,
                "lstat",
                side_effect=junction_lstat,
            ):
                payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "orphan")
            self.assertEqual(payload["orphan_paths"], [".project"])

    def test_lstat_fallback_rejects_name_surrogate_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            readme = repo / "README.md"
            readme.write_text(
                "# External\n\nExisting project.\n",
                encoding="utf-8",
            )
            real_stat = detect_project.os.stat
            readme_evidence = readme.resolve()
            readme_status = real_stat(readme_evidence)
            name_surrogate = mock.Mock(
                st_mode=readme_status.st_mode,
                st_reparse_tag=0xA000000C,
            )

            def reparse_stat(path, *, dir_fd=None, follow_symlinks=True):
                if dir_fd is None and Path(path) == readme_evidence:
                    return name_surrogate
                return real_stat(
                    path,
                    dir_fd=dir_fd,
                    follow_symlinks=follow_symlinks,
                )

            with mock.patch.object(
                detect_project,
                "ANCHORED_EVIDENCE_SUPPORTED",
                False,
            ):
                with mock.patch.object(
                    detect_project.os,
                    "stat",
                    side_effect=reparse_stat,
                ):
                    with self.assertRaisesRegex(
                        detect_project.DetectError,
                        "link-like Markdown evidence",
                    ):
                        self.classify(repo)

    def test_lstat_fallback_classifies_regular_owned_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            state = repo / ".project" / "STATE.md"
            state.parent.mkdir()
            state.write_text(
                "---\npipeline: gsd-path/v2\n---\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                detect_project,
                "ANCHORED_EVIDENCE_SUPPORTED",
                False,
            ):
                payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "owned")
            self.assertEqual(payload["pipeline"], "gsd-path/v2")

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
                with mock.patch.object(
                    detect_project,
                    "ANCHORED_EVIDENCE_SUPPORTED",
                    False,
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
                with mock.patch.object(
                    detect_project,
                    "ANCHORED_EVIDENCE_SUPPORTED",
                    False,
                ):
                    with self.assertRaisesRegex(
                        detect_project.DetectError,
                        "cannot inspect filesystem evidence",
                    ):
                        self.classify(repo)

    @unittest.skipUnless(
        DESCRIPTOR_TRAVERSAL_AVAILABLE,
        "descriptor-anchored traversal is unavailable",
    )
    def test_worktree_uses_descriptor_listing_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "main.py").write_text("print(1)\n", encoding="utf-8")
            with mock.patch.object(
                detect_project.os,
                "walk",
                side_effect=AssertionError("path traversal used"),
            ):
                payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "brownfield")
            self.assertEqual(
                payload["signals"],
                [{"kind": "source", "path": "main.py"}],
            )

    @unittest.skipUnless(
        DESCRIPTOR_TRAVERSAL_AVAILABLE,
        "descriptor-anchored traversal is unavailable",
    )
    def test_anchored_traversal_open_failures_are_detect_errors(self) -> None:
        for target in ("root", "child"):
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as temporary:
                    repo = Path(temporary)
                    repo_evidence = repo.resolve()
                    child = repo / "src"
                    if target == "child":
                        child.mkdir()
                        (child / "main.py").write_text(
                            "print(1)\n",
                            encoding="utf-8",
                        )
                    real_open = detect_project.os.open

                    def failing_open(path, flags, mode=0o777, *, dir_fd=None):
                        root_open = dir_fd is None and Path(path) == repo_evidence
                        child_open = dir_fd is not None and path == "src"
                        if (target == "root" and root_open) or (
                            target == "child" and child_open
                        ):
                            raise PermissionError(13, "denied", str(path))
                        return real_open(path, flags, mode, dir_fd=dir_fd)

                    with mock.patch.object(
                        detect_project.os,
                        "open",
                        side_effect=failing_open,
                    ):
                        with self.assertRaisesRegex(
                            detect_project.DetectError,
                            "cannot traverse filesystem evidence",
                        ):
                            self.classify(repo)

    def test_git_rejects_unsafe_tracked_paths(self) -> None:
        oid = b"1" * 40
        for path in (b"../README.md", b"/README.md"):
            raw = b"100644 " + oid + b" 0\t" + path + b"\0"
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
                stdout=b"100644 " + (b"1" * 40) + b" 0\tD:/outside.md\0",
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
    def test_tracked_markdown_symlink_is_ignored(self) -> None:
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
            payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "greenfield")
            self.assertEqual(payload["signals"], [])

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
                "link-like Markdown evidence",
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

    def test_cli_help_distinguishes_classify_and_initialize(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        help_text = " ".join(result.stdout.split())
        self.assertIn("classify is read-only", help_text)
        self.assertIn("initialize creates .project/STATE.md", help_text)

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
        for contents in (
            "<!-- scaffold --># Demo\n",
            "# Demo <!-- scaffold -->\n",
        ):
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

    def test_deleted_markdown_reads_blob_by_staged_oid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / ".git").mkdir()
            oid = "1" * 40

            def git_result(command, **kwargs):
                del kwargs
                if command[3:] == ["ls-files", "--stage", "-z"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=f"100644 {oid} 0\tREADME.md\0".encode(),
                        stderr=b"",
                    )
                if command[3:] == ["cat-file", "blob", oid]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=b"# Demo\n\nExisting project.\n",
                        stderr=b"",
                    )
                raise AssertionError(command)

            with mock.patch.object(
                detect_project.subprocess,
                "run",
                side_effect=git_result,
            ):
                payload = self.classify(repo)
            self.assertEqual(payload["verdict"], "brownfield")
            self.assertEqual(
                payload["signals"],
                [{"kind": "git", "path": "README.md"}],
            )

    def test_deleted_nonregular_markdown_index_entries_are_ignored(self) -> None:
        for mode in ("120000", "160000"):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as temporary:
                    repo = Path(temporary)
                    (repo / ".git").mkdir()
                    oid = "1" * 40

                    def git_result(command, **kwargs):
                        del kwargs
                        if command[3:] != ["ls-files", "--stage", "-z"]:
                            raise AssertionError(command)
                        return subprocess.CompletedProcess(
                            command,
                            0,
                            stdout=f"{mode} {oid} 0\tREADME.md\0".encode(),
                            stderr=b"",
                        )

                    with mock.patch.object(
                        detect_project.subprocess,
                        "run",
                        side_effect=git_result,
                    ):
                        payload = self.classify(repo)
                    self.assertEqual(payload["verdict"], "greenfield")
                    self.assertEqual(payload["signals"], [])

    def test_unmerged_git_index_entry_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / ".git").mkdir()
            oid = "1" * 40
            result = subprocess.CompletedProcess(
                ["git", "ls-files"],
                0,
                stdout=(
                    f"100644 {oid} 1\tREADME.md\0"
                    f"100644 {oid} 2\tREADME.md\0"
                ).encode(),
                stderr=b"",
            )
            with mock.patch.object(
                detect_project.subprocess,
                "run",
                return_value=result,
            ):
                with self.assertRaisesRegex(
                    detect_project.DetectError,
                    "git index contains unmerged entry: README.md",
                ):
                    self.classify(repo)

    def test_missing_regular_index_blob_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / ".git").mkdir()
            oid = "1" * 40
            results = (
                subprocess.CompletedProcess(
                    ["git", "ls-files"],
                    0,
                    stdout=f"100644 {oid} 0\tREADME.md\0".encode(),
                    stderr=b"",
                ),
                subprocess.CompletedProcess(
                    ["git", "cat-file"],
                    128,
                    stdout=b"",
                    stderr=b"missing blob",
                ),
            )
            with mock.patch.object(
                detect_project.subprocess,
                "run",
                side_effect=results,
            ):
                with self.assertRaisesRegex(
                    detect_project.DetectError,
                    "cannot read staged Markdown evidence: README.md: missing blob",
                ):
                    self.classify(repo)

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

    @unittest.skipUnless(
        ANCHORED_STATE_CREATE_AVAILABLE,
        "anchored state creation is unavailable",
    )
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

    def test_initialize_fails_closed_without_anchored_create(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            template = (
                ROOT / "skills" / "gsd-path" / "templates" / "state.md"
            )
            with mock.patch.object(
                detect_project,
                "ANCHORED_STATE_CREATE_SUPPORTED",
                False,
            ):
                with self.assertRaisesRegex(
                    detect_project.DetectError,
                    "anchored no-follow STATE.md creation is unavailable",
                ):
                    detect_project.initialize(repo, template)
            self.assertFalse((repo / ".project").exists())

    @unittest.skipUnless(
        ANCHORED_STATE_CREATE_AVAILABLE,
        "anchored state creation is unavailable",
    )
    @unittest.skipIf(os.name == "nt", "symlink replacement requires POSIX")
    def test_initialize_rejects_symlinked_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            repo = workspace / "repo"
            target = workspace / "target"
            repo.mkdir()
            target.mkdir()
            (repo / "package.json").write_text("{}\n", encoding="utf-8")
            template = (
                ROOT / "skills" / "gsd-path" / "templates" / "state.md"
            )
            project = repo / ".project"
            real_mkdir = detect_project.os.mkdir

            def replacing_mkdir(path, mode=0o777, *, dir_fd=None):
                if path == ".project" and dir_fd is not None:
                    project.symlink_to(target, target_is_directory=True)
                    raise FileExistsError(".project appeared")
                return real_mkdir(path, mode, dir_fd=dir_fd)

            with mock.patch.object(
                detect_project.os,
                "mkdir",
                side_effect=replacing_mkdir,
            ):
                with self.assertRaisesRegex(
                    detect_project.DetectError,
                    ".project changed after classification",
                ):
                    detect_project.initialize(repo, template)
            self.assertFalse((target / "STATE.md").exists())

    @unittest.skipUnless(
        ANCHORED_STATE_CREATE_AVAILABLE,
        "anchored state creation is unavailable",
    )
    @unittest.skipIf(os.name == "nt", "directory replacement requires POSIX")
    def test_initialize_rolls_back_after_project_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            repo = workspace / "repo"
            project = repo / ".project"
            moved = workspace / "moved-project"
            external = workspace / "external"
            project.mkdir(parents=True)
            external.mkdir()
            (repo / "package.json").write_text("{}\n", encoding="utf-8")
            template = (
                ROOT / "skills" / "gsd-path" / "templates" / "state.md"
            )
            real_open = detect_project.os.open
            replaced = False

            def replacing_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal replaced
                creating_state = (
                    dir_fd is not None
                    and path == "STATE.md"
                    and bool(flags & os.O_CREAT)
                )
                if creating_state and not replaced:
                    project.rename(moved)
                    project.symlink_to(external, target_is_directory=True)
                    replaced = True
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(
                detect_project.os,
                "open",
                side_effect=replacing_open,
            ):
                with self.assertRaisesRegex(
                    detect_project.DetectError,
                    "project identity changed while creating STATE.md",
                ):
                    detect_project.initialize(repo, template)
            self.assertTrue(replaced)
            self.assertFalse((moved / "STATE.md").exists())
            self.assertFalse((external / "STATE.md").exists())

    @unittest.skipUnless(
        ANCHORED_STATE_CREATE_AVAILABLE,
        "anchored state creation is unavailable",
    )
    def test_initialize_rolls_back_after_project_contents_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            project = repo / ".project"
            project.mkdir()
            (repo / "package.json").write_text("{}\n", encoding="utf-8")
            template = (
                ROOT / "skills" / "gsd-path" / "templates" / "state.md"
            )
            real_open = detect_project.os.open
            changed = False

            def changing_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal changed
                creating_state = (
                    dir_fd is not None
                    and path == "STATE.md"
                    and bool(flags & os.O_CREAT)
                )
                if creating_state and not changed:
                    (project / "foreign.md").write_text(
                        "foreign\n",
                        encoding="utf-8",
                    )
                    changed = True
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(
                detect_project.os,
                "open",
                side_effect=changing_open,
            ):
                with self.assertRaisesRegex(
                    detect_project.DetectError,
                    ".project contents changed while creating STATE.md",
                ):
                    detect_project.initialize(repo, template)
            self.assertTrue(changed)
            self.assertTrue((project / "foreign.md").exists())
            self.assertFalse((project / "STATE.md").exists())

    @unittest.skipUnless(
        ANCHORED_STATE_CREATE_AVAILABLE,
        "anchored state creation is unavailable",
    )
    def test_initialize_retries_short_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            template = (
                ROOT / "skills" / "gsd-path" / "templates" / "state.md"
            )
            real_write = detect_project.os.write

            def short_write(descriptor, data):
                return real_write(descriptor, data[:7])

            with mock.patch.object(
                detect_project.os,
                "write",
                side_effect=short_write,
            ):
                payload = detect_project.initialize(repo, template)
            self.assertTrue(payload["wrote_state"])
            expected = detect_project.filled_state_template(
                template.read_text(encoding="utf-8"),
                detect_project.project_slug(repo.resolve()),
                "define",
            )
            actual = (repo / ".project" / "STATE.md").read_text(encoding="utf-8")
            self.assertEqual(actual, expected)

    @unittest.skipUnless(
        ANCHORED_STATE_CREATE_AVAILABLE,
        "anchored state creation is unavailable",
    )
    def test_initialize_removes_partial_state_after_write_failure(self) -> None:
        for failure in ("zero", "error"):
            with self.subTest(failure=failure):
                with tempfile.TemporaryDirectory() as temporary:
                    repo = Path(temporary)
                    template = (
                        ROOT
                        / "skills"
                        / "gsd-path"
                        / "templates"
                        / "state.md"
                    )
                    real_write = detect_project.os.write
                    calls = 0

                    def failing_write(descriptor, data):
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            return real_write(descriptor, data[:7])
                        if failure == "zero":
                            return 0
                        raise OSError("write failed")

                    with mock.patch.object(
                        detect_project.os,
                        "write",
                        side_effect=failing_write,
                    ):
                        with self.assertRaises(detect_project.DetectError):
                            detect_project.initialize(repo, template)
                    self.assertFalse((repo / ".project" / "STATE.md").exists())

    @unittest.skipUnless(
        ANCHORED_STATE_CREATE_AVAILABLE,
        "anchored state creation is unavailable",
    )
    def test_initialize_rolls_back_after_state_fstat_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            template = (
                ROOT / "skills" / "gsd-path" / "templates" / "state.md"
            )
            real_fstat = detect_project.os.fstat
            failed = False

            def failing_fstat(descriptor):
                nonlocal failed
                status = real_fstat(descriptor)
                if not failed and stat.S_ISREG(status.st_mode):
                    failed = True
                    raise OSError("fstat failed")
                return status

            with mock.patch.object(
                detect_project.os,
                "fstat",
                side_effect=failing_fstat,
            ):
                with self.assertRaisesRegex(
                    detect_project.DetectError,
                    "fstat failed",
                ):
                    detect_project.initialize(repo, template)
            self.assertTrue(failed)
            self.assertFalse((repo / ".project" / "STATE.md").exists())

    @unittest.skipUnless(
        ANCHORED_STATE_CREATE_AVAILABLE,
        "anchored state creation is unavailable",
    )
    def test_initialize_rolls_back_after_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            template = (
                ROOT / "skills" / "gsd-path" / "templates" / "state.md"
            )
            real_write = detect_project.os.write
            calls = 0

            def interrupted_write(descriptor, data):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return real_write(descriptor, data[:7])
                raise KeyboardInterrupt

            with mock.patch.object(
                detect_project.os,
                "write",
                side_effect=interrupted_write,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    detect_project.initialize(repo, template)
            self.assertEqual(calls, 2)
            self.assertFalse((repo / ".project" / "STATE.md").exists())

    @unittest.skipUnless(
        ANCHORED_STATE_CREATE_AVAILABLE,
        "anchored state creation is unavailable",
    )
    def test_initialize_rolls_back_after_state_close_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            template = (
                ROOT / "skills" / "gsd-path" / "templates" / "state.md"
            )
            real_close = detect_project.os.close
            real_fstat = detect_project.os.fstat
            real_open = detect_project.os.open
            failed = False
            closed_state_descriptor = None
            state_close_retried = False
            opened_descriptors = []

            def recording_open(path, flags, mode=0o777, *, dir_fd=None):
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                opened_descriptors.append(descriptor)
                return descriptor

            def failing_close(descriptor):
                nonlocal failed
                nonlocal closed_state_descriptor, state_close_retried
                if descriptor == closed_state_descriptor:
                    state_close_retried = True
                    raise AssertionError("state descriptor close retried")
                status = real_fstat(descriptor)
                if not failed and stat.S_ISREG(status.st_mode):
                    failed = True
                    closed_state_descriptor = descriptor
                    real_close(descriptor)
                    raise OSError("close failed")
                return real_close(descriptor)

            with mock.patch.object(
                detect_project.os,
                "open",
                side_effect=recording_open,
            ), mock.patch.object(
                detect_project.os,
                "close",
                side_effect=failing_close,
            ):
                with self.assertRaisesRegex(
                    detect_project.DetectError,
                    "close failed",
                ):
                    detect_project.initialize(repo, template)
            self.assertTrue(failed)
            self.assertFalse(state_close_retried)
            for descriptor in set(opened_descriptors):
                with self.subTest(descriptor=descriptor):
                    with self.assertRaises(OSError) as caught:
                        real_fstat(descriptor)
                    self.assertEqual(caught.exception.errno, errno.EBADF)
            self.assertFalse((repo / ".project" / "STATE.md").exists())


if __name__ == "__main__":
    unittest.main()
