"""Runner recovery keeps original evidence and never resends uncertain inference."""

from copy import deepcopy
from datetime import timedelta
from io import StringIO
import json
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase, override_settings

from macro_agent.desk import permissions, service as desk
from macro_agent.desk.models import DailyReview
from macro_agent.monitoring import capture, runner
from macro_agent.monitoring.models import NewsAnalysisAttempt, NewsAnalysisResult, SourceState
from macro_agent.monitoring.tests import test_runner as fixtures
from macro_agent.scheduling import service as schedule
from macro_agent.scheduling.models import AnalysisDispatch, ScheduledSlot, SlotLease, SlotOutcome, SlotRecovery


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class PostgreSQLRunnerRecoveryTests(TransactionTestCase):
    setUp = fixtures.PostgreSQLRunnerTests.setUp
    clock = fixtures.PostgreSQLRunnerTests.clock
    batch = fixtures.PostgreSQLRunnerTests.batch
    tick = fixtures.PostgreSQLRunnerTests.tick
    news_slot = fixtures.PostgreSQLRunnerTests.news_slot

    def revise_bounds(self, **changes):
        current = schedule.current_watch(self.actor, self.watch)
        config = deepcopy(current["configuration"])
        config["context_bounds"].update(changes)
        return schedule.configure_watch(self.actor, self.thesis["id"], str(uuid4()),
            current["revision"], config, clock=self.clock)

    def claim(self, kind):
        schedule.enqueue_due(self.actor, self.watch, kind=kind, clock=self.clock)
        return schedule.claim_due(self.actor, kind, watch_id=self.watch, clock=self.clock)

    def recover(self, slot, *, action="retry", command=None, token=None, revision=None,
                reason="Reviewed saved evidence and explicitly selected recovery."):
        last = SlotLease.objects.filter(slot=slot).order_by("sequence").last()
        return runner.recover_job(self.actor, str(slot.pk), command or str(uuid4()),
            token or str(last.pk), revision or schedule.current_watch(self.actor, self.watch)["revision"],
            action, reason, loaders={fixtures.SOURCE: self.batch}, provider=self.provider, clock=self.clock)

    def blocked_daily(self):
        self.revise_bounds(encoded_bytes=1)
        self.at = self.cutoff + timedelta(hours=1)
        lease = self.claim("daily_review")
        result = runner.execute_lease(lease, clock=self.clock)
        self.assertEqual(result["outcome"]["status"], "blocked")
        self.assertFalse(DailyReview.objects.exists())
        return ScheduledSlot.objects.get(pk=lease["slot_id"]), lease, result["outcome"]

    def withdraw_source(self):
        self.owner.is_staff = True
        self.owner.save(update_fields=("is_staff",))
        return permissions.set_source_permission(self.actor, fixtures.SOURCE,
            SourceState.objects.get(pk=fixtures.SOURCE).contract_digest, False,
            "Withdraw processing permission after the original result was retained.", clock=self.clock)

    def test_reviewed_larger_bounds_finish_original_daily_interval_then_unblock_successor(self):
        slot, original_lease, original = self.blocked_daily()
        self.at = self.cutoff + timedelta(days=1, hours=1)
        self.revise_bounds(encoded_bytes=1_000_000)
        schedule.enqueue_due(self.actor, self.watch, kind="daily_review", clock=self.clock)
        self.assertIsNone(schedule.claim_due(self.actor, "daily_review", watch_id=self.watch, clock=self.clock))

        result = self.recover(slot)
        self.assertEqual(result["current_slot_state"], "completed")
        self.assertEqual(result["processed"]["outcome"]["status"], "completed")
        first = DailyReview.objects.get()
        self.assertEqual(first.start, slot.period_start)
        self.assertEqual(first.cutoff, slot.cutoff)
        self.assertEqual(str(first.command_id), original_lease["command_id"])
        self.assertEqual(SlotOutcome.objects.get(lease_id=original_lease["token"]).payload, original["payload"])

        successor = schedule.claim_due(self.actor, "daily_review", watch_id=self.watch, clock=self.clock)
        self.assertIsNotNone(successor)
        self.assertNotEqual(successor["slot_id"], str(slot.pk))
        self.assertEqual(successor["period_start"], slot.cutoff.isoformat())
        self.assertEqual(runner.execute_lease(successor, clock=self.clock)["outcome"]["status"], "completed")
        self.assertEqual(DailyReview.objects.count(), 2)
        second = DailyReview.objects.order_by("cutoff").last()
        self.assertEqual(second.context.predecessor_id, first.context_id)
        self.assertEqual(self.provider.calls, 0)

    def test_retained_daily_after_crash_is_adopted_before_new_bounds_with_current_stale_disposition(self):
        self.at = self.cutoff + timedelta(hours=1)
        lease = self.claim("daily_review")
        with patch.object(schedule, "complete_slot", side_effect=fixtures.SimulatedCrash):
            with self.assertRaises(fixtures.SimulatedCrash):
                runner.execute_lease(lease, clock=self.clock)
        retained = DailyReview.objects.get()
        original = desk.inspect_review(self.actor, str(retained.pk), clock=self.clock)["review"]

        self.at += timedelta(seconds=31)
        replacement = schedule.claim_due(self.actor, "daily_review", watch_id=self.watch, clock=self.clock)
        # Simulate a worker that stopped after noticing the retained result but
        # before adopting it. The operator must recover the existing artifact.
        schedule.complete_slot(self.actor, replacement["token"], "blocked",
            {"code": "context_overflow"}, clock=self.clock)
        capture.capture(fixtures.SOURCE, fixtures.CONTRACT,
            lambda: self.batch(title="Corrected fictional source headline"), clock=self.clock)
        self.revise_bounds(encoded_bytes=1)

        result = self.recover(ScheduledSlot.objects.get(pk=lease["slot_id"]))
        adopted = result["processed"]["outcome"]["payload"]["review"]
        self.assertEqual(result["current_slot_state"], "completed")
        self.assertEqual(adopted["review"], original)
        self.assertEqual(adopted["current_disposition"]["status"], "stale")
        self.assertEqual(DailyReview.objects.count(), 1)
        self.assertEqual(self.provider.calls, 0)

    def test_retained_daily_adoption_after_permission_withdrawal_performs_no_new_assembly(self):
        self.at = self.cutoff + timedelta(hours=1)
        lease = self.claim("daily_review")
        with patch.object(schedule, "complete_slot", side_effect=fixtures.SimulatedCrash):
            with self.assertRaises(fixtures.SimulatedCrash):
                runner.execute_lease(lease, clock=self.clock)
        retained = DailyReview.objects.get()
        original = desk.inspect_review(self.actor, str(retained.pk), clock=self.clock)["review"]
        self.at += timedelta(seconds=31)
        replacement = schedule.claim_due(self.actor, "daily_review", watch_id=self.watch, clock=self.clock)
        schedule.complete_slot(self.actor, replacement["token"], "blocked",
            {"code": "context_overflow"}, clock=self.clock)
        self.withdraw_source()

        with patch.object(desk, "create_review", side_effect=AssertionError("Withdrawn input cannot enter new assembly")):
            result = self.recover(ScheduledSlot.objects.get(pk=lease["slot_id"]))
        adopted = result["processed"]["outcome"]["payload"]["review"]
        self.assertEqual(result["current_slot_state"], "completed")
        self.assertEqual(adopted["review"], original)
        self.assertEqual(adopted["current_disposition"]["status"], "stale")
        self.assertEqual(DailyReview.objects.count(), 1)
        self.assertEqual(self.provider.calls, 0)

    def test_dispatch_marker_without_receipt_reconciles_without_keys_catalogue_or_inference(self):
        with patch.object(runner.analysis, "analyse_next", side_effect=fixtures.SimulatedCrash):
            with self.assertRaises(fixtures.SimulatedCrash):
                self.tick()
        self.at += timedelta(seconds=31)
        self.tick()
        slot = self.news_slot()
        self.assertEqual(slot.state, "blocked")
        self.assertTrue(AnalysisDispatch.objects.filter(slot=slot).exists())
        self.assertFalse(NewsAnalysisAttempt.objects.exists())
        last = SlotLease.objects.filter(slot=slot).order_by("sequence").last()
        def at_test_clock(*args, **kwargs):
            return runner.recover_job(*args, **kwargs, clock=self.clock)
        with patch("macro_agent.monitoring.management.commands.desk_recover.recover_job", side_effect=at_test_clock), \
                self.assertRaisesRegex(CommandError, "only read-only reconciliation is allowed"):
            call_command("desk_recover", "--owner", self.actor, "--slot-id", str(slot.pk),
                "--command-id", str(uuid4()), "--expected-token", str(last.pk),
                "--expected-watch-revision", "1", "--action", "retry",
                "--reason", "Attempt to repeat dispatched work must be denied.")
        self.assertFalse(SlotRecovery.objects.exists())

        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                               SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch.object(self.provider, "list_models", side_effect=AssertionError("No catalogue during reconciliation")), \
                patch.object(self.provider, "complete", side_effect=AssertionError("No inference during reconciliation")):
            result = self.recover(slot, action="reconcile")
        self.assertEqual(result["current_slot_state"], "blocked")
        outcome = result["processed"]["outcome"]
        self.assertEqual(outcome["status"], "unresolved")
        self.assertEqual(outcome["payload"]["code"], "dispatch_started_without_saved_news_receipt")
        self.assertFalse(outcome["payload"]["paid_retry_authorized"])
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.provider.catalog_calls, 0)
        self.assertFalse(NewsAnalysisAttempt.objects.exists())

    def test_saved_success_reconciles_after_permission_withdrawal_without_another_model_request(self):
        lease = self.claim("analysis")
        # The model result commits before the separate observation step fails.
        with patch.object(desk, "observe_analysis_results", side_effect=ValueError("Observation unavailable")):
            failed = runner.execute_lease(lease, provider=self.provider, clock=self.clock)
        self.assertEqual(failed["outcome"]["status"], "blocked")
        self.assertEqual(NewsAnalysisResult.objects.count(), 1)
        self.assertEqual(self.provider.calls, 1)
        self.withdraw_source()

        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                               SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch.object(self.provider, "list_models", side_effect=AssertionError("No catalogue during reconciliation")), \
                patch.object(self.provider, "complete", side_effect=AssertionError("No inference during reconciliation")):
            result = self.recover(ScheduledSlot.objects.get(pk=lease["slot_id"]), action="reconcile")
        self.assertEqual(result["current_slot_state"], "completed")
        saved = result["processed"]["outcome"]["payload"]["analysis"]
        self.assertEqual(saved["status"], "analysed")
        self.assertEqual(saved["current_disposition"], "stale")
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.provider.catalog_calls, 1)
        self.assertEqual(NewsAnalysisResult.objects.count(), 1)
        self.assertEqual(SlotOutcome.objects.get(lease_id=lease["token"]).status, "blocked")

    def test_successful_reconciliation_releases_unresolved_allowance_without_erasing_history(self):
        lease = self.claim("analysis")
        with patch.object(desk, "observe_analysis_results", side_effect=ValueError("Observation unavailable")):
            original = runner.execute_lease(lease, provider=self.provider, clock=self.clock)
        self.assertEqual(original["outcome"]["status"], "blocked")
        self.assertEqual(self.provider.calls, 1)
        request = AnalysisDispatch.objects.get(slot_id=lease["slot_id"]).request
        self.at += timedelta(seconds=61)
        next_lease = self.claim("analysis")
        self.assertIsNotNone(next_lease)
        with self.assertRaises(schedule.AnalysisAllowanceExhausted):
            schedule.mark_analysis_started(self.actor, next_lease["token"], request, clock=self.clock)
        self.assertEqual(AnalysisDispatch.objects.count(), 1)

        result = self.recover(ScheduledSlot.objects.get(pk=lease["slot_id"]), action="reconcile")
        self.assertEqual(result["current_slot_state"], "completed")
        admitted = schedule.mark_analysis_started(self.actor, next_lease["token"], request, clock=self.clock)
        self.assertEqual(admitted["slot_id"], next_lease["slot_id"])
        self.assertEqual(AnalysisDispatch.objects.count(), 2)
        historical = SlotOutcome.objects.get(lease_id=lease["token"])
        self.assertEqual(historical.status, "blocked")
        self.assertEqual(historical.payload, original["outcome"]["payload"])
        self.assertEqual(NewsAnalysisResult.objects.count(), 1)
        self.assertEqual(self.provider.calls, 1)

    def test_exact_recovery_command_replay_never_executes_even_after_permission_change(self):
        slot, lease, _ = self.blocked_daily()
        reviewed = self.revise_bounds(encoded_bytes=1_000_000)
        command, reason = str(uuid4()), "Reviewed bounds and retained the complete evidence set."
        first = self.recover(slot, command=command, token=lease["token"],
            revision=reviewed["revision"], reason=reason)
        counts = (SlotLease.objects.count(), SlotOutcome.objects.count(), SlotRecovery.objects.count(), DailyReview.objects.count())
        self.withdraw_source()
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch.object(runner, "execute_lease", side_effect=AssertionError("Historical command replay cannot execute")):
            replay = self.recover(slot, command=command, token=lease["token"],
                revision=reviewed["revision"], reason=reason)
        self.assertTrue(replay["replayed"])
        self.assertIsNone(replay["processed"])
        self.assertEqual(replay["recovery"], first["recovery"])
        self.assertEqual(replay["current_slot_state"], "completed")
        self.assertEqual(counts, (SlotLease.objects.count(), SlotOutcome.objects.count(), SlotRecovery.objects.count(), DailyReview.objects.count()))

    def test_recovery_losing_its_lease_does_not_guess_the_present_job_state(self):
        slot, _, _ = self.blocked_daily()
        self.revise_bounds(encoded_bytes=1_000_000)

        def replaced_while_working(lease, clock):
            self.at += timedelta(seconds=31)
            replacement = schedule.claim_due(self.actor, "daily_review", watch_id=self.watch, clock=self.clock)
            self.assertNotEqual(replacement["token"], lease["token"])
            return "completed", {"model_calls": 0}

        with patch.object(runner, "_daily_slot", side_effect=replaced_while_working):
            result = self.recover(slot)
        self.assertEqual(result["processed"]["outcome"]["status"], "lease_lost")
        self.assertIsNone(result["current_slot_state"])
        self.assertEqual(SlotRecovery.objects.count(), 1)
        self.assertFalse(DailyReview.objects.exists())

    def test_cli_brief_and_explicit_recovery_preserve_inspected_outcome_and_reason(self):
        lease = self.claim("analysis")
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            original = runner.execute_lease(lease, provider=self.provider, clock=self.clock)
        out = StringIO()
        before = (SlotLease.objects.count(), SlotOutcome.objects.count())
        call_command("desk_inspect", "--owner", self.actor, "--watch-id", self.watch, "--brief", stdout=out)
        self.assertIn("analysis: pending=0, running=0, completed=0, blocked=1", out.getvalue())
        self.assertIn("selected_provider_not_configured", out.getvalue())
        self.assertEqual(before, (SlotLease.objects.count(), SlotOutcome.objects.count()))

        out, command, reason = StringIO(), str(uuid4()), "Configured provider remains unavailable; inspect without paid calls."
        def at_test_clock(*args, **kwargs):
            return runner.recover_job(*args, **kwargs, clock=self.clock)
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch("macro_agent.monitoring.management.commands.desk_recover.recover_job", side_effect=at_test_clock):
            call_command("desk_recover", "--owner", self.actor, "--slot-id", lease["slot_id"],
                "--command-id", command, "--expected-token", lease["token"],
                "--expected-watch-revision", "1", "--action", "retry", "--reason", reason, stdout=out)
        response = json.loads(out.getvalue())
        self.assertEqual(response["recovery"]["reason"], reason)
        self.assertEqual(response["current_slot_state"], "blocked")
        self.assertEqual(response["processed"]["outcome"]["payload"]["code"], "selected_provider_not_configured")
        self.assertEqual(SlotOutcome.objects.get(lease_id=lease["token"]).payload, original["outcome"]["payload"])
        self.assertEqual(SlotRecovery.objects.count(), 1)
        self.assertEqual(self.provider.calls, 0)
