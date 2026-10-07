"""One automatically selected report, durable request identity and no hidden retry."""

import copy
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import review_news as review

THESIS = "05ab1e58-8390-4b8f-b86a-8c3f031be88e"
APPROVAL = "a7433838-92b5-4d3a-a6cb-d58658002f82"
POSITION = "00479a43-7b8a-496f-a2e6-8ae87c57c5ad"
REVISION = "de6856cf-5717-414d-b94a-76d7a4bde90a"
ATTEMPT = "168bcfe1-2b19-4564-88b7-13edb0f4c313"
MODEL = "example/model"
SOURCE = "fixture-divergence"
EXACT = "  Policy easing may support equities over a few months.\r\nΔ\r\n"
MEANING = {"drivers": ["Policy easing"], "horizon": "A few months", "invalidation_signposts": []}
POSITIONS = [{"position_id": POSITION, "version_id": "15b53372-649b-420e-872d-18962a233b4f",
    "status": "open", "underlying": "NQ", "direction": "long", "quantity": None,
    "quantity_unit": None, "horizon": None, "product_id": None, "venue": None,
    "expiry": None, "quote_currency": None, "missing_fields": ["quantity"],
    "mapping_status": "user_declared_unverified"}]
PREVIEW = {"thesis_id": THESIS, "approval_id": APPROVAL, "exposure_digest": "b" * 64,
    "approved_exact_text": EXACT, "approved_interpretation": MEANING,
    "positions": POSITIONS, "limitations": ["Attached thesis book, unverified mapping."]}
FEED = json.loads((ROOT / "fixtures" / "news_analysis_case.json").read_text())["items"][0]
DOCUMENT = json.loads((ROOT / "fixtures" / "news_analysis_response.json").read_text())
DOCUMENT["attributed_facts"][0]["source_revision_id"] = REVISION
DOCUMENT["trade_route"]["position_ids"] = [POSITION]
DOCUMENT["hypotheses"][0]["position_ids"] = [POSITION]
CONTEXT = {"source": {"source_key": SOURCE, "report_id": 1, "native_id": FEED["id"],
    "revision_id": REVISION, "digest": "c" * 64, "title": FEED["title"],
    "content": FEED["content"], "url": FEED["url"], "published_at": FEED["published_at"],
    "received_at": "2026-10-07T12:00:00Z", "availability_witness_at": None, "is_fixture": True},
    "approved_thesis": {"thesis_id": THESIS, "thesis_version_id": "531c54cb-7e51-497e-a8f5-67fcb5c9d42f",
    "approval_id": APPROVAL, "interpretation_id": "c6c16880-f11c-46a7-ad7e-1a30c62f80f4",
    "exact_text": EXACT, **MEANING}, "positions": POSITIONS}


def result(*, status="analysed", disposition="current"):
    empty = status == "queue_empty"
    return {"analysis": {"id": None if empty else ATTEMPT, "status": status,
        "current_disposition": "queue_empty" if empty else disposition, "replayed": False,
        "source_revision_id": None if empty else REVISION, "provider": "nanogpt", "model_id": MODEL,
        "created_at": None if empty else "2026-10-07T12:01:00Z", "finished_at": None,
        "context": None if empty else copy.deepcopy(CONTEXT),
        "document": copy.deepcopy(DOCUMENT) if status in {"analysed", "stale"} else None,
        "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        "reported_cost_usd": None, "estimated_cost_usd": None, "reported_model": None,
        "provider_request_id": None, "latency_ms": None, "stop_reason": None,
        "stale_reasons": [], "limitations": ["This is fictional news, not a current macro regime."],
        "unresolved_attempt_count": 2}}


def answers(values):
    values = iter(values)
    return lambda prompt: next(values)


class Client:
    def __init__(self, *, response=None, fail=False):
        self.calls = []
        self.logged_out = False
        self.response = response if response is not None else result()
        self.fail = fail

    def login(self, username, password):
        pass

    def logout(self):
        self.logged_out = True

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if "/news-commands/" in path:
            if self.fail:
                raise review.WalkthroughError("saved item or endpoint unavailable")
            return copy.deepcopy(self.response)
        if path.endswith("/news-context/"):
            return copy.deepcopy(PREVIEW)
        if path == "/api/v1/news/sources/":
            return {"sources": [{"id": SOURCE, "label": "Fictional example", "kind": "fictional_fixture",
                "current_reports": 1}], "limitations": ["Not complete coverage."]}
        if path == "/api/v1/models/":
            return {"provider": "nanogpt", "compilation_enabled": True, "credentials_configured": True,
                "models": [{"id": MODEL}], "fetched_at": "2026-10-07T12:00:00Z"}
        if path.endswith("/analyse-next/"):
            if self.fail:
                raise review.WalkthroughError("response unavailable")
            return copy.deepcopy(self.response)
        raise AssertionError(path)


