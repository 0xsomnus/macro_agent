"""Force source changes and daily admission through both database orderings."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings

from macro_agent.desk import invalidation, permissions, publication
from macro_agent.monitoring.models import SourceState
from macro_agent.monitoring.tests import test_analysis as recorded
from macro_agent.persistence.models import AssessmentRecord, CurrentAssessment, NotificationIntent
from . import test_service as daily
from . import test_publication as lifecycle


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    SETTINGS_MODULE="macro_agent.web.local_settings")
class DailyPublicationRaceTests(TransactionTestCase):
    setUp = daily.DailyReviewPersistenceTests.setUp
    capture = daily.DailyReviewPersistenceTests.capture
    review = daily.DailyReviewPersistenceTests.review
    server_lock_wait = lifecycle.DailyPublicationTests.server_lock_wait

    def race(self, *, publication_first, permission):
        review = self.review()["review"]
        source = SourceState.objects.get(pk=recorded.SOURCE)
        protected, release, second_started = Event(), Event(), Event()
        pids = {}
        def publish():
            return publication.publish_review(self.actor, review["id"], str(uuid4()), review["digest"], 0, 10)
        def change():
            if permission:
                return permissions.set_source_permission(str(self.staff.pk), source.pk, source.contract_digest,
                    False, "Explicit race-test withdrawal.")
            return self.capture(title="Correction ordered against publication")
        def worker(name, action):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids[name] = cursor.fetchone()[0]
                if name == "second":
                    second_started.set()
                return action()
            finally:
                connection.close()
        target = ("macro_agent.desk.publication.AssessmentRecord.objects.create" if publication_first
                  else "macro_agent.desk.invalidation.invalidate_daily_briefs")
        original = AssessmentRecord.objects.create if publication_first else invalidation.invalidate_daily_briefs
        def pause(*args, **kwargs):
            saved = original(*args, **kwargs)
            protected.set()
            if not release.wait(10):
                raise RuntimeError("Race release was not signalled")
            return saved
        first_action, second_action = (publish, change) if publication_first else (change, publish)
        with ThreadPoolExecutor(max_workers=2) as pool, patch(target, side_effect=pause):
            first = pool.submit(worker, "first", first_action)
            try:
                self.assertTrue(protected.wait(5))
                second = pool.submit(worker, "second", second_action)
                self.assertTrue(second_started.wait(5))
                self.server_lock_wait(pids["second"], pids["first"], "macro_monitoring_sourcestate")
            finally:
                release.set()
            first_value, second_value = first.result(timeout=10), second.result(timeout=10)
        saved = first_value if publication_first else second_value
        self.assertFalse(CurrentAssessment.objects.exists())
        if publication_first:
            self.assertEqual(saved["publication"]["original_decision"]["status"], "current")
            self.assertEqual(NotificationIntent.objects.get().state, "canceled")
        else:
            self.assertEqual(saved["publication"]["original_decision"]["status"], "superseded")
            self.assertFalse(NotificationIntent.objects.exists())
        inspected = publication.inspect_publication(self.actor, saved["publication"]["id"])
        self.assertEqual(inspected["publication"], saved["publication"])
        self.assertEqual(inspected["current_disposition"]["status"], "superseded")

    def test_correction_first_blocks_stale_publication(self):
        self.race(publication_first=False, permission=False)

    def test_publication_first_preserves_original_then_cancels_on_correction(self):
        self.race(publication_first=True, permission=False)

    def test_permission_first_blocks_stale_publication(self):
        self.race(publication_first=False, permission=True)

    def test_publication_first_preserves_original_then_cancels_on_withdrawal(self):
        self.race(publication_first=True, permission=True)
