"""Readable currentness and supported-fact rules, with no persistence imports."""

from dataclasses import dataclass, fields
from datetime import datetime
from hashlib import sha256
import json

from .models import (ContextSnapshot, EventRevision, PinnedDependency, VersionedContent,
                     normalize_json)
from .routing import Screening, route_event
from .time import as_utc


# A no-model run still pins explicit not-used prompt/model records.
REQUIRED_ROLES = frozenset({
    "user_thesis", "compiled_thesis", "activation", "exposure",
    "event_revision", "source_contract", "source_manifest", "coverage",
    "macro_context", "knowledge", "rules", "execution_graph",
    "entitlements", "budget", "model", "prompt",
})


def encode(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def pin_dict(pin: PinnedDependency) -> dict:
    return {"role": pin.role, "version_id": pin.version_id,
            "digest": pin.digest, "known_at": pin.known_at.isoformat()}


@dataclass(frozen=True)
class FactClaim:
    field: str
    value_json: str

    def __post_init__(self):
        if not isinstance(self.field, str) or not self.field.strip():
            raise ValueError("factual field must be named")
        if not isinstance(self.value_json, str):
            raise TypeError("fact value must be encoded JSON")
        object.__setattr__(self, "value_json", normalize_json(self.value_json))


@dataclass(frozen=True)
class PublicationCandidate:
    assessment_id: str
    run_id: str
    brief_id: str
    owner_id: str
    snapshot: ContextSnapshot
    expected_generation: int
    event: EventRevision
    source_contract: VersionedContent
    screening: Screening
    fact_claims: tuple[FactClaim, ...]
    material_change: bool = True

    def __post_init__(self):
        for value in (self.assessment_id, self.run_id, self.brief_id, self.owner_id):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("publication identities must be named")
        if type(self.expected_generation) is not int or self.expected_generation < 0:
            raise ValueError("publication generation must be a nonnegative integer")
        if type(self.material_change) is not bool:
            raise TypeError("material change must be explicit boolean")
        if not isinstance(self.snapshot, ContextSnapshot):
            raise TypeError("publication requires an immutable context snapshot")
        if not isinstance(self.event, EventRevision) or not isinstance(self.source_contract, VersionedContent):
            raise TypeError("publication requires immutable event and source contract")
        if not isinstance(self.screening, Screening):
            raise TypeError("publication requires a screening record")
        if type(self.fact_claims) is not tuple or not self.fact_claims:
            raise ValueError("qualified notice requires immutable supported facts")
        if any(not isinstance(claim, FactClaim) for claim in self.fact_claims):
            raise TypeError("fact claims must be validated values")
        if len({claim.field for claim in self.fact_claims}) != len(self.fact_claims):
            raise ValueError("each factual field must appear once")
        pins = {pin.role: pin for pin in self.snapshot.dependencies}
        if set(pins) != REQUIRED_ROLES:
            raise ValueError("publication snapshot must pin every required role")
        self._matches(pins["event_revision"], self.event.version_id,
                      self.event.digest, self.event.times.known_at)
        self._matches(pins["source_contract"], self.source_contract.version_id,
                      self.source_contract.digest, self.source_contract.known_at)
        if self.event.source_contract_version_id != self.source_contract.version_id:
            raise ValueError("event must use its pinned source-use contract")
        contract = json.loads(self.source_contract.content_json)
        permissions = contract.get("permitted_uses", [])
        if self.source_contract.kind != "SourceContractVersion":
            raise ValueError("source permissions require a source-use contract")
        if type(permissions) is not list or any(type(use) is not str for use in permissions):
            raise ValueError("permitted uses must be a list of named uses")
        if "display" not in permissions:
            raise PermissionError("source contract does not permit display")
        facts = json.loads(self.event.facts_json)
        for claim in self.fact_claims:
            if claim.field not in facts or encode(facts[claim.field]) != claim.value_json:
                raise ValueError("factual claim differs from its exact source field")
        decision = route_event(self.screening)
        if not self.screening.credible or not decision.analysis_required:
            raise ValueError("screening does not support a factual notice")
        if not self.screening.resolved and not decision.early_notice:
            raise ValueError("unresolved investigation cannot interrupt without urgency")

    @staticmethod
    def _matches(pin, version_id, digest, known_at):
        if (pin.version_id, pin.digest, pin.known_at) != (version_id, digest, known_at):
            raise ValueError("context pin does not identify the exact input")

    @property
    def payload(self) -> str:
        return encode({
            "assessment_id": self.assessment_id, "run_id": self.run_id,
            "brief_id": self.brief_id, "owner_id": self.owner_id,
            "snapshot_id": self.snapshot.snapshot_id,
            "snapshot_digest": self.snapshot.digest,
            "cutoff": self.snapshot.cutoff.isoformat(),
            "dependencies": [pin_dict(pin) for pin in sorted(self.snapshot.dependencies,
                                                             key=lambda pin: pin.role)],
            "expected_generation": self.expected_generation,
            "screening": {field.name: (value.value if hasattr(value, "value") else value)
                          for field in fields(self.screening)
                          for value in (getattr(self.screening, field.name),)},
            "facts": [{"field": claim.field, "value": json.loads(claim.value_json)}
                      for claim in self.fact_claims],
            "portfolio_impact": "unresolved", "expectations": "unavailable",
            "kind": "supported_factual_notice", "material_change": self.material_change,
        })

    @property
    def digest(self) -> str:
        return sha256(self.payload.encode("utf-8")).hexdigest()

    @property
    def intent_id(self) -> str | None:
        if not self.material_change:
            return None
        # Hash an array rather than join IDs with ambiguous separators.
        identity = encode([self.owner_id, self.brief_id, self.assessment_id])
        return "notice:" + sha256(identity.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BriefState:
    owner_id: str
    generation: int
    dependencies: tuple[PinnedDependency, ...]
    changed_at: datetime

    def __post_init__(self):
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise ValueError("current state must identify its owner")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("current generation must be a nonnegative integer")
        if type(self.dependencies) is not tuple or any(
                not isinstance(pin, PinnedDependency) for pin in self.dependencies):
            raise TypeError("current dependencies must be immutable validated pins")
        if {pin.role for pin in self.dependencies} != REQUIRED_ROLES:
            raise ValueError("current state must pin every required role")
        if len(self.dependencies) != len(REQUIRED_ROLES):
            raise ValueError("current dependency roles must be unique")
        object.__setattr__(self, "changed_at", as_utc(self.changed_at))
        if any(pin.known_at > self.changed_at for pin in self.dependencies):
            raise ValueError("current state cannot precede its dependencies")


@dataclass(frozen=True)
class PublicationDecision:
    status: str
    reasons: tuple[str, ...]
    reassessment_required: bool


def decide_publication(candidate: PublicationCandidate, current: BriefState,
                       at: datetime) -> PublicationDecision:
    """Call inside the store's protected transaction, using freshly read state."""
    at = as_utc(at)
    if candidate.owner_id != current.owner_id:
        raise PermissionError("publication belongs to a different owner")
    if at < candidate.snapshot.cutoff or at < as_utc(current.changed_at):
        raise ValueError("publication cannot be backdated behind its inputs or current state")
    if candidate.expected_generation > current.generation:
        raise ValueError("analysis cannot claim a publication generation that does not exist")
    used = {pin.role: pin for pin in candidate.snapshot.dependencies}
    heads = {pin.role: pin for pin in current.dependencies}
    if len(heads) != len(current.dependencies):
        raise ValueError("current state contains duplicate dependency roles")
    changed = tuple(sorted(role for role in set(used) | set(heads)
                           if used.get(role) != heads.get(role)))
    if changed:
        return PublicationDecision("superseded", tuple("changed:" + role for role in changed), True)
    if candidate.expected_generation != current.generation:
        return PublicationDecision("superseded", ("newer_publication",), False)
    return PublicationDecision("current", ("all_dependencies_current",), False)
