"""Immutable values for the first contract slice, not the full domain model.

    Constructors validate their inputs at runtime. Canonical JSON strings keep
    nested source content immutable without selecting an external schema tool.
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import re
from typing import Any

from .time import SourceTimes, as_utc


def require_text(value: str, field: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} cannot be empty")


def require_digest(value: str, field: str = "digest") -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


def text_digest(value: str) -> str:
    """Hash exact UTF-8 text without trimming or Unicode normalization."""
    if not isinstance(value, str):
        raise TypeError("text digest requires a string")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_json(value: Any) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if type(value) is list:
        for item in value:
            _validate_json(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            _validate_json(item)
        return
    raise TypeError("content must contain only JSON primitive values, objects and arrays")


def canonical_json(value: Any) -> str:
    """Produce stable internal JSON, not a cross-language wire standard."""
    _validate_json(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object keys are ambiguous")
        result[key] = value
    return result


def normalize_json(value: str) -> str:
    """Validate encoded primitive JSON and reject ambiguous duplicate keys."""
    if not isinstance(value, str):
        raise TypeError("immutable content must be a JSON string")
    decoded = json.loads(value, object_pairs_hook=_unique_object)
    return canonical_json(decoded)


def normalize_json_object(value: str) -> str:
    normalized = normalize_json(value)
    decoded = json.loads(normalized)
    if type(decoded) is not dict:
        raise ValueError("record content must be a JSON object")
    return normalized


def _strings(value: tuple[str, ...], field: str, *, unique: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{field} must be a list or tuple of strings")
    result = tuple(value)
    for item in result:
        require_text(item, field)
    if unique and len(set(result)) != len(result):
        raise ValueError(f"{field} cannot contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class UserThesisVersion:
    version_id: str
    thesis_id: str
    owner_id: str
    exact_text: str
    created_at: datetime
    parent_version_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("version_id", "thesis_id", "owner_id", "exact_text"):
            require_text(getattr(self, name), name)
        if self.parent_version_id is not None:
            require_text(self.parent_version_id, "parent_version_id")
            if self.parent_version_id == self.version_id:
                raise ValueError("a thesis version cannot be its own parent")
        object.__setattr__(self, "created_at", as_utc(self.created_at))

    @property
    def text_digest(self) -> str:
        return text_digest(self.exact_text)


@dataclass(frozen=True, slots=True)
class CompiledThesisVersion:
    version_id: str
    thesis_version_id: str
    drivers: tuple[str, ...]
    horizon: str | None
    invalidation_signposts: tuple[str, ...]
    known_at: datetime
    review_card_json: str | None = None

    def __post_init__(self) -> None:
        require_text(self.version_id, "version_id")
        require_text(self.thesis_version_id, "thesis_version_id")
        object.__setattr__(self, "drivers", _strings(self.drivers, "drivers", unique=True))
        if self.horizon is not None:
            require_text(self.horizon, "horizon")
        object.__setattr__(self, "invalidation_signposts", _strings(self.invalidation_signposts, "invalidation_signposts"))
        object.__setattr__(self, "known_at", as_utc(self.known_at))
        if self.review_card_json is not None:
            from .compilation import validate_review_card_json
            content = validate_review_card_json(self.review_card_json)
            interpretation = json.loads(content)["document"]["interpretation"]
            if interpretation != {"drivers": list(self.drivers), "horizon": self.horizon,
                                  "invalidation_signposts": list(self.invalidation_signposts)}:
                raise ValueError("review card must bind the same extracted interpretation")
            object.__setattr__(self, "review_card_json", content)

    @property
    def digest(self) -> str:
        content = {
            "version_id": self.version_id,
            "thesis_version_id": self.thesis_version_id,
            "drivers": list(self.drivers),
            "horizon": self.horizon,
            "invalidation_signposts": list(self.invalidation_signposts),
            "known_at": self.known_at.isoformat(),
        }
        if self.review_card_json is not None:
            card = json.loads(self.review_card_json)
            content.update(review_schema_version=card["schema_version"], review_card=card)
        return text_digest(canonical_json(content))


@dataclass(frozen=True, slots=True)
class ThesisApproval:
    approval_id: str
    actor_id: str
    thesis_version_id: str
    text_digest: str
    interpretation_version_id: str
    interpretation_digest: str
    approved_at: datetime

    def __post_init__(self) -> None:
        for name in ("approval_id", "actor_id", "thesis_version_id", "interpretation_version_id"):
            require_text(getattr(self, name), name)
        require_digest(self.text_digest, "text_digest")
        require_digest(self.interpretation_digest, "interpretation_digest")
        object.__setattr__(self, "approved_at", as_utc(self.approved_at))

    @property
    def digest(self) -> str:
        return text_digest(canonical_json({
            "approval_id": self.approval_id,
            "actor_id": self.actor_id,
            "thesis_version_id": self.thesis_version_id,
            "text_digest": self.text_digest,
            "interpretation_version_id": self.interpretation_version_id,
            "interpretation_digest": self.interpretation_digest,
            "approved_at": self.approved_at.isoformat(),
        }))


@dataclass(frozen=True, slots=True)
class VersionedContent:
    version_id: str
    kind: str
    known_at: datetime
    content_json: str

    def __post_init__(self) -> None:
        require_text(self.version_id, "version_id")
        require_text(self.kind, "kind")
        object.__setattr__(self, "known_at", as_utc(self.known_at))
        object.__setattr__(self, "content_json", normalize_json_object(self.content_json))

    @property
    def digest(self) -> str:
        return text_digest(self.content_json)


@dataclass(frozen=True, slots=True)
class EventRevision:
    event_id: str
    revision: int
    source_id: str
    source_contract_version_id: str
    times: SourceTimes
    facts_json: str

    def __post_init__(self) -> None:
        for name in ("event_id", "source_id", "source_contract_version_id"):
            require_text(getattr(self, name), name)
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("event revision must be a positive integer")
        if not isinstance(self.times, SourceTimes):
            raise TypeError("event revision requires source times")
        object.__setattr__(self, "facts_json", normalize_json_object(self.facts_json))

    @property
    def version_id(self) -> str:
        return f"{self.event_id}@{self.revision}"

    @property
    def digest(self) -> str:
        public_at = self.times.public_available_at
        return text_digest(canonical_json({
            "event_id": self.event_id,
            "revision": self.revision,
            "source_id": self.source_id,
            "source_contract_version_id": self.source_contract_version_id,
            "public_available_at": public_at.isoformat() if public_at is not None else None,
            "system_received_at": self.times.system_received_at.isoformat(),
            "known_at": self.times.known_at.isoformat(),
            "facts": json.loads(self.facts_json),
        }))


@dataclass(frozen=True, slots=True)
class PinnedDependency:
    role: str
    version_id: str
    digest: str
    known_at: datetime

    def __post_init__(self) -> None:
        require_text(self.role, "role")
        require_text(self.version_id, "version_id")
        require_digest(self.digest)
        object.__setattr__(self, "known_at", as_utc(self.known_at))


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    snapshot_id: str
    cutoff: datetime
    dependencies: tuple[PinnedDependency, ...]

    def __post_init__(self) -> None:
        require_text(self.snapshot_id, "snapshot_id")
        object.__setattr__(self, "cutoff", as_utc(self.cutoff))
        if not isinstance(self.dependencies, (tuple, list)):
            raise TypeError("dependencies must be a list or tuple")
        dependencies = tuple(self.dependencies)
        if not dependencies or any(not isinstance(item, PinnedDependency) for item in dependencies):
            raise ValueError("snapshot requires pinned dependencies")
        if len({item.role for item in dependencies}) != len(dependencies):
            raise ValueError("each dependency role must have exactly one pinned version")
        if any(item.known_at > self.cutoff for item in dependencies):
            raise ValueError("future context cannot enter an operational snapshot")
        object.__setattr__(self, "dependencies", dependencies)

    def dependency(self, role: str) -> PinnedDependency:
        for item in self.dependencies:
            if item.role == role:
                return item
        raise KeyError(role)

    @property
    def digest(self) -> str:
        return text_digest(canonical_json({
            "snapshot_id": self.snapshot_id,
            "cutoff": self.cutoff.isoformat(),
            "dependencies": [{
                "role": item.role, "version_id": item.version_id,
                "digest": item.digest, "known_at": item.known_at.isoformat(),
            } for item in sorted(self.dependencies, key=lambda item: item.role)],
        }))
