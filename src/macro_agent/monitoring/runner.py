"""Internal orchestration; leases never authorize replay of a model request.

Capture and analytical roles run in different processes. Each tick performs
bounded work, releases database transactions before transport/inference and
retains a stable slot/command identity. This is not notification publication.
"""

from dataclasses import asdict

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, close_old_connections, connection
from django.utils import timezone

from macro_agent.domain.daily_review import DailyReviewLimits
from macro_agent.desk import service as desk
from macro_agent.scheduling import service as schedule
from macro_agent.scheduling.recovery import begin_recovery
from macro_agent.theses.service import ThesisUnavailable

from . import analysis, capture, news_context
from .gates import require_local_proof
from .models import NewsAnalysisAttempt, SourceRevision, SourceState
from .sources import fetch_source, source_specs


def gate():
    require_local_proof()
    if not getattr(settings, "MACRO_ENABLE_CONTINUOUS_DESK", False):
        raise PermissionError("Internal continuous desk is disabled")


def enrollment_preview(actor_id, thesis_id):
    """Inspect existing authority and safe configuration, never fetch a model."""
    gate()
    context = news_context.review_context(actor_id, thesis_id)
    with news_context.readonly_snapshot():
        news_context.set_readonly()
        sources = [{"source_id": row.pk, "contract_digest": row.contract_digest,
                    "label": row.contract.get("label"), "kind": row.contract.get("kind")}
                   for row in SourceState.objects.order_by("id") if news_context.allowed_source(row)]
    return {"thesis": context, "sources": sources,
            "provider": settings.MACRO_MODEL_PROVIDER,
            "model_configuration": analysis.model_configuration(settings.MACRO_MODEL_PROVIDER),
            "limitations": ["No model catalogue or inference request was made.",
                            "Timing, bounds and allowances require explicit configuration."]}


def _safe_failure(error):
    # Never persist arbitrary exception text, credentials, remote bodies or paths.
    return {"code": type(error).__name__}


def _capture_slot(lease, loaders, clock):
    results = []
    for selected in lease["configuration"]["sources"]:
        source_id = selected["source_id"]
        try:
            row = SourceState.objects.get(pk=source_id)
            if row.contract_digest != selected["contract_digest"]:
                raise ValueError("Source contract changed")
            if source_id in source_specs:
                expected = {**asdict(source_specs[source_id]), "adapter_version": "rss-v1",
                            "coverage": "bounded_snapshot"}
                if row.contract != expected:
                    raise PermissionError("Source adapter contract differs")
                loader = lambda source_id=source_id: fetch_source(source_id)
            elif row.contract.get("kind") == "fictional_fixture" and source_id in loaders:
                require_local_proof(synthetic=True)
                loader = loaders[source_id]
            else:
                raise PermissionError("No reviewed capture adapter is configured")
            result = capture.capture(source_id, row.contract, loader, clock=clock)
            results.append({"source_id": source_id, "capture_id": str(result.attempt_id),
                "status": result.status, "code": result.code,
                "items": result.item_count, "new_revisions": result.new_revision_count})
        except DatabaseError:
            raise  # Leave the slot lease recoverable rather than invent a result.
        except SourceState.DoesNotExist:
            results.append({"source_id": source_id, "status": "failed", "code": "source_unavailable"})
        except (ValueError, PermissionError, PermissionDenied, OSError) as error:
            results.append({"source_id": source_id, "status": "failed", **_safe_failure(error)})
    status = "completed" if all(row["status"] == "captured" for row in results) else "failed"
    return status, {"captures": results, "model_calls": 0,
        "coverage": "bounded_snapshots; coalesced polling does not recover missed feed contents"}


def _terminal_news(response):
    value = response["analysis"]
    if value["status"] in ("running", "outcome_unknown"):
        return "unresolved", {"analysis": value, "paid_retry_authorized": False}
    if value["status"] == "failed":
        return "failed", {"analysis": value, "paid_retry_authorized": False}
    return "completed", {"analysis": value, "paid_retry_authorized": False}


