"""Daily publication rules, preserving exact retained evidence and its labels.

The candidate is distinct from an urgent factual notice. Quiet days are valid.
The application supplies protected present dependencies and owns persistence.
"""

from dataclasses import dataclass
from datetime import datetime
import json
from uuid import UUID

from .daily_review import (
    DailyReviewLimits, DailyReviewPeriod, DailyReviewScope, RetainedNewsAnalysis,
    RetainedReport, ReviewIssue, SourceContractReference, build_daily_review,
)
from .models import canonical_json, normalize_json_object, require_digest, require_text, text_digest
from .publication import PublicationDecision
from .time import as_utc


KIND = "daily_evidence_review"


def _uuid(value, name):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError(f"{name} requires a canonical UUID")


def _time(value):
    if type(value) is not str:
        raise ValueError("retained time requires ISO text")
    return as_utc(datetime.fromisoformat(value))


def _optional_time(value):
    return None if value is None else _time(value)


def validate_daily_content(content_json):
    """Rebuild the existing contract; reject omitted, added or relabelled fields.

    This verifies attribution and structural fidelity, not factual truth. The
    original contexts remain mandatory so historical model documents are checked
    against their own inputs rather than today's approved thesis.
    """
    normalized = normalize_json_object(content_json)
    content = json.loads(normalized)
    try:
        period = DailyReviewPeriod(*(_time(content["period"][name]) for name in
            ("start_exclusive", "cutoff_inclusive", "prepared_at")))
        original_scope = content["scope"]
        scope = DailyReviewScope(
            original_scope["owner_id"], original_scope["thesis_id"],
            original_scope["approval_id"], original_scope["interpretation_id"],
            original_scope["exposure_digest"], original_scope["exposure_version_ids"],
            tuple(SourceContractReference(**item) for item in original_scope["source_contracts"]),
            original_scope["predecessor_context_id"], original_scope["predecessor_assessment_id"])
        reports = []
        analyses = []
        for section in ("new", "background", "deferred"):
            for item in content["reports"][section]:
                reports.append(RetainedReport(item["revision_id"], item["report_id"],
                    item["source_id"], item["source_contract_version_id"],
                    item["source_contract_digest"], canonical_json(item["payload"]),
                    item["payload_digest"], _time(item["received_at"]),
                    _optional_time(item["availability_witness_at"])))
            for item in content["analyses"][section]:
                analyses.append(RetainedNewsAnalysis(item["analysis_id"], scope.owner_id,
                    scope.thesis_id, item["source_revision_id"], _time(item["created_at"]),
                    _optional_time(item["finished_at"]), _optional_time(item["availability_witness_at"]),
                    item["original_status"], item["original_stale_reasons"],
                    item["current_disposition"], item["current_stale_reasons"],
                    canonical_json(item["original_context"]),
                    canonical_json(item["document"]) if item["document"] is not None else None,
                    canonical_json(item["costs"]), item["stop_reason"]))
        issues = tuple(ReviewIssue(item["issue_id"], item["kind"], canonical_json(item["detail"]),
            item["source_id"], item["analysis_id"]) for item in content["issues"])
        # These are validation capacities derived from the complete artifact,
        # never a selection policy or an operational default.
        limits = DailyReviewLimits(max(1, len(reports)), max(1, len(analyses)),
            max(1, len(scope.exposure_version_ids)), max(1, len(issues)),
            max(1, len(scope.source_contracts)), max(1, len(normalized.encode("utf-8"))))
        rebuilt = build_daily_review(period=period, scope=scope, reports=tuple(reports),
            analyses=tuple(analyses), issues=issues, limits=limits)
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError("daily publication requires the complete retained review contract") from error
    if rebuilt.content_json != normalized:
        raise ValueError("daily publication cannot change retained fields, classifications or analysis labels")
    return normalized


