"""Independent PostgreSQL checks for fair, nonblocking, durable work admission."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Event
from unittest.mock import Mock

from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.monitoring import capture as capture_service
from macro_agent.monitoring import work as work_service
from macro_agent.monitoring.models import (DurableObservation, ScreeningAttempt,
    ScreeningResult, ScreeningWork, SourceRevision, SourceState)
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.monitoring.tests.test_pipeline import CONTRACT, independent


@override_settings(MACRO_ENABLE_MONITORING_PROOF=True,
                   MACRO_ALLOW_SYNTHETIC_SETUP=True,
                   SETTINGS_MODULE="macro_agent.web.local_settings")
class PostgreSQLWorkSchedulingTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("Work scheduling races require PostgreSQL")

    def capture(self, source, *identities, observe=True):
        def load():
            items = tuple(SourceItem(identity, "Fictional release",
                "https://example.invalid/news/1", None, "Fictional evidence")
                for identity in identities)
            return SourceBatch(items, timezone.now(), "bounded_snapshot", False,
                               sha256(b"recorded work scheduling").hexdigest())

        def crash_after_commit():
            raise RuntimeError("Stopped before durable observation")

        if observe:
            return capture_service.capture(source, CONTRACT, load)
        with self.assertRaisesMessage(RuntimeError, "before durable observation"):
            capture_service.capture(source, CONTRACT, load,
                                    after_commit=crash_after_commit)

    def revision(self, identity):
        return SourceRevision.objects.get(report__native_id=identity)

    def assert_claim_while_locked(self, locker, expected):
        held, release = Event(), Event()

        def holder():
            with transaction.atomic():
                locker()
                held.set()
                if not release.wait(10):
                    raise TimeoutError("Scheduling lock was not released")

        with ThreadPoolExecutor(max_workers=2) as pool:
            locked = pool.submit(independent, holder)
            try:
                self.assertTrue(held.wait(10))
                claiming = pool.submit(independent, work_service.claim_work)
                # The independent holder remains protected for this assertion.
                # Waiting for it would deadlock this test until the timeout.
                claim = claiming.result(timeout=5)
                self.assertEqual(claim.work_id, expected.pk)
            finally:
                release.set()
            locked.result(timeout=10)
        return claim

    def test_locked_empty_first_source_does_not_block_unrelated_work(self):
        self.capture("a-empty")
        self.capture("z-ready", "later-source")
        expected = self.revision("later-source")
        self.assert_claim_while_locked(
            lambda: SourceState.objects.select_for_update().get(pk="a-empty"),
            expected)

    def test_locked_oldest_source_is_skipped_without_hiding_later_work(self):
        self.capture("a-locked", "older-locked")
        self.capture("z-ready", "later-ready")
        self.assert_claim_while_locked(
            lambda: SourceState.objects.select_for_update().get(pk="a-locked"),
            self.revision("later-ready"))
        self.assertEqual(ScreeningWork.objects.get(
            pk=self.revision("older-locked").pk).state, "pending")
        claim = work_service.claim_work()
        self.assertEqual(claim.work_id, self.revision("older-locked").pk)

    def test_locked_oldest_work_is_skipped_without_hiding_same_source_work(self):
        self.capture("same-source", "older-locked")
        self.capture("same-source", "later-ready")
        older = self.revision("older-locked")
        self.assert_claim_while_locked(
            lambda: ScreeningWork.objects.select_for_update().get(pk=older.pk),
            self.revision("later-ready"))
        self.assertEqual(ScreeningWork.objects.get(pk=older.pk).state, "pending")
        self.assertEqual(work_service.claim_work().work_id, older.pk)

    def test_later_source_progresses_despite_replenished_first_source(self):
        self.capture("a-replenished", "initial-first-source")
        self.capture("z-older", "older-later-source")
        expected = self.revision("older-later-source")
        chosen = []
        with ThreadPoolExecutor(max_workers=1) as pool:
            for index in range(5):
                pool.submit(independent, lambda index=index: self.capture(
                    "a-replenished", f"new-first-source-{index}")).result(timeout=10)
                attempt = pool.submit(independent, work_service.claim_work).result(timeout=10)
                chosen.append(attempt.work_id)
                pool.submit(independent, lambda: work_service.complete_work(
                    attempt.token)).result(timeout=10)
        self.assertEqual(chosen[:2], [self.revision("initial-first-source").pk,
                                     expected.pk])
        self.assertEqual(ScreeningWork.objects.get(pk=expected.pk).state, "completed")

    def test_more_than_one_hundred_live_older_leases_do_not_hide_pending_work(self):
        self.capture("a-live-leases", *(f"leased-{i}" for i in range(100)))
        self.capture("a-live-leases", "leased-100")
        for _ in range(101):
            self.assertIsNotNone(work_service.claim_work(lease_seconds=300))
        self.capture("z-ready", "later-ready")
        with ThreadPoolExecutor(max_workers=1) as pool:
            claim = pool.submit(independent, work_service.claim_work).result(timeout=10)
        self.assertEqual(claim.work_id, self.revision("later-ready").pk)
        self.assertEqual(ScreeningWork.objects.filter(state="running").count(), 102)

    def test_equal_receipts_use_stable_revision_identity_order(self):
        self.capture("same-receipt", "first-item", "second-item")
        revisions = list(SourceRevision.objects.order_by("pk"))
        self.assertEqual(revisions[0].system_received_at, revisions[1].system_received_at)
        first = work_service.claim_work()
        second = work_service.claim_work()
        self.assertEqual([first.work_id, second.work_id], [row.pk for row in revisions])

    def test_clock_is_sampled_only_after_source_and_work_protection(self):
        self.capture("protected-source", "protected-work")
        revision = self.revision("protected-work")

        def cannot_lock(model, pk):
            try:
                with transaction.atomic():
                    model.objects.select_for_update(nowait=True).get(pk=pk)
            except DatabaseError:
                return True
            return False

        def protected_clock():
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertTrue(pool.submit(independent, lambda: cannot_lock(
                    SourceState, "protected-source")).result(timeout=5))
                self.assertTrue(pool.submit(independent, lambda: cannot_lock(
                    ScreeningWork, revision.pk)).result(timeout=5))
            return timezone.now()

        claim = work_service.claim_work(clock=protected_clock)
        self.assertEqual(claim.work_id, revision.pk)

    def test_claim_rejects_manual_transaction_without_effects(self):
        self.capture("manual-transaction", "pending", observe=False)
        clock = Mock(side_effect=AssertionError("Unprotected clock sampled"))
        connection.set_autocommit(False)
        try:
            with self.assertRaisesMessage(ValueError, "commit before processing"):
                work_service.claim_work(clock=clock)
            self.assertFalse(ScreeningAttempt.objects.exists())
            self.assertFalse(DurableObservation.objects.exists())
            with ThreadPoolExecutor(max_workers=1) as pool:
                visible = pool.submit(independent, lambda: (
                    ScreeningAttempt.objects.count(), DurableObservation.objects.count(),
                    ScreeningWork.objects.get().state)).result(timeout=5)
            self.assertEqual(visible, (0, 0, "pending"))
        finally:
            connection.rollback()
            connection.set_autocommit(True)
        clock.assert_not_called()
        self.assertIsNotNone(work_service.claim_work())

    def test_completion_rejects_manual_transaction_without_effects(self):
        self.capture("manual-transaction", "pending")
        attempt = work_service.claim_work()
        clock = Mock(side_effect=AssertionError("Unprotected clock sampled"))
        connection.set_autocommit(False)
        try:
            with self.assertRaisesMessage(ValueError, "own its transaction"):
                work_service.complete_work(attempt.token, clock=clock)
            self.assertFalse(ScreeningResult.objects.exists())
            with ThreadPoolExecutor(max_workers=1) as pool:
                visible = pool.submit(independent, lambda: (
                    ScreeningResult.objects.count(), ScreeningWork.objects.get().state,
                    ScreeningWork.objects.get().active_token)).result(timeout=5)
            self.assertEqual(visible, (0, "running", attempt.token))
        finally:
            connection.rollback()
            connection.set_autocommit(True)
        clock.assert_not_called()
        result = work_service.complete_work(attempt.token)
        self.assertEqual(result.attempt_id, attempt.token)
