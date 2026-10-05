"""Owner-scoped PostgreSQL adapter for the publication application boundary.

Every governing writer locks its brief before reading versions. Bound briefs
first lock the owner and thesis, and reject context pending fresh admission.
Only synthetic fixtures can register source evidence until trusted ingestion.
"""

from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
import json
from typing import Callable
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.db.models import Q

from ..domain.models import PinnedDependency, require_text
from ..domain.publication import (
    BriefState, PublicationCandidate, PublicationDecision, REQUIRED_ROLES,
    decide_publication, encode, pin_dict,
)
from ..domain.time import as_utc
from .models import (
    AssessmentRecord, AuditTransition, BriefStateRecord, BriefVersion,
    CurrentAssessment, DependencyHead, DependencyVersion, NotificationIntent,
    ReassessmentWork,
)


AUTHORITY_ROLES = frozenset({"user_thesis", "compiled_thesis", "activation"})


def canonical_actor(actor_id: str) -> str:
    if not isinstance(actor_id, str):
        raise TypeError("actor identity must be a stable UUID string")
    if str(UUID(actor_id)) != actor_id:
        raise ValueError("actor identity must use canonical UUID spelling")
    return actor_id


def require_postgresql(using: str):
    connection = connections[using]
    if connection.vendor != "postgresql":
        raise RuntimeError("publication persistence requires PostgreSQL; no fallback is supported")
    return connection


def record_pin(record: DependencyVersion) -> PinnedDependency:
    return PinnedDependency(record.role, record.version_id, record.digest, record.known_at)


def current_dependencies(brief_id: str, using: str) -> tuple[PinnedDependency, ...]:
    heads = DependencyHead.objects.using(using).filter(brief_id=brief_id).select_related("version").order_by("role")
    result = []
    for head in heads:
        if head.version.brief_id != brief_id or head.version.role != head.role:
            raise ValueError("dependency head crosses its brief or role")
        result.append(record_pin(head.version))
    return tuple(result)


def context_digest(dependencies: tuple[PinnedDependency, ...]) -> str:
    value = encode([pin_dict(pin) for pin in sorted(dependencies, key=lambda pin: pin.role)])
    return sha256(value.encode("utf-8")).hexdigest()


def _clock(at: datetime | Callable[[], datetime]) -> datetime:
    return as_utc(at() if callable(at) else at)


def _audit(brief, actor_id, kind, at, detail, using):
    AuditTransition.objects.using(using).create(
        brief=brief, kind=kind, happened_at=at, detail={"actor_id": actor_id, **detail})


def _synthetic_gate(synthetic: bool):
    if synthetic is not True or getattr(settings, "MACRO_ALLOW_SYNTHETIC_SETUP", False) is not True:
        raise PermissionError("synthetic setup is disabled outside explicit fixture setup")


