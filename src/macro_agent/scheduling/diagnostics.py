"""Read-only summaries of saved watch evidence, without recovery authority."""

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re


KINDS = ("capture", "analysis", "daily_review")
STATES = ("pending", "running", "completed", "blocked")
TOKEN = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
UNKNOWN_ACTION = "Inspect the saved command and full outcome before choosing a recovery action."
CALL_ACTION = "Inspect the saved model command and provider usage; no repeated paid request is authorized."
DESCRIPTIONS = {
    "reviewed_approval_or_exposure_changed": (
        "The watch's approved thesis or attached paper exposure changed.",
        "Review current approved meaning and complete exposure, then explicitly update the watch."),
    "approved_meaning_changed": (
        "Approved thesis meaning differs from the saved input.",
        "Review the current approved thesis before updating the watch."),
    "paper_exposure_changed": (
        "Attached paper exposure differs from the saved input.",
        "Review the complete paper book before updating the watch."),
    "model_configuration_changed": (
        "The server model configuration differs from the watch's saved configuration.",
        "Review model configuration and allowances before explicitly updating the watch."),
    "selected_provider_not_configured": (
        "The watch's provider is not selected in the backend or its key is unavailable.",
        "Configure the reviewed provider locally, or review and save a different watch configuration."),
    "source_unavailable": (
        "A selected source is unavailable.",
        "Inspect source identity and retained capture state before changing the manifest."),
    "source_contract_or_permission_changed": (
        "A selected source's contract or processing permission changed.",
        "Inspect the current source contract and permission history; do not bypass withdrawal."),
    "source_contract_unavailable": (
        "The retained source is outside current processing permission.",
        "Inspect its contract and permission history before any further processing."),
    "observed_source_revision_changed": (
        "A source correction superseded the revision used by this analysis.",
        "Inspect the original and corrected revisions; preserve the original analysis labels."),
    "governing_input_changed": (
        "The saved analysis became stale when governing inputs changed.",
        "Inspect its original context and stale reasons before choosing further analysis."),
    "context_overflow": (
        "The retained context exceeded a saved bound.",
        "Inspect record and byte bounds; review an explicit bound change without discarding evidence."),
    "ReviewCapacityExceeded": (
        "The complete retained review cannot fit its configured context bound.",
        "Inspect record and byte bounds; review an explicit bound change without discarding evidence."),
    "daily_backlog_limit_exceeded": (
        "The daily backlog exceeded its configured admission bound.",
        "Inspect missed daily intervals and review the backlog bound; do not skip an earlier interval silently."),
    "NewsBudgetExhausted": (
        "Combined private-model admission allowance was exhausted.",
        "Inspect aggregate admissions and unresolved work before reviewing allowances."),
    "analysis_allowance_exhausted": (
        "The saved analytical allowance was exhausted.",
        "Inspect admissions and unresolved work before reviewing allowances."),
    "AnalysisAllowanceExhausted": (
        "The watch's analytical allowance was exhausted.",
        "Inspect admissions and unresolved work before reviewing allowances."),
    "lease_expired": (
        "The saved work lease expired; that does not prove remote cancellation.", UNKNOWN_ACTION),
    "dispatch_started_without_saved_news_receipt": (
        "Dispatch was recorded but no saved news receipt was found; remote completion and billing remain uncertain.", CALL_ACTION),
    "response_not_recorded": (
        "An admitted model call has no recorded response; completion and billing remain uncertain.", CALL_ACTION),
    "completion_deadline_exceeded": (
        "The result missed its admission deadline; remote completion and billing remain uncertain.", CALL_ACTION),
    "timeout": ("The model request timed out; remote completion and billing remain uncertain.", CALL_ACTION),
    "outcome_unknown": ("The model request's outcome is uncertain.", CALL_ACTION),
    "invalid_model_output": ("The model response failed the analysis contract.", CALL_ACTION),
    "invalid_response": ("The provider response failed validation.", CALL_ACTION),
    "truncated_response": ("The model response was truncated.", CALL_ACTION),
    "authentication": ("The provider rejected authentication.", "Check local provider credentials and inspect the saved command before any new request."),
    "rate_limited": ("The provider rejected the request because of a rate limit.", CALL_ACTION),
    "provider_error": ("The provider reported an error.", CALL_ACTION),
}


