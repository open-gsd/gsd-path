import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "README.md").write_text("Demo\n====\n", encoding="utf-8")
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
            (repo / "AGENTS.md").write_text("# Agents\n\nInstructions.\n")
            (repo / "WORKFLOW.md").write_text("# Workflow\n\nSteps.\n")
            bundle = repo / ".codex" / "skills" / "gsd-path-define"
            bundle.mkdir(parents=True)
            (bundle / "SKILL.md").write_text("# Installed skill\n\nRules.\n")
            (bundle / "helper.py").write_text("print('managed')\n")
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


if __name__ == "__main__":
    unittest.main()
