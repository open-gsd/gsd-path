import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon import atlas

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gsd-atlas"


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    run_git(root, "init", "-b", "main", str(repo))
    run_git(repo, "config", "user.name", "GSD Path Test")
    run_git(repo, "config", "user.email", "test@example.com")
    (repo / "file.txt").write_text("demo\n", encoding="utf-8")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "fixture")
    return repo


def load_fixture(name: str) -> dict:
    import json

    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class AtlasStoreDiscoveryTests(unittest.TestCase):
    def test_repo_without_a_store_discovers_none(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = make_repo(Path(temporary))
            self.assertIsNone(atlas.discover_store(str(repo)))

    def test_store_in_the_git_common_dir_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = make_repo(Path(temporary))
            store = repo / ".git" / "gsd-atlas"
            store.mkdir()
            (store / "facts.db").write_bytes(b"")
            self.assertEqual(atlas.discover_store(str(repo)), str(store.resolve()))

    def test_worktrees_share_the_main_checkout_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = make_repo(root)
            store = repo / ".git" / "gsd-atlas"
            store.mkdir()
            (store / "facts.db").write_bytes(b"")
            worktree = root / "linked"
            run_git(repo, "worktree", "add", str(worktree), "-b", "feature")
            self.assertEqual(atlas.discover_store(str(worktree)), str(store.resolve()))

    def test_non_git_directory_discovers_none(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plain = Path(temporary) / "plain"
            plain.mkdir()
            self.assertIsNone(atlas.discover_store(str(plain)))

    def test_empty_store_folder_is_not_a_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = make_repo(Path(temporary))
            (repo / ".git" / "gsd-atlas").mkdir()
            self.assertIsNone(atlas.discover_store(str(repo)))

    def test_symlinked_store_directory_is_not_the_default_store(self) -> None:
        # gsd-atlas relocates a symlinked store to its cache fallback
        # (src/fact-store/location.ts); the default location has no store then.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = make_repo(root)
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            (elsewhere / "facts.db").write_bytes(b"")
            link = repo / ".git" / "gsd-atlas"
            link.symlink_to(elsewhere, target_is_directory=True)
            self.assertIsNone(atlas.discover_store(str(repo)))

    def test_symlinked_facts_db_is_not_the_default_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = make_repo(root)
            store = repo / ".git" / "gsd-atlas"
            store.mkdir()
            target = root / "facts.db"
            target.write_bytes(b"")
            (store / "facts.db").symlink_to(target)
            self.assertIsNone(atlas.discover_store(str(repo)))


class AtlasHealthInterpretationTests(unittest.TestCase):
    def test_missing_binary_is_not_installed(self) -> None:
        result = atlas.interpret_health(None, exit_code=None, binary_present=False)
        self.assertEqual(result["state"], atlas.STATE_NOT_INSTALLED)

    def test_exit_three_is_busy_not_an_error(self) -> None:
        result = atlas.interpret_health(None, exit_code=3, binary_present=True)
        self.assertEqual(result["state"], atlas.STATE_BUSY)

    def test_follower_alone_is_ok(self) -> None:
        envelope = load_fixture("health-degraded-follower.json")
        result = atlas.interpret_health(envelope, exit_code=0, binary_present=True)
        self.assertEqual(result["state"], atlas.STATE_OK)
        self.assertEqual(result["health"], "degraded")
        self.assertEqual(result["reasons"], ["follower"])

    def test_degraded_beyond_follower_stays_degraded(self) -> None:
        envelope = load_fixture("health-degraded-follower.json")
        envelope["data"]["reasons"] = ["follower", "stale_files"]
        result = atlas.interpret_health(envelope, exit_code=0, binary_present=True)
        self.assertEqual(result["state"], atlas.STATE_DEGRADED)

    def test_healthy_envelope_is_ok(self) -> None:
        envelope = load_fixture("health-ok-writer-lease.json")
        result = atlas.interpret_health(envelope, exit_code=0, binary_present=True)
        self.assertEqual(result["state"], atlas.STATE_OK)
        self.assertEqual(result["health"], "ok")

    def test_not_indexed_error_envelope_is_not_indexed(self) -> None:
        envelope = load_fixture("health-not-indexed.json")
        result = atlas.interpret_health(envelope, exit_code=2, binary_present=True)
        self.assertEqual(result["state"], atlas.STATE_NOT_INDEXED)

    def test_lease_held_error_envelope_is_busy(self) -> None:
        envelope = load_fixture("health-not-indexed.json")
        envelope["diagnostics"][0]["code"] = "lease_held"
        result = atlas.interpret_health(envelope, exit_code=3, binary_present=True)
        self.assertEqual(result["state"], atlas.STATE_BUSY)

    def test_schema_too_new_error_envelope_is_unsupported(self) -> None:
        envelope = load_fixture("health-not-indexed.json")
        envelope["diagnostics"][0]["code"] = "schema_too_new"
        result = atlas.interpret_health(envelope, exit_code=2, binary_present=True)
        self.assertEqual(result["state"], atlas.STATE_UNSUPPORTED)

    def test_other_error_envelope_is_unavailable(self) -> None:
        envelope = load_fixture("health-not-indexed.json")
        envelope["diagnostics"][0]["code"] = "store_unavailable"
        result = atlas.interpret_health(envelope, exit_code=2, binary_present=True)
        self.assertEqual(result["state"], atlas.STATE_UNAVAILABLE)

    def test_unknown_success_schema_is_unsupported_version(self) -> None:
        envelope = load_fixture("health-ok-writer-lease.json")
        envelope["schema"] = "gsd-atlas.atlas-status/2"
        result = atlas.interpret_health(envelope, exit_code=0, binary_present=True)
        self.assertEqual(result["state"], atlas.STATE_UNSUPPORTED)

    def test_other_failure_without_an_envelope_is_unavailable(self) -> None:
        result = atlas.interpret_health(None, exit_code=1, binary_present=True)
        self.assertEqual(result["state"], atlas.STATE_UNAVAILABLE)


class AtlasFixtureContractTests(unittest.TestCase):
    def test_health_fixtures_carry_the_published_envelope_shapes(self) -> None:
        for name in (
            "health-ok-writer-lease.json",
            "health-degraded-follower.json",
        ):
            with self.subTest(fixture=name):
                envelope = load_fixture(name)
                self.assertEqual(envelope["schema"], atlas.HEALTH_SCHEMA)
                data = envelope["data"]
                for field in ("worktrees", "store", "indexer", "tiers", "health", "reasons"):
                    self.assertIn(field, data)
                for worktree in data["worktrees"]:
                    self.assertIn("worktree", worktree)
                    self.assertIn("seq", worktree)
                    self.assertIn("staleCount", worktree)
                self.assertIn("sizeBytes", data["store"])
                self.assertIn("writerLeaseHeld", data["store"])
                self.assertIn("failed", data["indexer"])
                self.assertIsInstance(data["indexer"]["lastIndexedAt"], (int, type(None)))
                for tier in data["tiers"]:
                    self.assertIn("module", tier)

    def test_error_fixture_carries_the_error_schema_and_diagnostics(self) -> None:
        envelope = load_fixture("health-not-indexed.json")
        self.assertEqual(envelope["schema"], atlas.ERROR_SCHEMA)
        self.assertIs(envelope["ok"], False)
        self.assertEqual(envelope["diagnostics"][0]["code"], "not_indexed")

    def test_status_fixture_documents_the_answer_inflation_probe(self) -> None:
        envelope = load_fixture("status-answers.json")
        self.assertEqual(envelope["schema"], atlas.STATUS_SCHEMA)
        answers = envelope["data"]["report"]["answers"]
        self.assertEqual(answers["total"], 3)
        self.assertEqual(answers["byTool"], {"atlas_status": 3})


if __name__ == "__main__":
    unittest.main()
