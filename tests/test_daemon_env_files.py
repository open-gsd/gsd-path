"""The app edits a project's .env files through the daemon. Values stay masked."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon import env_files
from gsd_daemon.model import ProjectStatus

SOURCE = """# Database
DATABASE_URL=postgres://localhost/app
export API_KEY="s3cret value"
EMPTY=

  # indented comment
SINGLE='it''s'
not a variable line
MULTI="line one\\nline two"
"""


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def write(self, name=".env", text=SOURCE):
        (self.root / name).write_bytes(text.encode("utf-8"))

    def text(self, name=".env"):
        return (self.root / name).read_bytes().decode("utf-8")


class ReadTests(Case):
    def test_list_names_every_variable_and_no_value(self):
        self.write()
        listing = env_files.list_file(self.root, ".env")
        self.assertEqual(listing["exists"], True)
        self.assertEqual([item["name"] for item in listing["vars"]],
                         ["DATABASE_URL", "API_KEY", "EMPTY", "SINGLE", "MULTI"])
        self.assertNotIn("s3cret", repr(listing))
        self.assertNotIn("postgres", repr(listing))
        # The page shows an empty value as empty, not as a masked secret.
        self.assertEqual({item["name"]: item["empty"] for item in listing["vars"]}["EMPTY"], True)
        self.assertEqual({item["name"]: item["empty"] for item in listing["vars"]}["API_KEY"], False)

    def test_reveal_returns_one_value_without_its_quotes(self):
        self.write()
        self.assertEqual(env_files.reveal(self.root, ".env", "API_KEY"), "s3cret value")
        self.assertEqual(env_files.reveal(self.root, ".env", "DATABASE_URL"), "postgres://localhost/app")
        self.assertEqual(env_files.reveal(self.root, ".env", "MULTI"), "line one\nline two")
        self.assertEqual(env_files.reveal(self.root, ".env", "EMPTY"), "")
        with self.assertRaises(ValueError):
            env_files.reveal(self.root, ".env", "MISSING")

    def test_a_missing_file_lists_as_empty(self):
        self.assertEqual(env_files.list_file(self.root, ".env.local"),
                         {"file": ".env.local", "exists": False, "git": "untracked", "vars": []})

    def test_only_the_four_env_files_can_be_named(self):
        for name in ("../.env", ".env.staging", "package.json", "/etc/passwd", ".env/../x"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                env_files.list_file(self.root, name)

    def test_a_link_is_refused(self):
        outside = self.root / "outside.txt"
        outside.write_text("SECRET=1\n", encoding="utf-8")
        os.symlink(outside, self.root / ".env")
        with self.assertRaises(ValueError):
            env_files.list_file(self.root, ".env")
        with self.assertRaises(ValueError):
            env_files.save(self.root, ".env", [{"name": "A", "value": "1"}])
        self.assertEqual(outside.read_text(encoding="utf-8"), "SECRET=1\n")


class QuotedValueTests(Case):
    PEM = "-----BEGIN KEY-----\nAbCd12==\nEfGh34==\n-----END KEY-----"
    SPANS = ('FIRST=1\nPRIVATE_KEY="' + PEM + '" # prod key\n'
             "NOTE='line one\nB=not a variable'\nLAST=2\n")

    def test_a_comment_after_the_closing_quote_is_not_part_of_the_value(self):
        self.write(text='API_KEY="abc" # prod key\nSINGLE=\'a # b\' # note\nBLANK="" # x\nHASH="a#b"#c\n')
        self.assertEqual(env_files.reveal(self.root, ".env", "API_KEY"), "abc")
        self.assertEqual(env_files.reveal(self.root, ".env", "SINGLE"), "a # b")
        self.assertEqual(env_files.reveal(self.root, ".env", "HASH"), "a#b")
        empty = {item["name"]: item["empty"] for item in env_files.list_file(self.root, ".env")["vars"]}
        self.assertEqual(empty, {"API_KEY": False, "SINGLE": False, "BLANK": True, "HASH": False})
        self.assertEqual(env_files.save(self.root, ".env", [{"name": "API_KEY", "value": "abc"}])["diff"], [])

    def test_a_value_that_spans_lines_is_one_variable(self):
        self.write(text=self.SPANS)
        listing = env_files.list_file(self.root, ".env")
        self.assertEqual([item["name"] for item in listing["vars"]], ["FIRST", "PRIVATE_KEY", "NOTE", "LAST"])
        self.assertEqual(env_files.reveal(self.root, ".env", "PRIVATE_KEY"), self.PEM)
        self.assertEqual(env_files.reveal(self.root, ".env", "NOTE"), "line one\nB=not a variable")
        with self.assertRaises(ValueError):
            env_files.reveal(self.root, ".env", "AbCd12")

    def test_a_change_replaces_the_whole_span_and_keeps_every_other_byte(self):
        self.write(text=self.SPANS)
        result = env_files.save(self.root, ".env", [{"name": "PRIVATE_KEY", "value": "short"},
                                                    {"name": "NOTE", "value": "line one\nB=not a variable"}])
        self.assertEqual(result["diff"], [{"name": "PRIVATE_KEY", "change": "change"}])
        self.assertEqual(self.text(), "FIRST=1\nPRIVATE_KEY=short\nNOTE='line one\nB=not a variable'\nLAST=2\n")

    def test_a_remove_deletes_the_whole_span_and_keeps_every_other_byte(self):
        self.write(text=self.SPANS)
        env_files.save(self.root, ".env", [{"name": "PRIVATE_KEY", "remove": True}])
        self.assertEqual(self.text(), "FIRST=1\nNOTE='line one\nB=not a variable'\nLAST=2\n")

    def test_a_quote_that_does_not_close_is_refused_by_name_without_a_value(self):
        for text in ('A=1\nKEY="hunter2-secret\nB=2\n', "KEY='hunter2-secret\nB=2\n",
                     'KEY="hunter2-secret\nmore" junk\nB=2\n'):
            self.write(text=text)
            calls = (lambda: env_files.list_file(self.root, ".env"),
                     lambda: env_files.reveal(self.root, ".env", "B"),
                     lambda: env_files.save(self.root, ".env", [{"name": "B", "value": "3"}]),
                     lambda: env_files.save(self.root, ".env", [{"name": "KEY", "remove": True}]))
            for call in calls:
                with self.subTest(text=text), self.assertRaises(ValueError) as raised:
                    call()
                self.assertIn("KEY", str(raised.exception))
                self.assertNotIn("hunter2", str(raised.exception))
            self.assertEqual(self.text(), text)


class SaveTests(Case):
    def test_dry_run_reports_the_diff_and_writes_nothing(self):
        self.write()
        result = env_files.save(self.root, ".env", [
            {"name": "API_KEY", "value": "new"}, {"name": "ADDED", "value": "1"},
            {"name": "EMPTY", "remove": True}, {"name": "DATABASE_URL", "value": "postgres://localhost/app"},
        ], dry_run=True)
        self.assertEqual(result, {"written": False, "diff": [
            {"name": "API_KEY", "change": "change"}, {"name": "ADDED", "change": "add"},
            {"name": "EMPTY", "change": "remove"}]})
        self.assertEqual(self.text(), SOURCE)

    def test_save_changes_only_the_named_lines(self):
        self.write()
        env_files.save(self.root, ".env", [
            {"name": "API_KEY", "value": "new value # with hash"}, {"name": "ADDED", "value": "plain"},
            {"name": "EMPTY", "remove": True}])
        self.assertEqual(self.text(), SOURCE
                         .replace('export API_KEY="s3cret value"', "export API_KEY='new value # with hash'")
                         .replace("EMPTY=\n", "") + "ADDED=plain\n")
        self.assertEqual(env_files.reveal(self.root, ".env", "API_KEY"), "new value # with hash")

    def test_values_round_trip(self):
        for value in ("plain", "", "two words", 'quote " inside', "back\\slash", "line\nbreak", "tab\there",
                      "$HOME", "'single'", "trailing ", "#hash", "a=b"):
            with self.subTest(value=value):
                env_files.save(self.root, ".env.local", [{"name": "VALUE", "value": value}])
                self.assertEqual(env_files.reveal(self.root, ".env.local", "VALUE"), value)
                self.assertEqual(self.text(".env.local").count("\n"), 1)  # one variable, one line

    def test_a_new_file_is_private_and_an_existing_mode_is_kept(self):
        env_files.save(self.root, ".env.local", [{"name": "A", "value": "1"}])
        self.assertEqual(self.text(".env.local"), "A=1\n")
        if os.name != "nt":
            self.assertEqual((self.root / ".env.local").stat().st_mode & 0o777, 0o600)
            self.write()
            os.chmod(self.root / ".env", 0o644)
            env_files.save(self.root, ".env", [{"name": "A", "value": "1"}])
            self.assertEqual((self.root / ".env").stat().st_mode & 0o777, 0o644)

    def test_a_file_without_a_final_newline_gets_one_before_an_added_line(self):
        self.write(text="A=1")
        env_files.save(self.root, ".env", [{"name": "B", "value": "2"}])
        self.assertEqual(self.text(), "A=1\nB=2\n")

    def test_crlf_line_endings_are_kept(self):
        self.write(text="A=1\r\nB=2\r\n")
        env_files.save(self.root, ".env", [{"name": "A", "value": "9"}, {"name": "C", "value": "3"}])
        self.assertEqual(self.text(), "A=9\r\nB=2\r\nC=3\r\n")

    def test_bad_changes_are_refused_and_nothing_is_written(self):
        self.write()
        bad = [[{"name": "1BAD", "value": "x"}], [{"name": "A B", "value": "x"}], [{"name": "A"}],
               [{"name": "A", "value": 3}], [{"name": "A", "value": "x"}, {"name": "A", "value": "y"}],
               [{"name": "NOPE", "remove": True}], "A=1", [{"value": "x"}]]
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                env_files.save(self.root, ".env", changes)
        self.assertEqual(self.text(), SOURCE)

    def test_an_error_never_quotes_a_value(self):
        self.write()
        try:
            env_files.save(self.root, ".env", [{"name": "bad name", "value": "hunter2-secret"}])
        except ValueError as error:
            self.assertNotIn("hunter2-secret", str(error))


class GitStateTests(Case):
    def test_tracked_ignored_and_untracked(self):
        def git(*args):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)
        git("init", "-q")
        (self.root / ".gitignore").write_text(".env.local\n", encoding="utf-8")
        self.write(".env")
        self.write(".env.local")
        self.write(".env.production")
        git("add", ".env", ".gitignore")
        self.assertEqual(env_files.list_file(self.root, ".env")["git"], "tracked")
        self.assertEqual(env_files.list_file(self.root, ".env.local")["git"], "ignored")
        self.assertEqual(env_files.list_file(self.root, ".env.production")["git"], "untracked")



class RouteTests(Case):
    def test_a_card_of_another_framework_is_not_a_watched_project(self):
        card = str(self.root) + "::gsd-core"
        self.write()
        handler = SimpleNamespace(token="t", watcher=SimpleNamespace(projects={
            str(self.root): ProjectStatus(root=str(self.root)),
            card: ProjectStatus(root=str(self.root), id=card, flavor="gsd-core")}))
        self.assertEqual(env_files.list_route(handler, {"root": str(self.root), "file": ".env"})["file"], ".env")
        with self.assertRaisesRegex(ValueError, "not a watched project"):
            env_files.list_route(handler, {"root": card, "file": ".env"})

if __name__ == "__main__":
    unittest.main()
