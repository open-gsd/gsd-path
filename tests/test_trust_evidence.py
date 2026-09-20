import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_trust_evidence, pipeline_git
from tests import test_archive_milestone


class TrustEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture_temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        self.fixtures = {}
        self.omit_fixture_artifact = {}
        self.fixture_states = {}
        self.fixture_manifest_overrides = {}
        self.keep_fixture_branches = set()
        self.unrelated_integration_hosts = set()
        self.blocked_final_hosts = set()
        self.shared_history_groups = {}
        self.shared_landing_groups = set()
        self.guard_tiers = {
            "alpha": "native-fail-closed",
            "beta": "git-only",
        }
        self.child_apis = {"alpha": "alpha.spawn", "beta": "beta.spawn"}
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "skill-resources.json").write_text(
            json.dumps(
                {
                    "hosts": {
                        "alpha": {
                            "local_root": ".alpha/skills",
                            "guard_tier": self.guard_tiers["alpha"],
                            "child_apis": [self.child_apis["alpha"]],
                        },
                        "beta": {
                            "local_root": ".beta/skills",
                            "guard_tier": self.guard_tiers["beta"],
                            "child_apis": [self.child_apis["beta"]],
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        (self.repo / "package.json").write_text(
            json.dumps({"version": "1.2.3"}), encoding="utf-8"
        )
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "trust@example.invalid")
        self.git("config", "user.name", "Trust")
        self.git("add", "-A")
        self.git("commit", "-qm", "candidate")
        self.candidate = self.git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self):
        self.fixture_temporary.cleanup()
        self.temporary.cleanup()

    def git(self, *arguments):
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.repo,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result

    def fixture(self, host):
        if host in self.fixtures:
            return self.fixtures[host]
        fixture_hosts = (host,)
        for owner, members in self.shared_history_groups.items():
            if host not in members:
                continue
            if host != owner:
                self.fixture(owner)
                return self.fixtures[host]
            fixture_hosts = members
            break
        repository = Path(self.fixture_temporary.name) / host
        repository.mkdir()
        remote = repository.parent / f"{host}-origin.git"
        builder = test_archive_milestone.ArchiveMilestoneTests()

        def git(*arguments):
            result = subprocess.run(
                ["git", *arguments],
                cwd=repository,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            return result.stdout.strip()

        with mock.patch.dict(
            "os.environ",
            {
                "GIT_AUTHOR_NAME": f"Trust Evidence {host}",
                "GIT_COMMITTER_NAME": f"Trust Evidence {host}",
            },
        ):
            builder.make_publishable_bound_repo(repository, remote)
        landing = git("rev-parse", "HEAD")
        base = git("rev-parse", "HEAD^")
        pre_integration_default = git("rev-parse", "main")
        landing_commits = {fixture_hosts[0]: landing}
        reviewed_head = landing
        for evidence_host in fixture_hosts[1:]:
            git("commit", "--allow-empty", "-qm", f"land {evidence_host} task")
            landing_commit = git("rev-parse", "HEAD")
            landing_commits[evidence_host] = (
                landing if host in self.shared_landing_groups else landing_commit
            )
            for review_name in ("FINAL.md", "final-gap-1.md"):
                review = repository / ".project" / "review" / review_name
                review.write_text(
                    review.read_text(encoding="utf-8").replace(
                        f"Reviewed HEAD: {reviewed_head}",
                        f"Reviewed HEAD: {landing_commit}",
                    ),
                    encoding="utf-8",
                )
            reviewed_head = landing_commit
        pre_integration_defaults = {fixture_hosts[0]: pre_integration_default}
        default_tree = git("rev-parse", f"{pre_integration_default}^{{tree}}")
        for evidence_host in fixture_hosts[1:]:
            pre_integration_defaults[evidence_host] = git(
                "commit-tree",
                default_tree,
                "-p",
                pre_integration_default,
                "-m",
                f"advance {evidence_host} default",
            )
        task_branches = {
            evidence_host: f"task/{evidence_host}-milestone"
            for evidence_host in fixture_hosts
        }
        task_worktrees = {
            evidence_host: repository.parent / f"{evidence_host}-task-worktree"
            for evidence_host in fixture_hosts
        }
        run_ids = {
            evidence_host: f"{evidence_host}-run-001"
            for evidence_host in fixture_hosts
        }
        archive_directory = builder.prepare_archive(repository)
        archive = archive_directory.relative_to(repository).as_posix()
        artifact_paths_by_host = {}
        run_manifests = {}
        for evidence_host in fixture_hosts:
            suffix = f"-{evidence_host}" if len(fixture_hosts) > 1 else ""
            artifact_paths = {
                "state": ".project/STATE.md",
                "verify": f"{archive}/tasks/T001-demo.md",
                "wave_review": f"{archive}/review/wave-1.cycle1.md",
                "final_review": f"{archive}/review/FINAL.md",
                "archive": archive,
                "guards": f"{archive}/guards{suffix}.json",
            }
            run_manifest = f"{archive}/trust-run-manifest{suffix}.json"
            artifact_paths_by_host[evidence_host] = artifact_paths
            run_manifests[evidence_host] = run_manifest
            (repository / artifact_paths["guards"]).write_text(
                json.dumps(
                    {
                        "schema": check_trust_evidence.GUARD_EVIDENCE_SCHEMA,
                        "host": evidence_host,
                        "run_id": run_ids[evidence_host],
                        "declared_tier": self.guard_tiers[evidence_host],
                        "native_guard": (
                            "not-applicable"
                            if self.guard_tiers[evidence_host] == "git-only"
                            else "pass"
                        ),
                        "git_hooks": "pass",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            manifest = {
                "schema": check_trust_evidence.RUN_MANIFEST_SCHEMA,
                "host": evidence_host,
                "run_id": run_ids[evidence_host],
                "host_version": "fixture-cli 1.0",
                "candidate": self.candidate,
                "package_version": "1.2.3",
                "child_api": self.child_apis[evidence_host],
                "child_id": "builder",
                "guard_tier": self.guard_tiers[evidence_host],
                "fixture_base_commit": base,
                "landing_commit": landing_commits[evidence_host],
                "pre_integration_default_commit": pre_integration_defaults[
                    evidence_host
                ],
                "task_branch": task_branches[evidence_host],
                "bound_branch": "gsd-path/M001",
                "default_branch": "main",
                "milestone_tag": f"milestone/{archive_directory.name}",
                "artifacts": artifact_paths,
            }
            manifest.update(self.fixture_manifest_overrides.get(evidence_host, {}))
            (repository / run_manifest).write_text(
                json.dumps(manifest) + "\n", encoding="utf-8"
            )
        task_branch = task_branches[host]
        task_worktree = task_worktrees[host]
        artifact_paths = artifact_paths_by_host[host]
        rendered = builder.render_manifest(repository)
        self.assertEqual(0, rendered.returncode, rendered.stderr)
        checked = builder.preflight(repository)
        self.assertEqual(0, checked.returncode, checked.stderr)
        builder.mark_shipped(repository)
        if host in self.blocked_final_hosts:
            final = repository / artifact_paths["final_review"]
            final.write_text(
                final.read_text(encoding="utf-8").replace(
                    "Overall verdict: pass", "Overall verdict: blocked"
                ),
                encoding="utf-8",
            )
        if host in self.fixture_states:
            (repository / artifact_paths["state"]).write_text(
                self.fixture_states[host], encoding="utf-8"
            )
        omitted = self.omit_fixture_artifact.get(host)
        if omitted:
            (repository / omitted).unlink()
        git("add", ".project")
        ship_result = builder.commit_ship(repository, archive_directory)
        self.assertEqual(0, ship_result.returncode, ship_result.stderr)
        ship = git("rev-parse", "HEAD")
        bound_branch = "gsd-path/M001"
        milestone_tag = f"milestone/{archive_directory.name}"
        integration_worktree = repository.parent / f".{host}-gsd-path-integrate-M001"
        invalid_ship = bool(
            omitted
            or host in self.fixture_states
            or host in self.blocked_final_hosts
        )
        if invalid_ship or host in self.unrelated_integration_hosts:
            git("worktree", "add", "-q", str(integration_worktree), "main")

            def integration_git(*arguments):
                result = subprocess.run(
                    ["git", *arguments],
                    cwd=integration_worktree,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                return result.stdout.strip()

            merge_commit = ship
            if host in self.unrelated_integration_hosts:
                integration_git("merge", "--ff-only", "-q", bound_branch)
                tree = git("rev-parse", f"{pre_integration_default}^{{tree}}")
                merge_commit = git(
                    "commit-tree",
                    tree,
                    "-p",
                    pre_integration_default,
                    "-m",
                    "unrelated change",
                )
            integration_git(
                "merge",
                "--no-ff",
                "-q",
                "-m",
                pipeline_git.integrate_subject(archive_directory.name, "main"),
                "-m",
                pipeline_git.integrate_commit_body(
                    archive, ship, "main", bound_branch
                ),
                merge_commit,
            )
            integration = integration_git("rev-parse", "HEAD")
            integration_git("tag", "-a", "-m", f"{host} milestone", milestone_tag)
            integration_git(
                "push",
                "-q",
                "origin",
                "main",
                f"{bound_branch}:{bound_branch}",
                f"refs/tags/{milestone_tag}",
            )
            git("worktree", "remove", str(integration_worktree))
            git("fetch", "-q", "origin")
            tag_object = git("rev-parse", f"refs/tags/{milestone_tag}")
            git("update-ref", f"refs/remotes/origin/tags/{milestone_tag}", tag_object)
        else:
            integrated = builder.integrate(repository)
            self.assertEqual(0, integrated.returncode, integrated.stderr)
            result = json.loads(integrated.stdout)
            integration = result["integrate"]
            integration_worktree = (
                repository.parent / f".{repository.name}-gsd-path-integrate-M001"
            )
        integrations = {fixture_hosts[0]: integration}
        if host in self.keep_fixture_branches:
            git("branch", task_branch, landing)

        def create_bundle(evidence_host):
            bundle_path = self.artifact(evidence_host, "fixture").with_suffix(
                ".bundle"
            )
            bundle_path.parent.mkdir(parents=True, exist_ok=True)
            git("bundle", "create", str(bundle_path), "--all")

        create_bundle(fixture_hosts[0])
        ship_tree = git("rev-parse", f"{ship}^{{tree}}")
        for evidence_host in fixture_hosts[1:]:
            alternate_integration = git(
                "commit-tree",
                ship_tree,
                "-p",
                pre_integration_defaults[evidence_host],
                "-p",
                ship,
                "-m",
                pipeline_git.integrate_subject(archive_directory.name, "main"),
                "-m",
                pipeline_git.integrate_commit_body(
                    archive, ship, "main", bound_branch
                ),
            )
            integrations[evidence_host] = alternate_integration
            git(
                "tag",
                "-f",
                "-a",
                "-m",
                f"{evidence_host} milestone",
                milestone_tag,
                alternate_integration,
            )
            tag_object = git("rev-parse", f"refs/tags/{milestone_tag}")
            git("update-ref", "refs/remotes/origin/main", alternate_integration)
            git(
                "update-ref",
                f"refs/remotes/origin/tags/{milestone_tag}",
                tag_object,
            )
            create_bundle(evidence_host)

        for evidence_host in fixture_hosts:
            self.fixtures[evidence_host] = {
                "base": base,
                "landing": landing_commits[evidence_host],
                "ship": ship,
                "pre_integration_default": pre_integration_defaults[evidence_host],
                "integration": integrations[evidence_host],
                "milestone_tag": milestone_tag,
                "bound_branch": bound_branch,
                "default_branch": "main",
                "task_branch": task_branches[evidence_host],
                "task_worktree": str(task_worktrees[evidence_host]),
                "primary_worktree": str(repository),
                "integration_worktree": str(integration_worktree),
                "worktree_output": (
                    f"worktree {repository}\n"
                    f"HEAD {ship}\n"
                    f"branch refs/heads/{bound_branch}\n"
                ),
                "bundle": f"{evidence_host}/fixture.bundle",
                "run_id": run_ids[evidence_host],
                "run_manifest": run_manifests[evidence_host],
                "artifacts": artifact_paths_by_host[evidence_host],
            }
        return self.fixtures[host]

    def step_evidence(self, host, step):
        fixture = self.fixture(host)
        child_spawn = step == "child-spawn"
        evidence = {
            "schema": check_trust_evidence.STEP_SCHEMA,
            "host": host,
            "step": step,
            "run_id": fixture["run_id"],
            "command": (
                self.child_apis[host]
                if child_spawn
                else f"run {step} for {host}"
            ),
            "result": "pass",
            "output": (
                {"child_id": "builder", "status": "completed"}
                if child_spawn
                else f"observed {step} output for {host}"
            ),
        }
        details = {
            "install": {
                "host_version": "fixture-cli 1.0",
                "install_root": f".{host}/skills",
                "candidate": self.candidate,
                "package_version": "1.2.3",
                "exit_code": 0,
            },
            "router": {
                "state_artifact": fixture["artifacts"]["state"],
                "state_phase": "shipped",
            },
            "child-spawn": {
                "child_api": self.child_apis[host],
                "child_id": "builder",
                "child_status": "completed",
            },
            "task-landing": {
                "fixture_bundle": fixture["bundle"],
                "run_manifest": fixture["run_manifest"],
                "fixture_base_commit": fixture["base"],
                "task_branch": fixture["task_branch"],
                "task_worktree": fixture["task_worktree"],
                "landing_commit": fixture["landing"],
            },
            "task-verify": {
                "verify_artifact": fixture["artifacts"]["verify"],
                "verify_exit_code": 0,
            },
            "reviews": {
                "wave_review_artifact": fixture["artifacts"]["wave_review"],
                "final_review_artifact": fixture["artifacts"]["final_review"],
            },
            "archive": {
                "archive_path": fixture["artifacts"]["archive"],
                "validation_exit_code": 0,
            },
            "integration": {
                "fixture_bundle": fixture["bundle"],
                "run_manifest": fixture["run_manifest"],
                "ship_commit": fixture["ship"],
                "bound_branch": fixture["bound_branch"],
                "default_branch": fixture["default_branch"],
                "pre_integration_default_commit": fixture[
                    "pre_integration_default"
                ],
                "integration_commit": fixture["integration"],
                "milestone_tag": fixture["milestone_tag"],
            },
            "worktrees": {
                "primary_worktree": fixture["primary_worktree"],
                "integration_worktree": fixture["integration_worktree"],
                "output": fixture["worktree_output"],
            },
            "guards": {
                "guard_artifact": fixture["artifacts"]["guards"],
                "declared_tier": self.guard_tiers[host],
                "native_guard": (
                    "not-applicable"
                    if self.guard_tiers[host] == "git-only"
                    else "pass"
                ),
                "git_hooks": "pass",
            },
        }
        evidence.update(details[step])
        return evidence

    def receipt(
        self,
        host,
        details=True,
        write_artifacts=True,
        shared_artifact=False,
        **overrides,
    ):
        fields = {
            "schema": "gsd-path/live-evidence/v1",
            "host": host,
            "package": "1.2.3",
            "pipeline": "gsd-path/v2",
            "candidate": self.candidate,
            "verdict": "pass",
            "child_spawn": "pass",
            "state": "pass",
            "task_verify": "pass",
            "wave_review": "pass",
            "final_review": "pass",
            "archive": "pass",
            "integration": "pass",
            "guard_tier": self.guard_tiers[host],
        }
        fields.update(overrides)
        lines = [
            "---",
            *[f"{key}: {value}" for key, value in fields.items()],
            "---",
            "",
            f"# {host} live evidence",
            "",
        ]
        if details:
            lines.extend(
                f"- {label}: verified {host} metadata"
                for label in check_trust_evidence.METADATA_DETAILS
            )
            lines.extend(
                f"- {label}: {host}/"
                f"{'install' if shared_artifact else check_trust_evidence.ARTIFACT_STEPS[label]}.json"
                for label in check_trust_evidence.ARTIFACT_DETAILS
            )
        path = (
            self.repo
            / "docs"
            / "trust-validation"
            / "evidence"
            / "releases"
            / "1.2.3"
            / f"{host}.md"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        if details and write_artifacts:
            for step in check_trust_evidence.ARTIFACT_STEPS.values():
                artifact_step = "install" if shared_artifact else step
                artifact = self.artifact(host, artifact_step)
                artifact.parent.mkdir(parents=True, exist_ok=True)
                if artifact.exists():
                    continue
                artifact.write_text(
                    json.dumps(self.step_evidence(host, step)) + "\n",
                    encoding="utf-8",
                )

    def commit_receipts(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "trust evidence")

    def release_change(self, path, content="changed\n"):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.commit_receipts()
        self.candidate = self.git("rev-parse", "HEAD").stdout.strip()

    def test_reuses_original_receipts_after_version_and_docs_change(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()
        original = self.candidate
        self.release_change("package.json", json.dumps({"version": "1.2.4"}))
        self.release_change("README.md")
        result = check_trust_evidence.validate_repository(self.repo)
        self.assertEqual([], result["required_runs"])
        self.assertEqual(["alpha", "beta"], result["reused_hosts"])
        self.assertEqual(original, result["receipts"]["alpha"]["candidate"])
        self.assertEqual("1.2.3", result["receipts"]["alpha"]["version"])
        self.assertFalse((self.repo / "docs/trust-validation/evidence/releases/1.2.4").exists())

    def test_plan_requires_only_host_with_stale_receipt(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()
        self.release_change("platforms/alpha/dispatch.md")
        result = check_trust_evidence.validate_repository(self.repo, plan=True)
        self.assertEqual(["alpha"], result["required_runs"])
        self.assertEqual(["beta"], list(result["receipts"]))
        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "alpha.*non-evidence"):
            check_trust_evidence.validate_repository(self.repo)
        self.release_change("skills/gsd-path/SKILL.md")
        self.assertEqual(["alpha", "beta"], check_trust_evidence.validate_repository(self.repo, plan=True)["required_runs"])

    def test_plan_cannot_reuse_corrupt_historical_receipt(self):
        self.receipt("alpha", child_spawn="unverifiable")
        self.receipt("beta")
        self.commit_receipts()
        self.release_change("package.json", json.dumps({"version": "1.2.4"}))
        result = check_trust_evidence.validate_repository(self.repo, plan=True)
        self.assertEqual(["alpha"], result["required_runs"])
        self.assertIn("child_spawn", result["reasons"]["alpha"])
        current = self.repo / "docs/trust-validation/evidence/releases/1.2.4/beta.md"
        current.parent.mkdir()
        current.write_text("failed current attempt\n")
        self.commit_receipts()
        result = check_trust_evidence.validate_repository(self.repo, plan=True)
        self.assertEqual(["alpha", "beta"], result["required_runs"])
        self.assertIn("missing frontmatter", result["reasons"]["beta"])

    def test_full_matrix_requires_current_version_receipts(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()
        self.release_change("package.json", json.dumps({"version": "1.2.4"}))
        result = check_trust_evidence.validate_repository(self.repo, plan=True, full=True)
        self.assertEqual(["alpha", "beta"], result["required_runs"])

    def scope(self):
        version = json.loads((self.repo / "package.json").read_text())["version"]
        hosts = list(json.loads((self.repo / "scripts/skill-resources.json").read_text())["hosts"])
        return check_trust_evidence.release_scope(self.repo, version, hosts)

    def test_release_scope_skips_live_runs_for_non_host_changes(self):
        self.git("tag", "v1.2.2")
        for path in ("README.md", "docs/guide.md", "tests/test_example.py",
                     ".github/workflows/release.yml", "daemon/gsd_daemon/serve.py",
                     "scripts/update_release_docs.mjs", "scripts/check_trust_evidence.py"):
            with self.subTest(path=path):
                self.release_change(path)
                result = check_trust_evidence.release_scope(self.repo, "1.2.3", ["alpha", "beta"])
                self.assertEqual([], result["hosts"])
                self.assertEqual("v1.2.2", result["baseline"])

    def test_release_scope_accepts_version_only_package_change(self):
        self.git("tag", "v1.2.2")
        self.release_change("package.json", json.dumps({"version": "1.2.4"}))
        self.assertEqual([], self.scope()["hosts"])
        self.release_change("package.json", json.dumps({"version": "1.2.4", "scripts": {"test": "false"}}))
        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "missing.*alpha, beta"):
            check_trust_evidence.validate_repository(self.repo)

    def test_release_scope_requires_only_changed_host(self):
        self.receipt("beta")
        self.commit_receipts()
        self.git("tag", "v1.2.2")
        self.release_change("platforms/alpha/dispatch.md")
        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "missing host evidence: alpha$"):
            check_trust_evidence.validate_repository(self.repo)
        self.receipt("alpha")
        self.commit_receipts()
        result = check_trust_evidence.validate_repository(self.repo)
        self.assertEqual([], result["required_runs"])
        self.assertIsNone(result["candidate"])  # Independent host candidates are valid.
        self.assertEqual(["alpha"], self.scope()["hosts"])

    def add_api_hosts(self):
        path = self.repo / "scripts/skill-resources.json"
        manifest = json.loads(path.read_text())
        for host in ("qwen", "kiro", "zed"):
            manifest["hosts"][host] = {
                "local_root": f".{host}/skills", "guard_tier": "git-only",
                "child_apis": [f"{host}.spawn"],
            }
        self.release_change("scripts/skill-resources.json", json.dumps(manifest))
        return list(manifest["hosts"])

    def test_release_excludes_api_hosts_but_keeps_install_contracts(self):
        self.add_api_hosts()
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()
        result = check_trust_evidence.validate_repository(self.repo)
        self.assertEqual(["alpha", "beta"], result["hosts"])
        manifest = json.loads((self.repo / "scripts/skill-resources.json").read_text())
        self.assertTrue({"qwen", "kiro", "zed"}.issubset(manifest["hosts"]))

    def test_excluded_host_changes_do_not_select_other_hosts(self):
        self.add_api_hosts()
        self.git("tag", "v1.2.2")
        for host in ("qwen", "kiro", "zed"):
            with self.subTest(host=host):
                self.release_change(f"platforms/{host}/dispatch.md")
                self.assertEqual([], self.scope()["hosts"])
        self.release_change("platforms/unknown/dispatch.md")
        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "missing.*alpha, beta$"):
            check_trust_evidence.validate_repository(self.repo)

    def test_prepare_release_uses_same_evaluation_hosts(self):
        self.prepare_release()

    def test_prepare_release_selects_only_stale_host(self):
        self.prepare_release(affected=True)

    def test_prepare_release_full_matrix_is_explicit(self):
        self.prepare_release(affected=True, full=True)

    def test_prepare_release_does_nothing_when_receipts_are_valid(self):
        self.prepare_release(unchanged=True)

    def prepare_release(self, affected=False, full=False, unchanged=False):
        self.add_api_hosts()
        manifest = (self.repo / "scripts/skill-resources.json").read_text()
        source = Path(__file__).resolve().parents[1]
        shutil.copytree(source / "scripts", self.repo / "scripts", dirs_exist_ok=True)
        (self.repo / "scripts/skill-resources.json").write_text(manifest)
        (self.repo / "tests").mkdir()
        # Preparation is the external boundary; never install or invoke paid hosts.
        (self.repo / "tests/evaluate_host.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            "with Path('prepared-hosts.txt').open('a') as out:\n"
            "    out.write(sys.argv[sys.argv.index('--host') + 1] + '\\n')\n"
        )
        self.git("add", "-A")
        self.git("commit", "-qm", "prepare fixture")
        self.candidate = self.git("rev-parse", "HEAD").stdout.strip()
        if affected or unchanged:
            self.receipt("alpha")
            self.receipt("beta")
            self.commit_receipts()
            if affected:
                self.release_change("platforms/alpha/dispatch.md")
        result = subprocess.run(
            ["bash", str(self.repo / "scripts/prepare_release_evidence.sh"),
             "--candidate", self.git("rev-parse", "HEAD").stdout.strip(),
             "--output-base", str(self.repo.parent / "prepared"), *(["--full"] if full else [])],
            cwd=self.repo, text=True, capture_output=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        if unchanged:
            self.assertFalse((self.repo / "prepared-hosts.txt").exists())
            self.assertIn("no new runs needed", result.stdout)
        else:
            self.assertEqual(["alpha"] if affected and not full else ["alpha", "beta"],
                             (self.repo / "prepared-hosts.txt").read_text().splitlines())

    def test_release_scope_lockfile_exempts_only_package_version(self):
        lock = {"version": "1.2.2", "packages": {"": {"version": "1.2.2"},
                "node_modules/example": {"version": "1.0.0"}}}
        self.release_change("package-lock.json", json.dumps(lock))
        self.git("tag", "v1.2.2")
        lock["version"] = lock["packages"][""]["version"] = "1.2.3"
        self.release_change("package-lock.json", json.dumps(lock))
        self.assertEqual([], self.scope()["hosts"])
        lock["packages"]["node_modules/example"]["version"] = "2.0.0"
        self.release_change("package-lock.json", json.dumps(lock))
        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "missing.*alpha, beta"):
            check_trust_evidence.validate_repository(self.repo)

    def test_release_scope_shared_adapter_requires_all_hosts(self):
        self.git("tag", "v1.2.2")
        self.release_change("platforms/shared-agents/dispatch.md")
        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "missing.*alpha, beta"):
            check_trust_evidence.validate_repository(self.repo)

    def test_release_scope_new_lockfile_requires_all_hosts(self):
        self.git("tag", "v1.2.2")
        self.release_change("package-lock.json", json.dumps({"version": "1.2.3"}))
        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "missing.*alpha, beta"):
            check_trust_evidence.validate_repository(self.repo)

    def test_release_scope_current_tag_does_not_hide_shared_changes(self):
        self.git("tag", "v1.2.2")
        self.release_change("skills/gsd-path/SKILL.md")
        self.git("tag", "v1.2.3")
        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "missing.*alpha, beta"):
            check_trust_evidence.validate_repository(self.repo)

    def test_release_scope_unknown_changes_require_all_hosts(self):
        self.git("tag", "v1.2.2")
        self.release_change("new-runtime.py")
        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "missing.*alpha, beta"):
            check_trust_evidence.validate_repository(self.repo)

    def test_release_scope_rename_cannot_hide_shared_contract_deletion(self):
        self.release_change("WORKFLOW.md")
        self.git("tag", "v1.2.2")
        self.git("mv", "WORKFLOW.md", "README.md")
        self.commit_receipts()
        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "missing.*alpha, beta"):
            check_trust_evidence.validate_repository(self.repo)

    @mock.patch.dict(
        "os.environ",
        {
            "GIT_AUTHOR_DATE": "2026-08-31T13:25:19+00:00",
            "GIT_COMMITTER_DATE": "2026-08-31T13:25:19+00:00",
        },
    )
    def test_accepts_complete_current_evidence(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()

        result = check_trust_evidence.validate_repository(self.repo)

        self.assertEqual(["alpha", "beta"], result["hosts"])
        self.assertEqual(self.candidate, result["candidate"])

    def test_rejects_noncanonical_landing_in_shared_history(self):
        self.shared_history_groups["alpha"] = ("alpha", "beta")
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError,
            "landing_commit is not one canonically proven task landing",
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_one_landing_reused_for_multiple_hosts(self):
        self.shared_history_groups["alpha"] = ("alpha", "beta")
        self.shared_landing_groups.add("alpha")
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "share one landing commit"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_missing_host_receipt(self):
        self.receipt("alpha")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "missing.*beta"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_partial_or_top_level_only_evidence(self):
        self.receipt("alpha", child_spawn="unverifiable")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "child_spawn"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_simulated_child_spawn_evidence(self):
        self.receipt("alpha")
        self.receipt("beta")
        child_spawn = self.artifact("alpha", "child-spawn")
        evidence = json.loads(child_spawn.read_text(encoding="utf-8"))
        evidence["command"] = "echo simulated"
        evidence["output"] = {
            "child_id": evidence["child_id"],
            "status": "completed",
        }
        child_spawn.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError,
            "child-spawn command must name child_api",
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_child_id_not_bound_to_task_landing(self):
        self.fixture_manifest_overrides["alpha"] = {
            "child_id": "simulated-child"
        }
        self.receipt("alpha")
        self.receipt("beta")
        child_spawn = self.artifact("alpha", "child-spawn")
        evidence = json.loads(child_spawn.read_text(encoding="utf-8"))
        evidence["child_id"] = "simulated-child"
        evidence["output"] = {
            "child_id": "simulated-child",
            "status": "completed",
        }
        child_spawn.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError,
            "child_id does not own the proven task landing",
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_landing_commit_equal_to_ship_commit(self):
        self.receipt("alpha")
        self.receipt("beta")
        landing = self.artifact("alpha", "task-landing")
        evidence = json.loads(landing.read_text(encoding="utf-8"))
        evidence["landing_commit"] = self.fixtures["alpha"]["ship"]
        landing.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError,
            "landing commit must precede ship commit",
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_frontmatter_only_receipt(self):
        self.receipt("alpha", details=False)
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "missing reproducible evidence detail"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_missing_evidence_artifact(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.artifact("alpha", "install").unlink()
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "invalid evidence artifact"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_empty_evidence_artifact(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.artifact("alpha", "install").write_text("", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "invalid evidence artifact"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_untracked_release_input(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()
        (self.repo / "untracked.txt").write_text("not tested\n", encoding="utf-8")

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "clean worktree"):
            check_trust_evidence.validate_repository(self.repo)

    def artifact(self, host, step):
        return (
            self.repo
            / "docs"
            / "trust-validation"
            / "evidence"
            / "releases"
            / "1.2.3"
            / host
            / f"{step}.json"
        )

    def test_rejects_one_artifact_reused_for_every_step(self):
        self.receipt("alpha", shared_artifact=True)
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "own artifact"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_unstructured_step_evidence(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.artifact("alpha", "install").write_text("{}\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "schema"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_generic_attestations_without_step_proof(self):
        self.receipt("alpha")
        self.receipt("beta")
        for step in check_trust_evidence.ARTIFACT_STEPS.values():
            self.artifact("alpha", step).write_text(
                json.dumps(
                    {
                        "schema": check_trust_evidence.STEP_SCHEMA,
                        "host": "alpha",
                        "step": step,
                        "command": "x",
                        "result": "pass",
                        "output": "x",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "step evidence requires"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_integration_commit_that_is_not_a_merge(self):
        self.receipt("alpha")
        self.receipt("beta")
        integration = self.artifact("alpha", "integration")
        evidence = json.loads(integration.read_text(encoding="utf-8"))
        evidence["integration_commit"] = self.fixtures["alpha"]["landing"]
        integration.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
        worktrees = self.artifact("alpha", "worktrees")
        evidence = json.loads(worktrees.read_text(encoding="utf-8"))
        evidence["output"] = evidence["output"].replace(
            self.fixtures["alpha"]["integration"], self.fixtures["alpha"]["landing"]
        )
        worktrees.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "integration commit subject"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_integration_that_merged_an_unrelated_branch(self):
        self.unrelated_integration_hosts.add("alpha")
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError,
            "canonical merge of the ship commit",
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_blocked_canonical_final_review(self):
        self.blocked_final_hosts.add("alpha")
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "final review did not pass"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_missing_artifact_claimed_by_bundled_run(self):
        missing = ".project/STATE.md"
        self.omit_fixture_artifact["alpha"] = missing
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "missing real state file"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_bundled_state_missing_canonical_fields(self):
        self.fixture_states["alpha"] = (
            "---\npipeline: gsd-path/v2\nphase: shipped\nstatus: done\n---\n"
        )
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "STATE.md is invalid"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_evidence_steps_from_different_runs(self):
        self.receipt("alpha")
        self.receipt("beta")
        router = self.artifact("alpha", "router")
        evidence = json.loads(router.read_text(encoding="utf-8"))
        evidence["run_id"] = "another-run"
        router.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "one run_id"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_bundled_run_for_different_candidate(self):
        self.fixture_manifest_overrides["alpha"] = {"candidate": "0" * 40}
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "run manifest candidate"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_bundled_run_for_different_package(self):
        self.fixture_manifest_overrides["alpha"] = {"package_version": "0.0.1"}
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "run manifest package_version"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_unstructured_worktree_output(self):
        self.receipt("alpha")
        self.receipt("beta")
        worktrees = self.artifact("alpha", "worktrees")
        evidence = json.loads(worktrees.read_text(encoding="utf-8"))
        evidence["output"] = "still registered"
        worktrees.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "git worktree porcelain"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_registered_task_worktree(self):
        self.receipt("alpha")
        self.receipt("beta")
        fixture = self.fixtures["alpha"]
        worktrees = self.artifact("alpha", "worktrees")
        evidence = json.loads(worktrees.read_text(encoding="utf-8"))
        evidence["output"] += (
            f"\nworktree {fixture['task_worktree']}\n"
            f"HEAD {fixture['landing']}\n"
            f"branch refs/heads/{fixture['task_branch']}\n"
        )
        worktrees.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "task worktree was not retired"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_registered_integration_worktree(self):
        self.receipt("alpha")
        self.receipt("beta")
        fixture = self.fixtures["alpha"]
        worktrees = self.artifact("alpha", "worktrees")
        evidence = json.loads(worktrees.read_text(encoding="utf-8"))
        evidence["output"] += (
            f"\nworktree {fixture['integration_worktree']}\n"
            f"HEAD {fixture['integration']}\n"
            "branch refs/heads/gsd-path-integrate/M001\n"
        )
        worktrees.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError,
            "integration worktree was not retired",
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_primary_worktree_without_named_branch(self):
        self.receipt("alpha")
        self.receipt("beta")
        worktrees = self.artifact("alpha", "worktrees")
        evidence = json.loads(worktrees.read_text(encoding="utf-8"))
        evidence["output"] = evidence["output"].replace(
            "branch refs/heads/gsd-path/M001", "bare"
        )
        worktrees.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "must be on the bound branch"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_unretired_task_branch(self):
        self.keep_fixture_branches.add("alpha")
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "task branch was not retired"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_guard_tier_that_disagrees_with_manifest(self):
        self.receipt("alpha", guard_tier="git-only")
        self.receipt("beta")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "guard_tier"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_ignored_untracked_evidence(self):
        (self.repo / ".gitignore").write_text(
            "docs/trust-validation/evidence/\n", encoding="utf-8"
        )
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "ignore evidence")
        self.candidate = self.git("rev-parse", "HEAD").stdout.strip()
        self.receipt("alpha")
        self.receipt("beta")

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "not tracked"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_artifacts_bound_to_older_candidate(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()
        (self.repo / "candidate.txt").write_text("new candidate\n", encoding="utf-8")
        self.git("add", "candidate.txt")
        self.git("commit", "-qm", "new candidate")
        self.candidate = self.git("rev-parse", "HEAD").stdout.strip()
        self.receipt("alpha", write_artifacts=False)
        self.receipt("beta", write_artifacts=False)
        self.commit_receipts()

        with self.assertRaisesRegex(
            check_trust_evidence.EvidenceError, "install candidate does not match receipt"
        ):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_unstaged_release_input(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()
        (self.repo / "package.json").write_text('{"version": "9.9.9"}\n', encoding="utf-8")

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "clean worktree"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_staged_release_input(self):
        self.receipt("alpha")
        self.receipt("beta")
        self.commit_receipts()
        (self.repo / "staged.txt").write_text("not tested\n", encoding="utf-8")
        self.git("add", "staged.txt")

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "clean worktree"):
            check_trust_evidence.validate_repository(self.repo)

    def test_rejects_non_evidence_changes_after_candidate(self):
        self.receipt("alpha")
        self.receipt("beta")
        (self.repo / "product.py").write_text("changed\n", encoding="utf-8")
        self.commit_receipts()

        with self.assertRaisesRegex(check_trust_evidence.EvidenceError, "non-evidence"):
            check_trust_evidence.validate_repository(self.repo)

    def test_accepts_evaluation_policy_changes_after_candidate(self):
        self.receipt("alpha")
        self.receipt("beta")
        for name in ("scripts/check_trust_evidence.py", "scripts/prepare_release_evidence.sh",
                     "tests/test_trust_evidence.py", "RELEASE.md",
                     "docs/trust-validation/TRUST-VALIDATION-SPEC.md"):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("changed evaluation policy\n", encoding="utf-8")
        self.commit_receipts()
        self.assertEqual(["alpha", "beta"], check_trust_evidence.validate_repository(self.repo)["hosts"])


if __name__ == "__main__":
    unittest.main()
