"""Complete admission-time evidence without a scheduled daily-review boundary."""

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import F
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.desk import analysis_context, service
from macro_agent.desk.models import (
    ContextExposure, DailyReview, EvidenceAnalysis, EvidenceRevision, EvidenceSet,
    PrivateContext, SourceContractHead, SourceContractVersion,
)
from macro_agent.domain.cumulative_news import cumulative_digest, validate_cumulative_context
from macro_agent.domain.daily_review import ReviewCapacityExceeded
from macro_agent.monitoring import analysis, capture, news_context
from macro_agent.monitoring.models import NewsAnalysisAttempt, SourceRevision
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.persistence.context_binding import _at, _resolved, lock_owner_thesis
from macro_agent.positions import service as positions
from macro_agent.theses import service as theses

from . import test_service as daily


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class AnalysisContextPersistenceTests(TransactionTestCase):
    setUp = daily.DailyReviewPersistenceTests.setUp
    capture = daily.DailyReviewPersistenceTests.capture
    analyse = daily.DailyReviewPersistenceTests.analyse
    review = daily.DailyReviewPersistenceTests.review

    def focus(self, native="report-1"):
        return SourceRevision.objects.select_related("report").get(report__native_id=native)

    def build(self, *, persist=False, focus=None, limits=daily.LIMITS, at=None, actor=None):
        with transaction.atomic():
            sources = service._lock_sources([daily.SOURCE])
            thesis = lock_owner_thesis(self.actor, self.thesis["id"], "default")
            approval, resolved, exposure = _resolved(thesis, str(thesis.current_approval_id), "default")
            observed = _at(lambda: at or timezone.now(), thesis, resolved=resolved)
            return analysis_context.build_analysis_context(actor or self.actor, thesis, approval,
                resolved, exposure, sources, focus or self.focus(), limits, observed, persist=persist)

    def test_preflight_does_not_create_permission_context_or_evidence_rows(self):
        context, envelope = self.build()
        self.assertIsNone(context)
        self.assertEqual(envelope["digest"], cumulative_digest(envelope))
        self.assertEqual([item["revision_id"] for item in envelope["reports"]], [str(self.focus().pk)])
        self.assertEqual(envelope["reports"][0]["source_contract_provenance"],
                         "existing_allowlisted_adapter_manifest")
        self.assertFalse(SourceContractHead.objects.exists())
        self.assertFalse(SourceContractVersion.objects.exists())
        self.assertFalse(PrivateContext.objects.exists())
        self.assertFalse(EvidenceSet.objects.exists())
        validate_cumulative_context(envelope, envelope["reports"][0])

    def test_admission_pins_complete_intraday_evidence_without_daily_review(self):
        first_result = self.analyse()
        service.observe_analysis_results(self.actor, self.thesis["id"], [daily.SOURCE], 100)
        first, first_envelope = self.build(persist=True)
        self.capture("report-2", "Second intraday report")
        second_result = self.analyse()
        service.observe_analysis_results(self.actor, self.thesis["id"], [daily.SOURCE], 100)
        self.capture("report-3", "Third intraday report")
        second, envelope = self.build(persist=True, focus=self.focus("report-3"))
        self.assertEqual(second.predecessor_id, first.pk)
        self.assertEqual(envelope["predecessor_context_id"], str(first.pk))
        self.assertEqual(second.evidence.start, first.evidence.cutoff)
        self.assertEqual(len(envelope["reports"]), 3)
        self.assertEqual({item["section"] for item in envelope["reports"]}, {"new", "background"})
        self.assertEqual({item["analysis_id"] for item in envelope["analyses"]},
                         {first_result["analysis"]["id"], second_result["analysis"]["id"]})
        self.assertTrue(all("original_context" not in item for item in envelope["analyses"]))
        self.assertEqual(second.evidence.revisions.count(), 3)
        self.assertEqual(second.evidence.analyses.count(), 2)
        self.assertEqual(second.resolved_inputs["cumulative"], envelope)
        self.assertEqual(first.resolved_inputs["cumulative"], first_envelope)
        self.assertFalse(DailyReview.objects.exists())
        validate_cumulative_context(envelope, next(item for item in envelope["reports"]
            if item["revision_id"] == str(self.focus("report-3").pk)))

    def test_missing_report_and_analysis_witnesses_are_explicitly_deferred(self):
        result = self.analyse()
        with self.assertRaises(RuntimeError):
            self.capture("report-2", after_commit=lambda: (_ for _ in ()).throw(RuntimeError("crash")))
        _, envelope = self.build()
        self.assertEqual(envelope["deferred_reports"], [{"revision_id": str(self.focus("report-2").pk),
            "reason": "availability_unproven"}])
        self.assertEqual(envelope["deferred_analyses"], [{"analysis_id": result["analysis"]["id"],
            "reason": "availability_unproven"}])
        self.assertEqual(envelope["analyses"], [])
        self.assertNotIn(str(self.focus("report-2").pk), {item["revision_id"] for item in envelope["reports"]})

    def test_focus_without_conservative_witness_rejects_and_rolls_back_admission(self):
        with self.assertRaises(RuntimeError):
            self.capture("report-2", after_commit=lambda: (_ for _ in ()).throw(RuntimeError("crash")))
        with self.assertRaisesMessage(theses.ThesisConflict, "eligible conservative"):
            self.build(persist=True, focus=self.focus("report-2"))
        self.assertFalse(SourceContractHead.objects.exists())
        self.assertFalse(SourceContractVersion.objects.exists())
        self.assertFalse(PrivateContext.objects.exists())

    def test_private_scope_is_rejected_before_any_context_write(self):
        with self.assertRaises(theses.ThesisUnavailable):
            self.build(persist=True, actor=str(self.other.pk))
        self.assertFalse(PrivateContext.objects.exists())
        self.assertFalse(SourceContractVersion.objects.exists())

    def test_complete_book_is_pinned_and_not_silently_truncated(self):
        first = positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
            self.thesis["approved"]["approval"]["id"], daily.DECLARATION)["position"]
        second = positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
            self.thesis["approved"]["approval"]["id"], {**daily.DECLARATION, "direction": "short"})["position"]
        with self.assertRaises(ReviewCapacityExceeded):
            self.build(persist=True, limits=replace(daily.LIMITS, exposure_versions=1))
        self.assertFalse(PrivateContext.objects.exists())
        context, _ = self.build(persist=True)
        self.assertEqual(set(ContextExposure.objects.filter(context=context).values_list("version_id", flat=True)),
            {UUID(first["current_version"]["id"]), UUID(second["current_version"]["id"])})
        self.assertEqual(len(context.resolved_inputs["approved_user"]["exposure"]["positions"]), 2)

    def test_record_and_encoding_overflow_make_no_partial_context(self):
        self.capture("report-2")
        for limits in (replace(daily.LIMITS, reports=1), replace(daily.LIMITS, encoded_bytes=100)):
            with self.subTest(limits=limits), self.assertRaises(ReviewCapacityExceeded):
                self.build(persist=True, limits=limits)
            self.assertFalse(PrivateContext.objects.exists())
            self.assertFalse(EvidenceRevision.objects.exists())
            self.assertFalse(EvidenceAnalysis.objects.exists())
            self.assertFalse(SourceContractVersion.objects.exists())

    def test_lineage_falls_back_to_daily_then_rejects_equal_or_future_cutoffs(self):
        reviewed = self.review()
        context, envelope = self.build(persist=True)
        self.assertEqual(str(context.predecessor_id), reviewed["review"]["context_id"])
        self.assertEqual(envelope["predecessor_context_id"], reviewed["review"]["context_id"])
        for at in (context.evidence.cutoff, context.evidence.cutoff - timedelta(microseconds=1)):
            with self.subTest(at=at), self.assertRaises(theses.ThesisConflict):
                self.build(persist=True, at=at)
        self.assertEqual(PrivateContext.objects.count(), 2)

    def test_backdated_admission_cannot_precede_late_daily_preparation(self):
        self.review(cutoff=timezone.now() - timedelta(hours=1))
        previous = DailyReview.objects.get().context
        self.assertLess(previous.evidence.cutoff, previous.prepared_at)
        with self.assertRaises(theses.ThesisConflict):
            self.build(at=previous.prepared_at)
        self.assertEqual(PrivateContext.objects.count(), 1)

    def test_interleaved_daily_and_cumulative_contexts_continue_latest_cutoff(self):
        first_daily = self.review()
        first_context, _ = self.build(persist=True)
        self.assertEqual(str(first_context.predecessor_id), first_daily["review"]["context_id"])
        self.capture("report-2", "Between cumulative context and later daily review")
        second_daily = self.review(start=datetime.fromisoformat(first_daily["review"]["cutoff"]))
        self.capture("report-3", "After later daily review")
        second_context, envelope = self.build(persist=True, focus=self.focus("report-3"))
        self.assertEqual(str(second_context.predecessor_id), second_daily["review"]["context_id"])
        self.assertEqual(second_context.evidence.start.isoformat(), second_daily["review"]["cutoff"])
        sections = {item["revision_id"]: item["section"] for item in envelope["reports"]}
        self.assertEqual(sections[str(self.focus("report-2").pk)], "background")
        self.assertEqual(sections[str(self.focus("report-3").pk)], "new")

    def test_superseded_report_remains_visible_with_explicit_current_head(self):
        old = self.focus()
        self.capture(title="A corrected headline")
        focus = SourceRevision.objects.select_related("report").get(report__native_id="report-1",
            report__current_revision_id=F("pk"))
        _, envelope = self.build(focus=focus)
        historical = next(item for item in envelope["reports"] if item["revision_id"] == str(old.pk))
        self.assertFalse(historical["is_current_revision"])
        self.assertEqual(historical["head_at_preparation_id"], str(focus.pk))
        self.assertTrue(any("historical_source_revision" in item for item in envelope["gaps"]))

    def test_prior_cumulative_analysis_requires_its_complete_governing_source_manifest(self):
        second_source = "fixture-other-governing-source"
        item = SourceItem("other-report", "Other retained context", "https://example.invalid/other",
            timezone.now() - timedelta(days=1), "A separate fictional report.")
        capture.capture(second_source, daily.CONTRACT, lambda: SourceBatch((item,), timezone.now(),
            "bounded_snapshot", False, "a" * 64))
        context = news_context.review_context(self.actor, self.thesis["id"])
        analysis.analyse_next(self.actor, self.thesis["id"], str(uuid4()), context["approval_id"],
            context["exposure_digest"], daily.SOURCE, daily.MODEL, "nanogpt", provider=self.provider,
            context_source_ids=[daily.SOURCE, second_source], context_limits=daily.LIMITS)
        self.assertIsNotNone(NewsAnalysisAttempt.objects.get().admission_context_id)
        with self.assertRaisesMessage(theses.ThesisConflict, "Complete governing source manifest"):
            self.build()
        self.assertEqual(PrivateContext.objects.count(), 1)
        self.assertEqual(self.provider.calls, 1)
