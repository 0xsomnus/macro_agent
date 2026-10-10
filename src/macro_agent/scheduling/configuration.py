"""Explicit internal watch configuration, with no inferred operating policy."""

from datetime import date, datetime, time, timezone
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from macro_agent.domain.daily_review import DailyReviewLimits
from macro_agent.domain.models import canonical_json, require_digest
from macro_agent.providers import PROVIDER_IDS, is_explicit_model_id
from macro_agent.theses.service import _uuid


SCHEMA_VERSION = "internal-desk-watch-v1"
FIELDS = {"schema_version", "approval_id", "exposure_digest", "sources", "provider", "model_id",
    "model_configuration", "capture_interval_seconds", "analysis_interval_seconds", "lease_seconds",
    "timezone", "daily_time", "daily_start_date", "daily_backlog_limit", "context_bounds", "allowances"}


def integer(value, field, *, zero=False):
    if type(value) is not int or value < (0 if zero else 1) or value > 2**31 - 1:
        raise ValueError(f"{field} requires an explicit bounded integer")
    return value


def json_object(value, field):
    if type(value) is not dict:
        raise ValueError(f"{field} requires an explicit JSON object")
    try:
        encoded = canonical_json(value)
        encoded.encode("utf-8", errors="strict")
        if "\\u0000" in encoded:
            raise ValueError("NUL is forbidden")
        return json.loads(encoded)
    except (ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        raise ValueError(f"{field} requires finite unambiguous JSON object data") from None


def configuration(value):
    value = json_object(value, "watch configuration")
    if set(value) != FIELDS or value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("watch configuration requires exactly its documented fields and schema version")
    _uuid(value["approval_id"], "approval_id")
    require_digest(value["exposure_digest"], "exposure_digest")
    sources = value["sources"]
    if type(sources) is not list or not 1 <= len(sources) <= 16:
        raise ValueError("an explicit source manifest with 1 to 16 entries is required")
    for item in sources:
        if type(item) is not dict or set(item) != {"source_id", "contract_digest"}:
            raise ValueError("each source requires exact identity and contract digest")
        if type(item["source_id"]) is not str or not item["source_id"].strip() or len(item["source_id"]) > 128:
            raise ValueError("source identity must be bounded nonblank text")
        require_digest(item["contract_digest"])
    if len({item["source_id"] for item in sources}) != len(sources):
        raise ValueError("watch source identities must be unique")
    if type(value["provider"]) is not str or value["provider"] not in PROVIDER_IDS:
        raise ValueError("an explicitly supported provider is required")
    if not is_explicit_model_id(value["model_id"]):
        raise ValueError("an explicit model identity is required")
    value["model_configuration"] = json_object(value["model_configuration"], "model configuration")
    from macro_agent.monitoring.analysis import model_configuration
    context = value["model_configuration"].get("context")
    if context not in ("one_retained_report_and_approved_paper_book", "complete_retained_context"):
        raise ValueError("model context mode must be explicitly reviewed")
    expected = (model_configuration(value["provider"], cumulative=True)
        if context == "complete_retained_context" else model_configuration(value["provider"]))
    if set(value["model_configuration"]) != set(expected) or value["model_configuration"] != expected:
        raise ValueError("model configuration must exactly match the current safe server configuration")
    for name in ("capture_interval_seconds", "analysis_interval_seconds", "lease_seconds", "daily_backlog_limit"):
        integer(value[name], name)
    if type(value["timezone"]) is not str:
        raise ValueError("an explicit IANA timezone is required")
    try:
        ZoneInfo(value["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("an explicit valid IANA timezone is required") from None
    if type(value["daily_time"]) is not str or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value["daily_time"]) is None:
        raise ValueError("daily time requires exact HH:MM local time")
    try:
        if type(value["daily_start_date"]) is not str or date.fromisoformat(value["daily_start_date"]).isoformat() != value["daily_start_date"]:
            raise ValueError
    except ValueError:
        raise ValueError("daily_start_date requires exact YYYY-MM-DD") from None
    bounds = value["context_bounds"]
    if type(bounds) is not dict or set(bounds) != {"reports", "analyses", "exposure_versions", "issues", "source_contracts", "encoded_bytes"}:
        raise ValueError("all context bounds must be explicit")
    for name, bound in bounds.items():
        integer(bound, name)
    DailyReviewLimits(**bounds)
    if bounds["analyses"] > 1000:
        raise ValueError("retained analysis observation bound cannot exceed 1000")
    if len(sources) > bounds["source_contracts"]:
        raise ValueError("complete source manifest exceeds its explicit bound")
    allowances = value["allowances"]
    if type(allowances) is not dict or set(allowances) != {"window_seconds", "analysis_dispatches", "inflight_slots", "unresolved_slots"}:
        raise ValueError("all additional per-watch allowances must be explicit")
    integer(allowances["window_seconds"], "window_seconds")
    for name in ("analysis_dispatches", "inflight_slots", "unresolved_slots"):
        integer(allowances[name], name, zero=True)
    return value


def scheduled_at(local_date, config):
    """Reject DST ambiguity/gaps instead of silently choosing a clock policy."""
    zone = ZoneInfo(config["timezone"])
    local = datetime.combine(local_date, time.fromisoformat(config["daily_time"]))
    first = local.replace(tzinfo=zone, fold=0)
    second = local.replace(tzinfo=zone, fold=1)
    if first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local:
        raise ValueError("daily local time does not exist; review the schedule")
    if first.utcoffset() != second.utcoffset():
        raise ValueError("daily local time is ambiguous; review the schedule")
    return first.astimezone(timezone.utc)
