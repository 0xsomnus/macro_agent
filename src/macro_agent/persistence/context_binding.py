"""Observe committed user context, then admit it under publication protection.

Input observation is a conservative durable-availability witness. The admission
transition's effective clock is not a measured PostgreSQL commit timestamp.
Sources remain explicit synthetic fixtures; no model or network call belongs here.
"""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from macro_agent.domain.models import (
    CompiledThesisVersion, PinnedDependency, ThesisApproval, UserThesisVersion,
    canonical_json, require_text, text_digest,
)
from macro_agent.domain.publication import REQUIRED_ROLES, pin_dict
from macro_agent.domain.time import as_utc
from macro_agent.theses.models import ThesisRecord

from .binding_models import ContextAdmission, ThesisBriefBinding
from .models import (
    AuditTransition, BriefStateRecord, CurrentAssessment, DependencyHead,
    DependencyVersion, NotificationIntent, ReassessmentWork,
)
from .publication_store import (
    _PublicationTransaction, _synthetic_gate, canonical_actor, context_digest,
    current_dependencies, record_pin, require_postgresql,
)


CONTEXT_ROLES = frozenset({"user_thesis", "compiled_thesis", "activation", "exposure"})
Clock = Callable[[], datetime]


class ContextPending(ValueError):
    """Current approved user context has not been admitted for publication."""


def _outermost(using: str):
    connection = require_postgresql(using)
    if connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("context admission requires its own outermost transaction")


def _uuid(value: str, name: str) -> str:
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError(f"{name} requires a canonical UUID")
    return value


def lock_owner_thesis(actor_id: str, thesis_id: str, using: str):
    """The common order is owner, thesis, then sorted brief rows."""
    canonical_actor(actor_id)
    _uuid(thesis_id, "thesis_id")
    owner = get_user_model().objects.using(using).select_for_update().filter(
        pk=actor_id, is_active=True).first()
    if owner is None:
        raise PermissionError("context is unavailable to this actor")
    thesis = ThesisRecord.objects.using(using).select_for_update().filter(
        pk=thesis_id, owner_id=actor_id).first()
    if thesis is None:
        raise PermissionError("context is unavailable to this actor")
    return thesis


def _book(thesis_id: str, using: str) -> dict:
    from macro_agent.positions.service import exposure_book
    return exposure_book(thesis_id, using=using)


def book_digest(book: dict) -> str:
    return text_digest(canonical_json(book))


def validate_binding(binding: ThesisBriefBinding, thesis: ThesisRecord, using: str):
    """Call only after the owner, thesis and brief protections are held."""
    if (binding.status != "ready" or binding.owner_id != thesis.owner_id
            or binding.thesis_id != thesis.pk
            or binding.admitted_approval_id != thesis.current_approval_id
            or binding.admitted_exposure_digest != book_digest(_book(str(thesis.pk), using))):
        raise ContextPending("approved thesis or paper exposure requires context admission")
    admission = ContextAdmission.objects.using(using).filter(
        brief_id=binding.brief_id, approval_id=binding.admitted_approval_id,
        exposure_digest=binding.admitted_exposure_digest).first()
    actual = [pin_dict(pin) for pin in current_dependencies(binding.brief_id, using)
              if pin.role in CONTEXT_ROLES]
    if (admission is None or binding.observed_at != admission.input_observed_at
            or {pin["role"]: pin for pin in actual}
            != {pin["role"]: pin for pin in admission.pins}):
        raise ContextPending("governing user-context heads differ from their exact admission")


