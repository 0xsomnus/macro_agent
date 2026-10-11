"""Database guards reject alternate daily authority and uncancelled changes."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.domain.daily_publication import DailyPublicationCandidate
from macro_agent.domain.models import canonical_json
from macro_agent.desk.models import DailyBrief, DailyPublication, DailyReview, SourceContractHead, SourceContractVersion
from macro_agent.desk.tests import test_service as baseline
from macro_agent.monitoring.models import SourceReport, SourceRevision
from macro_agent.persistence.models import (
    AssessmentRecord, BriefStateRecord, BriefVersion, CurrentAssessment,
    DependencyHead, DependencyVersion, NotificationIntent, ThesisBriefBinding,
)
from macro_agent.positions.models import PositionRecord
from macro_agent.theses.models import ApprovalRecord, ThesisRecord


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class DailyPublicationRecordTests(TransactionTestCase):
    capture = baseline.DailyReviewPersistenceTests.capture
    review = baseline.DailyReviewPersistenceTests.review

    def setUp(self):
        baseline.DailyReviewPersistenceTests.setUp(self)
        self.initial_review = DailyReview.objects.get(pk=self.review()["review"]["id"])

    def binding(self):
        now = timezone.now()
        brief = BriefStateRecord.objects.create(brief_id="daily:" + self.thesis["id"],
            owner=self.owner, generation=0, changed_at=now)
        return DailyBrief.objects.create(brief=brief, owner=self.owner,
            thesis_id=self.thesis["id"], fanout_limit=8, created_at=now)

    def admitted(self, *, binding=None, review=None, status="current", payload_changes=None):
        binding = binding or self.binding()
        review = review or self.initial_review
        candidate = DailyPublicationCandidate(str(uuid4()), self.actor, self.thesis["id"],
            binding.brief_id, str(review.pk), str(review.context_id), review.cutoff, review.digest,
            str(review.context.approval_id), review.context.exposure_digest,
            binding.brief.generation, canonical_json(review.content))
        at = timezone.now()
        payload = candidate.payload
        digest = candidate.digest
        if payload_changes is not None:
            import json
            from macro_agent.domain.models import text_digest
            value = json.loads(payload)
            value.update(payload_changes)
            payload, digest = canonical_json(value), text_digest(canonical_json(value))
        assessment = AssessmentRecord.objects.create(brief=binding.brief,
            assessment_id=candidate.assessment_id, digest=digest, payload=payload,
            status=status, reasons=["all_dependencies_current"] if status == "current" else ["test_superseded"],
            reassessment_required=False, observed_dependencies=[], saved_at=at)
        publication = DailyPublication.objects.create(command_id=candidate.command_id,
            owner=self.owner, thesis_id=self.thesis["id"], brief=binding.brief,
            review=review, assessment=assessment, request_digest=candidate.digest,
            expected_generation=candidate.expected_generation, published_at=at)
        return binding, publication, candidate

    def finish(self, binding, publication, candidate):
        brief = binding.brief
        brief.generation = publication.expected_generation + 1
        brief.changed_at = publication.published_at
        brief.save(update_fields=("generation", "changed_at"))
        CurrentAssessment.objects.update_or_create(brief=brief, defaults={"assessment": publication.assessment})
        BriefVersion.objects.create(brief=brief, assessment=publication.assessment,
            generation=brief.generation, saved_at=publication.published_at)
        NotificationIntent.objects.filter(brief=brief, state="pending").update(
            state="canceled", updated_at=publication.published_at)
        NotificationIntent.objects.create(intent_id=candidate.intent_id, brief=brief,
            assessment=publication.assessment, state="pending", created_at=publication.published_at,
            updated_at=publication.published_at)

    def published(self):
        with transaction.atomic():
            values = self.admitted()
            self.finish(*values)
        return values

    def test_shared_records_retain_original_receipt_and_create_no_dummy_roles(self):
        binding, publication, candidate = self.published()
        self.assertEqual(CurrentAssessment.objects.get().assessment_id, publication.assessment_id)
        self.assertEqual(NotificationIntent.objects.get().intent_id, candidate.intent_id)
        self.assertFalse(DependencyHead.objects.exists())
        self.assertEqual(BriefVersion.objects.get().generation, 1)
        self.assertEqual(publication.assessment.status, "current")

    def test_binding_and_publication_are_immutable_under_queryset_writes(self):
        binding, publication, _ = self.published()
        for mutation in (
            lambda: DailyBrief.objects.filter(pk=binding.pk).update(fanout_limit=9),
            lambda: DailyBrief.objects.filter(pk=binding.pk).delete(),
            lambda: DailyPublication.objects.filter(pk=publication.pk).update(request_digest="0" * 64),
            lambda: DailyPublication.objects.filter(pk=publication.pk).delete(),
        ):
            with self.subTest(mutation=mutation), self.assertRaises(IntegrityError), transaction.atomic():
                mutation()

    def test_daily_receipt_rejects_cross_owner_and_changed_exact_body(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.admitted(payload_changes={"owner_id": str(self.other.pk)})
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.admitted(payload_changes={"content": {"market": "nothing happened"}})

    def test_binding_cannot_share_a_factual_stream_in_either_direction(self):
        binding = self.binding()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ThesisBriefBinding.objects.create(brief=binding.brief, thesis_id=self.thesis["id"],
                owner=self.owner, status="pending", created_at=timezone.now())
        now = timezone.now()
        other = BriefStateRecord.objects.create(brief_id="factual", owner=self.owner,
                                                generation=0, changed_at=now)
        ThesisBriefBinding.objects.create(brief=other, thesis_id=self.thesis["id"],
            owner=self.owner, status="pending", created_at=now)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DailyBrief.objects.create(brief=other, thesis_id=self.thesis["id"],
                owner=self.owner, created_at=now, fanout_limit=8)

    def test_dummy_governing_heads_and_missing_fanout_bounds_are_rejected(self):
        binding = self.binding()
        version = DependencyVersion.objects.create(brief=binding.brief, role="model",
            version_id="unused", digest="0" * 64, known_at=timezone.now())
        with self.assertRaises(IntegrityError), transaction.atomic():
            DependencyHead.objects.create(brief=binding.brief, role="model", version=version)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DailyBrief.objects.filter(pk=binding.pk).update(fanout_limit=0)

    def test_superseded_receipt_cannot_install_pointer_version_or_notice(self):
        with transaction.atomic():
            binding, publication, candidate = self.admitted(status="superseded")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.finish(binding, publication, candidate)
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertEqual(DailyPublication.objects.count(), 1)

    def test_wrong_pointer_and_delivered_notice_have_no_authority(self):
        binding, publication, _ = self.published()
        with self.assertRaises(IntegrityError), transaction.atomic():
            NotificationIntent.objects.update(state="delivered", updated_at=timezone.now())
        with self.assertRaises(IntegrityError), transaction.atomic():
            CurrentAssessment.objects.filter(brief=binding.brief).delete()
        self.assertEqual(NotificationIntent.objects.get().state, "pending")
        self.assertEqual(CurrentAssessment.objects.get().assessment_id, publication.assessment_id)

    def test_direct_approval_head_change_rejects_uncancelled_daily_current_at_commit(self):
        self.published()
        thesis = ThesisRecord.objects.get(pk=self.thesis["id"])
        original = thesis.current_approval
        with self.assertRaises(IntegrityError), transaction.atomic():
            fresh = ApprovalRecord.objects.create(thesis=thesis, text_version=original.text_version,
                interpretation=original.interpretation, actor=self.owner, approved_at=timezone.now(),
                digest="a" * 64, revision=thesis.revision + 1)
            ThesisRecord.objects.filter(pk=thesis.pk).update(current_approval=fresh,
                revision=thesis.revision + 1, changed_at=fresh.approved_at)
        thesis.refresh_from_db()
        self.assertEqual(thesis.current_approval_id, original.pk)
        self.assertTrue(CurrentAssessment.objects.exists())

    def test_new_unrepresented_position_rejects_uncancelled_daily_current_at_commit(self):
        self.published()
        with self.assertRaises(IntegrityError), transaction.atomic():
            now = timezone.now()
            PositionRecord.objects.create(owner=self.owner, thesis_id=self.thesis["id"],
                original_approval_id=self.thesis["approved"]["approval"]["id"], created_at=now, changed_at=now)
        self.assertFalse(PositionRecord.objects.exists())
        self.assertTrue(CurrentAssessment.objects.exists())

    def test_direct_source_correction_requires_current_and_pending_invalidation_first(self):
        self.published()
        original = SourceRevision.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            changed = SourceRevision.objects.create(report=original.report, observation_revision=2,
                digest="c" * 64, payload={**original.payload, "title": "Corrected title"},
                source_claimed_published_at=original.source_claimed_published_at,
                system_received_at=timezone.now(), capture=original.capture)
            SourceReport.objects.filter(pk=original.report_id).update(current_revision=changed, revision_count=2)
        self.assertEqual(SourceReport.objects.get().current_revision_id, original.pk)
        self.assertEqual(NotificationIntent.objects.get().state, "pending")

    def test_direct_permission_withdrawal_requires_invalidation_first(self):
        self.published()
        head = SourceContractHead.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            version = SourceContractVersion.objects.create(source=head.source,
                contract=head.version.contract, digest=head.version.digest, permitted=False,
                provenance="explicit_staff_permission_review", reviewer=self.staff,
                reason="Test withdrawal", observed_at=timezone.now(), parent=head.version)
            SourceContractHead.objects.filter(pk=head.pk).update(version=version)
        self.assertEqual(SourceContractHead.objects.get().version_id, head.version_id)

    def test_receipt_does_not_allow_older_cutoff_after_current_pointer_was_cleared(self):
        binding, publication, candidate = self.published()
        with transaction.atomic():
            CurrentAssessment.objects.filter(brief=binding.brief).delete()
            NotificationIntent.objects.filter(brief=binding.brief).update(state="canceled", updated_at=timezone.now())
        with self.assertRaises(IntegrityError), transaction.atomic():
            # An immutable original receipt can be inspected but not reinstalled.
            CurrentAssessment.objects.create(brief=binding.brief, assessment=publication.assessment)

    def test_scoped_current_pointer_rejects_non_daily_assessment_without_receipt(self):
        binding = self.binding()
        assessment = AssessmentRecord.objects.create(brief=binding.brief, assessment_id="unsupported",
            digest="a" * 64, payload="{}", status="current", reasons=[],
            reassessment_required=False, observed_dependencies=[], saved_at=timezone.now())
        with self.assertRaises(IntegrityError), transaction.atomic():
            CurrentAssessment.objects.create(brief=binding.brief, assessment=assessment)

    def test_raw_position_writer_waits_for_protected_thesis_then_rejects_uncancelled_output(self):
        self.published()
        attempted = Event()
        backend = []

        def raw_writer():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_backend_pid()")
                        backend.append(cursor.fetchone()[0])
                    attempted.set()
                    now = timezone.now()
                    PositionRecord.objects.create(owner=self.owner, thesis_id=self.thesis["id"],
                        original_approval_id=self.thesis["approved"]["approval"]["id"],
                        created_at=now, changed_at=now)
            except IntegrityError:
                return "rejected"
            finally:
                close_old_connections()
            return "unexpectedly_committed"

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                ThesisRecord.objects.select_for_update().get(pk=self.thesis["id"])
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    blocker = cursor.fetchone()[0]
                future = pool.submit(raw_writer)
                self.assertTrue(attempted.wait(timeout=3))
                deadline = monotonic() + 3
                blocked = False
                while monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_blocking_pids(%s)", [backend[0]])
                        blocked = blocker in cursor.fetchone()[0]
                    if blocked:
                        break
                    sleep(0.01)
                self.assertTrue(blocked, "raw position writer did not wait on protected thesis")
            self.assertEqual(future.result(timeout=5), "rejected")
        self.assertFalse(PositionRecord.objects.exists())
        self.assertTrue(CurrentAssessment.objects.exists())
