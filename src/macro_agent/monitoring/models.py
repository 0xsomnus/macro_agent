"""Source capture evidence and recoverable work, never publication authority.

Writers protect source then work, and sample time after protection. Database
guards preserve immutable evidence; source heads mean latest observed payload,
not publisher-authoritative ordering or reviewed facts.
"""

from uuid import uuid4

from django.db import models
from django.db.models import F, Q
from django.conf import settings


class SourceState(models.Model):
    id = models.CharField(primary_key=True, max_length=128)
    contract = models.JSONField()
    contract_digest = models.CharField(max_length=64)
    capture_sequence = models.PositiveBigIntegerField(default=0)
    active_capture = models.UUIDField(null=True)
    last_successful_capture_at = models.DateTimeField(null=True)


class CaptureAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    source = models.ForeignKey(SourceState, on_delete=models.PROTECT)
    sequence = models.PositiveBigIntegerField()
    admitted_at = models.DateTimeField()
    deadline_at = models.DateTimeField()
    contract_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("source", "sequence"), name="monitor_capture_sequence"),
            models.CheckConstraint(condition=Q(deadline_at__gt=F("admitted_at")), name="monitor_capture_deadline"),
        ]


class CaptureOutcome(models.Model):
    attempt = models.OneToOneField(CaptureAttempt, primary_key=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=32, choices=[(s, s) for s in ("captured", "failed", "outcome_unknown")])
    code = models.CharField(max_length=64)
    finished_at = models.DateTimeField()
    received_at = models.DateTimeField(null=True)
    transport_digest = models.CharField(max_length=64, null=True)
    item_count = models.PositiveIntegerField(default=0)
    new_revision_count = models.PositiveIntegerField(default=0)
    coverage = models.CharField(max_length=32, default="bounded_snapshot")

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(status__in=("captured", "failed", "outcome_unknown")), name="monitor_capture_status")]


class SourceReport(models.Model):
    source = models.ForeignKey(SourceState, on_delete=models.PROTECT)
    native_id = models.CharField(max_length=512)
    revision_count = models.PositiveIntegerField(default=0)
    current_revision = models.ForeignKey("SourceRevision", null=True, on_delete=models.PROTECT, related_name="current_heads")

    class Meta:
        constraints = [models.UniqueConstraint(fields=("source", "native_id"), name="monitor_native_identity")]


class SourceRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    report = models.ForeignKey(SourceReport, on_delete=models.PROTECT, related_name="revisions")
    observation_revision = models.PositiveIntegerField()
    digest = models.CharField(max_length=64)
    payload = models.JSONField()
    source_claimed_published_at = models.DateTimeField(null=True)
    system_received_at = models.DateTimeField()
    capture = models.ForeignKey(CaptureAttempt, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("report", "digest"), name="monitor_payload_identity"),
            models.UniqueConstraint(fields=("report", "observation_revision"), name="monitor_observation_order"),
            models.UniqueConstraint(fields=("report", "id"), name="monitor_revision_scope"),
            models.CheckConstraint(condition=Q(observation_revision__gt=0), name="monitor_revision_positive"),
            models.CheckConstraint(condition=Q(digest__regex=r"^[0-9a-f]{64}$"), name="monitor_revision_digest"),
        ]


class CaptureMembership(models.Model):
    capture = models.ForeignKey(CaptureAttempt, on_delete=models.PROTECT)
    revision = models.ForeignKey(SourceRevision, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("capture", "revision"), name="monitor_capture_membership")]


class DurableObservation(models.Model):
    revision = models.OneToOneField(SourceRevision, primary_key=True, on_delete=models.PROTECT)
    observed_by_at = models.DateTimeField()
    method = models.CharField(max_length=32, default="postcommit_read")