@dataclass(frozen=True, slots=True)
class DailyPublicationCandidate:
    command_id: str
    owner_id: str
    thesis_id: str
    brief_id: str
    review_id: str
    context_id: str
    cutoff: datetime
    review_digest: str
    approval_id: str
    exposure_digest: str
    expected_generation: int
    content_json: str

    def __post_init__(self):
        for name in ("command_id", "owner_id", "thesis_id", "review_id", "context_id", "approval_id"):
            _uuid(getattr(self, name), name)
        require_text(self.brief_id, "brief_id")
        if len(self.brief_id) > 255:
            raise ValueError("daily brief identity exceeds its record bound")
        require_digest(self.review_digest, "review digest")
        require_digest(self.exposure_digest, "exposure digest")
        if type(self.expected_generation) is not int or self.expected_generation < 0:
            raise ValueError("daily publication generation requires a nonnegative integer")
        object.__setattr__(self, "cutoff", as_utc(self.cutoff))
        content_json = validate_daily_content(self.content_json)
        object.__setattr__(self, "content_json", content_json)
        content = json.loads(content_json)
        scope = content["scope"]
        if (text_digest(content_json) != self.review_digest
                or _time(content["period"]["cutoff_inclusive"]) != self.cutoff
                or any(scope[name] != getattr(self, name) for name in
                       ("owner_id", "thesis_id", "approval_id", "exposure_digest"))):
            raise ValueError("daily publication must bind the exact retained review and scope")

    @property
    def assessment_id(self):
        return "daily:" + self.review_id

    @property
    def payload(self):
        return canonical_json({"kind": KIND, "command_id": self.command_id,
            "assessment_id": self.assessment_id, "owner_id": self.owner_id,
            "thesis_id": self.thesis_id, "brief_id": self.brief_id,
            "review_id": self.review_id, "context_id": self.context_id,
            "cutoff": self.cutoff.isoformat(), "review_digest": self.review_digest,
            "approval_id": self.approval_id, "exposure_digest": self.exposure_digest,
            "expected_generation": self.expected_generation, "content": json.loads(self.content_json)})

    @property
    def digest(self):
        return text_digest(self.payload)

    @property
    def intent_id(self):
        return "notice:" + text_digest(canonical_json([self.owner_id, self.brief_id, self.assessment_id]))


@dataclass(frozen=True, slots=True)
class DailyPublicationState:
    owner_id: str
    thesis_id: str
    generation: int
    changed_at: datetime
    latest_review_id: str | None
    latest_review_cutoff: datetime | None
    latest_published_cutoff: datetime | None
    stale_reasons: tuple[str, ...]

    def __post_init__(self):
        _uuid(self.owner_id, "owner_id")
        _uuid(self.thesis_id, "thesis_id")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("daily generation requires a nonnegative integer")
        object.__setattr__(self, "changed_at", as_utc(self.changed_at))
        if (self.latest_review_id is None) != (self.latest_review_cutoff is None):
            raise ValueError("latest daily review identity and cutoff must be paired")
        if self.latest_review_id is not None:
            _uuid(self.latest_review_id, "latest_review_id")
        for name in ("latest_review_cutoff", "latest_published_cutoff"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, as_utc(getattr(self, name)))
        if type(self.stale_reasons) is not tuple or len(set(self.stale_reasons)) != len(self.stale_reasons):
            raise ValueError("daily dependency reasons require a unique immutable tuple")
        for reason in self.stale_reasons:
            require_text(reason, "stale reason")


def decide_daily_publication(candidate, current, at):
    """Decide under protection; a retry separately reuses its saved decision."""
    if type(candidate) is not DailyPublicationCandidate or type(current) is not DailyPublicationState:
        raise TypeError("daily publication requires its separate typed contract")
    at = as_utc(at)
    if (candidate.owner_id, candidate.thesis_id) != (current.owner_id, current.thesis_id):
        raise PermissionError("daily publication belongs to a different private stream")
    prepared = _time(json.loads(candidate.content_json)["period"]["prepared_at"])
    if at < max(candidate.cutoff, prepared, current.changed_at) or (
            current.latest_review_cutoff is not None and at < current.latest_review_cutoff):
        raise ValueError("daily publication cannot precede its protected input observations")
    if candidate.expected_generation > current.generation:
        raise ValueError("daily publication cannot claim an unobserved generation")
    if current.stale_reasons:
        return PublicationDecision("superseded", tuple(sorted(current.stale_reasons)), True)
    if (candidate.review_id, candidate.cutoff) != (current.latest_review_id, current.latest_review_cutoff):
        return PublicationDecision("superseded", ("newer_retained_review",), False)
    if current.latest_published_cutoff is not None and candidate.cutoff <= current.latest_published_cutoff:
        return PublicationDecision("superseded", ("already_published_cutoff",), False)
    if candidate.expected_generation != current.generation:
        return PublicationDecision("superseded", ("newer_publication",), False)
    return PublicationDecision("current", ("all_dependencies_current",), False)