def _resolved(thesis: ThesisRecord, expected_approval_id: str, using: str):
    _uuid(expected_approval_id, "expected_approval_id")
    if thesis.current_approval_id is None or str(thesis.current_approval_id) != expected_approval_id:
        raise ContextPending("current approval changed; inspect it before admitting context")
    approval = thesis.current_approval
    text, meaning = approval.text_version, approval.interpretation
    text_value = UserThesisVersion(str(text.pk), str(thesis.pk), str(thesis.owner_id),
                                  text.exact_text, text.created_at,
                                  str(text.parent_id) if text.parent_id else None)
    from macro_agent.theses.service import interpretation_value
    meaning_value = interpretation_value(meaning)
    approval_value = ThesisApproval(str(approval.pk), str(approval.actor_id), str(text.pk),
                                    text.text_digest, str(meaning.pk), meaning.digest,
                                    approval.approved_at)
    if (text_value.text_digest != text.text_digest or meaning_value.digest != meaning.digest
            or approval_value.digest != approval.digest
            or meaning.text_version_id != text.pk or approval.actor_id != thesis.owner_id):
        raise ValueError("approved user context failed integrity verification")
    book = _book(str(thesis.pk), using)
    resolved = {
        "thesis_id": str(thesis.pk), "owner_id": str(thesis.owner_id),
        "text": {"version_id": str(text.pk), "exact_text": text.exact_text,
                 "digest": text.text_digest, "created_at": as_utc(text.created_at).isoformat()},
        "interpretation": {"version_id": str(meaning.pk), "text_version_id": str(text.pk),
                           "drivers": meaning.drivers, "horizon": meaning.horizon,
                           "invalidation_signposts": meaning.invalidation_signposts,
                           "digest": meaning.digest, "prepared_at": as_utc(meaning.known_at).isoformat(),
                           "origin": meaning.origin},
        "approval": {"version_id": str(approval.pk), "actor_id": str(approval.actor_id),
                     "digest": approval.digest, "approved_at": as_utc(approval.approved_at).isoformat(),
                     "revision": approval.revision},
        "exposure": book,
    }
    if meaning.review_card is not None:
        resolved["interpretation"]["review_card"] = meaning.review_card
    return approval, resolved, book_digest(book)


def _at(clock: Clock, thesis: ThesisRecord, briefs=(), resolved: dict | None = None):
    at = as_utc(clock())
    bounds = [as_utc(thesis.changed_at), *(as_utc(brief.changed_at) for brief in briefs)]
    if resolved is not None:
        bounds.extend(datetime.fromisoformat(item) for item in (
            resolved["text"]["created_at"], resolved["interpretation"]["prepared_at"],
            resolved["approval"]["approved_at"]))
        for position in resolved["exposure"]["positions"]:
            bounds.append(datetime.fromisoformat(position["payload"]["accepted_at"]))
    if any(at < bound for bound in bounds):
        raise ValueError("context transition cannot precede its protected state or input times")
    return at


def lock_thesis_briefs(thesis: ThesisRecord, *, using: str = "default") -> list[BriefStateRecord]:
    """Acquire every bound brief in stable order after owner/thesis protection."""
    if not require_postgresql(using).in_atomic_block:
        raise RuntimeError("bound brief locks require a protected write transaction")
    ids = list(ThesisBriefBinding.objects.using(using).filter(thesis=thesis)
               .order_by("brief_id").values_list("brief_id", flat=True))
    return list(BriefStateRecord.objects.using(using).select_for_update(of=("self",))
                .filter(brief_id__in=ids, owner_id=thesis.owner_id).order_by("brief_id"))


def invalidate_thesis_briefs(thesis: ThesisRecord, at: datetime, reason: str,
                            *, using: str = "default") -> list[str]:
    """Hook called within an existing owner/thesis/all-briefs protected write."""
    require_text(reason, "reason")
    at = as_utc(at)
    briefs = lock_thesis_briefs(thesis, using=using)
    for brief in briefs:
        if at < brief.changed_at:
            raise ValueError("context invalidation cannot precede the current brief")
        ThesisBriefBinding.objects.using(using).filter(brief=brief).update(status="pending")
        CurrentAssessment.objects.using(using).filter(brief=brief).delete()
        canceled = list(NotificationIntent.objects.using(using).filter(brief=brief, state="pending")
                        .order_by("intent_id").values_list("intent_id", flat=True))
        NotificationIntent.objects.using(using).filter(brief=brief, state="pending").update(
            state="canceled", updated_at=at)
        ReassessmentWork.objects.using(using).filter(brief=brief, state="pending").update(
            state="superseded", completed_at=at)
        brief.changed_at = at
        brief.save(using=using, update_fields=("changed_at",))
        AuditTransition.objects.using(using).create(brief=brief, kind="context_pending", happened_at=at,
            detail={"actor_id": str(thesis.owner_id), "thesis_id": str(thesis.pk),
                    "reason": reason, "canceled_intents": canceled,
                    "current_approval_id": str(thesis.current_approval_id)})
    return [brief.pk for brief in briefs]


