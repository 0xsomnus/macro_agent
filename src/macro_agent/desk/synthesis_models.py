"""Immutable one-call morning interpretations, separate from publication."""

from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class DailySynthesisAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    review = models.ForeignKey("macro_desk.DailyReview", on_delete=models.PROTECT)
    command_id = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    review_digest = models.CharField(max_length=64)
    context = models.JSONField()
    context_digest = models.CharField(max_length=64)
    provider = models.CharField(max_length=32)
    model_id = models.CharField(max_length=255)
    model_metadata = models.JSONField()
    configuration = models.JSONField()
    created_at = models.DateTimeField()
    deadline_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="desk_synthesis_command_once"),
            models.CheckConstraint(condition=Q(deadline_at__gt=F("created_at")), name="desk_synthesis_deadline"),
        ]


class DailySynthesisResult(models.Model):
    attempt = models.OneToOneField(DailySynthesisAttempt, primary_key=True,
        on_delete=models.PROTECT, related_name="result")
    status = models.CharField(max_length=32)
    document = models.JSONField(null=True)
    provider_metadata = models.JSONField()
    stop_reason = models.CharField(max_length=64)
    stale_reasons = models.JSONField()
    finished_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(status__in=("synthesised", "stale", "failed", "outcome_unknown")),
                                   name="desk_synthesis_result_status"),
            models.CheckConstraint(condition=~Q(status__in=("synthesised", "stale")) | Q(document__isnull=False),
                                   name="desk_synthesis_document_present"),
        ]
