"""Publication records, with authority and decisions retained in domain modules.

Every governing-state writer locks the brief before reading its heads. Bound
briefs first lock owner and thesis, then sorted briefs. Model save methods and
signals do not substitute for that ordering.
The initial PostgreSQL migration protects immutable history and scoped links.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from macro_agent.domain.publication import REQUIRED_ROLES


ROLE_CHOICES = tuple((role, role) for role in sorted(REQUIRED_ROLES))
DIGEST_PATTERN = r"^[0-9a-f]{64}$"


class BriefStateRecord(models.Model):
    brief_id = models.CharField(primary_key=True, max_length=255)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name="macro_briefs")
    generation = models.PositiveBigIntegerField(default=0)
    changed_at = models.DateTimeField()

    class Meta:
        db_table = "macro_brief_states"
        constraints = [
            models.UniqueConstraint(fields=("brief_id", "owner"), name="macro_brief_owner_target"),
            models.CheckConstraint(condition=Q(brief_id__regex=r"\S"), name="macro_brief_id_named"),
            models.CheckConstraint(condition=Q(generation__gte=0), name="macro_brief_generation_nonnegative"),
        ]


class DependencyVersion(models.Model):
    brief = models.ForeignKey(BriefStateRecord, on_delete=models.PROTECT,
                              related_name="dependency_versions")
    role = models.CharField(max_length=64, choices=ROLE_CHOICES)
    version_id = models.CharField(max_length=512)
    digest = models.CharField(max_length=64)
    known_at = models.DateTimeField()

    class Meta:
        db_table = "macro_dependency_versions"
        constraints = [
            models.UniqueConstraint(fields=("brief", "role", "version_id"), name="macro_dependency_version_identity"),
            # PostgreSQL composite foreign keys need a matching unique target.
            models.UniqueConstraint(fields=("brief", "role", "id"), name="macro_dependency_scoped_target"),
            models.CheckConstraint(condition=Q(role__in=sorted(REQUIRED_ROLES)), name="macro_dependency_role_allowed"),
            models.CheckConstraint(condition=Q(version_id__regex=r"\S"), name="macro_dependency_version_named"),
            models.CheckConstraint(condition=Q(digest__regex=DIGEST_PATTERN), name="macro_dependency_digest_sha256"),
        ]


class DependencyHead(models.Model):
    brief = models.ForeignKey(BriefStateRecord, on_delete=models.PROTECT,
                              related_name="dependency_heads")
    role = models.CharField(max_length=64, choices=ROLE_CHOICES)
    version = models.ForeignKey(DependencyVersion, on_delete=models.PROTECT,
                                related_name="heads")

    class Meta:
        db_table = "macro_dependency_heads"
        constraints = [
            models.UniqueConstraint(fields=("brief", "role"), name="macro_dependency_head_identity"),
            models.CheckConstraint(condition=Q(role__in=sorted(REQUIRED_ROLES)), name="macro_dependency_head_role_allowed"),
        ]


class AssessmentRecord(models.Model):
    brief = models.ForeignKey(BriefStateRecord, on_delete=models.PROTECT,
                              related_name="assessments")
    assessment_id = models.CharField(max_length=255)
    digest = models.CharField(max_length=64)
    # Preserve the exact canonical payload used to derive the domain digest.
    payload = models.TextField()
    status = models.CharField(max_length=16, choices=(("current", "current"), ("superseded", "superseded")))
    reasons = models.JSONField()
    reassessment_required = models.BooleanField()
    observed_dependencies = models.JSONField()
    saved_at = models.DateTimeField()

    class Meta:
        db_table = "macro_assessments"
        constraints = [
            models.UniqueConstraint(fields=("brief", "assessment_id"), name="macro_assessment_identity"),
            models.UniqueConstraint(fields=("brief", "id"), name="macro_assessment_scoped_target"),
            models.CheckConstraint(condition=Q(assessment_id__regex=r"\S"), name="macro_assessment_id_named"),
            models.CheckConstraint(condition=Q(digest__regex=DIGEST_PATTERN), name="macro_assessment_digest_sha256"),
            models.CheckConstraint(condition=Q(status__in=("current", "superseded")), name="macro_assessment_status_allowed"),
        ]


class CurrentAssessment(models.Model):
    brief = models.OneToOneField(BriefStateRecord, primary_key=True, on_delete=models.PROTECT,
                                 related_name="current_assessment")
    assessment = models.ForeignKey(AssessmentRecord, on_delete=models.PROTECT,
                                   related_name="current_pointers")

    class Meta:
        db_table = "macro_current_assessments"


class BriefVersion(models.Model):
    brief = models.ForeignKey(BriefStateRecord, on_delete=models.PROTECT,
                              related_name="versions")
    generation = models.PositiveBigIntegerField()
    assessment = models.ForeignKey(AssessmentRecord, on_delete=models.PROTECT,
                                   related_name="brief_versions")
    saved_at = models.DateTimeField()

    class Meta:
        db_table = "macro_brief_versions"
        constraints = [
            models.UniqueConstraint(fields=("brief", "generation"), name="macro_brief_version_generation"),
            models.CheckConstraint(condition=Q(generation__gt=0), name="macro_brief_version_generation_positive"),
        ]


class NotificationIntent(models.Model):
    intent_id = models.CharField(primary_key=True, max_length=80)
    brief = models.ForeignKey(BriefStateRecord, on_delete=models.PROTECT,
                              related_name="notification_intents")
    assessment = models.ForeignKey(AssessmentRecord, on_delete=models.PROTECT,
                                   related_name="notification_intents")
    state = models.CharField(max_length=16, default="pending", choices=(
        ("pending", "pending"), ("canceled", "canceled"), ("delivered", "delivered")))
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "macro_notification_intents"
        constraints = [
            models.CheckConstraint(condition=Q(intent_id__regex=r"\S"), name="macro_notification_id_named"),
            models.CheckConstraint(condition=Q(state__in=("pending", "canceled", "delivered")), name="macro_notification_state_allowed"),
            models.CheckConstraint(condition=Q(updated_at__gte=F("created_at")), name="macro_notification_time_order"),
        ]
        indexes = [models.Index(fields=("brief", "state"), name="macro_notification_pending_idx")]


class ReassessmentWork(models.Model):
    brief = models.ForeignKey(BriefStateRecord, on_delete=models.PROTECT,
                              related_name="reassessment_work")
    context_digest = models.CharField(max_length=64)
    reason = models.TextField()
    created_at = models.DateTimeField()
    state = models.CharField(max_length=16, default="pending", choices=(
        ("pending", "pending"), ("completed", "completed"), ("superseded", "superseded")))
    completed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "macro_reassessment_work"
        constraints = [
            models.UniqueConstraint(fields=("brief", "context_digest"), name="macro_reassessment_context_identity"),
            models.CheckConstraint(condition=Q(context_digest__regex=DIGEST_PATTERN), name="macro_reassessment_digest_sha256"),
            models.CheckConstraint(condition=Q(reason__regex=r"\S"), name="macro_reassessment_reason_named"),
            models.CheckConstraint(condition=(
                Q(state="pending", completed_at__isnull=True)
                | Q(state__in=("completed", "superseded"), completed_at__isnull=False,
                    completed_at__gte=F("created_at"))
            ), name="macro_reassessment_completion_state"),
        ]


class AuditTransition(models.Model):
    sequence = models.BigAutoField(primary_key=True)
    brief = models.ForeignKey(BriefStateRecord, on_delete=models.PROTECT,
                              related_name="audit_transitions")
    kind = models.CharField(max_length=64)
    happened_at = models.DateTimeField()
    detail = models.JSONField()

    class Meta:
        db_table = "macro_audit_transitions"
        ordering = ("sequence",)
        constraints = [
            models.CheckConstraint(condition=Q(kind__regex=r"\S"), name="macro_audit_kind_named"),
        ]


# Registered with this app while keeping the context boundary a small module.
from .binding_models import ContextAdmission, ThesisBriefBinding  # noqa: E402,F401