class DjangoPublicationStore:
    def __init__(self, actor_id: str, *, using: str = "default"):
        self.actor_id = canonical_actor(actor_id)
        self.using = using
        require_postgresql(using)

    @contextmanager
    def transaction(self, brief_id: str):
        """Lock before any version read; retain ordering until atomic commit."""
        require_text(brief_id, "brief_id")
        require_postgresql(self.using)
        with transaction.atomic(using=self.using):
            # Bindings are immutable and can only be created with a new brief.
            # An existing unbound fixture therefore cannot change lock protocols.
            from .binding_models import ThesisBriefBinding
            from .context_binding import lock_owner_thesis, validate_binding
            binding = ThesisBriefBinding.objects.using(self.using).filter(
                brief_id=brief_id, owner_id=self.actor_id).first()
            thesis = None
            if binding is not None:
                thesis = lock_owner_thesis(self.actor_id, str(binding.thesis_id), self.using)
            brief = (BriefStateRecord.objects.using(self.using)
                     .select_for_update(of=("self",))
                     .filter(brief_id=brief_id, owner_id=self.actor_id, owner__is_active=True).first())
            if brief is None:
                # Missing and foreign rows deliberately have the same result.
                raise PermissionError("brief is unavailable to this actor")
            if binding is not None:
                binding.refresh_from_db(using=self.using)
                validate_binding(binding, thesis, self.using)
            yield _PublicationTransaction(brief, self.actor_id, self.using)

    def bootstrap_synthetic(self, brief_id: str, dependencies: tuple[PinnedDependency, ...],
                            at: datetime, *, synthetic: bool = False):
        """Explicit management-command/test setup, never thesis approval."""
        _synthetic_gate(synthetic)
        require_text(brief_id, "brief_id")
        at = as_utc(at)
        if type(dependencies) is not tuple or any(not isinstance(pin, PinnedDependency) for pin in dependencies):
            raise TypeError("fixture setup requires validated immutable dependencies")
        if len(dependencies) != len(REQUIRED_ROLES) or {pin.role for pin in dependencies} != REQUIRED_ROLES:
            raise ValueError("fixture setup requires each governing role exactly once")
        if any(pin.known_at > at for pin in dependencies):
            raise ValueError("fixture setup cannot activate future context")
        require_postgresql(self.using)
        with transaction.atomic(using=self.using):
            if not get_user_model().objects.using(self.using).filter(pk=self.actor_id, is_active=True).exists():
                raise PermissionError("fixture owner must have an active account")
            brief = BriefStateRecord.objects.using(self.using).create(
                brief_id=brief_id, owner_id=self.actor_id, generation=0, changed_at=at)
            for pin in dependencies:
                version = DependencyVersion.objects.using(self.using).create(
                    brief=brief, role=pin.role, version_id=pin.version_id, digest=pin.digest, known_at=pin.known_at)
                DependencyHead.objects.using(self.using).create(brief=brief, role=pin.role, version=version)
            _audit(brief, self.actor_id, "bootstrap", at,
                   {"synthetic": True, "dependencies": [pin_dict(pin) for pin in dependencies]}, self.using)

    def register_synthetic_dependency(self, brief_id: str, pin: PinnedDependency, *, synthetic: bool = False):
        """Register a fixture version without changing its governing head."""
        _synthetic_gate(synthetic)
        if not isinstance(pin, PinnedDependency) or pin.role not in REQUIRED_ROLES:
            raise ValueError("fixture version must pin a known governing role")
        with self.transaction(brief_id) as tx:
            if pin.role in AUTHORITY_ROLES | {"exposure"}:
                from .binding_models import ThesisBriefBinding
                if ThesisBriefBinding.objects.using(self.using).filter(brief=tx.brief).exists():
                    raise PermissionError("bound user context is resolved from immutable approved records")
            existing = DependencyVersion.objects.using(self.using).filter(
                brief=tx.brief, role=pin.role, version_id=pin.version_id).first()
            if existing is not None:
                if record_pin(existing) != pin:
                    raise ValueError("a dependency version cannot change digest or known_at")
                return
            DependencyVersion.objects.using(self.using).create(
                brief=tx.brief, role=pin.role, version_id=pin.version_id, digest=pin.digest, known_at=pin.known_at)
            _audit(tx.brief, self.actor_id, "synthetic_dependency_registered", pin.known_at,
                   {"synthetic": True, "dependency": pin_dict(pin)}, self.using)

    def advance_evidence(self, brief_id: str, pin: PinnedDependency,
                         expected_previous: PinnedDependency, at: datetime | Callable[[], datetime]):
        """Move a registered evidence head with an exact compare-and-swap guard.

        Authority roles require a separate durable approval path. This method
        cannot create evidence provenance from a caller-supplied hash.
        """
        if not isinstance(pin, PinnedDependency) or not isinstance(expected_previous, PinnedDependency):
            raise TypeError("evidence transition requires exact validated pins")
        if pin.role in AUTHORITY_ROLES:
            raise PermissionError("authority changes require durable user approval")
        if pin.role != expected_previous.role:
            raise ValueError("evidence transition must keep its dependency role")
        with self.transaction(brief_id) as tx:
            if pin.role == "exposure":
                from .binding_models import ThesisBriefBinding
                if ThesisBriefBinding.objects.using(self.using).filter(brief=tx.brief).exists():
                    raise PermissionError("bound paper exposure is admitted from immutable position records")
            state = tx.state()
            at = _clock(at)
            if at < state.changed_at or pin.known_at > at:
                raise ValueError("evidence transition cannot be backdated")
            previous = next((item for item in state.dependencies if item.role == pin.role), None)
            if previous is None:
                raise ValueError("unknown governing dependency role")
            if previous != expected_previous:
                raise ValueError("governing dependency changed since read")
            registered = DependencyVersion.objects.using(self.using).filter(
                brief=tx.brief, role=pin.role, version_id=pin.version_id).first()
            if registered is None or record_pin(registered) != pin:
                raise PermissionError("evidence version lacks exact registered provenance")
            if previous == pin:
                return
            if pin.known_at < previous.known_at:
                raise ValueError("governing evidence cannot move backwards in known_at")
            history = AuditTransition.objects.using(self.using).filter(brief=tx.brief)
            activated = history.filter(
                Q(kind="bootstrap", detail__dependencies__contains=[pin_dict(pin)])
                | Q(kind="dependency_advanced", detail__current=pin_dict(pin))).exists()
            if activated:
                # Equal timestamps do not imply equal activation order. Restored
                # content requires a fresh version, never a reused old head.
                raise ValueError("a previously activated evidence version cannot become current again")
            DependencyHead.objects.using(self.using).filter(brief=tx.brief, role=pin.role).update(version=registered)
            CurrentAssessment.objects.using(self.using).filter(brief=tx.brief).delete()
            tx.brief.changed_at = at
            tx.brief.save(using=self.using, update_fields=["changed_at"])
            canceled = []
            pending = list(NotificationIntent.objects.using(self.using).filter(
                brief=tx.brief, state="pending").select_related("assessment").order_by("intent_id"))
            for intent in pending:
                used = {item["role"]: item for item in json.loads(intent.assessment.payload)["dependencies"]}
                if used.get(pin.role) != pin_dict(pin):
                    NotificationIntent.objects.using(self.using).filter(pk=intent.pk).update(state="canceled", updated_at=at)
                    canceled.append(intent.intent_id)
            fresh_dependencies = current_dependencies(brief_id, self.using)
            target = context_digest(fresh_dependencies)
            ReassessmentWork.objects.using(self.using).filter(brief=tx.brief, state="pending").exclude(
                context_digest=target).update(state="superseded", completed_at=at)
            tx.queue_reassessment(fresh_dependencies, at, "changed:" + pin.role)
            _audit(tx.brief, self.actor_id, "dependency_advanced", at,
                   {"previous": pin_dict(previous), "current": pin_dict(pin),
                    "canceled_intents": canceled}, self.using)

    def mark_delivered(self, intent_id: str, at: datetime | Callable[[], datetime]) -> bool:
        """Local acknowledgement only; there is no external delivery worker yet."""
        require_text(intent_id, "intent_id")
        require_postgresql(self.using)
        brief_id = (NotificationIntent.objects.using(self.using)
                    .filter(intent_id=intent_id, brief__owner_id=self.actor_id, brief__owner__is_active=True)
                    .values_list("brief_id", flat=True).first())
        if brief_id is None:
            raise PermissionError("notification is unavailable to this actor")
        with self.transaction(brief_id) as tx:
            state = tx.state()
            at = _clock(at)
            intent = NotificationIntent.objects.using(self.using).select_related("assessment").get(
                intent_id=intent_id, brief=tx.brief)
            if at < state.changed_at or at < as_utc(intent.updated_at):
                raise ValueError("local acknowledgement cannot be backdated")
            if intent.state != "pending":
                return False
            used = json.loads(intent.assessment.payload)["dependencies"]
            current = [pin_dict(pin) for pin in state.dependencies]
            valid = sorted(used, key=lambda pin: pin["role"]) == current
            result = "delivered" if valid else "canceled"
            NotificationIntent.objects.using(self.using).filter(pk=intent.pk).update(state=result, updated_at=at)
            _audit(tx.brief, self.actor_id, "local_delivery_" + result, at,
                   {"intent_id": intent_id, "dependencies_current": valid}, self.using)
            return valid

    def inspect(self, brief_id: str) -> dict:
        from .inspection import inspect_brief
        return inspect_brief(self.actor_id, brief_id, using=self.using)