def _token(value):
    return value if type(value) is str and TOKEN.fullmatch(value) else None


def _amount(value):
    if type(value) is not str or len(value) > 64:
        return None
    try:
        amount = Decimal(value)
        return value if amount.is_finite() and amount >= 0 else None
    except InvalidOperation:
        return None


def _description(code, analysis_status=None):
    if code in DESCRIPTIONS:
        description, action = DESCRIPTIONS[code]
        return description, action, True
    if analysis_status in ("outcome_unknown", "running"):
        return "The saved model outcome is unresolved; its specific reason is unavailable.", CALL_ACTION, False
    return "The saved outcome has incomplete diagnostics; its specific cause is unavailable.", UNKNOWN_ACTION, False


def _entry(slot, lease, outcome, payload, *, source_id=None):
    analysis = payload.get("analysis")
    analysis = analysis if type(analysis) is dict else {}
    # Older scheduling fixtures used reason rather than code. Only bounded
    # identifiers are retained, never arbitrary exception messages or bodies.
    raw_code = payload.get("code", payload.get("reason", analysis.get("stop_reason")))
    code = _token(raw_code)
    description, action, complete = _description(code, analysis.get("status"))
    calls = payload.get("model_calls")
    return {"slot_id": _token(slot.get("slot_id")), "kind": slot["kind"],
        "slot_state": slot["state"], "lease_sequence": lease.get("sequence"),
        "recovery_id": _token(lease.get("recovery_id")),
        "effective_watch_version_id": _token(lease.get("effective_watch_version_id")),
        "saved_outcome": outcome["status"], "saved_code": code,
        "source_id": _token(source_id), "analysis_id": _token(analysis.get("id")),
        "analysis_status": _token(analysis.get("status")),
        "diagnostics_complete": complete, "description": description, "suggested_action": action,
        "billing": {"model_calls": calls if type(calls) is int and calls >= 0 else None,
            "reported_cost_usd": _amount(analysis.get("reported_cost_usd")),
            "estimated_cost_usd": _amount(analysis.get("estimated_cost_usd")),
            "dispatch_recorded": slot.get("analysis_request") is not None,
            "paid_retry_authorized": False}}


def _order(slot):
    try:
        instant = datetime.fromisoformat(slot["intended_at"])
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError
        return instant.astimezone(timezone.utc), slot["slot_id"]
    except (TypeError, ValueError, KeyError):
        raise ValueError("Watch inspection requires aware intended times and slot identities") from None


