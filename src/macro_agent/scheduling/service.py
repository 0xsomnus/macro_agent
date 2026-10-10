"""Short owner-scoped scheduling transactions, separate from task execution.

Protection order is owner, thesis, watch, then slot. No transport or model call
belongs here. Effective timestamps are sampled after protection and are not
claims of exact database commit time. A dispatch marker bars automatic paid
retry even if a crash happened before actual provider admission.
"""

from contextlib import contextmanager
from datetime import date, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.domain.time import as_utc
from macro_agent.monitoring.gates import require_local_proof
from macro_agent.monitoring.models import SourceState
from macro_agent.monitoring.news_context import allowed_source
from macro_agent.persistence.context_binding import book_digest
from macro_agent.positions.representation import exposure_book
from macro_agent.theses import service as theses

from .configuration import configuration as validate_configuration, json_object
from .models import AnalysisDispatch, KINDS, ScheduledSlot, SlotLease, SlotOutcome, WatchRecord, WatchVersion
from .configuration import scheduled_at


class ScheduleUnavailable(PermissionError):
    pass


class ScheduleConflict(ValueError):
    pass


class ScheduleFenced(ScheduleConflict):
    pass


class InferenceAlreadyStarted(ScheduleConflict):
    pass


def gate():
    require_local_proof()
    if not getattr(settings, "MACRO_ENABLE_CONTINUOUS_DESK", False):
        raise ScheduleUnavailable("Internal desk scheduling requires MACRO_ENABLE_CONTINUOUS_DESK=1")


def _own_transaction():
    gate()
    if connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("Scheduling operations require their own transaction")


def _now(clock, *floor):
    at = as_utc(clock())
    if any(item is not None and at < item for item in floor):
        raise ScheduleConflict("Trusted clock precedes protected scheduling state")
    return at


def _watch(actor_id, watch_id, *, lock=False):
    theses._uuid(watch_id, "watch_id")
    rows = WatchRecord.objects.filter(owner_id=actor_id)
    if lock:
        rows = rows.select_for_update()
    row = rows.filter(pk=watch_id).first()
    if row is None:
        raise ScheduleUnavailable("Watch unavailable")
    return row


def _owner_thesis_watch(actor_id, watch_id):
    hint = _watch(actor_id, watch_id)
    theses._owner(actor_id, lock=True)
    thesis = theses._record(actor_id, str(hint.thesis_id), lock=True)
    return thesis, _watch(actor_id, watch_id, lock=True)


def _watch_wire(watch):
    version = WatchVersion.objects.get(pk=watch.current_version_id)
    return {"watch_id": str(watch.pk), "owner_id": str(watch.owner_id), "thesis_id": str(watch.thesis_id),
        "revision": watch.revision, "watch_version_id": str(version.pk), "configuration": version.configuration,
        "configuration_digest": version.configuration_digest, "changed_at": watch.changed_at.isoformat(),
        "next_capture_at": watch.next_capture_at.isoformat(), "next_analysis_at": watch.next_analysis_at.isoformat(),
        "next_daily_date": watch.next_daily_date.isoformat()}


def _slot_wire(slot):
    return {"slot_id": str(slot.pk), "command_id": str(slot.command_id), "watch_id": str(slot.watch_id),
        "watch_version_id": str(slot.watch_version_id), "owner_id": str(slot.owner_id), "thesis_id": str(slot.thesis_id),
        "kind": slot.kind, "intended_at": slot.intended_at.isoformat(), "created_at": slot.created_at.isoformat(),
        "period_start": slot.period_start.isoformat() if slot.period_start else None,
        "cutoff": slot.cutoff.isoformat() if slot.cutoff else None,
        "local_date": slot.local_date.isoformat() if slot.local_date else None,
        "late": slot.late, "coalesced_intervals": slot.coalesced_intervals, "state": slot.state,
        "attempt_count": slot.attempt_count, "configuration": slot.watch_version.configuration}


