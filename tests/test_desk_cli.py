"""Exercise human approval and authenticated HTTP transport without Django."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("desk_cli", ROOT / "tools" / "desk_cli.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

THESIS_ID = "05ab1e58-8390-4b8f-b86a-8c3f031be88e"
TEXT_ID = "f1139469-dba6-4a98-af0c-95f3e778719f"
INTERPRETATION_ID = "c6c16880-f11c-46a7-ad7e-1a30c62f80f4"
APPROVAL_ID = "93a90fc0-e4a0-4ee4-b659-dd6187e73944"
POSITION_ID = "9e83956d-8f2f-4a54-9fd5-7f3d4f4c8d09"


def news_response():
    return {
        "mode": "recorded_example", "synthetic": True, "model": "not_used",
        "brief": {"context_status": "ready"},
        "notice": {"facts": [{"field": "headline", "value": "Fictional port disruption"}],
                   "portfolio_impact": "unresolved", "is_current": True,
                   "notification": {"state": "pending", "external_delivery": "not_configured"}},
        "source": {"source_id": "fictional-example-source", "revision": 1},
        "limitations": ["Screening is recorded, not analysis of your inputs."],
    }


class FakeClient:
    def __init__(self, *, conflict=False):
        self.calls = []
        self.conflict = conflict
        self.login_args = None
        self.logged_out = False

    def login(self, username, password):
        self.login_args = (username, password)

    def logout(self):
        self.logged_out = True

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/v1/theses/":
            return {"thesis": {"id": THESIS_ID, "revision": 7, "draft": {
                "text_version": {"id": TEXT_ID, "text_digest": "a" * 64, "exact_text": body["text"]},
                "interpretation": {"id": INTERPRETATION_ID, "digest": "b" * 64, **body["interpretation"]},
            }}}
        if path.endswith("/approvals/"):
            if self.conflict:
                raise cli.WalkthroughError("The saved state changed. Review the current thesis before approving again.")
            return {"thesis": {"approved": {"approval": {"id": APPROVAL_ID}}}}
        if path.endswith("/positions/"):
            return {"position": {"id": POSITION_ID, "current_version": {
                "missing_fields": ["product_id", "venue", "quote_currency"]}}}
        if path.endswith("/recorded-news/"):
            return news_response()
        raise AssertionError(path)


def answerer(values):
    values = iter(values)
    return lambda prompt: next(values)


@contextmanager
def http_server(callback):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            callback(self)

        def do_POST(self):
            callback(self)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def respond(handler, body, *, status=200, headers=()):
    data = json.dumps(body).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    for name, value in headers:
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(data)


class InputsAndApprovalTests(unittest.TestCase):
    def test_loopback_origins_only_and_no_ambiguous_credentials_or_paths(self):
        self.assertEqual(cli.local_url("http://localhost:8000/"), "http://127.0.0.1:8000")
        self.assertEqual(cli.local_url("http://[::1]:8000"), "http://[::1]:8000")
        for value in ("https://127.0.0.1:8000", "http://example.com", "http://127.0.0.1.example.com",
                      "http://user:password@127.0.0.1:8000", "http://127.0.0.1:8000/path",
                      "http://127.0.0.1:8000?target=elsewhere", "http://127.0.0.1:8000#target",
                      "http://127.0.0.1:8000\\@example.com", "\nhttp://127.0.0.1:8000",
                      "http://127.0.0.1:99999", "http://127.0.0.1:0", "http://127%2e0%2e0%2e1:8000"):
            with self.subTest(value=value), self.assertRaises(cli.argparse.ArgumentTypeError):
                cli.local_url(value)

    def test_file_preserves_utf8_line_endings_and_outer_whitespace(self):
        text = "  Gold α\r\nsecond line\r\n  "
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thesis.txt"
            path.write_bytes(text.encode("utf-8"))
            self.assertEqual(cli.read_thesis(path), text)
            path.write_bytes(b"\xff")
            with self.assertRaises(cli.WalkthroughError):
                cli.read_thesis(path)

    def test_declining_approval_saves_only_draft_and_excludes_secrets(self):
        client = FakeClient()
        messages = []
        trace = cli.happy_path(client, ask=answerer(["trader", " Exact view ", "", "", "", ""]),
                              secret=lambda prompt: "private-password", say=messages.append)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][2]["text"], " Exact view ")
        self.assertEqual(client.calls[0][2]["interpretation"], {"drivers": [], "horizon": None, "invalidation_signposts": []})
        self.assertNotIn("approval", trace)
        self.assertNotIn("private-password", json.dumps(trace) + "\n".join(messages))
        self.assertIn("Draft left unapproved", messages[-1])
        self.assertTrue(client.logged_out)

    def test_explicit_approval_binds_reviewed_exact_fields_and_optional_declaration(self):
        client = FakeClient()
        messages = []
        answers = ["trader", "  Exact α view  ", " Real yields ", "", "  Weeks ",
                   " Yields rise ", "", "approve", " XAU ", "long", "1.00", "ounces", "Weeks"]
        trace = cli.happy_path(client, ask=answerer(answers), secret=lambda prompt: "password", say=messages.append)
        approval = client.calls[1][2]
        self.assertEqual({name: approval[name] for name in approval if name != "command_id"}, {
            "expected_revision": 7, "thesis_version_id": TEXT_ID, "text_digest": "a" * 64,
            "interpretation_version_id": INTERPRETATION_ID, "interpretation_digest": "b" * 64,
        })
        position = client.calls[2][2]
        self.assertEqual(position["expected_approval_id"], APPROVAL_ID)
        self.assertEqual(position["position"], {"underlying": " XAU ", "direction": "long", "quantity": "1.00",
                                                "quantity_unit": "ounces", "horizon": "Weeks", "product_id": None,
                                                "venue": None, "expiry": None, "quote_currency": None})
        command_ids = [call[2]["command_id"] for call in client.calls[:3]]
        self.assertEqual(len(set(command_ids)), 3)
        for command_id in command_ids:
            self.assertEqual(str(cli.UUID(command_id)), command_id)
        self.assertEqual(client.calls[3][2], {"expected_approval_id": APPROVAL_ID})
        self.assertIn("recorded_news", trace)
        rendered = "\n".join(messages)
        self.assertIn("fictional source", rendered)
        self.assertIn("did not analyse whether the news is relevant", rendered)
        self.assertIn('Portfolio impact: "unresolved"', rendered)
        self.assertIn("Model calls: 0", rendered)
        self.assertNotIn("password", rendered)
        self.assertTrue(client.logged_out)

    def test_missing_size_is_null_not_an_invented_quantity(self):
        client = FakeClient()
        answers = ["trader", "View", "", "", "", "approve", "ES", "short", "", ""]
        cli.happy_path(client, ask=answerer(answers), secret=lambda prompt: "password", say=lambda message: None)
        declaration = client.calls[2][2]["position"]
        self.assertIsNone(declaration["quantity"])
        self.assertIsNone(declaration["quantity_unit"])
        self.assertIsNone(declaration["horizon"])

    def test_pending_or_superseded_notice_is_not_displayed_as_current_success(self):
        client = FakeClient()
        request = client.request
        def pending_request(method, path, body=None):
            response = request(method, path, body)
            if path.endswith("/recorded-news/"):
                response["brief"]["context_status"] = "pending"
                response["notice"]["is_current"] = False
            return response
        client.request = pending_request
        messages = []
        answers = ["trader", "View", "", "", "", "approve", "ES", "short", "", ""]
        cli.happy_path(client, ask=answerer(answers), secret=lambda prompt: "password", say=messages.append)
        self.assertIn("not current", messages[-1])
        self.assertNotIn("Walkthrough complete", "\n".join(messages))
        self.assertTrue(client.logged_out)

    def test_approval_conflict_never_retries_or_proceeds_to_attachment(self):
        client = FakeClient(conflict=True)
        with self.assertRaises(cli.WalkthroughError):
            cli.happy_path(client, ask=answerer(["trader", "View", "", "", "", "approve"]),
                           secret=lambda prompt: "password", say=lambda message: None)
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(client.calls[-1][1].endswith("/approvals/"))
        self.assertTrue(client.logged_out)

    def test_interrupted_input_ends_authenticated_session(self):
        client = FakeClient()
        def interrupted(prompt):
            if prompt == "Username: ":
                return "trader"
            raise EOFError
        with self.assertRaises(EOFError):
            cli.happy_path(client, ask=interrupted, secret=lambda prompt: "password", say=lambda message: None)
        self.assertTrue(client.logged_out)
        self.assertEqual(client.calls, [])

    def test_session_cleanup_failure_does_not_hide_successfully_saved_records(self):
        client = FakeClient()
        def offline_logout():
            raise cli.WalkthroughError("server stopped")
        client.logout = offline_logout
        messages = []
        trace = cli.happy_path(client, ask=answerer(["trader", "View", "", "", "", ""]),
                              secret=lambda prompt: "password", say=messages.append)
        self.assertIn("draft", trace)
        self.assertIn("Saved records are unchanged", messages[-1])

    def test_trace_is_private_and_existing_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.json"
            cli.write_trace(path, {"exact_text": "  View α\r\n"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text())["exact_text"], "  View α\r\n")
            with self.assertRaises(cli.WalkthroughError):
                cli.write_trace(path, {"different": "value"})
            self.assertIn("exact_text", json.loads(path.read_text()))


class SessionTransportTests(unittest.TestCase):
    def test_real_http_login_cookies_and_csrf_rotation_with_proxies_disabled(self):
        requests = []
        def callback(handler):
            length = int(handler.headers.get("Content-Length", "0"))
            body = json.loads(handler.rfile.read(length)) if length else None
            requests.append((handler.path, handler.headers.get("X-CSRFToken"), handler.headers.get("Cookie"), body))
            if handler.path == "/api/v1/session/":
                respond(handler, {"authenticated": False, "csrf_token": "bootstrap-token"},
                        headers=[("Set-Cookie", "csrftoken=bootstrap-cookie; Path=/; HttpOnly")])
            elif handler.path == "/api/v1/session/login/":
                respond(handler, {"authenticated": True, "csrf_token": "rotated-token"}, headers=[
                    ("Set-Cookie", "csrftoken=rotated-cookie; Path=/; HttpOnly"),
                    ("Set-Cookie", "sessionid=session-cookie; Path=/; HttpOnly"),
                ])
            else:
                respond(handler, {"saved": True})
        with http_server(callback) as url, patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "no_proxy": ""}):
            client = cli.DeskClient(url)
            client.login(" trader ", " secret ")
            self.assertEqual(client.request("POST", "/api/v1/theses/", {"text": "view"}), {"saved": True})
            client.logout()
            self.assertFalse(client.authenticated)
            self.assertIsNone(client.csrf_token)
        self.assertIsNone(requests[0][1])
        self.assertEqual(requests[1][1], "bootstrap-token")
        self.assertIn("csrftoken=bootstrap-cookie", requests[1][2])
        self.assertEqual(requests[1][3], {"username": " trader ", "password": " secret "})
        self.assertEqual(requests[2][1], "rotated-token")
        self.assertIn("csrftoken=rotated-cookie", requests[2][2])
        self.assertIn("sessionid=session-cookie", requests[2][2])
        self.assertNotIn("password", requests[2][3])
        self.assertEqual(requests[3][0], "/api/v1/session/logout/")
        self.assertEqual(requests[3][1], "rotated-token")
        self.assertEqual(requests[3][3], {})

    def test_login_redirect_does_not_forward_password_or_make_followup_request(self):
        sink_requests = []
        def sink(handler):
            sink_requests.append(handler.path)
            respond(handler, {"authenticated": True, "csrf_token": "wrong-target-token"})
        with http_server(sink) as sink_url:
            def callback(handler):
                if handler.path == "/api/v1/session/":
                    respond(handler, {"csrf_token": "bootstrap"})
                else:
                    handler.rfile.read(int(handler.headers.get("Content-Length", "0")))
                    respond(handler, {}, status=307, headers=[("Location", sink_url + "/received-password")])
            with http_server(callback) as url:
                with self.assertRaisesRegex(cli.WalkthroughError, "redirect"):
                    cli.DeskClient(url).login("trader", "never-forward-this-password")
        self.assertEqual(sink_requests, [])

    def test_bootstrap_failure_does_not_send_credentials(self):
        paths = []
        def callback(handler):
            paths.append(handler.path)
            respond(handler, {"authenticated": False})
        with http_server(callback) as url:
            with self.assertRaises(cli.WalkthroughError):
                cli.DeskClient(url).login("trader", "private-password")
        self.assertEqual(paths, ["/api/v1/session/"])

    def test_error_response_is_redacted_and_conflict_requires_review(self):
        def callback(handler):
            respond(handler, {"detail": "secret-password csrf-private-token"}, status=409)
        with http_server(callback) as url:
            with self.assertRaises(cli.WalkthroughError) as caught:
                cli.DeskClient(url).request("GET", "/api/v1/theses/")
        self.assertNotIn("secret-password", str(caught.exception))
        self.assertNotIn("csrf-private-token", str(caught.exception))
        self.assertIn("Review the current thesis", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
