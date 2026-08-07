import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from scripts import bootstrap_repository


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = PROJECT_ROOT / "scripts" / "bootstrap_repository.py"
STATE_TEMPLATE = PROJECT_ROOT / "skills" / "gsd-path" / "templates" / "state.md"


class BootstrapRepositoryTests(unittest.TestCase):
    def run_command(self, *args: str, cwd: Path, env=None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def git(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_command("git", *args, cwd=repo)

    def write_fake_gh(self, root: Path) -> tuple[Path, Path]:
        binary = root / "bin"
        binary.mkdir()
        remotes = root / "remotes"
        remotes.mkdir()
        gh = binary / "gh"
        gh.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import os
                import subprocess
                import sys
                import tempfile
                from pathlib import Path

                root = Path(os.environ["FAKE_GH_ROOT"]).resolve()
                args = sys.argv[1:]

                if args[:2] == ["auth", "status"]:
                    raise SystemExit(0)

                if args[:2] == ["api", "--silent"]:
                    repository = args[2].removeprefix("repos/")
                    remote = root / f"{repository}.git"
                    if remote.is_dir():
                        raise SystemExit(0)
                    print("HTTP 404: Not Found", file=sys.stderr)
                    raise SystemExit(1)

                if args[:2] == ["repo", "create"]:
                    repository = args[2]
                    remote = root / f"{repository}.git"
                    remote.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryDirectory() as temporary:
                        seed = Path(temporary)
                        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=seed, check=True)
                        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=seed, check=True)
                        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=seed, check=True)
                        (seed / "README.md").write_text("# Demo\\n")
                        subprocess.run(["git", "add", "README.md"], cwd=seed, check=True)
                        subprocess.run(["git", "commit", "-q", "-m", "Initial commit"], cwd=seed, check=True)
                        subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(remote)], check=True)
                    raise SystemExit(0)

                if args[:2] == ["repo", "clone"]:
                    if os.environ.get("FAKE_GH_FAIL_CLONE") == "1":
                        print("injected clone failure", file=sys.stderr)
                        raise SystemExit(1)
                    repository, destination = args[2], args[3]
                    remote = root / f"{repository}.git"
                    raise SystemExit(subprocess.run(["git", "clone", "-q", str(remote), destination]).returncode)

                if args[:2] == ["repo", "view"]:
                    remote = Path(args[2]).resolve()
                    relative = remote.relative_to(root)
                    print(relative.as_posix().removesuffix(".git"))
                    raise SystemExit(0)

                print(f"unsupported fake gh command: {args}", file=sys.stderr)
                raise SystemExit(2)
                """
            ),
            encoding="utf-8",
        )
        gh.chmod(0o755)
        return binary, remotes

    def bootstrap_command(
        self,
        workspace: Path,
        checkout: Path,
        worktree: Path,
        repository_template: Path,
    ) -> tuple[str, ...]:
        return (
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            "create",
            "--workspace",
            str(workspace),
            "--owner",
            "acme",
            "--repo",
            "demo",
            "--visibility",
            "private",
            "--default-checkout",
            str(checkout),
            "--worktree",
            str(worktree),
            "--state-template",
            str(STATE_TEMPLATE),
            "--repository-template",
            str(repository_template),
        )

    def test_recovers_existing_remote_checkout_and_worktree_before_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workspace = root / "workspace"
            workspace.mkdir()
            binary, remotes = self.write_fake_gh(root)
            checkout = workspace / "demo"
            worktree = workspace / "demo-gsd-path"
            repository_template = root / "repository.md"
            repository_template.write_text(
                """# Repository Binding

