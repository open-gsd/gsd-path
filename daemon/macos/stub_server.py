import json
from http.server import BaseHTTPRequestHandler, HTTPServer

PAYLOAD = json.dumps({
    "schema": "gsd-path-daemon/status/v1",
    "generated_at": "2026-09-11T14:32:07Z",
    "projects": [
        {
            "root": "~/orca/workspaces/orca", "project": "orca", "milestone": "fleet-ui",
            "phase": "build", "status": "active", "branch": "gsd-path/M002",
            "git": {"branch": "gsd-path/M002", "head": "0e9a3b1", "dirty": False},
            "tasks_done": 7, "tasks_total": 12, "current_wave": 2,
            "waves": {"1": "graph model", "2": "fleet intents", "3": "resolve"},
            "pending_answers": [],
            "next_skill": "gsd-path-build",
            "time_in_phase_s": 273600,
            "usage": {"tokens_in": 412000, "tokens_out": 133000, "cost": 9.80,
                      "models": [{"model": "claude-opus-4.5", "family": "claude", "share": 0.55},
                                 {"model": "kimi-k2", "family": "kimi", "share": 0.31}]},
            "health": "amber",
            "attention": [
                {"kind": "question", "label": "A007 needs an answer", "ref": "A007"},
                {"kind": "stale", "label": "no progress in 3d", "ref": None}]
        },
        {
            "root": "~/work/gsd-path", "project": "gsd-path", "milestone": "daemon",
            "phase": "ship", "status": "blocked", "branch": "gsd-path/M001",
            "git": {"branch": "gsd-path/M001", "head": "9a0b1c2", "dirty": True},
            "tasks_done": 12, "tasks_total": 12, "current_wave": None,
            "waves": {"1": "core parsers", "2": "watcher", "3": "tray"},
            "pending_answers": [
                {"answer": "A002", "owner": "gsd-path-define", "status": "final"},
                {"answer": "A007", "owner": "gsd-path-plan", "status": "NEEDS-USER"}],
            "next_skill": "gsd-path-forensics",
            "time_in_phase_s": 3480,
            "usage": None,
            "health": "red",
            "attention": [
                {"kind": "blocked", "label": "ship blocked on wave review", "ref": None},
                {"kind": "failed", "label": "verify failed: task T012", "ref": "T012"}]
        },
        {
            "root": "~/work/memtrace", "project": "memtrace", "milestone": "graph",
            "phase": "shipped", "status": "shipped", "branch": "gsd-path/M003",
            "git": {"branch": "gsd-path/M003", "head": "c41d2e7", "dirty": False},
            "tasks_done": 9, "tasks_total": 9, "current_wave": None,
            "waves": {"1": "index"},
            "pending_answers": [],
            "next_skill": None,
            "time_in_phase_s": 60,
            "usage": None,
            "health": "green",
            "attention": []
        },
        {
            "root": "~/work/alpha", "project": "alpha", "milestone": "bootstrap",
            "phase": "define", "status": "active", "branch": "gsd-path/M001",
            "git": {"branch": "gsd-path/M001", "head": "1a2b3c4", "dirty": False},
            "tasks_done": 0, "tasks_total": 0, "current_wave": None,
            "waves": None,
            "pending_answers": [],
            "next_skill": "gsd-path-define",
            "time_in_phase_s": 900,
            "usage": None,
            "health": "green",
            "attention": []
        }
    ]
}).encode()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)

    def log_message(self, *args):
        pass

HTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
