import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon.config import Config
from gsd_daemon.plugin import DEFAULT_REPO, HOSTS, PluginManager
from gsd_daemon.serve import serve
from gsd_daemon.watcher import Watcher

GUARD_MARKER = "gsd-path guard"
RUNTIME_MARKER = "gsd-path project runtime"
STATUS_MARKER = "gsd-path project status launcher"
CLAUDE_BRIDGE = "@../AGENTS.md\n@../WORKFLOW.md\n"

STATE = """---
pipeline: gsd-path/v2
project: demo
milestone: demo-ms
phase: build
status: active
branch: gsd-path/M001
archive: null
---

# Project State
"""


class FakeRunner:
    """Programmable (rc, stdout, stderr) runner that records every call."""

    def __init__(self, responses=None):
        self.calls = []  # (argv, cwd)
        self.responses = list(responses or [])

    def __call__(self, argv, cwd=None):
        self.calls.append((list(argv), cwd))
        if self.responses:
            return self.responses.pop(0)
        return 0, "", ""


def make_manager(tmp, runner=None, git_runner=None, clock=None, **kwargs):
    base = Path(tmp)
    home = base / "daemon-home"
    user_home = base / "user-home"
    user_home.mkdir(parents=True, exist_ok=True)
    return PluginManager(
        home=home,
        user_home=user_home,
        runner=runner or FakeRunner(),
        git_runner=git_runner or FakeRunner(),
        environ={},
        out=lambda line: None,
        clock=clock or (lambda: 1_000_000.0),
        **kwargs,
    )