Kind: <kind>
Remote: <remote>
Remote default: <remote-default>
Remote default SHA: <remote-default-sha>
Default checkout: <default-checkout>
GSD Path branch: <branch>
Primary worktree: <primary-worktree>
""",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PATH"] = f"{binary}{os.pathsep}{environment['PATH']}"
            environment["FAKE_GH_ROOT"] = str(remotes)
            environment["FAKE_GH_FAIL_CLONE"] = "1"
            command = self.bootstrap_command(
                workspace, checkout, worktree, repository_template
            )

            interrupted = self.run_command(*command, cwd=workspace, env=environment)

            self.assertNotEqual(interrupted.returncode, 0)
            journals = list((workspace / ".gsd-path-transactions").glob("*.json"))
            self.assertEqual(len(journals), 1)
            remote = remotes / "acme" / "demo.git"
            self.assertTrue(remote.is_dir())

            preview_command = list(command)
            preview_command[2] = "preview"
            recovery_preview = self.run_command(
                *preview_command, cwd=workspace, env=environment
            )
            self.assertEqual(recovery_preview.returncode, 0, recovery_preview.stderr)
            preview = json.loads(recovery_preview.stdout)
            self.assertEqual(preview["mode"], "resume")
            self.assertEqual(
                preview["stages"],
                {
                    "remote": True,
                    "default_checkout": False,
                    "worktree": False,
                    "pipeline": False,
                },
            )

            clone = self.run_command(
                "git", "clone", "-q", str(remote), str(checkout), cwd=workspace
            )
            self.assertEqual(clone.returncode, 0, clone.stderr)
            base = self.git(checkout, "rev-parse", "refs/remotes/origin/main").stdout.strip()
            add_worktree = self.git(
                checkout,
                "worktree",
                "add",
                "-q",
                "-b",
                "gsd-path/demo",
                str(worktree),
                base,
            )
            self.assertEqual(add_worktree.returncode, 0, add_worktree.stderr)
            environment.pop("FAKE_GH_FAIL_CLONE")

            resumed = self.run_command(*command, cwd=workspace, env=environment)

            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            result = json.loads(resumed.stdout)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["branch"], "gsd-path/demo")
            state = (worktree / ".project" / "STATE.md").read_text()
            binding = (worktree / ".project" / "REPOSITORY.md").read_text()
            self.assertIn("branch: gsd-path/demo", state)
            self.assertIn(f"Default checkout: {checkout.resolve()}", binding)
            self.assertIn(f"Primary worktree: {worktree.resolve()}", binding)
            self.assertFalse(journals[0].exists())
            self.assertEqual(self.git(checkout, "status", "--porcelain").stdout, "")
            self.assertEqual(
                self.git(worktree, "branch", "--show-current").stdout.strip(),
                "gsd-path/demo",
            )

            repeated = self.run_command(*command, cwd=workspace, env=environment)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)

            binding_path = worktree / ".project" / "REPOSITORY.md"
            binding_path.write_text(
                binding.replace(
                    f"Remote default SHA: {base}",
                    f"Remote default SHA: {'0' * 40}",
                )
            )
            mismatched = self.run_command(*command, cwd=workspace, env=environment)
            self.assertNotEqual(mismatched.returncode, 0)
            self.assertIn("binding", mismatched.stderr)

    def test_pipeline_artifacts_publish_as_one_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            worktree = root / "worktree"
            worktree.mkdir()
            request = bootstrap_repository.BootstrapRequest(
                workspace=str(root),
                owner="acme",
                repo="demo",
                visibility="private",
                default_checkout=str(root / "demo"),
                worktree=str(worktree),
                branch="gsd-path/demo",
                description=None,
            )
            repository_template = root / "repository.md"
            repository_template.write_text(
                "Kind: <kind>\nRemote: <remote>\nRemote default: <remote-default>\n"
                "Remote default SHA: <remote-default-sha>\n"
                "Default checkout: <default-checkout>\nGSD Path branch: <branch>\n"
                "Primary worktree: <primary-worktree>\n"
            )
            real_atomic_write = bootstrap_repository.atomic_write
            writes = 0

            def fail_second_write(path, content):
                nonlocal writes
                writes += 1
                if writes == 2:
                    raise OSError("injected publication failure")
                return real_atomic_write(path, content)

            with mock.patch.object(
                bootstrap_repository, "atomic_write", side_effect=fail_second_write
            ):
                with self.assertRaises(OSError):
                    bootstrap_repository.initialize_pipeline(
                        request,
                        "main",
                        "1" * 40,
                        STATE_TEMPLATE,
                        repository_template,
                    )

            self.assertFalse((worktree / ".project").exists())
            self.assertFalse((worktree / ".project.gsd-path-tmp").exists())


if __name__ == "__main__":
    unittest.main()
