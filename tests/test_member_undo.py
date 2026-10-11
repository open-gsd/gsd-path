import unittest
from contextlib import contextmanager
from unittest import mock

import tests.test_member_landing as landing
from scripts import isolation, pipeline_undo

git = landing.git


class MemberUndoTests(unittest.TestCase):
    setUp = landing.MemberLandingTests.setUp
    tearDown = landing.MemberLandingTests.tearDown
    land = landing.MemberLandingTests.land
    edit = landing.MemberLandingTests.edit
    bound_tip = landing.MemberLandingTests.bound_tip
    journal = landing.MemberLandingTests.journal

    def landed(self) -> dict:
        self.edit()
        return self.land()

    def test_member_record_undo_resets_the_member_landing_then_the_record(self) -> None:
        result = self.landed()
        target = pipeline_undo.preview(self.coordinator)["target"]
        self.assertEqual((target["kind"], target["member"], target["landing"]),
                         ("member-task", "web", result["landing"]))
        pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), self.base)
        self.assertEqual(self.bound_tip(), self.member_base)
        self.assertEqual(git(self.bound, "status", "--porcelain"), "")

    def test_interrupted_member_undo_resumes_after_the_member_reset(self) -> None:
        result = self.landed()
        with mock.patch.object(pipeline_undo, "_reset_to", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(self.bound_tip(), self.member_base)
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), result["commit"])
        pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), self.base)

    def test_member_journal_is_valid_on_its_first_write(self) -> None:
        result = self.landed()
        write = pipeline_undo._write_json
        writes = []

        def checked_write(path, value):
            write(path, value)
            writes.append(pipeline_undo.pending_transaction(self.coordinator))

        with mock.patch.object(pipeline_undo, "_write_json", side_effect=checked_write):
            pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["landing"], result["landing"])

    def test_member_undo_resumes_after_coordinator_reset(self) -> None:
        result = self.landed()
        reset = pipeline_undo._reset_to

        def reset_then_crash(repo, parent):
            reset(repo, parent)
            raise OSError("crash after coordinator reset")

        with mock.patch.object(pipeline_undo, "_reset_to", side_effect=reset_then_crash):
            with self.assertRaises(OSError):
                pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), self.base)
        self.assertIsNotNone(pipeline_undo.pending_transaction(self.coordinator))
        pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertIsNone(pipeline_undo.pending_transaction(self.coordinator))

    def test_resume_blocks_landing_published_to_origin_main(self) -> None:
        self._assert_resume_blocks_published_landing("refs/remotes/origin/main")

    def test_resume_blocks_landing_published_to_remote_bound_branch(self) -> None:
        branch = git(self.bound, "symbolic-ref", "--short", "HEAD")
        self._assert_resume_blocks_published_landing(f"refs/remotes/origin/{branch}")

    def test_resume_after_member_reset_blocks_origin_main_publication(self) -> None:
        self._assert_reset_member_resume_blocks_publication("refs/remotes/origin/main")

    def test_resume_after_member_reset_blocks_remote_bound_publication(self) -> None:
        branch = git(self.bound, "symbolic-ref", "--short", "HEAD")
        self._assert_reset_member_resume_blocks_publication(f"refs/remotes/origin/{branch}")

    def _assert_reset_member_resume_blocks_publication(self, ref: str) -> None:
        result = self.landed()
        with mock.patch.object(pipeline_undo, "_reset_to", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(self.bound_tip(), self.member_base)
        git(self.member, "update-ref", ref, result["landing"])
        with self.assertRaisesRegex(pipeline_undo.UndoError, "already on"):
            pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), result["commit"])

    def test_lock_rechecks_target_before_writing_journal(self) -> None:
        result = self.landed()

        @contextmanager
        def moved_before_lock(_repo):
            (self.bound / "extra.txt").write_text("later\n", encoding="utf-8")
            git(self.bound, "add", "extra.txt")
            git(self.bound, "commit", "-q", "--no-verify", "-m", "later landing")
            yield

        with mock.patch.object(isolation, "_member_landing_lock", moved_before_lock):
            with self.assertRaisesRegex(pipeline_undo.UndoError, "target changed"):
                pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertIsNone(pipeline_undo.pending_transaction(self.coordinator))
        self.assertNotEqual(self.bound_tip(), result["landing"])

    def test_pending_landing_journal_blocks_preview_apply_and_resume(self) -> None:
        result = self.landed()
        self.journal().write_text("{}", encoding="utf-8")
        target = pipeline_undo.preview(self.coordinator)["target"]
        self.assertIsNone(target["kind"])
        self.assertIn("member landing journal", " ".join(target["blocked"]))
        self.journal().unlink()

        @contextmanager
        def journal_appears(_repo):
            self.journal().write_text("{}", encoding="utf-8")
            yield

        with mock.patch.object(isolation, "_member_landing_lock", journal_appears):
            with self.assertRaisesRegex(pipeline_undo.UndoError, "member landing journal"):
                pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertIsNone(pipeline_undo.pending_transaction(self.coordinator))
        self.journal().unlink()

        with mock.patch.object(pipeline_undo, "_undo_member_landing", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.journal().write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(pipeline_undo.UndoError, "member landing journal"):
            pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(self.bound_tip(), result["landing"])
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), result["commit"])

    def test_moved_coordinator_blocks_before_member_reset(self) -> None:
        result = self.landed()
        prepare = pipeline_undo._prepare_transaction

        def prepare_then_move(*args, **kwargs):
            transaction = prepare(*args, **kwargs)
            git(self.coordinator, "commit", "-q", "--allow-empty", "--no-verify", "-m", "later record")
            return transaction

        with mock.patch.object(pipeline_undo, "_prepare_transaction", side_effect=prepare_then_move):
            with self.assertRaisesRegex(pipeline_undo.UndoError, "HEAD moved"):
                pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(self.bound_tip(), result["landing"])
        self.assertIsNotNone(pipeline_undo.pending_transaction(self.coordinator))

    def _assert_resume_blocks_published_landing(self, ref: str) -> None:
        result = self.landed()
        with mock.patch.object(pipeline_undo, "_undo_member_landing", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        git(self.member, "update-ref", ref, result["landing"])
        with self.assertRaisesRegex(pipeline_undo.UndoError, "already on"):
            pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(self.bound_tip(), result["landing"])
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), result["commit"])

    def test_member_and_coordinator_resets_hold_landing_lock(self) -> None:
        result = self.landed()
        locked = False
        observed = []
        run_git = pipeline_undo._run_git
        reset = pipeline_undo._reset_to

        @contextmanager
        def lock(_repo):
            nonlocal locked
            locked = True
            try:
                yield
            finally:
                locked = False

        def checked_git(repo, *args, **kwargs):
            if repo == self.bound and args[:2] == ("reset", "--hard"):
                observed.append("member")
                self.assertTrue(locked)
            return run_git(repo, *args, **kwargs)

        def checked_reset(repo, parent):
            observed.append("coordinator")
            self.assertTrue(locked)
            return reset(repo, parent)

        with mock.patch.object(isolation, "_member_landing_lock", lock), \
             mock.patch.object(pipeline_undo, "_run_git", side_effect=checked_git), \
             mock.patch.object(pipeline_undo, "_reset_to", side_effect=checked_reset):
            pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(observed, ["member", "coordinator"])

    def test_member_landing_on_origin_main_is_not_undone(self) -> None:
        result = self.landed()
        git(self.member, "update-ref", "refs/remotes/origin/main", result["landing"])
        target = pipeline_undo.preview(self.coordinator)["target"]
        self.assertIsNone(target["kind"])
        self.assertRegex(" ".join(target["blocked"]), "origin/main")
        self.assertEqual(self.bound_tip(), result["landing"])

    def test_member_bound_branch_moved_past_the_landing_blocks(self) -> None:
        result = self.landed()
        (self.bound / "extra.txt").write_text("x\n", encoding="utf-8")
        git(self.bound, "add", "-A")
        git(self.bound, "commit", "-q", "--no-verify", "-m", "extra")
        tip = self.bound_tip()
        target = pipeline_undo.preview(self.coordinator)["target"]
        self.assertIsNone(target["kind"])
        self.assertRegex(" ".join(target["blocked"]), "moved")
        self.assertEqual(self.bound_tip(), tip)


