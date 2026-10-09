"""Capture owns commits before transport and conservative durability witnesses."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from unittest.mock import Mock

from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.monitoring import capture as capture_service
from macro_agent.monitoring.models import (CaptureAttempt, CaptureMembership,
    CaptureOutcome, DurableObservation, ScreeningWork, SourceReport,
    SourceRevision, SourceState)
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.monitoring.tests.test_pipeline import CONTRACT, independent


@override_settings(MACRO_ENABLE_MONITORING_PROOF=True,
                   MACRO_ALLOW_SYNTHETIC_SETUP=True,
                   SETTINGS_MODULE="macro_agent.web.local_settings")
class CaptureTransactionBoundaryTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("Capture durability checks require PostgreSQL")

    def batch(self):
        item = SourceItem("fictional-1", "Fictional release",
                          "https://example.invalid/news/1", None, "Exact evidence")
        return SourceBatch((item,), timezone.now(), "bounded_snapshot", False,
                           sha256(b"recorded transport").hexdigest())

    def independently(self, function):
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(independent, function).result(timeout=5)

    def test_disabled_autocommit_rejects_admission_before_loader_or_records(self):
        loader = Mock(side_effect=AssertionError("Transport must not be reached"))
        operations = (
            lambda: capture_service.admit_capture("fixture-monitor", CONTRACT),
            lambda: capture_service.capture("fixture-monitor", CONTRACT, loader),
        )
        connection.set_autocommit(False)
        try:
            self.assertFalse(connection.in_atomic_block)
            for operation in operations:
                with self.subTest(operation=operation), self.assertNumQueries(0):
                    with self.assertRaisesMessage(ValueError, "commit before transport"):
                        operation()
        finally:
            connection.rollback()
            connection.set_autocommit(True)
        loader.assert_not_called()
        for model in (SourceState, CaptureAttempt, CaptureOutcome, SourceReport,
                      SourceRevision, CaptureMembership, ScreeningWork, DurableObservation):
            self.assertFalse(model.objects.exists(), model._meta.label)

    def test_disabled_autocommit_rejects_receipt_and_failure_before_state_changes(self):
        attempt = capture_service.admit_capture("fixture-monitor", CONTRACT)
        batch = self.batch()
        operations = (
            lambda: capture_service.commit_batch(attempt.pk, batch),
            lambda: capture_service.fail_capture(attempt.pk, "transport_unavailable"),
        )
        connection.set_autocommit(False)
        try:
            for operation in operations:
                with self.subTest(operation=operation), self.assertNumQueries(0):
                    with self.assertRaisesMessage(ValueError, "own its transaction"):
                        operation()
        finally:
            connection.rollback()
            connection.set_autocommit(True)
        self.assertEqual(SourceState.objects.get().active_capture, attempt.pk)
        self.assertEqual(CaptureAttempt.objects.count(), 1)
        for model in (CaptureOutcome, SourceReport, SourceRevision, CaptureMembership,
                      ScreeningWork, DurableObservation):
            self.assertFalse(model.objects.exists(), model._meta.label)

    def test_disabled_autocommit_rejects_recovered_observation_before_reading(self):
        attempt = capture_service.admit_capture("fixture-monitor", CONTRACT)
        capture_service.commit_batch(attempt.pk, self.batch())
        connection.set_autocommit(False)
        try:
            with self.assertNumQueries(0):
                with self.assertRaisesMessage(ValueError, "already committed input"):
                    capture_service.observe_capture(attempt.pk)
        finally:
            connection.rollback()
            connection.set_autocommit(True)
        self.assertFalse(DurableObservation.objects.exists())
        capture_service.observe_capture(attempt.pk)
        self.assertEqual(self.independently(lambda: DurableObservation.objects.count()), 1)

    def test_normal_capture_commits_each_boundary_before_external_observation(self):
        def admission_snapshot():
            with transaction.atomic():
                source = SourceState.objects.select_for_update(nowait=True).get(pk="fixture-monitor")
                attempt = CaptureAttempt.objects.get(pk=source.active_capture)
                return (attempt.sequence, CaptureOutcome.objects.count(),
                        SourceRevision.objects.count(), DurableObservation.objects.count())

        def loader():
            self.assertFalse(connection.in_atomic_block)
            self.assertTrue(connection.get_autocommit())
            self.assertEqual(self.independently(admission_snapshot), (1, 0, 0, 0))
            return self.batch()

        def receipt_snapshot():
            with transaction.atomic():
                source = SourceState.objects.select_for_update(nowait=True).get(pk="fixture-monitor")
                return (source.active_capture, CaptureOutcome.objects.get().status,
                        SourceRevision.objects.count(), CaptureMembership.objects.count(),
                        ScreeningWork.objects.get().state, DurableObservation.objects.count())

        def after_commit():
            self.assertFalse(connection.in_atomic_block)
            self.assertTrue(connection.get_autocommit())
            self.assertEqual(self.independently(receipt_snapshot),
                             (None, "captured", 1, 1, "pending", 0))

        result = capture_service.capture("fixture-monitor", CONTRACT, loader,
                                         after_commit=after_commit)
        self.assertEqual(result.status, "captured")
        observed_at, received_at = self.independently(lambda: (
            DurableObservation.objects.get().observed_by_at,
            SourceRevision.objects.get().system_received_at))
        self.assertGreaterEqual(observed_at, received_at)
