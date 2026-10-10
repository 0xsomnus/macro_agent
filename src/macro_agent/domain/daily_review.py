"""Deterministic retained-evidence review, with no publication authority.

This is an internal value contract, not an HTTP schema or a source selector.
The caller supplies the complete selected input set, explicit limits and
conservative postcommit availability observations. It also owns permission,
owner scope, governing-state protection and current-disposition checks.
Availability observations are upper bounds, never exact commit timestamps.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json

from .models import canonical_json, normalize_json_object, require_digest, text_digest
from .news_analysis import validate_news_document
from .time import as_utc


SCHEMA_VERSION = "deterministic-daily-evidence-review-v1"


class ReviewCapacityExceeded(ValueError):
    """Complete context cannot fit; no evidence may be silently discarded."""


def _text(value, field):
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise ValueError(f"{field} requires nonblank text without NUL")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError(f"{field} requires valid Unicode") from None
    return value


def _texts(values, field):
    if type(values) not in (list, tuple):
        raise ValueError(f"{field} requires a list or tuple")
    result = tuple(_text(value, field) for value in values)
    if len(set(result)) != len(result):
        raise ValueError(f"{field} must be unique")
    return result


def _json(value, field):
    try:
        result = normalize_json_object(value)
        # normalize_json validates primitive types and finite numbers. Check
        # every decoded string too, including escaped NUL and lone surrogates.
        def check(item):
            if type(item) is str:
                if "\x00" in item:
                    raise ValueError("NUL is forbidden")
                item.encode("utf-8", errors="strict")
            elif type(item) is dict:
                for key, child in item.items():
                    check(key)
                    check(child)
            elif type(item) is list:
                for child in item:
                    check(child)
        check(json.loads(result))
        return result
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise ValueError(f"{field} requires unambiguous finite JSON object data") from None


def _instant(value):
    return value.isoformat() if value is not None else None


def _items(values, kind, limit, field):
    if type(values) not in (list, tuple):
        raise ValueError(f"{field} requires a list or tuple")
    if len(values) > limit:
        raise ReviewCapacityExceeded(f"{field} exceeds its explicit bound; do not truncate")
    result = tuple(values)
    if any(type(value) is not kind for value in result):
        raise ValueError(f"{field} requires {kind.__name__} values")
    return result


@dataclass(frozen=True, slots=True)
class DailyReviewPeriod:
    """New availability is (start, cutoff]; earlier availability is background."""

    start: datetime
    cutoff: datetime
    prepared_at: datetime

    def __post_init__(self):
        for name in ("start", "cutoff", "prepared_at"):
            object.__setattr__(self, name, as_utc(getattr(self, name)))
        if not self.start < self.cutoff <= self.prepared_at:
            raise ValueError("review requires start < cutoff <= actual preparation observation")


@dataclass(frozen=True, slots=True)
class DailyReviewLimits:
    """Explicit implementation bounds, not materiality or coverage policy."""

    reports: int
    analyses: int
    exposure_versions: int
    issues: int
    source_contracts: int
    encoded_bytes: int

    def __post_init__(self):
        for name in ("reports", "analyses", "exposure_versions", "issues", "source_contracts", "encoded_bytes"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError("review bounds must be explicit positive integers")


@dataclass(frozen=True, slots=True)
class SourceContractReference:
    source_id: str
    version_id: str
    digest: str

    def __post_init__(self):
        _text(self.source_id, "source identity")
        _text(self.version_id, "source contract version")
        require_digest(self.digest)


@dataclass(frozen=True, slots=True)
class DailyReviewScope:
    owner_id: str
    thesis_id: str
    approval_id: str
    interpretation_id: str
    exposure_digest: str
    exposure_version_ids: tuple[str, ...]
    source_contracts: tuple[SourceContractReference, ...]
    predecessor_context_id: str | None = None
    predecessor_assessment_id: str | None = None

    def __post_init__(self):
        for name in ("owner_id", "thesis_id", "approval_id", "interpretation_id"):
            _text(getattr(self, name), name)
        require_digest(self.exposure_digest, "complete exposure digest")
        object.__setattr__(self, "exposure_version_ids", _texts(self.exposure_version_ids, "exposure versions"))
        if type(self.source_contracts) not in (list, tuple):
            raise ValueError("source contracts require a list or tuple")
        contracts = tuple(self.source_contracts)
        if any(type(item) is not SourceContractReference for item in contracts):
            raise ValueError("source contract references required")
        if len({(item.source_id, item.version_id) for item in contracts}) != len(contracts):
            raise ValueError("each source contract identity must have one exact reference")
        object.__setattr__(self, "source_contracts", contracts)
        for name in ("predecessor_context_id", "predecessor_assessment_id"):
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class RetainedReport:
    revision_id: str
    report_id: str
    source_id: str
    source_contract_version_id: str
    source_contract_digest: str
    payload_json: str
    payload_digest: str
    received_at: datetime
    availability_witness_at: datetime | None

    def __post_init__(self):
        for name in ("revision_id", "report_id", "source_id", "source_contract_version_id"):
            _text(getattr(self, name), name)
        require_digest(self.source_contract_digest)
        require_digest(self.payload_digest)
        content = _json(self.payload_json, "retained payload")
        payload = json.loads(content)
        for name in ("title", "url"):
            _text(payload.get(name), f"retained {name}")
        if type(payload.get("content")) is not str:
            raise ValueError("retained content requires a string, including an explicit empty excerpt")
        if text_digest(content) != self.payload_digest:
            raise ValueError("retained payload failed digest verification")
        object.__setattr__(self, "payload_json", content)
        object.__setattr__(self, "received_at", as_utc(self.received_at))
        if self.availability_witness_at is not None:
            witness = as_utc(self.availability_witness_at)
            if witness < self.received_at:
                raise ValueError("report availability observation cannot precede receipt")
            object.__setattr__(self, "availability_witness_at", witness)


@dataclass(frozen=True, slots=True)
class RetainedNewsAnalysis:
    analysis_id: str
    owner_id: str
    thesis_id: str
    source_revision_id: str
    created_at: datetime
    finished_at: datetime | None
    availability_witness_at: datetime | None
    original_status: str | None
    original_stale_reasons: tuple[str, ...]
    current_disposition: str
    current_stale_reasons: tuple[str, ...]
    context_json: str
    document_json: str | None
    costs_json: str
    stop_reason: str | None = None

    def __post_init__(self):
        for name in ("analysis_id", "owner_id", "thesis_id", "source_revision_id"):
            _text(getattr(self, name), name)
        for name in ("original_stale_reasons", "current_stale_reasons"):
            object.__setattr__(self, name, _texts(getattr(self, name), name))
        if self.original_status not in (None, "analysed", "stale", "failed", "outcome_unknown"):
            raise ValueError("original status must describe the retained result or explicitly absent result")
        if self.current_disposition not in ("current", "stale", "unresolved"):
            raise ValueError("current disposition must be explicit")
        if self.current_disposition == "current" and (
                self.original_status != "analysed" or self.original_stale_reasons or self.current_stale_reasons):
            raise ValueError("a current analysis cannot discard stale reasons or an unresolved original outcome")
        if self.current_disposition == "stale" and not (
                self.original_status == "stale" or self.original_stale_reasons or self.current_stale_reasons):
            raise ValueError("stale disposition requires retained reasons or an originally stale result")
        if self.original_status == "stale" and self.current_disposition != "stale":
            raise ValueError("an originally stale result cannot be reactivated")
        object.__setattr__(self, "created_at", as_utc(self.created_at))
        if self.finished_at is not None:
            finished = as_utc(self.finished_at)
            if finished < self.created_at:
                raise ValueError("analysis finish cannot precede admission")
            object.__setattr__(self, "finished_at", finished)
        if (self.original_status is None) != (self.finished_at is None):
            raise ValueError("retained result status and finish must be both present or both absent")
        if self.availability_witness_at is not None:
            witness = as_utc(self.availability_witness_at)
            if witness < (self.finished_at or self.created_at):
                raise ValueError("analysis availability observation cannot precede its recorded result/admission")
            object.__setattr__(self, "availability_witness_at", witness)
        object.__setattr__(self, "context_json", _json(self.context_json, "original analysis context"))
        if self.document_json is not None:
            document = validate_news_document(self.document_json, json.loads(self.context_json))
            object.__setattr__(self, "document_json", canonical_json(document))
        if self.original_status in ("analysed", "stale") and self.document_json is None:
            raise ValueError("analysed and stale outcomes require their retained document")
        if self.original_status is None and self.document_json is not None:
            raise ValueError("an absent result cannot contain a document")
        if self.stop_reason is not None:
            _text(self.stop_reason, "stop reason")
        costs = _json(self.costs_json, "cost observations")
        values = json.loads(costs)
        if set(values) != {"reported_cost_usd", "estimated_cost_usd"}:
            raise ValueError("reported and estimated costs must remain separate and explicitly nullable")
        for cost in values.values():
            if cost is None:
                continue
            if type(cost) is not str:
                raise ValueError("cost observations require decimal text or null")
            try:
                amount = Decimal(cost)
                if not amount.is_finite() or amount < 0:
                    raise InvalidOperation
            except InvalidOperation:
                raise ValueError("cost observations require finite nonnegative decimal text") from None
        object.__setattr__(self, "costs_json", costs)


@dataclass(frozen=True, slots=True)
class ReviewIssue:
    """Exact retained diagnostic data, without a synthesized factual claim."""

    issue_id: str
    kind: str
    detail_json: str
    source_id: str | None = None
    analysis_id: str | None = None

    def __post_init__(self):
        _text(self.issue_id, "issue identity")
        if self.kind not in ("coverage_gap", "unresolved_work"):
            raise ValueError("review issue must be coverage_gap or unresolved_work")
        object.__setattr__(self, "detail_json", _json(self.detail_json, "retained diagnostic"))
        for name in ("source_id", "analysis_id"):
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class DailyReviewCandidate:
    """Immutable inspection content; no current pointer, notice or approval."""

    content_json: str

    def __post_init__(self):
        object.__setattr__(self, "content_json", _json(self.content_json, "daily review"))

    @property
    def digest(self):
        return text_digest(self.content_json)

    def to_dict(self):
        """Return a detached copy so display code cannot mutate retained state."""
        return json.loads(self.content_json)


def _classification(witness, period):
    if witness is None:
        return "deferred", "availability_unproven"
    if witness > period.cutoff:
        return "deferred", "available_after_cutoff"
    return ("new" if witness > period.start else "background"), None


def build_daily_review(*, period: DailyReviewPeriod, scope: DailyReviewScope,
                       reports: tuple[RetainedReport, ...], analyses: tuple[RetainedNewsAnalysis, ...],
                       issues: tuple[ReviewIssue, ...], limits: DailyReviewLimits) -> DailyReviewCandidate:
    """Assemble every supplied input or reject; never fetch, infer or truncate.

    Retained documents are validated against their original contexts, including
    historical exposure, rather than rewritten to fit today's approved thesis.
    Current disposition is a caller observation at preparation, which may be
    later than the evidence cutoff. This function does not establish it.
    """
    if type(period) is not DailyReviewPeriod or type(scope) is not DailyReviewScope or type(limits) is not DailyReviewLimits:
        raise ValueError("review requires typed period, scope and explicit limits")
    reports = _items(reports, RetainedReport, limits.reports, "reports")
    analyses = _items(analyses, RetainedNewsAnalysis, limits.analyses, "analyses")
    issues = _items(issues, ReviewIssue, limits.issues, "issues")
    if len(scope.exposure_version_ids) > limits.exposure_versions or len(scope.source_contracts) > limits.source_contracts:
        raise ReviewCapacityExceeded("complete exposure or source manifest exceeds its bound; do not truncate")
    contracts = {(item.source_id, item.version_id): item for item in scope.source_contracts}
    source_ids = {item.source_id for item in scope.source_contracts}
    report_map = {item.revision_id: item for item in reports}
    analysis_map = {item.analysis_id: item for item in analyses}
    if len(report_map) != len(reports) or len(analysis_map) != len(analyses) or len({item.issue_id for item in issues}) != len(issues):
        raise ValueError("retained report, analysis and issue identities must be unique")
    report_sections = {name: [] for name in ("new", "background", "deferred")}
    for report in sorted(reports, key=lambda item: item.revision_id):
        if any(value is not None and value > period.prepared_at for value in
               (report.received_at, report.availability_witness_at)):
            raise ValueError("report receipt and availability observations cannot follow actual preparation")
        contract = contracts.get((report.source_id, report.source_contract_version_id))
        if contract is None or contract.digest != report.source_contract_digest:
            raise ValueError("report must reference its selected exact source contract")
        section, reason = _classification(report.availability_witness_at, period)
        report_sections[section].append({"revision_id": report.revision_id, "report_id": report.report_id,
            "source_id": report.source_id, "source_contract_version_id": report.source_contract_version_id,
            "source_contract_digest": report.source_contract_digest, "payload_digest": report.payload_digest,
            "payload": json.loads(report.payload_json), "received_at": _instant(report.received_at),
            "availability_witness_at": _instant(report.availability_witness_at), "deferred_reason": reason})
    analysis_sections = {name: [] for name in ("new", "background", "deferred")}
    unresolved = []
    unknown_cost = []
    for analysis in sorted(analyses, key=lambda item: item.analysis_id):
        report = report_map.get(analysis.source_revision_id)
        if report is None or (analysis.owner_id, analysis.thesis_id) != (scope.owner_id, scope.thesis_id):
            raise ValueError("analysis must reference a supplied report and the selected private owner/thesis")
        if any(value is not None and value > period.prepared_at for value in
               (analysis.created_at, analysis.finished_at, analysis.availability_witness_at)):
            raise ValueError("analysis admission, finish and availability observations cannot follow actual preparation")
        if analysis.created_at < report.received_at:
            raise ValueError("analysis admission cannot precede receipt of its retained source")
        context = json.loads(analysis.context_json)
        source = context.get("source", {})
        thesis = context.get("approved_thesis", {})
        payload = json.loads(report.payload_json)
        if (type(source) is not dict or type(thesis) is not dict
                or source.get("revision_id") != report.revision_id
                or source.get("digest") != report.payload_digest
                or source.get("source_key") != report.source_id
                or thesis.get("thesis_id") != scope.thesis_id
                or any(source.get(field) != payload.get(field) for field in ("title", "content", "url", "published_at"))):
            raise ValueError("analysis original context must bind the exact supplied retained payload and thesis")
        if analysis.current_disposition == "current":
            for name in ("approval_id", "interpretation_id"):
                if name in thesis and thesis[name] != getattr(scope, name):
                    raise ValueError("current analysis cannot contradict selected approval or interpretation identity")
            positions = context.get("positions")
            if type(positions) is not list or any(type(item) is not dict for item in positions):
                raise ValueError("current analysis requires complete original position-version references")
            versions = _texts([item.get("version_id") for item in positions], "original exposure versions")
            if set(versions) != set(scope.exposure_version_ids):
                raise ValueError("current analysis must bind the complete selected exposure versions")
        section, reason = _classification(analysis.availability_witness_at, period)
        if section != "deferred":
            source_section, source_reason = _classification(report.availability_witness_at, period)
            if source_section == "deferred":
                section, reason = "deferred", f"source_{source_reason}"
        costs = json.loads(analysis.costs_json)
        if costs["reported_cost_usd"] is None:
            unknown_cost.append(analysis.analysis_id)
        analysis_sections[section].append({"analysis_id": analysis.analysis_id,
            "source_revision_id": analysis.source_revision_id, "created_at": _instant(analysis.created_at),
            "finished_at": _instant(analysis.finished_at),
            "availability_witness_at": _instant(analysis.availability_witness_at),
            "original_status": analysis.original_status, "original_stale_reasons": list(analysis.original_stale_reasons),
            "current_disposition": analysis.current_disposition,
            "current_stale_reasons": list(analysis.current_stale_reasons),
            "disposition_observed_at": _instant(period.prepared_at), "stop_reason": analysis.stop_reason,
            "original_context": context, "document": json.loads(analysis.document_json) if analysis.document_json else None,
            "costs": costs, "deferred_reason": reason})
        if analysis.original_status in (None, "failed", "outcome_unknown"):
            unresolved.append(analysis.analysis_id)
    diagnostics = []
    for issue in sorted(issues, key=lambda item: item.issue_id):
        if (issue.source_id is not None and issue.source_id not in source_ids
                or issue.analysis_id is not None and issue.analysis_id not in analysis_map):
            raise ValueError("diagnostics must reference supplied source/analysis identities")
        if (issue.source_id is not None and issue.analysis_id is not None
                and report_map[analysis_map[issue.analysis_id].source_revision_id].source_id != issue.source_id):
            raise ValueError("diagnostic source must match the referenced analysis source")
        diagnostics.append({"issue_id": issue.issue_id, "kind": issue.kind,
            "source_id": issue.source_id, "analysis_id": issue.analysis_id, "detail": json.loads(issue.detail_json)})
    content = canonical_json({"schema_version": SCHEMA_VERSION,
        "period": {"start_exclusive": _instant(period.start), "cutoff_inclusive": _instant(period.cutoff),
                   "prepared_at": _instant(period.prepared_at)},
        "scope": {"owner_id": scope.owner_id, "thesis_id": scope.thesis_id, "approval_id": scope.approval_id,
            "interpretation_id": scope.interpretation_id, "exposure_digest": scope.exposure_digest,
            "exposure_version_ids": list(scope.exposure_version_ids),
            "source_contracts": [{"source_id": item.source_id, "version_id": item.version_id, "digest": item.digest}
                                 for item in sorted(scope.source_contracts, key=lambda item: (item.source_id, item.version_id))],
            "predecessor_context_id": scope.predecessor_context_id,
            "predecessor_assessment_id": scope.predecessor_assessment_id},
        "reports": report_sections, "analyses": analysis_sections, "issues": diagnostics,
        "unresolved_analysis_ids": unresolved, "unknown_reported_cost_analysis_ids": unknown_cost,
        "new_eligible_report_count": len(report_sections["new"]),
        "limitations": ["No new eligible reports does not establish that no market events occurred.",
            "Exact retained quotations establish attribution, not factual truth or investment usefulness.",
            "Current disposition is a caller observation at preparation, not reconstructed cutoff state.",
            "Cross-source independence, current macro regime and market expectations remain unverified.",
            "This deterministic review grants no approval, publication, notification or paid-retry authority."],
        "assembly_inference_calls": 0, "assembly_inference_cost_usd": "0"})
    if len(content.encode("utf-8")) > limits.encoded_bytes:
        raise ReviewCapacityExceeded("daily review exceeds its explicit encoded bound; do not truncate")
    return DailyReviewCandidate(content)
