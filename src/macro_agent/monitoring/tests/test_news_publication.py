"""Protected evolving analysis, internal qualified review and source-order races."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.domain.daily_review import ReviewCapacityExceeded
from macro_agent.domain.news_publication import POLICY_VERSION, decide_attention
from macro_agent.desk import permissions
from macro_agent.monitoring import analysis, publication
from macro_agent.monitoring.attention_models import NewsBrief, NewsPublication
from macro_agent.monitoring.models import NewsAnalysisAttempt, SourceState
from macro_agent.persistence.models import (AssessmentRecord, BriefStateRecord, BriefVersion,
    CurrentAssessment, NotificationIntent)
from macro_agent.persistence.publication_store import DjangoPublicationStore
from macro_agent.positions import service as positions
from macro_agent.theses import service as theses
from . import test_analysis as recorded
from . import test_cumulative_analysis as cumulative
from .test_driver_review import RecordedDriverProvider


@override_settings(MACRO_ENABLE_NEWS_ANALYSIS=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class NewsPublicationTests(TransactionTestCase):
    approve = recorded.PostgreSQLNewsAnalysisTests.approve
    approval_id = recorded.PostgreSQLNewsAnalysisTests.approval_id
    item = recorded.PostgreSQLNewsAnalysisTests.item
    batch = recorded.PostgreSQLNewsAnalysisTests.batch
    capture_item = recorded.PostgreSQLNewsAnalysisTests.capture_item
    reviewed = recorded.PostgreSQLNewsAnalysisTests.reviewed
    revise_position = recorded.PostgreSQLNewsAnalysisTests.revise_position
    replace_approval = recorded.PostgreSQLNewsAnalysisTests.replace_approval
    server_lock_wait = recorded.PostgreSQLNewsAnalysisTests.server_lock_wait
    background = cumulative.PostgreSQLCumulativeAnalysisTests.background
    cumulative = cumulative.PostgreSQLCumulativeAnalysisTests.cumulative

    def setUp(self):
        recorded.PostgreSQLNewsAnalysisTests.setUp(self)
        self.provider = RecordedDriverProvider(); self.provider.cumulative = True
        self.staff = get_user_model().objects.create_user(username="news-publication-reviewer", is_staff=True)
        self.background()

    def analysed(self):
        return self.cumulative(driver_review=True)["analysis"]

    def publish(self, output=None, *, command=None, generation=None, fanout_limit=10, **kwargs):
        output = output or self.analysed()
        preview = publication.preview_publication(self.actor, output["id"], fanout_limit, POLICY_VERSION)
        return publication.publish_analysis(self.actor, output["id"], command or str(uuid4()),
            preview["analysis_digest"], preview["expected_generation"] if generation is None else generation,
            fanout_limit, POLICY_VERSION, **kwargs)

    def assert_canceled(self, saved):
        self.assertFalse(CurrentAssessment.objects.filter(brief_id=saved["publication"]["brief_id"]).exists())
        if saved["notification_intent"]:
            self.assertEqual(NotificationIntent.objects.get(pk=saved["notification_intent"]["id"]).state, "canceled")
        self.assertIsNone(publication.get_current_brief(self.actor, self.thesis["id"])["current_publication"])

    def test_exact_analysis_current_pointer_version_and_review_intent_are_atomic(self):
        output = self.analysed()
        before = theses.get_thesis(self.actor, self.thesis["id"])
        self.assertFalse(CurrentAssessment.objects.exists())
        saved = self.publish(output)
        self.assertEqual(saved["analysis"]["document"], output["document"])
        self.assertEqual(saved["publication"]["original_decision"]["status"], "current")
        self.assertEqual(saved["publication"]["attention_decision"]["status"], "review_requested")
        self.assertEqual(saved["notification_intent"]["state"], "pending")
        self.assertEqual(saved["publication"]["generation_at_publication"], 1)
        self.assertEqual((NewsPublication.objects.count(), BriefVersion.objects.count(),
            CurrentAssessment.objects.count(), NotificationIntent.objects.count()), (1, 1, 1, 1))
        self.assertEqual(theses.get_thesis(self.actor, self.thesis["id"]), before)
        self.assertEqual(publication.get_current_brief(self.actor, self.thesis["id"])
            ["current_publication"]["publication"], saved["publication"])

    def test_empty_exposure_book_keeps_independent_driver_attention(self):
        row = self.position
        positions.close_position(self.actor, row["id"], str(uuid4()), row["revision"], self.approval_id)
        saved = self.publish()
        self.assertEqual(saved["analysis"]["document"]["trade_route"]["position_ids"], [])
        self.assertEqual(saved["notification_intent"]["state"], "pending")

    def test_exact_retry_after_correction_preserves_original_without_reactivation_or_model_call(self):
        output, command = self.analysed(), str(uuid4())
        saved = self.publish(output, command=command)
        self.background("Corrected background claim")
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter", SETTINGS_MODULE="macro_agent.web.local_settings"):
            retry = self.publish(output, command=command, generation=0)
        self.assertTrue(retry["replayed"])
        self.assertEqual(saved["publication"], retry["publication"])
        self.assertEqual(retry["current_disposition"]["status"], "superseded")
        self.assert_canceled(saved)
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (1,1))
        self.assertEqual(NewsPublication.objects.count(), 1)

    def test_source_permission_approval_and_exposure_changes_cancel_current_review(self):
        for change in ("permission", "approval", "exposure"):
            with self.subTest(change=change):
                saved = self.publish()
                if change == "permission":
                    source = SourceState.objects.get(pk=cumulative.BACKGROUND)
                    permissions.set_source_permission(str(self.staff.pk), source.pk, source.contract_digest,
                        True, "Recorded fresh permission revision")
                elif change == "approval":
                    self.replace_approval()
                else:
                    self.revise_position()
                self.assert_canceled(saved)
                # A fresh exact input is needed for the next analysis.
                self.capture_item(native="next-"+change, title="Fresh report "+change)

    def test_stale_before_publication_is_retained_without_pointer_or_intent(self):
        output = self.analysed()
        self.background("Correction before publication")
        saved = self.publish(output)
        self.assertEqual(saved["publication"]["original_decision"]["status"], "superseded")
        self.assertEqual(saved["publication"]["attention_decision"]["status"], "superseded")
        self.assertIsNone(saved["notification_intent"])
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertEqual(NewsBrief.objects.get().brief.generation, 0)

    def test_single_report_profile_and_failed_results_cannot_acquire_publication_authority(self):
        row = analysis.analyse_next(self.actor, self.thesis["id"], str(uuid4()),
            self.reviewed()["approval_id"], self.reviewed()["exposure_digest"], recorded.SOURCE,
            recorded.MODEL, "nanogpt", provider=self.provider, driver_review=True)["analysis"]
        with self.assertRaises(theses.ThesisConflict):
            publication.preview_publication(self.actor, row["id"], 10, POLICY_VERSION)
        self.assertFalse(NewsBrief.objects.exists())

    def test_no_historical_fallback_private_scope_and_generic_publisher_exclusion(self):
        saved = self.publish()
        foreign = str(self.other.pk)
        with self.assertRaises(theses.ThesisUnavailable):
            publication.inspect_publication(foreign, saved["publication"]["id"])
        with self.assertRaises(theses.ThesisUnavailable):
            publication.get_current_brief(foreign, self.thesis["id"])
        with self.assertRaises(PermissionError), DjangoPublicationStore(self.actor).transaction(saved["publication"]["brief_id"]):
            pass
        self.background("Correction clears pointer")
        self.assertIsNone(publication.get_current_brief(self.actor, self.thesis["id"])["current_publication"])

    def test_newer_retained_analysis_and_obsolete_generation_cannot_replace_current(self):
        first = self.analysed()
        saved = self.publish(first)
        self.capture_item(native="report-2", title="Later fictional report")
        second = self.analysed()
        obsolete = self.publish(second, generation=0)
        self.assertEqual(obsolete["publication"]["original_decision"]["reasons"], ["newer_publication"])
        self.assertEqual(publication.get_current_brief(self.actor, self.thesis["id"])
            ["current_publication"]["publication"], saved["publication"])
        with self.assertRaises(theses.ThesisConflict):
            self.publish(first)

    def test_unchanged_typed_driver_updates_brief_without_repeated_interruption(self):
        first = self.publish()
        self.capture_item(native="report-2", title="Repeated fictional development in another report")
        second = self.publish()
        self.assertEqual(second["publication"]["generation_at_publication"], 2)
        self.assertEqual(second["publication"]["attention_decision"]["status"], "review_carried")
        self.assertEqual(second["notification_intent"]["state"], "pending")
        self.assertEqual(NotificationIntent.objects.filter(state="pending").count(), 1)
        old = publication.inspect_publication(self.actor, first["publication"]["id"])
        self.assertEqual(old["notification_intent"]["state"], "canceled")

    def test_carried_review_keeps_direct_origin_across_model_negative_and_repeated_updates(self):
        import json
        first = self.publish()
        original = self.provider.complete
        def no_new_request(model_id, messages):
            response = original(model_id, messages)
            document = json.loads(response["content"])
            document["driver_assessment"]["attention"]["status"] = "not_identified"
            response["content"] = json.dumps(document)
            return response
        self.provider.complete = no_new_request
        for index in (2, 3):
            self.capture_item(native=f"report-{index}", title="Update without a new requested interruption")
            updated = self.publish()
            self.assertEqual(updated["publication"]["attention_decision"]["status"], "review_carried")
            self.assertEqual(updated["publication"]["attention_origin_publication_id"], first["publication"]["id"])
            self.assertEqual(updated["notification_intent"]["state"], "pending")
        self.assertEqual(NotificationIntent.objects.filter(state="pending").count(), 1)
        self.assertEqual(NewsPublication.objects.exclude(attention_origin__isnull=True).count(), 2)
        self.background("Origin evidence corrected after successive carries")
        self.assert_canceled(updated)

    def test_pending_origin_dependencies_cannot_be_dropped_by_a_new_source_manifest(self):
        first = self.publish()
        reviewed = self.reviewed()
        output = analysis.analyse_next(self.actor, self.thesis["id"], str(uuid4()),
            reviewed["approval_id"], reviewed["exposure_digest"], cumulative.BACKGROUND,
            recorded.MODEL, "nanogpt", provider=self.provider, context_source_ids=(cumulative.BACKGROUND,),
            context_limits=cumulative.LIMITS, driver_review=True)["analysis"]
        with self.assertRaises(theses.ThesisConflict):
            self.publish(output)
        with patch.object(publication, "_preserve_attention_origin"), self.assertRaises(DatabaseError):
            self.publish(output)
        self.assertEqual(publication.get_current_brief(self.actor, self.thesis["id"])
            ["current_publication"]["publication"], first["publication"])
        self.assertEqual(NewsPublication.objects.count(), 1)
        self.assertEqual(NotificationIntent.objects.filter(state="pending").count(), 1)

    def test_changed_typed_driver_review_creates_a_new_internal_intent(self):
        import json
        first = self.publish()
        original = self.provider.complete
        def changed(model_id, messages):
            response = original(model_id, messages)
            document = json.loads(response["content"])
            document["driver_assessment"]["approved_drivers"][0]["mechanism"]["status"] = "mixed"
            response["content"] = json.dumps(document)
            return response
        self.provider.complete = changed
        self.capture_item(native="report-2", title="New evidence changes typed mechanism support")
        second = self.publish()
        self.assertEqual(second["publication"]["attention_decision"]["status"], "review_requested")
        self.assertEqual(second["notification_intent"]["state"], "pending")
        self.assertEqual(NotificationIntent.objects.filter(state="pending").count(), 1)
        self.assertEqual(second["publication"]["predecessor_publication_id"], first["publication"]["id"])

    def test_sql_rejects_bypassed_duplicate_attention_admission(self):
        self.publish()
        self.capture_item(native="report-2", title="Another report repeating the same evidence")
        original = publication.decide_attention
        def bypass(*args, **kwargs):
            decision = original(*args, **kwargs)
            decision["status"] = "review_requested"
            return decision
        with patch.object(publication, "decide_attention", side_effect=bypass), self.assertRaises(DatabaseError):
            self.publish()
        self.assertEqual(NewsPublication.objects.count(), 1)
        self.assertEqual(NotificationIntent.objects.filter(state="pending").count(), 1)

    def test_shared_fanout_capacity_checks_daily_and_news_together(self):
        from macro_agent.desk import publication as daily_publication, service as daily
        from .test_cumulative_analysis import LIMITS
        saved = self.publish(fanout_limit=1)
        cutoff = timezone.now()
        from datetime import timedelta
        review = daily.create_review(self.actor, self.thesis["id"], str(uuid4()), cutoff-timedelta(days=1),
            cutoff, (recorded.SOURCE, cumulative.BACKGROUND), LIMITS)["review"]
        with self.assertRaises(ReviewCapacityExceeded):
            daily_publication.publish_review(self.actor, review["id"], str(uuid4()), review["digest"], 0, 1)
        self.assertEqual(NewsPublication.objects.count(), 1)
        self.assertEqual(CurrentAssessment.objects.count(), 1)
        self.assertEqual(NotificationIntent.objects.get().state, "pending")

    def test_sql_guards_history_pointer_delivery_and_governing_bypasses(self):
        saved = self.publish()
        row = NewsPublication.objects.get()
        for operation in (
            lambda: NewsPublication.objects.filter(pk=row.pk).update(attention_decision={}),
            lambda: NewsBrief.objects.all().update(fanout_limit=11),
            lambda: NotificationIntent.objects.all().update(state="delivered"),
            lambda: CurrentAssessment.objects.all().delete(),
            lambda: SourceState.objects.filter(pk=recorded.SOURCE).update(contract_digest="0"*64),
        ):
            with self.subTest(operation=operation), self.assertRaises(DatabaseError), transaction.atomic():
                operation()
        self.assertEqual(saved["publication"]["original_decision"]["status"], "current")

    def test_source_first_publication_blocks_correction_until_atomic_publication_then_cancels(self):
        output = self.analysed()
        ready, release, correcting_ready = Event(), Event(), Event()
        pids = {}
        def protected_clock():
            ready.set()
            if not release.wait(10):
                raise RuntimeError("Recorded publication release timed out")
            return timezone.now()
        def publishing():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids["publication"] = cursor.fetchone()[0]
                return self.publish(output, clock=protected_clock)
            finally:
                connections.close_all()
        def correcting():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids["correction"] = cursor.fetchone()[0]
                correcting_ready.set()
                return self.background("Concurrent correction after publication protection")
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(publishing)
            self.assertTrue(ready.wait(5))
            correction = pool.submit(correcting)
            try:
                self.assertTrue(correcting_ready.wait(5))
                self.server_lock_wait(pids["correction"], pids["publication"], "macro_monitoring_sourcestate")
            finally:
                release.set()
            saved = pending.result(timeout=15)
            correction.result(timeout=15)
        self.assertEqual(saved["publication"]["original_decision"]["status"], "current")
        self.assert_canceled(saved)

    def test_correction_first_orders_publication_on_actual_source_wait_and_prevents_backdating(self):
        from macro_agent.monitoring import capture
        output = self.analysed()
        correcting_ready, release, publishing_ready = Event(), Event(), Event()
        pids, samples = {}, []
        calls = 0
        def correction_clock():
            nonlocal calls
            calls += 1
            # Capture admission is already committed. Pause only when receipt
            # completion holds the source and complete publication dependents.
            if calls == 2:
                correcting_ready.set()
                if not release.wait(10):
                    raise RuntimeError("Recorded source release timed out")
            return timezone.now()
        def correcting():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids["correction"] = cursor.fetchone()[0]
                return capture.capture(cumulative.BACKGROUND, cumulative.BACKGROUND_CONTRACT,
                    lambda: self.batch(self.item("background-1", "Correction commits before publication")),
                    clock=correction_clock)
            finally:
                connections.close_all()
        def publishing():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids["publication"] = cursor.fetchone()[0]
                publishing_ready.set()
                return self.publish(output, clock=lambda: (samples.append(timezone.now()) or samples[-1]))
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            correction = pool.submit(correcting)
            self.assertTrue(correcting_ready.wait(5))
            pending = pool.submit(publishing)
            try:
                self.assertTrue(publishing_ready.wait(5))
                self.server_lock_wait(pids["publication"], pids["correction"], "macro_monitoring_sourcestate")
                self.assertEqual(samples, [])
            finally:
                release.set()
            correction.result(timeout=15)
            saved = pending.result(timeout=15)
        self.assertEqual(saved["publication"]["original_decision"]["status"], "superseded")
        self.assertIsNone(saved["notification_intent"])
        self.assertEqual(len(samples), 1)

    def test_unmapped_unlinked_and_unchanged_recommendations_do_not_invent_attention_authority(self):
        output = self.analysed()
        content = {"document": deepcopy(output["document"])}
        value = content["document"]["driver_assessment"]
        value["attention"]["driver_indices"] = []
        self.assertEqual(decide_attention(content)["status"], "unmapped")
        value["attention"]["driver_indices"] = [0]
        value["approved_drivers"][0]["premise"]["claim_ids"] = []
        value["approved_drivers"][0]["mechanism"]["claim_ids"] = []
        self.assertEqual(decide_attention(content)["status"], "unlinked")
        content["document"] = deepcopy(output["document"])
        self.assertEqual(decide_attention(content, previous_document=output["document"])["status"], "unchanged")
        content["document"]["driver_assessment"]["attention"]["status"] = "not_identified"
        self.assertEqual(decide_attention(content)["status"], "not_requested")