def configure_watch(actor_id, thesis_id, command_id, expected_revision, configuration, *, clock=timezone.now):
    """Save an explicit version. Revision zero creates; historical replay is inert."""
    _own_transaction()
    config = validate_configuration(configuration)
    theses._uuid(command_id, "command_id")
    if type(expected_revision) is not int or not 0 <= expected_revision <= 2**63 - 1:
        raise ValueError("expected_revision requires a nonnegative integer")
    digest = text_digest(canonical_json(config))
    # Avoid disclosing source-state details to an unavailable private actor.
    theses._owner(actor_id)
    theses._record(actor_id, thesis_id)
    with transaction.atomic():
        # Configuration writes follow the same source -> owner -> thesis
        # ordering used by source/permission and analytical admission writers.
        for entry in sorted(config["sources"], key=lambda item: item["source_id"]):
            source = SourceState.objects.select_for_update().filter(pk=entry["source_id"]).first()
            if source is None or source.contract_digest != entry["contract_digest"] or not allowed_source(source):
                raise ScheduleUnavailable("Selected source contract unavailable for internal use")
        theses._owner(actor_id, lock=True)
        thesis = theses._record(actor_id, thesis_id, lock=True)
        saved = WatchVersion.objects.filter(owner_id=actor_id, command_id=command_id).first()
        if saved is not None:
            if saved.watch.thesis_id != thesis.pk or saved.configuration_digest != digest or saved.sequence != expected_revision + 1:
                raise ScheduleConflict("Configuration command already belongs to a different request")
            response = _watch_wire(saved.watch)
            response.update(replayed=True, original_watch_version_id=str(saved.pk))
            return response
        watch = WatchRecord.objects.select_for_update().filter(owner_id=actor_id, thesis=thesis).first()
        if (watch.revision if watch else 0) != expected_revision:
            raise ScheduleConflict("Watch revision changed; inspect configuration before amendment")
        at = _now(clock, thesis.changed_at, watch.changed_at if watch else None)
        if thesis.current_approval_id is None or str(thesis.current_approval_id) != config["approval_id"]:
            raise ScheduleConflict("Configuration must pin the current approved thesis")
        if book_digest(exposure_book(str(thesis.pk))) != config["exposure_digest"]:
            raise ScheduleConflict("Configuration must pin the complete current attached exposure")
        if watch is None:
            watch = WatchRecord.objects.create(owner_id=actor_id, thesis=thesis, revision=0,
                changed_at=at, next_capture_at=at, next_analysis_at=at,
                next_daily_date=date.fromisoformat(config["daily_start_date"]))
        elif WatchVersion.objects.get(pk=watch.current_version_id).configuration["daily_start_date"] != config["daily_start_date"]:
            raise ScheduleConflict("daily_start_date cannot rewrite existing scheduling history")
        version = WatchVersion.objects.create(watch=watch, owner_id=actor_id, command_id=command_id,
            sequence=watch.revision + 1, configuration=config, configuration_digest=digest, created_at=at)
        watch.current_version = version
        watch.revision = version.sequence
        watch.changed_at = at
        watch.save(update_fields=("current_version", "revision", "changed_at"))
        response = _watch_wire(watch)
        response.update(replayed=False, original_watch_version_id=str(version.pk))
        return response


