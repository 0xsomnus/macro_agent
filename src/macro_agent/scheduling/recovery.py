"""Explicit operator recovery, preserving the original job and every outcome.

Reconciliation reads a retained news command only. It cannot repeat an uncertain
model call. A retry is allowed only before a dispatch marker, or for deterministic
capture/review work. Neither action waives budgets, permissions or publication.
"""

from datetime import timedelta
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.monitoring.models import SourceState
from macro_agent.monitoring.news_context import allowed_source
from macro_agent.theses import service as theses

from . import service
from .models import AnalysisDispatch, ScheduledSlot, SlotLease, SlotOutcome, SlotRecovery, WatchVersion


def recovery_wire(row):
    return {"recovery_id": str(row.pk), "command_id": str(row.command_id),
        "slot_id": str(row.slot_id), "prior_token": str(row.prior_lease_id),
        "watch_version_id": str(row.watch_version_id), "action": row.action,
        "reason": row.reason, "created_at": row.created_at.isoformat(),
        "initial_lease_token": str(row.initial_lease_token), "request_digest": row.request_digest}


def _response(row, *, replayed):
    slot = ScheduledSlot.objects.get(pk=row.slot_id)
    lease = SlotLease.objects.get(pk=row.initial_lease_token)
    return {"recovery": recovery_wire(row), "lease": service._claim_wire(lease, slot),
            "current_slot_state": slot.state, "replayed": replayed}


def begin_recovery(actor_id, slot_id, command_id, expected_last_token,
                   expected_watch_revision, action, reason, *, clock=timezone.now):
    """Admit exactly one recovery lease against the inspected blocked outcome.

    Exact historical command replay is inert, including after permissions or
    configuration change. A new command must compare the last failed token and
    current reviewed watch revision while holding their governing locks.
    """
    service._own_transaction()
    for value, name in ((slot_id, "slot_id"), (command_id, "command_id"),
                        (expected_last_token, "expected_last_token")):
        theses._uuid(value, name)
    if type(expected_watch_revision) is not int or not 1 <= expected_watch_revision <= 2**63 - 1:
        raise ValueError("expected_watch_revision requires a positive integer")
    if action not in ("retry", "reconcile"):
        raise ValueError("Choose retry or reconcile")
    if type(reason) is not str or not reason.strip() or len(reason) > 2000 or "\x00" in reason:
        raise ValueError("Recovery requires an explicit reason of at most 2000 characters")
    try:
        reason.encode("utf-8")
    except UnicodeError:
        raise ValueError("Recovery reason requires valid text") from None
    request = {"slot_id": str(slot_id), "expected_last_token": str(expected_last_token),
        "expected_watch_revision": expected_watch_revision, "action": action, "reason": reason}
    digest = text_digest(canonical_json(request))
    theses._owner(actor_id)

    def saved():
        row = SlotRecovery.objects.filter(owner_id=actor_id, command_id=command_id).first()
        if row is not None and row.request_digest != digest:
            raise service.ScheduleConflict("Recovery command already belongs to another request")
        return row

    # Historical replay must not depend on a currently enabled source or key.
    previous = saved()
    if previous is not None:
        return _response(previous, replayed=True)
    hint = ScheduledSlot.objects.filter(pk=slot_id, owner_id=actor_id).select_related("watch", "watch_version").first()
    if hint is None:
        raise service.ScheduleUnavailable("Scheduled job unavailable")
    theses._record(actor_id, str(hint.thesis_id))
    candidate = WatchVersion.objects.get(pk=hint.watch.current_version_id)
    source_ids = sorted({entry["source_id"] for version in (hint.watch_version, candidate)
                         for entry in version.configuration["sources"]})
    with transaction.atomic():
        # All source/permission and governing writers use this protection order.
        sources = {row.pk: row for row in SourceState.objects.select_for_update()
                   .filter(pk__in=source_ids).order_by("pk")}
        thesis, watch = service._owner_thesis_watch(actor_id, str(hint.watch_id))
        slot = ScheduledSlot.objects.select_for_update().get(pk=slot_id, owner_id=actor_id)
        previous = saved()
        if previous is not None:
            return _response(previous, replayed=True)
        if watch.revision != expected_watch_revision or watch.current_version_id != candidate.pk:
            raise service.ScheduleConflict("Watch revision changed; inspect before recovery")
        prior = SlotLease.objects.filter(slot=slot, sequence=slot.attempt_count).first()
        outcome = SlotOutcome.objects.filter(lease=prior).first() if prior else None
        if (slot.state != "blocked" or slot.active_token is not None or prior is None
                or str(prior.pk) != str(expected_last_token) or outcome is None
                or outcome.status not in ("failed", "blocked", "unresolved")):
            raise service.ScheduleConflict("Job no longer has the inspected blocked outcome")
        at = service._now(clock, thesis.changed_at, watch.changed_at, outcome.finished_at)
        marker = AnalysisDispatch.objects.filter(slot=slot).first()
        if action == "reconcile":
            if slot.kind != "analysis" or marker is None:
                raise service.ScheduleConflict("Reconcile requires an existing analysis dispatch")
        elif marker is not None:
            raise service.ScheduleConflict("Model dispatch already started; only read-only reconciliation is allowed")
        config = candidate.configuration
        if slot.kind == "daily_review":
            if config["sources"] != slot.watch_version.configuration["sources"]:
                raise service.ScheduleConflict("Daily recovery cannot change its original source manifest")
            if ScheduledSlot.objects.filter(watch=watch, kind="daily_review",
                    local_date__lt=slot.local_date).exclude(state="completed").exists():
                raise service.ScheduleConflict("An older daily interval must finish first")
        from macro_agent.desk.models import DailyReview
        retained_daily = slot.kind == "daily_review" and DailyReview.objects.filter(
            owner_id=actor_id, thesis_id=slot.thesis_id, command_id=slot.command_id).exists()
        if action == "retry" and not retained_daily:
            for entry in config["sources"]:
                source = sources.get(entry["source_id"])
                if source is None or source.contract_digest != entry["contract_digest"] or not allowed_source(source):
                    raise service.ScheduleUnavailable("Selected source contract unavailable for retry")
            if slot.kind == "analysis" and ScheduledSlot.objects.filter(watch=watch, kind="analysis",
                    state="running", lease_until__gt=at).count() >= config["allowances"]["inflight_slots"]:
                raise service.AnalysisAllowanceExhausted("Analysis inflight allowance exhausted; no recovery lease admitted")
        token = uuid4()
        row = SlotRecovery.objects.create(owner_id=actor_id, command_id=command_id,
            slot=slot, prior_lease=prior, watch_version=candidate, action=action, reason=reason,
            created_at=at, request_digest=digest, initial_lease_token=token)
        lease = SlotLease.objects.create(token=token, slot=slot, recovery=row,
            sequence=slot.attempt_count + 1, admitted_at=at,
            deadline_at=at + timedelta(seconds=config["lease_seconds"]),
            mode="recover" if marker else "execute")
        slot.state, slot.active_token, slot.lease_until = "running", lease.pk, lease.deadline_at
        slot.attempt_count = lease.sequence
        slot.save(update_fields=("state", "active_token", "lease_until", "attempt_count"))
        watch.changed_at = at
        watch.save(update_fields=("changed_at",))
        return _response(row, replayed=False)
