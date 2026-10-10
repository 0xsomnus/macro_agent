"""One automatically selected report and one explicitly initiated model call.

No stored current pointer, no publication, no automatic paid retries. Current
disposition is computed from a coherent snapshot of approval, book and source.
"""

from dataclasses import asdict
from datetime import timedelta
import json

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from macro_agent.domain.daily_review import DailyReviewLimits
from macro_agent.domain.cumulative_news import CUMULATIVE_PROMPT_VERSION, CUMULATIVE_SCHEMA_VERSION
from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.domain.news_analysis import PROMPT_VERSION, SCHEMA_VERSION, build_news_prompt, validate_news_document
from macro_agent.domain.time import as_utc
from macro_agent.persistence.context_binding import _at, book_digest, lock_owner_thesis
from macro_agent.positions.representation import exposure_book
from macro_agent.providers import PROVIDER_IDS, ProviderError, create_provider, is_explicit_model_id
from macro_agent.theses import compilation, service as theses
from macro_agent.theses.model_budget import capacity_available, lock_model_budget

from .models import NewsAnalysisAttempt, NewsAnalysisResult, NewsReviewReceipt, SourceRevision, SourceState
from .news_context import (LIMITATIONS, NewsConflict, NewsDisabled, NewsMissing,
    allowed_source, build_context, gate, news_catalog, protected_source, readonly_snapshot,
    resolve, review_context, set_readonly)


class NewsUnavailable(RuntimeError):
    pass


class NewsBudgetExhausted(RuntimeError):
    pass


def model_configuration(provider_id, *, cumulative=False):
    """Safe configuration shared by watch review and actual news admission."""
    configuration = compilation._configuration(provider_id)
    configuration.update(prompt_version=CUMULATIVE_PROMPT_VERSION if cumulative else PROMPT_VERSION,
        schema_version=CUMULATIVE_SCHEMA_VERSION if cumulative else SCHEMA_VERSION,
        cost_category="private_investigation",
        context="complete_retained_context" if cumulative else "one_retained_report_and_approved_paper_book")
    return configuration


def _saved_response(actor_id, command_id, digest, thesis, clock):
    row = NewsReviewReceipt.objects.filter(owner_id=actor_id, command_id=command_id).select_related("attempt").first()
    if row is not None and (row.request_digest != digest or row.thesis_id != thesis.pk):
        raise NewsConflict("Command identity already belongs to another news request")
    if row is None:
        return None
    return _receipt_response(row, thesis, clock)


def _receipt_response(row, thesis, clock):
    if row.attempt_id:
        return _response(row.attempt, thesis, as_utc(clock()), replayed=True)
    response = json.loads(canonical_json(row.empty_response))
    response["analysis"]["replayed"] = True
    response["analysis"]["unresolved_attempt_count"] = _unresolved_count(thesis)
    return response


def _stale_reasons(attempt, thesis):
    reasons = []
    if thesis.current_approval_id != attempt.approval_id:
        reasons.append("approved_meaning_changed")
    if book_digest(exposure_book(str(thesis.pk))) != attempt.exposure_digest:
        reasons.append("paper_exposure_changed")
    revision = SourceRevision.objects.select_related("report__source").get(pk=attempt.source_revision_id)
    if revision.report.current_revision_id != revision.pk:
        reasons.append("observed_source_revision_changed")
    source = revision.report.source
    if source.contract != attempt.resolved_inputs["source_contract"]:
        reasons.append("source_contract_changed")
    if not allowed_source(source):
        reasons.append("source_contract_unavailable")
    if attempt.admission_context_id is not None:
        from .cumulative import cumulative_stale_reasons
        reasons.extend(cumulative_stale_reasons(attempt))
    return reasons


def _unresolved_count(thesis):
    rows = NewsAnalysisAttempt.objects.filter(thesis=thesis)
    return rows.filter(result__isnull=True).count() + rows.filter(result__status__in=("failed", "outcome_unknown")).count()