class MasterMemberUndoTests(unittest.TestCase):
    """Undo checks publication against the default branch that MEMBERS.md records."""
    member_default = "master"
    setUp = landing.MemberLandingTests.setUp
    tearDown = landing.MemberLandingTests.tearDown
    land = landing.MemberLandingTests.land
    edit = landing.MemberLandingTests.edit
    bound_tip = landing.MemberLandingTests.bound_tip
    landed = MemberUndoTests.landed

    def test_unpublished_landing_of_a_master_member_is_undone(self) -> None:
        result = self.landed()
        pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), self.base)
        self.assertEqual(self.bound_tip(), self.member_base)

    def test_landing_on_the_recorded_default_branch_is_not_undone(self) -> None:
        result = self.landed()
        git(self.member, "update-ref", "refs/remotes/origin/master", result["landing"])
        target = pipeline_undo.preview(self.coordinator)["target"]
        self.assertIsNone(target["kind"])
        self.assertRegex(" ".join(target["blocked"]), "landing is already on origin/master")
        with self.assertRaisesRegex(pipeline_undo.UndoError, "already on origin/master"):
            pipeline_undo.apply_undo(self.coordinator, "member-task", result["commit"])
        self.assertEqual(self.bound_tip(), result["landing"])


if __name__ == "__main__":
    unittest.main()
