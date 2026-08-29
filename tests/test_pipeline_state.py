import json
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import pipeline_git, pipeline_state


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def state_text(
    *,
    project: str = "demo",
    milestone: str = "second",
    phase: str = "plan",
    status: str = "done",
    branch: str = "null",
    archive: str = "null",
    integration_default=None,
    integration=None,
) -> str:
    integration_fields = ""
    if integration_default is not None:
        integration_fields += f"integration_default: {integration_default}\n"
    if integration is not None:
        integration_fields += f"integration: {integration}\n"
    return (
        "---\n"
        "pipeline: gsd-path/v2\n"
        f"project: {project}\n"
        f"milestone: {milestone}\n"
        f"phase: {phase}\n"
        f"status: {status}\n"
        f"branch: {branch}\n"
        f"archive: {archive}\n"
        f"{integration_fields}"
        "---\n\n"
        "# Project State\n\n"
        "## Log\n\n"
        "- 2026-08-23 — plan — fixture\n"
    )


def roadmap_text() -> str:
    return (
        "# Roadmap — demo\n\n"
        "## Milestones\n\n"
        "### M001 — first\n\n"
        "Goal: first\n"
        "Depends on: []\n"
        "Status: shipped\n"
        "Archive: .project/archive/001-first/\n"
        "Integrated: null\n\n"
        "Open questions\n"
        "- None\n\n"
        "### M002 — second\n\n"
        "Goal: second\n"
        "Depends on: [M001]\n"
        "Status: pending\n"
        "Archive: null\n"
        "Integrated: null\n\n"
        "Open questions\n"
        "- None\n"
    )


def task_text() -> str:
    return (
        "---\n"
        "id: T002\n"
        "title: Change app\n"
        "wave: 1\n"
        "deps: []\n"
        "status: pending\n"
        "agent: null\n"
        "commit: null\n"
        "base: null\n"
        "worktree: null\n"
        "task_branch: null\n"
        "files:\n"
        "  - app.py\n"
        "---\n\n"
        "# T002 — Change app\n"
    )


