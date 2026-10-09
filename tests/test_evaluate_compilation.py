"""One-call research review preserves uncertainty and cannot approve a thesis."""

import copy
import importlib.util
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location("evaluate_compilation", ROOT / "tools" / "evaluate_compilation.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)

from macro_agent.domain.compilation_evaluation import REVIEW_RUBRIC

THESIS = "05ab1e58-8390-4b8f-b86a-8c3f031be88e"
TEXT = "f1139469-dba6-4a98-af0c-95f3e778719f"
MEANING = "c6c16880-f11c-46a7-ad7e-1a30c62f80f4"
MODEL = "example/model"
EXACT = "  Gold may benefit if real yields fall.\r\nΔ\r\n"
CASE = {"id": "user-input", "title": "Exact trader input", "instrument": "unverified",
        "tags": ["user_supplied"], "exact_text": EXACT,
        "review_questions": ["Are the user's qualifiers retained?"]}
RUBRIC = [{"id": key, "question": question} for key, question in REVIEW_RUBRIC]


def answers(values):
    values = iter(values)
    return lambda prompt: next(values)


class Client:
    def __init__(self, *, state="compiled", current=True, fail=False, mismatch=False):
        self.state, self.current, self.fail, self.mismatch = state, current, fail, mismatch
        self.calls = []
        self.logged_out = False

    def login(self, username, password):
        pass

    def logout(self):
        self.logged_out = True

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/v1/models/":
            return {"provider": "nanogpt", "compilation_enabled": True, "credentials_configured": True,
                    "models": [{"id": MODEL, "name": "Recorded model"}]}
        if path == "/api/v1/theses/":
            self.thesis = {"id": THESIS, "revision": 1, "approved": None, "draft": {
                "text_version": {"id": TEXT, "exact_text": body["text"], "text_digest": "a" * 64},
                "interpretation": {"id": MEANING, "origin": "user_supplied", "digest": "b" * 64,
                                   **body["interpretation"]}}}
            return {"thesis": copy.deepcopy(self.thesis)}
        if path.endswith("/compile/"):
            if self.fail:
                raise review.WalkthroughError("The response is unavailable; outcome and cost are unknown.")
            meaning = {"drivers": ["Gold may benefit if real yields fall."], "horizon": None,
                       "invalidation_signposts": []}
            doc = {"interpretation": meaning, "grounding": [{"field": "drivers", "index": 0, "input_id": "thesis",
                    "exact_quote": "Gold may benefit if real yields fall."}],
                   "refinement_issues": [], "agent_hypotheses": [], "counter_case": None,
                   "review_card": {key: {"extracted": [], "proposed": [], "gap": "Not supplied."}
                       for key in ("claim", "affected_assets", "causal_path", "assumptions", "catalysts", "scenarios", "monitoring_scope")}}
            if self.state == "compiled":
                self.thesis["revision"] += 1
                self.thesis["draft"]["interpretation"] = {"id": MEANING,
                    "origin": "model_compilation", "digest": "c" * 64, **meaning,
                    "review_card": {"schema_version": "thesis-review-card-v1",
                        "inputs": [{"input_id": "thesis", "exact_text": EXACT}],
                        "document": copy.deepcopy(doc), "evidence": {"status": "unavailable", "references": []}}}
            if self.mismatch:
                doc["interpretation"]["horizon"] = "Ten weeks"
                doc["grounding"].append({"field": "horizon", "index": None, "input_id": "thesis",
                                         "exact_quote": "Gold"})
            return {"thesis": copy.deepcopy(self.thesis), "compilation": {
                "id": TEXT, "provider": "nanogpt", "model_id": MODEL,
                "status": self.state, "is_current_draft": self.current,
                "interpretation_version_id": MEANING if self.state == "compiled" else None,
                "document": doc if self.state == "compiled" else None}}
        raise AssertionError("Unexpected endpoint: " + path)


class OneThesisReviewTests(unittest.TestCase):
    def run_case(self, client, values, path):
        journal = review.ReviewJournal(path)
        try:
            return review.evaluate_one(client, CASE, RUBRIC, journal, requested_model=MODEL,
                ask=answers(values), secret=lambda prompt: "never-record-password", say=lambda value: None)
        finally:
            journal.close()

    def test_review_records_exact_input_baseline_and_only_manual_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.jsonl"
            client = Client()
            ratings = ["good", "uncertain", "poor", "uncertain", "good"]
            result = self.run_case(client, ["trader", "run", "review", *ratings, "baseline", "Model missed qualifiers."], path)
            text = path.read_text()
            records = [json.loads(line) for line in text.splitlines()]
            self.assertEqual(records[0]["detail"]["case"]["exact_text"], EXACT)
            self.assertEqual(records[0]["detail"]["baseline"]["exact_text"], EXACT)
            self.assertEqual(result["comparison"], "baseline")
            self.assertEqual(list(result["ratings"].values()), ratings)
            self.assertNotIn("never-record-password", text)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        posts = [path for method, path, body in client.calls if method == "POST"]
        self.assertEqual(posts, ["/api/v1/theses/", f"/api/v1/theses/{THESIS}/compile/"])
        self.assertTrue(client.logged_out)
        self.assertIsNone(client.thesis["approved"])

    def test_cancel_before_run_makes_no_draft_or_model_request(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Client()
            self.run_case(client, ["trader", ""], Path(directory) / "cancel.jsonl")
        self.assertEqual([item[0] for item in client.calls], ["GET"])
        self.assertTrue(client.logged_out)

    def test_operational_failures_and_stale_disposition_have_no_quality_grade(self):
        for state, current in (("failed", True), ("outcome_unknown", True), ("running", True),
                               ("stale", True), ("compiled", False)):
            with self.subTest(state=state, current=current), tempfile.TemporaryDirectory() as directory:
                client = Client(state=state, current=current)
                result = self.run_case(client, ["trader", "run"], Path(directory) / "unknown.jsonl")
                self.assertEqual(result["status"], "not_reviewable")
                self.assertIsNone(result["ratings"])
                self.assertEqual(sum(path.endswith("/compile/") for _, path, _ in client.calls), 1)

    def test_transport_failure_retains_request_identity_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lost.jsonl"
            client = Client(fail=True)
            with self.assertRaises(review.WalkthroughError):
                self.run_case(client, ["trader", "run"], path)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            requested = next(record for record in records if record["kind"] == "compile_requested")
            self.assertEqual(requested["detail"]["thesis_id"], THESIS)
            self.assertEqual(requested["detail"]["request"]["provider_id"], "nanogpt")
            self.assertEqual(records[-1]["detail"]["review"]["status"], "not_reviewable")
        self.assertTrue(client.logged_out)
        self.assertEqual(sum(path.endswith("/compile/") for _, path, _ in client.calls), 1)

    def test_disagreement_between_document_and_draft_is_not_reviewed(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Client(mismatch=True)
            with self.assertRaisesRegex(review.WalkthroughError, "disagree"):
                self.run_case(client, ["trader", "run"], Path(directory) / "mismatch.jsonl")
        self.assertTrue(client.logged_out)

    def test_new_draft_text_during_inference_keeps_stale_outcome_and_no_grade(self):
        class ChangedDraftClient(Client):
            def request(self, method, path, body=None):
                result = super().request(method, path, body)
                if path.endswith("/compile/"):
                    result["thesis"]["draft"]["text_version"]["exact_text"] = "A newer trader view."
                    result["thesis"]["revision"] += 1
                return result
        with tempfile.TemporaryDirectory() as directory:
            client = ChangedDraftClient(state="stale", current=False)
            result = self.run_case(client, ["trader", "run"], Path(directory) / "stale.jsonl")
        self.assertEqual(result, {"status": "not_reviewable", "attempt_status": "stale", "ratings": None})
        self.assertTrue(client.logged_out)

    def test_custom_rubric_control_sequences_are_escaped_in_terminal(self):
        displayed = []
        question = "Review this\x1b]52;c;clipboard\x07"
        rating = review._rating(question, answers(["uncertain"]), displayed.append)
        self.assertEqual(rating, "uncertain")
        self.assertNotIn("\x1b", displayed[0])
        self.assertNotIn("\x07", displayed[0])
        self.assertIn("\\u001b", displayed[0])

    def test_interrupted_review_keeps_response_and_individual_completed_ratings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interrupted.jsonl"
            journal = review.ReviewJournal(path)
            client = Client()
            iterator = iter(["trader", "run", "review", "good"])
            def interrupted(prompt):
                try:
                    return next(iterator)
                except StopIteration:
                    raise EOFError
            try:
                with self.assertRaises(EOFError):
                    review.evaluate_one(client, CASE, RUBRIC, journal, requested_model=MODEL,
                        ask=interrupted, secret=lambda prompt: "password", say=lambda value: None)
            finally:
                journal.close()
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertIn("compile_response", [record["kind"] for record in records])
            self.assertEqual(records[-1]["kind"], "review_dimension")
            self.assertNotIn("review", [record["kind"] for record in records])
        self.assertTrue(client.logged_out)

    def test_journal_failure_before_transmission_blocks_model_request(self):
        class FailingJournal:
            def append(self, kind, detail):
                if kind == "compile_requested":
                    raise review.WalkthroughError("journal cannot be saved")
        client = Client()
        with self.assertRaisesRegex(review.WalkthroughError, "journal"):
            review.evaluate_one(client, CASE, RUBRIC, FailingJournal(), requested_model=MODEL,
                ask=answers(["trader", "run"]), secret=lambda prompt: "password", say=lambda value: None)
        self.assertFalse(any(path.endswith("/compile/") for _, path, _ in client.calls))
        self.assertTrue(client.logged_out)

    def test_existing_review_file_and_symlink_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "existing.jsonl"
            existing.write_text("preserve")
            linked = Path(directory) / "link.jsonl"
            linked.symlink_to(existing)
            for path in (existing, linked):
                with self.subTest(path=path), self.assertRaises(review.WalkthroughError):
                    review.ReviewJournal(path)
            self.assertEqual(existing.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
