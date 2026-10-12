"""One-call recovery, digest fallback and governing changes across connections."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
from uuid import uuid4

from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.domain.daily_synthesis import SCHEMA_VERSION
from macro_agent.domain.models import canonical_json
from macro_agent.monitoring.models import SourceState
from macro_agent.monitoring.tests import test_analysis as recorded
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.positions import service as positions
from macro_agent.providers import ProviderError
from macro_agent.theses import compilation, service as theses

from macro_agent.desk import permissions, publication, synthesis
from macro_agent.desk.models import DailyReview, DailySynthesisAttempt, DailySynthesisResult
from . import test_service as daily


def synthesis_document(context):
    reports = [item for section in ("new", "background") for item in context["review"]["reports"][section]]
    claims = [{"claim_id": "claim",
        "source_revision_id": reports[0]["revision_id"], "source_field": "title",
        "quote": reports[0]["payload"]["title"]}] if reports else []
    refs = ["claim"] if claims else []
    section = {"text": "Conditional interpretation of retained evidence.", "claim_ids": refs,
        "prior_analysis_ids": [], "uncertainty": "Timing and transmission are uncertain."}
    effect = {"effect": "supports" if claims else "unresolved", "reasoning": "Potential policy support.",
        **{key: section[key] for key in ("claim_ids", "prior_analysis_ids", "uncertainty")}}
    positions = context["original_inputs"]["approved_user"]["exposure"]["positions"]
    return {"schema_version": SCHEMA_VERSION, "attributed_claims": claims, "overview": section,
        "thesis_effect": effect, "trade_effects": [{**effect, "position_id": item["position_id"],
            "effect": "potential_risk" if claims else "unresolved", "reasoning": "Funding stress can hurt the open trade first."}
            for item in positions if item["payload"]["status"] == "open"],
        "counter_case": deepcopy(section), "watch_questions": ["Is policy transmitting?"],
        "gaps": ["Current macro regime and prices are unavailable."]}


class RecordedSynthesisProvider(recorded.RecordedProvider):
    def complete(self, model_id, messages):
        self.calls += 1
        self.messages = deepcopy(messages)
        if connection.in_atomic_block or not connection.get_autocommit():
            raise AssertionError("Synthesis inference cannot retain a transaction")
        if self.callback:
            self.callback()
        return {"content": canonical_json(synthesis_document(json.loads(messages[1]["content"]))),
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "reported_cost_usd": None, "reported_model": model_id, "latency_ms": 1}


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class DailySynthesisTests(TransactionTestCase):
    capture = daily.DailyReviewPersistenceTests.capture
    review = daily.DailyReviewPersistenceTests.review
    approve = recorded.PostgreSQLNewsAnalysisTests.approve
    approval_id = recorded.PostgreSQLNewsAnalysisTests.approval_id
    replace_approval = recorded.PostgreSQLNewsAnalysisTests.replace_approval

    def server_lock_wait(self, waiter, blocker, table):
        deadline = monotonic() + 5
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_stat_clear_snapshot()")
                cursor.execute("SELECT state,wait_event_type,query,pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=%s", [waiter])
                row = cursor.fetchone()
            if row and row[0] == "active" and row[1] == "Lock" and table in row[2] and blocker in row[3]:
                return
            sleep(0.01)
        self.fail(f"Expected actual PostgreSQL source wait: {row!r}")

    def setUp(self):
        daily.DailyReviewPersistenceTests.setUp(self)
        self.position = positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
            self.approval_id, recorded.DECLARATION)["position"]
        self.provider = RecordedSynthesisProvider()

    def synthesize(self, review=None, command=None, **kwargs):
        review = review or self.review()
        return synthesis.synthesize_review(self.actor, review["review"]["id"], command or str(uuid4()),
            review["review"]["digest"], recorded.MODEL, "nanogpt", provider=self.provider, **kwargs)

    def publish(self, review):
        row = review["review"]
        return publication.publish_review(self.actor, row["id"], str(uuid4()), row["digest"], 0, 10)

    def test_admission_is_committed_before_one_model_call_and_digest_stays_separate(self):
        review = self.review()
        published = self.publish(review)
        def callback():
            with ThreadPoolExecutor(max_workers=1) as pool:
                attempt = pool.submit(recorded.independent, lambda: DailySynthesisAttempt.objects.get()).result(timeout=10)
            self.assertEqual(attempt.review_digest, review["review"]["digest"])
            self.assertFalse(DailySynthesisResult.objects.exists())
        self.provider.callback = callback
        result = self.synthesize(review)
        self.assertEqual(result["synthesis"]["status"], "synthesised")
        self.assertEqual(result["current_disposition"]["status"], "current")
        self.assertFalse(result["current_disposition"]["publication_authority"])
        self.assertEqual(result["synthesis"]["document"]["thesis_effect"]["effect"], "supports")
        self.assertEqual(result["synthesis"]["document"]["trade_effects"][0]["effect"], "potential_risk")
        current = publication.get_current_brief(self.actor, self.thesis["id"])["current_publication"]
        self.assertEqual(current["publication"], published["publication"])
        self.assertEqual((CurrentAssessment.objects.count(), NotificationIntent.objects.count()), (1, 1))
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (1, 1))

    def test_saved_command_retry_and_read_need_no_credentials_or_catalogue(self):
        review, command = self.review(), str(uuid4())
        saved = self.synthesize(review, command)
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            replay = self.synthesize(review, command)
            read = synthesis.get_synthesis_command(self.actor, review["review"]["id"], command)
        self.assertEqual(saved["synthesis"], replay["synthesis"])
        self.assertEqual(saved["synthesis"], read["synthesis"])
        self.assertTrue(read["replayed"])
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (1, 1))

    def test_same_command_cannot_switch_model_or_exact_review(self):
        review, command = self.review(), str(uuid4())
        self.synthesize(review, command)
        with self.assertRaises(theses.ThesisConflict):
            synthesis.synthesize_review(self.actor, review["review"]["id"], command,
                review["review"]["digest"], "other/model", "nanogpt", provider=self.provider)
        self.assertEqual(self.provider.calls, 1)

    def test_correction_during_inference_preserves_stale_original_without_publication(self):
        review = self.review()
        def callback():
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(recorded.independent, lambda: self.capture(title="Corrected observed report")).result(timeout=10)
        self.provider.callback = callback
        result = self.synthesize(review)
        self.assertEqual(result["synthesis"]["status"], "stale")
        self.assertTrue(any(reason.startswith("included_report_corrected:")
                            for reason in result["synthesis"]["original_stale_reasons"]))
        self.assertIsNotNone(result["synthesis"]["document"])
        self.assertFalse(CurrentAssessment.objects.exists())

    def test_correction_after_success_changes_only_observed_disposition(self):
        result = self.synthesize()
        self.capture(title="Later correction")
        read = synthesis.inspect_synthesis(self.actor, result["synthesis"]["id"])
        self.assertEqual(read["synthesis"], result["synthesis"])
        self.assertEqual(read["current_disposition"]["status"], "stale")

    def test_distinct_later_report_keeps_pinned_cutoff_valid(self):
        self.provider.callback = lambda: self.capture(native="report-2", title="Distinct development")
        result = self.synthesize()
        self.assertEqual(result["synthesis"]["status"], "synthesised")
        self.assertEqual(result["current_disposition"]["status"], "current")

    def test_permission_withdrawal_during_inference_records_stale_result(self):
        def callback():
            source = SourceState.objects.get(pk=recorded.SOURCE)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(recorded.independent, lambda: permissions.set_source_permission(str(self.staff.pk),
                    source.pk, source.contract_digest, False, "Recorded permission withdrawal.")).result(timeout=10)
        self.provider.callback = callback
        result = self.synthesize()
        self.assertEqual(result["synthesis"]["status"], "stale")
        self.assertIn("source_contract_or_permission_changed:" + recorded.SOURCE,
                      result["synthesis"]["original_stale_reasons"])

    def test_approval_and_book_changes_during_inference_are_independent_stale_reasons(self):
        self.provider.callback = lambda: self.replace_approval()
        result = self.synthesize()
        self.assertIn("approved_meaning_changed", result["synthesis"]["original_stale_reasons"])
        review = self.review(start=DailyReview.objects.order_by("-cutoff").first().cutoff)
        def change_book():
            row = positions.get_position(self.actor, self.position["id"])
            positions.close_position(self.actor, row["id"], str(uuid4()), row["revision"],
                theses.get_thesis(self.actor, self.thesis["id"])["approved"]["approval"]["id"])
        self.provider.callback = change_book
        later = self.synthesize(review)
        self.assertIn("paper_exposure_changed", later["synthesis"]["original_stale_reasons"])

    def test_newer_daily_review_during_inference_prevents_current_synthesis_label(self):
        review = self.review()
        self.provider.callback = lambda: self.review(start=DailyReview.objects.get().cutoff)
        result = self.synthesize(review)
        self.assertEqual(result["synthesis"]["status"], "stale")
        self.assertIn("newer_retained_review", result["current_disposition"]["stale_reasons"])

    def test_invalid_model_output_retains_usage_and_exact_digest_fallback(self):
        review = self.review()
        self.publish(review)
        original = self.provider.complete
        def invalid(model, messages):
            value = original(model, messages)
            value["content"] = '{"approve":true}'
            return value
        self.provider.complete = invalid
        result = self.synthesize(review)
        self.assertEqual(result["synthesis"]["status"], "failed")
        self.assertEqual(result["synthesis"]["usage"]["total_tokens"], 150)
        self.assertIsNone(result["synthesis"]["document"])
        self.assertIsNotNone(publication.get_current_brief(self.actor, self.thesis["id"])["current_publication"])

    def test_unknown_provider_outcome_is_retained_and_never_repeated(self):
        review, command = self.review(), str(uuid4())
        def unknown():
            raise ProviderError("outcome_unknown")
        self.provider.callback = unknown
        result = self.synthesize(review, command)
        self.assertEqual(result["synthesis"]["status"], "outcome_unknown")
        self.synthesize(review, command)
        self.assertEqual(self.provider.calls, 1)

    def test_crash_after_admission_recovers_running_then_unknown_without_second_call(self):
        review, command = self.review(), str(uuid4())
        self.provider.callback = lambda: (_ for _ in ()).throw(RuntimeError("process interrupted"))
        with self.assertRaises(RuntimeError):
            self.synthesize(review, command)
        attempt = DailySynthesisAttempt.objects.get()
        before = synthesis.get_synthesis_command(self.actor, review["review"]["id"], command)
        after = synthesis.get_synthesis_command(self.actor, review["review"]["id"], command,
            clock=lambda: attempt.deadline_at + timedelta(seconds=1))
        self.assertEqual(before["synthesis"]["status"], "running")
        self.assertEqual(after["synthesis"]["status"], "outcome_unknown")
        self.synthesize(review, command)
        self.assertEqual(self.provider.calls, 1)

    def test_owner_scoped_reads_do_not_give_staff_private_access(self):
        result = self.synthesize()
        for actor in (str(self.other.pk), str(self.staff.pk)):
            with self.assertRaises(theses.ThesisUnavailable):
                synthesis.inspect_synthesis(actor, result["synthesis"]["id"])

    def test_stale_before_admission_and_overflow_make_no_provider_request(self):
        review = self.review()
        with patch("macro_agent.domain.daily_synthesis.MAX_CONTEXT_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "do not truncate"):
                self.synthesize(review)
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (0, 0))
        self.capture(title="Correction before admission")
        with self.assertRaises(theses.ThesisConflict):
            self.synthesize(review)
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (0, 0))
        self.assertFalse(DailySynthesisAttempt.objects.exists())

    def test_shared_budget_counts_synthesis_and_blocks_other_research_roles(self):
        review = self.review()
        with override_settings(MACRO_COMPILATION_OWNER_ATTEMPTS_PER_DAY=1,
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            self.synthesize(review)
            with self.assertRaises(compilation.CompilationBudgetExhausted):
                self.synthesize(review)
        self.assertEqual(self.provider.calls, 1)

    def test_source_lock_wait_precedes_trusted_admission_clock(self):
        review = self.review()
        observed, released = Event(), Event()
        pids = {}
        initial, after_wait = timezone.now(), timezone.now() + timedelta(seconds=1)
        def clock():
            if not observed.is_set():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids["waiter"] = cursor.fetchone()[0]
                observed.set()
            return after_wait if released.is_set() else initial
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                SourceState.objects.select_for_update().get(pk=recorded.SOURCE)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    blocker = cursor.fetchone()[0]
                future = pool.submit(recorded.independent, lambda: self.synthesize(review, clock=clock))
                self.assertTrue(observed.wait(5))
                self.server_lock_wait(pids["waiter"], blocker, "macro_monitoring_sourcestate")
                self.assertEqual(self.provider.calls, 0)
                released.set()
            result = future.result(timeout=10)
        self.assertEqual(DailySynthesisAttempt.objects.get().created_at, after_wait)
        self.assertEqual(result["synthesis"]["status"], "synthesised")

    def test_ambient_transaction_and_backdated_inspection_are_rejected(self):
        review = self.review()
        with transaction.atomic(), self.assertRaises(RuntimeError):
            self.synthesize(review)
        result = self.synthesize(review)
        attempt = DailySynthesisAttempt.objects.get()
        with self.assertRaises(theses.ThesisConflict):
            synthesis.inspect_synthesis(self.actor, result["synthesis"]["id"],
                clock=lambda: attempt.created_at - timedelta(seconds=1))

    def test_database_rejects_mutation_scope_forgery_and_false_current_result(self):
        result = self.synthesize()
        attempt = DailySynthesisAttempt.objects.get()
        for mutation in (lambda: DailySynthesisAttempt.objects.filter(pk=attempt.pk).update(model_id="changed"),
                         lambda: DailySynthesisResult.objects.filter(pk=attempt.pk).delete()):
            with self.assertRaises(DatabaseError), transaction.atomic():
                mutation()
        fields = {field.name: getattr(attempt, field.name) for field in attempt._meta.fields
                  if field.name not in ("id", "command_id")}
        with self.assertRaises(DatabaseError), transaction.atomic():
            DailySynthesisAttempt.objects.create(**{**fields, "owner": self.other}, command_id=uuid4())
        with self.assertRaises(DatabaseError), transaction.atomic():
            forged = deepcopy(fields["context"])
            forged["report_heads"] = {}
            DailySynthesisAttempt.objects.create(**{**fields, "context": forged}, command_id=uuid4())

    def test_database_rejects_synthesised_result_after_correction(self):
        review = self.review()
        self.provider.callback = lambda: (_ for _ in ()).throw(RuntimeError("crash after admission"))
        with self.assertRaises(RuntimeError):
            self.synthesize(review)
        attempt = DailySynthesisAttempt.objects.get()
        self.capture(title="Correction before forged result")
        with self.assertRaises(DatabaseError), transaction.atomic():
            DailySynthesisResult.objects.create(attempt=attempt, status="synthesised",
                document=synthesis_document(attempt.context), provider_metadata={}, stop_reason="completed",
                stale_reasons=[], finished_at=timezone.now())
