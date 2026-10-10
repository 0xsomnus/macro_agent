"""PostgreSQL runner traces, restart boundaries and independent capture progress."""

from datetime import timedelta
from hashlib import sha256
from io import StringIO
import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.exceptions import PermissionDenied
from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.desk import service as desk
from macro_agent.desk.models import DailyReview
from macro_agent.monitoring import capture, news_context, runner
from macro_agent.monitoring.models import DurableObservation, NewsAnalysisAttempt, NewsAnalysisResult, SourceRevision, SourceState
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.monitoring.tests.test_analysis import (
    CONTRACT, DECLARATION, EXACT, MEANING, MODEL, QUOTE, SOURCE, RecordedProvider,
)
from macro_agent.positions import service as positions
from macro_agent.scheduling import service as schedule
from macro_agent.scheduling.models import AnalysisDispatch, ScheduledSlot
from macro_agent.theses import compilation, service as theses


class SimulatedCrash(BaseException):
    pass


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class PostgreSQLRunnerTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="runner-owner")
        self.actor = str(self.owner.pk)
        draft = theses.create_thesis(self.actor, str(uuid4()), EXACT, MEANING)["thesis"]
        text, meaning = draft["draft"]["text_version"], draft["draft"]["interpretation"]
        self.thesis = theses.approve_thesis(self.actor, draft["id"], str(uuid4()), text["id"],
            text["text_digest"], meaning["id"], meaning["digest"], draft["revision"])["thesis"]
        self.approval = self.thesis["approved"]["approval"]["id"]
        self.position = positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
            self.approval, DECLARATION)["position"]
        capture.capture(SOURCE, CONTRACT, self.batch)
        self.at = timezone.now() + timedelta(seconds=1)
        self.cutoff = (self.at + timedelta(hours=1)).replace(second=0, microsecond=0)
        reviewed = news_context.review_context(self.actor, self.thesis["id"])
        self.config = {"schema_version": "internal-desk-watch-v1", "approval_id": self.approval,
            "exposure_digest": reviewed["exposure_digest"],
            "sources": [{"source_id": SOURCE, "contract_digest": SourceState.objects.get(pk=SOURCE).contract_digest}],
            "provider": "nanogpt", "model_id": MODEL,
            "model_configuration": runner.analysis.model_configuration("nanogpt"),
            "capture_interval_seconds": 60, "analysis_interval_seconds": 60, "lease_seconds": 30,
            "timezone": "UTC", "daily_time": self.cutoff.strftime("%H:%M"),
            "daily_start_date": self.cutoff.date().isoformat(), "daily_backlog_limit": 8,
            "context_bounds": {"reports": 100, "analyses": 100, "exposure_versions": 100,
                "issues": 100, "source_contracts": 16, "encoded_bytes": 1_000_000},
            "allowances": {"window_seconds": 3600, "analysis_dispatches": 10,
                "inflight_slots": 1, "unresolved_slots": 1}}
        self.watch = schedule.configure_watch(self.actor, self.thesis["id"], str(uuid4()), 0,
            self.config, clock=self.clock)["watch_id"]
        self.provider = RecordedProvider()

    def clock(self):
        return self.at

    def batch(self, native="report-1", title="Fictional policy and funding announcement"):
        received = getattr(self, "at", None) or timezone.now()
        item = SourceItem(native, title, "https://example.invalid/retained-report",
            received - timedelta(days=1), "  " + QUOTE + "\r\nΔ\r\n")
        return SourceBatch((item,), received, "bounded_snapshot", False, sha256(b"recorded").hexdigest())

    def tick(self, role="analysis", **kwargs):
        return runner.run_tick(self.actor, self.watch, role, clock=self.clock,
            loaders={SOURCE: self.batch}, provider=kwargs.pop("provider", self.provider), **kwargs)

    def news_slot(self):
        return ScheduledSlot.objects.filter(watch_id=self.watch, kind="analysis").order_by("created_at").first()

    def test_capture_restart_analysis_and_late_daily_once_preserve_exact_inputs(self):
        self.tick("capture")
        connections.close_all()  # New database session, no retained in-process work.
        first = self.tick()
        self.assertEqual(first["processed"][0]["outcome"]["status"], "completed")
        self.assertEqual(self.provider.calls, 1)
        self.at = self.cutoff + timedelta(hours=1)
        result = self.tick()
        daily = next(row for row in result["processed"] if row["kind"] == "daily_review")
        self.assertEqual(daily["outcome"]["status"], "completed")
        self.assertTrue(daily["outcome"]["payload"]["late"])
        review = DailyReview.objects.get()
        saved = desk.inspect_review(self.actor, str(review.pk), clock=self.clock)
        self.assertEqual(saved["review"]["original_inputs"]["approved_user"]["text"]["exact_text"], EXACT)
        self.assertEqual(saved["current_disposition"]["status"], "prepared")
        self.assertIn(str(NewsAnalysisAttempt.objects.get().pk), json.dumps(saved["review"]["content"]))
        self.tick()
        self.assertEqual(DailyReview.objects.count(), 1)
        self.assertEqual(self.provider.calls, 1)

    def test_result_commit_before_slot_completion_recovers_without_keys_or_respend(self):
        with patch.object(schedule, "complete_slot", side_effect=SimulatedCrash):
            with self.assertRaises(SimulatedCrash):
                self.tick()
        self.assertEqual(NewsAnalysisResult.objects.count(), 1)
        self.at += timedelta(seconds=31)
        connections.close_all()
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            result = self.tick()
        old = result["processed"][0]
        self.assertEqual(old["outcome"]["status"], "completed")
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.provider.catalog_calls, 1)
        self.assertEqual(NewsAnalysisResult.objects.count(), 1)

    def test_uncertain_paid_call_blocks_another_dispatch_but_not_capture_or_daily(self):
        self.provider.callback = lambda: (_ for _ in ()).throw(SimulatedCrash())
        with self.assertRaises(SimulatedCrash):
            self.tick()
        self.at += timedelta(seconds=31)
        self.provider.callback = None
        recovery = self.tick()
        self.assertEqual(recovery["processed"][0]["outcome"]["status"], "unresolved")
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.tick("capture")["processed"][0]["outcome"]["status"], "completed")
        self.at = self.cutoff + timedelta(hours=1)
        self.tick()
        self.assertEqual(DailyReview.objects.count(), 1)
        self.assertEqual(self.provider.calls, 1)

    def test_dispatch_marker_without_admission_never_sends_after_restart(self):
        with patch.object(runner.analysis, "analyse_next", side_effect=SimulatedCrash):
            with self.assertRaises(SimulatedCrash):
                self.tick()
        self.assertTrue(AnalysisDispatch.objects.exists())
        self.assertFalse(NewsAnalysisAttempt.objects.exists())
        self.at += timedelta(seconds=31)
        result = self.tick()
        payload = result["processed"][0]["outcome"]["payload"]
        self.assertEqual(payload["code"], "dispatch_started_without_saved_news_receipt")
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.provider.catalog_calls, 0)

    def test_capture_commit_without_witness_recovers_when_next_snapshot_omits_report(self):
        self.at += timedelta(seconds=1)
        with self.assertRaises(SimulatedCrash):
            capture.capture(SOURCE, CONTRACT, lambda: self.batch("orphan-report"), clock=self.clock,
                after_commit=lambda: (_ for _ in ()).throw(SimulatedCrash()))
        revision = SourceRevision.objects.get(report__native_id="orphan-report")
        self.assertFalse(DurableObservation.objects.filter(pk=revision.pk).exists())
        self.at += timedelta(seconds=1)
        result = self.tick("capture")
        self.assertIn(str(revision.pk), result["receipt_observations"]["observed_revision_ids"])
        self.assertEqual(DurableObservation.objects.get(pk=revision.pk).observed_by_at, self.at)
        self.assertEqual(SourceRevision.objects.filter(report__native_id="orphan-report").count(), 1)

    def test_known_provider_mismatch_blocks_before_dispatch_marker(self):
        with override_settings(MACRO_MODEL_PROVIDER="openrouter", SETTINGS_MODULE="macro_agent.web.local_settings"):
            result = self.tick()
        self.assertEqual(result["processed"][0]["outcome"]["payload"]["code"], "selected_provider_not_configured")
        self.assertFalse(AnalysisDispatch.objects.exists())
        self.assertEqual(self.provider.catalog_calls, 0)

    def test_preflight_block_without_dispatch_does_not_consume_uncertain_call_allowance(self):
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            self.tick()
        self.at += timedelta(seconds=61)
        result = self.tick()
        self.assertEqual(result["processed"][0]["outcome"]["status"], "completed")
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(AnalysisDispatch.objects.count(), 1)

    def test_changed_news_prompt_configuration_blocks_before_dispatch(self):
        changed = {**self.config["model_configuration"], "prompt_version": "unreviewed-next-prompt"}
        with patch.object(runner.analysis, "model_configuration", return_value=changed):
            result = self.tick()
        self.assertEqual(result["processed"][0]["outcome"]["payload"]["code"], "model_configuration_changed")
        self.assertFalse(AnalysisDispatch.objects.exists())
        self.assertEqual(self.provider.catalog_calls, 0)

    def test_daily_schedule_error_does_not_stop_capture_or_news_analysis(self):
        with patch.object(schedule, "scheduled_at", side_effect=ValueError("ambiguous daily time")):
            result = self.tick("capture")
            self.assertEqual(result["processed"][0]["outcome"]["status"], "completed")
            self.at = self.cutoff + timedelta(hours=1)
            result = self.tick()
        self.assertEqual(result["scheduled"]["daily_schedule_error"]["code"], "ValueError")
        self.assertEqual(result["processed"][0]["outcome"]["status"], "completed")
        self.assertEqual(self.provider.calls, 1)

    def test_daily_slot_enqueued_on_time_but_prepared_after_restart_is_labelled_late(self):
        self.at = self.cutoff
        schedule.enqueue_due(self.actor, self.watch, kind="daily_review", clock=self.clock)
        self.at += timedelta(seconds=10)
        result = self.tick()
        daily = next(row for row in result["processed"] if row["kind"] == "daily_review")
        self.assertFalse(ScheduledSlot.objects.get(pk=daily["slot_id"]).late)
        self.assertTrue(daily["outcome"]["payload"]["late"])

    def test_exposure_change_blocks_analysis_before_call(self):
        current = positions.get_position(self.actor, self.position["id"])
        positions.revise_position(self.actor, self.position["id"], str(uuid4()), current["revision"],
            self.approval, {**DECLARATION, "quantity": "2", "quantity_unit": "paper contracts"}, clock=self.clock)
        result = self.tick()
        self.assertEqual(result["processed"][0]["outcome"]["payload"]["code"], "reviewed_approval_or_exposure_changed")
        self.assertFalse(AnalysisDispatch.objects.exists())
        self.assertEqual(self.provider.calls, 0)

    def test_invalid_model_output_remains_failed_not_successful_slot(self):
        self.provider.complete = lambda *args: {"content": "{}", "usage": compilation.UNKNOWN_USAGE}
        result = self.tick()
        self.assertEqual(result["processed"][0]["outcome"]["status"], "failed")
        self.assertEqual(self.news_slot().state, "blocked")

    def test_expired_completion_keeps_committed_result_and_runner_alive(self):
        self.provider.callback = lambda: setattr(self, "at", self.at + timedelta(seconds=31))
        result = self.tick()
        self.assertEqual(result["processed"][0]["outcome"]["status"], "lease_lost")
        self.assertEqual(NewsAnalysisResult.objects.count(), 1)
        self.provider.callback = None
        self.assertEqual(self.tick()["processed"][0]["outcome"]["status"], "completed")
        self.assertEqual(self.provider.calls, 1)

    def test_permissions_and_owner_gate_do_not_enqueue_work(self):
        other = get_user_model().objects.create_user(username="runner-other")
        with self.assertRaises(PermissionError):
            runner.run_tick(str(other.pk), self.watch, "capture", clock=self.clock)
        with override_settings(MACRO_ENABLE_CONTINUOUS_DESK=False, SETTINGS_MODULE="macro_agent.web.local_settings"):
            with self.assertRaises((PermissionError, PermissionDenied)):
                self.tick()
        with transaction.atomic():
            with self.assertRaises(RuntimeError):
                self.tick()
        self.assertEqual(ScheduledSlot.objects.count(), 0)

    def test_management_preview_and_inspect_are_readonly(self):
        out = StringIO()
        call_command("desk_watch", owner=self.actor, thesis_id=self.thesis["id"], preview=True, stdout=out)
        self.assertEqual(json.loads(out.getvalue())["thesis"]["approval_id"], self.approval)
        out = StringIO()
        call_command("desk_inspect", owner=self.actor, watch_id=self.watch, stdout=out)
        self.assertEqual(json.loads(out.getvalue())["watch_id"], self.watch)
        self.assertEqual(ScheduledSlot.objects.count(), 0)
        self.assertEqual(self.provider.calls, 0)
