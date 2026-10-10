"""PostgreSQL evidence cutoffs, correction ordering and private restart recovery."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from threading import Event
from time import monotonic
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.domain.daily_review import DailyReviewLimits
from macro_agent.monitoring import analysis, capture, news_context
from macro_agent.monitoring.models import DurableObservation, NewsAnalysisResult, SourceRevision, SourceState
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.monitoring.tests.test_analysis import (
    CONTRACT, DECLARATION, EXACT, MEANING, MODEL, QUOTE, SOURCE, RecordedProvider,
)
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.positions import service as positions
from macro_agent.theses import service as theses
from macro_agent.desk import permissions, service
from macro_agent.desk.models import (
    AnalysisResultObservation, ContextExposure, DailyReview, EvidenceAnalysis, EvidenceRevision,
    EvidenceSet, PrivateContext, SourceContractHead, SourceContractVersion,
)


LIMITS = DailyReviewLimits(reports=100, analyses=100, exposure_versions=200,
                          issues=300, source_contracts=16, encoded_bytes=2_000_000)


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class DailyReviewPersistenceTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="daily-owner")
        self.staff = get_user_model().objects.create_user(username="daily-staff", is_staff=True)
        self.other = get_user_model().objects.create_user(username="daily-other")
        self.actor = str(self.owner.pk)
        draft = theses.create_thesis(self.actor, str(uuid4()), EXACT, MEANING)["thesis"]
        text, meaning = draft["draft"]["text_version"], draft["draft"]["interpretation"]
        self.thesis = theses.approve_thesis(self.actor, draft["id"], str(uuid4()),
            text["id"], text["text_digest"], meaning["id"], meaning["digest"], draft["revision"])["thesis"]
        self.provider = RecordedProvider()
        self.capture()

    def capture(self, native="report-1", title="Policy report", **kwargs):
        item = SourceItem(native, title, "https://example.invalid/retained-report",
                          timezone.now() - timedelta(days=1), "  " + QUOTE + "\r\nΔ\r\n")
        return capture.capture(SOURCE, CONTRACT, lambda: SourceBatch((item,), timezone.now(),
            "bounded_snapshot", False, sha256(b"daily transport").hexdigest()), **kwargs)

    def analyse(self):
        context = news_context.review_context(self.actor, self.thesis["id"])
        return analysis.analyse_next(self.actor, self.thesis["id"], str(uuid4()),
            context["approval_id"], context["exposure_digest"], SOURCE, MODEL, "nanogpt", provider=self.provider)

    def review(self, command=None, start=None, cutoff=None, **kwargs):
        cutoff = cutoff or timezone.now()
        return service.create_review(self.actor, self.thesis["id"], command or str(uuid4()),
            start or cutoff - timedelta(days=1), cutoff, [SOURCE], LIMITS, **kwargs)

    def test_review_retains_exact_context_and_recovery_has_no_publication_authority(self):
        command, cutoff = str(uuid4()), timezone.now()
        first = self.review(command, cutoff=cutoff)
        recovered = self.review(command, cutoff=cutoff)
        self.assertEqual(first["review"], recovered["review"])
        self.assertTrue(recovered["replayed"])
        self.assertEqual(first["review"]["original_inputs"]["approved_user"]["text"]["exact_text"], EXACT)
        snapshot = first["review"]["original_inputs"]["source_contracts"][0]
        self.assertEqual(snapshot["contract"], CONTRACT)
        self.assertEqual(snapshot["provenance"], "existing_allowlisted_adapter_manifest")
        self.assertEqual(first["review"]["evidence_set"]["limits"]["reports"], LIMITS.reports)
        self.assertEqual(first["review"]["content"]["new_eligible_report_count"], 1)
        self.assertEqual(first["review"]["content"]["assembly_inference_calls"], 0)
        self.assertFalse(first["current_disposition"]["publication_authority"])
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertEqual((DailyReview.objects.count(), PrivateContext.objects.count(), EvidenceSet.objects.count()), (1, 1, 1))
        self.assertEqual(EvidenceRevision.objects.count(), 1)

    def test_missing_capture_witness_defers_then_postcommit_recovery_is_not_backdated(self):
        with self.assertRaises(RuntimeError):
            self.capture("report-2", after_commit=lambda: (_ for _ in ()).throw(RuntimeError("crash")))
        cutoff = timezone.now()
        first = self.review(cutoff=cutoff)
        self.assertEqual(len(first["review"]["content"]["reports"]["deferred"]), 1)
        revision = SourceRevision.objects.get(report__native_id="report-2")
        self.assertFalse(DurableObservation.objects.filter(revision=revision).exists())
        capture.observe_capture(revision.capture_id)
        self.assertGreater(DurableObservation.objects.get(revision=revision).observed_by_at, cutoff)
        later = self.review(start=cutoff)
        new = later["review"]["content"]["reports"]["new"]
        self.assertEqual([item["revision_id"] for item in new], [str(revision.pk)])
        self.assertEqual(later["review"]["predecessor_id"], first["review"]["context_id"])

    def test_late_analysis_of_background_report_enters_new_interval_by_its_own_witness(self):
        cutoff = timezone.now()
        first = self.review(cutoff=cutoff)
        result = self.analyse()
        self.assertFalse(AnalysisResultObservation.objects.exists())
        service.observe_analysis_results(self.actor, self.thesis["id"], [SOURCE], 100)
        second = self.review(start=cutoff)
        content = second["review"]["content"]
        self.assertEqual(len(content["reports"]["background"]), 1)
        self.assertEqual(len(content["reports"]["new"]), 0)
        self.assertEqual([item["analysis_id"] for item in content["analyses"]["new"]], [result["analysis"]["id"]])
        self.assertEqual(content["analyses"]["new"][0]["original_status"], "analysed")
        self.assertEqual(content["unknown_reported_cost_analysis_ids"], [result["analysis"]["id"]])
        self.assertEqual(EvidenceAnalysis.objects.count(), 1)

    def test_missing_analysis_witness_is_deferred_even_if_result_finished_before_cutoff(self):
        result = self.analyse()
        cutoff = timezone.now()
        review = self.review(cutoff=cutoff)
        deferred = review["review"]["content"]["analyses"]["deferred"]
        self.assertEqual(deferred[0]["analysis_id"], result["analysis"]["id"])
        self.assertEqual(deferred[0]["deferred_reason"], "availability_unproven")
        service.observe_analysis_results(self.actor, self.thesis["id"], [SOURCE], 100)
        self.assertGreater(AnalysisResultObservation.objects.get().observed_by_at, cutoff)
        original = service.inspect_review(self.actor, review["review"]["id"])
        self.assertEqual(original["review"], review["review"])

    def test_result_witness_recovery_preserves_first_observation_and_does_not_repeat_inference(self):
        result = self.analyse()
        first = service.observe_analysis_results(self.actor, self.thesis["id"], [SOURCE], 100)
        witness = AnalysisResultObservation.objects.get()
        second = service.observe_analysis_results(self.actor, self.thesis["id"], [SOURCE], 100)
        self.assertEqual(first["observed_analysis_ids"], [result["analysis"]["id"]])
        self.assertEqual(second["observed_analysis_ids"], [])
        self.assertEqual(AnalysisResultObservation.objects.get().observed_by_at, witness.observed_by_at)
        self.assertEqual(self.provider.calls, 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnalysisResultObservation.objects.update(observed_by_at=timezone.now())

    def test_original_success_is_labelled_stale_at_preparation_after_source_correction(self):
        self.analyse()
        service.observe_analysis_results(self.actor, self.thesis["id"], [SOURCE], 100)
        self.capture(title="Correction before daily preparation")
        review = self.review()
        item = review["review"]["content"]["analyses"]["new"][0]
        self.assertEqual(item["original_status"], "analysed")
        self.assertEqual(item["original_stale_reasons"], [])
        self.assertEqual(item["current_disposition"], "stale")
        self.assertIn("observed_source_revision_changed", item["current_stale_reasons"])
        self.assertEqual(NewsAnalysisResult.objects.get().status, "analysed")
        self.assertEqual(review["current_disposition"]["status"], "prepared")

    def test_complete_exposure_and_approved_meaning_are_pinned_and_present_changes_stale_only(self):
        position = positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
            self.thesis["approved"]["approval"]["id"], DECLARATION)["position"]
        first = self.review()
        original = first["review"]["original_inputs"]["approved_user"]
        self.assertEqual(len(original["exposure"]["positions"]), 1)
        self.assertEqual(str(ContextExposure.objects.get().version_id), position["current_version"]["id"])
        self.assertEqual(first["review"]["content"]["scope"]["exposure_version_ids"],
                         [position["current_version"]["id"]])
        positions.revise_position(self.actor, position["id"], str(uuid4()), position["revision"],
            self.thesis["approved"]["approval"]["id"], {**DECLARATION, "direction": "short"})
        self.assertEqual(str(ContextExposure.objects.get().version_id), position["current_version"]["id"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            ContextExposure.objects.update(version_id=positions.get_position(self.actor, position["id"])["current_version"]["id"])
        inspected = service.inspect_review(self.actor, first["review"]["id"])
        self.assertEqual(inspected["review"], first["review"])
        self.assertIn("paper_exposure_changed", inspected["current_disposition"]["stale_reasons"])
        proposed = theses.propose_thesis(self.actor, self.thesis["id"], str(uuid4()),
            EXACT + "Reviewed change", MEANING, self.thesis["revision"])["thesis"]
        text, meaning = proposed["draft"]["text_version"], proposed["draft"]["interpretation"]
        theses.approve_thesis(self.actor, self.thesis["id"], str(uuid4()), text["id"], text["text_digest"],
            meaning["id"], meaning["digest"], proposed["revision"])
        inspected = service.inspect_review(self.actor, first["review"]["id"])
        self.assertIn("approved_meaning_changed", inspected["current_disposition"]["stale_reasons"])
        later = self.review(start=DailyReview.objects.get().cutoff)
        self.assertEqual(later["review"]["original_inputs"]["changes_since_predecessor"],
                         {"approved_meaning_changed": True, "exposure_changed": True})
        self.assertEqual(later["current_disposition"]["status"], "prepared")

    def test_present_observation_cannot_be_backdated_before_review_or_changed_input(self):
        first = self.review()
        row = DailyReview.objects.get()
        with self.assertRaises(theses.ThesisConflict):
            service.inspect_review(self.actor, first["review"]["id"],
                                   clock=lambda: row.prepared_at-timedelta(microseconds=1))
        self.capture(title="Later correction")
        with self.assertRaises(theses.ThesisConflict):
            service.inspect_review(self.actor, first["review"]["id"], clock=lambda: row.prepared_at)

    def test_database_rejects_exposure_not_present_in_original_private_context(self):
        first = self.review()
        later = positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
            self.thesis["approved"]["approval"]["id"], DECLARATION)["position"]
        with self.assertRaises(IntegrityError), transaction.atomic():
            ContextExposure.objects.create(context_id=first["review"]["context_id"],
                position_id=later["id"], version_id=later["current_version"]["id"])
        self.assertFalse(ContextExposure.objects.exists())

    def test_correction_after_review_changes_present_disposition_only(self):
        first = self.review()
        self.capture(title="Corrected report")
        inspected = service.inspect_review(self.actor, first["review"]["id"])
        self.assertEqual(inspected["review"], first["review"])
        self.assertEqual(inspected["current_disposition"]["status"], "stale")
        self.assertTrue(any(reason.startswith("included_report_corrected") for reason in inspected["current_disposition"]["stale_reasons"]))
        next_review = self.review(start=DailyReview.objects.get().cutoff)
        self.assertEqual(next_review["current_disposition"]["status"], "prepared")
        self.assertEqual(len(next_review["review"]["content"]["reports"]["background"]), 1)
        self.assertEqual(len(next_review["review"]["content"]["reports"]["new"]), 1)

    def test_later_distinct_report_does_not_mark_prior_cutoff_stale(self):
        first = self.review()
        self.capture("report-2", "A later unrelated report")
        inspected = service.inspect_review(self.actor, first["review"]["id"])
        self.assertEqual(inspected["current_disposition"]["status"], "prepared")

    def test_withdrawal_is_versioned_and_historical_retry_never_reactivates_old_permission(self):
        command, cutoff = str(uuid4()), timezone.now()
        first = self.review(command, cutoff=cutoff)
        old_version = SourceContractHead.objects.get().version_id
        source = SourceState.objects.get(pk=SOURCE)
        denied = permissions.set_source_permission(str(self.staff.pk), SOURCE, source.contract_digest,
                                                   False, "Internal review withdrawal")
        self.assertFalse(permissions.permission_allows(SOURCE))
        retry = self.review(command, cutoff=cutoff)
        self.assertEqual(retry["review"], first["review"])
        self.assertEqual(retry["current_disposition"]["status"], "stale")
        with self.assertRaises(theses.ThesisConflict):
            self.review(start=cutoff)
        self.assertEqual(str(SourceContractHead.objects.get().version_id), denied["version_id"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            SourceContractHead.objects.update(version_id=old_version)
        renewed = permissions.set_source_permission(str(self.staff.pk), SOURCE, source.contract_digest,
                                                     True, "Fresh fixed-adapter permission review")
        self.assertNotEqual(renewed["version_id"], str(old_version))
        self.assertTrue(permissions.permission_allows(SOURCE))
        self.assertEqual(service.inspect_review(self.actor, first["review"]["id"])["current_disposition"]["status"], "stale")

    def test_withdrawal_survives_disabled_desk_and_cannot_restore_an_unavailable_adapter(self):
        self.review()
        digest = SourceState.objects.get(pk=SOURCE).contract_digest
        permissions.set_source_permission(str(self.staff.pk), SOURCE, digest, False, "Withdraw fixture processing")
        with override_settings(MACRO_ENABLE_CONTINUOUS_DESK=False, SETTINGS_MODULE="macro_agent.web.local_settings"):
            self.assertFalse(permissions.permission_allows(SOURCE))
            with self.assertRaises(PermissionError):
                self.capture("report-2")
            with self.assertRaises(service.DeskDisabled):
                service.get_review_command(self.actor, self.thesis["id"], str(DailyReview.objects.get().command_id))
        with override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=False,
                               SETTINGS_MODULE="macro_agent.web.local_settings"), self.assertRaises(theses.ThesisConflict):
            permissions.set_source_permission(str(self.staff.pk), SOURCE, digest, True, "Attempt unsupported restoration")
        self.assertFalse(permissions.permission_allows(SOURCE))
        self.assertEqual(SourceContractVersion.objects.count(), 2)

    def test_overflow_rejects_atomically_and_does_not_discard_exposure_or_reports(self):
        self.capture("report-2")
        with self.assertRaises(ValueError):
            service.create_review(self.actor, self.thesis["id"], str(uuid4()), timezone.now()-timedelta(days=1),
                timezone.now(), [SOURCE], replace(LIMITS, reports=1))
        self.assertFalse(DailyReview.objects.exists())
        self.assertFalse(EvidenceSet.objects.exists())
        self.assertFalse(SourceContractVersion.objects.exists())
        with self.assertRaises(ValueError):
            service.create_review(self.actor, self.thesis["id"], str(uuid4()), timezone.now()-timedelta(days=1),
                timezone.now(), [SOURCE], replace(LIMITS, encoded_bytes=10))
        self.assertFalse(DailyReview.objects.exists())

    def test_owned_inspection_rejects_foreign_owner_and_immutable_history_changes(self):
        review = self.review()
        with self.assertRaises(theses.ThesisUnavailable):
            service.inspect_review(str(self.other.pk), review["review"]["id"])
        for model in (DailyReview, PrivateContext, EvidenceSet, SourceContractVersion):
            with self.subTest(model=model), self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.all().delete()
        with self.assertRaises(theses.ThesisUnavailable):
            permissions.set_source_permission(self.actor, SOURCE, SourceState.objects.get().contract_digest,
                                               False, "Not authorized")

    def test_rejects_caller_transactions_and_out_of_order_missed_intervals(self):
        with transaction.atomic(), self.assertNumQueries(0), self.assertRaises(RuntimeError):
            self.review()
        connection.set_autocommit(False)
        try:
            with self.assertNumQueries(0), self.assertRaises(RuntimeError):
                self.review()
        finally:
            connection.rollback()
            connection.set_autocommit(True)
        first = self.review()
        with self.assertRaises(theses.ThesisConflict):
            self.review(cutoff=DailyReview.objects.get().cutoff-timedelta(hours=1))
        self.assertEqual(DailyReview.objects.count(), 1)

    def test_clock_is_sampled_only_after_independent_source_lock_is_acquired(self):
        entered, release, started = Event(), Event(), Event()
        def holder():
            close_old_connections()
            try:
                with transaction.atomic():
                    SourceState.objects.select_for_update().get(pk=SOURCE)
                    entered.set()
                    release.wait(timeout=3)
            finally:
                close_old_connections()
        sampled = []
        def assemble():
            close_old_connections()
            try:
                started.set()
                return self.review(clock=lambda: (sampled.append(monotonic()) or timezone.now()))
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            locked = pool.submit(holder)
            self.assertTrue(entered.wait(timeout=2))
            future = pool.submit(assemble)
            self.assertTrue(started.wait(timeout=2))
            self.assertFalse(sampled)
            release.set()
            result = future.result(timeout=5)
            locked.result(timeout=5)
        self.assertTrue(sampled)
        self.assertEqual(result["current_disposition"]["status"], "prepared")

    def test_duplicate_commands_on_independent_connections_create_one_immutable_pack(self):
        command, cutoff = str(uuid4()), timezone.now()
        entered, release, second_started = Event(), Event(), Event()
        def first_clock():
            entered.set()
            if not release.wait(timeout=3):
                raise AssertionError("Duplicate review race was not released")
            return timezone.now()
        def run(clock, started=None):
            close_old_connections()
            try:
                if started is not None:
                    started.set()
                return self.review(command, cutoff=cutoff, clock=clock)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run, first_clock)
            self.assertTrue(entered.wait(timeout=2))
            second = pool.submit(run, timezone.now, second_started)
            self.assertTrue(second_started.wait(timeout=2))
            release.set()
            a, b = first.result(timeout=5), second.result(timeout=5)
        self.assertEqual(a["review"], b["review"])
        self.assertFalse(a["replayed"])
        self.assertTrue(b["replayed"])
        self.assertEqual((DailyReview.objects.count(), PrivateContext.objects.count(), EvidenceSet.objects.count()), (1, 1, 1))

    def test_permission_withdrawal_first_blocks_waiting_review_after_source_protection(self):
        entered, release, started = Event(), Event(), Event()
        source = SourceState.objects.get(pk=SOURCE)
        def deny_clock():
            entered.set()
            if not release.wait(timeout=3):
                raise AssertionError("Permission race was not released")
            return timezone.now()
        def withdraw():
            close_old_connections()
            try:
                return permissions.set_source_permission(str(self.staff.pk), SOURCE,
                    source.contract_digest, False, "Withdraw before review", clock=deny_clock)
            finally:
                close_old_connections()
        def review():
            close_old_connections()
            try:
                started.set()
                return self.review()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            denied = pool.submit(withdraw)
            self.assertTrue(entered.wait(timeout=2))
            pending = pool.submit(review)
            self.assertTrue(started.wait(timeout=2))
            release.set()
            denied.result(timeout=5)
            with self.assertRaises(theses.ThesisConflict):
                pending.result(timeout=5)
        self.assertFalse(DailyReview.objects.exists())
        self.assertFalse(PrivateContext.objects.exists())
        self.assertFalse(permissions.permission_allows(SOURCE))

    def test_review_first_preserves_original_then_waiting_withdrawal_marks_it_stale(self):
        entered, release, started = Event(), Event(), Event()
        source = SourceState.objects.get(pk=SOURCE)
        def review_clock():
            entered.set()
            if not release.wait(timeout=3):
                raise AssertionError("Review race was not released")
            return timezone.now()
        def review():
            close_old_connections()
            try:
                return self.review(clock=review_clock)
            finally:
                close_old_connections()
        def withdraw():
            close_old_connections()
            try:
                started.set()
                return permissions.set_source_permission(str(self.staff.pk), SOURCE,
                    source.contract_digest, False, "Withdraw after review")
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            prepared = pool.submit(review)
            self.assertTrue(entered.wait(timeout=2))
            pending = pool.submit(withdraw)
            self.assertTrue(started.wait(timeout=2))
            release.set()
            original = prepared.result(timeout=5)
            pending.result(timeout=5)
        inspected = service.inspect_review(self.actor, original["review"]["id"])
        self.assertEqual(original["current_disposition"]["status"], "prepared")
        self.assertEqual(inspected["review"], original["review"])
        self.assertEqual(inspected["current_disposition"]["status"], "stale")
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())

    def test_correction_first_is_visible_to_review_waiting_on_independent_source_lock(self):
        attempt = capture.admit_capture(SOURCE, CONTRACT)
        corrected = SourceItem("report-1", "Correction committed first", "https://example.invalid/correction",
                               timezone.now(), QUOTE)
        batch = SourceBatch((corrected,), timezone.now(), "bounded_snapshot", False, sha256(b"correction").hexdigest())
        entered, release, started = Event(), Event(), Event()
        sampled = []
        def correction_clock():
            entered.set()
            if not release.wait(timeout=3):
                raise AssertionError("Correction race was not released")
            return timezone.now()
        def correct():
            close_old_connections()
            try:
                return capture.commit_batch(attempt.pk, batch, clock=correction_clock)
            finally:
                close_old_connections()
        def review():
            close_old_connections()
            try:
                started.set()
                return self.review(clock=lambda: (sampled.append(monotonic()) or timezone.now()))
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            correction = pool.submit(correct)
            self.assertTrue(entered.wait(timeout=2))
            pending = pool.submit(review)
            self.assertTrue(started.wait(timeout=2))
            self.assertFalse(sampled)
            release.set()
            correction.result(timeout=5)
            original = pending.result(timeout=5)
        self.assertEqual(EvidenceRevision.objects.count(), 2)
        heads = set(EvidenceRevision.objects.values_list("head_at_preparation_id", flat=True))
        self.assertEqual(heads, {SourceRevision.objects.get(digest=corrected.digest).pk})
        self.assertEqual(len(original["review"]["content"]["reports"]["deferred"]), 1)
        self.assertEqual(original["current_disposition"]["status"], "prepared")

    def test_review_first_cannot_be_replaced_by_correction_waiting_on_source_lock(self):
        attempt = capture.admit_capture(SOURCE, CONTRACT)
        corrected = SourceItem("report-1", "Correction committed later", "https://example.invalid/correction",
                               timezone.now(), QUOTE)
        batch = SourceBatch((corrected,), timezone.now(), "bounded_snapshot", False, sha256(b"correction").hexdigest())
        entered, release, started = Event(), Event(), Event()
        def review_clock():
            entered.set()
            if not release.wait(timeout=3):
                raise AssertionError("Review race was not released")
            return timezone.now()
        def review():
            close_old_connections()
            try:
                return self.review(clock=review_clock)
            finally:
                close_old_connections()
        def correct():
            close_old_connections()
            try:
                started.set()
                return capture.commit_batch(attempt.pk, batch)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            prepared = pool.submit(review)
            self.assertTrue(entered.wait(timeout=2))
            pending = pool.submit(correct)
            self.assertTrue(started.wait(timeout=2))
            release.set()
            original = prepared.result(timeout=5)
            pending.result(timeout=5)
        self.assertEqual(EvidenceRevision.objects.count(), 1)
        inspected = service.inspect_review(self.actor, original["review"]["id"])
        self.assertEqual(inspected["review"], original["review"])
        self.assertEqual(original["current_disposition"]["status"], "prepared")
        self.assertEqual(inspected["current_disposition"]["status"], "stale")