def _response(attempt, thesis, at, *, replayed=False):
    result = NewsAnalysisResult.objects.filter(attempt=attempt).first()
    if attempt.admission_context_id is not None:
        from .cumulative import check_cumulative_clock
        _, inputs, _ = resolve(thesis, str(thesis.current_approval_id))
        _at(lambda: at, thesis, resolved=inputs)
        if at < attempt.created_at or result is not None and at < result.finished_at:
            raise NewsConflict("Disposition observation cannot precede retained analysis state")
        check_cumulative_clock(attempt, at)
    status = result.status if result else ("outcome_unknown" if at >= attempt.deadline_at else "running")
    stale = _stale_reasons(attempt, thesis)
    disposition = ("stale" if stale or status == "stale" else "current" if status == "analysed" else "unresolved")
    metadata = result.provider_metadata if result else {}
    return {"analysis": {"id": str(attempt.pk), "status": status, "current_disposition": disposition,
        "replayed": replayed, "source_revision_id": str(attempt.source_revision_id),
        "provider": attempt.provider, "model_id": attempt.model_id,
        "created_at": attempt.created_at.isoformat(), "finished_at": result.finished_at.isoformat() if result else None,
        "context": attempt.context, "document": result.document if result else None,
        "usage": metadata.get("usage", compilation.UNKNOWN_USAGE),
        "reported_cost_usd": metadata.get("reported_cost_usd"), "estimated_cost_usd": compilation._estimate(attempt, metadata),
        "reported_model": metadata.get("reported_model"), "provider_request_id": metadata.get("provider_request_id"),
        "latency_ms": metadata.get("latency_ms"),
        "stop_reason": result.stop_reason if result else ("response_not_recorded" if status == "outcome_unknown" else None),
        "stale_reasons": sorted(set(stale + (result.stale_reasons if result else []))),
        "limitations": _limitations(attempt), "unresolved_attempt_count": _unresolved_count(thesis)}}


def _empty(thesis, provider_id, model_id):
    return {"analysis": {"id": None, "status": "queue_empty", "current_disposition": "queue_empty", "replayed": False,
        "source_revision_id": None, "provider": provider_id, "model_id": model_id,
        "created_at": None, "finished_at": None, "context": None, "document": None,
        "usage": compilation.UNKNOWN_USAGE, "reported_cost_usd": None, "estimated_cost_usd": None,
        "reported_model": None, "provider_request_id": None, "latency_ms": None,
        "stop_reason": "no_unattempted_current_report", "stale_reasons": [],
        "limitations": LIMITATIONS, "unresolved_attempt_count": _unresolved_count(thesis)}}


def _save_empty(actor_id, thesis, command_id, digest, provider_id, model_id, at):
    response = _empty(thesis, provider_id, model_id)
    NewsReviewReceipt.objects.create(owner_id=actor_id, thesis=thesis, command_id=command_id,
        request_digest=digest, empty_response=response, saved_at=at)
    return response


def _next_revision(source, thesis, approval_id, exposure_digest):
    attempted = NewsAnalysisAttempt.objects.filter(thesis=thesis, approval_id=approval_id,
        exposure_digest=exposure_digest).values_list("source_revision_id", flat=True)
    return (SourceRevision.objects.filter(report__source=source, current_heads__isnull=False)
            .exclude(pk__in=attempted).select_related("report")
            .order_by("system_received_at", "report__native_id", "id").first())


def get_analysis(actor_id, thesis_id, attempt_id, *, clock=timezone.now):
    gate()
    theses._uuid(attempt_id, "attempt_id")
    with readonly_snapshot():
        set_readonly()
        theses._owner(actor_id)
        thesis = theses._record(actor_id, thesis_id)
        attempt = NewsAnalysisAttempt.objects.filter(pk=attempt_id, owner_id=actor_id, thesis=thesis).first()
        if attempt is None:
            raise NewsMissing("News analysis unavailable")
        return _response(attempt, thesis, as_utc(clock()))


def get_news_command(actor_id, thesis_id, command_id, *, clock=timezone.now):
    """Inspect a saved request identity without admitting or retrying inference."""
    gate()
    command_id = theses._uuid(command_id, "command_id")
    with readonly_snapshot():
        set_readonly()
        theses._owner(actor_id)
        thesis = theses._record(actor_id, thesis_id)
        receipt = NewsReviewReceipt.objects.filter(
            owner_id=actor_id, thesis=thesis, command_id=command_id
        ).select_related("attempt").first()
        if receipt is None:
            raise NewsMissing("News command unavailable")
        return _receipt_response(receipt, thesis, clock)


def _limitations(attempt):
    if attempt.admission_context_id is None:
        return LIMITATIONS
    return ["Complete eligible retained context from the explicit source manifest, not broad news coverage or a verified macro regime.",
        *LIMITATIONS[1:]]


def _context_scope(source_id, context_source_ids, context_limits):
    if context_source_ids is None:
        if context_limits is not None:
            raise ValueError("Context limits require an explicit cumulative manifest")
        return None
    from macro_agent.desk import service as desk
    desk.gate()
    ids = desk._source_ids(context_source_ids)
    if source_id not in ids or type(context_limits) is not DailyReviewLimits:
        raise ValueError("Cumulative admission requires the focus source and explicit typed context bounds")
    if len(ids) > context_limits.source_contracts:
        raise ValueError("Complete source manifest exceeds the configured contract bound")
    return ids


