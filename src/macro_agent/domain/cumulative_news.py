"""Pinned cumulative news inputs, without evidence selection or authority.

The application supplies the complete protected selection and validates prior
documents against their original contexts. This module verifies the projected
envelope and citation identities. Prior model prose remains interpretation,
including when it was valid under a different approval or exposure snapshot.
"""

from datetime import datetime
from uuid import UUID

from .models import canonical_json, require_digest, text_digest
from .time import as_utc


CUMULATIVE_SCHEMA_VERSION = "retained-news-analysis-v2"
CUMULATIVE_PROMPT_VERSION = "retained-news-analysis-prompt-v3"
CUMULATIVE_POLICY_VERSION = "complete-retained-cumulative-news-v1"
MAX_CUMULATIVE_ITEMS = 1_000
CUMULATIVE_FIELDS = frozenset((
    "context_id", "digest", "cutoff", "policy_version", "reports", "analyses",
    "deferred_reports", "deferred_analyses", "gaps", "predecessor_context_id",
))
COMPARISON_RELATIONSHIPS = frozenset(("strengthens", "weakens", "offsets", "unresolved"))


def _text(value, field, limit=2_000, *, blank=False):
    if type(value) is not str or len(value) > limit or "\x00" in value:
        raise ValueError(f"{field} requires bounded text without NUL")
    if not blank and not value.strip():
        raise ValueError(f"{field} requires nonblank text")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError(f"{field} requires valid Unicode") from None
    return value


def _uuid(value, field):
    _text(value, field, 128)
    try:
        UUID(value)
    except (ValueError, AttributeError):
        raise ValueError(f"{field} requires a UUID string") from None


def _items(value, field):
    if type(value) is not list or len(value) > MAX_CUMULATIVE_ITEMS:
        raise ValueError(f"{field} exceeds its explicit array bound; do not truncate")
    return value


def _strings(value, field):
    values = [_text(item, field) for item in _items(value, field)]
    if len(set(values)) != len(values):
        raise ValueError(f"{field} must be unique")
    return values


def cumulative_digest(value: dict) -> str:
    """Hash the complete projection independently of its persisted identity.

    Preflight can reserve a temporary UUID. All other fields, including cutoff,
    lineage, source provenance, unavailable work and exact evidence, are hashed.
    This is a content identity, not proof of scope, permission or durable receipt.
    """
    if type(value) is not dict:
        raise ValueError("cumulative context requires an object")
    try:
        return text_digest(canonical_json({key: item for key, item in value.items()
                                          if key not in ("context_id", "digest")}))
    except (TypeError, UnicodeError, RecursionError, OverflowError):
        raise ValueError("cumulative context requires finite bounded JSON data") from None


def validate_cumulative_context(value: dict, focus: dict) -> tuple[dict, set]:
    """Return attributable report fields and comparable prior interpretation IDs.

    Large payloads are rejected by the complete-context bound in news_analysis.
    The generous collection bound is a second implementation guard, never a
    selection rule. No entry is silently dropped or promoted to verified fact.
    """
    if type(value) is not dict or set(value) != CUMULATIVE_FIELDS:
        raise ValueError("cumulative context requires exactly its documented fields")
    _uuid(value["context_id"], "cumulative context identity")
    if value["predecessor_context_id"] is not None:
        _uuid(value["predecessor_context_id"], "predecessor context identity")
    require_digest(value["digest"], "cumulative context digest")
    if value["digest"] != cumulative_digest(value):
        raise ValueError("cumulative context failed digest verification")
    _text(value["cutoff"], "cumulative cutoff", 128)
    try:
        as_utc(datetime.fromisoformat(value["cutoff"]))
    except (TypeError, ValueError):
        raise ValueError("cumulative cutoff requires an aware ISO instant") from None
    _text(value["policy_version"], "cumulative policy version", 128)
    reports = {focus["revision_id"]: focus}
    background_ids = set()
    for report in _items(value["reports"], "cumulative reports"):
        if type(report) is not dict or not {"revision_id", "title", "content"} <= set(report):
            raise ValueError("cumulative report requires retained revision identity and fields")
        identity = _text(report["revision_id"], "cumulative report identity", 128)
        _text(report["title"], "cumulative report title", 4_096)
        _text(report["content"], "cumulative report content", 16_384, blank=True)
        if identity in background_ids:
            raise ValueError("cumulative report identities must be unique")
        background_ids.add(identity)
        if identity in reports and any(report[field] != reports[identity][field]
                                       for field in ("title", "content")):
            raise ValueError("one source revision cannot supply contradictory retained fields")
        reports[identity] = report
    comparable_ids = set()
    analysis_ids = set()
    for analysis in _items(value["analyses"], "cumulative analyses"):
        required = {"analysis_id", "document", "original_status", "current_disposition",
                    "stale_reasons", "approval_id", "exposure_digest", "context_digest",
                    "source_revision_id"}
        if type(analysis) is not dict or not required <= set(analysis):
            raise ValueError("cumulative analysis requires pinned interpretation metadata")
        identity = _text(analysis["analysis_id"], "prior analysis identity", 128)
        if identity in analysis_ids:
            raise ValueError("prior analysis identities must be unique")
        analysis_ids.add(identity)
        for name in ("approval_id", "source_revision_id"):
            _text(analysis[name], f"prior analysis {name}", 128)
        for name in ("exposure_digest", "context_digest"):
            require_digest(analysis[name], f"prior analysis {name}")
        status = analysis["original_status"]
        if status is not None and (type(status) is not str or status not in (
                "analysed", "stale", "failed", "outcome_unknown")):
            raise ValueError("prior analysis original status is unsupported")
        disposition = analysis["current_disposition"]
        if type(disposition) is not str or disposition not in ("current", "stale", "unresolved"):
            raise ValueError("prior analysis current disposition is unsupported")
        _strings(analysis["stale_reasons"], "prior analysis stale reasons")
        document = analysis["document"]
        if document is not None and type(document) is not dict:
            raise ValueError("prior analysis document must be an object or null")
        if status in ("analysed", "stale"):
            if document is None or type(document.get("schema_version")) is not str or document.get(
                    "schema_version") not in ("retained-news-analysis-v1", CUMULATIVE_SCHEMA_VERSION):
                raise ValueError("prior analysed interpretation requires a supported document")
            comparable_ids.add(identity)
        elif status is None and document is not None:
            raise ValueError("unfinished prior work cannot contain a completed document")
        if disposition == "current" and (status != "analysed" or analysis["stale_reasons"]):
            raise ValueError("current prior interpretation must be analysed without stale reasons")
        if status == "stale" and disposition != "stale":
            raise ValueError("an originally stale interpretation must remain stale")
    for collection, key, supplied in (("deferred_reports", "revision_id", set(reports)),
                                      ("deferred_analyses", "analysis_id", analysis_ids)):
        seen = set()
        for item in _items(value[collection], collection):
            if type(item) is not dict or set(item) != {key, "reason"}:
                raise ValueError("deferred work requires exactly an identity and reason")
            identity = _text(item[key], "deferred identity", 128)
            _text(item["reason"], "deferred reason")
            if identity in seen or identity in supplied:
                raise ValueError("deferred work must have unique identities outside eligible inputs")
            seen.add(identity)
    _strings(value["gaps"], "cumulative gaps")
    return reports, comparable_ids
