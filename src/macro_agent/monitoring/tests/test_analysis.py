"""Private news-analysis admissions, independent PostgreSQL races and replay."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.monitoring import analysis, capture, news_context
from macro_agent.monitoring.models import (
    NewsAnalysisAttempt, NewsAnalysisResult, NewsReviewReceipt, SourceReport, SourceState,
)
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.positions import service as positions
from macro_agent.providers import ProviderError
from macro_agent.theses import compilation, service as theses
from macro_agent.theses.models import CompilationAttempt, ThesisRecord


MODEL = "example/cheap"
SOURCE = "fixture-news-analysis"
CONTRACT = {"kind": "fictional_fixture", "label": "Fictional analytical feed",
            "coverage": "bounded_snapshot"}
EXACT = "  Easier policy may support equities.\r\nΔ\r\n"
MEANING = {"drivers": ["Easier policy"], "horizon": "medium term",
           "invalidation_signposts": ["Policy transmission fails"]}
DECLARATION = {"underlying": "  NQ Δ  ", "direction": "long", "quantity": None,
    "quantity_unit": None, "horizon": None, "product_id": None, "venue": None,
    "expiry": None, "quote_currency": None}
QUOTE = ("The fictional central bank cut its policy rate and opened a temporary "
         "liquidity facility following reports of funding stress.")
FIXTURE = Path(__file__).resolve().parents[4] / "fixtures" / "news_analysis_response.json"


def independent(function):
    connections.close_all()
    try:
        return function()
    finally:
        connections.close_all()


class RecordedProvider:
    def __init__(self, callback=None):
        self.callback = callback
        self.calls = 0
        self.catalog_calls = 0
        self.messages = None

    def list_models(self):
        self.catalog_calls += 1
        if connection.in_atomic_block:
            raise AssertionError("Catalogue must not hold database protection")
        return {"fetched_at": timezone.now().isoformat(), "models": [{"id": MODEL,
            "name": "Recorded research model", "context_length": 32768,
            "input_price_usd_per_million": None, "output_price_usd_per_million": None,
            "capabilities": {"chat_completions": True}}]}

    def complete(self, model_id, messages):
        self.calls += 1
        self.messages = deepcopy(messages)
        if connection.in_atomic_block:
            raise AssertionError("Inference must not retain a transaction or locks")
        if self.callback:
            self.callback()
        context = json.loads(messages[1]["content"])
        document = json.loads(FIXTURE.read_text())
        revision = context["source"]["revision_id"]
        ids = [row["position_id"] for row in context["positions"] if row["status"] == "open"]
        document["attributed_facts"][0]["source_revision_id"] = revision
        document["trade_route"]["position_ids"] = ids
        document["hypotheses"][0]["position_ids"] = ids
        if not ids:
            document["trade_route"]["status"] = "not_identified"
        return {"content": json.dumps(document), "reported_model": model_id,
            "provider_request_id": "recorded-news-request", "usage": {
                "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "reported_cost_usd": None, "finish_reason": "stop", "latency_ms": 1}


class RecordedCompilationProvider(RecordedProvider):
    def complete(self, model_id, messages):
        self.calls += 1
        if connection.in_atomic_block:
            raise AssertionError("Inference must not hold database protection")
        from macro_agent.domain.compilation import SECTIONS
        document = {"interpretation": MEANING, "grounding": [
            {"field": "drivers", "input_id": "thesis", "index": 0, "exact_quote": "Easier policy"},
            {"field": "horizon", "input_id": "thesis", "index": None, "exact_quote": "Easier policy"},
            {"field": "invalidation_signposts", "input_id": "thesis", "index": 0, "exact_quote": "Easier policy"}],
            "refinement_issues": [], "agent_hypotheses": [],
            "counter_case": "Unverified: policy transmission may fail.",
            "review_card": {name: {"extracted": [], "proposed": [],
                "gap": "Not resolved in the recorded response."} for name in SECTIONS}}
        return {"content": json.dumps(document), "usage": compilation.UNKNOWN_USAGE,
                "reported_cost_usd": None}


@override_settings(MACRO_ENABLE_NEWS_ANALYSIS=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ALLOW_SYNTHETIC_SETUP=True, MACRO_ENABLE_MODEL_COMPILATION=True,
    MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="recorded-test-key",
    SETTINGS_MODULE="macro_agent.web.local_settings")
class PostgreSQLNewsAnalysisTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("News-analysis races require PostgreSQL")
        self.owner = get_user_model().objects.create_user(username="news-owner")
        self.other = get_user_model().objects.create_user(username="news-other")
        self.actor = str(self.owner.pk)
        draft = theses.create_thesis(self.actor, str(uuid4()), EXACT, MEANING)["thesis"]
        self.thesis = self.approve(draft)["thesis"]
        self.position = positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
            self.approval_id, DECLARATION)["position"]
        self.provider = RecordedProvider()
        self.capture_item()

    @property
    def approval_id(self):
        return self.thesis["approved"]["approval"]["id"]

    def approve(self, draft, *, clock=timezone.now):
        text, meaning = draft["draft"]["text_version"], draft["draft"]["interpretation"]
        return theses.approve_thesis(self.actor, draft["id"], str(uuid4()), text["id"],
            text["text_digest"], meaning["id"], meaning["digest"], draft["revision"], clock=clock)

    def item(self, native="report-1", title="Fictional policy and funding announcement"):
        return SourceItem(native, title, "https://example.invalid/retained-report",
            timezone.now() - timedelta(days=1), "  " + QUOTE + "\r\nΔ\r\n")

    def batch(self, *items):
        return SourceBatch(tuple(items), timezone.now(), "bounded_snapshot", False,
                           sha256(b"recorded news transport").hexdigest())

    def capture_item(self, native="report-1", title="Fictional policy and funding announcement"):
        return capture.capture(SOURCE, CONTRACT, lambda: self.batch(self.item(native, title)))

    def reviewed(self):
        return news_context.review_context(self.actor, self.thesis["id"])

    def analyse(self, command=None, *, reviewed=None, **kwargs):
        reviewed = reviewed or self.reviewed()
        return analysis.analyse_next(self.actor, self.thesis["id"], command or str(uuid4()),
            reviewed["approval_id"], reviewed["exposure_digest"], SOURCE, MODEL, "nanogpt",
            provider=self.provider, **kwargs)

    def inspect(self, result):
        return analysis.get_analysis(self.actor, self.thesis["id"], result["analysis"]["id"])

    def revise_position(self, *, clock=timezone.now):
        current = positions.get_position(self.actor, self.position["id"])
        return positions.revise_position(self.actor, self.position["id"], str(uuid4()),
            current["revision"], self.reviewed()["approval_id"],
            {**DECLARATION, "quantity": "2", "quantity_unit": "paper contracts"}, clock=clock)

    def replace_approval(self, *, clock=timezone.now):
        current = theses.get_thesis(self.actor, self.thesis["id"])
        draft = theses.propose_thesis(self.actor, self.thesis["id"], str(uuid4()),
            EXACT + " New approved horizon.", MEANING, current["revision"])["thesis"]
        return self.approve(draft, clock=clock)

    def db_guard(self, function):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                function()

    def server_lock_wait(self, waiter_pid, blocker_pid, table, *, timeout=5):
        deadline, observed = monotonic() + timeout, None
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT state, wait_event_type, query, pg_blocking_pids(pid) "
                    "FROM pg_stat_activity WHERE pid = %s", [waiter_pid])
                observed = cursor.fetchone()
            if (observed and observed[0] == "active" and observed[1] == "Lock"
                    and "FOR UPDATE" in observed[2] and table in observed[2]
                    and blocker_pid in observed[3]):
                return
            sleep(0.01)
        self.fail(f"Expected an actual PostgreSQL protection wait: {observed!r}")

    def test_exact_approved_state_attributed_evidence_and_separate_trade_path(self):
        before = theses.get_thesis(self.actor, self.thesis["id"])
        result = self.analyse()["analysis"]
        self.assertEqual(result["status"], "analysed")
        self.assertEqual(result["current_disposition"], "current")
        self.assertEqual(result["context"]["approved_thesis"]["exact_text"], EXACT)
        self.assertEqual(result["context"]["positions"][0]["underlying"], DECLARATION["underlying"])
        self.assertIsNone(result["context"]["positions"][0]["quantity"])
        self.assertIn("quantity", result["context"]["positions"][0]["missing_fields"])
        doc = result["document"]
        self.assertEqual(doc["thesis_route"]["status"], "potential")
        self.assertIn("support", doc["thesis_route"]["explanation"])
        self.assertEqual(doc["trade_route"]["status"], "potential")
        self.assertIn("adverse", doc["trade_route"]["explanation"])
        self.assertEqual(doc["attributed_facts"][0]["exact_quote"], QUOTE)
        self.assertEqual(theses.get_thesis(self.actor, self.thesis["id"]), before)
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertIsNone(result["reported_cost_usd"])
        self.assertIsNone(result["estimated_cost_usd"])

    def test_inference_sees_a_committed_immutable_admission_outside_transaction(self):
        def callback():
            with ThreadPoolExecutor(max_workers=1) as pool:
                row = pool.submit(independent, lambda: NewsAnalysisAttempt.objects.get()).result(timeout=10)
            self.assertEqual(row.owner_id, self.owner.pk)
            self.assertFalse(NewsAnalysisResult.objects.exists())
            self.assertEqual(row.prompt_digest, text_digest(canonical_json(self.provider.messages)))
        self.provider.callback = callback
        self.analyse()
        self.assertEqual(self.provider.calls, 1)

    def test_auto_selection_skips_obsolete_heads_and_already_admitted_reports(self):
        self.capture_item(title="Changed observed payload")
        self.capture_item(native="report-2")
        first = self.analyse()["analysis"]
        current = SourceReport.objects.get(source_id=SOURCE, native_id="report-1").current_revision_id
        self.assertEqual(first["source_revision_id"], str(current))
        self.assertEqual(first["context"]["source"]["title"], "Changed observed payload")
        second = self.analyse()["analysis"]
        self.assertEqual(second["context"]["source"]["native_id"], "report-2")
        self.assertEqual(self.analyse()["analysis"]["status"], "queue_empty")
        self.assertEqual(self.provider.calls, 2)

    def test_same_command_is_history_after_source_change_without_respending(self):
        command, reviewed = str(uuid4()), self.reviewed()
        first = self.analyse(command, reviewed=reviewed)
        self.capture_item(title="Changed observed payload")
        again = self.analyse(command, reviewed=reviewed)["analysis"]
        self.assertTrue(again["replayed"])
        self.assertEqual(again["id"], first["analysis"]["id"])
        self.assertEqual(again["status"], "analysed")
        self.assertEqual(again["current_disposition"], "stale")
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.provider.catalog_calls, 1)

    def test_empty_command_stays_empty_when_new_news_arrives(self):
        self.analyse()
        command = str(uuid4())
        first = self.analyse(command)["analysis"]
        self.assertEqual(first["status"], "queue_empty")
        self.capture_item(native="report-2")
        again = self.analyse(command)["analysis"]
        self.assertEqual(again["status"], "queue_empty")
        self.assertTrue(again["replayed"])
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.analyse()["analysis"]["status"], "analysed")

    def test_missing_command_inspection_has_no_receipt_or_model_side_effect(self):
        before = (NewsReviewReceipt.objects.count(), NewsAnalysisAttempt.objects.count())
        with self.assertRaises(news_context.NewsMissing):
            analysis.get_news_command(self.actor, self.thesis["id"], str(uuid4()))
        self.assertEqual((NewsReviewReceipt.objects.count(), NewsAnalysisAttempt.objects.count()), before)
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.provider.catalog_calls, 0)

    def test_command_inspection_preserves_success_and_empty_history_after_new_inputs(self):
        success_command, empty_command = str(uuid4()), str(uuid4())
        first = self.analyse(success_command)
        self.assertEqual(self.analyse(empty_command)["analysis"]["status"], "queue_empty")
        self.capture_item(title="Changed observed payload")
        self.revise_position()
        before = (NewsReviewReceipt.objects.count(), NewsAnalysisAttempt.objects.count(), self.provider.calls)
        success = analysis.get_news_command(self.actor, self.thesis["id"], success_command)["analysis"]
        empty = analysis.get_news_command(self.actor, self.thesis["id"], empty_command)["analysis"]
        self.assertEqual(success["id"], first["analysis"]["id"])
        self.assertEqual(success["status"], "analysed")
        self.assertEqual(success["current_disposition"], "stale")
        self.assertEqual(empty["status"], "queue_empty")
        self.assertEqual((NewsReviewReceipt.objects.count(), NewsAnalysisAttempt.objects.count(), self.provider.calls), before)
        with self.assertRaises(PermissionError):
            analysis.get_news_command(str(self.other.pk), self.thesis["id"], success_command)

    def test_source_permission_withdrawal_preserves_history_but_blocks_new_analysis(self):
        command = str(uuid4())
        result = self.analyse(command)
        reviewed = self.reviewed()
        with override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=False,
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            responses = (self.inspect(result),
                analysis.get_news_command(self.actor, self.thesis["id"], command))
            for response in responses:
                record = response["analysis"]
                self.assertEqual(record["status"], "analysed")
                self.assertEqual(record["document"], result["analysis"]["document"])
                self.assertEqual(record["current_disposition"], "stale")
                self.assertIn("source_contract_unavailable", record["stale_reasons"])
            with self.assertRaises(news_context.NewsMissing):
                self.analyse(reviewed=reviewed)
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.provider.catalog_calls, 1)
        self.assertEqual(NewsAnalysisAttempt.objects.count(), 1)

    def test_provider_failure_is_unresolved_and_new_command_does_not_repeat_spend(self):
        for code, expected in (("unavailable", "failed"), ("outcome_unknown", "outcome_unknown")):
            with self.subTest(code=code):
                self.capture_item(native=code)
                with patch.object(self.provider, "complete", side_effect=ProviderError(code)):
                    result = self.analyse()["analysis"]
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["current_disposition"], "unresolved")
                self.assertIsNone(result["document"])
                self.assertIsNone(result["estimated_cost_usd"])
        self.analyse()
        before = NewsAnalysisAttempt.objects.count()
        self.assertEqual(self.analyse()["analysis"]["status"], "queue_empty")
        self.assertEqual(NewsAnalysisAttempt.objects.count(), before)

    def test_invalid_output_preserves_usage_without_retiring_source_work(self):
        with patch.object(self.provider, "complete", return_value={"content": "{malformed}",
            "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}}):
            result = self.analyse()["analysis"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["current_disposition"], "unresolved")
        self.assertEqual(result["usage"]["total_tokens"], 17)
        self.assertIsNone(result["document"])
        self.assertEqual(SourceReport.objects.get(source_id=SOURCE).current_revision.screeningwork.state, "pending")
        self.assertEqual(self.analyse()["analysis"]["status"], "queue_empty")

    def test_crash_admission_survives_restart_and_never_automatically_retries(self):
        command = str(uuid4())
        with patch.object(self.provider, "complete", side_effect=RuntimeError("process stopped")):
            with self.assertRaisesMessage(RuntimeError, "process stopped"):
                self.analyse(command)
        attempt = NewsAnalysisAttempt.objects.get()
        self.assertFalse(NewsAnalysisResult.objects.exists())
        with ThreadPoolExecutor(max_workers=1) as pool:
            again = pool.submit(independent, lambda: self.analyse(command,
                clock=lambda: attempt.deadline_at + timedelta(seconds=1))).result(timeout=10)
        self.assertEqual(again["analysis"]["status"], "outcome_unknown")
        self.assertEqual(again["analysis"]["current_disposition"], "unresolved")
        self.assertEqual(self.provider.catalog_calls, 1)
        self.assertEqual(self.analyse()["analysis"]["status"], "queue_empty")
        self.assertEqual(NewsAnalysisAttempt.objects.count(), 1)

    def test_late_completion_is_uncertain_even_without_other_writers(self):
        calls = 0
        def clock():
            nonlocal calls
            calls += 1
            if calls == 1:
                return timezone.now()
            return NewsAnalysisAttempt.objects.get().deadline_at
        result = self.analyse(clock=clock)["analysis"]
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertEqual(result["stop_reason"], "completion_deadline_exceeded")
        self.assertEqual(result["current_disposition"], "unresolved")

    def assert_admitted_unknown_without_result(self):
        attempt = NewsAnalysisAttempt.objects.get()
        self.assertFalse(NewsAnalysisResult.objects.exists())
        result = analysis.get_analysis(self.actor, self.thesis["id"], str(attempt.pk),
            clock=lambda: attempt.deadline_at + timedelta(seconds=1))["analysis"]
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertEqual(result["current_disposition"], "stale")
        self.assertEqual(self.provider.calls, 1)

    def test_completion_cannot_precede_observed_exposure_effective_time(self):
        def callback():
            self.revise_position(clock=lambda: timezone.now() + timedelta(seconds=5))
        self.provider.callback = callback
        with self.assertRaises(ValueError):
            self.analyse()
        self.assert_admitted_unknown_without_result()

    def test_completion_cannot_precede_current_source_receipt(self):
        def callback():
            attempt = capture.admit_capture(SOURCE, CONTRACT)
            received = timezone.now() + timedelta(seconds=5)
            batch = SourceBatch((self.item(title="Future observed receipt"),), received,
                "bounded_snapshot", False, sha256(b"future receipt").hexdigest())
            capture.commit_batch(attempt.pk, batch, clock=lambda: received + timedelta(seconds=1))
        self.provider.callback = callback
        with self.assertRaises(ValueError):
            self.analyse()
        self.assert_admitted_unknown_without_result()

    def test_changes_during_unlocked_inference_retain_stale_history(self):
        mutations = ((lambda: self.capture_item(title="Changed observed payload"), "observed_source_revision_changed"),
            (self.revise_position, "paper_exposure_changed"),
            (self.replace_approval, "approved_meaning_changed"))
        for index, (mutate, reason) in enumerate(mutations):
            with self.subTest(reason=reason):
                self.capture_item(native=f"race-{index}")
                def callback():
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        pool.submit(independent, mutate).result(timeout=10)
                self.provider.callback = callback
                result = self.analyse()["analysis"]
                self.assertEqual(result["status"], "stale")
                self.assertEqual(result["current_disposition"], "stale")
                self.assertIn(reason, result["stale_reasons"])
                self.assertIsNotNone(result["document"])

    def test_draft_only_change_preserves_current_approved_analysis(self):
        def callback():
            current = theses.get_thesis(self.actor, self.thesis["id"])
            theses.propose_thesis(self.actor, self.thesis["id"], str(uuid4()),
                "Unapproved different intent", MEANING, current["revision"])
        self.provider.callback = callback
        result = self.analyse()
        self.assertEqual(result["analysis"]["status"], "analysed")
        self.assertEqual(result["analysis"]["context"]["approved_thesis"]["exact_text"], EXACT)
        self.assertEqual(self.inspect(result)["analysis"]["current_disposition"], "current")

    def test_complete_book_keeps_closed_positions_and_explicit_gaps(self):
        second = positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
            self.approval_id, {**DECLARATION, "underlying": "XAU"})["position"]
        positions.close_position(self.actor, second["id"], str(uuid4()), second["revision"], self.approval_id)
        result = self.analyse()["analysis"]
        book = result["context"]["positions"]
        self.assertEqual(len(book), 2)
        self.assertEqual({row["status"] for row in book}, {"open", "closed"})
        self.assertEqual(result["document"]["trade_route"]["position_ids"], [self.position["id"]])
        self.assertEqual(len(NewsAnalysisAttempt.objects.get().resolved_inputs["user"]["exposure"]["positions"]), 2)

    def test_complete_book_of_two_hundred_is_rejected_before_call_when_oversized(self):
        for index in range(199):
            positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
                self.approval_id, {**DECLARATION, "underlying": f"ES-{index}", "horizon": "h" * 1000})
        reviewed = self.reviewed()
        self.assertEqual(len(reviewed["positions"]), 200)
        with self.assertRaisesMessage(ValueError, "do not truncate"):
            self.analyse(reviewed=reviewed)
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.provider.catalog_calls, 0)
        self.assertFalse(NewsAnalysisAttempt.objects.exists())

    def test_owned_current_approval_and_book_are_required_before_network(self):
        reviewed = self.reviewed()
        self.revise_position()
        with self.assertRaises(news_context.NewsConflict):
            self.analyse(reviewed=reviewed)
        with self.assertRaises(PermissionError):
            analysis.analyse_next(str(self.other.pk), self.thesis["id"], str(uuid4()),
                reviewed["approval_id"], reviewed["exposure_digest"], SOURCE, MODEL,
                "nanogpt", provider=self.provider)
        self.assertEqual(self.provider.catalog_calls, 0)
        self.assertFalse(NewsAnalysisAttempt.objects.exists())

    def test_disabled_owner_and_cross_owner_cannot_read_analysis(self):
        result = self.analyse()
        with self.assertRaises(PermissionError):
            analysis.get_analysis(str(self.other.pk), self.thesis["id"], result["analysis"]["id"])
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
        with self.assertRaises(PermissionError):
            self.inspect(result)

    def test_model_allowance_combines_compilation_and_news_in_both_directions(self):
        with override_settings(MACRO_COMPILATION_OWNER_ATTEMPTS_PER_DAY=1,
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            self.analyse()
            current = theses.get_thesis(self.actor, self.thesis["id"])
            provider = RecordedCompilationProvider()
            with self.assertRaises(compilation.CompilationBudgetExhausted):
                compilation.compile_thesis(self.actor, self.thesis["id"], str(uuid4()),
                    current["revision"], MODEL, "nanogpt", provider=provider)
            self.assertEqual(provider.calls, 0)
        # A different owner avoids reusing the allowance exhausted above.
        actor = str(self.other.pk)
        draft = theses.create_thesis(actor, str(uuid4()), EXACT, MEANING)["thesis"]
        text, meaning = draft["draft"]["text_version"], draft["draft"]["interpretation"]
        approved = theses.approve_thesis(actor, draft["id"], str(uuid4()), text["id"],
            text["text_digest"], meaning["id"], meaning["digest"], draft["revision"])["thesis"]
        with override_settings(MACRO_COMPILATION_OWNER_ATTEMPTS_PER_DAY=1,
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            compilation.compile_thesis(actor, approved["id"], str(uuid4()), approved["revision"],
                MODEL, "nanogpt", provider=RecordedCompilationProvider())
            review = news_context.review_context(actor, approved["id"])
            with self.assertRaises(analysis.NewsBudgetExhausted):
                analysis.analyse_next(actor, approved["id"], str(uuid4()), review["approval_id"],
                    review["exposure_digest"], SOURCE, MODEL, "nanogpt", provider=self.provider)
        self.assertEqual(CompilationAttempt.objects.count(), 1)
        self.assertEqual(NewsAnalysisAttempt.objects.count(), 1)

    def test_aggregate_allowance_counts_other_owners_and_roles(self):
        self.analyse()
        actor = str(self.other.pk)
        draft = theses.create_thesis(actor, str(uuid4()), EXACT, MEANING)["thesis"]
        with override_settings(MACRO_COMPILATION_ATTEMPTS_PER_DAY=1,
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            with self.assertRaises(compilation.CompilationBudgetExhausted):
                compilation.compile_thesis(actor, draft["id"], str(uuid4()), draft["revision"],
                    MODEL, "nanogpt", provider=RecordedCompilationProvider())

    def test_caller_transaction_cannot_hide_admission_or_write_in_inspection(self):
        reviewed = self.reviewed()
        with transaction.atomic():
            with self.assertRaises(RuntimeError):
                self.analyse(reviewed=reviewed)
        result = self.analyse()
        with transaction.atomic():
            with self.assertRaises(RuntimeError):
                self.inspect(result)

    def test_database_preserves_attempt_result_and_scope(self):
        result = self.analyse()
        attempt = NewsAnalysisAttempt.objects.get()
        saved = NewsAnalysisResult.objects.get()
        receipt = NewsReviewReceipt.objects.get()
        for row in (attempt, saved, receipt):
            model = type(row)
            self.db_guard(lambda model=model, row=row: model.objects.filter(pk=row.pk).update(
                **{row._meta.pk.attname: row.pk}))
            def delete(row=row):
                table = connection.ops.quote_name(row._meta.db_table)
                key = connection.ops.quote_name(row._meta.pk.column)
                with connection.cursor() as cursor:
                    cursor.execute(f"DELETE FROM {table} WHERE {key} = %s", [row.pk])
            self.db_guard(delete)
        clone = {field.attname: getattr(attempt, field.attname) for field in attempt._meta.concrete_fields}
        clone.update(id=uuid4(), command_id=uuid4(), owner_id=self.other.pk,
                     exposure_digest="a" * 64)
        self.db_guard(lambda: NewsAnalysisAttempt.objects.create(**clone))
        self.assertEqual(self.inspect(result)["analysis"]["status"], "analysed")

    def test_completion_then_source_change_retains_original_success_and_current_staleness(self):
        self.ordered_source_race(completion_first=True)

    def test_source_change_then_completion_retains_stale_document(self):
        self.ordered_source_race(completion_first=False)

    def ordered_source_race(self, *, completion_first):
        admitted = capture.admit_capture(SOURCE, CONTRACT)
        changed = self.batch(self.item(title="Changed observed payload"))
        held, release, attempted, clock_called, inference = (Event() for _ in range(5))
        holder_pid, waiter_pid = {}, {}
        clock_count = 0

        def completion_clock():
            nonlocal clock_count
            clock_count += 1
            if clock_count == 2:
                holder_pid["pid"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("Analysis completion was not released")
            return timezone.now()

        def capture_clock():
            holder_pid["pid"] = connection.connection.info.backend_pid
            held.set()
            if not release.wait(10):
                raise TimeoutError("Source correction was not released")
            return timezone.now()

        def waiter_clock():
            clock_called.set()
            return timezone.now()

        def observe(execute, sql, params, many, context):
            if "FOR UPDATE" in sql and SourceState._meta.db_table in sql:
                waiter_pid["pid"] = context["connection"].connection.info.backend_pid
                attempted.set()
            return execute(sql, params, many, context)

        reviewed = self.reviewed()
        if completion_first:
            holder = lambda: self.analyse(reviewed=reviewed, clock=completion_clock)
            def waiter():
                with connection.execute_wrapper(observe):
                    return capture.commit_batch(admitted.pk, changed, clock=waiter_clock)
        else:
            # Admit analysis before the correcting transaction takes protection.
            def callback():
                inference.set()
                if not held.wait(10):
                    raise TimeoutError("Correction failed to acquire protection")
                clock_called.clear()
            self.provider.callback = callback
            def holder():
                if not inference.wait(10):
                    raise TimeoutError("Analysis did not reach inference")
                return capture.commit_batch(admitted.pk, changed, clock=capture_clock)
            def waiter():
                with connection.execute_wrapper(observe):
                    return self.analyse(reviewed=reviewed, clock=waiter_clock)
        with ThreadPoolExecutor(max_workers=2) as pool:
            if completion_first:
                protected = pool.submit(independent, holder)
                waiting = None
            else:
                waiting = pool.submit(independent, waiter)
                protected = pool.submit(independent, holder)
            try:
                self.assertTrue(held.wait(10))
                if completion_first:
                    waiting = pool.submit(independent, waiter)
                # Earlier preflight calls can set these observations; only the
                # active server lock wait proves completion ordering.
                self.assertTrue(attempted.wait(10))
                self.server_lock_wait(waiter_pid["pid"], holder_pid["pid"], SourceState._meta.db_table)
                self.assertFalse(clock_called.is_set())
                self.assertFalse(waiting.done())
            finally:
                release.set()
            holder_result = protected.result(timeout=10)
            waiter_result = waiting.result(timeout=10)
        result = holder_result if completion_first else waiter_result
        saved = NewsAnalysisResult.objects.get()
        self.assertEqual(saved.status, "analysed" if completion_first else "stale")
        self.assertIsNotNone(saved.document)
        inspected = self.inspect(result)["analysis"]
        self.assertEqual(inspected["current_disposition"], "stale")
        self.assertIn("observed_source_revision_changed", inspected["stale_reasons"])

    def test_approval_writer_waits_for_analysis_completion_protection(self):
        self.ordered_user_race("approval", completion_first=True)

    def test_analysis_completion_waits_for_approval_then_is_stale(self):
        self.ordered_user_race("approval", completion_first=False)

    def test_exposure_writer_waits_for_analysis_completion_protection(self):
        self.ordered_user_race("exposure", completion_first=True)

    def test_analysis_completion_waits_for_exposure_then_is_stale(self):
        self.ordered_user_race("exposure", completion_first=False)

    def ordered_user_race(self, kind, *, completion_first):
        reviewed = self.reviewed()
        draft = None
        if kind == "approval":
            current = theses.get_thesis(self.actor, self.thesis["id"])
            draft = theses.propose_thesis(self.actor, self.thesis["id"], str(uuid4()),
                EXACT + " New approved intent.", MEANING, current["revision"])["thesis"]
        held, release, attempted, clock_called, inference = (Event() for _ in range(5))
        holder_pid, waiter_pid = {}, {}
        clock_count = 0

        def completion_clock():
            nonlocal clock_count
            clock_count += 1
            if clock_count == 2:
                holder_pid["pid"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("Analysis completion was not released")
            return timezone.now()

        def writer_clock():
            holder_pid["pid"] = connection.connection.info.backend_pid
            held.set()
            if not release.wait(10):
                raise TimeoutError("Governing user writer was not released")
            return timezone.now()

        def waiter_clock():
            clock_called.set()
            return timezone.now()

        def mutate(clock):
            return self.approve(draft, clock=clock) if kind == "approval" else self.revise_position(clock=clock)

        def observe(execute, sql, params, many, context):
            if "FOR UPDATE" in sql and get_user_model()._meta.db_table in sql:
                waiter_pid["pid"] = context["connection"].connection.info.backend_pid
                attempted.set()
            return execute(sql, params, many, context)

        if completion_first:
            holder = lambda: self.analyse(reviewed=reviewed, clock=completion_clock)
            def waiter():
                with connection.execute_wrapper(observe):
                    return mutate(waiter_clock)
        else:
            def callback():
                inference.set()
                if not held.wait(10):
                    raise TimeoutError("Governing user writer failed to acquire protection")
                clock_called.clear()
            self.provider.callback = callback
            def holder():
                if not inference.wait(10):
                    raise TimeoutError("Analysis did not reach inference")
                return mutate(writer_clock)
            def waiter():
                with connection.execute_wrapper(observe):
                    return self.analyse(reviewed=reviewed, clock=waiter_clock)
        with ThreadPoolExecutor(max_workers=2) as pool:
            if completion_first:
                protected = pool.submit(independent, holder)
                waiting = None
            else:
                waiting = pool.submit(independent, waiter)
                protected = pool.submit(independent, holder)
            try:
                self.assertTrue(held.wait(10))
                if completion_first:
                    waiting = pool.submit(independent, waiter)
                self.assertTrue(attempted.wait(10))
                self.server_lock_wait(waiter_pid["pid"], holder_pid["pid"], get_user_model()._meta.db_table)
                self.assertFalse(clock_called.is_set())
                self.assertFalse(waiting.done())
            finally:
                release.set()
            holder_result = protected.result(timeout=10)
            waiter_result = waiting.result(timeout=10)
        result = holder_result if completion_first else waiter_result
        saved = NewsAnalysisResult.objects.get()
        self.assertEqual(saved.status, "analysed" if completion_first else "stale")
        inspected = self.inspect(result)["analysis"]
        self.assertEqual(inspected["current_disposition"], "stale")
        self.assertIn("approved_meaning_changed" if kind == "approval" else "paper_exposure_changed",
                      inspected["stale_reasons"])

    def test_read_only_inspection_remains_coherent_during_source_change(self):
        result = self.analyse()
        original = analysis._stale_reasons
        def change_after_snapshot(attempt, thesis):
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(independent, lambda: self.capture_item(title="Changed observed payload")).result(timeout=10)
            return original(attempt, thesis)
        with patch.object(analysis, "_stale_reasons", side_effect=change_after_snapshot):
            old_snapshot = self.inspect(result)["analysis"]
        self.assertEqual(old_snapshot["status"], "analysed")
        self.assertEqual(old_snapshot["current_disposition"], "current")
        self.assertEqual(self.inspect(result)["analysis"]["current_disposition"], "stale")