def summarize_watch(value):
    """Summarize only supplied inspection evidence, without inferring live state."""
    if type(value) is not dict or type(value.get("slots")) is not list:
        raise ValueError("A saved watch inspection with slots is required")
    counts = {kind: {state: 0 for state in STATES} for kind in KINDS}
    diagnostics, blockers, changes, recoveries = [], [], [], []
    current = value.get("configuration", {})
    for slot in value["slots"]:
        if (type(slot) is not dict or slot.get("kind") not in KINDS or slot.get("state") not in STATES
                or type(slot.get("leases")) is not list or _token(slot.get("slot_id")) is None):
            raise ValueError("A saved slot has unsupported identity, kind, state or lease records")
        counts[slot["kind"]][slot["state"]] += 1
        for saved_recovery in slot.get("recoveries", []):
            recoveries.append({"slot_id": slot["slot_id"], **{key: _token(saved_recovery.get(key)) for key in
                ("recovery_id", "action", "prior_token", "initial_lease_token", "watch_version_id")},
                "created_at": saved_recovery.get("created_at")})
        if slot["kind"] == "daily_review" and slot["state"] != "completed":
            blockers.append(slot)
        saved = slot.get("configuration", {})
        if type(saved) is dict and type(current) is dict:
            differences = [field for field in ("provider", "model_id", "approval_id", "exposure_digest",
                "model_configuration", "sources", "context_bounds", "allowances")
                if field in saved and field in current and saved[field] != current[field]]
            if differences:
                changes.append({"slot_id": slot["slot_id"], "fields": differences,
                    "description": "Saved slot inputs differ from the current enrolled watch configuration; this does not establish the failure cause."})
        for lease in slot["leases"]:
            outcome = lease.get("outcome")
            if outcome is None:
                continue
            payload = outcome.get("payload", {})
            if type(payload) is not dict:
                raise ValueError("Saved outcomes require object payloads")
            captured = payload.get("captures", [])
            failed_captures = [row for row in captured if type(row) is dict and row.get("status") != "captured"]
            if failed_captures:
                for row in failed_captures:
                    diagnostics.append(_entry(slot, lease, outcome,
                        {**row, "model_calls": payload.get("model_calls")}, source_id=row.get("source_id")))
            elif (outcome.get("status") != "completed" or
                    type(payload.get("analysis")) is dict and payload["analysis"].get("status") in
                    ("failed", "outcome_unknown", "running", "stale")):
                diagnostics.append(_entry(slot, lease, outcome, payload))
    oldest = min(blockers, key=_order) if blockers else None
    codes = Counter(item["saved_code"] for item in diagnostics if item["saved_code"] is not None)
    return {"schema_version": "internal-watch-diagnostics-v1", "watch_id": _token(value.get("watch_id")),
        "slot_count": len(value["slots"]), "counts_by_kind_state": counts,
        "oldest_blocking_daily_slot": ({key: oldest.get(key) for key in
            ("slot_id", "state", "local_date", "intended_at", "period_start", "cutoff")} if oldest else None),
        "saved_failure_codes": [{"code": code, "count": count} for code, count in sorted(codes.items())],
        "diagnostics": diagnostics, "incomplete_diagnostics_count": sum(not item["diagnostics_complete"] for item in diagnostics),
        "configuration_changes": changes, "recoveries": recoveries,
        "read_only": True, "paid_retry_authorized": False,
        "limitations": ["Counts describe saved slot state; inspection does not expire leases or determine liveness.",
            "An unfinished daily slot precedes later daily contexts; this summary does not retry or skip it.",
            "Configuration comparisons use the current enrolled watch, not live provider, source or thesis state.",
            "Missing cost observations remain unknown; failure or lease expiry does not establish zero billing."]}


def _display(value):
    return json.dumps(value, ensure_ascii=True)[1:-1] if type(value) is str else "unknown"


def render_brief(summary):
    """Human text with escaped external identifiers and no hidden side effects."""
    lines = ["Watch " + _display(summary.get("watch_id")) + " (saved state, read only)"]
    for kind, states in summary["counts_by_kind_state"].items():
        lines.append(kind + ": " + ", ".join(f"{state}={count}" for state, count in states.items()))
    oldest = summary["oldest_blocking_daily_slot"]
    lines.append("Oldest unfinished daily: " + (f"{_display(oldest['slot_id'])}, {_display(oldest['local_date'])}, {_display(oldest['state'])}" if oldest else "none"))
    for item in summary["diagnostics"]:
        lines.append(f"{_display(item['slot_id'])} [saved {_display(item['saved_outcome'])}, current {_display(item['slot_state'])}, {_display(item['saved_code'])}]: "
                     + item["description"] + " " + item["suggested_action"])
    for item in summary.get("recoveries", []):
        lines.append(f"Recovery {_display(item['recovery_id'])}: {_display(item['action'])} for {_display(item['slot_id'])}, "
                     + "reviewed version " + _display(item["watch_version_id"]) + ".")
    for item in summary["configuration_changes"]:
        lines.append(_display(item["slot_id"]) + ": saved inputs differ from current watch in " + ", ".join(item["fields"]) + ".")
    lines.append("Unreported costs remain unknown. This inspection authorizes no repeated paid request.")
    return "\n".join(lines)
