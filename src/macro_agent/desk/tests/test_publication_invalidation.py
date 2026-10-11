"""Actual source writers invalidate daily authority without rewriting history."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from hashlib import sha256
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.domain.daily_review import ReviewCapacityExceeded
from macro_agent.monitoring import capture
from macro_agent.monitoring.models import CaptureOutcome, SourceReport, SourceRevision, SourceState
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.monitoring.tests import test_analysis as recorded
from macro_agent.persistence.models import AssessmentRecord, AuditTransition, BriefStateRecord, CurrentAssessment, NotificationIntent
from macro_agent.persistence.publication_store import DjangoPublicationStore
from macro_agent.positions import service as positions
from macro_agent.theses import service as theses

from macro_agent.desk import permissions, publication, service
from macro_agent.desk.invalidation import invalidate_daily_briefs, lock_source_dependents
from macro_agent.desk.models import DailyBrief, DailyPublication, DailyReview
from . import test_service as daily


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    SETTINGS_MODULE="macro_agent.web.local_settings")
class DailyPublicationInvalidationTests(TransactionTestCase):
    setUp = daily.DailyReviewPersistenceTests.setUp
    capture = daily.DailyReviewPersistenceTests.capture
    review = daily.DailyReviewPersistenceTests.review
    server_lock_wait = recorded.PostgreSQLNewsAnalysisTests.server_lock_wait

    def publish(self, review=None, *, actor=None, fanout_limit=10):
        actor = actor or self.actor
        review = review or self.review()
        row = DailyReview.objects.get(pk=review["review"]["id"])
        binding = DailyBrief.objects.select_related("brief").filter(thesis_id=row.thesis_id).first()
        return publication.publish_review(actor, str(row.pk), command_id=str(uuid4()),
            expected_review_digest=row.digest, expected_generation=binding.brief.generation if binding else 0,
            fanout_limit=fanout_limit)

    def second_owner(self, *, fanout_limit=10, actor=None, source_id=recorded.SOURCE):
        actor = actor or str(self.other.pk)
        draft = theses.create_thesis(actor, str(uuid4()), recorded.EXACT, recorded.MEANING)["thesis"]
        text, meaning = draft["draft"]["text_version"], draft["draft"]["interpretation"]
        thesis = theses.approve_thesis(actor, draft["id"], str(uuid4()), text["id"], text["text_digest"],
            meaning["id"], meaning["digest"], draft["revision"])["thesis"]
        cutoff = timezone.now()
        review = service.create_review(actor, thesis["id"], str(uuid4()), cutoff-timedelta(days=1),
            cutoff, [source_id], daily.LIMITS)
        return self.publish(review, actor=actor, fanout_limit=fanout_limit)

    def assert_canceled(self, result):
        brief_id = result["publication"]["brief_id"]
        self.assertFalse(CurrentAssessment.objects.filter(brief_id=brief_id).exists())
        self.assertEqual(list(NotificationIntent.objects.filter(brief_id=brief_id)
            .values_list("state", flat=True)), ["canceled"])
        saved = DailyPublication.objects.get(pk=result["publication"]["id"])
        self.assertEqual(saved.assessment.status, "current")
        self.assertEqual(saved.assessment.reasons, ["all_dependencies_current"])

    def repeat_revision(self, revision):
        payload = revision.payload
        item = SourceItem(payload["id"], payload["title"], payload["url"],
            datetime.fromisoformat(payload["published_at"]) if payload["published_at"] else None,
            payload["content"])
        return capture.capture(recorded.SOURCE, recorded.CONTRACT, lambda: SourceBatch((item,), timezone.now(),
            "bounded_snapshot", False, sha256(b"exact repeated payload").hexdigest()))

    def test_correction_cancels_authority_and_pending_intent_but_preserves_original_decision(self):
        result = self.publish()
        before = (DailyReview.objects.get().content, AssessmentRecord.objects.get().payload)
        generation = BriefStateRecord.objects.get().generation
        self.capture(title="Corrected source claim")
        self.assert_canceled(result)
        self.assertEqual(before, (DailyReview.objects.get().content, AssessmentRecord.objects.get().payload))
        self.assertEqual(BriefStateRecord.objects.get().generation, generation)
        self.assertEqual(AuditTransition.objects.filter(kind="daily_publication_invalidated").count(), 1)

    def test_new_distinct_report_and_exact_repetition_preserve_daily_interval(self):
        result = self.publish()
        self.capture("distinct-report", "Later distinct report")
        self.repeat_revision(SourceRevision.objects.get(report__native_id="report-1"))
        self.assertTrue(CurrentAssessment.objects.filter(brief_id=result["publication"]["brief_id"]).exists())
        self.assertEqual(NotificationIntent.objects.get().state, "pending")
        self.assertFalse(AuditTransition.objects.filter(kind="daily_publication_invalidated").exists())

    def test_repeated_older_payload_never_repromotes_or_invalidates_current_review(self):
        original = SourceRevision.objects.get()
        self.capture(title="Newer corrected report")
        result = self.publish(fanout_limit=1)
        head = SourceReport.objects.get(native_id="report-1").current_revision_id
        self.repeat_revision(original)
        self.assertEqual(SourceReport.objects.get(native_id="report-1").current_revision_id, head)
        self.assertTrue(CurrentAssessment.objects.filter(brief_id=result["publication"]["brief_id"]).exists())
        self.assertEqual(NotificationIntent.objects.get().state, "pending")

    def test_fanout_finds_pending_notice_after_current_pointer_cleared_within_transaction(self):
        result = self.publish()
        with transaction.atomic():
            SourceState.objects.select_for_update().get(pk=recorded.SOURCE)
            protected = lock_source_dependents(source_id=recorded.SOURCE)
            CurrentAssessment.objects.all().delete()
            # The deferred database guard forbids committing this intermediate
            # state, but fanout must still find it before pending cancellation.
            rediscovered = lock_source_dependents(source_id=recorded.SOURCE)
            self.assertEqual([row.pk for row in rediscovered], [row.pk for row in protected])
            invalidate_daily_briefs(rediscovered, timezone.now(), "source_permission_changed:" + recorded.SOURCE)
        self.assert_canceled(result)

    def test_permission_revision_invalidates_even_when_it_still_permits_processing(self):
        result = self.publish()
        source = SourceState.objects.get(pk=recorded.SOURCE)
        permissions.set_source_permission(str(self.staff.pk), source.pk, source.contract_digest,
            True, "Explicitly reviewed replacement permission version.")
        self.assert_canceled(result)

    def test_permission_withdrawal_cancels_current_output_for_inactive_owner_too(self):
        result = self.publish()
        self.owner.is_active = False
        self.owner.save(update_fields=("is_active",))
        source = SourceState.objects.get(pk=recorded.SOURCE)
        permissions.set_source_permission(str(self.staff.pk), source.pk, source.contract_digest,
            False, "Withdraw processing rights for the retained source.")
        self.assert_canceled(result)

    def test_exposure_and_approval_writers_use_shared_daily_brief_protection(self):
        result = self.publish()
        positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
            self.thesis["approved"]["approval"]["id"], recorded.DECLARATION)
        self.assert_canceled(result)
        first = DailyReview.objects.get()
        next_review = self.review(start=first.cutoff)
        next_result = self.publish(next_review)
        proposed = theses.propose_thesis(self.actor, self.thesis["id"], str(uuid4()),
            recorded.EXACT + " Reviewed amendment.", recorded.MEANING, self.thesis["revision"])["thesis"]
        text, meaning = proposed["draft"]["text_version"], proposed["draft"]["interpretation"]
        theses.approve_thesis(self.actor, self.thesis["id"], str(uuid4()), text["id"], text["text_digest"],
            meaning["id"], meaning["digest"], proposed["revision"])
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertEqual(NotificationIntent.objects.filter(brief_id=next_result["publication"]["brief_id"],
            state="canceled").count(), 2)

    def test_generic_fixture_store_cannot_publish_or_advance_a_daily_brief(self):
        result = self.publish()
        with self.assertRaises(PermissionError):
            with DjangoPublicationStore(self.actor).transaction(result["publication"]["brief_id"]):
                self.fail("Daily authority entered the synthetic publication boundary")

    def test_complete_cross_owner_fanout_enforces_smallest_persisted_bound_before_any_invalidation(self):
        first = self.publish(fanout_limit=1)
        # Construct unexpected legacy state to retain the correction-time guard.
        # Normal admission below prevents this state from arising through services.
        with patch("macro_agent.desk.invalidation.check_publication_capacity"):
            second = self.second_owner(fanout_limit=10)
        heads = dict(SourceReport.objects.values_list("pk", "current_revision_id"))
        with self.assertRaises(ReviewCapacityExceeded):
            self.capture(title="Correction exceeding one trader's reviewed fanout bound")
        self.assertEqual(dict(SourceReport.objects.values_list("pk", "current_revision_id")), heads)
        self.assertEqual(CurrentAssessment.objects.count(), 2)
        self.assertEqual(NotificationIntent.objects.filter(state="pending").count(), 2)
        self.assertFalse(AuditTransition.objects.filter(kind="daily_publication_invalidated").exists())
        self.assertEqual(DailyPublication.objects.count(), 2)
        self.assertNotEqual(first["publication"]["brief_id"], second["publication"]["brief_id"])

    def test_capacity_rejects_new_desk_before_it_can_block_permission_withdrawal(self):
        first = self.publish(fanout_limit=1)
        with self.assertRaises(ReviewCapacityExceeded):
            self.second_owner(fanout_limit=10)
        self.assertEqual(DailyPublication.objects.count(), 1)
        self.assertEqual(DailyBrief.objects.count(), 1)
        source = SourceState.objects.get(pk=recorded.SOURCE)
        permissions.set_source_permission(str(self.staff.pk), source.pk, source.contract_digest,
            False, "Withdraw after rejecting excessive source fanout.")
        self.assert_canceled(first)

    def test_complete_batch_fanout_cancels_both_owners_and_deduplicates_revision_membership(self):
        self.capture(title="Earlier correction retained as background")
        first = self.publish(fanout_limit=2)
        second = self.second_owner(fanout_limit=2)
        self.capture(title="Another correction affecting both private desks")
        self.assert_canceled(first)
        self.assert_canceled(second)
        self.assertEqual(AuditTransition.objects.filter(kind="daily_publication_invalidated").count(), 2)

    def test_cross_owner_permission_reviews_share_owner_order_after_distinct_source_locks(self):
        first = self.publish()
        self.owner.is_staff = True
        self.owner.save(update_fields=("is_staff",))
        other_source = "fixture-daily-permission-cross-owner"
        item = SourceItem("other-report", "Other desk source", "https://example.invalid/other-report", None, recorded.QUOTE)
        capture.capture(other_source, recorded.CONTRACT, lambda: SourceBatch((item,), timezone.now(),
            "bounded_snapshot", False, sha256(b"other desk source").hexdigest()))
        second = self.second_owner(actor=str(self.staff.pk), source_id=other_source)
        together = Barrier(2)

        def align_sources(**kwargs):
            # Both transactions own a different source before either attempts
            # the common owner set. Actor-first locking would now deadlock.
            together.wait(timeout=10)
            return lock_source_dependents(**kwargs)

        def withdraw(actor, source_id):
            source = SourceState.objects.get(pk=source_id)
            return permissions.set_source_permission(actor, source_id, source.contract_digest,
                False, "Independent permission reviews using common owner ordering.")

        with patch("macro_agent.desk.invalidation.lock_source_dependents", side_effect=align_sources):
            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(recorded.independent, lambda: withdraw(str(self.staff.pk), recorded.SOURCE))
                b = pool.submit(recorded.independent, lambda: withdraw(self.actor, other_source))
                self.assertFalse(a.result(timeout=15)["permitted"])
                self.assertFalse(b.result(timeout=15)["permitted"])
        self.assert_canceled(first)
        self.assert_canceled(second)

    def wait_capture(self, *, expired):
        result = self.publish()
        brief_id = result["publication"]["brief_id"]
        attempt = capture.admit_capture(recorded.SOURCE, recorded.CONTRACT)
        item = SourceItem("report-1", "Correction waiting for publication protection", "https://example.invalid/retained-report",
            timezone.now()-timedelta(days=1), recorded.QUOTE)
        batch = SourceBatch((item,), timezone.now(), "bounded_snapshot", False, sha256(b"protected correction").hexdigest())
        locked, release, sampled, writer_started = Event(), Event(), Event(), Event()
        pids, times = {}, []

        def holder():
            with transaction.atomic():
                BriefStateRecord.objects.select_for_update().get(pk=brief_id)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids["holder"] = cursor.fetchone()[0]
                locked.set()
                if not release.wait(10):
                    raise TimeoutError("Daily brief holder was not released")

        def clock():
            sampled.set()
            at = attempt.deadline_at if expired else timezone.now()
            times.append(at)
            return at

        def writer():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids["writer"] = cursor.fetchone()[0]
            writer_started.set()
            return capture.commit_batch(attempt.pk, batch, clock=clock)

        with ThreadPoolExecutor(max_workers=2) as pool:
            holder_future = pool.submit(recorded.independent, holder)
            self.assertTrue(locked.wait(10))
            writer_future = pool.submit(recorded.independent, writer)
            try:
                self.assertTrue(writer_started.wait(10))
                self.server_lock_wait(pids["writer"], pids["holder"], "macro_brief_states")
                self.assertFalse(sampled.is_set())
            finally:
                release.set()
            holder_future.result(timeout=10)
            if expired:
                with self.assertRaises(capture.CaptureFenced):
                    writer_future.result(timeout=10)
                self.assertTrue(CurrentAssessment.objects.exists())
                self.assertEqual(NotificationIntent.objects.get().state, "pending")
                self.assertFalse(CaptureOutcome.objects.filter(attempt=attempt).exists())
                self.assertEqual(SourceRevision.objects.count(), 1)
            else:
                outcome = writer_future.result(timeout=10)
                self.assertEqual(outcome.finished_at, times[0])
                self.assert_canceled(result)
        self.assertEqual(len(times), 1)

    def test_capture_samples_clock_only_after_actual_daily_brief_lock_wait(self):
        self.wait_capture(expired=False)

    def test_capture_rechecks_expired_admission_after_actual_daily_brief_lock_wait(self):
        self.wait_capture(expired=True)
