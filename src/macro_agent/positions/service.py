"""Owner-scoped manual paper positions with explicit approval/version guards.

Lock order: account, thesis, existing position, sorted bound briefs. Every
accepted exposure change invalidates affected publication state in the same
transaction. Model/network calls never belong in these short operations.
"""

from dataclasses import replace
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone

from macro_agent.domain.exposure import (
    DECLARATION_FIELDS, PaperPositionVersion, validate_position_transition,
)
from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.domain.time import as_utc
from macro_agent.persistence.publication_store import canonical_actor
from macro_agent.theses.models import ThesisRecord

from .models import AuditTransition, CommandReceipt, PositionRecord, PositionVersion
from .representation import detail_wire, exposure_book, record_version, version_wire


class PositionUnavailable(PermissionError):
    pass


class PositionConflict(ValueError):
    pass


HISTORY_LIMIT = 100
MAX_POSITION_RECORDS = 200


def _uuid(value, name):
    if type(value) is not str:
        raise TypeError(f"{name} must be a canonical UUID string")
    return canonical_actor(value)


def _revision(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError("expected_revision must be a positive integer")
    return value


def _declaration(value):
    if type(value) is not dict or set(value) != set(DECLARATION_FIELDS):
        raise ValueError("position must contain exactly the declaration fields")
    return dict(value)


def _owner(actor_id, *, lock=False):
    _uuid(actor_id, "actor_id")
    rows = get_user_model().objects
    if lock:
        rows = rows.select_for_update()
    owner = rows.filter(pk=actor_id, is_active=True).first()
    if owner is None:
        raise PositionUnavailable("position unavailable")
    return owner


def _thesis(actor_id, thesis_id, *, lock=False):
    _uuid(thesis_id, "thesis_id")
    rows = ThesisRecord.objects.filter(pk=thesis_id, owner_id=actor_id)
    if lock:
        rows = rows.select_for_update()
    row = rows.first()
    if row is None:
        raise PositionUnavailable("position unavailable")
    return row


def _position(actor_id, position_id, *, lock=False):
    _uuid(position_id, "position_id")
    rows = PositionRecord.objects.filter(pk=position_id, owner_id=actor_id)
    rows = rows.select_for_update() if lock else rows.select_related("current_version")
    row = rows.first()
    if row is None:
        raise PositionUnavailable("position unavailable")
    return row


def _approval(thesis, expected_approval_id):
    _uuid(expected_approval_id, "expected_approval_id")
    if thesis.current_approval_id is None or str(thesis.current_approval_id) != expected_approval_id:
        raise PositionConflict("review the current approved thesis before changing exposure")


def _clock(clock, thesis, position=None):
    from macro_agent.persistence.context_binding import lock_thesis_briefs
    briefs = lock_thesis_briefs(thesis)
    at = as_utc(clock())
    floor = max(thesis.changed_at, position.changed_at) if position is not None else thesis.changed_at
    if at < floor or any(at < brief.changed_at for brief in briefs):
        raise PositionConflict("trusted clock precedes current reviewed state")
    return at


def _digest(kind, target, body):
    return text_digest(canonical_json({"kind": kind, "target": target, "body": body}))


def _receipt(actor_id, command_id, digest):
    row = CommandReceipt.objects.filter(owner_id=actor_id, command_id=command_id).first()
    if row is not None and row.request_digest != digest:
        raise PositionConflict("command_id already belongs to a different request")
    return row


def _response(position, receipt, *, replayed):
    return {
        "command": {
            "command_id": str(receipt.command_id), "kind": receipt.kind,
            "replayed": replayed, "result": receipt.result,
            "is_current_version": str(position.current_version_id) == receipt.result["version_id"],
        },
        "position": detail_wire(position),
    }


def _save_version(position, value):
    if value.position_id != str(position.pk) or value.thesis_id != str(position.thesis_id):
        raise ValueError("position version belongs to another aggregate")
    position.current_version = PositionVersion.objects.create(
        id=value.version_id, position=position, owner_id=value.owner_id,
        thesis_id=value.thesis_id, reviewed_approval_id=value.approval_id,
        parent_id=value.parent_version_id, accepted_at=value.accepted_at,
        paper=True, status=value.status, mapping_status=value.mapping_status,
        digest=value.digest, **value.declaration_dict,
    )
    position.revision += 1
    position.changed_at = value.accepted_at
    position.save(update_fields=("current_version", "revision", "changed_at"))


def _save_command(thesis, position, command_id, kind, digest, at):
    # Import lazily to keep the declaration/representation dependency acyclic.
    from macro_agent.persistence.context_binding import invalidate_thesis_briefs

    affected = invalidate_thesis_briefs(thesis, at, "exposure:" + kind)
    result = {"position_id": str(position.pk), "version_id": str(position.current_version_id),
              "revision": position.revision, "accepted_at": at.isoformat()}
    AuditTransition.objects.create(thesis=thesis, position=position, kind=kind, at=at, detail={
        **result, "actor_id": str(position.owner_id), "command_id": command_id,
        "reviewed_approval_id": str(position.current_version.reviewed_approval_id),
        "version_digest": position.current_version.digest, "invalidated_briefs": affected,
    })
    receipt = CommandReceipt.objects.create(
        owner_id=position.owner_id, thesis=thesis, position=position, command_id=command_id,
        kind=kind, request_digest=digest, result=result, saved_at=at,
    )
    return _response(position, receipt, replayed=False)


def create_position(actor_id, thesis_id, command_id, expected_approval_id, position,
                    *, clock=timezone.now):
    _uuid(command_id, "command_id")
    _uuid(thesis_id, "thesis_id")
    _uuid(expected_approval_id, "expected_approval_id")
    declaration = _declaration(position)
    digest = _digest("create", thesis_id, {
        "expected_approval_id": expected_approval_id, "position": declaration,
    })
    with transaction.atomic():
        owner = _owner(actor_id, lock=True)
        thesis = _thesis(actor_id, thesis_id, lock=True)
        receipt = _receipt(actor_id, command_id, digest)
        if receipt is not None:
            row = _position(actor_id, str(receipt.position_id), lock=True)
            return _response(row, receipt, replayed=True)
        _approval(thesis, expected_approval_id)
        if PositionRecord.objects.filter(thesis=thesis).count() >= MAX_POSITION_RECORDS:
            raise PositionConflict("internal paper-position record limit reached")
        at, position_id = _clock(clock, thesis), str(uuid4())
        value = PaperPositionVersion(
            version_id=str(uuid4()), position_id=position_id, owner_id=actor_id,
            thesis_id=thesis_id, approval_id=expected_approval_id, accepted_at=at,
            **declaration,
        )
        row = PositionRecord.objects.create(
            id=position_id, owner=owner, thesis=thesis,
            original_approval_id=expected_approval_id, created_at=at, changed_at=at,
        )
        _save_version(row, value)
        return _save_command(thesis, row, command_id, "create", digest, at)


def _change(actor_id, position_id, command_id, expected_revision, expected_approval_id,
            declaration, kind, clock):
    _uuid(command_id, "command_id")
    _uuid(position_id, "position_id")
    _uuid(expected_approval_id, "expected_approval_id")
    revision = _revision(expected_revision)
    body = {"expected_revision": revision, "expected_approval_id": expected_approval_id}
    if kind == "revise":
        body["position"] = _declaration(declaration)
    digest = _digest(kind, position_id, body)
    # The aggregate's owner and thesis are stable database-guarded identities.
    hint = _position(actor_id, position_id)
    with transaction.atomic():
        _owner(actor_id, lock=True)
        thesis = _thesis(actor_id, str(hint.thesis_id), lock=True)
        row = _position(actor_id, position_id, lock=True)
        receipt = _receipt(actor_id, command_id, digest)
        if receipt is not None:
            return _response(row, receipt, replayed=True)
        _approval(thesis, expected_approval_id)
        if row.revision != revision:
            raise PositionConflict("paper-position revision changed; review current exposure")
        previous = record_version(row.current_version)
        if previous.status == "closed":
            raise PositionConflict("a closed paper position cannot be revised or reopened")
        at = _clock(clock, thesis, row)
        value = replace(
            previous, version_id=str(uuid4()), parent_version_id=previous.version_id,
            approval_id=expected_approval_id, accepted_at=at,
            status="closed" if kind == "close" else "open",
            **(body["position"] if kind == "revise" else {}),
        )
        validate_position_transition(previous, value)
        _save_version(row, value)
        return _save_command(thesis, row, command_id, kind, digest, at)


def revise_position(actor_id, position_id, command_id, expected_revision,
                    expected_approval_id, position, *, clock=timezone.now):
    return _change(actor_id, position_id, command_id, expected_revision,
                   expected_approval_id, position, "revise", clock)


def close_position(actor_id, position_id, command_id, expected_revision,
                   expected_approval_id, *, clock=timezone.now):
    return _change(actor_id, position_id, command_id, expected_revision,
                   expected_approval_id, None, "close", clock)


def get_position(actor_id, position_id):
    _owner(actor_id)
    return detail_wire(_position(actor_id, position_id))


def list_positions(actor_id, thesis_id, limit=20, offset=0):
    _owner(actor_id)
    _thesis(actor_id, thesis_id)
    if (type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int
            or not 0 <= offset <= 1_000_000):
        raise ValueError("invalid pagination")
    rows = list(PositionRecord.objects.filter(owner_id=actor_id, thesis_id=thesis_id)
                .select_related("current_version").order_by("created_at", "id")
                [offset:offset + limit + 1])
    return {"positions": [detail_wire(row) for row in rows[:limit]], "limit": limit,
            "offset": offset, "has_more": len(rows) > limit}


def position_history(actor_id, position_id):
    if connection.vendor != "postgresql" or connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("position history requires its own PostgreSQL read-only snapshot")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        _owner(actor_id)
        row = _position(actor_id, position_id)
        audit = list(row.audit_transitions.order_by("sequence")[:HISTORY_LIMIT + 1])
        # Effective clocks can tie. Accepted audit order, rather than a random
        # version UUID, preserves the actual parent/child transition sequence.
        version_ids = [item.detail["version_id"] for item in audit[:HISTORY_LIMIT]]
        versions = {str(item.pk): item for item in row.versions.filter(pk__in=version_ids)}
        if set(version_ids) != set(versions):
            raise RuntimeError("paper-position audit references unavailable history")
        omitted_versions = row.versions.exclude(pk__in=version_ids).exists()
        return {
            "position": detail_wire(row),
            "versions": [version_wire(versions[version_id]) for version_id in version_ids],
            "audit": [{"sequence": item.sequence, "kind": item.kind,
                       "at": item.at.isoformat(), "detail": item.detail}
                      for item in audit[:HISTORY_LIMIT]],
            "history_limit": HISTORY_LIMIT,
            "truncated": omitted_versions or len(audit) > HISTORY_LIMIT,
            "replay_scope": "position_effective_time_history",
        }