class NewsReviewTests(unittest.TestCase):
    def run_one(self, client, values, path, *, say=lambda value: None):
        journal = review.ReviewJournal(path)
        try:
            return review.review_one(client, THESIS, journal, requested_source=SOURCE,
                requested_model=MODEL, ask=answers(values), secret=lambda prompt: "private-password", say=say)
        finally:
            journal.close()

    def test_one_automatic_selection_request_records_complete_pinned_inputs_and_manual_review(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.jsonl"
            client = Client()
            displayed = []
            output = self.run_one(client, ["trader", "run", "review", "good", "good", "uncertain", "good", "Useful divergent paths."], path, say=displayed.append)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(records[0]["detail"]["approved_exact_text"], EXACT)
            requested = next(item for item in records if item["kind"] == "analysis_requested")["detail"]
            self.assertEqual(requested["request"]["expected_approval_id"], APPROVAL)
            self.assertEqual(requested["request"]["expected_exposure_digest"], PREVIEW["exposure_digest"])
            self.assertNotIn("source_revision_id", requested["request"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertNotIn("private-password", path.read_text())
        self.assertEqual(output["status"], "reviewed")
        self.assertEqual(output["ratings"]["uncertainty"], "uncertain")
        self.assertEqual([path for method, path, body in client.calls if method == "POST"],
                         [f"/api/v1/theses/{THESIS}/analyse-next/"])
        self.assertTrue(client.logged_out)
        self.assertTrue(any("Open-trade relevance" in line for line in displayed))
        self.assertTrue(any("medium-term" in line for line in displayed))

    def test_cancel_makes_no_analysis_or_other_write(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Client()
            self.assertIsNone(self.run_one(client, ["trader", ""], Path(directory) / "cancel.jsonl"))
        self.assertFalse(any(method == "POST" for method, path, body in client.calls))
        self.assertTrue(client.logged_out)

    def test_unknown_transport_outcome_keeps_request_identity_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lost.jsonl"
            client = Client(fail=True)
            with self.assertRaisesRegex(review.WalkthroughError, "unknown"):
                self.run_one(client, ["trader", "run"], path)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            command = next(item for item in records if item["kind"] == "analysis_requested")["detail"]["request"]
            self.assertEqual(records[-1]["kind"], "response_unavailable")
            self.assertEqual(records[-1]["detail"]["command_id"], command["command_id"])
        self.assertEqual(sum(method == "POST" for method, path, body in client.calls), 1)
        self.assertTrue(client.logged_out)

    def test_stale_failed_unknown_running_and_empty_queue_are_never_quality_graded(self):
        for status, disposition in (("stale", "stale"), ("analysed", "stale"), ("failed", "unresolved"),
                ("outcome_unknown", "unresolved"), ("running", "unresolved"), ("queue_empty", "queue_empty")):
            with self.subTest(status=status, disposition=disposition), tempfile.TemporaryDirectory() as directory:
                client = Client(response=result(status=status, disposition=disposition))
                output = self.run_one(client, ["trader", "run"], Path(directory) / "unresolved.jsonl")
                self.assertEqual(output["status"], "not_reviewable")
                self.assertIsNone(output["ratings"])
                self.assertEqual(sum(method == "POST" for method, path, body in client.calls), 1)

    def test_mismatched_approval_book_source_or_model_cannot_be_reviewed(self):
        mutations = [
            lambda output: output["analysis"].update(model_id="other/model"),
            lambda output: output["analysis"]["context"]["approved_thesis"].update(approval_id=ATTEMPT),
            lambda output: output["analysis"]["context"]["approved_thesis"].update(exact_text="Changed"),
            lambda output: output["analysis"]["context"].update(positions=[]),
            lambda output: output["analysis"]["context"]["source"].update(source_key="other-source"),
        ]
        for mutation in mutations:
            output = result()
            mutation(output)
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                client = Client(response=output)
                with self.assertRaises(review.WalkthroughError):
                    self.run_one(client, ["trader", "run"], Path(directory) / "mismatch.jsonl")
                self.assertTrue(client.logged_out)

    def test_invented_quotation_cannot_be_reviewed(self):
        output = result()
        output["analysis"]["document"]["attributed_facts"][0]["exact_quote"] = "An invented price movement."
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "exact retained"):
                self.run_one(Client(response=output), ["trader", "run"], Path(directory) / "invented.jsonl")

    def test_journal_failure_before_transmission_blocks_analysis(self):
        class FailedJournal:
            def append(self, kind, detail):
                if kind == "analysis_requested":
                    raise review.WalkthroughError("journal cannot be saved")
        client = Client()
        with self.assertRaisesRegex(review.WalkthroughError, "journal"):
            review.review_one(client, THESIS, FailedJournal(), requested_source=SOURCE,
                requested_model=MODEL, ask=answers(["trader", "run"]),
                secret=lambda prompt: "private", say=lambda value: None)
        self.assertFalse(any(method == "POST" for method, path, body in client.calls))
        self.assertTrue(client.logged_out)

    def test_terminal_controls_in_report_and_questions_are_escaped(self):
        output = result()
        output["analysis"]["context"]["source"]["title"] += "\x1b]52;c;clipboard\x07"
        output["analysis"]["document"]["trader_questions"].append("Question\x1b[31mred\x07")
        displayed = []
        with tempfile.TemporaryDirectory() as directory:
            self.run_one(Client(response=output), ["trader", "run", ""], Path(directory) / "controls.jsonl", say=displayed.append)
        self.assertNotIn("\x1b", "\n".join(displayed))
        self.assertNotIn("\x07", "\n".join(displayed))
        self.assertIn("\\u001b", "\n".join(displayed))

    def test_interrupted_review_keeps_completed_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interrupted.jsonl"
            journal = review.ReviewJournal(path)
            iterator = iter(["trader", "run", "review", "good"])
            def interrupted(prompt):
                try:
                    return next(iterator)
                except StopIteration:
                    raise EOFError
            client = Client()
            try:
                with self.assertRaises(EOFError):
                    review.review_one(client, THESIS, journal, requested_source=SOURCE,
                        requested_model=MODEL, ask=interrupted, secret=lambda prompt: "private", say=lambda value: None)
            finally:
                journal.close()
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(records[-1]["kind"], "review_dimension")
            self.assertFalse(any(item["kind"] == "review" for item in records))
            self.assertTrue(client.logged_out)

    def test_unsupported_source_is_rejected_before_model_request(self):
        client = Client()
        with self.assertRaisesRegex(review.WalkthroughError, "requested source"):
            review.select_source(client, requested="missing", say=lambda value: None)
        self.assertEqual(len(client.calls), 1)

    def test_command_recovery_reads_historical_context_without_catalogue_or_post(self):
        output = result(disposition="stale")
        output["analysis"]["context"]["approved_thesis"]["exact_text"] = "Historical approved meaning."
        client = Client(response=output)
        displayed = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recovery.jsonl"
            journal = review.ReviewJournal(path)
            try:
                recovered = review.recover_one(client, THESIS, APPROVAL, journal,
                    ask=answers(["trader"]), secret=lambda prompt: "private-password", say=displayed.append)
            finally:
                journal.close()
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([record["kind"] for record in records], ["recovery_requested", "recovery_response"])
            self.assertEqual(records[0]["detail"]["command_id"], APPROVAL)
            self.assertNotIn("private-password", path.read_text())
        self.assertEqual(recovered["analysis"]["current_disposition"], "stale")
        self.assertEqual(client.calls, [("GET", f"/api/v1/theses/{THESIS}/news-commands/{APPROVAL}/", None)])
        self.assertTrue(client.logged_out)
        self.assertTrue(any("historical" in line for line in displayed))

    def test_absent_command_receipt_never_falls_back_to_paid_post(self):
        client = Client(fail=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing-receipt.jsonl"
            journal = review.ReviewJournal(path)
            try:
                with self.assertRaisesRegex(review.WalkthroughError, "No model request or POST fallback"):
                    review.recover_one(client, THESIS, APPROVAL, journal, ask=answers(["trader"]),
                        secret=lambda prompt: "private", say=lambda value: None)
            finally:
                journal.close()
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(records[-1]["kind"], "recovery_unavailable")
        self.assertEqual([method for method, path, body in client.calls], ["GET"])
        self.assertTrue(client.logged_out)

    def test_empty_queue_and_unknown_attempt_recovery_do_not_initiate_work(self):
        for status in ("queue_empty", "outcome_unknown", "running"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                client = Client(response=result(status=status, disposition="unresolved"))
                journal = review.ReviewJournal(Path(directory) / "unresolved-recovery.jsonl")
                try:
                    review.recover_one(client, THESIS, APPROVAL, journal, ask=answers(["trader"]),
                        secret=lambda prompt: "private", say=lambda value: None)
                finally:
                    journal.close()
                self.assertEqual([method for method, path, body in client.calls], ["GET"])

    def test_recovery_rejects_foreign_thesis_or_invented_attribution_without_fallback(self):
        for field in ("thesis", "quotation"):
            output = result()
            if field == "thesis":
                output["analysis"]["context"]["approved_thesis"]["thesis_id"] = ATTEMPT
            else:
                output["analysis"]["document"]["attributed_facts"][0]["exact_quote"] = "Invented."
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                client = Client(response=output)
                journal = review.ReviewJournal(Path(directory) / "invalid-recovery.jsonl")
                try:
                    with self.assertRaises((review.WalkthroughError, ValueError)):
                        review.recover_one(client, THESIS, APPROVAL, journal, ask=answers(["trader"]),
                            secret=lambda prompt: "private", say=lambda value: None)
                finally:
                    journal.close()
                self.assertEqual([method for method, path, body in client.calls], ["GET"])
                self.assertTrue(client.logged_out)


if __name__ == "__main__":
    unittest.main()