def _admit(binding: ThesisBriefBinding, brief: BriefStateRecord, thesis: ThesisRecord,
           approval, resolved: dict, exposure_digest: str, at: datetime, using: str) -> dict:
    existing = ContextAdmission.objects.using(using).filter(
        brief=brief, approval=approval, exposure_digest=exposure_digest).first()
    if existing is not None and binding.status == "ready":
        validate_binding(binding, thesis, using)
        return {"brief_id": brief.pk, "admission_id": str(existing.pk), "replayed": True,
                "status": "ready", "input_observed_at": existing.input_observed_at.isoformat(),
                "pins": existing.pins}
    if existing is not None:
        raise ContextPending("historical context admission cannot reactivate pending state")
    specs = (
        ("user_thesis", resolved["text"]["version_id"], resolved["text"]["digest"]),
        ("compiled_thesis", resolved["interpretation"]["version_id"], resolved["interpretation"]["digest"]),
        ("activation", str(approval.pk), approval.digest),
        ("exposure", "exposure:" + str(thesis.pk) + ":" + exposure_digest, exposure_digest),
    )
    pins = []
    for role, version_id, digest in specs:
        version = DependencyVersion.objects.using(using).filter(
            brief=brief, role=role, version_id=version_id).first()
        if version is None:
            version = DependencyVersion.objects.using(using).create(
                brief=brief, role=role, version_id=version_id, digest=digest, known_at=at)
        elif version.digest != digest:
            raise ValueError("context version identity changed its immutable content")
        DependencyHead.objects.using(using).update_or_create(
            brief=brief, role=role, defaults={"version": version})
        pins.append(pin_dict(record_pin(version)))
    admission = ContextAdmission.objects.using(using).create(
        brief=brief, thesis=thesis, approval=approval, exposure_digest=exposure_digest,
        input_digest=text_digest(canonical_json(resolved)), input_observed_at=at,
        admission_effective_at=at, resolved_inputs=resolved, pins=pins)
    binding.status, binding.admitted_approval = "ready", approval
    binding.admitted_exposure_digest, binding.observed_at = exposure_digest, at
    binding.save(using=using, update_fields=("status", "admitted_approval", "admitted_exposure_digest", "observed_at"))
    brief.changed_at = at
    brief.save(using=using, update_fields=("changed_at",))
    dependencies = current_dependencies(brief.pk, using)
    if {pin.role for pin in dependencies} != REQUIRED_ROLES:
        raise ValueError("admitted context requires all publication dependency roles")
    _PublicationTransaction(brief, str(thesis.owner_id), using).queue_reassessment(
        dependencies, at, "context_admitted")
    AuditTransition.objects.using(using).create(brief=brief, kind="context_admitted", happened_at=at,
        detail={"actor_id": str(thesis.owner_id), "thesis_id": str(thesis.pk),
                "admission_id": str(admission.pk), "input_observed_at": at.isoformat(),
                "admission_effective_at": at.isoformat(), "pins": pins,
                "source_scope": "synthetic_fixture", "commit_time_measured": False})
    return {"brief_id": brief.pk, "admission_id": str(admission.pk), "replayed": False,
            "status": "ready", "input_observed_at": at.isoformat(), "pins": pins}