class _PublicationTransaction:
    def __init__(self, brief, actor_id, using):
        self.brief, self.actor_id, self.using = brief, actor_id, using

    def state(self) -> BriefState:
        return BriefState(str(self.brief.owner_id), self.brief.generation,
                          current_dependencies(self.brief.brief_id, self.using), self.brief.changed_at)

    def existing(self, assessment_id: str):
        record = AssessmentRecord.objects.using(self.using).filter(
            brief=self.brief, assessment_id=assessment_id).first()
        if record is None:
            return None
        current_id = CurrentAssessment.objects.using(self.using).filter(brief=self.brief).values_list(
            "assessment_id", flat=True).first()
        if record.status == "current" and record.pk != current_id:
            return record.digest, PublicationDecision("superseded", ("historical_publication",), False)
        return record.digest, PublicationDecision(record.status, tuple(record.reasons), record.reassessment_required)

    def queue_reassessment(self, dependencies, at, reason):
        ReassessmentWork.objects.using(self.using).get_or_create(
            brief=self.brief, context_digest=context_digest(dependencies),
            defaults={"reason": reason, "created_at": at, "state": "pending"})

    def save(self, candidate: PublicationCandidate, decision: PublicationDecision, at: datetime):
        at = as_utc(at)
        state = self.state()
        if candidate.owner_id != self.actor_id or candidate.brief_id != self.brief.brief_id:
            raise PermissionError("assessment belongs to a different actor or brief")
        if decision != decide_publication(candidate, state, at):
            raise ValueError("publication decision differs from protected domain rules")
        assessment = AssessmentRecord.objects.using(self.using).create(
            brief=self.brief, assessment_id=candidate.assessment_id, digest=candidate.digest,
            payload=candidate.payload, status=decision.status, reasons=list(decision.reasons),
            reassessment_required=decision.reassessment_required,
            observed_dependencies=[pin_dict(pin) for pin in state.dependencies], saved_at=at)
        canceled = []
        if decision.status == "current":
            self.brief.generation += 1
            self.brief.changed_at = at
            self.brief.save(using=self.using, update_fields=["generation", "changed_at"])
            CurrentAssessment.objects.using(self.using).update_or_create(
                brief=self.brief, defaults={"assessment": assessment})
            BriefVersion.objects.using(self.using).create(
                brief=self.brief, generation=self.brief.generation, assessment=assessment, saved_at=at)
            ReassessmentWork.objects.using(self.using).filter(
                brief=self.brief, context_digest=context_digest(state.dependencies), state="pending").update(
                state="completed", completed_at=at)
            if candidate.material_change:
                canceled = list(NotificationIntent.objects.using(self.using).filter(
                    brief=self.brief, state="pending").order_by("intent_id").values_list("intent_id", flat=True))
                NotificationIntent.objects.using(self.using).filter(brief=self.brief, state="pending").update(
                    state="canceled", updated_at=at)
                NotificationIntent.objects.using(self.using).create(
                    intent_id=candidate.intent_id, brief=self.brief, assessment=assessment,
                    state="pending", created_at=at, updated_at=at)
        elif decision.reassessment_required:
            self.queue_reassessment(state.dependencies, at, ",".join(decision.reasons))
        _audit(self.brief, self.actor_id, "publication", at,
               {"assessment_id": candidate.assessment_id, "run_id": candidate.run_id,
                "status": decision.status, "reasons": list(decision.reasons),
                "pinned_dependencies": [pin_dict(pin) for pin in candidate.snapshot.dependencies],
                "observed_dependencies": [pin_dict(pin) for pin in state.dependencies],
                "canceled_intents": canceled,
                "intent_id": candidate.intent_id if decision.status == "current" else None}, self.using)