def enqueue_due(actor_id, watch_id, *, kind=None, clock=timezone.now):
    """Coalesce overdue periodic polls, never daily dates or implied coverage.

    Daily overflow is returned explicitly and its cursor stays unchanged.
    Periodic capture/analysis enqueue independently of that daily backlog.
    """
    _own_transaction()
    if kind is not None and kind not in KINDS:
        raise ValueError("Unknown scheduling kind")
    with transaction.atomic():
        thesis, watch = _owner_thesis_watch(actor_id, watch_id)
        at = _now(clock, thesis.changed_at, watch.changed_at)
        version = WatchVersion.objects.get(pk=watch.current_version_id)
        config = version.configuration
        created = []
        for periodic in ("capture", "analysis"):
            if kind is not None and periodic != kind:
                continue
            field = f"next_{periodic}_at"
            intended = getattr(watch, field)
            if intended > at:
                continue
            interval = config[f"{periodic}_interval_seconds"]
            elapsed = (at - intended) // timedelta(seconds=interval)
            slot = ScheduledSlot.objects.create(owner_id=actor_id, thesis=thesis, watch=watch,
                watch_version=version, kind=periodic, identity_key=f"{periodic}:{intended.isoformat()}",
                intended_at=intended, created_at=at, late=at > intended, coalesced_intervals=elapsed)
            created.append(_slot_wire(slot))
            setattr(watch, field, intended + timedelta(seconds=(elapsed + 1) * interval))
        backlog = None
        if kind is None or kind == "daily_review":
            today = at.astimezone(ZoneInfo(config["timezone"])).date()
            if watch.next_daily_date <= today:
                last_due = today if scheduled_at(today, config) <= at else today - timedelta(days=1)
                due_count = max(0, (last_due - watch.next_daily_date).days + 1)
                if due_count > config["daily_backlog_limit"]:
                    backlog = {"status": "overflow", "due_dates": due_count, "limit": config["daily_backlog_limit"],
                        "first_date": watch.next_daily_date.isoformat(), "last_date": last_due.isoformat(),
                        "detail": "No daily date was skipped or admitted; review the explicit backlog bound."}
                else:
                    for _ in range(due_count):
                        day = watch.next_daily_date
                        intended = scheduled_at(day, config)
                        previous = ScheduledSlot.objects.filter(owner_id=actor_id, thesis=thesis, kind="daily_review").order_by("-local_date").first()
                        start = previous.cutoff if previous else scheduled_at(day - timedelta(days=1), config)
                        if start >= intended:
                            raise ScheduleConflict("Changed schedule creates a non-increasing daily interval")
                        slot = ScheduledSlot.objects.create(owner_id=actor_id, thesis=thesis, watch=watch,
                            watch_version=version, kind="daily_review", identity_key=f"daily_review:{day.isoformat()}",
                            local_date=day, period_start=start, cutoff=intended, intended_at=intended,
                            created_at=at, late=at > intended, coalesced_intervals=0)
                        created.append(_slot_wire(slot))
                        watch.next_daily_date = day + timedelta(days=1)
        watch.changed_at = at
        watch.save(update_fields=("next_capture_at", "next_analysis_at", "next_daily_date", "changed_at"))
        return {"watch_id": str(watch.pk), "slots": created, "daily_backlog": backlog}


def _claim_wire(lease, slot):
    marker = AnalysisDispatch.objects.filter(slot=slot).first()
    return {**_slot_wire(slot), "token": str(lease.pk), "lease_deadline": lease.deadline_at.isoformat(),
        "mode": lease.mode, "analysis_request": marker.request if marker else None}


def claim_due(actor_id, kind, *, watch_id=None, clock=timezone.now):
    """Lease only this owner's due work; skip locked aggregates without waiting.

    Daily work is strictly oldest-uncompleted first per watch. A live older
    lease or blocked earlier daily slot bars newer daily work for that watch.
    """
    _own_transaction()
    theses._uuid(actor_id, "actor_id")
    if kind not in KINDS:
        raise ValueError("Unknown scheduling kind")
    if watch_id is not None:
        theses._uuid(watch_id, "watch_id")
    rows = ScheduledSlot.objects.filter(owner_id=actor_id, kind=kind).exclude(state="completed")
    if kind != "daily_review":
        rows = rows.exclude(state="blocked")
    if watch_id is not None:
        rows = rows.filter(watch_id=watch_id)
    candidates = rows.order_by("intended_at", "pk").values_list("pk", "watch_id", "thesis_id")
    unavailable = set()
    for slot_id, candidate_watch_id, thesis_id in candidates.iterator(chunk_size=100):
        if candidate_watch_id in unavailable:
            continue
        with transaction.atomic():
            owner = get_user_model().objects.select_for_update(skip_locked=True).filter(pk=actor_id, is_active=True).first()
            if owner is None:
                return None
            thesis = theses.ThesisRecord.objects.select_for_update(skip_locked=True).filter(pk=thesis_id, owner_id=actor_id).first()
            if thesis is None:
                unavailable.add(candidate_watch_id)
                continue
            watch = WatchRecord.objects.select_for_update(skip_locked=True).filter(pk=candidate_watch_id, owner_id=actor_id).first()
            if watch is None:
                unavailable.add(candidate_watch_id)
                continue
            slot = ScheduledSlot.objects.select_for_update(skip_locked=True).filter(pk=slot_id, owner_id=actor_id).first()
            if slot is None:
                unavailable.add(candidate_watch_id)
                continue
            at = _now(clock, thesis.changed_at, watch.changed_at, slot.created_at)
            if slot.state == "blocked" or (slot.state == "running" and slot.lease_until > at):
                if kind == "daily_review":
                    unavailable.add(candidate_watch_id)
                continue
            if slot.state not in ("pending", "running") or slot.intended_at > at:
                continue
            if kind == "daily_review" and ScheduledSlot.objects.filter(watch=watch, kind=kind,
                    local_date__lt=slot.local_date).exclude(state="completed").exists():
                unavailable.add(candidate_watch_id)
                continue
            config = slot.watch_version.configuration
            marker = AnalysisDispatch.objects.filter(slot=slot).first()
            if kind == "analysis" and marker is None:
                active = ScheduledSlot.objects.filter(watch=watch, kind=kind, state="running", lease_until__gt=at).count()
                if active >= config["allowances"]["inflight_slots"]:
                    unavailable.add(candidate_watch_id)
                    continue
            if slot.state == "running":
                old = SlotLease.objects.get(pk=slot.active_token)
                if at < old.admitted_at:
                    raise ScheduleConflict("Trusted clock precedes the active lease")
                SlotOutcome.objects.create(lease=old, status="expired", finished_at=at,
                    payload={"reason": "lease_expired", "paid_retry_authorized": False,
                             "dispatch_started": marker is not None})
            lease = SlotLease.objects.create(slot=slot, sequence=slot.attempt_count + 1,
                admitted_at=at, deadline_at=at + timedelta(seconds=config["lease_seconds"]),
                mode="recover" if marker else "execute")
            slot.state, slot.active_token, slot.lease_until = "running", lease.pk, lease.deadline_at
            slot.attempt_count = lease.sequence
            slot.save(update_fields=("state", "active_token", "lease_until", "attempt_count"))
            watch.changed_at = at
            watch.save(update_fields=("changed_at",))
            return _claim_wire(lease, slot)
    return None


