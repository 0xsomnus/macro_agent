"""Immutable, deliberately selected evidence available before thesis approval."""

from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import Q


class ResearchEvidenceContext(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    command_id = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    content = models.JSONField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="desk_research_command_once"),
            models.UniqueConstraint(fields=("id", "owner", "thesis"), name="desk_research_scope_target"),
            models.CheckConstraint(condition=Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                                   name="desk_research_request_digest"),
            models.CheckConstraint(condition=Q(digest__regex=r"^[0-9a-f]{64}$"),
                                   name="desk_research_content_digest"),
        ]


class ResearchEvidenceMember(models.Model):
    context = models.ForeignKey(ResearchEvidenceContext, on_delete=models.PROTECT,
                                related_name="members")
    revision = models.ForeignKey("macro_monitoring.SourceRevision", on_delete=models.PROTECT)
    contract = models.ForeignKey("macro_desk.SourceContractVersion", on_delete=models.PROTECT)
    witness = models.ForeignKey("macro_monitoring.DurableObservation", on_delete=models.PROTECT)
    head_at_admission = models.ForeignKey("macro_monitoring.SourceRevision", on_delete=models.PROTECT,
                                         related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=("context", "revision"),
                                               name="desk_research_revision_once")]
