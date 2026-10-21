"""Explicit research continuation consent and fenced internal worker history."""

from uuid import uuid4
from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ResearchJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    run = models.OneToOneField("macro_desk.ResearchRun", on_delete=models.PROTECT)
    command_id = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    compilation_command_id = models.UUIDField()
    evidence_command_id = models.UUIDField()
    provider = models.CharField(max_length=32)
    model_id = models.CharField(max_length=255)
    model_configuration = models.JSONField()
    policy = models.JSONField()
    created_at = models.DateTimeField()
    changed_at = models.DateTimeField()
    status = models.CharField(max_length=16)
    next_due_at = models.DateTimeField(null=True)
    active_token = models.UUIDField(null=True)
    lease_deadline_at = models.DateTimeField(null=True)
    attempt_count = models.PositiveBigIntegerField(default=0)
    last_stop_reason = models.CharField(max_length=96)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="desk_research_job_command"),
            models.CheckConstraint(condition=Q(status__in=("pending", "running", "blocked", "completed", "revoked")), name="desk_research_job_status"),
            models.CheckConstraint(condition=Q(changed_at__gte=F("created_at")), name="desk_research_job_clock"),
            models.CheckConstraint(condition=Q(request_digest__regex=r"^[0-9a-f]{64}$"), name="desk_research_job_digest"),
            models.CheckConstraint(condition=Q(attempt_count__lte=12), name="desk_research_job_lease_bound"),
        ]


class ResearchJobRevocation(models.Model):
    job = models.OneToOneField(ResearchJob, primary_key=True, on_delete=models.PROTECT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    command_id = models.UUIDField()
    created_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=("owner", "command_id"), name="desk_research_job_revoke_command")]


class ResearchJobLease(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    job = models.ForeignKey(ResearchJob, on_delete=models.PROTECT, related_name="leases")
    sequence = models.PositiveBigIntegerField()
    admitted_at = models.DateTimeField()
    deadline_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("job", "sequence"), name="desk_research_job_lease_sequence"),
            models.CheckConstraint(condition=Q(deadline_at__gt=F("admitted_at")), name="desk_research_job_lease_clock"),
        ]


class ResearchJobOutcome(models.Model):
    lease = models.OneToOneField(ResearchJobLease, primary_key=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=16)
    reason = models.CharField(max_length=96)
    finished_at = models.DateTimeField()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(status__in=("pending", "blocked", "completed", "expired", "revoked")), name="desk_research_job_outcome_status")]


class ResearchJobAdmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    lease = models.ForeignKey(ResearchJobLease, on_delete=models.PROTECT, related_name="admissions")
    source_attempt = models.OneToOneField("macro_desk.ResearchDiscoveryAttempt", null=True, on_delete=models.PROTECT)
    compilation_attempt = models.OneToOneField("macro_theses.CompilationAttempt", null=True, on_delete=models.PROTECT)
    admitted_at = models.DateTimeField()

    class Meta:
        constraints = [models.CheckConstraint(condition=(Q(source_attempt__isnull=False, compilation_attempt__isnull=True)
            | Q(source_attempt__isnull=True, compilation_attempt__isnull=False)), name="desk_research_job_admission_kind")]
