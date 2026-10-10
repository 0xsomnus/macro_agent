"""Already admitted outcomes survive ordered permission withdrawal."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.desk.permissions import set_source_permission
from macro_agent.monitoring import analysis, news_context
from macro_agent.monitoring.models import NewsAnalysisAttempt, NewsAnalysisResult, SourceState
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent

from . import test_analysis as recorded


@override_settings(MACRO_ENABLE_NEWS_ANALYSIS=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class PostgreSQLPermissionCompletionTests(TransactionTestCase):
    # Reuse fixture construction, not the existing test class or its tests.
    approve = recorded.PostgreSQLNewsAnalysisTests.approve
    approval_id = recorded.PostgreSQLNewsAnalysisTests.approval_id
    item = recorded.PostgreSQLNewsAnalysisTests.item
    batch = recorded.PostgreSQLNewsAnalysisTests.batch
    capture_item = recorded.PostgreSQLNewsAnalysisTests.capture_item
    reviewed = recorded.PostgreSQLNewsAnalysisTests.reviewed
    analyse = recorded.PostgreSQLNewsAnalysisTests.analyse
    server_lock_wait = recorded.PostgreSQLNewsAnalysisTests.server_lock_wait

    def setUp(self):
        recorded.PostgreSQLNewsAnalysisTests.setUp(self)
        self.staff = get_user_model().objects.create_user(username="permission-reviewer", is_staff=True)
        self.permission_actor = str(self.staff.pk)
        self.source_digest = SourceState.objects.get(pk=recorded.SOURCE).contract_digest

    def withdraw(self, *, clock=timezone.now):
        return set_source_permission(self.permission_actor, recorded.SOURCE, self.source_digest,
            False, "Withdraw new source use during the recorded race.", clock=clock)

    def assert_retained(self, result):
        saved = NewsAnalysisResult.objects.get()
        self.assertEqual(saved.document, result["document"])
        self.assertEqual(saved.provider_metadata, {
            "reported_model": recorded.MODEL, "provider_request_id": "recorded-news-request",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "reported_cost_usd": None, "finish_reason": "stop", "latency_ms": 1})
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.provider.catalog_calls, 1)
        self.assertEqual(NewsAnalysisAttempt.objects.count(), 1)

    def test_withdrawal_first_retains_stale_result_after_actual_source_lock_wait(self):
        inference, return_model, permission_locked, commit_permission = (Event() for _ in range(4))
        pids = {}
        command, reviewed = str(uuid4()), self.reviewed()

        def wait_for_return():
            inference.set()
            if not return_model.wait(10):
                raise AssertionError("Recorded model was not released")

        def permission_clock():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids["permission"] = cursor.fetchone()[0]
            permission_locked.set()
            if not commit_permission.wait(10):
                raise AssertionError("Permission transaction was not released")
            return timezone.now()

        def analyse_worker():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids["analysis"] = cursor.fetchone()[0]
            return self.analyse(command, reviewed=reviewed)

        self.provider.callback = wait_for_return
        with ThreadPoolExecutor(max_workers=2) as pool:
            analysis_future = pool.submit(recorded.independent, analyse_worker)
            try:
                self.assertTrue(inference.wait(10))
                permission_future = pool.submit(recorded.independent,
                    lambda: self.withdraw(clock=permission_clock))
                self.assertTrue(permission_locked.wait(10))
                return_model.set()
                self.server_lock_wait(pids["analysis"], pids["permission"],
                    "macro_monitoring_sourcestate")
            finally:
                return_model.set()
                commit_permission.set()
            permission = permission_future.result(timeout=10)
            result = analysis_future.result(timeout=10)["analysis"]
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["current_disposition"], "stale")
        self.assertIn("source_contract_unavailable", result["stale_reasons"])
        self.assertGreaterEqual(NewsAnalysisResult.objects.get().finished_at.isoformat(),
            permission["observed_at"])
        self.assert_retained(result)
        # Saved commands remain inspectable after withdrawal and without keys.
        with override_settings(MACRO_MODEL_API_KEY="",
                SETTINGS_MODULE="macro_agent.web.local_settings"):
            replay = self.analyse(command, reviewed=reviewed)["analysis"]
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["document"], result["document"])
        with self.assertRaises(news_context.NewsMissing):
            self.analyse(reviewed=reviewed)
        self.assert_retained(result)

    def test_completion_first_retains_original_success_then_current_stale_disposition(self):
        completion_locked, finish_completion, permission_started = (Event() for _ in range(3))
        pids = {}
        command, reviewed = str(uuid4()), self.reviewed()

        def analysis_clock():
            if self.provider.calls:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids["analysis"] = cursor.fetchone()[0]
                completion_locked.set()
                if not finish_completion.wait(10):
                    raise AssertionError("Completion transaction was not released")
            return timezone.now()

        def withdraw_worker():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids["permission"] = cursor.fetchone()[0]
            permission_started.set()
            return self.withdraw()

        with ThreadPoolExecutor(max_workers=2) as pool:
            analysis_future = pool.submit(recorded.independent,
                lambda: self.analyse(command, reviewed=reviewed, clock=analysis_clock))
            try:
                self.assertTrue(completion_locked.wait(10))
                permission_future = pool.submit(recorded.independent, withdraw_worker)
                self.assertTrue(permission_started.wait(10))
                self.server_lock_wait(pids["permission"], pids["analysis"],
                    "macro_monitoring_sourcestate")
            finally:
                finish_completion.set()
            original = analysis_future.result(timeout=10)["analysis"]
            permission = permission_future.result(timeout=10)
        self.assertEqual(original["status"], "analysed")
        self.assertEqual(original["current_disposition"], "current")
        self.assertEqual(original["stale_reasons"], [])
        self.assertLessEqual(NewsAnalysisResult.objects.get().finished_at.isoformat(),
            permission["observed_at"])
        current = analysis.get_news_command(self.actor, self.thesis["id"], command)["analysis"]
        self.assertEqual(current["status"], "analysed")
        self.assertEqual(current["current_disposition"], "stale")
        self.assertIn("source_contract_unavailable", current["stale_reasons"])
        self.assertEqual(current["document"], original["document"])
        self.assert_retained(original)

    def test_completion_cannot_backdate_permission_observation_or_repeat_paid_call(self):
        permission_at = timezone.now() + timedelta(seconds=5)
        self.provider.callback = lambda: self.withdraw(clock=lambda: permission_at)
        command, reviewed = str(uuid4()), self.reviewed()
        with self.assertRaisesMessage(news_context.NewsConflict,
                "Trusted clock precedes source permission observation"):
            self.analyse(command, reviewed=reviewed)
        attempt = NewsAnalysisAttempt.objects.get()
        self.assertFalse(NewsAnalysisResult.objects.exists())
        replay = self.analyse(command, reviewed=reviewed,
            clock=lambda: attempt.deadline_at + timedelta(seconds=1))["analysis"]
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["status"], "outcome_unknown")
        self.assertIn("source_contract_unavailable", replay["stale_reasons"])
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.provider.catalog_calls, 1)

    def test_invalid_return_is_retained_without_overwriting_original_failure(self):
        def complete(model_id, messages):
            self.provider.calls += 1
            self.withdraw()
            return {"content": "invalid output", "provider_request_id": "invalid-recorded-response",
                "usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14},
                "reported_cost_usd": "0.001"}
        self.provider.complete = complete
        result = self.analyse()["analysis"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["current_disposition"], "stale")
        self.assertEqual(result["stop_reason"], "invalid_model_output")
        self.assertIsNone(result["document"])
        self.assertEqual(result["reported_cost_usd"], "0.001")
        self.assertEqual(result["usage"]["total_tokens"], 14)
        self.assertIn("source_contract_unavailable", result["stale_reasons"])
        self.assertEqual(NewsAnalysisResult.objects.get().provider_metadata["provider_request_id"],
            "invalid-recorded-response")
        self.assertEqual(self.provider.calls, 1)
