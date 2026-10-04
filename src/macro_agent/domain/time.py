"""Availability rules for operational replay, distinct from public studies."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Protocol, TypeVar


def as_utc(value: datetime) -> datetime:
    """Reject ambiguous local time and normalize an aware instant to UTC."""
    if not isinstance(value, datetime):
        raise TypeError("instant must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("instant requires an explicit timezone")
    return value.astimezone(timezone.utc)


def parse_instant(value: str) -> datetime:
    """Parse a timestamp at an adapter boundary without inventing a timezone."""
    if not isinstance(value, str):
        raise TypeError("timestamp must be a string")
    return as_utc(datetime.fromisoformat(value))


@dataclass(frozen=True, slots=True)
class SourceTimes:
    public_available_at: datetime | None
    system_received_at: datetime
    known_at: datetime

    def __post_init__(self) -> None:
        public = self.public_available_at
        if public is not None:
            object.__setattr__(self, "public_available_at", as_utc(public))
        object.__setattr__(self, "system_received_at", as_utc(self.system_received_at))
        object.__setattr__(self, "known_at", as_utc(self.known_at))
        if self.known_at < self.system_received_at:
            raise ValueError("durable known_at cannot precede actual receipt")
        # Restricted or embargoed receipts can precede public availability.
        # Availability does not grant display or model-processing permission.


def operationally_available(times: SourceTimes, cutoff: datetime) -> bool:
    if not isinstance(times, SourceTimes):
        raise TypeError("source times required")
    return times.known_at <= as_utc(cutoff)


def publicly_available(times: SourceTimes, cutoff: datetime) -> bool:
    """For explicitly labelled public-information studies, never live replay."""
    if not isinstance(times, SourceTimes):
        raise TypeError("source times required")
    return times.public_available_at is not None and times.public_available_at <= as_utc(cutoff)


class _Revision(Protocol):
    event_id: str
    revision: int
    times: SourceTimes
    digest: str


RevisionT = TypeVar("RevisionT", bound=_Revision)


def latest_operational_revision(
    revisions: Iterable[RevisionT], event_id: str, cutoff: datetime
) -> RevisionT | None:
    """Select only a durably available revision, preserving earlier vintages.

    Revision numbers order source corrections, not arrival order. Conflicting
    records with the same identity are rejected instead of chosen arbitrarily.
    """
    at = as_utc(cutoff)
    identities: dict[int, RevisionT] = {}
    for item in revisions:
        if item.event_id != event_id:
            continue
        previous = identities.get(item.revision)
        if previous is not None and previous.digest != item.digest:
            raise ValueError("an event revision identity cannot change content")
        identities[item.revision] = item
    eligible = [item for item in identities.values() if operationally_available(item.times, at)]
    return max(eligible, key=lambda item: item.revision, default=None)