def _protected_lease(actor_id, token, clock):
    theses._uuid(token, "token")
    hint = SlotLease.objects.filter(pk=token, slot__owner_id=actor_id).select_related("slot").first()
    if hint is None:
        raise ScheduleUnavailable("Slot lease unavailable")
    thesis, watch = _owner_thesis_watch(actor_id, str(hint.slot.watch_id))
    slot = ScheduledSlot.objects.select_for_update().get(pk=hint.slot_id, owner_id=actor_id)
    at = _now(clock, thesis.changed_at, watch.changed_at, slot.created_at, hint.admitted_at)
    return hint, slot, thesis, watch, at


def _active(lease, slot, at):
    if slot.state != "running" or slot.active_token != lease.pk or at >= lease.deadline_at:
        raise ScheduleFenced("Slot lease expired, was replaced or completed")


def mark_analysis_started(actor_id, token, request, *, clock=timezone.now):
    """Commit a conservative paid-dispatch boundary before leaving the process.

    This is not inference admission or billing evidence. Once present, a
    recovered lease may only inspect the saved command, never resend it.
    """
    _own_transaction()
    request = json_object(request, "analysis dispatch request")
    fields = {"source_id", "expected_approval_id", "expected_exposure_digest", "provider", "model_id", "model_configuration"}
    if set(request) != fields:
        raise ValueError("Dispatch requires exactly its documented pinned request fields")
    with transaction.atomic():
        lease, slot, thesis, watch, at = _protected_lease(actor_id, token, clock)
        _active(lease, slot, at)
        if slot.kind != "analysis":
            raise ScheduleConflict("Only analysis slots may record a model dispatch")
        if AnalysisDispatch.objects.filter(slot=slot).exists():
            raise InferenceAlreadyStarted("Dispatch already started; use read-only command recovery")
        config = slot.watch_version.configuration
        if (request["source_id"] not in {item["source_id"] for item in config["sources"]}
                or request["expected_approval_id"] != config["approval_id"]
                or request["expected_exposure_digest"] != config["exposure_digest"]
                or any(request[key] != config[key] for key in ("provider", "model_id", "model_configuration"))):
            raise ScheduleConflict("Dispatch does not match its admitted watch configuration")
        if (str(thesis.current_approval_id) != config["approval_id"]
                or book_digest(exposure_book(str(thesis.pk))) != config["exposure_digest"]):
            raise ScheduleConflict("Approved meaning or complete paper exposure changed; review the watch")
        allowance = config["allowances"]
        dispatches = AnalysisDispatch.objects.filter(slot__watch=watch,
            started_at__gt=at - timedelta(seconds=allowance["window_seconds"])).count()
        failed = SlotOutcome.objects.filter(lease__slot__watch=watch, lease__slot__kind="analysis",
            lease__slot__analysisdispatch__isnull=False,
            status__in=("failed", "unresolved", "blocked")).values_list("lease__slot_id", flat=True)
        uncertain = (AnalysisDispatch.objects.filter(slot__watch=watch, lease__deadline_at__lte=at)
            .exclude(slot__state="completed").values_list("slot_id", flat=True))
        unresolved = ScheduledSlot.objects.filter(watch=watch, kind="analysis").filter(
            Q(pk__in=failed) | Q(pk__in=uncertain)).count()
        if dispatches >= allowance["analysis_dispatches"] or unresolved >= allowance["unresolved_slots"]:
            raise ScheduleConflict("Additional per-watch analysis allowance exhausted; no dispatch admitted")
        marker = AnalysisDispatch.objects.create(slot=slot, lease=lease, request=request,
            request_digest=text_digest(canonical_json(request)), started_at=at)
        watch.changed_at = at
        watch.save(update_fields=("changed_at",))
        return {"slot_id": str(slot.pk), "command_id": str(slot.command_id), "mode": "execute",
            "analysis_request": marker.request, "started_at": at.isoformat(),
            "limitation": "Dispatch intent is not proof of model admission, cancellation or billing."}


