"""Exercise human approval and authenticated HTTP transport without Django."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import stat
import shlex
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


def review_card(document, exact_text, inputs=()):
    return {"schema_version": "thesis-review-card-v1", "inputs": [
        {"input_id": "thesis", "exact_text": exact_text}, *inputs],
        "document": json.loads(json.dumps(document)),
        "evidence": {"status": "unavailable", "references": []}}


def card_sections():
    return {field: {"extracted": [], "proposed": [], "gap": "Not supplied."}
            for field, _ in cli.REVIEW_SECTIONS}


class CompilationClient(FakeClient):
    def __init__(self, *, status="compiled", current=True, credentials=True, provider="nanogpt"):
        super().__init__()
        self.status = status
        self.current = current
        self.credentials = credentials
        self.compilation_count = 0
        self.thesis = None
        self.receipts = {}
        self.refinements = []
        self.latest_refinement_id = None
        self.compiled_refinement_id = None
        self.catalog = {
            "provider": provider, "compilation_enabled": True,
            "credentials_configured": credentials, "fetched_at": "2026-10-06T00:00:00Z",
            "models": [
                {"id": "example/model-a", "name": "Alpha reasoning", "context_length": 64000,
                 "input_price_usd_per_million": "0.20", "output_price_usd_per_million": "0.80", "capabilities": {}},
                {"id": "example/model-b", "name": "Beta", "context_length": None,
                 "input_price_usd_per_million": None, "output_price_usd_per_million": None, "capabilities": {}},
            ],
        }

    def request(self, method, path, body=None):
        if method == "GET" and path == f"/api/v1/theses/{THESIS_ID}/":
            self.calls.append((method, path, body))
            return json.loads(json.dumps(self.thesis))
        if method == "GET" and path.startswith(f"/api/v1/theses/{THESIS_ID}/refinements/"):
            self.calls.append((method, path, body))
            identity = path.rstrip("/").split("/")[-1]
            saved = next(value for value in self.receipts.values()
                if "refinement" in value and value["refinement"]["id"] == identity)
            result = {"thesis": self.thesis, "refinement": saved["refinement"]}
            return json.loads(json.dumps(result))
        if path == "/api/v1/models/":
            self.calls.append((method, path, body))
            return self.catalog
        if "/compilation-commands/" in path or "/refinement-commands/" in path:
            self.calls.append((method, path, body))
            return json.loads(json.dumps(self.receipts[path.rstrip("/").split("/")[-1]]))
        if path.endswith("/refinements/"):
            self.calls.append((method, path, body))
            submission_id = str(cli.uuid4())
            self.latest_refinement_id = submission_id
            answers = [{"input_id": f"answer:{submission_id}:{item['question_index']}",
                        "parent_attempt_id": body["parent_attempt_id"],
                        "question_index": item["question_index"], "question": "What supports this mechanism?",
                        "exact_answer": item["exact_answer"]} for item in body["answers"]]
            self.refinements.extend(answers)
            result = {"thesis": self.thesis, "refinement": {
                "id": submission_id, "command_id": body["command_id"],
                "parent_attempt_id": body["parent_attempt_id"], "text_version_id": TEXT_ID,
                "expected_revision": body["expected_revision"], "answers": answers,
                "input_text_version": self.thesis["draft"]["text_version"],
                "cumulative_inputs": self.refinements, "created_at": "2026-10-09T00:00:00Z",
                "is_current_context": True}}
            self.receipts[body["command_id"]] = json.loads(json.dumps(result))
            return json.loads(json.dumps(result))
        if path.endswith("/compile/"):
            self.calls.append((method, path, body))
            if body["expected_revision"] != self.thesis["revision"]:
                raise AssertionError("Client did not use latest returned revision")
            prior_card = self.thesis["draft"]["interpretation"].get("review_card")
            attempt_inputs = self.refinements if body.get("refinement_id") else (prior_card["inputs"][1:] if prior_card else [])
            if body.get("refinement_id"):
                self.compiled_refinement_id = body["refinement_id"]
            self.compilation_count += 1
            interpretation_id = str(cli.uuid4())
            meaning = {"drivers": ["Rates"], "horizon": "Weeks", "invalidation_signposts": ["Rates rise"]}
            document = {
                "interpretation": meaning,
                "grounding": [{"field": "drivers", "index": 0, "input_id": "thesis", "exact_quote": "Gold"},
                              {"field": "horizon", "index": None, "input_id": "thesis", "exact_quote": "Gold"},
                              {"field": "invalidation_signposts", "index": 0, "input_id": "thesis", "exact_quote": "Gold"}],
                "refinement_issues": [{"kind": "unsupported_mechanism", "input_id": "thesis", "exact_quote": "Gold",
                                       "explanation": "The mechanism may not follow.", "question": "What supports this mechanism?"}],
                "agent_hypotheses": [{"explanation": "USD could be an additional channel.",
                                      "introduced_assumptions": ["USD matters for this trade."]}],
                "counter_case": "Rates might increase.", "review_card": card_sections(),
            }
            document["review_card"]["affected_assets"]["extracted"] = [
                {"text": "Gold exposure", "input_id": "thesis", "exact_quote": "Gold"}]
            document["review_card"]["causal_path"]["proposed"] = ["An unverified real-yield channel could apply."]
            if self.status == "compiled":
                self.thesis["revision"] += 1
                self.thesis["draft"]["interpretation"] = {
                    "id": interpretation_id, "digest": str(self.compilation_count) * 64,
                    "origin": "model_compilation", **meaning,
                    "review_card": review_card(document, self.thesis["draft"]["text_version"]["exact_text"], attempt_inputs),
                }
            response = {
                "compilation": {"id": str(cli.uuid4()), "status": self.status,
                                "command_id": body["command_id"], "refinement_inputs": attempt_inputs,
                                "refinement_id": self.compiled_refinement_id,
                                "input_text_version": self.thesis["draft"]["text_version"],
                                "model_id": body["model_id"], "provider": body["provider_id"],
                                "created_at": "2026-10-06T00:00:00Z", "finished_at": None,
                                "is_current_draft": self.current, "document": document if self.status == "compiled" else None,
                                "interpretation_version_id": interpretation_id if self.status == "compiled" else None,
                                "usage": {}, "reported_cost_usd": None, "estimated_cost_usd": None, "stop_reason": None},
                "thesis": self.thesis,
            }
            self.receipts[body["command_id"]] = json.loads(json.dumps(response))
            return json.loads(json.dumps(response))
        result = super().request(method, path, body)
        if path == "/api/v1/theses/":
            self.thesis = json.loads(json.dumps(result["thesis"]))
        return result


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

    def test_compile_timeout_reports_unknown_outcome_without_retry(self):
        client = cli.DeskClient("http://127.0.0.1:8000")
        client.csrf_token = "token"
        with patch.object(client.opener, "open", side_effect=TimeoutError) as opened:
            with self.assertRaises(cli.WalkthroughError) as caught:
                client.request("POST", f"/api/v1/theses/{THESIS_ID}/compile/", {"command_id": str(cli.uuid4())})
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(opened.call_args.kwargs["timeout"], 90)
        self.assertIn("outcome and cost are unknown", str(caught.exception))
        self.assertIn("No retry", str(caught.exception))

    def test_partial_or_invalid_http_compile_body_is_unknown_without_retry(self):
        for chunked in (True, False):
            with self.subTest(chunked=chunked):
                received = []
                def callback(handler):
                    handler.rfile.read(int(handler.headers.get("Content-Length", "0")))
                    received.append(handler.path)
                    handler.send_response(200)
                    handler.send_header("Content-Type", "application/json")
                    if chunked:
                        handler.send_header("Transfer-Encoding", "chunked")
                    handler.end_headers()
                    # A severed chunk or a malformed JSON body after acceptance
                    # cannot establish whether compilation was saved or billed.
                    handler.wfile.write(b"100\r\nprivate-provider-body" if chunked else b"private-provider-body")
                    handler.close_connection = True
                with http_server(callback) as url:
                    client = cli.DeskClient(url)
                    client.csrf_token = "token"
                    with self.assertRaises(cli.WalkthroughError) as caught:
                        client.request("POST", f"/api/v1/theses/{THESIS_ID}/compile/", {"command_id": str(cli.uuid4())})
                self.assertEqual(len(received), 1)
                self.assertIn("outcome and cost are unknown", str(caught.exception))
                self.assertIn("No retry", str(caught.exception))
                self.assertNotIn("private-provider-body", str(caught.exception))


class CompilationWalkthroughTests(unittest.TestCase):
    def test_compilation_keeps_exact_text_and_approves_only_reviewed_model_preview(self):
        client = CompilationClient()
        messages = []
        answers = ["trader", "  Gold α  ", "approve", "XAU", "long", "", "Weeks"]
        trace = cli.happy_path(client, compile=True, model_id="example/model-a", ask=answerer(answers),
                              secret=lambda prompt: "password", say=messages.append)
        created = next(body for method, path, body in client.calls if path == "/api/v1/theses/")
        self.assertEqual(created["text"], "  Gold α  ")
        self.assertEqual(created["interpretation"], {"drivers": [], "horizon": None, "invalidation_signposts": []})
        compiled = next(body for method, path, body in client.calls if path.endswith("/compile/"))
        self.assertEqual(set(compiled), {"command_id", "expected_revision", "model_id", "provider_id"})
        self.assertEqual(compiled["provider_id"], "nanogpt")
        self.assertEqual(compiled["expected_revision"], 7)
        self.assertEqual(compiled["model_id"], "example/model-a")
        approved = next(body for method, path, body in client.calls if path.endswith("/approvals/"))
        compiled_draft = trace["compilations"][0]["thesis"]["draft"]
        self.assertEqual(approved["interpretation_version_id"], compiled_draft["interpretation"]["id"])
        self.assertEqual(approved["interpretation_digest"], compiled_draft["interpretation"]["digest"])
        self.assertEqual(approved["text_digest"], "a" * 64)
        self.assertEqual(approved["expected_revision"], 8)
        output = "\n".join(messages)
        self.assertIn("What supports this mechanism?", output)
        self.assertIn("Agent hypotheses, separate", output)
        self.assertIn("Introduced assumptions", output)
        self.assertIn("Counter-case", output)
        self.assertIn("factual verification are unavailable", output)
        self.assertIn("Provider-reported cost USD: unknown", output)
        self.assertIn("Estimated cost USD: unknown", output)
        self.assertNotIn("Provider-reported cost USD: 0", output)
        self.assertTrue(client.logged_out)

    def test_named_search_number_selection_and_decline_do_not_approve(self):
        client = CompilationClient()
        messages = []
        cli.happy_path(client, compile=True, ask=answerer(["trader", "Gold", "/beta", "1", ""]),
                       secret=lambda prompt: "password", say=messages.append)
        compiles = [body for method, path, body in client.calls if path.endswith("/compile/")]
        self.assertEqual(compiles[0]["model_id"], "example/model-b")
        self.assertFalse(any(path.endswith("/approvals/") for method, path, body in client.calls))
        self.assertIn("Draft left unapproved", messages[-1])
        self.assertTrue(client.logged_out)

    def test_switch_fetches_catalog_again_and_uses_latest_revision_and_new_command(self):
        client = CompilationClient()
        answers = ["trader", "Gold", "1", "switch", "example/model-b", "approve", "XAU", "short", "", ""]
        trace = cli.happy_path(client, compile=True, ask=answerer(answers),
                              secret=lambda prompt: "password", say=lambda value: None)
        catalogs = [path for method, path, body in client.calls if path == "/api/v1/models/"]
        self.assertEqual(len(catalogs), 2)
        compiles = [body for method, path, body in client.calls if path.endswith("/compile/")]
        self.assertEqual([body["model_id"] for body in compiles], ["example/model-a", "example/model-b"])
        self.assertEqual([body["expected_revision"] for body in compiles], [7, 8])
        self.assertNotEqual(compiles[0]["command_id"], compiles[1]["command_id"])
        approved = next(body for method, path, body in client.calls if path.endswith("/approvals/"))
        self.assertEqual(approved["expected_revision"], 9)
        self.assertEqual(approved["interpretation_version_id"], trace["compilations"][-1]["compilation"]["interpretation_version_id"])
        self.assertEqual(len(trace["compilations"]), 2)

    def test_failed_running_unknown_stale_and_historical_results_never_reach_approval(self):
        for status, current in (("failed", False), ("running", False), ("outcome_unknown", False),
                                ("stale", False), ("compiled", False)):
            with self.subTest(status=status):
                client = CompilationClient(status=status, current=current)
                messages = []
                trace = cli.happy_path(client, compile=True, model_id="example/model-a",
                                      ask=answerer(["trader", "Gold"]), secret=lambda prompt: "password", say=messages.append)
                self.assertEqual(client.compilation_count, 1)
                self.assertNotIn("approval", trace)
                self.assertFalse(any(path.endswith("/approvals/") or path.endswith("/positions/")
                                     for method, path, body in client.calls))
                self.assertIn("no automatic retry", messages[-1])
                self.assertTrue(client.logged_out)

    def test_unknown_requested_model_has_no_fallback_or_provider_request(self):
        client = CompilationClient()
        with self.assertRaises(cli.WalkthroughError):
            cli.happy_path(client, compile=True, model_id="invented/default", ask=answerer(["trader", "Gold"]),
                           secret=lambda prompt: "password", say=lambda value: None)
        self.assertEqual(client.calls, [("GET", "/api/v1/models/", None)])
        self.assertTrue(client.logged_out)

    def test_unconfigured_credentials_are_actionable_and_no_draft_is_created(self):
        client = CompilationClient(credentials=False)
        with self.assertRaisesRegex(cli.WalkthroughError, "configure-models"):
            cli.happy_path(client, compile=True, ask=answerer(["trader", "Gold"]),
                           secret=lambda prompt: "password", say=lambda value: None)
        self.assertEqual(client.calls, [("GET", "/api/v1/models/", None)])

    def test_selection_cancellation_does_not_create_draft_or_request_model(self):
        client = CompilationClient()
        trace = cli.happy_path(client, compile=True, ask=answerer(["trader", "Gold", "cancel"]),
                              secret=lambda prompt: "password", say=lambda value: None)
        self.assertEqual(trace["model_selected"], False)
        self.assertEqual(client.calls, [("GET", "/api/v1/models/", None)])

    def test_model_switch_cancellation_keeps_preview_without_new_charge_or_approval(self):
        client = CompilationClient()
        cli.happy_path(client, compile=True, model_id="example/model-a", ask=answerer(["trader", "Gold", "switch", "cancel"]),
                       secret=lambda prompt: "password", say=lambda value: None)
        self.assertEqual(client.compilation_count, 1)
        self.assertFalse(any(path.endswith("/approvals/") for method, path, body in client.calls))

    def test_each_router_uses_its_dynamic_catalog_and_pins_provider(self):
        for provider in ("nanogpt", "openrouter", "cheaperinference"):
            with self.subTest(provider=provider):
                client = CompilationClient(provider=provider)
                messages = []
                trace = cli.happy_path(client, compile=True, ask=answerer(["trader", "Gold", "2", ""]),
                                      secret=lambda prompt: "password", say=messages.append)
                compiled = next(body for method, path, body in client.calls if path.endswith("/compile/"))
                self.assertEqual(compiled["provider_id"], provider)
                self.assertEqual(compiled["model_id"], "example/model-b")
                self.assertEqual(trace["compilations"][0]["compilation"]["provider"], provider)
                self.assertIn(cli.PROVIDER_LABELS[provider], "\n".join(messages))

    def test_provider_change_during_request_cannot_be_approved(self):
        client = CompilationClient()
        request = client.request
        def changed_provider(method, path, body=None):
            response = request(method, path, body)
            if path.endswith("/compile/"):
                response["compilation"]["provider"] = "openrouter"
            return response
        client.request = changed_provider
        with self.assertRaisesRegex(cli.WalkthroughError, "provider"):
            cli.happy_path(client, compile=True, model_id="example/model-a", ask=answerer(["trader", "Gold"]),
                           secret=lambda prompt: "password", say=lambda value: None)
        self.assertFalse(any(path.endswith("/approvals/") for method, path, body in client.calls))
        self.assertTrue(client.logged_out)

    def test_model_switch_uses_fresh_provider_pin(self):
        client = CompilationClient()
        request = client.request
        catalogs = 0
        def switched_provider(method, path, body=None):
            nonlocal catalogs
            if path == "/api/v1/models/":
                catalogs += 1
                if catalogs == 2:
                    client.catalog["provider"] = "cheaperinference"
            return request(method, path, body)
        client.request = switched_provider
        cli.happy_path(client, compile=True, model_id="example/model-a",
                       ask=answerer(["trader", "Gold", "switch", "1", ""]),
                       secret=lambda prompt: "password", say=lambda value: None)
        compiles = [body for method, path, body in client.calls if path.endswith("/compile/")]
        self.assertEqual([body["provider_id"] for body in compiles], ["nanogpt", "cheaperinference"])


class DurableRefinementTests(unittest.TestCase):
    def run_flow(self, client, values, journal, messages=None):
        return cli.happy_path(client, compile=True, model_id="example/model-a", journal=journal,
            ask=answerer(values), secret=lambda prompt: "private-password",
            say=(messages.append if messages is not None else lambda value: None))

    def test_saved_answers_do_not_require_another_paid_call_or_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = cli.CommandJournal(Path(directory) / "commands.jsonl")
            client, messages = CompilationClient(), []
            trace = self.run_flow(client, ["trader", "Gold", "refine", "  My mechanism α  ", "save", ""], journal, messages)
            journal.close()
            self.assertEqual(client.compilation_count, 1)
            self.assertNotIn("approval", trace)
            self.assertEqual(trace["refinements"][0]["refinement"]["answers"][0]["exact_answer"], "  My mechanism α  ")
            self.assertEqual(trace["draft"]["thesis"]["draft"]["text_version"]["exact_text"], "Gold")
            self.assertIn("Answers remain saved", messages[-1])
            records = [json.loads(line) for line in journal.path.read_text().splitlines()]
            self.assertEqual([record["kind"] for record in records], [
                "compile_requested", "compile_response", "refinement_requested", "refinement_response"])
            self.assertEqual(stat.S_IMODE(journal.path.stat().st_mode), 0o600)
            self.assertNotIn("private-password", journal.path.read_text())

    def test_explicit_recompile_pins_saved_answers_and_approves_latest_full_card(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = cli.CommandJournal(Path(directory) / "commands.jsonl")
            client, messages = CompilationClient(), []
            trace = self.run_flow(client, ["trader", "Gold", "refine", "My conditional mechanism", "save",
                "recompile", "approve", "XAU", "long", "", "Weeks"], journal, messages)
            journal.close()
            compiles = [body for _, path, body in client.calls if path.endswith("/compile/")]
            self.assertEqual(len(compiles), 2)
            saved = trace["refinements"][0]["refinement"]
            self.assertEqual(compiles[1]["refinement_id"], saved["id"])
            self.assertEqual(compiles[1]["expected_revision"], 8)
            last = trace["compilations"][-1]
            self.assertEqual(last["thesis"]["draft"]["interpretation"]["review_card"]["inputs"][1:], saved["cumulative_inputs"])
            approval = next(body for _, path, body in client.calls if path.endswith("/approvals/"))
            self.assertEqual(approval["interpretation_version_id"], last["compilation"]["interpretation_version_id"])
            self.assertEqual(approval["expected_revision"], 9)
            output = "\n".join(messages)
            for _, label in cli.REVIEW_SECTIONS:
                self.assertIn(label, output)
            self.assertIn("Agent proposal, unverified and not adopted as trader intent", output)
            self.assertIn('"status": "unavailable"', output)

    def test_answers_are_discarded_without_save_and_empty_answers_do_not_call_backend(self):
        for values in (["trader", "Gold", "refine", "", ""],
                       ["trader", "Gold", "refine", "An answer", "", ""]):
            with self.subTest(values=values), tempfile.TemporaryDirectory() as directory:
                journal = cli.CommandJournal(Path(directory) / "commands.jsonl")
                client = CompilationClient()
                self.run_flow(client, values, journal)
                journal.close()
                self.assertEqual(client.compilation_count, 1)
                self.assertFalse(any(path.endswith("/refinements/") for _, path, _ in client.calls))

    def test_full_card_mismatch_prevents_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = cli.CommandJournal(Path(directory) / "commands.jsonl")
            client = CompilationClient()
            request = client.request
            def mismatch(method, path, body=None):
                response = request(method, path, body)
                if path.endswith("/compile/"):
                    response["thesis"]["draft"]["interpretation"]["review_card"]["document"]["review_card"]["catalysts"]["gap"] = "Other meaning"
                return response
            client.request = mismatch
            with self.assertRaisesRegex(cli.WalkthroughError, "review card"):
                self.run_flow(client, ["trader", "Gold"], journal)
            journal.close()
            self.assertFalse(any(path.endswith("/approvals/") for _, path, _ in client.calls))

    def test_lost_compile_response_has_durable_identity_and_get_only_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = cli.CommandJournal(Path(directory) / "commands.jsonl")
            client = CompilationClient()
            request = client.request
            def lost(method, path, body=None):
                result = request(method, path, body)
                if path.endswith("/compile/"):
                    on_disk = [json.loads(line) for line in journal.path.read_text().splitlines()]
                    self.assertEqual(on_disk[-1]["detail"]["request"]["command_id"], body["command_id"])
                    raise cli.WalkthroughError("Lost after provider request")
                return result
            client.request = lost
            with self.assertRaisesRegex(cli.WalkthroughError, "Recover that command"):
                self.run_flow(client, ["trader", "Gold"], journal)
            journal.close()
            target = cli.recovery_target(journal_path=journal.path)
            before = len(client.calls)
            recovered = cli.recover_command(client, target, ask=answerer(["trader"]),
                secret=lambda prompt: "password", say=lambda value: None)
            self.assertEqual(recovered["compilation"]["status"], "compiled")
            self.assertEqual(client.compilation_count, 1)
            self.assertEqual(client.calls[before:], [("GET",
                f"/api/v1/theses/{THESIS_ID}/compilation-commands/{target['command_id']}/", None)])

    def test_lost_refinement_response_recovers_saved_exact_answers_without_model_call(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = cli.CommandJournal(Path(directory) / "commands.jsonl")
            client = CompilationClient()
            request = client.request
            def lost(method, path, body=None):
                result = request(method, path, body)
                if path.endswith("/refinements/"):
                    raise cli.WalkthroughError("Lost after durable save")
                return result
            client.request = lost
            with self.assertRaises(cli.WalkthroughError):
                self.run_flow(client, ["trader", "Gold", "refine", "  Exact α  ", "save"], journal)
            journal.close()
            target = cli.recovery_target(journal_path=journal.path)
            self.assertEqual(target["kind"], "refinement")
            before = len(client.calls)
            response = cli.recover_command(client, target, ask=answerer(["trader"]),
                secret=lambda prompt: "password", say=lambda value: None)
            self.assertEqual(response["refinement"]["answers"][0]["exact_answer"], "  Exact α  ")
            self.assertEqual(client.compilation_count, 1)
            self.assertEqual([method for method, _, _ in client.calls[before:]], ["GET"])

    def test_missing_answers_in_recompiled_output_cannot_be_approved(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = cli.CommandJournal(Path(directory) / "commands.jsonl")
            client = CompilationClient()
            request = client.request
            def missing(method, path, body=None):
                response = request(method, path, body)
                if path.endswith("/compile/") and client.compilation_count == 2:
                    response["compilation"]["refinement_inputs"] = []
                return response
            client.request = missing
            with self.assertRaisesRegex(cli.WalkthroughError, "answer lineage"):
                self.run_flow(client, ["trader", "Gold", "refine", "Conditional answer", "save", "recompile"], journal)
            journal.close()
            self.assertEqual(client.compilation_count, 2)
            self.assertFalse(any(path.endswith("/approvals/") for _, path, _ in client.calls))

    def test_recovery_uses_retained_original_input_after_current_text_changes(self):
        client = CompilationClient()
        client.request("POST", "/api/v1/theses/", {"text": "Gold", "interpretation": {
            "drivers": [], "horizon": None, "invalidation_signposts": []}})
        command = {"command_id": str(cli.uuid4()), "expected_revision": 7,
            "provider_id": "nanogpt", "model_id": "example/model-a"}
        client.request("POST", f"/api/v1/theses/{THESIS_ID}/compile/", command)
        receipt = client.receipts[command["command_id"]]
        receipt["thesis"]["draft"]["text_version"]["exact_text"] = "A different current thesis"
        receipt["compilation"]["is_current_draft"] = False
        messages = []
        cli.recover_command(client, {"thesis_id": THESIS_ID, "command_id": command["command_id"],
            "kind": "compilation"}, ask=answerer(["trader"]), secret=lambda prompt: "password", say=messages.append)
        self.assertIn('Original exact input: "Gold"', messages)
        self.assertNotIn("A different current thesis", "\n".join(messages))
        self.assertEqual(client.compilation_count, 1)

    def test_recovery_unavailable_has_no_catalogue_or_post_fallback(self):
        client = CompilationClient()
        def unavailable(method, path, body=None):
            client.calls.append((method, path, body))
            raise cli.WalkthroughError("Not found")
        client.request = unavailable
        with self.assertRaisesRegex(cli.WalkthroughError, "No catalogue, model request or POST fallback"):
            cli.recover_command(client, {"thesis_id": THESIS_ID, "command_id": TEXT_ID,
                "kind": "compilation"}, ask=answerer(["trader"]), secret=lambda prompt: "password", say=lambda value: None)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][0], "GET")
        self.assertTrue(client.logged_out)

    def test_recovery_preserves_fsynced_request_before_partial_final_response(self):
        for tail in (b'{"kind":"compile_response","detail":',
                     b'{"kind":"compile_response","detail":{"text":"\xe2\x82'):
            with self.subTest(tail=tail), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "commands.jsonl"
                journal = cli.CommandJournal(path)
                journal.append("compile_requested", {"thesis_id": THESIS_ID,
                    "request": {"command_id": TEXT_ID}, "exact_text": "Gold α"})
                journal.close()
                with path.open("ab") as stream:
                    stream.write(tail)
                target = cli.recovery_target(journal_path=path)
                self.assertEqual(target, {"thesis_id": THESIS_ID, "command_id": TEXT_ID,
                    "kind": "compilation", "exact_text": "Gold α"})
                self.assertTrue(path.read_bytes().endswith(tail))

    def test_recovery_rejects_malformed_complete_or_middle_records(self):
        for corrupt in (b'{"kind":"broken"\n', b'{"kind":"broken","value":"\xe2\x82"}\n'):
            for middle in (False, True):
                with self.subTest(corrupt=corrupt, middle=middle), tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "commands.jsonl"
                    request = {"kind": "compile_requested", "detail": {"thesis_id": THESIS_ID,
                        "request": {"command_id": TEXT_ID}, "exact_text": "Gold"}}
                    encoded = json.dumps(request).encode("utf-8") + b"\n"
                    path.write_bytes(encoded + corrupt + (encoded if middle else b""))
                    with self.assertRaisesRegex(cli.WalkthroughError, "Cannot resolve"):
                        cli.recovery_target(journal_path=path)

    def test_journal_failure_blocks_model_post_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = cli.CommandJournal(Path(directory) / "commands.jsonl")
            client = CompilationClient()
            with patch.object(cli.os, "fsync", side_effect=OSError("disk unavailable")):
                with self.assertRaisesRegex(cli.WalkthroughError, "journal could not be saved"):
                    self.run_flow(client, ["trader", "Gold"], journal)
            journal.close()
            self.assertEqual(client.compilation_count, 0)

    def test_recovery_unknown_or_historical_is_read_only_and_never_approves(self):
        for status in ("outcome_unknown", "running", "failed", "stale", "compiled"):
            with self.subTest(status=status):
                client = CompilationClient(status=status, current=False)
                created = client.request("POST", "/api/v1/theses/", {"text": "Gold", "interpretation": {
                    "drivers": [], "horizon": None, "invalidation_signposts": []}})
                command = {"command_id": str(cli.uuid4()), "expected_revision": 7,
                    "provider_id": "nanogpt", "model_id": "example/model-a"}
                client.request("POST", f"/api/v1/theses/{THESIS_ID}/compile/", command)
                before = len(client.calls)
                cli.recover_command(client, {"thesis_id": THESIS_ID, "command_id": command["command_id"],
                    "kind": "compilation"}, ask=answerer(["trader"]), secret=lambda prompt: "password", say=lambda value: None)
                self.assertEqual(client.compilation_count, 1)
                self.assertEqual([method for method, _, _ in client.calls[before:]], ["GET"])


class RetainedCompilationTests(unittest.TestCase):
    def prepared(self, directory):
        client = CompilationClient()
        journal = cli.CommandJournal(Path(directory) / "initial.jsonl")
        try:
            trace = cli.happy_path(client, compile=True, model_id="example/model-a", journal=journal,
                ask=answerer(["trader", "Gold", "refine", "  A conditional answer α  ", "save", ""]),
                secret=lambda prompt: "password", say=lambda value: None)
        finally:
            journal.close()
        client.thesis["approved"] = {"approval": {"id": APPROVAL_ID}}
        return client, trace["refinements"][0]["refinement"]["id"]

    def continuation(self, client, identity, values, directory, messages=None):
        journal = cli.CommandJournal(Path(directory) / "continuation.jsonl")
        try:
            return cli.compile_existing(client, THESIS_ID, refinement_id=identity,
                model_id="example/model-a", journal=journal, ask=answerer(values),
                secret=lambda prompt: "password", say=(messages.append if messages is not None else lambda value: None))
        finally:
            journal.close()

    def test_saved_answers_survive_restart_and_explicit_run_approves_new_review(self):
        with tempfile.TemporaryDirectory() as directory:
            client, identity = self.prepared(directory)
            before = len(client.calls)
            messages = []
            request = client.request
            observed_old_approval = []
            def observed(method, path, body=None):
                if path.endswith("/compile/") or path.endswith("/approvals/"):
                    observed_old_approval.append(client.thesis["approved"]["approval"]["id"])
                return request(method, path, body)
            client.request = observed
            trace = self.continuation(client, identity, ["trader", "run", "approve"], directory, messages)
            calls = client.calls[before:]
            self.assertEqual([(method, path.rsplit("/", 2)[-2]) for method, path, _ in calls], [
                ("GET", THESIS_ID), ("GET", identity), ("GET", "models"), ("POST", "compile"), ("POST", "approvals")])
            self.assertEqual(client.compilation_count, 2)
            self.assertEqual(observed_old_approval, [APPROVAL_ID, APPROVAL_ID])
            self.assertIn("approval", trace)
            self.assertEqual(trace["compilations"][0]["compilation"]["refinement_inputs"][0]["exact_answer"], "  A conditional answer α  ")
            self.assertIn("Retained exact thesis", "\n".join(messages))
            self.assertFalse(any(path.endswith("/positions/") or path.endswith("/recorded-news/") for _, path, _ in calls))

    def test_declining_run_keeps_answers_and_approval_without_paid_call(self):
        with tempfile.TemporaryDirectory() as directory:
            client, identity = self.prepared(directory)
            before = len(client.calls)
            trace = self.continuation(client, identity, ["trader", ""], directory)
            self.assertEqual(client.compilation_count, 1)
            self.assertNotIn("approval", trace)
            self.assertTrue(all(method == "GET" for method, _, _ in client.calls[before:]))
            self.assertEqual(client.thesis["approved"]["approval"]["id"], APPROVAL_ID)

    def test_stale_or_foreign_refinement_stops_before_catalogue_or_paid_call(self):
        for field, value in (("is_current_context", False), ("text_version_id", POSITION_ID)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                client, identity = self.prepared(directory)
                saved = next(item for item in client.receipts.values() if "refinement" in item)
                saved["refinement"][field] = value
                before = len(client.calls)
                with self.assertRaisesRegex(cli.WalkthroughError, "stale or belong"):
                    self.continuation(client, identity, ["trader"], directory)
                self.assertEqual(client.compilation_count, 1)
                self.assertEqual(len(client.calls[before:]), 2)
                self.assertFalse(any(path == "/api/v1/models/" for _, path, _ in client.calls[before:]))

    def test_unknown_new_attempt_keeps_old_approval_and_cannot_approve(self):
        with tempfile.TemporaryDirectory() as directory:
            client, identity = self.prepared(directory)
            client.status = "outcome_unknown"
            before = len(client.calls)
            trace = self.continuation(client, identity, ["trader", "run"], directory)
            self.assertEqual(client.compilation_count, 2)
            self.assertNotIn("approval", trace)
            self.assertEqual(client.thesis["approved"]["approval"]["id"], APPROVAL_ID)
            self.assertFalse(any(path.endswith("/approvals/") for _, path, _ in client.calls[before:]))

    def test_omitted_submission_inherits_only_current_compiled_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            client, identity = self.prepared(directory)
            trace = self.continuation(client, None, ["trader", "run", ""], directory)
            output = trace["compilations"][0]
            self.assertEqual(output["compilation"]["refinement_inputs"], [])
            self.assertIsNone(output["compilation"]["refinement_id"])
            self.assertEqual(len(client.refinements), 1)


class ModelSetupTests(unittest.TestCase):
    def test_hidden_key_is_shell_quoted_private_and_never_printed(self):
        key = "private'key$literal$(do-not-run)"
        messages = []
        prompts = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".local" / "models.env"
            def hidden(prompt):
                prompts.append(prompt)
                return key
            cli.configure_models(path, ask=answerer(["nanogpt"]), secret=hidden, say=messages.append)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            text = path.read_text()
            assignments = shlex.split(text)
            self.assertIn("MACRO_MODEL_API_KEY=" + key, assignments)
            self.assertIn("MACRO_MODEL_PROVIDER=nanogpt", assignments)
            self.assertIn("MACRO_ENABLE_MODEL_COMPILATION=1", assignments)
            self.assertNotIn(key, "\n".join(messages))
            self.assertEqual(prompts, ["NanoGPT API key (hidden): "])
            self.assertIn("No provider request was made", "\n".join(messages))
            with self.assertRaises(cli.WalkthroughError):
                cli.configure_models(path, ask=answerer(["nanogpt"]), secret=lambda prompt: "replacement", say=lambda value: None)
            self.assertEqual(path.read_text(), text)

    def test_invalid_key_does_not_create_configuration_or_echo_the_key(self):
        for key in ("", " ", "secret value", "secret\tvalue", "secret\nexport MALICIOUS=1", "secret\x00"):
            with self.subTest(key=repr(key)), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "models.env"
                messages = []
                with self.assertRaises(cli.WalkthroughError) as caught:
                    cli.configure_models(path, ask=answerer(["nanogpt"]), secret=lambda prompt: key, say=messages.append)
                self.assertFalse(path.exists())
                self.assertNotIn("MALICIOUS", str(caught.exception) + "\n".join(messages))

    def test_insecure_getpass_fallback_is_rejected_before_reading_the_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.env"
            def insecure(prompt):
                cli.warnings.warn("Cannot disable echo", cli.getpass.GetPassWarning)
                raise AssertionError("An insecure fallback must not continue reading credentials")
            with self.assertRaisesRegex(cli.WalkthroughError, "interactive terminal"):
                cli.configure_models(path, ask=answerer(["nanogpt"]), secret=insecure, say=lambda value: None)
            self.assertFalse(path.exists())

    def test_setup_provider_is_explicit_and_never_guessed_from_key_shape(self):
        for provider in ("nanogpt", "openrouter", "cheaperinference"):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "models.env"
                prompts = []
                def secret(prompt):
                    prompts.append(prompt)
                    return "same-unclassified-key-format"
                cli.configure_models(path, ask=answerer(["", "not-a-router", provider]),
                                     secret=secret, say=lambda value: None)
                assignments = shlex.split(path.read_text())
                self.assertIn("MACRO_MODEL_PROVIDER=" + provider, assignments)
                self.assertIn("MACRO_MODEL_API_KEY=same-unclassified-key-format", assignments)
                self.assertEqual(prompts, [cli.PROVIDER_LABELS[provider] + " API key (hidden): "])


if __name__ == "__main__":
    unittest.main()
