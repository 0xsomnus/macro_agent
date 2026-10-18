"""Immutable question-led research admissions, receipts and outcomes.

These records have no monitoring, approval, publication or execution authority.
The linked initial draft preserves the question verbatim with empty intent.
"""

from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ResearchRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    command_id = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    exact_question = models.TextField()
    thesis = models.OneToOneField("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    initial_text = models.ForeignKey("macro_theses.TextVersionRecord", on_delete=models.PROTECT)
    initial_revision = models.PositiveBigIntegerField()
    provider = models.CharField(max_length=32)
    model_id = models.CharField(max_length=255)
    bounds = models.JSONField()
    created_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="desk_investigation_command_once"),
            models.CheckConstraint(condition=Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                                   name="desk_investigation_request_digest"),
        ]


class ResearchPlanAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run = models.OneToOneField(ResearchRun, on_delete=models.PROTECT, related_name="plan_attempt")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    command_id = models.UUIDField()
    configuration = models.JSONField()
    model_metadata = models.JSONField()
    messages = models.JSONField()
    prompt_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField()
    deadline_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="desk_research_plan_command_once"),
            models.CheckConstraint(condition=Q(deadline_at__gt=F("created_at")),
                                   name="desk_research_plan_deadline"),
        ]


class ResearchPlanResult(models.Model):
    attempt = models.OneToOneField(ResearchPlanAttempt, primary_key=True, on_delete=models.PROTECT,
                                  related_name="result")
    status = models.CharField(max_length=32)
    document = models.JSONField(null=True)
    provider_metadata = models.JSONField()
    stop_reason = models.CharField(max_length=64)
    finished_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(status__in=("planned", "stale", "failed", "outcome_unknown")),
                                   name="desk_research_plan_result_status"),
            models.CheckConstraint(condition=~Q(status="planned") | Q(document__isnull=False),
                                   name="desk_research_plan_document"),
        ]


class ResearchDiscoveryAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run = models.ForeignKey(ResearchRun, on_delete=models.PROTECT, related_name="discoveries")
    question_index = models.PositiveSmallIntegerField()
    question = models.JSONField()
    source_id = models.CharField(max_length=128)
    contract = models.JSONField()
    admitted_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("run", "question_index"), name="desk_research_discovery_once"),
            models.CheckConstraint(condition=Q(question_index__gte=0, question_index__lt=3),
                                   name="desk_research_discovery_index"),
        ]


class ResearchDiscoveryReceipt(models.Model):
    attempt = models.OneToOneField(ResearchDiscoveryAttempt, primary_key=True, on_delete=models.PROTECT,
                                  related_name="receipt")
    capture = models.OneToOneField("macro_monitoring.CaptureAttempt", on_delete=models.PROTECT)
    batch = models.JSONField()
    metadata = models.JSONField()
    received_at = models.DateTimeField()


class ResearchDiscoveryResult(models.Model):
    attempt = models.OneToOneField(ResearchDiscoveryAttempt, primary_key=True, on_delete=models.PROTECT,
                                  related_name="result")
    capture = models.OneToOneField("macro_monitoring.CaptureAttempt", null=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=32)
    revision_ids = models.JSONField()
    metadata = models.JSONField()
    stop_reason = models.CharField(max_length=64)
    finished_at = models.DateTimeField()

    class Meta:
        constraints = [models.CheckConstraint(
            condition=Q(status__in=("captured", "failed", "outcome_unknown")),
            name="desk_research_discovery_status")]
