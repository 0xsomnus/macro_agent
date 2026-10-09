"""PostgreSQL capture recovery, source currentness and independent lease races."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from time import monotonic, sleep
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.monitoring import capture as capture_service
from macro_agent.monitoring import inspection
from macro_agent.monitoring import work as work_service
from macro_agent.monitoring.models import (CaptureAttempt, CaptureMembership,
    CaptureOutcome, DurableObservation, ScreeningAttempt, ScreeningResult,
    ScreeningWork, SourceReport, SourceRevision, SourceState)
from macro_agent.monitoring.sources import SourceBatch, SourceError, SourceItem, load_recorded


CONTRACT = {"kind": "fictional_fixture", "label": "Fictional feed",
            "coverage": "bounded_snapshot"}


def independent(function):
    connections.close_all()
    try:
        return function()
    finally:
        connections.close_all()


@override_settings(MACRO_ENABLE_MONITORING_PROOF=True,
                   MACRO_ALLOW_SYNTHETIC_SETUP=True,
                   SETTINGS_MODULE="macro_agent.web.local_settings")
class PostgreSQLMonitoringPipelineTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("Monitoring races require PostgreSQL")
        self.at = timezone.now()

    def item(self, title="Original fictional release", native_id="fictional-1"):
        return SourceItem(native_id, title, "https://example.invalid/news/1",
                          self.at - timedelta(days=1), "  Exact evidence\r\nΔ\r\n")

    def batch(self, items=(), *, received_at=None):
        return SourceBatch(tuple(items), received_at or timezone.now(),
                           "bounded_snapshot", False, sha256(b"recorded transport").hexdigest())

    def capture(self, *items, source="fixture-monitor"):
        return capture_service.capture(source, CONTRACT, lambda: self.batch(items))

    def revision(self):
        return SourceReport.objects.get(source_id="fixture-monitor").current_revision

    def guard(self, function):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                function()

    def server_lock_wait(self, waiter_pid, blocker_pid, *, table=None, timeout=5):
        deadline, observed = monotonic() + timeout, None
        table = table or SourceState._meta.db_table
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
        self.fail(f"Expected protected source lock wait: {observed!r}")

    def test_capture_commits_pending_work_before_postcommit_crash(self):
        def loader():
            self.assertFalse(connection.in_atomic_block)
            return self.batch([self.item()])

        def crash():
            raise RuntimeError("Process stopped after commit")

        with self.assertRaisesMessage(RuntimeError, "after commit"):
            capture_service.capture("fixture-monitor", CONTRACT, loader, after_commit=crash)
        revision = self.revision()
        self.assertEqual(SourceRevision.objects.count(), 1)
        self.assertEqual(CaptureOutcome.objects.get().status, "captured")
        self.assertEqual(ScreeningWork.objects.get().state, "pending")
        self.assertFalse(DurableObservation.objects.exists())
        self.assertEqual(revision.payload["content"], "  Exact evidence\r\nΔ\r\n")

        # A different connection acts as the restarted process, without recapture.
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(independent, lambda: work_service.work_once()).result(timeout=10)
        self.assertEqual(result[0]["decision"]["route"], "unresolved_queue")
        self.assertEqual(ScreeningWork.objects.get().state, "completed")
        self.assertEqual(CaptureAttempt.objects.count(), 1)
        observation = DurableObservation.objects.get()
        self.assertGreaterEqual(observation.observed_by_at, revision.system_received_at)
        self.assertGreater(revision.system_received_at, revision.source_claimed_published_at)

    def test_duplicates_record_receipts_without_repeating_revision_or_work(self):
        first = self.capture(self.item())
        revision = self.revision()
        again = self.capture(self.item())
        self.assertEqual(first.new_revision_count, 1)
        self.assertEqual(again.new_revision_count, 0)
        self.assertEqual(SourceRevision.objects.count(), 1)
        self.assertEqual(ScreeningWork.objects.count(), 1)
        self.assertEqual(CaptureMembership.objects.count(), 2)
        self.assertEqual(self.revision().pk, revision.pk)

    def test_old_payload_cannot_roll_back_observed_head(self):
        self.capture(self.item())
        old = self.revision()
        changed = self.capture(self.item("Changed fictional release"))
        current = self.revision()
        again = self.capture(self.item())
        self.assertNotEqual(old.pk, current.pk)
        self.assertEqual(changed.new_revision_count, 1)
        self.assertEqual(again.new_revision_count, 0)
        self.assertEqual(self.revision().pk, current.pk)
        self.assertEqual(SourceRevision.objects.count(), 2)
        self.assertEqual(ScreeningWork.objects.count(), 2)
        self.assertEqual(ScreeningWork.objects.get(pk=old.pk).state, "superseded")
        self.assertEqual(ScreeningWork.objects.get(pk=current.pk).state, "pending")

    def test_changed_payload_preserves_original_completed_decision(self):
        self.capture(self.item())
        attempt = work_service.claim_work()
        result = work_service.complete_work(attempt.token)
        original = result.decision.copy()
        self.capture(self.item("Changed fictional release"))
        result.refresh_from_db()
        self.assertEqual(result.decision, original)
        self.assertEqual(result.decision["route"], "unresolved_queue")
        self.assertEqual(ScreeningWork.objects.get(pk=attempt.work_id).state, "superseded")
        self.assertEqual(ScreeningWork.objects.get(pk=self.revision().pk).state, "pending")

    def test_no_model_key_never_converts_unresolved_into_low_relevance(self):
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_ENABLE_MODEL_COMPILATION=False,
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            self.capture(self.item())
            results = work_service.work_once()
        decision = results[0]["decision"]
        self.assertEqual(decision["route"], "unresolved_queue")
        self.assertEqual(decision["state"], "potential_or_unresolved")
        self.assertFalse(decision["early_notice"])
        self.assertFalse(decision["personalized"])
        self.assertEqual(decision["model_calls"], 0)
        self.assertIn("classifier_unavailable", decision["reasons"])

    def test_expired_worker_is_fenced_after_independent_reclaim(self):
        self.capture(self.item())
        first = work_service.claim_work(lease_seconds=1)
        reclaim_at = first.deadline_at + timedelta(seconds=1)
        with ThreadPoolExecutor(max_workers=1) as pool:
            second = pool.submit(independent, lambda: work_service.claim_work(
                clock=lambda: reclaim_at)).result(timeout=10)
        self.assertEqual(second.sequence, 2)
        self.assertNotEqual(first.token, second.token)
        with self.assertRaises(work_service.WorkFenced):
            work_service.complete_work(first.token, clock=lambda: reclaim_at)
        result = work_service.complete_work(second.token, clock=lambda: reclaim_at)
        self.assertEqual(result.attempt_id, second.token)
        self.assertEqual(ScreeningAttempt.objects.count(), 2)
        self.assertEqual(ScreeningResult.objects.count(), 1)

    def test_expired_worker_cannot_complete_even_without_reclaim(self):
        self.capture(self.item())
        attempt = work_service.claim_work(lease_seconds=1)
        with self.assertRaises(work_service.WorkFenced):
            work_service.complete_work(attempt.token, clock=lambda: attempt.deadline_at)
        self.assertFalse(ScreeningResult.objects.exists())

    def test_unavailable_source_differs_from_a_successful_empty_snapshot(self):
        def unavailable():
            raise SourceError("transport_unavailable")

        failed = capture_service.capture("fixture-monitor", CONTRACT, unavailable)
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.code, "transport_unavailable")
        self.assertIsNone(SourceState.objects.get().last_successful_capture_at)
        quiet = self.capture()
        self.assertEqual(quiet.status, "captured")
        self.assertEqual(quiet.item_count, 0)
        self.assertIsNotNone(SourceState.objects.get().last_successful_capture_at)
        self.assertFalse(SourceRevision.objects.exists())
        self.assertFalse(ScreeningWork.objects.exists())
        self.assertEqual(CaptureOutcome.objects.count(), 2)

    def test_parse_failure_creates_no_partial_receipts(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "malformed.json"
            path.write_text('{"items": [', encoding="utf-8")
            result = capture_service.capture("fixture-monitor", CONTRACT,
                                             lambda: load_recorded(path))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.code, "invalid_json")
        self.assertFalse(SourceRevision.objects.exists())
        self.assertFalse(CaptureMembership.objects.exists())
        self.assertFalse(ScreeningWork.objects.exists())

    def test_live_local_and_synthetic_gates_are_separate(self):
        for changes in ({"MACRO_ENABLE_MONITORING_PROOF": False},
                        {"SETTINGS_MODULE": "macro_agent.web.settings"},
                        {"MACRO_ALLOW_SYNTHETIC_SETUP": False}):
            with self.subTest(changes=changes), override_settings(**changes):
                with self.assertRaises(PermissionDenied):
                    capture_service.admit_capture("fixture-monitor", CONTRACT)
        self.assertFalse(SourceState.objects.exists())

    def test_outer_transactions_cannot_hide_admission_or_receipt_commit(self):
        with transaction.atomic(), self.assertRaisesMessage(ValueError, "commit before transport"):
            capture_service.admit_capture("fixture-monitor", CONTRACT)
        attempt = capture_service.admit_capture("fixture-monitor", CONTRACT)
        batch = self.batch([self.item()])
        with transaction.atomic(), self.assertRaisesMessage(ValueError, "own its transaction"):
            capture_service.commit_batch(attempt.pk, batch)
        with transaction.atomic(), self.assertRaisesMessage(ValueError, "own its transaction"):
            capture_service.fail_capture(attempt.pk, "transport_unavailable")
        capture_service.commit_batch(attempt.pk, batch)
        with transaction.atomic(), self.assertRaisesMessage(ValueError, "already committed"):
            capture_service.observe_capture(attempt.pk)
        with transaction.atomic(), self.assertRaisesMessage(ValueError, "commit before processing"):
            work_service.claim_work()
        claimed = work_service.claim_work()
        with transaction.atomic(), self.assertRaisesMessage(ValueError, "own its transaction"):
            work_service.complete_work(claimed.token)
        self.assertEqual(ScreeningWork.objects.get().state, "running")
        self.assertFalse(ScreeningResult.objects.exists())

    def test_capture_admission_is_busy_and_expired_tokens_are_fenced(self):
        first = capture_service.admit_capture("fixture-monitor", CONTRACT)
        with self.assertRaises(capture_service.CaptureBusy):
            capture_service.admit_capture("fixture-monitor", CONTRACT)
        reclaim_at = first.deadline_at + timedelta(seconds=1)
        second = capture_service.admit_capture("fixture-monitor", CONTRACT, clock=lambda: reclaim_at)
        self.assertEqual(second.sequence, 2)
        self.assertEqual(CaptureOutcome.objects.get(attempt=first).status, "outcome_unknown")
        with self.assertRaises(capture_service.CaptureFenced):
            capture_service.commit_batch(first.pk, self.batch(received_at=reclaim_at),
                                         clock=lambda: reclaim_at)
        capture_service.commit_batch(second.pk, self.batch(received_at=reclaim_at),
                                     clock=lambda: reclaim_at)
        self.assertEqual(CaptureOutcome.objects.count(), 2)

    def test_concurrent_admission_allows_one_inflight_capture(self):
        self.capture()
        barrier = Barrier(2)

        def admit():
            barrier.wait(timeout=5)
            try:
                return capture_service.admit_capture("fixture-monitor", CONTRACT).pk
            except capture_service.CaptureBusy:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(independent, admit) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(CaptureAttempt.objects.count(), 2)

    def test_concurrent_claims_cannot_obtain_two_current_tokens(self):
        self.capture(self.item())
        barrier = Barrier(2)

        def claim():
            barrier.wait(timeout=5)
            return work_service.claim_work()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(independent, claim) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(ScreeningAttempt.objects.count(), 1)
        self.assertEqual(ScreeningWork.objects.get().active_token,
                         next(value.token for value in results if value))

    def test_completion_lock_blocks_changed_payload_then_preserves_original_result(self):
        self.ordered_race(completion_first=True)

    def test_changed_payload_lock_blocks_completion_then_fences_old_result(self):
        self.ordered_race(completion_first=False)

    def ordered_race(self, *, completion_first):
        self.capture(self.item())
        old = work_service.claim_work()
        admitted = capture_service.admit_capture("fixture-monitor", CONTRACT)
        changed = self.batch([self.item("Changed fictional release")])
        held, release, attempted, clock_called = (Event() for _ in range(4))
        holder_pid, waiter_pid = {}, {}

        def pause_clock():
            holder_pid["pid"] = connection.connection.info.backend_pid
            held.set()
            if not release.wait(10):
                raise TimeoutError("Protected operation was not released")
            return timezone.now()

        def wait_clock():
            clock_called.set()
            return timezone.now()

        def holder():
            if completion_first:
                return work_service.complete_work(old.token, clock=pause_clock)
            return capture_service.commit_batch(admitted.pk, changed, clock=pause_clock)

        def waiter():
            def observe(execute, sql, params, many, context):
                if "FOR UPDATE" in sql and SourceState._meta.db_table in sql:
                    waiter_pid["pid"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                return execute(sql, params, many, context)

            with connection.execute_wrapper(observe):
                if completion_first:
                    return capture_service.commit_batch(admitted.pk, changed, clock=wait_clock)
                return work_service.complete_work(old.token, clock=wait_clock)

        with ThreadPoolExecutor(max_workers=2) as pool:
            protected = pool.submit(independent, holder)
            try:
                self.assertTrue(held.wait(10))
                waiting = pool.submit(independent, waiter)
                self.assertTrue(attempted.wait(10))
                self.server_lock_wait(waiter_pid["pid"], holder_pid["pid"])
                self.assertFalse(clock_called.is_set())
                self.assertFalse(waiting.done())
            finally:
                release.set()
            protected.result(timeout=10)
            if completion_first:
                waiting.result(timeout=10)
            else:
                with self.assertRaises(work_service.WorkFenced):
                    waiting.result(timeout=10)
        self.assertTrue(clock_called.is_set())
        self.assertEqual(ScreeningWork.objects.get(pk=old.work_id).state, "superseded")
        self.assertEqual(ScreeningWork.objects.get(pk=self.revision().pk).state, "pending")
        self.assertEqual(ScreeningResult.objects.count(), int(completion_first))
        if completion_first:
            self.assertEqual(ScreeningResult.objects.get().decision["route"], "unresolved_queue")

    def test_database_rejects_history_update_and_delete(self):
        self.capture(self.item())
        work_service.work_once()
        immutable = (CaptureAttempt, CaptureOutcome, SourceRevision, CaptureMembership,
                     DurableObservation, ScreeningAttempt, ScreeningResult)
        for model in immutable:
            row = model.objects.get()
            table = connection.ops.quote_name(model._meta.db_table)
            key = connection.ops.quote_name(model._meta.pk.column)
            for action in ("UPDATE", "DELETE"):
                with self.subTest(model=model._meta.label, action=action):
                    statement = (f"UPDATE {table} SET {key} = {key} WHERE {key} = %s"
                                 if action == "UPDATE" else
                                 f"DELETE FROM {table} WHERE {key} = %s")
                    def mutate():
                        with connection.cursor() as cursor:
                            cursor.execute(statement, [row.pk])
                    self.guard(mutate)

    def test_database_rejects_cross_source_head_and_membership(self):
        first = self.capture(self.item())
        report = SourceReport.objects.get(source_id="fixture-monitor")
        self.capture(self.item(), source="other-fictional")
        other = self.capture(self.item("Another observed revision"), source="other-fictional")
        other_revision = SourceReport.objects.get(source_id="other-fictional").current_revision
        self.guard(lambda: SourceReport.objects.filter(pk=report.pk).update(
            current_revision=other_revision, revision_count=2))
        self.guard(lambda: CaptureMembership.objects.create(
            capture_id=first.attempt_id, revision=other_revision))
        self.guard(lambda: SourceRevision.objects.create(report=report,
            observation_revision=2, digest="a" * 64, payload=self.item("Untrusted cross-source").payload(),
            system_received_at=timezone.now(), capture_id=other.attempt_id))

    def test_database_keeps_contract_fixed_and_superseded_work_terminal(self):
        self.capture(self.item())
        old = self.revision()
        self.capture(self.item("Changed fictional release"))
        self.guard(lambda: SourceState.objects.filter(pk="fixture-monitor").update(
            contract={**CONTRACT, "label": "Unreviewed source contract"}))
        self.guard(lambda: ScreeningWork.objects.filter(pk=old.pk).update(state="pending"))
        self.assertEqual(SourceState.objects.get(pk="fixture-monitor").contract, CONTRACT)
        self.assertEqual(ScreeningWork.objects.get(pk=old.pk).state, "superseded")

    def test_pending_work_is_reachable_after_one_hundred_live_leases(self):
        self.capture(*(self.item(native_id=f"leased-{index}") for index in range(100)))
        for _ in range(100):
            self.assertIsNotNone(work_service.claim_work(lease_seconds=300))
        self.capture(self.item(native_id="new-pending"))
        pending = SourceRevision.objects.get(report__native_id="new-pending")
        claimed = work_service.claim_work()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.work_id, pending.pk)
        report = inspection.inspect_source("fixture-monitor")
        self.assertEqual(report["counts"]["revisions"], 101)
        self.assertEqual(report["counts"]["running"], 101)
        self.assertEqual(len(report["revisions"]), 100)
        self.assertEqual(len(report["work"]), 100)
        self.assertTrue(report["revisions_truncated"])

    def test_claim_skips_protected_work_without_sampling_clock(self):
        self.capture(self.item())
        revision = self.revision()
        held, release, attempted, sampled = (Event() for _ in range(4))

        def clock():
            sampled.set()
            return timezone.now()

        def holder():
            with transaction.atomic():
                ScreeningWork.objects.select_for_update().get(pk=revision.pk)
                held.set()
                if not release.wait(10):
                    raise TimeoutError("Work protection not released")

        def waiter():
            def observe(execute, sql, params, many, context):
                if "FOR UPDATE" in sql and ScreeningWork._meta.db_table in sql:
                    attempted.set()
                return execute(sql, params, many, context)

            with connection.execute_wrapper(observe):
                return work_service.claim_work(clock=clock)

        with ThreadPoolExecutor(max_workers=2) as pool:
            locked = pool.submit(independent, holder)
            try:
                self.assertTrue(held.wait(10))
                waiting = pool.submit(independent, waiter)
                self.assertTrue(attempted.wait(10))
                self.assertIsNone(waiting.result(timeout=5))
                self.assertFalse(sampled.is_set())
                self.assertFalse(ScreeningAttempt.objects.exists())
            finally:
                release.set()
            locked.result(timeout=10)
        claim = work_service.claim_work(clock=clock)
        self.assertTrue(sampled.is_set())
        self.assertEqual(claim.work_id, revision.pk)

    def test_inspection_preserves_duplicate_receipt_times_and_original_disposition(self):
        self.capture(self.item())
        work_service.work_once()
        first = inspection.inspect_source("fixture-monitor")
        original = first["revisions"][0]
        self.capture(self.item())
        duplicate = inspection.inspect_source("fixture-monitor")
        self.assertEqual(duplicate["revisions"][0]["system_received_at"], original["system_received_at"])
        self.assertEqual(duplicate["revisions"][0]["durable_observed_by_at"], original["durable_observed_by_at"])
        self.assertEqual(duplicate["revisions"][0]["public_available_at"], None)
        self.assertEqual(duplicate["revisions"][0]["availability_precision"],
                         "conservative_postcommit_upper_bound")
        self.assertEqual(len(duplicate["captures"]), 2)
        self.assertGreaterEqual(duplicate["captures"][1]["received_at"],
                                duplicate["captures"][0]["received_at"])
        self.assertEqual(duplicate["captures"][1]["new_revision_count"], 0)
        self.capture(self.item("Changed fictional release"))
        changed = inspection.inspect_source("fixture-monitor")
        old = next(row for row in changed["work"] if row["revision_id"] == original["id"])
        self.assertEqual(old["current_disposition"], "superseded")
        self.assertEqual(old["attempts"][0]["attempt_disposition"], "completed")
        self.assertEqual(old["attempts"][0]["original_decision"]["route"], "unresolved_queue")
        self.assertEqual(changed["counts"], {"reports": 1, "revisions": 2, "pending": 1,
                                            "running": 0, "completed": 0, "superseded": 1})

    def test_inspection_retains_one_snapshot_while_new_payload_commits(self):
        self.capture(self.item())
        work_service.work_once()
        read, release = Event(), Event()

        def reader():
            def observe(execute, sql, params, many, context):
                result = execute(sql, params, many, context)
                if SourceState._meta.db_table in sql and sql.lstrip().upper().startswith("SELECT"):
                    read.set()
                    if not release.wait(10):
                        raise TimeoutError("Inspection snapshot not released")
                return result

            with connection.execute_wrapper(observe):
                return inspection.inspect_source("fixture-monitor")

        with ThreadPoolExecutor(max_workers=1) as pool:
            reading = pool.submit(independent, reader)
            try:
                self.assertTrue(read.wait(10))
                self.capture(self.item("Changed fictional release"))
            finally:
                release.set()
            original = reading.result(timeout=10)
        self.assertEqual(original["counts"]["revisions"], 1)
        self.assertEqual(original["counts"]["completed"], 1)
        self.assertTrue(original["revisions"][0]["is_current_observation"])
        self.assertEqual(original["work"][0]["current_disposition"], "completed")
        current = inspection.inspect_source("fixture-monitor")
        self.assertEqual(current["counts"]["revisions"], 2)
        self.assertEqual(current["counts"]["completed"], 0)
        self.assertEqual(current["counts"]["superseded"], 1)

    def test_database_rejects_pending_work_and_unreferenced_identity_deletion(self):
        self.capture(self.item())
        work = ScreeningWork.objects.get()
        self.guard(lambda: ScreeningWork.objects.filter(pk=work.pk).delete())
        state = SourceState.objects.create(id="unused-source", contract=CONTRACT,
                                           contract_digest=capture_service.canonical_digest(CONTRACT))
        report = SourceReport.objects.create(source=state, native_id="unused-report")
        self.guard(lambda: SourceReport.objects.filter(pk=report.pk).delete())
        empty = SourceState.objects.create(id="empty-source", contract=CONTRACT,
                                           contract_digest=capture_service.canonical_digest(CONTRACT))
        self.guard(lambda: SourceState.objects.filter(pk=empty.pk).delete())

    def test_mid_batch_failure_rolls_back_receipts_and_work_without_retry(self):
        created, fetched = [], []
        original_create = ScreeningWork.objects.create

        def loader():
            fetched.append(True)
            return self.batch([self.item(native_id="first"), self.item(native_id="second")])

        def fail_second_work(*args, **kwargs):
            created.append(True)
            if len(created) == 2:
                raise RuntimeError("Persistence stopped during second item")
            return original_create(*args, **kwargs)

        with patch.object(ScreeningWork.objects, "create", side_effect=fail_second_work):
            with self.assertRaisesMessage(RuntimeError, "during second item"):
                capture_service.capture("fixture-monitor", CONTRACT, loader)
        self.assertEqual(len(created), 2)
        self.assertEqual(len(fetched), 1)
        admission = CaptureAttempt.objects.get()
        state = SourceState.objects.get()
        self.assertEqual(state.active_capture, admission.pk)
        self.assertEqual(state.capture_sequence, 1)
        self.assertIsNone(state.last_successful_capture_at)
        for model in (SourceReport, SourceRevision, CaptureMembership, CaptureOutcome,
                      ScreeningWork, DurableObservation):
            self.assertEqual(model.objects.count(), 0, model._meta.label)
        with patch.object(inspection.timezone, "now", return_value=admission.deadline_at):
            report = inspection.inspect_source("fixture-monitor")
        self.assertEqual(report["health"]["last_attempt_state"], "outcome_unknown")
        self.assertEqual(report["captures"][0]["status"], "outcome_unknown")
        self.assertEqual(report["counts"]["revisions"], 0)
        self.assertEqual(report["counts"]["pending"], 0)
        self.assertEqual(len(fetched), 1)
        self.assertEqual(CaptureAttempt.objects.count(), 1)

    def test_naive_clocks_cannot_mutate_capture_admission_or_worker_leases(self):
        naive = self.at.replace(tzinfo=None)
        clock = lambda: naive
        with self.assertRaisesMessage(ValueError, "explicit timezone"):
            capture_service.admit_capture("fixture-monitor", CONTRACT, clock=clock)
        self.assertFalse(SourceState.objects.exists())
        self.assertFalse(CaptureAttempt.objects.exists())
        admission = capture_service.admit_capture("fixture-monitor", CONTRACT)
        batch = self.batch([self.item()])
        for operation in (
            lambda: capture_service.commit_batch(admission.pk, batch, clock=clock),
            lambda: capture_service.fail_capture(admission.pk, "transport_unavailable", clock=clock),
        ):
            with self.assertRaisesMessage(ValueError, "explicit timezone"):
                operation()
        self.assertEqual(SourceState.objects.get().active_capture, admission.pk)
        self.assertEqual(CaptureAttempt.objects.count(), 1)
        self.assertFalse(CaptureOutcome.objects.exists())
        self.assertFalse(SourceRevision.objects.exists())
        capture_service.commit_batch(admission.pk, batch)
        with self.assertRaisesMessage(ValueError, "explicit timezone"):
            capture_service.observe_capture(admission.pk, clock=clock)
        self.assertFalse(DurableObservation.objects.exists())
        with self.assertRaisesMessage(ValueError, "explicit timezone"):
            work_service.claim_work(clock=clock)
        work = ScreeningWork.objects.get()
        self.assertEqual(work.state, "pending")
        self.assertEqual(work.attempt_count, 0)
        self.assertIsNone(work.active_token)
        self.assertFalse(ScreeningAttempt.objects.exists())
        admitted_work = work_service.claim_work()
        with self.assertRaisesMessage(ValueError, "explicit timezone"):
            work_service.complete_work(admitted_work.token, clock=clock)
        work.refresh_from_db()
        self.assertEqual(work.state, "running")
        self.assertEqual(work.attempt_count, 1)
        self.assertEqual(work.active_token, admitted_work.token)
        self.assertEqual(work.lease_until, admitted_work.deadline_at)
        self.assertFalse(ScreeningResult.objects.exists())