class PipelineStateTests(unittest.TestCase):
    def test_legacy_state_defaults_to_direct_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "main")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")

            state, _, _ = pipeline_state.load_state(repo)

            self.assertEqual(state.integration_default, "direct")
            self.assertEqual(state.integration, "direct")

    def test_state_accepts_explicit_pull_request_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "main")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(
                    integration_default="pull-request",
                    integration="pull-request",
                ),
                encoding="utf-8",
            )

            state, _, _ = pipeline_state.load_state(repo)

            self.assertEqual(state.integration_default, "pull-request")
            self.assertEqual(state.integration, "pull-request")

    def test_state_rejects_partial_integration_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "main")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(integration_default="pull-request"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "integration_default and integration must appear together",
            ):
                pipeline_state.load_state(repo)

    def test_configure_integration_updates_default_and_milestone_before_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "gsd-path/M001")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(
                    milestone="first",
                    phase="plan",
                    status="active",
                    branch="gsd-path/M001",
                ),
                encoding="utf-8",
            )

            configured = pipeline_state.configure_integration(
                repo, "default", "pull-request"
            )
            overridden = pipeline_state.configure_integration(
                repo, "milestone", "direct"
            )

            self.assertEqual(configured["state"]["integration_default"], "pull-request")
            self.assertEqual(configured["state"]["integration"], "pull-request")
            self.assertEqual(overridden["state"]["integration_default"], "pull-request")
            self.assertEqual(overridden["state"]["integration"], "direct")

    def test_configure_integration_rejects_build_or_later(self) -> None:
        positions = (("build", "active"), ("ship", "active"), ("shipped", "done"))
        for phase, status in positions:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                run_git(repo, "init", "-b", "gsd-path/M001")
                project = repo / ".project"
                project.mkdir()
                archive = (
                    ".project/archive/001-first/" if phase == "shipped" else "null"
                )
                (project / "STATE.md").write_text(
                    state_text(
                        milestone="first",
                        phase=phase,
                        status=status,
                        branch="gsd-path/M001",
                        archive=archive,
                    ),
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(
                    pipeline_state.PipelineStateError,
                    "integration mode is locked when build starts",
                ):
                    pipeline_state.configure_integration(
                        repo, "milestone", "pull-request"
                    )

    def test_transition_cannot_bypass_integration_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "gsd-path/M001")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(
                    milestone="first",
                    phase="plan",
                    status="active",
                    branch="gsd-path/M001",
                    integration_default="direct",
                    integration="direct",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "integration mode changes require configure-integration",
            ):
                pipeline_state.transition_state(
                    repo,
                    {
                        "phase": "plan",
                        "status": "active",
                        "branch": "gsd-path/M001",
                        "archive": None,
                        "integration": "direct",
                    },
                    {"integration": "pull-request"},
                    "bypass integration helper",
                )

    def test_validate_and_route_approved_unbound_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "main")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")

            validated = pipeline_state.validate_state(repo)
            routed = pipeline_state.route_state(repo)

            self.assertEqual(validated["status"], "valid")
            self.assertEqual(routed["route"]["action"], "bind-initial")
            self.assertEqual(routed["route"]["branch"], "gsd-path/M001")

    def test_status_reports_route_without_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "gsd-path/M001")
            run_git(repo, "config", "user.name", "GSD Path Test")
            run_git(repo, "config", "user.email", "test@example.com")
            project = repo / ".project"
            project.mkdir()
            (project / "intent").mkdir()
            (project / "STATE.md").write_text(
                state_text(
                    milestone="first",
                    phase="plan",
                    status="done",
                    branch="gsd-path/M001",
                ),
                encoding="utf-8",
            )
            (project / "intent" / "INTENT.md").write_text(
                "# Intent — first\n\nLane: quick\n",
                encoding="utf-8",
            )
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: plan done")
            before = (project / "STATE.md").read_text(encoding="utf-8")

            status = pipeline_state.status_state(repo)

            self.assertEqual(status["schema"], pipeline_state.STATUS_SCHEMA)
            self.assertFalse(status["advance"])
            self.assertEqual(status["route"]["action"], "run-phase")
            self.assertEqual(status["route"]["phase"], "build")
            self.assertEqual(status["next_skill"], "gsd-path-build")
            self.assertEqual((project / "STATE.md").read_text(encoding="utf-8"), before)
            self.assertEqual(status["pending_answers"], [])

    def test_status_marks_head_published_when_remote_branch_advanced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = root / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
            repo = root / "repo"
            run_git(root, "init", "-b", "gsd-path/M001", str(repo))
            run_git(repo, "config", "user.name", "GSD Path Test")
            run_git(repo, "config", "user.email", "test@example.com")
            project = repo / ".project"
            (project / "intent").mkdir(parents=True)
            (project / "STATE.md").write_text(
                state_text(milestone="first", branch="gsd-path/M001"),
                encoding="utf-8",
            )
            (project / "intent" / "INTENT.md").write_text(
                "# Intent — first\n\nLane: quick\n", encoding="utf-8"
            )
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: published ancestor")
            published = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            run_git(repo, "remote", "add", "origin", str(origin))
            run_git(repo, "push", "-u", "origin", "gsd-path/M001")
            (repo / "later.txt").write_text("later\n", encoding="utf-8")
            run_git(repo, "add", "later.txt")
            run_git(repo, "commit", "-m", "fixture: later remote tip")
            run_git(repo, "push", "origin", "gsd-path/M001")
            run_git(repo, "reset", "--hard", published)

            self.assertTrue(pipeline_state.status_state(repo)["git"]["published"])

    def test_status_ignores_completed_artifact_collection_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "gsd-path/M001")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(
                    milestone="first",
                    phase="build",
                    status="active",
                    branch="gsd-path/M001",
                ),
                encoding="utf-8",
            )
            run_git(repo, "add", ".project/STATE.md")
            run_git(
                repo,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-m",
                "fixture",
            )
            head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            common = Path(run_git(repo, "rev-parse", "--git-common-dir").stdout.strip())
            if not common.is_absolute():
                common = repo / common
            receipt = common / "gsd-path" / "collect-artifact" / "receipt.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(
                json.dumps(
                    {
                        "schema": "gsd-path/collect-artifact/v1",
                        "primary_worktree": str(repo.resolve()),
                        "source_worktree": str(repo.resolve()),
                        "base": head,
                        "branch": "gsd-path-verify/demo",
                        "source": "artifact.md",
                        "destination": ".project/review/artifact.md",
                        "expected_destination": None,
                        "bytes": 4,
                        "previous_sha256": None,
                        "replaced": False,
                        "sha256": "a" * 64,
                        "stage": "complete",
                    }
                ),
                encoding="utf-8",
            )

            self.assertIsNone(
                pipeline_state.status_state(repo)["journals"]["collect_artifact"]
            )

    def test_status_blocks_when_git_ancestry_probe_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = root / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
            repo = root / "repo"
            run_git(root, "init", "-b", "gsd-path/M001", str(repo))
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(
                    milestone="first",
                    phase="build",
                    status="active",
                    branch="gsd-path/M001",
                ),
                encoding="utf-8",
            )
            run_git(repo, "add", ".project/STATE.md")
            run_git(
                repo,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-m",
                "fixture",
            )
            run_git(repo, "remote", "add", "origin", str(origin))
            run_git(repo, "push", "-u", "origin", "gsd-path/M001")
            original = pipeline_state._run_git

            def fail_ancestry(path, *arguments, **kwargs):
                if arguments[:2] == ("merge-base", "--is-ancestor"):
                    return subprocess.CompletedProcess(arguments, 128, "", "bad object")
                return original(path, *arguments, **kwargs)

            with mock.patch.object(pipeline_state, "_run_git", side_effect=fail_ancestry):
                with self.assertRaisesRegex(
                    pipeline_state.PipelineStateError, "bad object"
                ):
                    pipeline_state.status_state(repo)

    def test_route_binds_initialized_state_before_phase_work(self) -> None:
        for phase in ("inspect", "define"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                run_git(repo, "init", "-b", "main")
                project = repo / ".project"
                project.mkdir()
                (project / "STATE.md").write_text(
                    state_text(phase=phase, status="active", milestone="null"),
                    encoding="utf-8",
                )

                routed = pipeline_state.route_state(repo)

                self.assertEqual(routed["route"]["action"], "bind-initial")
                self.assertEqual(routed["route"]["branch"], "gsd-path/M001")

    def test_validate_rejects_unowned_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project = repo / ".project"
            project.mkdir()
            text = state_text().replace("pipeline: gsd-path/v2", "pipeline: other/v1")
            (project / "STATE.md").write_text(text, encoding="utf-8")

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "pipeline must be gsd-path/v2",
            ):
                pipeline_state.validate_state(repo)

    def test_validate_rejects_m000_branch_and_archive(self) -> None:
        cases = (
            (
                state_text(branch="gsd-path/M000"),
                "invalid branch",
            ),
            (
                state_text(
                    milestone="first",
                    phase="shipped",
                    status="done",
                    branch="gsd-path/M001",
                    archive=".project/archive/000-first/",
                ),
                "invalid archive",
            ),
        )
        for content, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                project = repo / ".project"
                project.mkdir()
                (project / "STATE.md").write_text(content, encoding="utf-8")

                with self.assertRaisesRegex(pipeline_state.PipelineStateError, message):
                    pipeline_state.validate_state(repo)

    def test_route_rejects_m000_roadmap_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")
            (project / "ROADMAP.md").write_text(
                roadmap_text().replace("M002", "M000"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "invalid milestone id: M000",
            ):
                pipeline_state.route_state(repo)

    def test_route_rejects_duplicate_roadmap_slugs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "main")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")
            (project / "ROADMAP.md").write_text(
                roadmap_text().replace("### M002 — second", "### M002 — first"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "repeats milestone slug: first",
            ):
                pipeline_state.route_state(repo)

    def test_validate_enforces_lookahead_context(self) -> None:
        cases = (
            (
                state_text(branch="gsd-path/M002"),
                "lookahead branch and archive must be null",
            ),
            (
                state_text(phase="build", status="active"),
                "lookahead cannot enter build",
            ),
            (
                state_text(phase="roadmap", status="active"),
                "lookahead cannot enter roadmap",
            ),
        )
        for content, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                next_root = repo / ".project" / "next"
                next_root.mkdir(parents=True)
                (next_root / "STATE.md").write_text(content, encoding="utf-8")

                with self.assertRaisesRegex(
                    pipeline_state.PipelineStateError,
                    message,
                ):
                    pipeline_state.validate_state(repo, ".project/next")

    def test_validate_accepts_initial_lookahead_inspect_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            next_root = repo / ".project" / "next"
            next_root.mkdir(parents=True)
            (next_root / "STATE.md").write_text(
                state_text(phase="inspect", status="active"),
                encoding="utf-8",
            )

            result = pipeline_state.validate_state(repo, ".project/next")

            self.assertEqual(result["state"]["phase"], "inspect")

    def test_route_keeps_approved_lookahead_unbound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "main")
            next_root = repo / ".project" / "next"
            next_root.mkdir(parents=True)
            (next_root / "STATE.md").write_text(state_text(), encoding="utf-8")

            result = pipeline_state.route_state(repo, ".project/next")

            self.assertEqual(result["route"]["action"], "wait")
            self.assertEqual(result["route"]["mode"], "lookahead-ready")

    def test_route_derives_initial_branch_from_active_roadmap_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "main")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")
            roadmap = roadmap_text().replace(
                "### M002 — second\n\nGoal: second\nDepends on: [M001]\nStatus: pending",
                "### M002 — second\n\nGoal: second\nDepends on: [M001]\nStatus: active",
            )
            (project / "ROADMAP.md").write_text(roadmap, encoding="utf-8")

            result = pipeline_state.route_state(repo)

            self.assertEqual(result["route"]["action"], "bind-initial")
            self.assertEqual(result["route"]["branch"], "gsd-path/M002")

    def test_transition_compares_expected_state_before_atomic_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "main")
            project = repo / ".project"
            project.mkdir()
            state_path = project / "STATE.md"
            state_path.write_text(state_text(), encoding="utf-8")

            result = pipeline_state.transition_state(
                repo,
                {
                    "phase": "plan",
                    "status": "done",
                    "branch": None,
                    "archive": None,
                },
                {"branch": "gsd-path/M002"},
                "router bound initial milestone",
            )

            self.assertEqual(result["state"]["branch"], "gsd-path/M002")
            changed = state_path.read_text(encoding="utf-8")
            self.assertIn("router bound initial milestone", changed)
            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "expected state does not match",
            ):
                pipeline_state.transition_state(
                    repo,
                    {
                        "phase": "plan",
                        "status": "done",
                        "branch": None,
                        "archive": None,
                    },
                    {"status": "active"},
                    "must not write",
                )
            self.assertEqual(state_path.read_text(encoding="utf-8"), changed)

    def test_transition_rejects_gate_skips_and_wrong_edge_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project = repo / ".project"
            project.mkdir()
            state_path = project / "STATE.md"
            state_path.write_text(
                state_text(
                    phase="plan",
                    status="active",
                    branch="gsd-path/M001",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "illegal state transition",
            ):
                pipeline_state.transition_state(
                    repo,
                    {
                        "phase": "plan",
                        "status": "active",
                        "branch": "gsd-path/M001",
                        "archive": None,
                    },
                    {
                        "phase": "shipped",
                        "status": "done",
                        "archive": ".project/archive/001-second/",
                    },
                    "skip every gate",
                )

            state_path.write_text(
                state_text(
                    phase="plan",
                    status="done",
                    branch="gsd-path/M002",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "requires event: build started",
            ):
                pipeline_state.transition_state(
                    repo,
                    {
                        "phase": "plan",
                        "status": "done",
                        "branch": "gsd-path/M002",
                        "archive": None,
                    },
                    {"phase": "build", "status": "active"},
                    "start somehow",
                )

    def test_transition_cannot_enter_build_on_lookahead_track(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            next_root = repo / ".project" / "next"
            next_root.mkdir(parents=True)
            (next_root / "STATE.md").write_text(state_text(), encoding="utf-8")

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "lookahead cannot enter build",
            ):
                pipeline_state.transition_state(
                    repo,
                    {
                        "phase": "plan",
                        "status": "done",
                        "branch": None,
                        "archive": None,
                    },
                    {"phase": "build", "status": "active"},
                    "build started",
                    ".project/next",
                )

    def test_transition_allows_shipment_only_with_the_ship_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project = repo / ".project"
            project.mkdir()
            state_path = project / "STATE.md"
            state_path.write_text(
                state_text(
                    milestone="second",
                    phase="ship",
                    status="active",
                    branch="gsd-path/M002",
                    archive=".project/archive/002-second/",
                ),
                encoding="utf-8",
            )
            expected = {
                "phase": "ship",
                "status": "active",
                "branch": "gsd-path/M002",
                "archive": ".project/archive/002-second/",
            }
            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "archive preflight passed; shipment recorded",
            ):
                pipeline_state.transition_state(
                    repo,
                    expected,
                    {"phase": "shipped", "status": "done"},
                    "ship somehow",
                )

            result = pipeline_state.transition_state(
                repo,
                expected,
                {"phase": "shipped", "status": "done"},
                "archive preflight passed; shipment recorded",
            )

            self.assertEqual(
                (result["state"]["phase"], result["state"]["status"]),
                ("shipped", "done"),
            )

    def test_transition_rejects_build_phase_milestone_rename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(
                    milestone="first",
                    phase="build",
                    status="active",
                    branch="gsd-path/M001",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "illegal STATE.milestone transition",
            ):
                pipeline_state.transition_state(
                    repo,
                    {
                        "phase": "build",
                        "status": "active",
                        "milestone": "first",
                        "branch": "gsd-path/M001",
                        "archive": None,
                    },
                    {"milestone": "renamed"},
                    "rename active work",
                )

    def test_transition_allows_active_track_roadmap_reslice_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(
                    phase="define",
                    status="active",
                    branch="gsd-path/M001",
                ),
                encoding="utf-8",
            )

            result = pipeline_state.transition_state(
                repo,
                {
                    "phase": "define",
                    "status": "active",
                    "branch": "gsd-path/M001",
                    "archive": None,
                },
                {"phase": "roadmap", "status": "active"},
                "roadmap re-slice started",
            )
            self.assertEqual(result["state"]["phase"], "roadmap")

            next_root = project / "next"
            next_root.mkdir()
            (next_root / "STATE.md").write_text(
                state_text(phase="define", status="active"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "lookahead cannot enter roadmap|active track",
            ):
                pipeline_state.transition_state(
                    repo,
                    {
                        "phase": "define",
                        "status": "active",
                        "branch": None,
                        "archive": None,
                    },
                    {"phase": "roadmap", "status": "active"},
                    "roadmap re-slice started",
                    ".project/next",
                )

    def test_transition_binds_abandon_event_to_state_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project = repo / ".project"
            project.mkdir()
            state_path = project / "STATE.md"
            content = state_text(
                milestone="first",
                phase="build",
                status="active",
                branch="gsd-path/M001",
                archive=".project/archive/001-first/",
            )
            state_path.write_text(content, encoding="utf-8")
            expected = {
                "phase": "build",
                "status": "active",
                "milestone": "first",
                "branch": "gsd-path/M001",
                "archive": ".project/archive/001-first/",
            }
            changes = {
                "phase": "roadmap",
                "status": "active",
                "milestone": None,
                "archive": None,
            }
            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "abandon event",
            ):
                pipeline_state.transition_state(
                    repo,
                    expected,
                    changes,
                    "milestone abandoned: other; archive: elsewhere; ruling: stop",
                )

            result = pipeline_state.transition_state(
                repo,
                expected,
                changes,
                "milestone abandoned: first; archive: .project/archive/001-first/; "
                "ruling: stop this milestone",
            )
            self.assertEqual(
                (result["state"]["phase"], result["state"]["milestone"]),
                ("roadmap", None),
            )

    def test_transition_requires_a_higher_branch_after_shipment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(
                    milestone="second",
                    phase="shipped",
                    status="done",
                    branch="gsd-path/M002",
                    archive=".project/archive/002-second/",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "higher router-bound branch",
            ):
                pipeline_state.transition_state(
                    repo,
                    {
                        "phase": "shipped",
                        "status": "done",
                        "milestone": "second",
                        "branch": "gsd-path/M002",
                        "archive": ".project/archive/002-second/",
                    },
                    {
                        "phase": "define",
                        "status": "active",
                        "milestone": "third",
                        "branch": "gsd-path/M002",
                        "archive": None,
                    },
                    "next milestone bound",
                )

    def test_next_milestone_resets_integration_from_project_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project = repo / ".project"
            project.mkdir()
            archive = ".project/archive/001-first/"
            (project / "STATE.md").write_text(
                state_text(
                    milestone="first",
                    phase="shipped",
                    status="done",
                    branch="gsd-path/M001",
                    archive=archive,
                    integration_default="pull-request",
                    integration="direct",
                ),
                encoding="utf-8",
            )
            expected = {
                "phase": "shipped",
                "status": "done",
                "milestone": "first",
                "branch": "gsd-path/M001",
                "archive": archive,
                "integration": "direct",
            }
            changes = {
                "phase": "inspect",
                "status": "active",
                "milestone": "second",
                "branch": "gsd-path/M002",
                "archive": None,
                "integration": "pull-request",
            }

            result = pipeline_state.transition_state(
                repo,
                expected,
                changes,
                "next milestone bound",
            )

            self.assertEqual(result["state"]["integration_default"], "pull-request")
            self.assertEqual(result["state"]["integration"], "pull-request")

    def test_transition_requires_canonical_patch_reopen_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            project = repo / ".project"
            project.mkdir()
            state_path = project / "STATE.md"
            state_path.write_text(
                state_text(
                    milestone="first",
                    phase="plan",
                    status="done",
                    branch="gsd-path/M001",
                ),
                encoding="utf-8",
            )
            expected = {
                "phase": "plan",
                "status": "done",
                "branch": "gsd-path/M001",
                "archive": None,
            }
            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "illegal state transition",
            ):
                pipeline_state.transition_state(
                    repo,
                    expected,
                    {"status": "active"},
                    "reopen somehow",
                )

            result = pipeline_state.transition_state(
                repo,
                expected,
                {"status": "active"},
                "patch plan reopened",
            )
            self.assertEqual(result["state"]["status"], "active")

    def test_transition_state_rejects_direct_plan_and_roadmap_approval(self) -> None:
        cases = (
            (
                "plan",
                state_text(
                    milestone="first",
                    phase="plan",
                    status="active",
                    branch="gsd-path/M001",
                ),
                {
                    "phase": "plan",
                    "status": "active",
                    "branch": "gsd-path/M001",
                    "archive": None,
                },
                {"status": "done"},
                "plan approved",
            ),
            (
                "roadmap",
                state_text(
                    milestone="null",
                    phase="roadmap",
                    status="active",
                    branch="gsd-path/M001",
                ),
                {
                    "phase": "roadmap",
                    "status": "active",
                    "milestone": None,
                    "branch": "gsd-path/M001",
                    "archive": None,
                },
                {"status": "done", "milestone": "first"},
                "program roadmap approved",
            ),
        )
        for kind, content, expected, changes, event in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                project = repo / ".project"
                project.mkdir()
                state_path = project / "STATE.md"
                state_path.write_text(content, encoding="utf-8")

                with self.assertRaisesRegex(
                    pipeline_state.PipelineStateError,
                    rf"{kind} approval requires pipeline_state.py approve --kind {kind}",
                ):
                    pipeline_state.transition_state(
                        repo,
                        expected,
                        changes,
                        event,
                    )

                self.assertEqual(state_path.read_text(encoding="utf-8"), content)

    def test_transition_cli_rejects_direct_plan_and_roadmap_approval(self) -> None:
        cases = (
            ("plan", "first", "plan approved"),
            ("roadmap", "null", "program roadmap approved"),
        )
        for kind, milestone, event in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                project = repo / ".project"
                project.mkdir()
                content = state_text(
                    milestone=milestone,
                    phase=kind,
                    status="active",
                    branch="gsd-path/M001",
                )
                state_path = project / "STATE.md"
                state_path.write_text(content, encoding="utf-8")
                command = [
                    sys.executable,
                    str(Path(pipeline_state.__file__).resolve()),
                    "transition",
                    "--repo",
                    str(repo),
                    "--event",
                    event,
                    "--expect-phase",
                    kind,
                    "--expect-status",
                    "active",
                    "--expect-branch",
                    "gsd-path/M001",
                    "--expect-archive",
                    "null",
                    "--set-status",
                    "done",
                ]
                if kind == "roadmap":
                    command.extend(
                        [
                            "--expect-milestone",
                            "null",
                            "--set-milestone",
                            "first",
                        ]
                    )

                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 1)
                self.assertIn(
                    f"{kind} approval requires pipeline_state.py approve --kind {kind}",
                    result.stderr,
                )
                self.assertEqual(state_path.read_text(encoding="utf-8"), content)

    def _approval_repo(self, tmp: str, kind: str) -> tuple[Path, str]:
        repo = Path(tmp) / "repo"
        run_git(Path(tmp), "init", "-b", "gsd-path/M001", str(repo))
        run_git(repo, "config", "user.name", "GSD Path Test")
        run_git(repo, "config", "user.email", "test@example.com")
        project = repo / ".project"
        project.mkdir()
        phase = "plan" if kind == "plan" else "roadmap"
        milestone = "first" if kind == "plan" else "null"
        (project / "STATE.md").write_text(
            state_text(
                milestone=milestone,
                phase=phase,
                status="active",
                branch="gsd-path/M001",
            ),
            encoding="utf-8",
        )
        run_git(repo, "add", ".project/STATE.md")
        run_git(repo, "commit", "-m", "fixture: approval base")
        expected_head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
        if kind == "plan":
            (project / "plan").mkdir()
            (project / "plan" / "PLAN.md").write_text(
                "# Plan — first\n",
                encoding="utf-8",
            )
        else:
            (project / "ROADMAP.md").write_text(
                roadmap_text().replace("Status: shipped", "Status: pending", 1),
                encoding="utf-8",
            )
        return repo, expected_head

    def test_plan_approval_owns_state_change_and_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, expected_head = self._approval_repo(tmp, "plan")

            result = pipeline_state.checkpoint_approval(
                repo,
                "plan",
                expected_head,
            )

            self.assertEqual(result["status"], "approved")
            self.assertEqual(result["state"]["status"], "done")
            self.assertEqual(
                run_git(repo, "show", "-s", "--format=%s", "HEAD").stdout.strip(),
                "plan: build plan approved",
            )
            self.assertEqual(
                run_git(repo, "show", "-s", "--format=%b", "HEAD").stdout.strip(),
                "Why: approved plan checkpoint\nMilestone: first",
            )
            self.assertFalse(
                pipeline_state._git_path(
                    repo,
                    pipeline_state.CHECKPOINT_JOURNAL_NAME,
                ).exists()
            )

    def test_roadmap_approval_owns_selection_state_and_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, expected_head = self._approval_repo(tmp, "roadmap")

            result = pipeline_state.checkpoint_approval(
                repo,
                "roadmap",
                expected_head,
                selected_milestone="first",
            )

            self.assertEqual(
                (result["state"]["milestone"], result["state"]["status"]),
                ("first", "done"),
            )
            roadmap = (repo / ".project" / "ROADMAP.md").read_text(encoding="utf-8")
            self.assertIn(
                "### M001 — first\n\nGoal: first\nDepends on: []\nStatus: active",
                roadmap,
            )
            self.assertEqual(
                run_git(repo, "show", "-s", "--format=%s", "HEAD").stdout.strip(),
                "roadmap: program roadmap approved",
            )

    def test_route_and_resume_approval_after_state_write_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, expected_head = self._approval_repo(tmp, "plan")
            with mock.patch.object(
                pipeline_state,
                "isolation_checkpoint",
                side_effect=pipeline_state.IsolationError("simulated interruption"),
            ):
                with self.assertRaisesRegex(
                    pipeline_state.PipelineStateError,
                    "simulated interruption",
                ):
                    pipeline_state.checkpoint_approval(
                        repo,
                        "plan",
                        expected_head,
                    )

            state, _, _ = pipeline_state.load_state(repo)
            self.assertEqual((state.phase, state.status), ("plan", "done"))
            self.assertEqual(run_git(repo, "rev-parse", "HEAD").stdout.strip(), expected_head)
            routed = pipeline_state.route_state(repo)
            self.assertEqual(routed["route"]["action"], "resume-checkpoint")
            self.assertEqual(routed["route"]["kind"], "plan")

            result = pipeline_state.resume_checkpoint(repo)

            self.assertEqual(result["status"], "approved")
            self.assertNotEqual(result["commit"], expected_head)

    def test_resume_approval_rejects_artifact_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, expected_head = self._approval_repo(tmp, "plan")
            with mock.patch.object(
                pipeline_state,
                "isolation_checkpoint",
                side_effect=pipeline_state.IsolationError("simulated interruption"),
            ):
                with self.assertRaises(pipeline_state.PipelineStateError):
                    pipeline_state.checkpoint_approval(
                        repo,
                        "plan",
                        expected_head,
                    )
            (repo / ".project" / "plan" / "PLAN.md").write_text(
                "# Changed after approval preparation\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "approval artifacts drifted",
            ):
                pipeline_state.resume_checkpoint(repo)

    def test_resume_approval_after_commit_before_journal_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, expected_head = self._approval_repo(tmp, "roadmap")
            with mock.patch.object(
                pipeline_state,
                "_unlink_checkpoint_journal",
                side_effect=pipeline_state.PipelineStateError("simulated cleanup crash"),
            ):
                with self.assertRaisesRegex(
                    pipeline_state.PipelineStateError,
                    "simulated cleanup crash",
                ):
                    pipeline_state.checkpoint_approval(
                        repo,
                        "roadmap",
                        expected_head,
                        selected_milestone="first",
                    )
            committed = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            self.assertNotEqual(committed, expected_head)

            result = pipeline_state.resume_checkpoint(repo)

            self.assertEqual(result["commit"], committed)
            self.assertFalse(
                pipeline_state._git_path(
                    repo,
                    pipeline_state.CHECKPOINT_JOURNAL_NAME,
                ).exists()
            )

    def _promotion_repo(
        self,
        tmp: str,
        drift: bool,
        *,
        delete_declared: bool = False,
        mutate_plan: bool = False,
        mutate_task: bool = False,
        remove_task: bool = False,
        next_project: str = "demo",
        next_phase: str = "plan",
        next_status: str = "done",
        duplicate_approval: bool = False,
    ) -> tuple[Path, str]:
        repo = Path(tmp) / "repo"
        run_git(Path(tmp), "init", "-b", "main", str(repo))
        run_git(repo, "config", "user.name", "GSD Path Test")
        run_git(repo, "config", "user.email", "test@example.com")
        project = repo / ".project"
        (project / "next" / "tasks").mkdir(parents=True)
        (project / "next" / "plan").mkdir()
        (project / "next" / "review").mkdir()
        (repo / "app.py").write_text("approved = True\n", encoding="utf-8")
        run_git(repo, "add", "app.py")
        run_git(repo, "commit", "-m", "fixture: milestone base")
        run_git(repo, "switch", "-c", "gsd-path/M001")
        (project / "STATE.md").write_text(
            state_text(
                milestone="first",
                phase="build",
                status="active",
                branch="gsd-path/M001",
            ),
            encoding="utf-8",
        )
        (project / "ROADMAP.md").write_text(roadmap_text(), encoding="utf-8")
        (project / "next" / "STATE.md").write_text(
            state_text(
                project=next_project,
                phase=next_phase,
                status="active" if next_phase == "plan" and next_status == "done" else next_status,
            ),
            encoding="utf-8",
        )
        (project / "next" / "tasks" / "T002-change-app.md").write_text(
            task_text(),
            encoding="utf-8",
        )
        (project / "next" / "plan" / "PLAN.md").write_text(
            "# Plan — second\n",
            encoding="utf-8",
        )
        (project / "next" / "review" / "PLAN-PANEL.md").write_text(
            "# Plan review panel\n\nStatus: ready\n",
            encoding="utf-8",
        )
        if next_phase == "plan" and next_status == "done":
            approval_base = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            pipeline_state.checkpoint_approval(
                repo,
                "plan",
                approval_base,
                ".project/next",
            )
            if duplicate_approval:
                plan_path = project / "next" / "plan" / "PLAN.md"
                plan_path.write_text("# Plan — second revision\n", encoding="utf-8")
                task_path = project / "next" / "tasks" / "T002-change-app.md"
                task_path.write_text(
                    task_path.read_text(encoding="utf-8") + "\n## Revision\n\n- approved again\n",
                    encoding="utf-8",
                )
                next_state_path = project / "next" / "STATE.md"
                next_state_path.write_text(
                    next_state_path.read_text(encoding="utf-8")
                    + "- 2026-08-23 — plan — duplicate approval\n",
                    encoding="utf-8",
                )
                run_git(repo, "add", ".project/next")
                run_git(
                    repo,
                    "commit",
                    "-m",
                    "plan: build plan approved",
                    "-m",
                    "Why: approved plan checkpoint\nMilestone: second",
                )
        else:
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: lookahead phase")
        if drift:
            (repo / "app.py").write_text("approved = False\n", encoding="utf-8")
        if delete_declared:
            (repo / "app.py").unlink()
        if mutate_plan:
            (project / "next" / "plan" / "PLAN.md").write_text(
                "# Plan — changed after approval\n",
                encoding="utf-8",
            )
        task_path = project / "next" / "tasks" / "T002-change-app.md"
        if mutate_task:
            task_path.write_text(
                task_path.read_text(encoding="utf-8").replace(
                    "  - app.py\n",
                    "  - replacement.py\n",
                ),
                encoding="utf-8",
            )
        if remove_task:
            task_path.unlink()
        (project / "STATE.md").write_text(
            state_text(
                milestone="first",
                phase="shipped",
                status="done",
                branch="gsd-path/M001",
                archive=".project/archive/001-first/",
            ),
            encoding="utf-8",
        )
        run_git(repo, "add", "-A", "--", ".project", "app.py")
        run_git(
            repo,
            "commit",
            "-m",
            "ship: M001 — first",
        )
        run_git(repo, "switch", "main")
        run_git(
            repo,
            "merge",
            "--no-ff",
            "gsd-path/M001",
            "-m",
            "integrate: M001 — merge gsd-path/M001 into main",
        )
        integrate = run_git(repo, "rev-parse", "HEAD").stdout.strip()
        run_git(repo, "update-ref", "refs/remotes/origin/main", integrate)
        run_git(repo, "switch", "-c", "gsd-path/M002")
        return repo, integrate

    def test_promote_next_moves_track_commits_and_retries_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, integrate = self._promotion_repo(tmp, drift=False)

            unowned = pipeline_state.route_state(repo)
            self.assertEqual(unowned["route"]["action"], "block")

            journal_path = pipeline_git.bind_next_journal_path(repo, "gsd-path/M002")
            pipeline_git._write_bind_next_journal(
                journal_path,
                {
                    "schema": pipeline_git.BIND_NEXT_JOURNAL_SCHEMA,
                    "repo": str(repo.resolve()),
                    "branch": "gsd-path/M002",
                    "previous_branch": "gsd-path/M001",
                    "ship": integrate,
                    "remote_default": "origin/main",
                    "base": integrate,
                    "allow_remote_absent": True,
                    "stage": "switched",
                },
            )
            handoff = pipeline_state.route_state(repo)
            self.assertEqual(handoff["route"]["action"], "resume-next-handoff")
            self.assertEqual(handoff["route"]["previous_branch"], "gsd-path/M001")
            self.assertEqual(handoff["route"]["branch"], "gsd-path/M002")
            self.assertTrue(handoff["route"]["allow_remote_absent"])

            result = pipeline_state.promote_next(
                repo,
                "second",
                "gsd-path/M002",
                integrate,
            )

            self.assertEqual(result["status"], "promoted")
            self.assertEqual(result["drift"]["class"], "clean")
            self.assertFalse((repo / ".project" / "next").exists())
            self.assertTrue((repo / ".project" / "tasks" / "T002-change-app.md").is_file())
            self.assertTrue((repo / ".project" / "review" / "PLAN-PANEL.md").is_file())
            state, _, _ = pipeline_state.load_state(repo)
            self.assertEqual(
                (state.milestone, state.phase, state.status),
                ("second", "plan", "done"),
            )
            self.assertEqual(state.branch, "gsd-path/M002")
            self.assertIsNone(
                pipeline_state.status_state(repo)["journals"]["bind_next"]
            )
            roadmap = (repo / ".project" / "ROADMAP.md").read_text(encoding="utf-8")
            self.assertIn(f"Integrated: {integrate}", roadmap)
            self.assertEqual(
                run_git(repo, "show", "-s", "--format=%s", "HEAD").stdout.strip(),
                "router: promote lookahead milestone second",
            )

            retry = pipeline_state.promote_next(
                repo,
                "second",
                "gsd-path/M002",
                integrate,
            )
            self.assertEqual(retry["status"], "already-complete")
            self.assertEqual(retry["commit"], result["commit"])

    def test_promote_next_separates_landing_from_a_later_main_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, landing = self._promotion_repo(tmp, drift=False)
            run_git(repo, "switch", "main")
            (repo / "after-landing.txt").write_text("later\n", encoding="utf-8")
            run_git(repo, "add", "after-landing.txt")
            run_git(repo, "commit", "-m", "product: after milestone landing")
            base = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            run_git(repo, "update-ref", "refs/remotes/origin/main", base)
            run_git(repo, "branch", "-f", "gsd-path/M002", base)
            run_git(repo, "switch", "gsd-path/M002")

            result = pipeline_state.promote_next(
                repo,
                "second",
                "gsd-path/M002",
                base,
                landing,
            )

            self.assertEqual(result["base"], base)
            self.assertEqual(result["landing"], landing)
            self.assertEqual(
                run_git(repo, "show", "-s", "--format=%P", "HEAD").stdout.strip(),
                base,
            )
            roadmap = (repo / ".project" / "ROADMAP.md").read_text(encoding="utf-8")
            self.assertIn(f"Integrated: {landing}", roadmap)
            self.assertNotIn(f"Integrated: {base}", roadmap)

    def test_promote_next_reopens_plan_when_task_paths_drifted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, integrate = self._promotion_repo(tmp, drift=True)

            result = pipeline_state.promote_next(
                repo,
                "second",
                "gsd-path/M002",
                integrate,
            )

            self.assertEqual(result["drift"]["class"], "changed")
            self.assertEqual(result["drift"]["task_ids"], ["T002"])
            state, text, _ = pipeline_state.load_state(repo)
            self.assertEqual((state.phase, state.status), ("plan", "active"))
            self.assertIn("plan drift flagged tasks T002", text)

    def test_promote_next_detects_deleted_declared_path_as_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, integrate = self._promotion_repo(
                tmp,
                drift=False,
                delete_declared=True,
            )

            result = pipeline_state.promote_next(
                repo,
                "second",
                "gsd-path/M002",
                integrate,
            )

            self.assertEqual(result["drift"]["class"], "changed")
            self.assertEqual(result["drift"]["task_ids"], ["T002"])
            self.assertEqual(result["drift"]["changed_paths"], ["app.py"])

    def test_promote_next_reopens_when_plan_contract_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, integrate = self._promotion_repo(
                tmp,
                drift=False,
                mutate_plan=True,
            )

            result = pipeline_state.promote_next(
                repo,
                "second",
                "gsd-path/M002",
                integrate,
            )

            self.assertEqual(result["drift"]["class"], "changed")
            self.assertEqual(
                result["drift"]["contract_paths"],
                [".project/next/plan/PLAN.md"],
            )
            state, _, _ = pipeline_state.load_state(repo)
            self.assertEqual((state.phase, state.status), ("plan", "active"))

    def test_promote_next_reopens_when_task_declaration_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, integrate = self._promotion_repo(
                tmp,
                drift=False,
                mutate_task=True,
            )

            result = pipeline_state.promote_next(
                repo,
                "second",
                "gsd-path/M002",
                integrate,
            )

            self.assertEqual(result["drift"]["class"], "changed")
            self.assertEqual(result["drift"]["task_ids"], ["T002"])
            self.assertEqual(
                result["drift"]["contract_paths"],
                [".project/next/tasks/T002-change-app.md"],
            )

    def test_promote_next_reopens_when_approved_task_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, integrate = self._promotion_repo(
                tmp,
                drift=False,
                remove_task=True,
            )

            result = pipeline_state.promote_next(
                repo,
                "second",
                "gsd-path/M002",
                integrate,
            )

            self.assertEqual(result["drift"]["class"], "changed")
            self.assertEqual(result["drift"]["task_ids"], ["T002"])
            state, _, _ = pipeline_state.load_state(repo)
            self.assertEqual((state.phase, state.status), ("plan", "active"))

    def test_promote_next_rejects_duplicate_current_attempt_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, integrate = self._promotion_repo(
                tmp,
                drift=False,
                duplicate_approval=True,
            )

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "multiple matching plan approval checkpoints",
            ):
                pipeline_state.promote_next(
                    repo,
                    "second",
                    "gsd-path/M002",
                    integrate,
                )

    def test_plan_approval_search_does_not_adopt_prior_milestone_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            run_git(Path(tmp), "init", "-b", "main", str(repo))
            run_git(repo, "config", "user.name", "GSD Path Test")
            run_git(repo, "config", "user.email", "test@example.com")
            prior = repo / ".project" / "next"
            (prior / "plan").mkdir(parents=True)
            (prior / "tasks").mkdir()
            (prior / "STATE.md").write_text(state_text(), encoding="utf-8")
            (prior / "plan" / "PLAN.md").write_text("# Plan — second\n", encoding="utf-8")
            (prior / "tasks" / "T002-change-app.md").write_text(task_text(), encoding="utf-8")
            (repo / "app.py").write_text("base = True\n", encoding="utf-8")
            run_git(repo, "add", ".")
            run_git(
                repo,
                "commit",
                "-m",
                "plan: build plan approved",
                "-m",
                "Why: approved plan checkpoint\nMilestone: second",
            )
            shutil.rmtree(repo / ".project")
            run_git(repo, "add", "-A")
            run_git(repo, "commit", "-m", "fixture: current milestone boundary")
            run_git(repo, "switch", "-c", "gsd-path/M001")
            current = repo / ".project" / "next"
            (current / "plan").mkdir(parents=True)
            (current / "tasks").mkdir()
            (current / "STATE.md").write_text(state_text(), encoding="utf-8")
            (current / "plan" / "PLAN.md").write_text("# Plan — second\n", encoding="utf-8")
            (current / "tasks" / "T002-change-app.md").write_text(task_text(), encoding="utf-8")
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: unapproved current lookahead")
            run_git(repo, "switch", "main")
            run_git(
                repo,
                "merge",
                "--no-ff",
                "gsd-path/M001",
                "-m",
                "integrate: M001 — merge gsd-path/M001 into main",
            )
            integrate = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            candidate = pipeline_state._state_from_text(
                (current / "STATE.md").read_text(encoding="utf-8")
            )

            self.assertIsNone(
                pipeline_state._approval_checkpoint(repo, candidate, integrate)
            )

    def test_promote_next_rejects_spoofed_data_losing_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, integrate = self._promotion_repo(tmp, drift=False)
            project = repo / ".project"
            shutil.rmtree(project / "next")
            (project / "STATE.md").write_text(
                state_text(
                    milestone="second",
                    phase="plan",
                    status="done",
                    branch="gsd-path/M002",
                ),
                encoding="utf-8",
            )
            run_git(repo, "add", "-A", "--", ".project")
            run_git(
                repo,
                "commit",
                "-m",
                "router: promote lookahead milestone second",
                "-m",
                "Why: promote lookahead track\n"
                "Milestone: second\n"
                f"Integrate: {integrate}",
            )

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "wrong path set|did not preserve track",
            ):
                pipeline_state.promote_next(
                    repo,
                    "second",
                    "gsd-path/M002",
                    integrate,
                )

    def test_promote_next_rejects_lookahead_from_another_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, integrate = self._promotion_repo(
                tmp,
                drift=False,
                next_project="other",
            )

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "project does not match",
            ):
                pipeline_state.promote_next(
                    repo,
                    "second",
                    "gsd-path/M002",
                    integrate,
                )

    def test_promote_next_rejects_phase_outside_lookahead(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, integrate = self._promotion_repo(
                tmp,
                drift=False,
                next_phase="build",
                next_status="active",
            )

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "lookahead cannot enter build",
            ):
                pipeline_state.promote_next(
                    repo,
                    "second",
                    "gsd-path/M002",
                    integrate,
                )

    def test_promote_next_resumes_from_its_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, integrate = self._promotion_repo(tmp, drift=False)
            with mock.patch.object(
                pipeline_state,
                "_resume_metadata",
                side_effect=pipeline_state.PipelineStateError("simulated interruption"),
            ):
                with self.assertRaisesRegex(
                    pipeline_state.PipelineStateError,
                    "simulated interruption",
                ):
                    pipeline_state.promote_next(
                        repo,
                        "second",
                        "gsd-path/M002",
                        integrate,
                    )
            self.assertTrue((repo / ".project" / "tasks").is_dir())
            self.assertFalse((repo / ".project" / "next" / "tasks").exists())
            recovery = pipeline_state.route_state(repo)
            self.assertEqual(recovery["route"]["action"], "resume-promotion")
            self.assertEqual(recovery["route"]["milestone"], "second")
            self.assertEqual(recovery["route"]["base"], integrate)
            self.assertEqual(recovery["route"]["landing"], integrate)

            result = pipeline_state.promote_next(
                repo,
                "second",
                "gsd-path/M002",
                integrate,
            )

            self.assertEqual(result["status"], "promoted")
            self.assertFalse((repo / ".project" / "next").exists())

    def test_promote_next_resumes_after_staging_residual_track(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, integrate = self._promotion_repo(tmp, drift=False)
            with mock.patch.object(
                pipeline_state,
                "_commit_promotion",
                side_effect=pipeline_state.PipelineStateError("simulated interruption"),
            ):
                with self.assertRaisesRegex(
                    pipeline_state.PipelineStateError,
                    "simulated interruption",
                ):
                    pipeline_state.promote_next(
                        repo,
                        "second",
                        "gsd-path/M002",
                        integrate,
                    )

            residual = repo / pipeline_state.PROMOTION_RESIDUAL
            self.assertTrue(residual.is_dir())
            self.assertFalse((repo / ".project" / "next").exists())

            result = pipeline_state.promote_next(
                repo,
                "second",
                "gsd-path/M002",
                integrate,
            )

            self.assertEqual(result["status"], "promoted")
            self.assertFalse(residual.exists())

    def test_record_shipment_is_atomic_and_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "gsd-path/M001")
            project = repo / ".project"
            project.mkdir()
            (project / "CHARTER.md").write_text("# Charter\n", encoding="utf-8")
            (project / "STATE.md").write_text(
                state_text(
                    milestone="first", phase="ship", status="active",
                    branch="gsd-path/M001", archive=".project/archive/001-first",
                ), encoding="utf-8",
            )
            (project / "ROADMAP.md").write_text(
                roadmap_text().replace("Status: shipped", "Status: active", 1)
                .replace("Archive: .project/archive/001-first/", "Archive: null", 1),
                encoding="utf-8",
            )
            original = pipeline_state._atomic_write

            def interrupt(path: Path, content: str) -> None:
                if path.name == "STATE.md":
                    raise pipeline_state.PipelineStateError("simulated interruption")
                original(path, content)

            with mock.patch.object(pipeline_state, "_atomic_write", side_effect=interrupt):
                with self.assertRaisesRegex(pipeline_state.PipelineStateError, "interruption"):
                    pipeline_state.record_shipment(
                        repo, ".project/archive/001-first",
                        "archive preflight passed; shipment recorded",
                    )

            recovery = pipeline_state.route_state(repo)
            self.assertEqual(recovery["route"]["action"], "resume-shipment")

            result = pipeline_state.record_shipment(
                repo, ".project/archive/001-first",
                "archive preflight passed; shipment recorded",
            )
            retry = pipeline_state.record_shipment(
                repo, ".project/archive/001-first",
                "archive preflight passed; shipment recorded",
            )

            self.assertEqual(result["state"]["phase"], "shipped")
            self.assertEqual(retry["status"], "recorded")
            roadmap = (project / "ROADMAP.md").read_text()
            self.assertIn("Status: shipped", roadmap)
            self.assertIn("Archive: .project/archive/001-first", roadmap)

    def test_record_shipment_preserves_single_milestone_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "gsd-path/M001")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(milestone="first", phase="ship", status="active", branch="gsd-path/M001", archive=".project/archive/001-first"),
                encoding="utf-8",
            )

            result = pipeline_state.record_shipment(
                repo, ".project/archive/001-first",
                "archive preflight passed; shipment recorded",
            )

            self.assertEqual(result["state"]["phase"], "shipped")
            self.assertFalse((project / "ROADMAP.md").exists())

    def test_record_shipment_rejects_a_tampered_journal_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-b", "gsd-path/M001")
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(milestone="first", phase="ship", status="active", branch="gsd-path/M001", archive=".project/archive/001-first"),
                encoding="utf-8",
            )
            original = pipeline_state._atomic_write

            def interrupt(path: Path, content: str) -> None:
                if path.name == "STATE.md":
                    raise pipeline_state.PipelineStateError("simulated interruption")
                original(path, content)

            with mock.patch.object(pipeline_state, "_atomic_write", side_effect=interrupt):
                with self.assertRaises(pipeline_state.PipelineStateError):
                    pipeline_state.record_shipment(repo, ".project/archive/001-first", "archive preflight passed; shipment recorded")
            journal_path = pipeline_state._git_path(repo, pipeline_state.SHIPMENT_JOURNAL_NAME)
            journal = pipeline_state._read_json(journal_path)
            journal["state_after"] = journal["state_before"]
            pipeline_state._write_json(journal_path, journal)

            with self.assertRaisesRegex(
                pipeline_state.PipelineStateError,
                "journal target does not match derived metadata",
            ):
                pipeline_state.record_shipment(repo, ".project/archive/001-first", "archive preflight passed; shipment recorded")

    def test_record_shipment_rejects_missing_or_wrong_roadmap(self) -> None:
        for case in ("missing", "wrong"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                run_git(repo, "init", "-b", "gsd-path/M001")
                project = repo / ".project"
                project.mkdir()
                (project / "CHARTER.md").write_text("# Charter\n", encoding="utf-8")
                (project / "STATE.md").write_text(
                    state_text(milestone="first", phase="ship", status="active", branch="gsd-path/M001", archive=".project/archive/001-first"),
                    encoding="utf-8",
                )
                if case == "wrong":
                    (project / "ROADMAP.md").write_text(roadmap_text(), encoding="utf-8")
                with self.assertRaises(pipeline_state.PipelineStateError):
                    pipeline_state.record_shipment(repo, ".project/archive/001-first", "archive preflight passed; shipment recorded")


if __name__ == "__main__":
    unittest.main()
