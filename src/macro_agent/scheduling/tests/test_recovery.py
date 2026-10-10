"""Audited recovery cannot rewrite old work or repeat uncertain inference."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier, Event
from time import monotonic
from uuid import uuid4

from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings

from macro_agent.scheduling import recovery, service
from macro_agent.scheduling.models import AnalysisDispatch, ScheduledSlot, SlotLease, SlotOutcome, SlotRecovery
from . import test_scheduler as fixtures


@override_settings(SETTINGS_MODULE="macro_agent.web.local_settings", MACRO_ENABLE_MONITORING_PROOF=True,
                   MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ALLOW_SYNTHETIC_SETUP=True)
class PostgreSQLRecoveryTests(TransactionTestCase):
    setUp = fixtures.PostgreSQLSchedulerTests.setUp
    watch = fixtures.PostgreSQLSchedulerTests.watch
    enqueue = fixtures.PostgreSQLSchedulerTests.enqueue
    claim = fixtures.PostgreSQLSchedulerTests.claim
    request = fixtures.PostgreSQLSchedulerTests.request
    guard = fixtures.PostgreSQLSchedulerTests.guard

    def blocked(self, kind="capture", *, dispatched=False, config=None):
        watch = self.watch(config)
        self.enqueue(watch, kind=kind)
        lease = self.claim(kind, watch=watch)
        if dispatched:
            service.mark_analysis_started(self.actor, lease["token"], self.request(), clock=lambda: self.at)
        outcome = service.complete_slot(self.actor, lease["token"], "unresolved" if dispatched else "blocked",
            {"code": "response_not_recorded" if dispatched else "ValueError"}, clock=lambda: self.at)
        return watch, lease, outcome

    def recover(self, watch, prior, *, action="retry", command=None, reason="Reviewed retained outcome and chosen recovery.",
                at=None, actor=None, revision=None, token=None):
        return recovery.begin_recovery(actor or self.actor, prior["slot_id"], command or str(uuid4()),
            token or prior["token"], revision if revision is not None else watch["revision"], action, reason,
            clock=lambda: at or self.at)

    def revise_watch(self, watch, *, at=None, **changes):
        config = deepcopy(watch["configuration"])
        config.update(changes)
        return service.configure_watch(self.actor, self.thesis_id, str(uuid4()), watch["revision"], config,
                                       clock=lambda: at or self.at)

    def test_retry_preserves_original_job_and_outcome_but_pins_reviewed_current_configuration(self):
        watch, prior, original = self.blocked("daily_review")
        changed = self.revise_watch(watch, context_bounds={**self.config["context_bounds"], "reports": 200})
        result = self.recover(changed, prior)
        self.assertFalse(result["replayed"])
        self.assertEqual(result["current_slot_state"], "running")
        self.assertEqual(result["recovery"]["action"], "retry")
        self.assertEqual(result["recovery"]["prior_token"], prior["token"])
        self.assertEqual(result["lease"]["mode"], "execute")
        self.assertEqual(result["lease"]["command_id"], prior["command_id"])
        self.assertEqual(result["lease"]["original_watch_version_id"], prior["watch_version_id"])
        self.assertEqual(result["lease"]["watch_version_id"], changed["watch_version_id"])
        self.assertEqual(result["lease"]["configuration"]["context_bounds"]["reports"], 200)
        row = ScheduledSlot.objects.get(pk=prior["slot_id"])
        self.assertEqual(str(row.watch_version_id), prior["watch_version_id"])
        self.assertEqual(row.period_start.isoformat(), prior["period_start"])
        self.assertEqual(row.cutoff.isoformat(), prior["cutoff"])
        self.assertEqual(SlotOutcome.objects.get(lease_id=prior["token"]).payload, original["payload"])
        self.assertEqual(SlotRecovery.objects.count(), 1)
        self.assertEqual(SlotLease.objects.count(), 2)

    def test_exact_command_replay_after_completion_configuration_and_permission_change_is_inert(self):
        watch, prior, original = self.blocked()
        command = str(uuid4())
        first = self.recover(watch, prior, command=command)
        service.complete_slot(self.actor, first["lease"]["token"], "completed", {"retained": True}, clock=lambda: self.at)
        self.revise_watch(watch, capture_interval_seconds=90)
        counts = (SlotRecovery.objects.count(), SlotLease.objects.count(), SlotOutcome.objects.count())
        with override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=False, MACRO_MODEL_API_KEY="",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            replay = self.recover(watch, prior, command=command)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["recovery"], first["recovery"])
        self.assertEqual(replay["lease"]["token"], first["lease"]["token"])
        self.assertEqual(replay["current_slot_state"], "completed")
        self.assertEqual(counts, (SlotRecovery.objects.count(), SlotLease.objects.count(), SlotOutcome.objects.count()))
        self.assertEqual(SlotOutcome.objects.get(lease_id=prior["token"]).payload, original["payload"])
        with self.assertRaises(service.ScheduleConflict):
            self.recover(watch, prior, command=command, reason="Different recovery intent")

    def test_owner_last_token_watch_revision_and_required_reason_are_protected(self):
        watch, prior, _ = self.blocked()
        with self.assertRaises(service.ScheduleUnavailable):
            self.recover(watch, prior, actor=str(self.other.pk))
        for change in ({"token": str(uuid4())}, {"revision": watch["revision"] + 1}):
            with self.subTest(change=change), self.assertRaises(service.ScheduleConflict):
                self.recover(watch, prior, **change)
        for reason in ("", "  ", "x" * 2001):
            with self.subTest(reason=reason[:10]), self.assertRaises(ValueError):
                self.recover(watch, prior, reason=reason)
        with self.assertRaises(ValueError):
            self.recover(watch, prior, action="force")
        self.assertFalse(SlotRecovery.objects.exists())
        self.assertEqual(SlotLease.objects.count(), 1)
        self.assertEqual(ScheduledSlot.objects.get().state, "blocked")

    def test_dispatched_analysis_denies_retry_and_reconcile_does_not_need_current_provider_or_source_permission(self):
        watch, prior, original = self.blocked("analysis", dispatched=True)
        with self.assertRaises(service.ScheduleConflict):
            self.recover(watch, prior, action="retry")
        with override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=False, MACRO_MODEL_PROVIDER="openrouter",
                               MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            result = self.recover(watch, prior, action="reconcile")
            self.assertEqual(result["lease"]["mode"], "recover")
            self.assertEqual(result["lease"]["analysis_request"], self.request())
            with self.assertRaises(service.InferenceAlreadyStarted):
                service.mark_analysis_started(self.actor, result["lease"]["token"], self.request(), clock=lambda: self.at)
        self.assertEqual(AnalysisDispatch.objects.count(), 1)
        self.assertEqual(SlotOutcome.objects.get(lease_id=prior["token"]).payload, original["payload"])
        self.assertEqual(result["recovery"]["action"], "reconcile")

    def test_reconcile_requires_analysis_dispatch_and_retry_still_requires_source_permission(self):
        watch, prior, _ = self.blocked()
        with self.assertRaises(service.ScheduleConflict):
            self.recover(watch, prior, action="reconcile")
        with override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=False, SETTINGS_MODULE="macro_agent.web.local_settings"):
            with self.assertRaises(service.ScheduleUnavailable):
                self.recover(watch, prior)
        self.assertFalse(SlotRecovery.objects.exists())

    def test_analysis_retry_respects_zero_or_occupied_inflight_allowance(self):
        watch, prior, _ = self.blocked("analysis")
        zero = self.revise_watch(watch, allowances={**self.config["allowances"], "inflight_slots": 0})
        with self.assertRaises(service.ScheduleConflict):
            self.recover(zero, prior)
        restored = self.revise_watch(zero, allowances=self.config["allowances"])
        later = self.at + timedelta(seconds=61)
        self.enqueue(restored, at=later, kind="analysis")
        active = self.claim("analysis", at=later, watch=restored)
        self.assertIsNotNone(active)
        with self.assertRaises(service.ScheduleConflict):
            self.recover(restored, prior, at=later)
        self.assertFalse(SlotRecovery.objects.exists())

    def test_reconciliation_does_not_consume_fresh_inflight_call_allowance(self):
        watch, prior, _ = self.blocked("analysis", dispatched=True)
        zero = self.revise_watch(watch, allowances={**self.config["allowances"], "inflight_slots": 0})
        result = self.recover(zero, prior, action="reconcile")
        self.assertEqual(result["lease"]["mode"], "recover")
        self.assertEqual(AnalysisDispatch.objects.count(), 1)

    def test_daily_retry_cannot_rewrite_original_source_manifest(self):
        watch, prior, _ = self.blocked("daily_review")
        second = type(self.source).objects.create(pk="fixture-second", contract=self.source.contract,
                                                  contract_digest=self.source.contract_digest)
        changed = self.revise_watch(watch, sources=[{"source_id": second.pk, "contract_digest": second.contract_digest}])
        with self.assertRaises(service.ScheduleConflict):
            self.recover(changed, prior)
        self.assertFalse(SlotRecovery.objects.exists())
        self.assertEqual(ScheduledSlot.objects.get().state, "blocked")

    def test_expired_recovery_carries_forward_exact_recovery_configuration_and_fences_old_completion(self):
        watch, prior, _ = self.blocked()
        reviewed = self.revise_watch(watch, capture_interval_seconds=90)
        first = self.recover(reviewed, prior)
        self.revise_watch(reviewed, capture_interval_seconds=120)
        later = self.at + timedelta(seconds=31)
        with ThreadPoolExecutor(max_workers=1) as pool:
            resumed = pool.submit(fixtures.independent, lambda: self.claim("capture", at=later, watch=watch)).result(timeout=10)
        self.assertEqual(resumed["command_id"], prior["command_id"])
        self.assertEqual(resumed["recovery_id"], first["recovery"]["recovery_id"])
        self.assertEqual(resumed["watch_version_id"], reviewed["watch_version_id"])
        self.assertEqual(resumed["configuration"]["capture_interval_seconds"], 90)
        self.assertEqual(SlotRecovery.objects.count(), 1)
        self.assertEqual(SlotLease.objects.count(), 3)
        self.assertEqual(SlotOutcome.objects.get(lease_id=first["lease"]["token"]).status, "expired")
        with self.assertRaises(service.ScheduleFenced):
            service.complete_slot(self.actor, first["lease"]["token"], "completed", {}, clock=lambda: later)

    def test_competing_operator_commands_admit_one_recovery_on_independent_connections(self):
        watch, prior, _ = self.blocked()
        ready = Barrier(2)
        def attempt():
            ready.wait(timeout=5)
            try:
                return self.recover(watch, prior)
            except service.ScheduleConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(fixtures.independent, attempt) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(SlotRecovery.objects.count(), 1)
        self.assertEqual(SlotLease.objects.count(), 2)
        self.assertEqual(ScheduledSlot.objects.get().state, "running")

    def test_recovery_clock_is_sampled_after_independent_slot_protection(self):
        watch, prior, _ = self.blocked()
        entered, release, requested, sampled = Event(), Event(), Event(), Event()
        pending_pid = []
        def hold_slot():
            with transaction.atomic():
                ScheduledSlot.objects.select_for_update().get(pk=prior["slot_id"])
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("Recovery ordering was not released")
        def begin():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pending_pid.append(cursor.fetchone()[0])
            requested.set()
            return recovery.begin_recovery(self.actor, prior["slot_id"], str(uuid4()), prior["token"],
                watch["revision"], "retry", "Verify protected clock ordering",
                clock=lambda: (sampled.set() or self.at))
        with ThreadPoolExecutor(max_workers=2) as pool:
            holder = pool.submit(fixtures.independent, hold_slot)
            self.assertTrue(entered.wait(timeout=3))
            pending = pool.submit(fixtures.independent, begin)
            self.assertTrue(requested.wait(timeout=3))
            try:
                deadline, waiting = monotonic() + 3, False
                while monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT cardinality(pg_blocking_pids(%s)) > 0", pending_pid)
                        waiting = cursor.fetchone()[0]
                    if waiting:
                        break
                    release.wait(timeout=0.01)
                self.assertTrue(waiting, "Recovery must reach independent PostgreSQL lock contention")
                self.assertFalse(sampled.is_set())
            finally:
                release.set()
            result = pending.result(timeout=10)
            holder.result(timeout=10)
        self.assertTrue(sampled.is_set())
        self.assertEqual(result["recovery"]["created_at"], self.at.isoformat())

    def test_clock_rollback_and_caller_transactions_do_not_admit_recovery(self):
        watch, prior, _ = self.blocked()
        for at in (self.at - timedelta(seconds=1), self.at.replace(tzinfo=None)):
            with self.subTest(at=at), self.assertRaises(ValueError):
                self.recover(watch, prior, at=at)
        with transaction.atomic(), self.assertRaises(RuntimeError):
            self.recover(watch, prior)
        connection.set_autocommit(False)
        try:
            with self.assertRaises(RuntimeError):
                self.recover(watch, prior)
        finally:
            connection.rollback()
            connection.set_autocommit(True)
        self.assertFalse(SlotRecovery.objects.exists())
        self.assertEqual(SlotLease.objects.count(), 1)

    def test_database_preserves_recovery_and_rejects_unaudited_blocked_to_running_transition(self):
        watch, prior, _ = self.blocked()
        self.guard(lambda: ScheduledSlot.objects.filter(pk=prior["slot_id"]).update(
            state="running", active_token=uuid4(), lease_until=self.at+timedelta(seconds=30), attempt_count=2))
        result = self.recover(watch, prior)
        self.guard(lambda: SlotRecovery.objects.update(reason="Rewritten operator decision"))
        def delete_recovery():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM macro_scheduling_slotrecovery WHERE id=%s", [result["recovery"]["recovery_id"]])
        self.guard(delete_recovery)
        self.guard(lambda: SlotLease.objects.filter(pk=result["lease"]["token"]).update(recovery=None))
        self.assertEqual(SlotRecovery.objects.get().reason, "Reviewed retained outcome and chosen recovery.")

    def test_sql_recovery_scope_and_dispatch_action_cannot_be_forged(self):
        watch, prior, _ = self.blocked("analysis", dispatched=True)
        fields = {"owner": self.owner, "command_id": uuid4(), "slot_id": prior["slot_id"],
            "prior_lease_id": prior["token"], "watch_version_id": watch["watch_version_id"],
            "action": "reconcile", "reason": "Forged transition guard proof", "created_at": self.at,
            "request_digest": "d" * 64, "initial_lease_token": uuid4()}
        for changes in ({"owner": self.other}, {"action": "retry"}, {"reason": ""}):
            with self.subTest(changes=changes):
                self.guard(lambda changes=changes: SlotRecovery.objects.create(**{**fields, **changes}))
        self.assertFalse(SlotRecovery.objects.exists())

    def test_inspection_preserves_recovery_history_and_current_state_without_issuing_new_lease(self):
        watch, prior, _ = self.blocked()
        result = self.recover(watch, prior)
        before = (SlotRecovery.objects.count(), SlotLease.objects.count(), SlotOutcome.objects.count())
        inspected = service.inspect_watch(self.actor, watch["watch_id"])
        saved = inspected["slots"][0]
        self.assertEqual(saved["recoveries"][0], result["recovery"])
        self.assertEqual(saved["leases"][-1]["recovery_id"], result["recovery"]["recovery_id"])
        self.assertEqual(before, (SlotRecovery.objects.count(), SlotLease.objects.count(), SlotOutcome.objects.count()))
