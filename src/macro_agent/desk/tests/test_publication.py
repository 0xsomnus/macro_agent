"""Original decisions, current daily authority and protected restart behavior."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.desk import publication
from macro_agent.desk.models import DailyPublication, DailyReview
from macro_agent.monitoring.tests import test_analysis as recorded
from macro_agent.persistence.models import AssessmentRecord, BriefStateRecord, BriefVersion, CurrentAssessment, NotificationIntent
from macro_agent.theses import service as theses
from . import test_service as daily


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    SETTINGS_MODULE="macro_agent.web.local_settings")
class DailyPublicationTests(TransactionTestCase):
    setUp = daily.DailyReviewPersistenceTests.setUp
    capture = daily.DailyReviewPersistenceTests.capture
    review = daily.DailyReviewPersistenceTests.review

    def server_lock_wait(self, waiter_pid, blocker_pid, table):
        deadline = monotonic() + 5
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_stat_clear_snapshot()")
                cursor.execute("SELECT wait_event_type, query, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=%s", [waiter_pid])
                row = cursor.fetchone()
            if row and row[0] == "Lock" and table in row[1] and blocker_pid in row[2]:
                return
            sleep(0.01)
        self.fail(f"Expected actual PostgreSQL wait on {table}: {row!r}")

    def publish(self, review=None, *, command=None, generation=None, **kwargs):
        review = review or self.review()
        preview = publication.preview_publication(self.actor, review["review"]["id"], 10)
        return publication.publish_review(self.actor, preview["review_id"], command or str(uuid4()),
            preview["review_digest"], preview["expected_generation"] if generation is None else generation,
            10, **kwargs)

    def test_current_version_intent_and_exact_review_commit_together(self):
        review = self.review()
        saved = self.publish(review)
        self.assertEqual(saved["review"], review["review"])
        self.assertEqual(saved["publication"]["original_decision"], {
            "status": "current", "reasons": ["all_dependencies_current"], "reassessment_required": False})
        self.assertEqual(saved["publication"]["generation_at_publication"], 1)
        self.assertEqual(saved["notification_intent"]["state"], "pending")
        self.assertEqual(saved["current_disposition"]["status"], "current")
        current = publication.get_current_brief(self.actor, self.thesis["id"])
        self.assertEqual(current["current_publication"]["publication"], saved["publication"])
        self.assertEqual((DailyPublication.objects.count(), AssessmentRecord.objects.count(),
            BriefVersion.objects.count(), CurrentAssessment.objects.count(), NotificationIntent.objects.count()), (1,1,1,1,1))

    def test_retry_preserves_original_and_cannot_reactivate_after_correction(self):
        review, command = self.review(), str(uuid4())
        saved = self.publish(review, command=command)
        self.capture(title="Corrected source")
        retry = self.publish(review, command=command, generation=0)
        self.assertTrue(retry["replayed"])
        self.assertEqual(retry["publication"], saved["publication"])
        self.assertEqual(retry["notification_intent"]["state"], "canceled")
        self.assertEqual(retry["current_disposition"]["status"], "superseded")
        self.assertEqual(DailyPublication.objects.count(), 1)
        self.assertIsNone(publication.get_current_brief(self.actor, self.thesis["id"])["current_publication"])

    def test_same_command_different_exact_request_is_conflict(self):
        review, command = self.review(), str(uuid4())
        self.publish(review, command=command)
        with self.assertRaises(theses.ThesisConflict):
            self.publish(review, command=command, generation=1)
        with self.assertRaises(theses.ThesisConflict):
            publication.publish_review(self.actor, review["review"]["id"], command,
                "0"*64, 0, 10)

    def test_a_new_command_cannot_republish_the_same_review(self):
        review = self.review()
        self.publish(review)
        with self.assertRaises(theses.ThesisConflict):
            self.publish(review)
        self.assertEqual(BriefStateRecord.objects.get().generation, 1)

    def test_stale_first_admission_records_reasons_without_authority(self):
        review = self.review()
        self.capture(title="Correction before publication")
        saved = self.publish(review)
        self.assertEqual(saved["publication"]["original_decision"]["status"], "superseded")
        self.assertTrue(saved["publication"]["original_decision"]["reassessment_required"])
        self.assertIsNone(saved["publication"]["generation_at_publication"])
        self.assertIsNone(saved["notification_intent"])
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertEqual(BriefStateRecord.objects.get().generation, 0)

    def test_later_retained_review_prevents_older_unpublished_admission(self):
        old = self.review()
        later = self.review(start=DailyReview.objects.get().cutoff)
        saved = self.publish(old)
        self.assertEqual(saved["publication"]["original_decision"]["reasons"], ["newer_retained_review"])
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertEqual(self.publish(later)["publication"]["generation_at_publication"], 1)

    def test_newer_generation_cancels_old_notice_and_preserves_old_version(self):
        first = self.publish()
        later = self.review(start=DailyReview.objects.get().cutoff)
        second = self.publish(later)
        self.assertEqual(second["publication"]["generation_at_publication"], 2)
        historical = publication.inspect_publication(self.actor, first["publication"]["id"])
        self.assertEqual(historical["publication"], first["publication"])
        self.assertEqual(historical["notification_intent"]["state"], "canceled")
        self.assertEqual(historical["current_disposition"]["reasons"], ["newer_publication"])
        self.assertEqual(BriefVersion.objects.count(), 2)
        self.assertEqual(NotificationIntent.objects.filter(state="pending").count(), 1)

    def test_obsolete_generation_saves_superseded_decision_without_canceling_current(self):
        first = self.publish()
        later = self.review(start=DailyReview.objects.get().cutoff)
        obsolete = self.publish(later, generation=0)
        self.assertEqual(obsolete["publication"]["original_decision"]["reasons"], ["newer_publication"])
        self.assertEqual(publication.get_current_brief(self.actor, self.thesis["id"])
            ["current_publication"]["publication"], first["publication"])
        self.assertEqual(NotificationIntent.objects.filter(state="pending").count(), 1)

    def test_no_historical_fallback_and_private_staff_reads(self):
        self.assertIsNone(publication.get_current_brief(self.actor, self.thesis["id"])["brief_id"])
        saved = self.publish()
        for actor in (str(self.other.pk), str(self.staff.pk)):
            with self.assertRaises(theses.ThesisUnavailable):
                publication.inspect_publication(actor, saved["publication"]["id"])
            with self.assertRaises(theses.ThesisUnavailable):
                publication.get_current_brief(actor, self.thesis["id"])
        self.capture(title="Withdraw previous factual claim")
        current = publication.get_current_brief(self.actor, self.thesis["id"])
        self.assertIsNotNone(current["brief_id"])
        self.assertEqual(current["generation"], 1)
        self.assertIsNone(current["current_publication"])

    def test_explicit_immutable_capacity_and_strict_integers(self):
        review = self.review()["review"]
        for limit in (True, 0, 1001, "10"):
            with self.assertRaises(ValueError):
                publication.preview_publication(self.actor, review["id"], limit)
        self.publish({"review":review})
        with self.assertRaises(theses.ThesisConflict):
            publication.preview_publication(self.actor, review["id"], 11)
        for generation in (True, -1, "0", 2**63):
            with self.assertRaises(ValueError):
                publication.publish_review(self.actor, review["id"], str(uuid4()), review["digest"], generation, 10)

    def test_clock_is_sampled_after_brief_wait(self):
        first = self.publish()
        review = self.review(start=DailyReview.objects.get().cutoff)
        ready, sampled = Event(), []
        brief_id = first["publication"]["brief_id"]
        result = {}
        def worker():
            close_old_connections()
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                result["pid"] = cursor.fetchone()[0]
            ready.set()
            try:
                return self.publish(review, clock=lambda: (sampled.append(timezone.now()) or sampled[-1]))
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                BriefStateRecord.objects.select_for_update().get(pk=brief_id)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    blocker_pid = cursor.fetchone()[0]
                pending = pool.submit(worker)
                self.assertTrue(ready.wait(5))
                self.server_lock_wait(result["pid"], blocker_pid, "macro_brief_states")
                self.assertEqual(sampled, [])
                released = timezone.now()
            saved = pending.result(timeout=10)
        self.assertGreaterEqual(sampled[0], released)
        self.assertEqual(saved["publication"]["original_decision"]["status"], "current")
