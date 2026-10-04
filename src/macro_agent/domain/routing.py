"""Deterministic routing controls, independent of models and delivery.

Screening values are supplied observations, not an implemented classifier.
Evidence weights, windows, and thresholds below exercise synthetic fixtures;
they are not calibrated market materiality or notification rules.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from math import fsum, isfinite
from typing import Iterable

from .time import as_utc


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class Route(str, Enum):
    INVESTIGATE = "investigate"
    UNRESOLVED_QUEUE = "unresolved_queue"
    AUDIT_ONLY = "audit_only"


class RoutingState(str, Enum):
    RESOLVED_LOW = "resolved_low"
    POTENTIAL_OR_UNRESOLVED = "potential_or_unresolved"


def _boolean(value: object, name: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a bool")


def _identity(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def _finite_number(value: object, name: str) -> float:
    # bool is an int subclass; accepting it would hide malformed contracts.
    if type(value) not in (int, float):
        raise TypeError(f"{name} must be a finite int or float")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be finite") from error
    if not isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


@dataclass(frozen=True, slots=True)
class Screening:
    resolved: bool
    credible: bool
    urgent: bool
    potential_severity: Severity
    thesis_impact: bool
    trade_impact: bool
    plausible_transmission: bool
    broad_disruption: bool
    novel: bool
    classifier_available: bool

    def __post_init__(self) -> None:
        for name in (
            "resolved", "credible", "urgent", "thesis_impact", "trade_impact",
            "plausible_transmission", "broad_disruption", "novel",
            "classifier_available",
        ):
            _boolean(getattr(self, name), name)
        if not isinstance(self.potential_severity, (str, Severity)):
            raise TypeError("potential_severity must be a Severity or severity string")
        object.__setattr__(self, "potential_severity", Severity(self.potential_severity))


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    route: Route
    early_notice: bool
    analysis_required: bool
    state: RoutingState
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.route, Route) or not isinstance(self.state, RoutingState):
            raise TypeError("routing decision requires Route and RoutingState enums")
        _boolean(self.early_notice, "early_notice")
        _boolean(self.analysis_required, "analysis_required")
        if type(self.reasons) is not tuple or not self.reasons:
            raise ValueError("reasons must be a nonempty immutable tuple")
        for reason in self.reasons:
            _identity(reason, "reason")
        if self.analysis_required != (self.route == Route.INVESTIGATE):
            raise ValueError("analysis_required must agree with the investigation route")
        if self.early_notice and self.route != Route.INVESTIGATE:
            raise ValueError("an early notice requires an investigation route")
        if (self.state == RoutingState.RESOLVED_LOW) != (self.route == Route.AUDIT_ONLY):
            raise ValueError("only an audit-only decision may be resolved low")


def route_event(screening: Screening) -> RoutingDecision:
    """Choose a control route without deciding a final portfolio conclusion.

An early-notice result is eligibility only. Supported facts, rights, freshness,
and the publication authority checks still apply before any interruption.
"""
    if not isinstance(screening, Screening):
        raise TypeError("screening must be a Screening record")
    impact = screening.thesis_impact or screening.trade_impact
    severe_route = (
        screening.credible
        and screening.potential_severity in (Severity.HIGH, Severity.EXTREME)
        and (screening.plausible_transmission or screening.broad_disruption)
    )
    unresolved = not screening.classifier_available or not screening.resolved
    if impact or severe_route:
        route = Route.INVESTIGATE
    elif unresolved:
        route = Route.UNRESOLVED_QUEUE
    else:
        route = Route.AUDIT_ONLY

    reasons = []
    if not screening.classifier_available:
        reasons.append("classifier_unavailable")
    if not screening.resolved:
        reasons.append("screening_unresolved")
    if screening.thesis_impact:
        reasons.append("thesis_impact_candidate")
    if screening.trade_impact:
        reasons.append("trade_impact_candidate")
    if severe_route:
        reasons.append("credible_severe_surprise")
        if screening.plausible_transmission:
            reasons.append("plausible_transmission")
        if screening.broad_disruption:
            reasons.append("broad_disruption")
    if route == Route.AUDIT_ONLY:
        reasons.append("resolved_without_significance_candidate")
    # Novelty is deliberately absent from every escalation predicate.
    return RoutingDecision(
        route=route,
        early_notice=screening.credible and screening.urgent and (impact or severe_route),
        analysis_required=route == Route.INVESTIGATE,
        state=(
            RoutingState.RESOLVED_LOW if route == Route.AUDIT_ONLY
            else RoutingState.POTENTIAL_OR_UNRESOLVED
        ),
        reasons=tuple(reasons),
    )


@dataclass(frozen=True, slots=True)
class EvidenceContribution:
    """One synthetic contribution for an underlying event and driver.

This record has no revision field. Conflicting contributions for the same
eligible event identity require explicit upstream revision resolution.
"""

    event_id: str
    driver_id: str
    known_at: datetime
    signed_fixture_weight: float

    def __post_init__(self) -> None:
        _identity(self.event_id, "event_id")
        _identity(self.driver_id, "driver_id")
        object.__setattr__(self, "known_at", as_utc(self.known_at))
        object.__setattr__(
            self, "signed_fixture_weight",
            _finite_number(self.signed_fixture_weight, "signed_fixture_weight"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceAccumulation:
    event_ids: tuple[str, ...]
    signed_fixture_score: float
    material: bool

    def __post_init__(self) -> None:
        if type(self.event_ids) is not tuple:
            raise TypeError("event_ids must be an immutable tuple")
        for event_id in self.event_ids:
            _identity(event_id, "event_id")
        if tuple(sorted(set(self.event_ids))) != self.event_ids:
            raise ValueError("event_ids must be unique and sorted")
        object.__setattr__(
            self, "signed_fixture_score",
            _finite_number(self.signed_fixture_score, "signed_fixture_score"),
        )
        _boolean(self.material, "material")


def accumulate_evidence(
    contributions: Iterable[EvidenceContribution],
    driver_id: str,
    cutoff: datetime,
    window_seconds: int,
    threshold: float,
) -> EvidenceAccumulation:
    """Accumulate distinct eligible developments and signed offsets.

    The window includes both boundaries and excludes records known after the
    cutoff. Identical duplicates add no weight. Threshold and weights are
    fixture-only: this result cannot authorize a production notification.
    """
    _identity(driver_id, "driver_id")
    upper = as_utc(cutoff)
    if type(window_seconds) is not int:
        raise TypeError("window_seconds must be an int")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    fixture_threshold = _finite_number(threshold, "threshold")
    if fixture_threshold <= 0:
        raise ValueError("threshold must be positive")
    try:
        lower = upper - timedelta(seconds=window_seconds)
    except OverflowError as error:
        raise ValueError("window exceeds the supported datetime range") from error

    distinct: dict[str, EvidenceContribution] = {}
    for contribution in contributions:
        if not isinstance(contribution, EvidenceContribution):
            raise TypeError("contributions must contain EvidenceContribution records")
        if contribution.driver_id != driver_id or not lower <= contribution.known_at <= upper:
            continue
        previous = distinct.get(contribution.event_id)
        if previous is not None and previous != contribution:
            raise ValueError("conflicting duplicate requires explicit event revision resolution")
        distinct[contribution.event_id] = contribution

    event_ids = tuple(sorted(distinct))
    try:
        score = fsum(distinct[event_id].signed_fixture_weight for event_id in event_ids)
    except OverflowError as error:
        raise ValueError("accumulated fixture score must be finite") from error
    return EvidenceAccumulation(event_ids, score, abs(score) >= fixture_threshold)
