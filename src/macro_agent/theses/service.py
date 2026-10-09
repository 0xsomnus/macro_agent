"""Short, owner-scoped commands for exact thesis drafts and user approval.

Lock order is owner account, then thesis aggregate, then fresh immutable reads.
The owner lock serializes command identities, including the first create. No
model or external call belongs in these transactions. Times are effective
command times sampled under protection, not measured PostgreSQL commit times.
Bound synthetic briefs are invalidated atomically when approval changes; their
committed inputs require a separate observed-availability admission.
"""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone

from macro_agent.domain.models import (
    CompiledThesisVersion, UserThesisVersion, canonical_json, require_digest,
    require_text, text_digest,
)
from macro_agent.domain.thesis import ApprovalRequest, approve_thesis as approve_exact
from macro_agent.domain.time import as_utc

from .models import (
    ApprovalRecord, AuditTransition, CommandReceipt, InterpretationRecord,
    TextVersionRecord, ThesisRecord,
)


class ThesisUnavailable(PermissionError):
    """Missing and foreign resources deliberately share one boundary response."""


class ThesisConflict(ValueError):
    """Displayed state or command identity has changed; a fresh review is needed."""


Clock = Callable[[], datetime]
TEXT_LIMIT = 20_000
MEANING_LIMIT = 1_000
ARRAY_LIMIT = 32
HISTORY_LIMIT = 100
RELATED = (
    "latest_text", "latest_interpretation", "current_approval",
    "current_approval__text_version", "current_approval__interpretation",
)


def _uuid(value: str, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a canonical UUID string")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{name} must be a canonical UUID string") from error
    if str(parsed) != value:
        raise ValueError(f"{name} must be a canonical UUID string")
    return value


def _text(value: str, name: str, limit: int) -> str:
    require_text(value, name)
    if len(value) > limit or "\x00" in value:
        raise ValueError(f"{name} exceeds its limit or contains NUL")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{name} must contain valid Unicode") from error
    return value


def _meaning(value: dict) -> dict:
    if type(value) is not dict or set(value) != {"drivers", "horizon", "invalidation_signposts"}:
        raise ValueError("interpretation requires only drivers, horizon and invalidation_signposts")
    result = {}
    for key in ("drivers", "invalidation_signposts"):
        items = value[key]
        if type(items) is not list or len(items) > ARRAY_LIMIT:
            raise ValueError(f"{key} must be a bounded list of strings")
        result[key] = [_text(item, key, MEANING_LIMIT) for item in items]
    if len(set(result["drivers"])) != len(result["drivers"]):
        raise ValueError("drivers cannot contain duplicates")
    result["horizon"] = None if value["horizon"] is None else _text(value["horizon"], "horizon", MEANING_LIMIT)
    return result


