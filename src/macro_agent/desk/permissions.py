"""Explicit fixed-adapter permissions; observations never grant a new use."""

from django.db import transaction
from django.utils import timezone

from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.domain.time import as_utc
from macro_agent.monitoring.models import SourceState
from macro_agent.theses import service as theses

from .models import SourceContractHead, SourceContractVersion


def permission_allows(source_id):
    """Safe to consult under existing capture locks, independently of activation."""
    head = SourceContractHead.objects.select_related("version").filter(source_id=source_id).first()
    return None if head is None else head.version.permitted


def contract_snapshot(source, actor_id, at):
    """Called under its source lock and owner protection, no rights inference."""
    from macro_agent.monitoring.news_context import allowed_source
    if not allowed_source(source):
        raise theses.ThesisConflict("Source is outside the current permitted adapter manifest")
    head = SourceContractHead.objects.select_related("version").filter(source=source).first()
    if head is not None:
        if (head.version.contract != source.contract or head.version.digest != source.contract_digest
                or not head.version.permitted):
            raise theses.ThesisConflict("Source permission or contract is unavailable")
        return head.version
    if text_digest(canonical_json(source.contract)) != source.contract_digest:
        raise theses.ThesisConflict("Source is outside the existing reviewed adapter manifest")
    version = SourceContractVersion.objects.create(source=source, contract=source.contract,
        digest=source.contract_digest, permitted=True, reviewer_id=actor_id, observed_at=at,
        provenance="existing_allowlisted_adapter_manifest",
        reason="Observed existing contract; this snapshot is not a new human rights review.")
    SourceContractHead.objects.create(source=source, version=version)
    return version


def set_source_permission(actor_id, source_id, expected_contract_digest, permitted, reason,
                          *, clock=timezone.now):
    from .service import gate, outermost
    gate()
    outermost()
    if type(permitted) is not bool:
        raise ValueError("permitted requires a boolean")
    theses._text(reason, "reason", 2000)
    with transaction.atomic():
        source = SourceState.objects.select_for_update().filter(pk=source_id).first()
        actor = theses._owner(actor_id, lock=True)
        if not actor.is_staff or source is None:
            raise theses.ThesisUnavailable("Source permission unavailable")
        if expected_contract_digest != source.contract_digest:
            raise theses.ThesisConflict("Source contract changed")
        # This checks the existing adapter independent of the permission head.
        from macro_agent.monitoring.news_context import _adapter_allowed_source
        existing = SourceContractHead.objects.select_related("version").filter(source=source).first()
        if permitted and not _adapter_allowed_source(source):
            raise theses.ThesisConflict("No reviewed adapter permission exists")
        if text_digest(canonical_json(source.contract)) != source.contract_digest:
            raise theses.ThesisConflict("Source contract failed integrity verification")
        at = as_utc(clock())
        if existing is not None and at < existing.version.observed_at:
            raise theses.ThesisConflict("Permission observation cannot move backwards")
        version = SourceContractVersion.objects.create(source=source, contract=source.contract,
            digest=source.contract_digest, permitted=permitted, reviewer=actor, observed_at=at,
            provenance="explicit_staff_permission_review", reason=reason,
            parent=existing.version if existing else None)
        SourceContractHead.objects.update_or_create(source=source, defaults={"version": version})
        return {"source_id": source.pk, "version_id": str(version.pk), "permitted": permitted,
                "observed_at": at.isoformat(), "reviewer_id": str(actor.pk)}