def _recover_news(lease, clock):
    try:
        response = analysis.get_news_command(lease["owner_id"], lease["thesis_id"],
                                             lease["command_id"], clock=clock)
    except news_context.NewsMissing:
        return "unresolved", {"code": "dispatch_started_without_saved_news_receipt",
            "analysis_request": lease.get("analysis_request"), "paid_retry_authorized": False}
    return _terminal_news(response)


def _analysis_slot(lease, provider, clock):
    # Read-only recovery must precede catalogue, model configuration and keys.
    try:
        saved = analysis.get_news_command(lease["owner_id"], lease["thesis_id"],
                                          lease["command_id"], clock=clock)
    except news_context.NewsMissing:
        saved = None
    if saved is not None:
        return _terminal_news(saved)
    if lease["mode"] == "recover":
        return _recover_news(lease, clock)
    config = lease["configuration"]
    current = news_context.review_context(lease["owner_id"], lease["thesis_id"])
    if (current["approval_id"] != config["approval_id"]
            or current["exposure_digest"] != config["exposure_digest"]):
        return "blocked", {"code": "reviewed_approval_or_exposure_changed", "model_calls": 0}
    if analysis.model_configuration(config["provider"]) != config["model_configuration"]:
        return "blocked", {"code": "model_configuration_changed", "model_calls": 0}
    if settings.MACRO_MODEL_PROVIDER != config["provider"] or not settings.MACRO_MODEL_API_KEY:
        return "blocked", {"code": "selected_provider_not_configured", "model_calls": 0}
    source_ids = [row["source_id"] for row in config["sources"]]
    selected = {row["source_id"]: row["contract_digest"] for row in config["sources"]}
    sources = list(SourceState.objects.filter(pk__in=source_ids))
    if len(sources) != len(source_ids):
        return "blocked", {"code": "source_unavailable", "model_calls": 0}
    for source in sources:
        if source.contract_digest != selected[source.pk] or not news_context.allowed_source(source):
            return "blocked", {"code": "source_contract_or_permission_changed", "model_calls": 0}
    attempted = NewsAnalysisAttempt.objects.filter(thesis_id=lease["thesis_id"],
        approval_id=config["approval_id"], exposure_digest=config["exposure_digest"]
    ).values_list("source_revision_id", flat=True)
    revision = (SourceRevision.objects.filter(report__source_id__in=source_ids, current_heads__isnull=False)
        .exclude(pk__in=attempted).select_related("report")
        .order_by("system_received_at", "report__source_id", "report__native_id", "id").first())
    if revision is None:
        return "completed", {"code": "no_unattempted_current_report", "model_calls": 0}
    request = {"source_id": revision.report.source_id, "expected_approval_id": config["approval_id"],
        "expected_exposure_digest": config["exposure_digest"], "provider": config["provider"],
        "model_id": config["model_id"], "model_configuration": config["model_configuration"]}
    schedule.mark_analysis_started(lease["owner_id"], lease["token"], request, clock=clock)
    try:
        response = analysis.analyse_next(lease["owner_id"], lease["thesis_id"], lease["command_id"],
            request["expected_approval_id"], request["expected_exposure_digest"], request["source_id"],
            request["model_id"], request["provider"], provider=provider, clock=clock)
    except DatabaseError:
        raise
    except (ValueError, PermissionError, RuntimeError):
        # Admission may have committed before an error. Inspect, never resubmit.
        return _recover_news({**lease, "analysis_request": request}, clock)
    return _terminal_news(response)


def _daily_slot(lease, clock):
    from datetime import datetime
    config = lease["configuration"]
    # A result retained before a crash wins over newly reviewed bounds. Preserve
    # its exact inputs, preparation time and present stale/prepared disposition.
    try:
        response = desk.get_review_command(lease["owner_id"], lease["thesis_id"], lease["command_id"], clock=clock)
    except ThesisUnavailable:
        response = desk.create_review(lease["owner_id"], lease["thesis_id"], lease["command_id"],
            datetime.fromisoformat(lease["period_start"]), datetime.fromisoformat(lease["cutoff"]),
            tuple(row["source_id"] for row in config["sources"]), DailyReviewLimits(**config["context_bounds"]),
            clock=clock)
    late = lease["late"] or datetime.fromisoformat(response["review"]["prepared_at"]) > datetime.fromisoformat(lease["cutoff"])
    return "completed", {"review": response, "late": late,
                         "intended_at": lease["intended_at"], "model_calls": 0}


