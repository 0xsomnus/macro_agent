"""Stable thesis/brief bindings and immutable observations of durable inputs."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ThesisBriefBinding(models.Model):
    brief = models.OneToOneField("macro_persistence.BriefStateRecord", primary_key=True,
                                 on_delete=models.PROTECT, related_name="thesis_binding")
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT,
                               related_name="brief_bindings")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name="thesis_brief_bindings")
    created_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=(("pending", "pending"), ("ready", "ready")))
    admitted_approval = models.ForeignKey("macro_theses.ApprovalRecord", null=True,
                                          on_delete=models.PROTECT, related_name="brief_bindings")
    admitted_exposure_digest = models.CharField(max_length=64, null=True)
    observed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "macro_thesis_brief_bindings"
        constraints = [
            models.UniqueConstraint(fields=("brief", "thesis"), name="macro_binding_thesis_target"),
            models.CheckConstraint(condition=Q(status__in=("pending", "ready")),
                                   name="macro_binding_status_allowed"),
            models.CheckConstraint(condition=(Q(status="pending") | Q(
                status="ready", admitted_approval__isnull=False,
                admitted_exposure_digest__isnull=False,
                admitted_exposure_digest__regex=r"^[0-9a-f]{64}$", observed_at__isnull=False)),
                name="macro_binding_ready_inputs"),
            models.CheckConstraint(condition=(Q(observed_at__isnull=True) |
                                               Q(observed_at__gte=F("created_at"))),
                                   name="macro_binding_observation_order"),
        ]


class ContextAdmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brief = models.ForeignKey("macro_persistence.BriefStateRecord", on_delete=models.PROTECT,
                              related_name="context_admissions")
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT,
                               related_name="context_admissions")
    approval = models.ForeignKey("macro_theses.ApprovalRecord", on_delete=models.PROTECT,
                                 related_name="context_admissions")
    exposure_digest = models.CharField(max_length=64)
    input_digest = models.CharField(max_length=64)
    input_observed_at = models.DateTimeField()
    admission_effective_at = models.DateTimeField()
    resolved_inputs = models.JSONField()
    pins = models.JSONField()

    class Meta:
        db_table = "macro_context_admissions"
        constraints = [
            models.UniqueConstraint(fields=("brief", "approval", "exposure_digest"),
                                    name="macro_admission_context_identity"),
            models.CheckConstraint(condition=Q(exposure_digest__regex=r"^[0-9a-f]{64}$"),
                                   name="macro_admission_exposure_digest"),
            models.CheckConstraint(condition=Q(input_digest__regex=r"^[0-9a-f]{64}$"),
                                   name="macro_admission_input_digest"),
            models.CheckConstraint(condition=Q(admission_effective_at__gte=F("input_observed_at")),
                                   name="macro_admission_time_order"),
        ]
