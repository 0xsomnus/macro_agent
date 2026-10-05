"""Versioned user-declared paper exposure with immutable scoped history.

Commands lock owner, thesis, then position. Stored product declarations are
unverified and confer no coverage or execution authority. accepted_at is an
effective command time, not proof of exact durable availability.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


DIGEST_PATTERN = r"^[0-9a-f]{64}$"
COMMAND_KINDS = ("create", "revise", "close")
QUANTITY_PATTERN = r"^(0|[1-9][0-9]*)(\.[0-9]+)?$"


class PositionRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name="macro_paper_positions")
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT,
                               related_name="paper_positions")
    original_approval = models.ForeignKey("macro_theses.ApprovalRecord", on_delete=models.PROTECT,
                                          related_name="original_paper_positions")
    current_version = models.ForeignKey("PositionVersion", null=True, on_delete=models.PROTECT,
                                        related_name="+")
    revision = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField()
    changed_at = models.DateTimeField()

    class Meta:
        db_table = "macro_paper_positions"
        constraints = [
            models.UniqueConstraint(fields=("id", "thesis"), name="macro_position_thesis_target"),
            models.UniqueConstraint(fields=("id", "thesis", "owner"),
                                    name="macro_position_scope_target"),
            models.CheckConstraint(condition=Q(revision__gte=0), name="macro_position_revision_nonnegative"),
            models.CheckConstraint(condition=Q(changed_at__gte=F("created_at")),
                                   name="macro_position_time_order"),
            models.CheckConstraint(condition=(
                Q(revision=0, current_version__isnull=True)
                | Q(revision__gt=0, current_version__isnull=False)
            ), name="macro_position_current_revision_pair"),
        ]


class PositionVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    position = models.ForeignKey(PositionRecord, on_delete=models.PROTECT,
                                 related_name="versions")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name="macro_paper_position_versions")
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT,
                               related_name="paper_position_versions")
    reviewed_approval = models.ForeignKey("macro_theses.ApprovalRecord", on_delete=models.PROTECT,
                                          related_name="reviewed_paper_position_versions")
    parent = models.ForeignKey("self", null=True, on_delete=models.PROTECT,
                               related_name="children")
    paper = models.BooleanField(default=True, editable=False)
    status = models.CharField(max_length=8, choices=(("open", "open"), ("closed", "closed")))
    mapping_status = models.CharField(max_length=32, default="user_declared_unverified",
                                     editable=False)
    underlying = models.CharField(max_length=128)
    direction = models.CharField(max_length=8, choices=(("long", "long"), ("short", "short")))
    product_id = models.CharField(max_length=256, null=True)
    venue = models.CharField(max_length=128, null=True)
    expiry = models.CharField(max_length=10, null=True)
    quote_currency = models.CharField(max_length=16, null=True)
    horizon = models.CharField(max_length=1_000, null=True)
    quantity = models.CharField(max_length=29, null=True)
    quantity_unit = models.CharField(max_length=64, null=True)
    accepted_at = models.DateTimeField()
    digest = models.CharField(max_length=64)

    class Meta:
        db_table = "macro_paper_position_versions"
        constraints = [
            models.UniqueConstraint(fields=("position", "id"), name="macro_position_version_target"),
            models.CheckConstraint(condition=Q(paper=True), name="macro_position_paper_only"),
            models.CheckConstraint(condition=Q(status__in=("open", "closed")),
                                   name="macro_position_status_allowed"),
            models.CheckConstraint(condition=Q(mapping_status="user_declared_unverified"),
                                   name="macro_position_mapping_unverified"),
            models.CheckConstraint(condition=Q(underlying__regex=r"\S"),
                                   name="macro_position_underlying_named"),
            models.CheckConstraint(condition=Q(direction__in=("long", "short")),
                                   name="macro_position_direction_allowed"),
            models.CheckConstraint(condition=Q(digest__regex=DIGEST_PATTERN),
                                   name="macro_position_digest_sha256"),
            models.CheckConstraint(condition=~Q(parent=F("id")),
                                   name="macro_position_parent_not_self"),
            models.CheckConstraint(condition=(
                Q(quantity__isnull=True, quantity_unit__isnull=True)
                | Q(quantity__isnull=False, quantity_unit__isnull=False)
            ), name="macro_position_quantity_unit_pair"),
            models.CheckConstraint(condition=Q(quantity__regex=QUANTITY_PATTERN),
                                   name="macro_position_quantity_lexical"),
            *[
                models.CheckConstraint(condition=Q(**{f"{field}__regex": r"\S"}),
                                       name=f"macro_position_{field}_named")
                for field in ("product_id", "venue", "quote_currency", "horizon", "quantity_unit")
            ],
        ]


class CommandReceipt(models.Model):
    command_id = models.UUIDField()
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name="macro_paper_position_commands")
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT,
                               related_name="paper_position_commands")
    position = models.ForeignKey(PositionRecord, on_delete=models.PROTECT,
                                 related_name="command_receipts")
    kind = models.CharField(max_length=16, choices=tuple((kind, kind) for kind in COMMAND_KINDS))
    request_digest = models.CharField(max_length=64)
    result = models.JSONField()
    saved_at = models.DateTimeField()

    class Meta:
        db_table = "macro_paper_position_command_receipts"
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="macro_position_command_identity"),
            models.CheckConstraint(condition=Q(kind__in=COMMAND_KINDS),
                                   name="macro_position_command_kind_allowed"),
            models.CheckConstraint(condition=Q(request_digest__regex=DIGEST_PATTERN),
                                   name="macro_position_command_digest"),
        ]


class AuditTransition(models.Model):
    sequence = models.BigAutoField(primary_key=True)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT,
                               related_name="paper_position_audit")
    position = models.ForeignKey(PositionRecord, on_delete=models.PROTECT,
                                 related_name="audit_transitions")
    kind = models.CharField(max_length=64)
    at = models.DateTimeField()
    detail = models.JSONField()

    class Meta:
        db_table = "macro_paper_position_audit_transitions"
        ordering = ("sequence",)
        constraints = [
            models.CheckConstraint(condition=Q(kind__regex=r"\S"),
                                   name="macro_position_audit_kind_named"),
        ]
