"""Preapproval selected evidence, exact recovery and database scope guards."""

from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.desk import evidence, permissions
from macro_agent.desk.models import ResearchEvidenceContext, ResearchEvidenceMember
from macro_agent.monitoring import capture
from macro_agent.monitoring.models import SourceRevision, SourceState
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.theses import service


SOURCE = "fixture-research-compilation"
CONTRACT = {"kind": "fictional_fixture", "label": "Selected fictional research"}


class EvidenceFixtures:
    def setup_evidence(self):
        self.owner = get_user_model().objects.create_user(username="source-owner")
        self.other = get_user_model().objects.create_user(username="source-other")
        self.staff = get_user_model().objects.create_user(username="source-staff", is_staff=True)
        self.actor = str(self.owner.pk)
        self.thesis = service.create_thesis(self.actor, str(uuid4()),
            "  Gold may benefit if real yields fall.\r\nΔ\r\n",
            {"drivers": [], "horizon": None, "invalidation_signposts": []})["thesis"]
        self.capture_report()
        self.revision = SourceRevision.objects.get(report__source_id=SOURCE)

    def capture_report(self, title="Fictional policy rate report", native="research-1", **kwargs):
        item = SourceItem(native, title, "https://example.invalid/research",
            timezone.now() - timedelta(days=1), "The committee left the rate at 4%.")
        return capture.capture(SOURCE, CONTRACT, lambda: SourceBatch((item,), timezone.now(),
            "bounded_snapshot", False, "a" * 64), **kwargs)

    def prepare(self, command=None, revisions=None, **kwargs):
        return evidence.prepare_evidence(self.actor, self.thesis["id"], command or str(uuid4()),
            revisions or [str(self.revision.pk)], **kwargs)

    def withdraw(self, *, clock=timezone.now):
        source = SourceState.objects.get(pk=SOURCE)
        return permissions.set_source_permission(str(self.staff.pk), SOURCE, source.contract_digest,
            False, "Recorded research permission withdrawal.", clock=clock)


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ALLOW_SYNTHETIC_SETUP=True, MACRO_ENABLE_MODEL_COMPILATION=True,
    MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="recorded-test-key",
    SETTINGS_MODULE="macro_agent.web.local_settings")
class ResearchEvidenceTests(EvidenceFixtures, TransactionTestCase):
    def setUp(self):
        self.setup_evidence()

    def test_freeze_works_without_approval_and_does_not_amend_thesis(self):
        saved = self.prepare()
        self.assertIsNone(service.get_thesis(self.actor, self.thesis["id"])["approved"])
        self.assertEqual(saved["evidence"]["content"]["reports"][0]["revision_id"], str(self.revision.pk))
        self.assertEqual(saved["current_disposition"]["status"], "current")
        self.assertEqual(ResearchEvidenceMember.objects.count(), 1)
        self.assertEqual(service.get_thesis(self.actor, self.thesis["id"]), self.thesis)

    def test_saved_retry_after_correction_preserves_original_and_reports_stale(self):
        command = str(uuid4())
        first = self.prepare(command)
        self.capture_report("Corrected fictional policy report")
        again = self.prepare(command)
        self.assertEqual(again["evidence"], first["evidence"])
        self.assertTrue(again["replayed"])
        self.assertEqual(again["current_disposition"]["status"], "stale")
        self.assertEqual(ResearchEvidenceContext.objects.count(), 1)

    def test_new_distinct_report_does_not_change_frozen_disposition(self):
        saved = self.prepare()
        self.capture_report(native="research-2")
        self.assertEqual(evidence.get_evidence(self.actor, self.thesis["id"], saved["evidence"]["id"])
                         ["current_disposition"]["status"], "current")

    def test_withdrawal_blocks_new_freeze_but_saved_command_remains_readable(self):
        command = str(uuid4())
        first = self.prepare(command)
        self.withdraw()
        self.assertEqual(self.prepare(command)["evidence"], first["evidence"])
        with self.assertRaises(service.ThesisConflict):
            self.prepare()

    def test_historical_revision_and_missing_witness_are_rejected(self):
        self.capture_report("Corrected report")
        with self.assertRaises(service.ThesisConflict):
            self.prepare()
        with self.assertRaises(RuntimeError):
            self.capture_report(native="unwitnessed", after_commit=lambda: (_ for _ in ()).throw(RuntimeError("crash")))
        row = SourceRevision.objects.get(report__native_id="unwitnessed")
        with self.assertRaisesMessage(service.ThesisConflict, "durable witness"):
            self.prepare(revisions=[str(row.pk)])
        self.assertFalse(ResearchEvidenceContext.objects.exists())

    def test_foreign_owner_cannot_inspect_or_freeze_into_thesis(self):
        saved = self.prepare()
        with self.assertRaises(service.ThesisUnavailable):
            evidence.get_evidence(str(self.other.pk), self.thesis["id"], saved["evidence"]["id"])
        with self.assertRaises(service.ThesisUnavailable):
            evidence.prepare_evidence(str(self.other.pk), self.thesis["id"], str(uuid4()), [str(self.revision.pk)])

    def test_command_collision_and_duplicate_revision_rejected(self):
        command = str(uuid4())
        self.prepare(command)
        self.capture_report(native="research-2")
        row = SourceRevision.objects.get(report__native_id="research-2")
        with self.assertRaises(service.ThesisConflict):
            self.prepare(command, [str(row.pk)])
        with self.assertRaises(ValueError):
            self.prepare(revisions=[str(row.pk), str(row.pk)])

    def test_sql_rejects_mutation_missing_membership_and_foreign_scope(self):
        saved = self.prepare()
        context = ResearchEvidenceContext.objects.get(pk=saved["evidence"]["id"])
        for model in (ResearchEvidenceContext, ResearchEvidenceMember):
            with self.subTest(model=model), self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.all().delete()
        values = dict(owner=self.owner, thesis_id=self.thesis["id"], command_id=uuid4(),
            request_digest=context.request_digest, content=context.content, digest=context.digest,
            created_at=context.created_at)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchEvidenceContext.objects.create(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchEvidenceContext.objects.create(**{**values, "owner": self.other})

    def test_backdated_observation_rejected(self):
        saved = self.prepare()
        context = ResearchEvidenceContext.objects.get(pk=saved["evidence"]["id"])
        with self.assertRaises(service.ThesisConflict):
            evidence.get_evidence(self.actor, self.thesis["id"], str(context.pk),
                                  clock=lambda: context.created_at - timedelta(microseconds=1))
