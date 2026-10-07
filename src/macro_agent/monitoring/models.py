"""Source capture evidence and recoverable work, never publication authority.

Writers protect source then work, and sample time after protection. Database
guards preserve immutable evidence; source heads mean latest observed payload,
not publisher-authoritative ordering or reviewed facts.
"""

from uuid import uuid4

from django.db import models
from django.db.models import F, Q


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
