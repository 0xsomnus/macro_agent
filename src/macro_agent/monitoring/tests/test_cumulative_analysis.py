"""Cumulative admissions, independent governing races and inert recovery."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from threading import Event
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.domain.daily_review import DailyReviewLimits, ReviewCapacityExceeded
from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.desk import service as desk
from macro_agent.desk.models import EvidenceSet, PrivateContext, SourceContractVersion
from macro_agent.desk.permissions import set_source_permission
from macro_agent.monitoring import analysis, capture, news_context
from macro_agent.monitoring.models import NewsAnalysisAttempt, NewsAnalysisResult, SourceState
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.providers import ProviderError

from . import test_analysis as recorded
from .test_cumulative_runner import RecordedCumulativeProvider


BACKGROUND = "fixture-cumulative-background"
BACKGROUND_CONTRACT = {"kind": "fictional_fixture", "label": "Fictional background feed"}
LIMITS = DailyReviewLimits(reports=100, analyses=100, exposure_versions=200,
    issues=300, source_contracts=16, encoded_bytes=65536)


@override_settings(MACRO_ENABLE_NEWS_ANALYSIS=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class PostgreSQLCumulativeAnalysisTests(TransactionTestCase):
    approve = recorded.PostgreSQLNewsAnalysisTests.approve
    approval_id = recorded.PostgreSQLNewsAnalysisTests.approval_id
    item = recorded.PostgreSQLNewsAnalysisTests.item
    batch = recorded.PostgreSQLNewsAnalysisTests.batch
    capture_item = recorded.PostgreSQLNewsAnalysisTests.capture_item
    reviewed = recorded.PostgreSQLNewsAnalysisTests.reviewed
    server_lock_wait = recorded.PostgreSQLNewsAnalysisTests.server_lock_wait
    revise_position = recorded.PostgreSQLNewsAnalysisTests.revise_position
    replace_approval = recorded.PostgreSQLNewsAnalysisTests.replace_approval

    def setUp(self):
        recorded.PostgreSQLNewsAnalysisTests.setUp(self)
        self.provider = RecordedCumulativeProvider()
        self.staff = get_user_model().objects.create_user(username="context-permission-reviewer", is_staff=True)
        self.background()

    def background(self, title="Fictional funding counterevidence", *, native="background-1"):
        return capture.capture(BACKGROUND, BACKGROUND_CONTRACT,
            lambda: self.batch(self.item(native, title)))

    def cumulative(self, command=None, *, reviewed=None, limits=LIMITS, **kwargs):
        reviewed = reviewed or self.reviewed()
        return analysis.analyse_next(self.actor, self.thesis["id"], command or str(uuid4()),
            reviewed["approval_id"], reviewed["exposure_digest"], recorded.SOURCE, recorded.MODEL, "nanogpt",
            provider=self.provider, context_source_ids=(recorded.SOURCE, BACKGROUND),
            context_limits=limits, **kwargs)

    def withdraw(self, *, clock=timezone.now):
        row = SourceState.objects.get(pk=BACKGROUND)
        return set_source_permission(str(self.staff.pk), BACKGROUND, row.contract_digest,
            False, "Recorded withdrawal during cumulative inference.", clock=clock)

    def test_private_context_commits_with_admission_before_inference_and_has_no_publication_authority(self):
        def callback():
            with ThreadPoolExecutor(max_workers=1) as pool:
                row = pool.submit(recorded.independent, lambda: NewsAnalysisAttempt.objects.select_related(
                    "admission_context__evidence").get()).result(timeout=10)
            self.assertEqual(str(row.admission_context_id), row.context["cumulative"]["context_id"])
            self.assertEqual(row.admission_context.resolved_inputs["cumulative"], row.context["cumulative"])
            self.assertEqual(row.created_at, row.admission_context.prepared_at)
            self.assertEqual(row.context_digest, text_digest(canonical_json(row.context)))
            self.assertEqual(row.admission_context.evidence.sources.count(), 2)
            self.assertEqual(row.admission_context.positions.count(), 1)
            self.assertFalse(NewsAnalysisResult.objects.exists())
        self.provider.callback = callback
        result = self.cumulative()["analysis"]
        self.assertEqual(result["status"], "analysed")
        self.assertEqual(result["context"]["approved_thesis"]["exact_text"], recorded.EXACT)
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertIsNone(result["reported_cost_usd"])

    def test_background_correction_during_inference_preserves_return_as_stale(self):
        def callback():
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(recorded.independent, lambda: self.background("Corrected fictional counterevidence")).result(timeout=10)
        self.provider.callback = callback
        result = self.cumulative()["analysis"]
        self.assertEqual(result["status"], "stale")
        self.assertIn("contextual_source_revision_changed", result["stale_reasons"])
        self.assertNotIn("observed_source_revision_changed", result["stale_reasons"])
        self.assertIsNotNone(result["document"])
        self.assertEqual(self.provider.calls, 1)

    def test_distinct_later_report_does_not_stale_pinned_cutoff(self):
        self.provider.callback = lambda: self.background("Another fictional report", native="background-2")
        result = self.cumulative()["analysis"]
        self.assertEqual(result["status"], "analysed")
        self.assertEqual(result["current_disposition"], "current")
        self.assertEqual(result["stale_reasons"], [])
        self.assertEqual(len(result["context"]["cumulative"]["reports"]), 2)

    def test_inspection_cannot_backdate_retained_analysis_or_permission_state(self):
        command = str(uuid4())
        self.cumulative(command)
        attempt = NewsAnalysisAttempt.objects.get()
        with self.assertRaises(news_context.NewsConflict):
            analysis.get_news_command(self.actor, self.thesis["id"], command,
                clock=lambda: attempt.created_at - timedelta(microseconds=1))
        saved = NewsAnalysisResult.objects.get()
        self.withdraw()
        with self.assertRaisesMessage(news_context.NewsConflict, "contextual source permission"):
            analysis.get_news_command(self.actor, self.thesis["id"], command,
                clock=lambda: saved.finished_at)
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (1, 1))

    def test_already_superseded_background_is_labelled_without_false_new_staleness(self):
        self.background("Corrected before admission")
        result = self.cumulative()["analysis"]
        self.assertEqual(result["status"], "analysed")
        reports = [row for row in result["context"]["cumulative"]["reports"] if row["source_key"] == BACKGROUND]
        self.assertEqual(len(reports), 2)
        self.assertEqual(sum(row["is_current_revision"] for row in reports), 1)
        self.assertEqual(result["stale_reasons"], [])

    def test_later_background_correction_changes_only_current_disposition(self):
        command = str(uuid4())
        result = self.cumulative(command)["analysis"]
        original = deepcopy(result["context"])
        self.background("Correction after successful completion")
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                SETTINGS_MODULE="macro_agent.web.local_settings"):
            replay = self.cumulative(command)["analysis"]
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["status"], "analysed")
        self.assertEqual(replay["current_disposition"], "stale")
        self.assertEqual(replay["context"], original)
        self.assertIn("contextual_source_revision_changed", replay["stale_reasons"])
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (1, 1))
        with self.assertRaises(PermissionError):
            analysis.get_news_command(str(self.other.pk), self.thesis["id"], command)

    def test_record_and_byte_overflow_make_no_catalogue_or_inference_or_context_writes(self):
        for limits in (replace(LIMITS, reports=1), replace(LIMITS, encoded_bytes=1000)):
            with self.subTest(limits=limits), self.assertRaises(ReviewCapacityExceeded):
                self.cumulative(limits=limits)
            self.assertFalse(NewsAnalysisAttempt.objects.exists())
            self.assertFalse(PrivateContext.objects.exists())
            self.assertFalse(EvidenceSet.objects.exists())
            self.assertFalse(SourceContractVersion.objects.exists())
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (0, 0))

    def test_cumulative_attempt_uses_same_private_budget_as_legacy_news(self):
        legacy = recorded.RecordedProvider()
        reviewed = self.reviewed()
        analysis.analyse_next(self.actor, self.thesis["id"], str(uuid4()), reviewed["approval_id"],
            reviewed["exposure_digest"], recorded.SOURCE, recorded.MODEL, "nanogpt", provider=legacy)
        self.capture_item(native="report-2")
        with override_settings(MACRO_COMPILATION_OWNER_ATTEMPTS_PER_DAY=1,
                SETTINGS_MODULE="macro_agent.web.local_settings"):
            with self.assertRaises(analysis.NewsBudgetExhausted):
                self.cumulative()
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(NewsAnalysisAttempt.objects.count(), 1)
        self.assertFalse(PrivateContext.objects.exists())

    def test_failed_paid_outcome_enters_next_context_as_unresolved_metadata(self):
        def unknown(model, messages):
            self.provider.calls += 1
            raise ProviderError("outcome_unknown", metadata={"reported_cost_usd": "0.001"})
        self.provider.complete = unknown
        first = self.cumulative()["analysis"]
        self.assertEqual(first["status"], "outcome_unknown")
        desk.observe_analysis_results(self.actor, self.thesis["id"], (recorded.SOURCE, BACKGROUND), limit=10)
        self.capture_item(native="report-2")
        self.provider = RecordedCumulativeProvider()
        result = self.cumulative()["analysis"]
        prior = result["context"]["cumulative"]["analyses"]
        self.assertEqual(len(prior), 1)
        self.assertEqual(prior[0]["analysis_id"], first["id"])
        self.assertEqual(prior[0]["original_status"], "outcome_unknown")
        self.assertEqual(prior[0]["current_disposition"], "unresolved")
        self.assertIsNone(prior[0]["document"])
        self.assertEqual(prior[0]["costs"]["reported_cost_usd"], "0.001")
        self.assertEqual(result["document"]["evidence_comparisons"], [])

    def test_approval_and_book_changes_during_inference_keep_original_context_and_stale_result(self):
        for change, reason in ((self.revise_position, "paper_exposure_changed"),
                               (self.replace_approval, "approved_meaning_changed")):
            self.capture_item(native=str(uuid4()))
            self.provider.callback = change
            result = self.cumulative()["analysis"]
            self.assertEqual(result["status"], "stale")
            self.assertIn(reason, result["stale_reasons"])

    def test_sql_admission_guard_rejects_detached_context_and_cross_owner_binding(self):
        self.cumulative()
        original = NewsAnalysisAttempt.objects.get()
        fields = {field.name: getattr(original, field.attname) for field in original._meta.concrete_fields}
        fields.update(id=uuid4(), command_id=uuid4())
        # Run insert guards before the existing input uniqueness check matters.
        for changes in ({"admission_context": None}, {"owner": self.other.pk},
                        {"context": {**original.context, "cumulative": {**original.context["cumulative"], "digest": "0" * 64}}}):
            values = {**fields, **changes}
            kwargs = {original._meta.get_field(key).attname: value for key, value in values.items()}
            with self.subTest(changes=changes), self.assertRaises(DatabaseError) as error:
                with transaction.atomic():
                    NewsAnalysisAttempt.objects.create(**kwargs)
            self.assertEqual(getattr(error.exception.__cause__, "sqlstate", None), "23514")
        self.assertEqual(NewsAnalysisAttempt.objects.count(), 1)

    def test_background_permission_withdrawal_first_forces_actual_completion_wait_and_retains_outcome(self):
        inference, return_model, permission_locked, commit_permission = (Event() for _ in range(4))
        pids = {}
        command = str(uuid4())
        def callback():
            inference.set()
            if not return_model.wait(10):
                raise AssertionError("Recorded inference was not released")
        def permission_clock():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids["permission"] = cursor.fetchone()[0]
            permission_locked.set()
            if not commit_permission.wait(10):
                raise AssertionError("Permission transaction was not released")
            return timezone.now()
        def worker():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids["analysis"] = cursor.fetchone()[0]
            return self.cumulative(command)
        self.provider.callback = callback
        with ThreadPoolExecutor(max_workers=2) as pool:
            analyse_future = pool.submit(recorded.independent, worker)
            try:
                self.assertTrue(inference.wait(10))
                permission_future = pool.submit(recorded.independent, lambda: self.withdraw(clock=permission_clock))
                self.assertTrue(permission_locked.wait(10))
                return_model.set()
                self.server_lock_wait(pids["analysis"], pids["permission"], "macro_monitoring_sourcestate")
            finally:
                return_model.set()
                commit_permission.set()
            permission = permission_future.result(timeout=10)
            result = analyse_future.result(timeout=10)["analysis"]
        self.assertEqual(result["status"], "stale")
        self.assertIn("contextual_source_contract_unavailable", result["stale_reasons"])
        self.assertGreaterEqual(NewsAnalysisResult.objects.get().finished_at.isoformat(), permission["observed_at"])
        self.assertIsNotNone(result["document"])
        self.assertEqual(self.provider.calls, 1)

    def test_completion_first_preserves_success_then_permission_changes_current_disposition(self):
        completion_locked, complete, permission_started = (Event() for _ in range(3))
        pids = {}
        def clock():
            if self.provider.calls:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids["analysis"] = cursor.fetchone()[0]
                completion_locked.set()
                if not complete.wait(10):
                    raise AssertionError("Completion was not released")
            return timezone.now()
        def permission_worker():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids["permission"] = cursor.fetchone()[0]
            permission_started.set()
            return self.withdraw()
        command = str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            analyse_future = pool.submit(recorded.independent, lambda: self.cumulative(command, clock=clock))
            try:
                self.assertTrue(completion_locked.wait(10))
                permission_future = pool.submit(recorded.independent, permission_worker)
                self.assertTrue(permission_started.wait(10))
                self.server_lock_wait(pids["permission"], pids["analysis"], "macro_monitoring_sourcestate")
            finally:
                complete.set()
            result = analyse_future.result(timeout=10)["analysis"]
            permission_future.result(timeout=10)
        self.assertEqual(result["status"], "analysed")
        self.assertEqual(result["current_disposition"], "current")
        replay = self.cumulative(command)["analysis"]
        self.assertEqual(replay["status"], "analysed")
        self.assertEqual(replay["current_disposition"], "stale")
        self.assertIn("contextual_source_contract_unavailable", replay["stale_reasons"])
        self.assertEqual(self.provider.calls, 1)
