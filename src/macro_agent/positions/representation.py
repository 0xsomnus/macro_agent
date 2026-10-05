"""Exact immutable declarations and a complete protected exposure book."""

from macro_agent.domain.exposure import (
    DECLARATION_FIELDS, PaperPositionVersion, version_content,
)
from .models import PositionRecord


def record_version(record) -> PaperPositionVersion:
    value = PaperPositionVersion(
        version_id=str(record.pk), position_id=str(record.position_id),
        owner_id=str(record.owner_id), thesis_id=str(record.thesis_id),
        approval_id=str(record.reviewed_approval_id),
        parent_version_id=str(record.parent_id) if record.parent_id else None,
        accepted_at=record.accepted_at, paper=record.paper, status=record.status,
        **{name: getattr(record, name) for name in DECLARATION_FIELDS},
    )
    if value.digest != record.digest:
        raise ValueError("stored paper position failed integrity verification")
    return value


def version_wire(record) -> dict:
    value = record_version(record)
    return {
        "id": value.version_id, "position_id": value.position_id,
        "parent_version_id": value.parent_version_id,
        "reviewed_approval_id": value.approval_id,
        "paper": True, "status": value.status,
        **value.declaration_dict, "accepted_at": value.accepted_at.isoformat(),
        "digest": value.digest, "mapping_status": value.mapping_status,
        "missing_fields": list(value.missing_fields),
    }


def detail_wire(record: PositionRecord) -> dict:
    return {
        "id": str(record.pk), "thesis_id": str(record.thesis_id),
        "revision": record.revision, "created_at": record.created_at.isoformat(),
        "changed_at": record.changed_at.isoformat(),
        "original_approval_id": str(record.original_approval_id),
        "current_version": version_wire(record.current_version),
        "mapping_status": "user_declared_unverified", "monitoring": "not_configured",
    }


def exposure_book(thesis_id: str, *, using: str = "default") -> dict:
    """Caller holds the thesis lock, or a consistent read-only snapshot.

    Closed positions remain explicit. No implicit empty/partial book is used if
    a row is incomplete or violates its immutable content digest.
    """
    positions = []
    rows = (PositionRecord.objects.using(using).filter(thesis_id=thesis_id)
            .select_related("current_version").order_by("id"))
    for row in rows:
        if row.current_version_id is None:
            raise ValueError("position has no complete current version")
        value = record_version(row.current_version)
        positions.append({"position_id": str(row.pk), "version_id": value.version_id,
                          "version_digest": value.digest, "payload": version_content(value)})
    return {"thesis_id": str(thesis_id), "positions": positions}