class ScreeningWork(models.Model):
    revision = models.OneToOneField(SourceRevision, primary_key=True, on_delete=models.PROTECT)
    state = models.CharField(max_length=16, default="pending", choices=[(s, s) for s in ("pending", "running", "completed", "superseded")])
    attempt_count = models.PositiveIntegerField(default=0)
    active_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(state__in=("pending", "running", "completed", "superseded")), name="monitor_work_status"),
            models.CheckConstraint(condition=(Q(state="running", active_token__isnull=False, lease_until__isnull=False) | (~Q(state="running") & Q(active_token__isnull=True, lease_until__isnull=True))), name="monitor_work_lease_state"),
        ]


class ScreeningAttempt(models.Model):
    token = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    work = models.ForeignKey(ScreeningWork, on_delete=models.PROTECT, related_name="attempts")
    sequence = models.PositiveIntegerField()
    admitted_at = models.DateTimeField()
    deadline_at = models.DateTimeField()
    rule_version = models.CharField(max_length=64, default="unclassified-preserve-v1")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("work", "sequence"), name="monitor_screen_sequence"),
            models.CheckConstraint(condition=Q(deadline_at__gt=F("admitted_at")), name="monitor_screen_deadline"),
        ]


class ScreeningResult(models.Model):
    attempt = models.OneToOneField(ScreeningAttempt, primary_key=True, on_delete=models.PROTECT)
    finished_at = models.DateTimeField()
    decision = models.JSONField()


class NewsAnalysisAttempt(models.Model):
    """Immutable private admission. It grants neither approval nor publication."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    command_id = models.UUIDField()
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    approval = models.ForeignKey("macro_theses.ApprovalRecord", on_delete=models.PROTECT)
    source_revision = models.ForeignKey(SourceRevision, on_delete=models.PROTECT)
    exposure_digest = models.CharField(max_length=64)
    request_digest = models.CharField(max_length=64)
    resolved_inputs = models.JSONField()
    context = models.JSONField()
    context_digest = models.CharField(max_length=64)
    messages = models.JSONField()
    prompt_digest = models.CharField(max_length=64)
    provider = models.CharField(max_length=32)
    model_id = models.CharField(max_length=255)
    model_metadata = models.JSONField()
    configuration = models.JSONField()
    created_at = models.DateTimeField()
    deadline_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="monitor_analysis_command"),
            models.UniqueConstraint(fields=("thesis", "approval", "exposure_digest", "source_revision"), name="monitor_analysis_input_once"),
            models.CheckConstraint(condition=Q(deadline_at__gt=F("created_at")), name="monitor_analysis_deadline"),
            models.CheckConstraint(condition=Q(provider__in=("nanogpt", "openrouter", "cheaperinference")), name="monitor_analysis_provider"),
        ]


class NewsAnalysisResult(models.Model):
    attempt = models.OneToOneField(NewsAnalysisAttempt, primary_key=True, on_delete=models.PROTECT, related_name="result")
    status = models.CharField(max_length=32)
    stop_reason = models.CharField(max_length=64)
    finished_at = models.DateTimeField()
    document = models.JSONField(null=True)
    provider_metadata = models.JSONField()
    stale_reasons = models.JSONField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(status__in=("analysed", "stale", "failed", "outcome_unknown")), name="monitor_analysis_result_status"),
            models.CheckConstraint(condition=(~Q(status__in=("analysed", "stale")) | Q(document__isnull=False)), name="monitor_analysis_document"),
        ]


class NewsReviewReceipt(models.Model):
    """Pin no-call outcomes too, so a historical empty retry cannot spend."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    command_id = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    attempt = models.OneToOneField(NewsAnalysisAttempt, null=True, on_delete=models.PROTECT)
    empty_response = models.JSONField(null=True)
    saved_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="monitor_news_receipt_identity"),
            models.CheckConstraint(condition=(Q(attempt__isnull=False, empty_response__isnull=True)
                | Q(attempt__isnull=True, empty_response__isnull=False)), name="monitor_news_receipt_outcome"),
        ]