def make_source_clone(manager, version="1.2.0"):
    src = manager.src_dir
    (src / ".git").mkdir(parents=True)
    (src / "scripts").mkdir()
    (src / "scripts" / "install.py").write_text("# installer\n", encoding="utf-8")
    (src / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    (src / "AGENTS.md").write_text("# agents template\n", encoding="utf-8")
    (src / "WORKFLOW.md").write_text("# workflow template\n", encoding="utf-8")
    return src


def make_global_install(manager, host, version="1.0.0"):
    root = manager.global_root(host)
    skill = root / "gsd-path"
    skill.mkdir(parents=True)
    (skill / "VERSION").write_text(version + "\n", encoding="utf-8")
    (skill / "SKILL.md").write_text("# gsd-path\n", encoding="utf-8")
    return root


class ArgvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runner = FakeRunner()
        self.manager = make_manager(self.tmp.name, runner=self.runner)
        make_source_clone(self.manager)

    def argv(self):
        self.assertEqual(len(self.runner.calls), 1)
        return self.runner.calls[0][0]

    def test_install_global_all(self):
        result = self.manager.install_global()
        argv = self.argv()
        self.assertTrue(result["ok"])
        self.assertIn("--all", argv)
        self.assertNotIn("--update", argv)
        self.assertTrue(argv[0].endswith("python3") or "python" in Path(argv[0]).name)
        self.assertTrue(argv[1].endswith("scripts/install.py"))

    def test_install_global_hosts(self):
        self.manager.install_global(["claude", "kimi"])
        argv = self.argv()
        self.assertIn("--claude", argv)
        self.assertIn("--kimi", argv)
        self.assertNotIn("--all", argv)

    def test_install_global_dry_run(self):
        self.manager.install_global(["claude"], dry_run=True)
        self.assertIn("--dry-run", self.argv())

    def test_install_global_rejects_unknown_host(self):
        with self.assertRaises(ValueError):
            self.manager.install_global(["emacs"])

    def test_update_global(self):
        self.manager.update_global()
        argv = self.argv()
        self.assertIn("--update", argv)
        self.assertNotIn("--project", argv)

    def test_install_project_defaults_to_all(self):
        self.manager.install_project("/tmp/proj")
        argv = self.argv()
        self.assertIn("--project", argv)
        self.assertEqual(argv[argv.index("--project") + 1], "/tmp/proj")
        self.assertIn("--all", argv)
        self.assertNotIn("--local", argv)

    def test_install_project_local_hosts_and_hooks(self):
        self.manager.install_project("/tmp/proj", local_hosts=["claude", "kimi"], hooks=True)
        argv = self.argv()
        self.assertIn("--local", argv)
        self.assertIn("--claude", argv)
        self.assertIn("--kimi", argv)
        self.assertIn("--hooks", argv)
        self.assertNotIn("--all", argv)

    def test_update_project(self):
        self.manager.update_project("/tmp/proj", dry_run=True)
        argv = self.argv()
        self.assertIn("--runtime-upgrade", argv)
        self.assertIn("--project", argv)
        self.assertIn("--dry-run", argv)

    def test_updates_refresh_source_and_surface_fetch_failure(self):
        for scope in ("global", "project"):
            with self.subTest(scope=scope):
                self.runner.calls.clear()
                self.manager.git_runner = FakeRunner([(1, "", "source fetch failed")])
                result = (self.manager.update_project("/tmp/proj") if scope == "project"
                          else self.manager.update_global())
                self.assertFalse(result["ok"])
                self.assertIn("source fetch failed", result["error"])
                self.assertEqual(self.runner.calls, [])

    def test_wrapper_result_shape_and_log(self):
        self.runner.responses = [(0, "line1\nline2\n", "")]
        result = self.manager.install_global()
        self.assertEqual(result["stdout_tail"], "line1\nline2")
        self.assertIsNone(result["error"])
        log = self.manager.log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(log), 1)
        record = json.loads(log[0])
        self.assertEqual(record["rc"], 0)
        self.assertIn("--all", record["argv"])

    def test_wrapper_failure_reports_error(self):
        self.runner.responses = [(1, "boom output", "boom error")]
        result = self.manager.install_global()
        self.assertFalse(result["ok"])
        self.assertIn("boom error", result["error"])

    def test_wrapper_partial_exit_two(self):
        self.runner.responses = [(2, "", "host zed failed")]
        result = self.manager.install_global()
        self.assertFalse(result["ok"])
        self.assertIn("partial", result["error"])


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_ensure_source_clones_when_absent(self):
        git = FakeRunner()
        manager = make_manager(self.tmp.name, git_runner=git)
        manager.ensure_source()
        self.assertEqual(len(git.calls), 1)
        argv = git.calls[0][0]
        self.assertEqual(argv[:2], ["git", "clone"])
        self.assertEqual(argv[2], DEFAULT_REPO)
        self.assertTrue(argv[3].endswith("src"))

    def test_ensure_source_no_clone_when_present(self):
        git = FakeRunner()
        manager = make_manager(self.tmp.name, git_runner=git)
        make_source_clone(manager)
        manager.ensure_source()
        self.assertEqual(git.calls, [])

    def test_ensure_source_ssh_fallback_succeeds(self):
        git = FakeRunner(responses=[(128, "", "terminal prompts disabled")])
        manager = make_manager(self.tmp.name, git_runner=git)
        manager.ensure_source()
        self.assertEqual(len(git.calls), 2)
        self.assertEqual(git.calls[0][0][2], DEFAULT_REPO)
        self.assertEqual(git.calls[1][0][2], "git@github.com:open-gsd/gsd-path.git")

    def test_ensure_source_clone_failure_raises_friendly_private_repo_error(self):
        git = FakeRunner(responses=[
            (128, "", "remote: Repository not found"),
            (128, "", "Permission denied (publickey)"),
        ])
        manager = make_manager(self.tmp.name, git_runner=git)
        with self.assertRaises(RuntimeError) as ctx:
            manager.ensure_source()
        message = str(ctx.exception)
        self.assertIn("private", message)
        self.assertIn("gh auth login", message)
        self.assertIn("Repository not found", message)
        self.assertIn("Permission denied (publickey)", message)
        self.assertEqual(len(git.calls), 2)

    def test_refresh_throttled_by_ttl(self):
        now = [1_000_000.0]
        git = FakeRunner()
        manager = make_manager(self.tmp.name, git_runner=git, clock=lambda: now[0])
        make_source_clone(manager, version="1.2.0")
        first = manager.refresh_source(ttl_hours=24)
        self.assertTrue(first["refreshed"])
        self.assertEqual(first["latest"], "1.2.0")
        self.assertEqual(len(git.calls), 2)  # fetch + pull
        now[0] += 3600  # 1h later — inside the TTL
        second = manager.refresh_source(ttl_hours=24)
        self.assertFalse(second["refreshed"])
        self.assertEqual(second["latest"], "1.2.0")
        self.assertEqual(len(git.calls), 2)  # no new git calls
        now[0] += 24 * 3600  # past the TTL
        third = manager.refresh_source(ttl_hours=24)
        self.assertTrue(third["refreshed"])
        self.assertEqual(len(git.calls), 4)

    def test_refresh_offline_keeps_cached_state(self):
        git = FakeRunner(responses=[(128, "", "could not resolve host")])
        manager = make_manager(self.tmp.name, git_runner=git)
        make_source_clone(manager)
        manager._write_cache("1.1.0")
        # age the cache past the TTL so a refresh is attempted
        cache = json.loads(manager.cache_path.read_text(encoding="utf-8"))
        cache["last_fetch_epoch"] = 0
        manager.cache_path.write_text(json.dumps(cache), encoding="utf-8")
        git.responses = [(1, "", "offline")]
        result = manager.refresh_source(ttl_hours=24)
        self.assertFalse(result["refreshed"])
        self.assertEqual(result["latest"], "1.1.0")
        self.assertIsNotNone(result["error"])

    def test_src_version(self):
        manager = make_manager(self.tmp.name)
        self.assertIsNone(manager.src_version())
        make_source_clone(manager, version="2.0.1")
        self.assertEqual(manager.src_version(), "2.0.1")


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = make_manager(self.tmp.name)

    def test_detect_global_from_version_stamps(self):
        make_global_install(self.manager, "kimi", version="1.0.0")
        make_global_install(self.manager, "claude", version="1.0.0")
        detection = self.manager.detect_global()
        self.assertTrue(detection["kimi"]["installed"])
        self.assertEqual(detection["kimi"]["version"], "1.0.0")
        self.assertIn("gsd-path", detection["kimi"]["skill_dirs"])
        self.assertFalse(detection["cursor"]["installed"])
        self.assertIsNone(detection["cursor"]["version"])
        self.assertEqual(set(detection), set(HOSTS))

    def test_detect_global_no_clone_required(self):
        make_global_install(self.manager, "kimi")
        detection = self.manager.detect_global()
        self.assertTrue(detection["kimi"]["installed"])
        self.assertFalse(self.manager.src_dir.exists())

    def test_detect_project(self):
        project = Path(self.tmp.name) / "proj"
        local = project / ".kimi-code" / "skills" / "gsd-path"
        local.mkdir(parents=True)
        (local / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        runtime = project / ".gsd-path" / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "pipeline_state.py").write_text(f"# {RUNTIME_MARKER}\n", encoding="utf-8")
        (project / ".gsd-path" / "status_runtime.py").write_text(
            f"# {STATUS_MARKER}\n", encoding="utf-8")
        (project / ".gsd-path" / "guard_hook.py").write_text(f"# {GUARD_MARKER}\n", encoding="utf-8")
        (project / ".gsd-path" / "git_guard.py").write_text(f"# {GUARD_MARKER}\n", encoding="utf-8")
        (project / "AGENTS.md").write_text("x\n", encoding="utf-8")
        (project / "WORKFLOW.md").write_text("y\n", encoding="utf-8")
        result = self.manager.detect_project(project)
        self.assertEqual(result["local_skills"], ["kimi"])
        self.assertTrue(result["runtime"])
        self.assertTrue(result["hooks"])
        self.assertTrue(result["contracts"])
        self.assertIsNone(result["runtime_version"])
        (runtime / "VERSION").write_text("1.1.0\n")
        self.assertEqual(self.manager.detect_project(project)["runtime_version"], "1.1.0")
        (project / ".gsd-path/runtime.json").write_text(json.dumps({
            "schema": "gsd-path/runtime/v1", "version": "1.2.3", "digest": "a" * 64,
        }))
        self.assertEqual(self.manager.detect_project(project)["runtime_version"], "1.2.3")
        plan = self.manager.plan_uninstall_project(project)
        self.assertIn(str(runtime / "VERSION"), [entry["path"] for entry in plan["plan"]])
        self.manager.apply_plan(plan, confirm=True)
        self.assertIsNone(self.manager.detect_project(project)["runtime_version"])


    def test_check_update_uses_cache_offline(self):
        make_global_install(self.manager, "kimi", version="1.0.0")
        self.manager._write_cache("1.1.0")
        result = self.manager.check_update(fetch=False)
        self.assertEqual(result["latest"], "1.1.0")
        self.assertEqual(result["installed"], {"kimi": "1.0.0"})
        self.assertTrue(result["update_available"])
        self.assertFalse(self.manager.src_dir.exists())

    def test_check_update_no_cache(self):
        make_global_install(self.manager, "kimi", version="1.0.0")
        result = self.manager.check_update(fetch=False)
        self.assertIsNone(result["latest"])
        self.assertFalse(result["update_available"])


class UninstallPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = make_manager(self.tmp.name)
        self.src = make_source_clone(self.manager)

    def test_global_plan_only_proven_managed_dirs(self):
        root = make_global_install(self.manager, "kimi")
        # managed name but no VERSION and no gsd-path SKILL.md -> kept
        impostor = root / "gsd-path-impostor"
        impostor.mkdir()
        (impostor / "SKILL.md").write_text("# unrelated\n", encoding="utf-8")
        # backup dir -> never touched
        backup = root / "disabled-gsd-skills-2026"
        backup.mkdir()
        # foreign dir -> not listed at all
        (root / "other-skill").mkdir()
        plan = self.manager.plan_uninstall_global(["kimi"])
        paths = [entry["path"] for entry in plan["plan"]]
        self.assertIn(str(root / "gsd-path"), paths)
        self.assertNotIn(str(impostor), paths)
        self.assertFalse(any("disabled-gsd-skills" in path for path in paths))
        self.assertFalse(any("other-skill" in path for path in paths))
        skipped = {entry["path"]: entry["reason"] for entry in plan["skipped"]}
        self.assertIn(str(impostor), skipped)
        self.assertIn(str(backup), skipped)
        # hosts without a skills root appear in skipped, never in plan
        self.assertFalse(any(path.endswith("skills") for path in paths))

    def test_global_plan_includes_cursor_agent_file(self):
        agent = self.manager.user_home / ".cursor" / "agents" / "gsd-path.md"
        agent.parent.mkdir(parents=True)
        agent.write_text("# gsd-path subagent\n", encoding="utf-8")
        plan = self.manager.plan_uninstall_global(["cursor"])
        paths = [entry["path"] for entry in plan["plan"]]
        self.assertIn(str(agent), paths)
        plan = self.manager.plan_uninstall_global(["kimi"])
        self.assertNotIn(str(agent), [entry["path"] for entry in plan["plan"]])

    def _make_project(self):
        project = Path(self.tmp.name) / "proj"
        project.mkdir()
        return project

    def test_project_plan_markers_and_templates(self):
        project = self._make_project()
        runtime = project / ".gsd-path" / "runtime"
        runtime.mkdir(parents=True)
        managed = runtime / "pipeline_state.py"
        managed.write_text(f"# {RUNTIME_MARKER}\n", encoding="utf-8")
        foreign = runtime / "custom.py"
        foreign.write_text("# mine\n", encoding="utf-8")
        launcher = project / ".gsd-path" / "status_runtime.py"
        launcher.write_text(f"# {STATUS_MARKER}\n", encoding="utf-8")
        guard = project / ".gsd-path" / "guard_hook.py"
        guard.write_text(f"# {GUARD_MARKER}\n", encoding="utf-8")
        declaration = project / ".gsd-path/runtime.json"
        declaration.write_text(json.dumps({
            "schema": "gsd-path/runtime/v1", "version": "1.2.3", "digest": "a" * 64,
        }))
        # template-identical AGENTS.md -> planned; modified WORKFLOW.md -> kept
        (project / "AGENTS.md").write_bytes((self.src / "AGENTS.md").read_bytes())
        (project / "WORKFLOW.md").write_text("user edits\n", encoding="utf-8")
        (project / ".claude").mkdir()
        (project / ".claude" / "CLAUDE.md").write_text(CLAUDE_BRIDGE, encoding="utf-8")
        plan = self.manager.plan_uninstall_project(project)
        paths = [entry["path"] for entry in plan["plan"]]
        for expected in (managed, launcher, guard, declaration, project / "AGENTS.md",
                         project / ".claude" / "CLAUDE.md"):
            self.assertIn(str(expected), paths)
        skipped = {entry["path"]: entry["reason"] for entry in plan["skipped"]}
        self.assertIn(str(foreign), skipped)
        self.assertIn(str(project / "WORKFLOW.md"), skipped)
        self.assertIn("user-modified", skipped[str(project / "WORKFLOW.md")])

    def test_project_plan_never_touches_dot_project(self):
        project = self._make_project()
        # lookalikes inside .project/ must never appear in the plan
        inside = project / ".project"
        (inside / ".gsd-path" / "runtime").mkdir(parents=True)
        (inside / ".gsd-path" / "runtime" / "pipeline_state.py").write_text(
            f"# {RUNTIME_MARKER}\n", encoding="utf-8")
        (inside / "AGENTS.md").write_bytes((self.src / "AGENTS.md").read_bytes())
        local = inside / ".kimi-code" / "skills" / "gsd-path"
        local.mkdir(parents=True)
        (local / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        plan = self.manager.plan_uninstall_project(project)
        for entry in plan["plan"]:
            self.assertNotIn(".project", Path(entry["path"]).parts)

    def test_project_plan_git_hooks(self):
        project = self._make_project()
        hooks_dir = project / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        managed_hook = hooks_dir / "pre-commit"
        managed_hook.write_text(f"#!/bin/sh\n# {GUARD_MARKER}: x\n", encoding="utf-8")
        user_hook = hooks_dir / "commit-msg"
        user_hook.write_text("#!/bin/sh\n# user hook\n", encoding="utf-8")
        plan = self.manager.plan_uninstall_project(project)
        paths = [entry["path"] for entry in plan["plan"]]
        self.assertIn(str(managed_hook), paths)
        skipped = {entry["path"]: entry["reason"] for entry in plan["skipped"]}
        self.assertIn(str(user_hook), skipped)

    def test_settings_unmerge_preserves_foreign_keys(self):
        project = self._make_project()
        (project / ".claude").mkdir()
        settings = project / ".claude" / "settings.json"
        payload = {
            "model": "opus",
            "hooks": {
                "PreToolUse": [
                    {"matcher": ".*", "hooks": [
                        {"type": "command",
                         "command": 'python3 "$CLAUDE_PROJECT_DIR/.gsd-path/guard_hook.py"'},
                    ]},
                    {"matcher": "Bash", "hooks": [
                        {"type": "command", "command": "echo hi"},
                    ]},
                    {"matcher": "mixed", "hooks": [
                        {"type": "command",
                         "command": 'python3 ".gsd-path/guard_hook.py"'},
                        {"type": "command", "command": "echo keep-me"},
                    ]},
                ],
                "PostToolUse": [{"matcher": ".*", "hooks": []}],
            },
        }
        settings.write_text(json.dumps(payload), encoding="utf-8")
        plan = self.manager.plan_uninstall_project(project)
        kinds = {entry["path"]: entry["kind"] for entry in plan["plan"]}
        self.assertEqual(kinds[str(settings)], "settings")
        writes = {}
        manager = make_manager(
            self.tmp.name,
            remove_dir=lambda p: None,
            remove_file=lambda p: writes.setdefault("removed", []).append(p),
            write_file=lambda p, text: writes.setdefault(p, text),
        )
        result = manager.apply_plan(plan, confirm=True)
        self.assertTrue(result["ok"])
        rewritten = json.loads(writes[str(settings)])
        self.assertEqual(rewritten["model"], "opus")
        pre = rewritten["hooks"]["PreToolUse"]
        # foreign entries survive; the mixed entry keeps only its foreign hook
        self.assertEqual(len(pre), 2)
        self.assertEqual(pre[0]["matcher"], "Bash")
        self.assertEqual(pre[1]["hooks"], [{"type": "command", "command": "echo keep-me"}])
        self.assertIn("PostToolUse", rewritten["hooks"])
        self.assertTrue(settings.exists())  # fake hooks did not delete

    def test_settings_file_deleted_when_empty_after_unmerge(self):
        project = self._make_project()
        (project / ".cursor").mkdir()
        settings = project / ".cursor" / "hooks.json"
        payload = {
            "version": 1,
            "hooks": {"preToolUse": [
                {"command": 'python3 ".gsd-path/guard_hook.py"',
                 "matcher": ".*", "failClosed": True},
            ]},
        }
        settings.write_text(json.dumps(payload), encoding="utf-8")
        removed = []
        manager = make_manager(self.tmp.name,
                               remove_file=lambda p: removed.append(p),
                               remove_dir=lambda p: None)
        plan = manager.plan_uninstall_project(project)
        kinds = {entry["path"]: entry["kind"] for entry in plan["plan"]}
        self.assertEqual(kinds[str(settings)], "settings")
        result = manager.apply_plan(plan, confirm=True)
        self.assertTrue(result["ok"])
        self.assertIn(str(settings), removed)

    def test_invalid_settings_json_kept(self):
        project = self._make_project()
        (project / ".claude").mkdir()
        settings = project / ".claude" / "settings.json"
        settings.write_text("{not json", encoding="utf-8")
        plan = self.manager.plan_uninstall_project(project)
        skipped = {entry["path"]: entry["reason"] for entry in plan["skipped"]}
        self.assertIn(str(settings), skipped)

    def test_apply_plan_requires_confirm(self):
        removed = []
        manager = make_manager(self.tmp.name,
                               remove_file=lambda p: removed.append(p),
                               remove_dir=lambda p: removed.append(p))
        plan = {"plan": [{"path": "/tmp/x", "kind": "file", "reason": "test"}]}
        result = manager.apply_plan(plan, confirm=False)
        self.assertFalse(result["ok"])
        self.assertTrue(result["refused"])
        self.assertEqual(removed, [])
        result = manager.apply_plan(plan, confirm=True)
        self.assertTrue(result["ok"])
        self.assertEqual(removed, ["/tmp/x"])

    def test_apply_plan_refuses_dot_project_entries(self):
        removed = []
        manager = make_manager(self.tmp.name,
                               remove_file=lambda p: removed.append(p),
                               remove_dir=lambda p: removed.append(p))
        plan = {"plan": [{"path": "/tmp/proj/.project/STATE.md", "kind": "file",
                          "reason": "forged"}]}
        result = manager.apply_plan(plan, confirm=True)
        self.assertFalse(result["ok"])
        self.assertEqual(removed, [])
        self.assertEqual(result["applied"], [])


class EndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        parent = Path(cls.tmp.name) / "work"
        project = parent / "demo"
        (project / ".project").mkdir(parents=True)
        (project / ".project" / "STATE.md").write_text(STATE, encoding="utf-8")
        cls.project = project
        cls.manager = make_manager(cls.tmp.name)
        make_global_install(cls.manager, "kimi", version="1.0.0")
        cls.manager._write_cache("9.9.9")
        watcher = Watcher(Config(parents=[str(parent)]))
        cls.server = serve(watcher, port=0, plugin=cls.manager)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body) if body is not None else None
        connection.request(
            method, path, body=payload,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data)

    def test_status_has_plugin_key(self):
        status, payload = self.request("GET", "/status")
        self.assertEqual(status, 200)
        self.assertIn("plugin", payload)
        plugin = payload["plugin"]
        self.assertEqual(plugin["latest"], "9.9.9")
        self.assertTrue(plugin["update_available"])
        self.assertTrue(plugin["hosts"]["kimi"]["installed"])
        self.assertFalse(plugin["hosts"]["cursor"]["installed"])

    def test_api_plugin_status_full(self):
        status, payload = self.request("GET", "/api/plugin/status")
        self.assertEqual(status, 200)
        self.assertIn("hosts", payload)
        self.assertIn("projects", payload)
        self.assertEqual(payload["hosts"]["kimi"]["version"], "1.0.0")
        self.assertEqual(len(payload["projects"]), 1)
        project = payload["projects"][0]
        self.assertEqual(project["root"], str(self.project))
        for key in ("local_skills", "runtime", "contracts", "hooks", "runtime_version"):
            self.assertIn(key, project)

    def test_uninstall_dry_run_returns_plan(self):
        status, payload = self.request(
            "POST", "/api/plugin/uninstall", {"scope": "global", "hosts": ["kimi"],
                                              "dry_run": True})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        paths = [entry["path"] for entry in payload["plan"]["plan"]]
        self.assertTrue(any(path.endswith("gsd-path") for path in paths))
        self.assertFalse(any(".project" in Path(path).parts for path in paths))

    def test_uninstall_without_confirm_rejected(self):
        status, payload = self.request(
            "POST", "/api/plugin/uninstall", {"scope": "global", "hosts": ["kimi"]})
        self.assertEqual(status, 400)
        self.assertIn("confirm", payload["error"])

    def test_uninstall_project_requires_root(self):
        status, payload = self.request(
            "POST", "/api/plugin/uninstall", {"scope": "project", "dry_run": True})
        self.assertEqual(status, 400)
        self.assertIn("root", payload["error"])

    def test_invalid_body_rejected(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("POST", "/api/plugin/uninstall", body="{nope",
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        response.read()
        connection.close()
        self.assertEqual(response.status, 400)

    def test_409_while_operation_in_progress(self):
        started = threading.Event()
        release = threading.Event()

        def slow_runner(argv, cwd=None):
            started.set()
            release.wait(timeout=5)
            return 0, "done", ""

        manager = make_manager(self.__class__.tmp.name, runner=slow_runner)
        make_source_clone(manager)
        # swap the handler's plugin for one with a slow op
        original = self.server.RequestHandlerClass.plugin
        self.server.RequestHandlerClass.plugin = manager
        try:
            first = {}
            def fire():
                first["result"] = self.request(
                    "POST", "/api/plugin/install", {"scope": "global", "hosts": ["kimi"]})
            thread = threading.Thread(target=fire, daemon=True)
            thread.start()
            self.assertTrue(started.wait(timeout=5))
            status, payload = self.request(
                "POST", "/api/plugin/update", {"scope": "global"})
            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], "operation in progress")
            release.set()
            thread.join(timeout=5)
            self.assertEqual(first["result"][0], 200)
            self.assertTrue(first["result"][1]["ok"])
        finally:
            release.set()
            self.server.RequestHandlerClass.plugin = original

    def test_dashboard_has_plugin_tab(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", "/")
        response = connection.getresponse()
        html = response.read().decode("utf-8")
        connection.close()
        self.assertEqual(response.status, 200)
        for marker in ('data-nav="plugin"', "tabPlugin", "/api/plugin/status",
                       "uninstallPlan", "Install for all detected hosts"):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
