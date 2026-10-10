"""Durable internal task identities and fenced leases, never paid authority."""

from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import F, Q


KINDS = ("capture", "analysis", "daily_review")


class WatchRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    revision = models.PositiveBigIntegerField(default=0)
    current_version = models.ForeignKey("WatchVersion", null=True, on_delete=models.PROTECT, related_name="current_watches")
    changed_at = models.DateTimeField()
    next_capture_at = models.DateTimeField()
    next_analysis_at = models.DateTimeField()
    next_daily_date = models.DateField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=("owner", "thesis"), name="schedule_owner_thesis")]


class WatchVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    watch = models.ForeignKey(WatchRecord, on_delete=models.PROTECT, related_name="versions")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    command_id = models.UUIDField()
    sequence = models.PositiveBigIntegerField()
    configuration = models.JSONField()
    configuration_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("owner", "command_id"), name="schedule_config_command"),
            models.UniqueConstraint(fields=("watch", "sequence"), name="schedule_version_sequence"),
            models.CheckConstraint(condition=Q(sequence__gt=0), name="schedule_version_positive"),
            models.CheckConstraint(condition=Q(configuration_digest__regex=r"^[0-9a-f]{64}$"), name="schedule_config_digest"),
        ]


class ScheduledSlot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    thesis = models.ForeignKey("macro_theses.ThesisRecord", on_delete=models.PROTECT)
    watch = models.ForeignKey(WatchRecord, on_delete=models.PROTECT, related_name="slots")
    watch_version = models.ForeignKey(WatchVersion, on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=[(item, item) for item in KINDS])
    command_id = models.UUIDField(default=uuid4, unique=True)
    identity_key = models.CharField(max_length=128)
    intended_at = models.DateTimeField()
    created_at = models.DateTimeField()
    local_date = models.DateField(null=True)
    period_start = models.DateTimeField(null=True)
    cutoff = models.DateTimeField(null=True)
    late = models.BooleanField()
    coalesced_intervals = models.PositiveBigIntegerField(default=0)
    state = models.CharField(max_length=16, default="pending", choices=[(item, item) for item in ("pending", "running", "completed", "blocked")])
    attempt_count = models.PositiveIntegerField(default=0)
    active_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)

    class Meta:
        indexes = [models.Index(fields=("owner", "kind", "intended_at"), name="schedule_due_owner_kind"),
                   models.Index(fields=("watch", "kind", "state"), name="schedule_watch_kind_state")]
        constraints = [
            models.UniqueConstraint(fields=("owner", "thesis", "kind", "identity_key"), name="schedule_slot_identity"),
            models.UniqueConstraint(fields=("owner", "thesis", "kind", "local_date"), name="schedule_daily_identity"),
            models.CheckConstraint(condition=Q(kind__in=KINDS), name="schedule_slot_kind"),
            models.CheckConstraint(condition=Q(state__in=("pending", "running", "completed", "blocked")), name="schedule_slot_state"),
            models.CheckConstraint(condition=Q(created_at__gte=F("intended_at")), name="schedule_due_creation"),
            models.CheckConstraint(condition=(
                Q(kind="daily_review", local_date__isnull=False, period_start__isnull=False, cutoff__isnull=False,
                  coalesced_intervals=0, cutoff__gt=F("period_start"), cutoff=F("intended_at"))
                | (~Q(kind="daily_review") & Q(local_date__isnull=True, period_start__isnull=True, cutoff__isnull=True))
            ), name="schedule_daily_interval"),
            models.CheckConstraint(condition=(
                Q(state="running", active_token__isnull=False, lease_until__isnull=False)
                | (~Q(state="running") & Q(active_token__isnull=True, lease_until__isnull=True))
            ), name="schedule_active_lease"),
        ]


class SlotLease(models.Model):
    token = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    slot = models.ForeignKey(ScheduledSlot, on_delete=models.PROTECT, related_name="leases")
    sequence = models.PositiveIntegerField()
    admitted_at = models.DateTimeField()
    deadline_at = models.DateTimeField()
    mode = models.CharField(max_length=8, choices=[("execute", "execute"), ("recover", "recover")])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("slot", "sequence"), name="schedule_lease_sequence"),
            models.CheckConstraint(condition=Q(sequence__gt=0), name="schedule_lease_positive"),
            models.CheckConstraint(condition=Q(deadline_at__gt=F("admitted_at")), name="schedule_lease_deadline"),
            models.CheckConstraint(condition=Q(mode__in=("execute", "recover")), name="schedule_lease_mode"),
        ]


class SlotOutcome(models.Model):
    lease = models.OneToOneField(SlotLease, primary_key=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=[(item, item) for item in ("completed", "failed", "unresolved", "blocked", "expired")])
    payload = models.JSONField()
    finished_at = models.DateTimeField()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(status__in=("completed", "failed", "unresolved", "blocked", "expired")), name="schedule_outcome_status")]


class AnalysisDispatch(models.Model):
    """Conservative durable dispatch boundary, not proof of remote admission."""

    slot = models.OneToOneField(ScheduledSlot, primary_key=True, on_delete=models.PROTECT)
    lease = models.OneToOneField(SlotLease, on_delete=models.PROTECT)
    request = models.JSONField()
    request_digest = models.CharField(max_length=64)
    started_at = models.DateTimeField()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(request_digest__regex=r"^[0-9a-f]{64}$"), name="schedule_dispatch_digest")]
