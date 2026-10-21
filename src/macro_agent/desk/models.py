"""Immutable evidence membership, private context lineage and retained reviews."""

from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class SourceContractVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    source = models.ForeignKey("macro_monitoring.SourceState", on_delete=models.PROTECT)
    contract = models.JSONField()
    digest = models.CharField(max_length=64)
    permitted = models.BooleanField()
    provenance = models.CharField(max_length=64)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField()
    observed_at = models.DateTimeField()
    parent = models.ForeignKey("self", null=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("source", "id"), name="desk_contract_scope_target")]


class SourceContractHead(models.Model):
    source = models.OneToOneField("macro_monitoring.SourceState", primary_key=True, on_delete=models.PROTECT)
    version = models.OneToOneField(SourceContractVersion, on_delete=models.PROTECT)


class AnalysisResultObservation(models.Model):
    result = models.OneToOneField("macro_monitoring.NewsAnalysisResult", primary_key=True,
                                  on_delete=models.PROTECT)
    observed_by_at = models.DateTimeField()
    method = models.CharField(max_length=32, default="postcommit_read")


class EvidenceSet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    start = models.DateTimeField()
    cutoff = models.DateTimeField()
    prepared_at = models.DateTimeField()
    policy_version = models.CharField(max_length=64, default="complete-retained-sources-v1")
    limits = models.JSONField()
    source_manifest = models.JSONField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(cutoff__gt=F("start")) & Q(prepared_at__gte=F("cutoff")),
                                   name="desk_evidence_period"),
            models.UniqueConstraint(fields=("id", "owner", "thesis"), name="desk_evidence_scope_target"),
        ]


class EvidenceSource(models.Model):
    evidence = models.ForeignKey(EvidenceSet, on_delete=models.PROTECT, related_name="sources")
    source = models.ForeignKey("macro_monitoring.SourceState", on_delete=models.PROTECT)
    contract = models.ForeignKey(SourceContractVersion, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("evidence", "source"), name="desk_evidence_source_once")]


class EvidenceRevision(models.Model):
    evidence = models.ForeignKey(EvidenceSet, on_delete=models.PROTECT, related_name="revisions")
    revision = models.ForeignKey("macro_monitoring.SourceRevision", on_delete=models.PROTECT)
    contract = models.ForeignKey(SourceContractVersion, on_delete=models.PROTECT)
    witness = models.ForeignKey("macro_monitoring.DurableObservation", null=True, on_delete=models.PROTECT)
    head_at_preparation = models.ForeignKey("macro_monitoring.SourceRevision", null=True,
                                            on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=("evidence", "revision"), name="desk_evidence_revision_once")]


class EvidenceAnalysis(models.Model):
    evidence = models.ForeignKey(EvidenceSet, on_delete=models.PROTECT, related_name="analyses")
    attempt = models.ForeignKey("macro_monitoring.NewsAnalysisAttempt", on_delete=models.PROTECT)
    result = models.ForeignKey("macro_monitoring.NewsAnalysisResult", null=True, on_delete=models.PROTECT)
    witness = models.ForeignKey(AnalysisResultObservation, null=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("evidence", "attempt"), name="desk_evidence_analysis_once")]


class PrivateContext(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    approval = models.ForeignKey("macro_theses.ApprovalRecord", on_delete=models.PROTECT)
    interpretation = models.ForeignKey("macro_theses.InterpretationRecord", on_delete=models.PROTECT)
    evidence = models.OneToOneField(EvidenceSet, on_delete=models.PROTECT)
    predecessor = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    exposure_digest = models.CharField(max_length=64)
    resolved_inputs = models.JSONField()
    prepared_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=("id", "owner", "thesis"), name="desk_context_scope_target")]


class ContextExposure(models.Model):
    context = models.ForeignKey(PrivateContext, on_delete=models.PROTECT, related_name="positions")
    position = models.ForeignKey("macro_positions.PositionRecord", on_delete=models.PROTECT)
    version = models.ForeignKey("macro_positions.PositionVersion", on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("context", "position"), name="desk_context_position_once")]


class DailyReview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    command_id = models.UUIDField()
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    context = models.OneToOneField(PrivateContext, on_delete=models.PROTECT)
    request_digest = models.CharField(max_length=64)
    start = models.DateTimeField()
    cutoff = models.DateTimeField()
    prepared_at = models.DateTimeField()
    content = models.JSONField()
    digest = models.CharField(max_length=64)
    original_outcome = models.CharField(max_length=32, default="prepared")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="desk_review_command_once"),
            models.UniqueConstraint(fields=("thesis", "cutoff"), name="desk_review_cutoff_once"),
            models.CheckConstraint(condition=Q(original_outcome="prepared"), name="desk_review_original_outcome"),
        ]


class DailyBrief(models.Model):
    """Stable private daily stream, sharing protected publication state."""

    brief = models.OneToOneField("macro_persistence.BriefStateRecord", primary_key=True,
                                on_delete=models.PROTECT, related_name="daily_binding")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.OneToOneField("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    fanout_limit = models.PositiveIntegerField()
    created_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("brief", "owner", "thesis"), name="desk_daily_binding_scope"),
            models.CheckConstraint(condition=Q(fanout_limit__gte=1, fanout_limit__lte=1000),
                                   name="desk_daily_fanout_explicit"),
        ]


class DailyPublication(models.Model):
    """Immutable publication identity and original decision via assessment."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    command_id = models.UUIDField()
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    brief = models.ForeignKey("macro_persistence.BriefStateRecord", on_delete=models.PROTECT)
    review = models.OneToOneField(DailyReview, on_delete=models.PROTECT)
    assessment = models.OneToOneField("macro_persistence.AssessmentRecord", on_delete=models.PROTECT)
    request_digest = models.CharField(max_length=64)
    expected_generation = models.PositiveBigIntegerField()
    published_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="desk_daily_publication_command"),
            models.CheckConstraint(condition=Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                                   name="desk_daily_request_digest"),
        ]

# Separate record modules keep the two analytical roles independently auditable.
from .research_models import ResearchEvidenceContext, ResearchEvidenceMember  # noqa: E402,F401
from .synthesis_models import DailySynthesisAttempt, DailySynthesisResult  # noqa: E402,F401
from .investigation_models import (ResearchRun, ResearchPlanAttempt, ResearchPlanResult,
    ResearchDiscoveryAttempt, ResearchDiscoveryReceipt, ResearchDiscoveryResult,
    ResearchSourceState)  # noqa: E402,F401
from .search_budget_models import (SearchBudgetRoot, SearchPriceContract,
    SearchReservation, SearchSettlement)  # noqa: E402,F401
from .research_job_models import (ResearchJob, ResearchJobRevocation,
    ResearchJobLease, ResearchJobOutcome, ResearchJobAdmission)  # noqa: E402,F401