def execute_lease(lease, *, loaders=None, provider=None, clock=timezone.now):
    """Execute one admitted fenced lease, shared by ticks and operator recovery."""
    gate()
    if connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("Runner execution requires independent committed transactions")
    kind, actor_id = lease["kind"], lease["owner_id"]
    try:
        if kind == "capture":
            status, payload = _capture_slot(lease, loaders or {}, clock)
        elif kind == "analysis":
            status, payload = _analysis_slot(lease, provider, clock)
            if lease["mode"] != "recover":
                desk.observe_analysis_results(actor_id, lease["thesis_id"],
                    tuple(row["source_id"] for row in lease["configuration"]["sources"]),
                    lease["configuration"]["context_bounds"]["analyses"], clock=clock)
        else:
            status, payload = _daily_slot(lease, clock)
    except DatabaseError:
        raise  # Retained work survives; never invent remote failure/cancellation.
    except (ValueError, PermissionError, PermissionDenied, RuntimeError) as error:
        status, payload = "blocked", _safe_failure(error)
    try:
        outcome = schedule.complete_slot(actor_id, lease["token"], status, payload, clock=clock)
    except schedule.ScheduleFenced:
        outcome = {"status": "lease_lost", "code": "slot_completion_fenced",
                   "recovery_needed": True, "paid_retry_authorized": False}
    return {"kind": kind, "slot_id": lease["slot_id"], "outcome": outcome}


def recover_job(actor_id, slot_id, command_id, expected_last_token, expected_watch_revision,
                action, reason, *, loaders=None, provider=None, clock=timezone.now):
    """An exact repeated operator command inspects its receipt and never executes."""
    gate()
    result = begin_recovery(actor_id, slot_id, command_id, expected_last_token,
                           expected_watch_revision, action, reason, clock=clock)
    if result["replayed"]:
        return {**result, "processed": None, "publication": "none", "external_notifications": "none"}
    processed = execute_lease(result["lease"], loaders=loaders, provider=provider, clock=clock)
    return {**result, "current_slot_state": processed["outcome"].get("current_slot_state"),
            "processed": processed, "publication": "none", "external_notifications": "none"}


def run_tick(actor_id, watch_id, role, *, loaders=None, provider=None, clock=timezone.now):
    """One selected watch; at most one capture or one daily plus one news slot."""
    gate()
    if role not in ("capture", "analysis"):
        raise ValueError("Choose capture or analysis role")
    if connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("Runner ticks require independent committed transactions")
    close_old_connections()
    scheduled = schedule.enqueue_due(actor_id, watch_id,
        kind="capture" if role == "capture" else "analysis", clock=clock)
    if role == "analysis":
        try:
            daily = schedule.enqueue_due(actor_id, watch_id, kind="daily_review", clock=clock)
            scheduled["slots"].extend(daily["slots"])
            scheduled["daily_backlog"] = daily["daily_backlog"]
        except ValueError as error:
            scheduled["daily_schedule_error"] = _safe_failure(error)
    processed = []
    watch = schedule.current_watch(actor_id, watch_id)
    config = watch["configuration"]
    receipts = capture.observe_retained(tuple(row["source_id"] for row in config["sources"]),
                                       config["context_bounds"]["reports"], clock=clock)
    if role == "analysis":
        # Observations happen after committed result reads, independently of finish.
        desk.observe_analysis_results(actor_id, watch["thesis_id"],
            tuple(row["source_id"] for row in config["sources"]),
            config["context_bounds"]["analyses"], clock=clock)
    kinds = ("capture",) if role == "capture" else ("daily_review", "analysis")
    for kind in kinds:
        lease = schedule.claim_due(actor_id, kind, watch_id=watch_id, clock=clock)
        if lease is None:
            continue
        processed.append(execute_lease(lease, loaders=loaders, provider=provider, clock=clock))
    return {"scheduled": scheduled, "receipt_observations": receipts, "processed": processed,
            "publication": "none", "external_notifications": "none"}
