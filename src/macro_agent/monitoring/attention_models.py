"""Immutable evolving-news publication identity, separate from model admission."""

from uuid import uuid4
from django.conf import settings
from django.db import models
from django.db.models import Q
from macro_agent.domain.news_publication import POLICY_VERSION


class NewsBrief(models.Model):
    brief = models.OneToOneField("macro_persistence.BriefStateRecord", primary_key=True,
        on_delete=models.PROTECT, related_name="news_binding")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.OneToOneField("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    fanout_limit = models.PositiveIntegerField()
    policy_version = models.CharField(max_length=64)
    created_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("brief", "owner", "thesis"), name="monitor_news_binding_scope"),
            models.CheckConstraint(condition=Q(fanout_limit__gte=1, fanout_limit__lte=1000), name="monitor_news_fanout_explicit"),
            models.CheckConstraint(condition=Q(policy_version=POLICY_VERSION), name="monitor_news_policy_explicit"),
        ]


class NewsPublication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    command_id = models.UUIDField()
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    brief = models.ForeignKey("macro_persistence.BriefStateRecord", on_delete=models.PROTECT)
    attempt = models.OneToOneField("macro_monitoring.NewsAnalysisAttempt", on_delete=models.PROTECT)
    assessment = models.OneToOneField("macro_persistence.AssessmentRecord", on_delete=models.PROTECT)
    request_digest = models.CharField(max_length=64)
    analysis_digest = models.CharField(max_length=64)
    expected_generation = models.PositiveBigIntegerField()
    predecessor = models.ForeignKey("self", null=True, on_delete=models.PROTECT, related_name="successors")
    attention_origin = models.ForeignKey("self", null=True, on_delete=models.PROTECT, related_name="carried_reviews")
    slot_lease = models.ForeignKey("macro_scheduling.SlotLease", null=True, on_delete=models.PROTECT)
    attention_decision = models.JSONField()
    published_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="monitor_news_publication_command"),
            models.CheckConstraint(condition=Q(request_digest__regex=r"^[0-9a-f]{64}$"), name="monitor_news_request_digest"),
            models.CheckConstraint(condition=Q(analysis_digest__regex=r"^[0-9a-f]{64}$"), name="monitor_news_analysis_digest"),
        ]
