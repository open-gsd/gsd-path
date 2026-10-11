"""Observable handoffs and resumable roadmap re-slice approvals."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import pipeline_state, state_checkpoint
from tests.test_pipeline_state import roadmap_text, run_git, state_text
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))
from gsd_daemon import probe
from gsd_daemon.model import ProjectStatus


class WorkflowArchitectureTests(unittest.TestCase):
    def test_status_has_no_eager_transaction_dependency(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            repo, head = self.repo(tmp)
            before = (repo / ".project/STATE.md").read_bytes()
            code = """
import importlib.abc
import sys

class NoTransactions(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.rsplit(".", 1)[-1] in {"state_checkpoint", "state_promote"}:
            raise ModuleNotFoundError("status loaded transaction implementation", name=fullname)

sys.meta_path.insert(0, NoTransactions())
from scripts import pipeline_state
raise SystemExit(pipeline_state.main(["status", "--repo", sys.argv[1]]))
"""
            result = subprocess.run([sys.executable, "-B", "-c", code, str(repo)],
                                    cwd=root, capture_output=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["state"]["phase"], "inspect")
            self.assertEqual(payload["route"]["action"], "run-phase")
            self.assertEqual((repo / ".project/STATE.md").read_bytes(), before)
            self.assertEqual(run_git(repo, "rev-parse", "HEAD").stdout.strip(), head)

    def test_every_state_bundle_routes_pending_reslice_journal(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "scripts/skill-resources.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as packaged:
            package = Path(packaged)
            for source, target in manifest["script_targets"]:
                destination = package / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / source, destination)
            bundles = [package / target for source, target in manifest["script_targets"]
                       if source == "scripts/pipeline_state.py"]
            for alias, source in manifest["router_aliases"].items():
                shutil.copytree(package / "skills" / source, package / "skills" / alias)
                bundles.append(package / "skills" / alias / "scripts/pipeline_state.py")
            repo, head = self.repo(tmp)
            baseline = repo / ".project/ROADMAP.before-reslice.md"
            baseline.write_bytes((repo / ".project/ROADMAP.md").read_bytes())
            with mock.patch.object(state_checkpoint, "isolation_checkpoint",
                                   side_effect=pipeline_state.IsolationError("interrupted")):
                with self.assertRaisesRegex(pipeline_state.PipelineStateError, "interrupted"):
                    self.approve(repo, head)
            for bundle in bundles:
                for action in ("status", "route"):
                    with self.subTest(bundle=bundle.parent.parent.name, action=action):
                        result = subprocess.run([sys.executable, "-B", str(bundle), action,
                            "--repo", str(repo)], cwd=repo, capture_output=True, encoding="utf-8", errors="replace",
                            env={**os.environ, "PYTHONPATH": ""})
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(json.loads(result.stdout)["route"]["action"], "resume-checkpoint")

    def repo(self, directory, phase="inspect", milestone="second"):
        repo = Path(directory).resolve()
        run_git(repo, "init", "-b", "gsd-path/M002")
        run_git(repo, "config", "user.name", "Test")
        run_git(repo, "config", "user.email", "test@example.com")
        project = repo / ".project"
        project.mkdir()
        (project / "STATE.md").write_bytes(state_text(
            phase=phase, status="active", milestone=milestone, branch="gsd-path/M002").encode("utf-8"))
        roadmap = roadmap_text().replace("Status: pending", "Status: active")
        if phase == "roadmap":
            roadmap = roadmap_text().replace("Status: shipped", "Status: abandoned").replace("Depends on: [M001]", "Depends on: []")
        (project / "ROADMAP.md").write_bytes(roadmap.encode("utf-8"))
        run_git(repo, "add", ".project")
        run_git(repo, "commit", "-m", "fixture")
        return repo, run_git(repo, "rev-parse", "HEAD").stdout.strip()

    def test_status_explains_route_and_caller_without_advancing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, head = self.repo(tmp)
            path = repo / ".project/STATE.md"
            path.write_bytes(path.read_text(encoding="utf-8").replace("status: active", "status: done").encode("utf-8"))
            before = path.read_bytes()
            payload = json.loads(subprocess.run([sys.executable, "-B", str(Path(pipeline_state.__file__)),
                "status", "--repo", str(repo)], check=True, capture_output=True, encoding="utf-8", errors="replace").stdout)
            handoff = payload.get("handoff", {})
            self.assertEqual(handoff.get("outcome"), "inspect/done")
            self.assertEqual(handoff.get("review"), str(path))
            self.assertEqual(handoff.get("next"), "Invoke $gsd-path to continue with define.")
            self.assertEqual(handoff.get("router_next"), "Continue with define; honor its input and approval gates.")
            self.assertEqual(handoff.get("phase_next"), handoff.get("next"))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(run_git(repo, "rev-parse", "HEAD").stdout.strip(), head)

    def test_blocked_handoff_uses_route_reason_not_a_continue_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = self.repo(tmp, "ship")
            path = repo / ".project/STATE.md"
            path.write_bytes(path.read_text(encoding="utf-8").replace("status: active", "status: blocked").encode("utf-8"))
            payload = pipeline_state.status_state(repo)
            handoff = payload.get("handoff", {})
            expected = "block: " + payload["route"]["reason"]
            self.assertEqual(handoff.get("next"), expected)
            self.assertEqual(handoff.get("router_next"), expected)
            self.assertEqual(handoff.get("phase_next"), expected)

    def test_daemon_carries_real_runtime_handoff_through_serialization(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = self.repo(tmp)
            shutil.copytree(Path(pipeline_state.__file__).parent, repo / ".gsd-path/runtime")
            expected = pipeline_state.status_state(repo)["handoff"]
            status = probe.probe_project(repo)
            self.assertEqual(status.status_source, "runtime")
            self.assertEqual(status.to_dict().get("handoff"), expected)
            restored = ProjectStatus.from_dict(status.to_dict())
            self.assertEqual(restored.to_dict().get("handoff"), expected)

    def approve(self, repo, head):
        return state_checkpoint.checkpoint_approval(repo, "roadmap-reslice", head, selected_milestone="second")

    def test_reslice_preserves_active_phase_or_selects_post_abandon_and_commits_once(self):
        for phase in ("inspect", "define", "roadmap"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                repo, head = self.repo(tmp, phase, "null" if phase == "roadmap" else "second")
                baseline = repo / ".project/ROADMAP.before-reslice.md"
                baseline.write_bytes((repo / ".project/ROADMAP.md").read_bytes())
                completed = subprocess.run([sys.executable, "-B", str(Path(pipeline_state.__file__)),
                    "approve", "--repo", str(repo), "--kind", "roadmap-reslice",
                    "--milestone", "second", "--expected-head", head],
                    capture_output=True, encoding="utf-8", errors="replace", check=True)
                result = json.loads(completed.stdout)
                self.assertEqual(result["state"]["phase"], "inspect" if phase == "roadmap" else phase)
                self.assertEqual(result["state"]["status"], "active")
                self.assertEqual(result["state"]["milestone"], "second")
                self.assertFalse(baseline.exists())
                self.assertIn("Status: active", (repo / ".project/ROADMAP.md").read_text(encoding="utf-8"))
                self.assertEqual(run_git(repo, "rev-list", "--count", head + "..HEAD").stdout.strip(), "1")
                self.assertEqual(run_git(repo, "status", "--porcelain").stdout, "")

    def test_reslice_resumes_after_checkpoint_failure_and_after_commit(self):
        for point in ("isolation_checkpoint", "_unlink_checkpoint_journal"):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as tmp:
                repo, head = self.repo(tmp)
                baseline = repo / ".project/ROADMAP.before-reslice.md"
                content = (repo / ".project/ROADMAP.md").read_text(encoding="utf-8")
                baseline.write_bytes(content.encode("utf-8"))
                error = pipeline_state.IsolationError if point == "isolation_checkpoint" else pipeline_state.PipelineStateError
                with mock.patch.object(state_checkpoint, point, side_effect=error("interrupted")):
                    with self.assertRaisesRegex(pipeline_state.PipelineStateError, "interrupted"):
                        self.approve(repo, head)
                self.assertEqual(pipeline_state.route_state(repo)["route"]["action"], "resume-checkpoint")
                if point == "isolation_checkpoint":
                    self.assertEqual(baseline.read_text(encoding="utf-8"), content)
                result = state_checkpoint.resume_checkpoint(repo)
                self.assertEqual(result["state"]["phase"], "inspect")
                self.assertFalse(baseline.exists())
                self.assertEqual(run_git(repo, "rev-list", "--count", head + "..HEAD").stdout.strip(), "1")

    def test_reslice_rejects_active_entry_changes_without_losing_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, head = self.repo(tmp)
            roadmap = repo / ".project/ROADMAP.md"
            baseline = repo / ".project/ROADMAP.before-reslice.md"
            baseline.write_bytes(roadmap.read_bytes())
            roadmap.write_bytes(roadmap.read_text(encoding="utf-8").replace("Goal: second", "Goal: different").encode("utf-8"))
            with self.assertRaisesRegex(pipeline_state.PipelineStateError, "active.*changed"):
                self.approve(repo, head)
            self.assertTrue(baseline.exists())
            self.assertEqual(run_git(repo, "rev-parse", "HEAD").stdout.strip(), head)

    def test_define_reslice_may_amend_active_entry_but_keeps_it_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, head = self.repo(tmp, "define")
            roadmap = repo / ".project/ROADMAP.md"
            baseline = repo / ".project/ROADMAP.before-reslice.md"
            baseline.write_bytes(roadmap.read_bytes())
            narrowed = roadmap.read_text(encoding="utf-8").replace("Goal: second", "Goal: narrowed")
            changed = "active roadmap entry changed: second"
            tail = "Archive: null\nIntegrated: null"  # only the active entry ends like this
            third = "\n\n### M003 — third\n\nGoal: third\nDepends on: [M002]\nStatus: active\n" + tail
            for label, old, new, refusal in (
                ("dependencies", "Depends on: [M001]", "Depends on: []", changed),
                ("status", "Status: active", "Status: pending", changed),
                ("id", "### M002 — second", "### M003 — second", changed),
                ("slug", "### M002 — second", "### M002 — other", "exactly one entry for second"),
                ("archive", "Archive: null", "Archive: .project/archive/002-second/", changed),
                ("integrated", tail, "Archive: null\nIntegrated: " + head, changed),
                ("second active", tail, tail + third, "must retain the active entry"),
            ):
                with self.subTest(fixed=label):
                    roadmap.write_bytes(narrowed.replace(old, new).encode("utf-8"))
                    with self.assertRaisesRegex(pipeline_state.PipelineStateError, refusal):
                        self.approve(repo, head)
                    self.assertTrue(baseline.exists())
            roadmap.write_bytes(narrowed.encode("utf-8"))
            result = self.approve(repo, head)
            self.assertEqual((result["state"]["phase"], result["state"]["status"]), ("define", "active"))
            self.assertEqual(result["state"]["milestone"], "second")
            approved = roadmap.read_text(encoding="utf-8")
            self.assertEqual(approved, narrowed)
            self.assertEqual(approved.count("Status: active"), 1)
            self.assertFalse(baseline.exists())
            self.assertEqual(run_git(repo, "rev-list", "--count", head + "..HEAD").stdout.strip(), "1")
            self.assertEqual(run_git(repo, "show", "HEAD:.project/ROADMAP.md").stdout, narrowed)

    def test_define_reslice_with_amended_active_entry_resumes_after_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, head = self.repo(tmp, "define")
            roadmap = repo / ".project/ROADMAP.md"
            baseline = repo / ".project/ROADMAP.before-reslice.md"
            baseline.write_bytes(roadmap.read_bytes())
            narrowed = roadmap.read_text(encoding="utf-8").replace("Goal: second", "Goal: narrowed")
            roadmap.write_bytes(narrowed.encode("utf-8"))
            with mock.patch.object(state_checkpoint, "isolation_checkpoint",
                                   side_effect=pipeline_state.IsolationError("interrupted")):
                with self.assertRaisesRegex(pipeline_state.PipelineStateError, "interrupted"):
                    self.approve(repo, head)
            self.assertEqual(pipeline_state.route_state(repo)["route"]["action"], "resume-checkpoint")
            result = state_checkpoint.resume_checkpoint(repo)
            self.assertEqual((result["state"]["phase"], result["state"]["status"]), ("define", "active"))
            self.assertFalse(baseline.exists())
            self.assertEqual(run_git(repo, "show", "HEAD:.project/ROADMAP.md").stdout, narrowed)

    def test_define_reslice_refuses_active_entry_amendment_after_intent_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = self.repo(tmp, "plan")
            project = repo / ".project"
            for name in ("intent/INTENT.md", "plan/PLAN.md"):
                (project / name).parent.mkdir()
                (project / name).write_bytes(b"# Approved\n")
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "approved intent and plan draft")
            head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            pipeline_state.transition_state(
                repo,
                {"phase": "plan", "status": "active", "branch": "gsd-path/M002", "archive": None},
                {"phase": "define", "status": "active"},
                "plan intent corrections requested",
            )
            self.assertEqual(pipeline_state.route_state(repo)["route"].get("mode"), "corrections")
            roadmap = project / "ROADMAP.md"
            baseline = project / "ROADMAP.before-reslice.md"
            baseline.write_bytes(roadmap.read_bytes())
            roadmap.write_bytes(roadmap.read_text(encoding="utf-8").replace("Goal: second", "Goal: narrowed").encode("utf-8"))
            with self.assertRaisesRegex(pipeline_state.PipelineStateError, "active roadmap entry changed: second"):
                self.approve(repo, head)
            self.assertTrue(baseline.exists())
            self.assertEqual(run_git(repo, "rev-parse", "HEAD").stdout.strip(), head)

    def test_deferred_reslice_uses_same_selection_and_cleanup_without_committing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, head = self.repo(tmp, "roadmap", "null")
            project = repo / ".project"
            (project / "REPOSITORY.md").write_bytes("Kind: new-github\n".encode("utf-8"))
            baseline = project / "ROADMAP.before-reslice.md"
            baseline.write_bytes((project / "ROADMAP.md").read_bytes())
            result = state_checkpoint.defer_approval(repo, "roadmap-reslice", selected_milestone="second")
            self.assertTrue(result["deferred"])
            self.assertFalse(baseline.exists())
            self.assertIn("Status: active", (project / "ROADMAP.md").read_text(encoding="utf-8"))
            self.assertEqual(result["state"]["phase"], "inspect")
            self.assertEqual(run_git(repo, "rev-parse", "HEAD").stdout.strip(), head)
