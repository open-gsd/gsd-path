import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.hosts import opencode

# Trimmed lines recorded from `opencode run --format json --auto --pure` (1.18.25, 2026-09-06).
STEP_START = '{"type":"step_start","timestamp":1788750384712,"sessionID":"ses_f862b5441ffeBqkOCJOTMv86xC","part":{"id":"prt_079d4ce39001OuS5Le94OT6rIY","messageID":"msg_079d4af060013kt64lA831jCCC","sessionID":"ses_f862b5441ffeBqkOCJOTMv86xC","snapshot":"eefa917c4a27e1a50886840e6242549a9def5759","type":"step-start"}}'
TEXT = '{"type":"text","timestamp":1788750384715,"sessionID":"ses_f862b5441ffeBqkOCJOTMv86xC","part":{"id":"prt_079d4ce45001uy6WgH4KZskMJ7","messageID":"msg_079d4af060013kt64lA831jCCC","sessionID":"ses_f862b5441ffeBqkOCJOTMv86xC","type":"text","text":"ok","time":{"start":1788750384709,"end":1788750384713}}}'
STEP_FINISH = '{"type":"step_finish","timestamp":1788750384768,"sessionID":"ses_f862b5441ffeBqkOCJOTMv86xC","part":{"id":"prt_079d4ce7e001rQuTktZxN1NRgl","reason":"stop","snapshot":"be2620d138e5d373c4141aa85394b4ff2c261f79","messageID":"msg_079d4af060013kt64lA831jCCC","sessionID":"ses_f862b5441ffeBqkOCJOTMv86xC","type":"step-finish","tokens":{"total":58288,"input":58140,"output":3,"reasoning":17,"cache":{"write":0,"read":128}},"cost":0}}'
TASK_COMPLETED = '{"type":"tool_use","timestamp":1788750416590,"sessionID":"ses_f862af7a3ffevN3Tk3ERMJVWDO","part":{"type":"tool","tool":"task","callID":"call_1b97e6502f254c2fa037a86e","state":{"status":"completed","input":{"description":"build_probe","prompt":"Reply with exactly: ok","subagent_type":"general"},"output":"<task id=\\"ses_f862acbf6ffeN5ZyNDh1ZoH8H3\\" state=\\"completed\\">\\n<task_result>\\nok\\n</task_result>\\n</task>","metadata":{"parentSessionId":"ses_f862af7a3ffevN3Tk3ERMJVWDO","sessionId":"ses_f862acbf6ffeN5ZyNDh1ZoH8H3","model":{"modelID":"glm-5.3","providerID":"zai-coding-plan"},"truncated":false},"title":"build_probe","time":{"start":1788750410762,"end":1788750416576}},"id":"prt_079d53406001La3Wk8xiLia8Hv","sessionID":"ses_f862af7a3ffevN3Tk3ERMJVWDO","messageID":"msg_079d50b27001vWQX8Avq6CUbXP"}}'


def _task_line(status, task_state, description="build_probe"):
    ev = json.loads(TASK_COMPLETED)
    state = ev["part"]["state"]
    state["status"] = status
    state["input"]["description"] = description
    state["output"] = state["output"].replace('state="completed"', f'state="{task_state}"')
    return json.dumps(ev)


class ParseEventsTests(unittest.TestCase):
    def test_extracts_session_final_message_and_usage(self):
        parsed = opencode.parse_events([STEP_START, TEXT, "not json", STEP_FINISH])
        self.assertEqual(parsed["session_id"], "ses_f862b5441ffeBqkOCJOTMv86xC")
        self.assertEqual(parsed["final_message"], "ok")
        self.assertEqual(parsed["usage"]["tokens"]["output"], 3)
        self.assertEqual(parsed["usage"]["cost"], 0)

    def test_empty_stream_reports_nothing(self):
        self.assertEqual(opencode.parse_events([]), {"session_id": None, "final_message": None, "usage": None})


class CommandTests(unittest.TestCase):
    def test_resume_form_targets_session(self):
        base = opencode.command(Path("/p/prompt.txt"))
        self.assertEqual(base[:2], ["opencode", "run"])
        self.assertIn("json", base)
        self.assertEqual(opencode.command(Path("/p/prompt.txt"), "ses_x")[-2:], ["--session", "ses_x"])
        self.assertTrue(opencode.SPEC.prompt_on_stdin)


class BindChildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.db = self.root / "opencode.db"
        with sqlite3.connect(self.db) as conn:
            conn.execute("create table session (id text primary key, parent_id text, title text, agent text, model text, time_created integer, time_updated integer)")
            conn.execute("insert into session values (?,?,?,?,?,?,?)",
                         ("ses_f862acbf6ffeN5ZyNDh1ZoH8H3", "ses_f862af7a3ffevN3Tk3ERMJVWDO", "build_probe (@general subagent)", "general", None, 1, 2))
        self.original_db = opencode.SESSION_DB
        opencode.SESSION_DB = self.db
        self.addCleanup(setattr, opencode, "SESSION_DB", self.original_db)

    def record(self, run, lines):
        run_dir = self.root / "quick" / run
        run_dir.mkdir(parents=True)
        (run_dir / "events.jsonl").write_text("".join(json.dumps({"elapsed_seconds": 1.0, "raw": line}) + "\n" for line in lines))

    def test_binds_completed_child_by_description(self):
        self.record("run-1", [STEP_START, TASK_COMPLETED, TEXT, STEP_FINISH])
        bound = opencode.bind_child(self.root, "build_probe")
        self.assertEqual(bound["status"], "completed")
        self.assertEqual(bound["child_api"], "Task")
        self.assertEqual(bound["child_session"], "ses_f862acbf6ffeN5ZyNDh1ZoH8H3")
        self.assertEqual(bound["parent_session"], "ses_f862af7a3ffevN3Tk3ERMJVWDO")
        self.assertEqual(bound["input"], {"description": "build_probe", "subagent_type": "general"})
        self.assertNotIn("prompt", bound["input"])
        self.assertEqual(bound["session_row"]["parent_id"], "ses_f862af7a3ffevN3Tk3ERMJVWDO")

    def test_missing_session_store_still_binds(self):
        opencode.SESSION_DB = self.root / "absent.db"
        self.record("run-1", [TASK_COMPLETED])
        self.assertIsNone(opencode.bind_child(self.root, "build_probe")["session_row"])

    def test_unfinished_child_raises(self):
        self.record("run-1", [_task_line("running", "running")])
        with self.assertRaises(LookupError):
            opencode.bind_child(self.root, "build_probe")

    def test_errored_child_raises(self):
        self.record("run-1", [_task_line("error", "error")])
        with self.assertRaises(LookupError):
            opencode.bind_child(self.root, "build_probe")

    def test_other_child_name_raises(self):
        self.record("run-1", [TASK_COMPLETED])
        with self.assertRaises(LookupError):
            opencode.bind_child(self.root, "build_T001")

    def test_later_run_completion_wins(self):
        self.record("run-1", [_task_line("error", "error")])
        self.record("run-2", [TASK_COMPLETED])
        self.assertEqual(opencode.bind_child(self.root, "build_probe")["run"], "run-2")


if __name__ == "__main__":
    unittest.main()
