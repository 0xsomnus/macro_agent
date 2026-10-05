"""Immutable paper exposure declarations, without execution or valuation.

Identity and venue are supplied by the trader and remain unverified. Effective
acceptance times do not establish exact durable availability or publication
eligibility. Quantity is optional context, never a sizing recommendation.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import re

from .models import canonical_json, text_digest
from .time import as_utc


TEXT_LIMITS = {
    "underlying": 128, "product_id": 256, "venue": 128,
    "quote_currency": 16, "horizon": 1_000, "quantity_unit": 64,
}
MAPPING_STATUS = "user_declared_unverified"
QUANTITY_PATTERN = r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
DECLARATION_FIELDS = (
    "underlying", "direction", "product_id", "venue", "expiry",
    "quote_currency", "horizon", "quantity", "quantity_unit",
)


def declaration_text(value: str, name: str, limit: int) -> str:
    """Validate a bounded declaration without trimming or normalizing it."""
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{name} must be nonblank and within its limit")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{name} must contain valid Unicode") from error
    return value


def quantity_string(value: str | None) -> str | None:
    """Accept only positive fixed-point decimal strings."""
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError("quantity must be a decimal string or null")
    # Bound the lexical form before Decimal parsing or arithmetic is attempted.
    if len(value) > 29 or re.fullmatch(QUANTITY_PATTERN, value) is None:
        raise ValueError("quantity must be a fixed-point decimal string without leading zeroes")
    integer, _, fraction = value.partition(".")
    if len(integer) + len(fraction) > 28 or len(fraction) > 12:
        raise ValueError("quantity exceeds the 28 digit or 12 fractional digit limit")
    parsed = Decimal(value)
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("quantity must be positive and finite")
    return value


def expiry_string(value: str | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("expiry must be a YYYY-MM-DD date or null")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("expiry must be an actual calendar date") from error
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class PaperPositionVersion:
    version_id: str
    position_id: str
    owner_id: str
    thesis_id: str
    approval_id: str
    underlying: str
    direction: str
    accepted_at: datetime
    parent_version_id: str | None = None
    paper: bool = True
    status: str = "open"
    product_id: str | None = None
    venue: str | None = None
    expiry: str | None = None
    quote_currency: str | None = None
    horizon: str | None = None
    quantity: str | None = None
    quantity_unit: str | None = None

    def __post_init__(self) -> None:
        for name in ("version_id", "position_id", "owner_id", "thesis_id", "approval_id"):
            declaration_text(getattr(self, name), name, 128)
        if self.parent_version_id is not None:
            declaration_text(self.parent_version_id, "parent_version_id", 128)
            if self.parent_version_id == self.version_id:
                raise ValueError("a position version cannot be its own parent")
        if self.paper is not True:
            raise ValueError("this contract accepts paper exposure only")
        if type(self.status) is not str or self.status not in ("open", "closed"):
            raise ValueError("status must be open or closed")
        if type(self.direction) is not str or self.direction not in ("long", "short"):
            raise ValueError("direction must be long or short")
        declaration_text(self.underlying, "underlying", TEXT_LIMITS["underlying"])
        for name in ("product_id", "venue", "quote_currency", "horizon", "quantity_unit"):
            value = getattr(self, name)
            if value is not None:
                declaration_text(value, name, TEXT_LIMITS[name])
        expiry_string(self.expiry)
        quantity_string(self.quantity)
        if (self.quantity is None) != (self.quantity_unit is None):
            raise ValueError("quantity and quantity_unit must be supplied together or both null")
        object.__setattr__(self, "accepted_at", as_utc(self.accepted_at))

    @property
    def mapping_status(self) -> str:
        return MAPPING_STATUS

    @property
    def missing_fields(self) -> tuple[str, ...]:
        # Expiry may be inapplicable. Without validated product classification
        # it cannot be labelled complete or missing by a guessed instrument type.
        return tuple(name for name in (
            "product_id", "venue", "quote_currency", "horizon", "quantity", "quantity_unit",
        ) if getattr(self, name) is None)

    @property
    def declaration_dict(self) -> dict:
        return {name: getattr(self, name) for name in DECLARATION_FIELDS}

    @property
    def digest(self) -> str:
        return text_digest(canonical_json(version_content(self)))


def version_content(value: PaperPositionVersion) -> dict:
    """Return detached canonical-digest input, without adding derived authority."""
    if not isinstance(value, PaperPositionVersion):
        raise TypeError("version content requires a paper position version")
    return {
        "version_id": value.version_id, "position_id": value.position_id,
        "owner_id": value.owner_id, "thesis_id": value.thesis_id,
        "approval_id": value.approval_id, "parent_version_id": value.parent_version_id,
        "paper": value.paper, "status": value.status,
        "accepted_at": value.accepted_at.isoformat(),
        "mapping_status": value.mapping_status,
        **value.declaration_dict,
    }


def validate_position_transition(previous: PaperPositionVersion,
                                 proposed: PaperPositionVersion) -> None:
    """Check lifecycle continuity, without granting owner or approval authority."""
    if not isinstance(previous, PaperPositionVersion) or not isinstance(proposed, PaperPositionVersion):
        raise TypeError("a transition requires paper position versions")
    if previous.status == "closed":
        raise ValueError("a closed paper position cannot be revised or reopened")
    for name in ("position_id", "owner_id", "thesis_id"):
        if getattr(previous, name) != getattr(proposed, name):
            raise ValueError("a position transition cannot change its identity or scope")
    if proposed.version_id == previous.version_id or proposed.parent_version_id != previous.version_id:
        raise ValueError("a position transition requires a new version linked to its predecessor")
    if proposed.accepted_at < previous.accepted_at:
        raise ValueError("a position transition cannot precede its predecessor")
    if proposed.status == "closed" and any(
        getattr(previous, name) != getattr(proposed, name) for name in DECLARATION_FIELDS
    ):
        raise ValueError("closing a position cannot silently revise exposure declarations")