def _protected_sources(source_id, scope, *, completing=False):
    if scope is None:
        if completing:
            return [SourceState.objects.select_for_update().get(pk=source_id)]
        return [protected_source(source_id)]
    from .cumulative import lock_sources
    return lock_sources(scope, require_permitted=not completing)


def _cumulative_context(actor_id, thesis, approval, inputs, exposure, sources, revision, limits, at, *, persist):
    from macro_agent.desk.analysis_context import build_analysis_context
    context = build_context(next(row for row in sources if row.pk == revision.report.source_id), revision, inputs)
    private, envelope = build_analysis_context(actor_id, thesis, approval, inputs, exposure,
        sources, revision, limits, at, persist=persist)
    context["cumulative"] = envelope
    return private, context


def analyse_next(actor_id, thesis_id, command_id, expected_approval_id, expected_exposure_digest,
                 source_id, model_id, provider_id, *, provider=None, clock=timezone.now,
                 context_source_ids=None, context_limits=None):
    gate()
    if connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("News analysis requires durable admission outside a caller transaction")
    command_id = theses._uuid(command_id, "command_id")
    thesis_id = theses._uuid(thesis_id, "thesis_id")
    expected_approval_id = theses._uuid(expected_approval_id, "expected_approval_id")
    if type(source_id) is not str or not source_id or len(source_id) > 128:
        raise ValueError("Choose a captured source")
    if type(provider_id) is not str or provider_id not in PROVIDER_IDS or not is_explicit_model_id(model_id):
        raise ValueError("Choose an explicit provider/catalogue model")
    if (type(expected_exposure_digest) is not str or len(expected_exposure_digest) != 64
            or any(c not in "0123456789abcdef" for c in expected_exposure_digest)):
        raise ValueError("Review the complete exposure digest")
    scope = _context_scope(source_id, context_source_ids, context_limits)
    request = {"thesis_id": thesis_id, "approval_id": expected_approval_id,
        "exposure_digest": expected_exposure_digest, "source_id": source_id, "provider_id": provider_id, "model_id": model_id}
    if scope is not None:
        request.update(context_source_ids=scope, context_bounds=asdict(context_limits))
    digest = text_digest(canonical_json(request))
    # Ownership and saved identity precede any source disclosure or network call.
    with readonly_snapshot():
        set_readonly()
        theses._owner(actor_id)
        thesis = theses._record(actor_id, thesis_id)
        existing = _saved_response(actor_id, command_id, digest, thesis, clock)
        if existing is not None:
            return existing
    # Protected preflight prevents empty/oversized/conflicting input from paying.
    with transaction.atomic():
        sources = _protected_sources(source_id, scope)
        source = next(row for row in sources if row.pk == source_id)
        thesis = lock_owner_thesis(actor_id, thesis_id, "default")
        existing = _saved_response(actor_id, command_id, digest, thesis, clock)
        if existing is not None:
            return existing
        approval, inputs, exposure = resolve(thesis, expected_approval_id)
        if exposure != expected_exposure_digest:
            raise NewsConflict("Paper exposure changed; review the complete book")
        revision = _next_revision(source, thesis, approval.pk, exposure)
        if revision is None:
            return _save_empty(actor_id, thesis, command_id, digest, provider_id, model_id,
                               _at(clock, thesis, resolved=inputs))
        if scope is None:
            context = build_context(source, revision, inputs)
        else:
            at = _at(clock, thesis, resolved=inputs)
            _, context = _cumulative_context(actor_id, thesis, approval, inputs, exposure,
                sources, revision, context_limits, at, persist=False)
        build_news_prompt(context)
    if settings.MACRO_MODEL_PROVIDER != provider_id or not settings.MACRO_MODEL_API_KEY:
        raise NewsUnavailable("Configure the selected provider in the backend environment")
    try:
        configuration = model_configuration(provider_id, cumulative=scope is not None)
        adapter = provider or create_provider(provider_id, settings.MACRO_MODEL_API_KEY,
            timeout_seconds=configuration["timeout_seconds"], max_output_tokens=configuration["max_output_tokens"])
        catalog = adapter.list_models()
    except (ProviderError, compilation.CompilationUnavailable):
        raise NewsUnavailable("Model catalogue or configuration unavailable") from None
    model = next((item for item in catalog["models"] if item["id"] == model_id), None)
    if model is None or model["capabilities"].get("chat_completions") is False:
        raise ValueError("Selected model is unavailable")
    with transaction.atomic():
        sources = _protected_sources(source_id, scope)
        source = next(row for row in sources if row.pk == source_id)
        thesis = lock_owner_thesis(actor_id, thesis_id, "default")
        existing = _saved_response(actor_id, command_id, digest, thesis, clock)
        if existing is not None:
            return existing
        approval, inputs, exposure = resolve(thesis, expected_approval_id)
        if exposure != expected_exposure_digest:
            raise NewsConflict("Paper exposure changed; review the complete book")
        revision = _next_revision(source, thesis, approval.pk, exposure)
        if revision is None:
            return _save_empty(actor_id, thesis, command_id, digest, provider_id, model_id,
                               _at(clock, thesis, resolved=inputs))
        if scope is None:
            context = build_context(source, revision, inputs)
            messages = build_news_prompt(context)
        lock_model_budget()
        at = _at(clock, thesis, resolved=inputs)
        if at < revision.system_received_at:
            raise NewsConflict("Trusted clock precedes source receipt")
        if not capacity_available(actor_id, at, configuration):
            raise NewsBudgetExhausted("Combined private-model admission limit reached")
        private = None
        if scope is not None:
            private, context = _cumulative_context(actor_id, thesis, approval, inputs, exposure,
                sources, revision, context_limits, at, persist=True)
            messages = build_news_prompt(context)
        attempt = NewsAnalysisAttempt.objects.create(owner_id=actor_id, thesis=thesis, approval=approval,
            source_revision=revision, admission_context=private, exposure_digest=exposure, request_digest=digest, command_id=command_id,
            resolved_inputs={"user": inputs, "source_contract": source.contract, "input_observed_at": at.isoformat()},
            context=context, context_digest=text_digest(canonical_json(context)), messages=messages,
            prompt_digest=text_digest(canonical_json(messages)), provider=provider_id, model_id=model_id,
            model_metadata={**model, "catalog_fetched_at": catalog["fetched_at"]}, configuration=configuration,
            created_at=at, deadline_at=at + timedelta(seconds=configuration["timeout_seconds"] + 5))
        NewsReviewReceipt.objects.create(owner_id=actor_id, thesis=thesis, command_id=command_id,
            request_digest=digest, attempt=attempt, saved_at=at)
    metadata, document, status, reason = {}, None, "failed", "invalid_model_output"
    try:
        metadata = adapter.complete(model_id, messages)
        document = validate_news_document(metadata.pop("content"), attempt.context)
        status, reason = "analysed", "completed"
    except ProviderError as error:
        metadata, reason = error.metadata, error.code
        status = "outcome_unknown" if reason in ("timeout", "outcome_unknown") else "failed"
    except (ValueError, TypeError, KeyError):
        metadata.pop("content", None)
    with transaction.atomic():
        # Admission already authorized this call. A later permission withdrawal
        # cannot erase its returned outcome or authorize another paid request.
        # Protect the source to order against permission writers, then preserve
        # the outcome with stale reasons instead of requiring fresh-use rights.
        sources = _protected_sources(source_id, scope, completing=True)
        source = next(row for row in sources if row.pk == source_id)
        thesis = lock_owner_thesis(actor_id, thesis_id, "default")
        _, current_inputs, _ = resolve(thesis, str(thesis.current_approval_id))
        current_source = SourceRevision.objects.select_related("report__current_revision").get(
            pk=attempt.source_revision_id).report.current_revision
        from macro_agent.desk.models import SourceContractHead
        permission = SourceContractHead.objects.select_related("version").filter(source=source).first()
        at = _at(clock, thesis, resolved=current_inputs)
        if at < attempt.created_at:
            raise NewsConflict("Trusted clock precedes analysis admission")
        if current_source is not None and at < current_source.system_received_at:
            raise NewsConflict("Trusted clock precedes observed source state")
        if permission is not None and at < permission.version.observed_at:
            raise NewsConflict("Trusted clock precedes source permission observation")
        if private is not None:
            from .cumulative import check_cumulative_clock
            check_cumulative_clock(attempt, at)
        stale = _stale_reasons(attempt, thesis)
        if at >= attempt.deadline_at:
            status, reason = "outcome_unknown", "completion_deadline_exceeded"
        elif status == "analysed" and stale:
            status, reason = "stale", "governing_input_changed"
        NewsAnalysisResult.objects.create(attempt=attempt, status=status, stop_reason=reason,
            finished_at=at, document=document, provider_metadata=metadata, stale_reasons=stale)
        return _response(attempt, thesis, at)
