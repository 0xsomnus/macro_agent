"""User-owned drafts and append-only approval evidence.

Every writer locks the authenticated owner row, then ThesisRecord in a short
application transaction. These records do not compile user beliefs, authenticate
callers, or activate drafts themselves. PostgreSQL protects scoped history.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


DIGEST_PATTERN = r"^[0-9a-f]{64}$"
COMMAND_KINDS = ("create", "propose", "approve")


class ThesisRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name="macro_theses")
    revision = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField()
    changed_at = models.DateTimeField()
    latest_text = models.ForeignKey("TextVersionRecord", null=True, on_delete=models.PROTECT,
                                   related_name="+")
    latest_interpretation = models.ForeignKey("InterpretationRecord", null=True,
                                             on_delete=models.PROTECT, related_name="+")
    current_approval = models.ForeignKey("ApprovalRecord", null=True, on_delete=models.PROTECT,
                                        related_name="+")

    class Meta:
        db_table = "macro_theses"
        constraints = [
            # Composite PostgreSQL references need matching unique targets.
            models.UniqueConstraint(fields=("id", "owner"), name="macro_thesis_owner_target"),
            models.CheckConstraint(condition=Q(revision__gte=0), name="macro_thesis_revision_nonnegative"),
            models.CheckConstraint(condition=Q(changed_at__gte=F("created_at")),
                                   name="macro_thesis_time_order"),
            models.CheckConstraint(condition=(
                Q(latest_text__isnull=True, latest_interpretation__isnull=True,
                  current_approval__isnull=True)
                | Q(latest_text__isnull=False, latest_interpretation__isnull=False)
            ), name="macro_thesis_draft_pair"),
        ]


class TextVersionRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thesis = models.ForeignKey(ThesisRecord, on_delete=models.PROTECT,
                               related_name="text_versions")
    exact_text = models.TextField()
    text_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField()
    parent = models.ForeignKey("self", null=True, on_delete=models.PROTECT,
                               related_name="children")

    class Meta:
        db_table = "macro_thesis_text_versions"
        constraints = [
            models.UniqueConstraint(fields=("thesis", "id"), name="macro_text_scoped_target"),
            models.CheckConstraint(condition=Q(exact_text__regex=r"\S"), name="macro_text_named"),
            models.CheckConstraint(condition=Q(text_digest__regex=DIGEST_PATTERN),
                                   name="macro_text_digest_sha256"),
            models.CheckConstraint(condition=~Q(parent=F("id")), name="macro_text_parent_not_self"),
        ]


class InterpretationRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thesis = models.ForeignKey(ThesisRecord, on_delete=models.PROTECT,
                               related_name="interpretations")
    text_version = models.ForeignKey(TextVersionRecord, on_delete=models.PROTECT,
                                     related_name="interpretations")
    drivers = models.JSONField()
    horizon = models.TextField(null=True)
    invalidation_signposts = models.JSONField()
    known_at = models.DateTimeField()
    digest = models.CharField(max_length=64)
    # This slice persists an explicit user-supplied preview, with no compiler.
    origin = models.CharField(max_length=32, default="user_supplied", editable=False,
                              choices=(("user_supplied", "user_supplied"),))

    class Meta:
        db_table = "macro_thesis_interpretations"
        constraints = [
            models.UniqueConstraint(fields=("thesis", "id"), name="macro_interp_scoped_target"),
            models.UniqueConstraint(fields=("thesis", "text_version", "id"),
                                    name="macro_interp_text_target"),
            models.CheckConstraint(condition=Q(digest__regex=DIGEST_PATTERN),
                                   name="macro_interp_digest_sha256"),
            models.CheckConstraint(condition=Q(origin="user_supplied"),
                                   name="macro_interp_origin_manual"),
        ]


class ApprovalRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thesis = models.ForeignKey(ThesisRecord, on_delete=models.PROTECT,
                               related_name="approvals")
    text_version = models.ForeignKey(TextVersionRecord, on_delete=models.PROTECT,
                                     related_name="approvals")
    interpretation = models.ForeignKey(InterpretationRecord, on_delete=models.PROTECT,
                                       related_name="approvals")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name="macro_thesis_approvals")
    approved_at = models.DateTimeField()
    digest = models.CharField(max_length=64)
    revision = models.PositiveBigIntegerField()

    class Meta:
        db_table = "macro_thesis_approvals"
        constraints = [
            models.UniqueConstraint(fields=("thesis", "id"), name="macro_approval_scoped_target"),
            models.UniqueConstraint(fields=("thesis", "revision"), name="macro_approval_revision_identity"),
            models.CheckConstraint(condition=Q(digest__regex=DIGEST_PATTERN),
                                   name="macro_approval_digest_sha256"),
            models.CheckConstraint(condition=Q(revision__gt=0), name="macro_approval_revision_positive"),
        ]


class CommandReceipt(models.Model):
    command_id = models.UUIDField()
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name="macro_thesis_commands")
    thesis = models.ForeignKey(ThesisRecord, on_delete=models.PROTECT,
                               related_name="command_receipts")
    kind = models.CharField(max_length=16, choices=tuple((kind, kind) for kind in COMMAND_KINDS))
    request_digest = models.CharField(max_length=64)
    result = models.JSONField()
    saved_at = models.DateTimeField()

    class Meta:
        db_table = "macro_thesis_command_receipts"
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="macro_thesis_command_identity"),
            models.CheckConstraint(condition=Q(kind__in=COMMAND_KINDS),
                                   name="macro_thesis_command_kind_allowed"),
            models.CheckConstraint(condition=Q(request_digest__regex=DIGEST_PATTERN),
                                   name="macro_command_digest_sha256"),
        ]


class AuditTransition(models.Model):
    sequence = models.BigAutoField(primary_key=True)
    thesis = models.ForeignKey(ThesisRecord, on_delete=models.PROTECT,
                               related_name="audit_transitions")
    kind = models.CharField(max_length=64)
    at = models.DateTimeField()
    detail = models.JSONField()

    class Meta:
        db_table = "macro_thesis_audit_transitions"
        ordering = ("sequence",)
        constraints = [
            models.CheckConstraint(condition=Q(kind__regex=r"\S"), name="macro_thesis_audit_kind_named"),
        ]
