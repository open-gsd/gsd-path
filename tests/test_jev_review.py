"""Exercise optional screening through the CLI and a local HTTP boundary."""

import copy
import hashlib
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
INPUT = {"reviewed_head": "a" * 40, "items": [
    {"id": "AC-1", "criterion": "Reject empty names", "evidence": "test_empty passed"},
    {"id": "AC-2", "criterion": "Preserve Unicode", "evidence": ""},
]}
OPTIONS = ("supported", "partial", "unsupported", "unclear")


def answer(choice):
    return {"type": "choice", "choice": choice, "confidence": 1.0,
            "probabilities": {option: float(option == choice) for option in OPTIONS}}


class JevReviewTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.response = {"model": "jev-1.13.0", "answers": {
            "AC-2": answer("unsupported"), "AC-1": answer("supported")},
            "usage": {"input_tokens": 120, "output_tokens": 24}}
        self.status = 200
        self.release_response = threading.Event()
        self.release_response.set()
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                owner.requests.append((dict(self.headers), json.loads(body)))
                owner.release_response.wait()
                self.send_response(owner.status)
                if owner.status == 302:
                    self.send_header("Location", owner.url + "/redirected")
                self.end_headers()
                data = owner.response
                try:
                    self.wfile.write(data if isinstance(data, bytes) else json.dumps(data).encode())
                except BrokenPipeError:
                    pass  # The timeout test deliberately closes its client socket.

            def do_GET(self):
                owner.requests.append((dict(self.headers), "redirected"))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.release_response.set)

    def run_cli(self, payload=INPUT, env=None, script=None):
        script = script or ROOT / "scripts/jev_review.py"
        # Only the remote HTTP boundary changes. The real CLI and transport run.
        program = ("import runpy, sys; "
                   "module = runpy.run_path(sys.argv[1]); "
                   "module['main'].__globals__['API_URL'] = sys.argv[2]; "
                   "raise SystemExit(module['main']())")
        process_env = dict(os.environ)
        for key in ("GSD_PATH_JEV", "TYPESAFE_API_KEY", "GSD_PATH_JEV_TIMEOUT_SECONDS"):
            process_env.pop(key, None)
        process_env.update({"GSD_PATH_JEV": "1", "TYPESAFE_API_KEY": "test-secret",
                            "GSD_PATH_JEV_TIMEOUT_SECONDS": "1"})
        process_env.update(env or {})
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-B", "-c", program, str(script), self.url],
                                    input=payload if isinstance(payload, str) else json.dumps(payload),
                                    capture_output=True, text=True, cwd=directory, env=process_env)
            self.assertEqual(list(Path(directory).iterdir()), [], "helper must not write project files")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("test-secret", result.stdout)
        receipt = json.loads(result.stdout)
        self.assertIs(receipt["advisory"], True)
        return receipt

    def test_disabled_does_not_parse_input_or_send_request_even_with_key(self):
        for flag in ("", "0", "true"):
            with self.subTest(flag=flag):
                result = self.run_cli("not JSON", {"GSD_PATH_JEV": flag})
                self.assertEqual(result["status"], "disabled")
        self.assertEqual(self.requests, [])

    def test_success_preserves_revision_ids_and_actual_request_hash(self):
        result = self.run_cli()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reviewed_head"], INPUT["reviewed_head"])
        self.assertEqual(result["answers"], self.response["answers"])
        self.assertEqual(result["usage"], self.response["usage"])
        self.assertEqual(result["model"], "jev-1.13.0")
        self.assertEqual(len(self.requests), 1)
        headers, body = self.requests[0]
        self.assertEqual(headers["Authorization"], "Bearer test-secret")
        self.assertEqual(body["state"], INPUT)
        self.assertEqual(body["model"], "jev-1.13.0")
        for item in INPUT["items"]:
            question = body["questions"][item["id"]]
            self.assertIn(item["id"], question["instructions"])
            self.assertEqual(question["type"], "choice")
            self.assertEqual(set(question["criteria"]), set(OPTIONS))
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(result["request_sha256"], digest)

    def test_missing_configuration_is_visible_without_request(self):
        for environment, reason in [({"TYPESAFE_API_KEY": ""}, "missing_api_key"),
                                    ({"GSD_PATH_JEV_TIMEOUT_SECONDS": ""}, "invalid_timeout"),
                                    ({"GSD_PATH_JEV_TIMEOUT_SECONDS": "nan"}, "invalid_timeout"),
                                    ({"GSD_PATH_JEV_TIMEOUT_SECONDS": "0"}, "invalid_timeout")]:
            with self.subTest(environment=environment):
                result = self.run_cli(env=environment)
                self.assertEqual((result["status"], result.get("reason")), ("unavailable", reason))
        self.assertEqual(self.requests, [])

    def test_invalid_input_is_visible_without_request(self):
        duplicate = copy.deepcopy(INPUT)
        duplicate["items"].append(duplicate["items"][0])
        # Cross the interpreter's recursion limit rather than invent a payload cap.
        nested = "[" * (sys.getrecursionlimit() + 1)
        for payload in ("not JSON", nested, [], {}, {**INPUT, "reviewed_head": "main"},
                        {**INPUT, "items": []}, duplicate,
                        {**INPUT, "items": [{"id": "AC-1", "criterion": "x", "evidence": 2}]}):
            with self.subTest(payload=payload):
                result = self.run_cli(payload)
                self.assertEqual((result["status"], result.get("reason")), ("unavailable", "invalid_input"))
        self.assertEqual(self.requests, [])

    def test_http_failure_and_redirect_are_visible_without_retries_or_secret_echo(self):
        for status in (401, 422, 429, 529, 302):
            with self.subTest(status=status):
                self.status = status
                self.response = b"test-secret provider error"
                result = self.run_cli()
                self.assertEqual((result["status"], result.get("reason")), ("unavailable", f"http_{status}"))
        self.assertEqual(len(self.requests), 5)

    def test_connection_failure_is_visible(self):
        self.server.shutdown()
        self.server.server_close()
        result = self.run_cli()
        self.assertEqual((result["status"], result.get("reason")),
                         ("unavailable", "network_error"))

    def test_owner_timeout_returns_unavailable(self):
        self.release_response.clear()
        # A held response must exceed any positive timeout; this is test input,
        # not a recommended production limit.
        result = self.run_cli(env={"GSD_PATH_JEV_TIMEOUT_SECONDS": "0.01"})
        self.assertEqual((result["status"], result.get("reason")),
                         ("unavailable", "network_error"))
        self.assertEqual(len(self.requests), 1)

    def test_distributed_helpers_support_opt_in_and_default_off(self):
        for skill in ("gsd-path", "gsd-path-build", "gsd-path-ship", "path"):
            with self.subTest(skill=skill):
                script = ROOT / "skills" / skill / "scripts/jev_review.py"
                result = self.run_cli(script=script)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["answers"], self.response["answers"])
                result = self.run_cli("not JSON", {"GSD_PATH_JEV": ""}, script=script)
                self.assertEqual(result["status"], "disabled")
        self.assertEqual(len(self.requests), 4)

    def test_incomplete_or_invalid_responses_never_become_advice(self):
        valid = copy.deepcopy(self.response)
        nested = b"[" * (sys.getrecursionlimit() + 1)
        variants = [b"not JSON", nested, [], {}, {**valid, "answers": {"AC-1": answer("supported")}},
                    {**valid, "model": "unexpected-model"}, {**valid, "usage": {}}]
        for field, value in (("choice", "pass"), ("type", "score"), ("confidence", float("nan")),
                             ("confidence", True), ("probabilities", {"supported": 1.0})):
            changed = copy.deepcopy(valid)
            changed["answers"]["AC-1"][field] = value
            variants.append(changed)
        for response in variants:
            with self.subTest(response=response):
                self.response = response
                result = self.run_cli()
                self.assertEqual((result["status"], result.get("reason")), ("unavailable", "invalid_response"))
                self.assertNotIn("answers", result)


if __name__ == "__main__":
    unittest.main()