def _revision(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError("expected_revision must be a positive integer")
    return value


def _owner(actor_id: str, *, lock: bool = False):
    _uuid(actor_id, "actor_id")
    owners = get_user_model().objects
    if lock:
        owners = owners.select_for_update()
    try:
        return owners.get(pk=actor_id, is_active=True)
    except get_user_model().DoesNotExist as error:
        raise ThesisUnavailable("thesis unavailable") from error


def _record(actor_id: str, thesis_id: str, *, lock: bool = False) -> ThesisRecord:
    _uuid(thesis_id, "thesis_id")
    rows = ThesisRecord.objects.filter(owner_id=actor_id)
    # Read immutable joins only after acquiring the aggregate lock. A joined
    # SELECT FOR UPDATE could retain values sampled before waiting on a writer.
    rows = rows.select_for_update() if lock else rows.select_related(*RELATED)
    try:
        return rows.get(pk=thesis_id)
    except ThesisRecord.DoesNotExist as error:
        raise ThesisUnavailable("thesis unavailable") from error


def _instant(clock: Clock, thesis: ThesisRecord | None = None) -> datetime:
    at = as_utc(clock())
    if thesis is not None and at < thesis.changed_at:
        raise ThesisConflict("trusted clock precedes the current thesis revision")
    return at


def _digest(kind: str, thesis_id: str | None, body: dict) -> str:
    return text_digest(canonical_json({"kind": kind, "thesis_id": thesis_id, "body": body}))


def _receipt(actor_id: str, command_id: str, digest: str) -> CommandReceipt | None:
    receipt = CommandReceipt.objects.filter(owner_id=actor_id, command_id=command_id).first()
    if receipt is not None and receipt.request_digest != digest:
        raise ThesisConflict("command_id already belongs to a different request")
    return receipt


def _text_wire(item: TextVersionRecord) -> dict:
    return {
        "id": str(item.pk), "parent_version_id": str(item.parent_id) if item.parent_id else None,
        "exact_text": item.exact_text, "text_digest": item.text_digest,
        "created_at": as_utc(item.created_at).isoformat(),
    }


def interpretation_value(item: InterpretationRecord) -> CompiledThesisVersion:
    """Reconstruct both legacy meaning and any hash-bound review surface."""
    value = CompiledThesisVersion(
        str(item.pk), str(item.text_version_id), tuple(item.drivers), item.horizon,
        tuple(item.invalidation_signposts), item.known_at,
        review_card_json=canonical_json(item.review_card) if item.review_card is not None else None,
    )
    if item.review_card is not None:
        if item.review_card["inputs"][0]["exact_text"] != item.text_version.exact_text:
            raise ThesisConflict("review card does not bind the linked exact thesis text")
        if item.origin != "model_compilation" or item.compilation_id is None:
            raise ThesisConflict("review card requires immutable compilation provenance")
        attempt = item.compilation
        expected_inputs = attempt.refinement.cumulative_inputs if attempt.refinement_id else []
        from .models import CompilationResult
        result = CompilationResult.objects.filter(attempt=attempt, status="compiled", interpretation=item).first()
        if (item.review_card["inputs"][1:] != expected_inputs or result is None
                or item.review_card["document"] != result.document):
            raise ThesisConflict("review card differs from saved compilation inputs or output")
    return value


def _meaning_wire(item: InterpretationRecord) -> dict:
    return {
        "id": str(item.pk), "text_version_id": str(item.text_version_id),
        "drivers": item.drivers, "horizon": item.horizon,
        "invalidation_signposts": item.invalidation_signposts,
        "known_at": as_utc(item.known_at).isoformat(), "digest": item.digest,
        "origin": item.origin,
        "review_card": item.review_card,
    }


def _approval_wire(item: ApprovalRecord) -> dict:
    return {
        "id": str(item.pk), "text_version_id": str(item.text_version_id),
        "interpretation_version_id": str(item.interpretation_id),
        "text_digest": item.text_version.text_digest,
        "interpretation_digest": item.interpretation.digest,
        "approved_at": as_utc(item.approved_at).isoformat(), "digest": item.digest,
        "revision": item.revision,
    }


def _detail(item: ThesisRecord) -> dict:
    approved = item.current_approval
    return {
        "id": str(item.pk), "revision": item.revision,
        "created_at": as_utc(item.created_at).isoformat(),
        "changed_at": as_utc(item.changed_at).isoformat(),
        "draft": {
            "text_version": _text_wire(item.latest_text),
            "interpretation": _meaning_wire(item.latest_interpretation),
        },
        "approved": None if approved is None else {
            "approval": _approval_wire(approved),
            "text_version": _text_wire(approved.text_version),
            "interpretation": _meaning_wire(approved.interpretation),
        },
        "monitoring": "not_configured",
    }


def _response(thesis: ThesisRecord, receipt: CommandReceipt, *, replayed: bool) -> dict:
    return {
        "command": {
            "command_id": str(receipt.command_id), "kind": receipt.kind,
            "replayed": replayed, "result": receipt.result,
            "is_current_approval": receipt.result["approval_id"] is not None
                and str(thesis.current_approval_id) == receipt.result["approval_id"],
        },
        "thesis": _detail(thesis),
    }


def _save_command(thesis: ThesisRecord, command_id: str, kind: str,
                  digest: str, at: datetime, approval_id: str | None = None) -> dict:
    result = {
        "thesis_id": str(thesis.pk), "thesis_version_id": str(thesis.latest_text_id),
        "interpretation_version_id": str(thesis.latest_interpretation_id),
        "approval_id": approval_id, "revision": thesis.revision,
        "accepted_at": at.isoformat(),
    }
    AuditTransition.objects.create(thesis=thesis, kind=kind, at=at, detail={
        **result, "actor_id": str(thesis.owner_id), "command_id": command_id,
        "text_digest": thesis.latest_text.text_digest,
        "interpretation_digest": thesis.latest_interpretation.digest,
        "request_digest": digest,
    })
    receipt = CommandReceipt.objects.create(
        owner_id=thesis.owner_id, thesis=thesis, command_id=command_id,
        kind=kind, request_digest=digest, result=result, saved_at=at,
    )
    return _response(thesis, receipt, replayed=False)


def _draft(thesis: ThesisRecord, text: str, meaning: dict, at: datetime) -> None:
    text_value = UserThesisVersion(
        str(uuid4()), str(thesis.pk), str(thesis.owner_id), text, at,
        str(thesis.latest_text_id) if thesis.latest_text_id else None,
    )
    meaning_value = CompiledThesisVersion(
        str(uuid4()), text_value.version_id, tuple(meaning["drivers"]),
        meaning["horizon"], tuple(meaning["invalidation_signposts"]), at,
    )
    thesis.latest_text = TextVersionRecord.objects.create(
        id=text_value.version_id, thesis=thesis, exact_text=text,
        text_digest=text_value.text_digest, created_at=at,
        parent_id=text_value.parent_version_id,
    )
    thesis.latest_interpretation = InterpretationRecord.objects.create(
        id=meaning_value.version_id, thesis=thesis, text_version=thesis.latest_text,
        drivers=meaning["drivers"], horizon=meaning["horizon"],
        invalidation_signposts=meaning["invalidation_signposts"], known_at=at,
        digest=meaning_value.digest, origin="user_supplied",
    )
    thesis.revision += 1
    thesis.changed_at = at
    thesis.save(update_fields=("latest_text", "latest_interpretation", "revision", "changed_at"))


def create_thesis(actor_id: str, command_id: str, text: str, interpretation: dict,
                  *, clock: Clock = timezone.now) -> dict:
    command_id = _uuid(command_id, "command_id")
    text, meaning = _text(text, "text", TEXT_LIMIT), _meaning(interpretation)
    digest = _digest("create", None, {"text": text, "interpretation": meaning})
    with transaction.atomic():
        owner = _owner(actor_id, lock=True)
        receipt = _receipt(actor_id, command_id, digest)
        if receipt is not None:
            thesis = _record(actor_id, str(receipt.thesis_id), lock=True)
            return _response(thesis, receipt, replayed=True)
        at = _instant(clock)
        thesis = ThesisRecord.objects.create(owner=owner, created_at=at, changed_at=at)
        _draft(thesis, text, meaning, at)
        return _save_command(thesis, command_id, "create", digest, at)


def propose_thesis(actor_id: str, thesis_id: str, command_id: str,
                   text: str, interpretation: dict, expected_revision: int,
                   *, clock: Clock = timezone.now) -> dict:
    command_id = _uuid(command_id, "command_id")
    _uuid(thesis_id, "thesis_id")
    revision = _revision(expected_revision)
    text, meaning = _text(text, "text", TEXT_LIMIT), _meaning(interpretation)
    digest = _digest("propose", thesis_id, {
        "text": text, "interpretation": meaning, "expected_revision": revision,
    })
    with transaction.atomic():
        _owner(actor_id, lock=True)
        thesis = _record(actor_id, thesis_id, lock=True)
        receipt = _receipt(actor_id, command_id, digest)
        if receipt is not None:
            return _response(thesis, receipt, replayed=True)
        if thesis.revision != revision:
            raise ThesisConflict("thesis revision changed; review the latest draft")
        at = _instant(clock, thesis)
        _draft(thesis, text, meaning, at)
        return _save_command(thesis, command_id, "propose", digest, at)


def approve_thesis(actor_id: str, thesis_id: str, command_id: str,
                   thesis_version_id: str, text_digest: str,
                   interpretation_version_id: str, interpretation_digest: str,
                   expected_revision: int, *, clock: Clock = timezone.now) -> dict:
    command_id = _uuid(command_id, "command_id")
    for value, name in ((thesis_id, "thesis_id"), (thesis_version_id, "thesis_version_id"),
                        (interpretation_version_id, "interpretation_version_id")):
        _uuid(value, name)
    require_digest(text_digest, "text_digest")
    require_digest(interpretation_digest, "interpretation_digest")
    revision = _revision(expected_revision)
    digest = _digest("approve", thesis_id, {
        "thesis_version_id": thesis_version_id, "text_digest": text_digest,
        "interpretation_version_id": interpretation_version_id,
        "interpretation_digest": interpretation_digest, "expected_revision": revision,
    })
    with transaction.atomic():
        _owner(actor_id, lock=True)
        thesis = _record(actor_id, thesis_id, lock=True)
        receipt = _receipt(actor_id, command_id, digest)
        if receipt is not None:
            return _response(thesis, receipt, replayed=True)
        if (thesis.revision != revision or str(thesis.latest_text_id) != thesis_version_id
                or str(thesis.latest_interpretation_id) != interpretation_version_id):
            raise ThesisConflict("displayed draft changed; review its current versions")
        text, meaning = thesis.latest_text, thesis.latest_interpretation
        text_value = UserThesisVersion(
            str(text.pk), str(thesis.pk), actor_id, text.exact_text, text.created_at,
            str(text.parent_id) if text.parent_id else None,
        )
        meaning_value = interpretation_value(meaning)
        if (text.text_digest != text_value.text_digest or meaning.digest != meaning_value.digest):
            raise ThesisConflict("stored draft failed integrity verification")
        if text_digest != text_value.text_digest or interpretation_digest != meaning_value.digest:
            raise ThesisConflict("approval must bind exact displayed text and interpretation")
        from macro_agent.persistence.context_binding import lock_thesis_briefs
        briefs = lock_thesis_briefs(thesis)
        at = _instant(clock, thesis)
        if any(at < brief.changed_at for brief in briefs):
            raise ThesisConflict("trusted clock precedes current publication state")
        approval = approve_exact(text_value, meaning_value, ApprovalRequest(
            str(uuid4()), actor_id, "user", thesis_version_id, text_digest,
            interpretation_version_id, interpretation_digest, at,
        ), now=at)
        thesis.revision += 1
        thesis.current_approval = ApprovalRecord.objects.create(
            id=approval.approval_id, thesis=thesis, text_version=text,
            interpretation=meaning, actor_id=actor_id, approved_at=at,
            digest=approval.digest, revision=thesis.revision,
        )
        thesis.changed_at = at
        thesis.save(update_fields=("current_approval", "revision", "changed_at"))
        from macro_agent.persistence.context_binding import invalidate_thesis_briefs
        invalidate_thesis_briefs(thesis, at, "approval_changed")
        return _save_command(thesis, command_id, "approve", digest, at, approval.approval_id)


def get_thesis(actor_id: str, thesis_id: str) -> dict:
    _owner(actor_id)
    return _detail(_record(actor_id, thesis_id))


def list_theses(actor_id: str, limit: int = 20, offset: int = 0) -> dict:
    _owner(actor_id)
    if (type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int
            or not 0 <= offset <= 1_000_000):
        raise ValueError("invalid pagination")
    rows = list(ThesisRecord.objects.filter(owner_id=actor_id).select_related(*RELATED)
                .order_by("created_at", "id")[offset:offset + limit + 1])
    return {"theses": [_detail(item) for item in rows[:limit]],
            "limit": limit, "offset": offset, "has_more": len(rows) > limit}


def thesis_history(actor_id: str, thesis_id: str) -> dict:
    """One coherent snapshot of bounded effective-time history, not live replay."""
    if connection.in_atomic_block:
        raise RuntimeError("history requires its own read-only snapshot transaction")
    if connection.vendor != "postgresql":
        raise RuntimeError("thesis history requires the reviewed PostgreSQL adapter")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        _owner(actor_id)
        thesis = _record(actor_id, thesis_id)
        texts = list(thesis.text_versions.order_by("created_at", "id")[:HISTORY_LIMIT + 1])
        meanings = list(thesis.interpretations.order_by("known_at", "id")[:HISTORY_LIMIT + 1])
        approvals = list(thesis.approvals.select_related("text_version", "interpretation")
                         .order_by("revision")[:HISTORY_LIMIT + 1])
        audit = list(thesis.audit_transitions.order_by("sequence")[:HISTORY_LIMIT + 1])
        return {
            "thesis": _detail(thesis),
            "text_versions": [_text_wire(item) for item in texts[:HISTORY_LIMIT]],
            "interpretations": [_meaning_wire(item) for item in meanings[:HISTORY_LIMIT]],
            "approvals": [_approval_wire(item) for item in approvals[:HISTORY_LIMIT]],
            "audit": [{"sequence": item.sequence, "kind": item.kind,
                       "at": as_utc(item.at).isoformat(), "detail": item.detail}
                      for item in audit[:HISTORY_LIMIT]],
            "replay_scope": "approval_effective_time_history", "history_limit": HISTORY_LIMIT,
            "truncated": any(len(items) > HISTORY_LIMIT for items in (texts, meanings, approvals, audit)),
        }
