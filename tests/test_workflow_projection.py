"""Status proof and presentation through real Git, runtime and daemon callers."""
import json
import contextlib
import io
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from tests import test_archive_milestone as archive_tests
from scripts import install, integration, pipeline_state
from tests.test_pipeline_state import run_git, state_text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'daemon'))
from gsd_daemon import probe
from gsd_daemon.model import ProjectStatus


class WorkflowProjectionTests(unittest.TestCase):
    def runtime(self, repo):
        runtime = repo / '.gsd-path' / 'runtime'
        runtime.mkdir(parents=True)
        for name in install.PROJECT_RUNTIME_SCRIPTS:
            shutil.copy2(ROOT / 'scripts' / name, runtime / name)

    def status(self, repo):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/pipeline_state.py'),
                                 'status', '--repo', str(repo)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_runtime_completion_requires_published_proof_without_fetching(self):
        fixture = archive_tests.ArchiveMilestoneTests()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'primary'
            repo.mkdir()
            remote = Path(tmp) / 'origin.git'
            fixture.make_publishable_bound_repo(repo, remote)
            archive, _ = fixture.ship_canonical_bound(repo)
            self.assertEqual(self.status(repo).get('completion', {}).get('status'), 'unverified')
            integrated = fixture.integrate(repo)
            self.assertEqual(integrated.returncode, 0, integrated.stderr)
            refs = run_git(repo, 'show-ref').stdout
            head = run_git(repo, 'rev-parse', 'HEAD').stdout
            state = (repo / '.project/STATE.md').read_bytes()
            self.assertEqual(self.status(repo)['completion']['status'], 'verified')
            self.assertEqual(run_git(repo, 'show-ref').stdout, refs)
            self.assertEqual(run_git(repo, 'rev-parse', 'HEAD').stdout, head)
            self.assertEqual((repo / '.project/STATE.md').read_bytes(), state)
            # A removed published tag must invalidate proof despite cached local refs.
            deleted = fixture.git(repo, 'push', 'origin', '--delete', 'milestone/' + archive)
            self.assertEqual(deleted.returncode, 0, deleted.stderr)
            before = run_git(repo, 'show-ref').stdout
            self.assertEqual(self.status(repo)['completion']['status'], 'unverified')
            self.assertEqual(run_git(repo, 'show-ref').stdout, before)

    def test_missing_github_cli_preserves_unverified_status_and_handoff(self):
        fixture = archive_tests.ArchiveMilestoneTests()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "primary"
            repo.mkdir()
            fixture.make_publishable_bound_repo(repo, root / "origin.git")
            fixture.enable_pull_request_integration(repo)
            archive, ship = fixture.ship_canonical_bound(repo)
            pushed = fixture.git(repo, "push", "-q", "origin", "gsd-path/M001")
            self.assertEqual(pushed.returncode, 0, pushed.stderr)
            merge = fixture.integrate_bound(repo, archive, ship, tag=False,
                subject="Merge pull request #7 from open-gsd/gsd-path/M001")
            pushed = fixture.git(repo, "push", "-q", "origin", f"{merge}:refs/heads/main")
            self.assertEqual(pushed.returncode, 0, pushed.stderr)
            pull = fixture.merged_pull_request(ship, merge)
            with mock.patch.object(integration, "github_repository", return_value="open-gsd/demo"), \
                 mock.patch.object(integration, "run_command", side_effect=fixture.github_api([pull])):
                integration.integrate(repo, "demo")
            refs = run_git(repo, "show-ref").stdout
            before = (repo / ".project/STATE.md").read_bytes()
            missing_gh = root / "missing-gh"
            # Exercise the real subprocess OSError at the external CLI boundary.
            def unavailable_gh(*arguments):
                self.assertEqual(arguments[0], "gh")
                return subprocess.run([str(missing_gh), *arguments[1:]], check=False)
            output = io.StringIO()
            with mock.patch.object(integration, "run_command", side_effect=unavailable_gh), \
                 contextlib.redirect_stdout(output):
                exit_code = pipeline_state.main(["status", "--repo", str(repo)])
            self.assertEqual(exit_code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["completion"]["status"], "unverified")
            self.assertIn(str(missing_gh), payload["completion"]["reason"])
            self.assertEqual(payload["state"]["phase"], "shipped")
            self.assertEqual(payload["route"]["action"], "run-phase")
            self.assertEqual(payload["route"]["phase"], "ship")
            self.assertEqual(payload["route"]["mode"], "validate-integrated")
            self.assertEqual(payload["next_skill"], "gsd-path-ship")
            self.assertEqual(payload["handoff"]["next"], "Invoke $gsd-path to continue with ship.")
            self.assertEqual(payload["pending_answers"], [])
            self.assertEqual(probe.workflow_projection(payload)["label"], "Unverified")
            self.assertEqual(run_git(repo, "show-ref").stdout, refs)
            self.assertEqual((repo / ".project/STATE.md").read_bytes(), before)

    def test_projection_uses_runtime_state_and_labels_unavailable_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, 'init', '-b', 'gsd-path/M001')
            project = repo / '.project'
            project.mkdir()
            (project / 'STATE.md').write_text(state_text(phase='build', status='active'))
            self.runtime(repo)
            result = probe.probe_project(repo)
            self.assertEqual(result.to_dict().get('workflow', {}).get('label'), 'In build')
            self.assertEqual(ProjectStatus.from_dict(result.to_dict()).to_dict()['workflow'], result.workflow)
            # Invalid owned state still leaves parsed facts visible, explicitly unverified.
            (project / 'STATE.md').write_text(state_text(phase='build', status='active').replace(
                'pipeline: gsd-path/v2', 'pipeline: other/v1'))
            result = probe.probe_project(repo)
            self.assertEqual(result.phase, 'build')
            self.assertEqual(result.to_dict()['workflow']['label'], 'Unverified')
            self.assertEqual(result.health, 'amber')

    def test_archive_without_runtime_is_never_shipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project = repo / '.project'
            project.mkdir()
            (project / 'STATE.md').write_text(state_text(phase='ship', status='active',
                archive='.project/archive/001-first'))
            status = probe.probe_project(repo)
            self.assertEqual(status.to_dict().get('workflow', {}).get('label'), 'Unverified')
            self.assertEqual(status.phase, 'ship')
            self.assertEqual(status.health, 'amber')