def enroll_synthetic(actor_id: str, thesis_id: str, brief_id: str, expected_approval_id: str,
                     fixture_dependencies: tuple[PinnedDependency, ...], *,
                     clock: Clock = timezone.now, synthetic: bool = False, using: str = "default") -> dict:
    """Bind real, committed approval/exposure to explicitly local source fixtures."""
    _outermost(using)
    _synthetic_gate(synthetic)
    require_text(brief_id, "brief_id")
    if len(brief_id) > 255:
        raise ValueError("brief identity exceeds its limit")
    if (type(fixture_dependencies) is not tuple
            or any(not isinstance(pin, PinnedDependency) for pin in fixture_dependencies)
            or len(fixture_dependencies) != len(REQUIRED_ROLES - CONTEXT_ROLES)
            or {pin.role for pin in fixture_dependencies} != REQUIRED_ROLES - CONTEXT_ROLES):
        raise ValueError("fixture setup requires exactly the twelve non-user-context roles")
    with transaction.atomic(using=using, durable=True):
        thesis = lock_owner_thesis(actor_id, thesis_id, using)
        approval, resolved, exposure = _resolved(thesis, expected_approval_id, using)
        binding = ThesisBriefBinding.objects.using(using).filter(brief_id=brief_id, owner_id=actor_id,
                                                                thesis=thesis).first()
        if binding is not None:
            brief = BriefStateRecord.objects.using(using).select_for_update().get(pk=brief_id)
            at = _at(clock, thesis, (brief,), resolved)
            current_fixtures = {pin.role: pin for pin in current_dependencies(brief_id, using)
                                if pin.role not in CONTEXT_ROLES}
            if current_fixtures != {pin.role: pin for pin in fixture_dependencies}:
                raise ValueError("enrollment retry cannot replace fixture evidence")
            return _admit(binding, brief, thesis, approval, resolved, exposure, at, using)
        if BriefStateRecord.objects.using(using).filter(pk=brief_id).exists():
            raise PermissionError("brief is unavailable for enrollment")
        at = _at(clock, thesis, resolved=resolved)
        if any(pin.known_at > at for pin in fixture_dependencies):
            raise ValueError("fixture inputs cannot come from the future")
        brief = BriefStateRecord.objects.using(using).create(
            brief_id=brief_id, owner_id=actor_id, generation=0, changed_at=at)
        binding = ThesisBriefBinding.objects.using(using).create(
            brief=brief, thesis=thesis, owner_id=actor_id, created_at=at, status="pending")
        for pin in fixture_dependencies:
            version = DependencyVersion.objects.using(using).create(
                brief=brief, role=pin.role, version_id=pin.version_id, digest=pin.digest, known_at=pin.known_at)
            DependencyHead.objects.using(using).create(brief=brief, role=pin.role, version=version)
        return _admit(binding, brief, thesis, approval, resolved, exposure, at, using)


def refresh_context(actor_id: str, thesis_id: str, expected_approval_id: str,
                    *, clock: Clock = timezone.now, using: str = "default") -> dict:
    """Retryable admission of current committed user context to existing bindings."""
    _outermost(using)
    with transaction.atomic(using=using, durable=True):
        thesis = lock_owner_thesis(actor_id, thesis_id, using)
        bindings = list(ThesisBriefBinding.objects.using(using).filter(thesis=thesis, owner_id=actor_id)
                        .order_by("brief_id"))
        ids = [binding.brief_id for binding in bindings]
        briefs = list(BriefStateRecord.objects.using(using).select_for_update(of=("self",))
                      .filter(pk__in=ids, owner_id=actor_id).order_by("brief_id"))
        approval, resolved, exposure = _resolved(thesis, expected_approval_id, using)
        at = _at(clock, thesis, briefs, resolved)
        return {"thesis_id": thesis_id, "briefs": [
            _admit(binding, brief, thesis, approval, resolved, exposure, at, using)
            for binding, brief in zip(bindings, briefs, strict=True)]}