def complete_slot(actor_id, token, status, payload, *, clock=timezone.now):
    _own_transaction()
    if status not in ("completed", "failed", "unresolved", "blocked"):
        raise ValueError("Completion requires an explicit terminal outcome")
    payload = json_object(payload, "slot outcome")
    with transaction.atomic():
        lease, slot, thesis, watch, at = _protected_lease(actor_id, token, clock)
        existing = SlotOutcome.objects.filter(lease=lease).first()
        if existing is not None:
            if existing.status == "expired":
                raise ScheduleFenced("Expired lease has retained history and cannot complete")
            if existing.status != status or existing.payload != payload:
                raise ScheduleConflict("Completed lease already has a different retained outcome")
            return {"token": str(lease.pk), "slot_id": str(slot.pk), "status": existing.status,
                "payload": existing.payload, "finished_at": existing.finished_at.isoformat(),
                "current_slot_state": slot.state, "replayed": True}
        _active(lease, slot, at)
        outcome = SlotOutcome.objects.create(lease=lease, status=status, payload=payload, finished_at=at)
        slot.state = "completed" if status == "completed" else "blocked"
        slot.active_token = slot.lease_until = None
        slot.save(update_fields=("state", "active_token", "lease_until"))
        watch.changed_at = at
        watch.save(update_fields=("changed_at",))
        return {"token": str(lease.pk), "slot_id": str(slot.pk), "status": outcome.status,
            "payload": outcome.payload, "finished_at": at.isoformat(), "current_slot_state": slot.state, "replayed": False}


@contextmanager
def _readonly():
    _own_transaction()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        yield


def _current_watch(actor_id, watch_id):
    theses._owner(actor_id)
    watch = _watch(actor_id, watch_id)
    return watch, _watch_wire(watch)


def current_watch(actor_id, watch_id):
    """Read only the current configuration/cursors, without historical scans."""
    with _readonly():
        return _current_watch(actor_id, watch_id)[1]


def inspect_watch(actor_id, watch_id):
    """Inspect retained state without enqueuing, expiring leases or model calls."""
    with _readonly():
        watch, current = _current_watch(actor_id, watch_id)
        slots = []
        for slot in watch.slots.select_related("watch_version").order_by("intended_at", "pk"):
            row = _slot_wire(slot)
            row["leases"] = []
            for lease in slot.leases.order_by("sequence"):
                outcome = SlotOutcome.objects.filter(lease=lease).first()
                row["leases"].append({"token": str(lease.pk), "sequence": lease.sequence, "mode": lease.mode,
                    "admitted_at": lease.admitted_at.isoformat(), "deadline_at": lease.deadline_at.isoformat(),
                    "outcome": {"status": outcome.status, "payload": outcome.payload,
                                "finished_at": outcome.finished_at.isoformat()} if outcome else None})
            marker = AnalysisDispatch.objects.filter(slot=slot).first()
            row["analysis_request"] = marker.request if marker else None
            slots.append(row)
        return {**current, "slots": slots,
            "limitations": ["Inspection does not expire leases or authorize paid retries.",
                "Intended times and protected observations do not measure exact durable commit times.",
                "Periodic coalescing records missed poll intervals, not source coverage."]}
