"""One explicit fresh morning call over a retained, independently usable digest.

Durable admission precedes inference. Saved-command reads need no catalogue or
credentials and never retry. Current disposition is a coherent observation,
not a new publication pointer or notification authority.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from macro_agent.domain.daily_synthesis import (
    DRIVER_PROMPT_VERSION, DRIVER_SCHEMA_VERSION, LIMITATIONS, MAX_CONTEXT_BYTES,
    PROMPT_VERSION, SCHEMA_VERSION,
    build_synthesis_prompt, validate_synthesis_document,
)
from macro_agent.domain.models import canonical_json, require_digest, text_digest
from macro_agent.domain.time import as_utc
from macro_agent.persistence.context_binding import _at, lock_owner_thesis, lock_thesis_briefs
from macro_agent.providers import PROVIDER_IDS, ProviderError, create_provider, is_explicit_model_id
from macro_agent.theses import compilation, service as theses
from macro_agent.theses.model_budget import capacity_available, lock_model_budget

from . import service
from .publication import _read_snapshot, _review
from .synthesis_models import DailySynthesisAttempt, DailySynthesisResult


def gate():
    service.gate()
    compilation._gate()


def model_configuration(provider_id, *, driver_review=False):
    if type(driver_review) is not bool:
        raise ValueError("driver_review requires an explicit boolean")
    configuration = compilation._configuration(provider_id)
    configuration.update(
        prompt_version=DRIVER_PROMPT_VERSION if driver_review else PROMPT_VERSION,
        schema_version=DRIVER_SCHEMA_VERSION if driver_review else SCHEMA_VERSION,
        cost_category="private_investigation", context="exact_retained_daily_review",
        max_context_bytes=MAX_CONTEXT_BYTES)
    return configuration


def _context(review, *, driver_review=False):
    heads = {}
    for report_id, head_id in review.context.evidence.revisions.values_list(
            "revision__report_id", "head_at_preparation_id"):
        key, value = str(report_id), str(head_id) if head_id else None
        if key in heads and heads[key] != value:
            raise theses.ThesisConflict("Retained report has contradictory original head labels")
        heads[key] = value
    value = {"review_id": str(review.pk), "review_digest": review.digest,
        "review": review.content, "original_inputs": review.context.resolved_inputs,
        "report_heads": heads}
    if driver_review:
        value["driver_review"] = True
    build_synthesis_prompt(value)
    return value


def _stale(review, thesis, at):
    reasons = service._wire(review, thesis, at)["current_disposition"]["stale_reasons"]
    if review.__class__.objects.filter(thesis=thesis, cutoff__gt=review.cutoff).exists():
        reasons.append("newer_retained_review")
    return sorted(set(reasons))


def _response(attempt, thesis, at, *, replayed=False):
    result = DailySynthesisResult.objects.filter(attempt=attempt).first()
    versions = (attempt.configuration.get("schema_version"), attempt.configuration.get("prompt_version"))
    if versions not in ((SCHEMA_VERSION, PROMPT_VERSION), (DRIVER_SCHEMA_VERSION, DRIVER_PROMPT_VERSION)):
        raise theses.ThesisConflict("Retained synthesis configuration has an unsupported exact profile")
    context = _context(attempt.review, driver_review=versions[0] == DRIVER_SCHEMA_VERSION)
    if (attempt.review_digest != attempt.review.digest or attempt.context != context
            or attempt.context_digest != text_digest(canonical_json(context))):
        raise theses.ThesisConflict("Retained synthesis admission failed integrity verification")
    if at < attempt.created_at or result is not None and at < result.finished_at:
        raise theses.ThesisConflict("Synthesis observation precedes retained history")
    if result is not None and result.document is not None:
        validate_synthesis_document(canonical_json(result.document), attempt.context)
    status = result.status if result else ("outcome_unknown" if at >= attempt.deadline_at else "running")
    reasons = sorted(set(_stale(attempt.review, thesis, at) + (result.stale_reasons if result else [])))
    disposition = "stale" if reasons or status == "stale" else "current" if status == "synthesised" else "unresolved"
    metadata = result.provider_metadata if result else {}
    return {"synthesis": {
        "id": str(attempt.pk), "command_id": str(attempt.command_id),
        "review_id": str(attempt.review_id), "review_digest": attempt.review_digest,
        "provider": attempt.provider, "model_id": attempt.model_id,
        "schema_version": attempt.configuration["schema_version"],
        "prompt_version": attempt.configuration["prompt_version"],
        "status": status, "created_at": attempt.created_at.isoformat(),
        "finished_at": result.finished_at.isoformat() if result else None,
        "document": result.document if result else None, "context": attempt.context,
        "context_digest": attempt.context_digest,
        "usage": metadata.get("usage", compilation.UNKNOWN_USAGE),
        "reported_cost_usd": metadata.get("reported_cost_usd"),
        "estimated_cost_usd": compilation._estimate(attempt, metadata),
        "reported_model": metadata.get("reported_model"),
        "provider_request_id": metadata.get("provider_request_id"),
        "latency_ms": metadata.get("latency_ms"),
        "stop_reason": result.stop_reason if result else ("response_not_recorded" if status == "outcome_unknown" else None),
        "original_stale_reasons": result.stale_reasons if result else [], "limitations": LIMITATIONS,
    }, "current_disposition": {"status": disposition, "stale_reasons": reasons,
        "observed_at": at.isoformat(), "publication_authority": False},
        "replayed": replayed, "review_id": str(attempt.review_id), "review_digest": attempt.review_digest}


def get_synthesis_command(actor_id, review_id, command_id, *, clock=timezone.now):
    gate()
    service.outermost()
    theses._uuid(command_id, "command_id")
    with transaction.atomic():
        _read_snapshot()
        theses._owner(actor_id)
        review = _review(actor_id, review_id)
        thesis = theses._record(actor_id, str(review.thesis_id))
        attempt = DailySynthesisAttempt.objects.select_related("review__context__evidence").filter(
            owner_id=actor_id, review=review, command_id=command_id).first()
        if attempt is None:
            raise theses.ThesisUnavailable("Daily synthesis command unavailable")
        return _response(attempt, thesis, as_utc(clock()), replayed=True)


def inspect_synthesis(actor_id, synthesis_id, *, clock=timezone.now):
    gate()
    service.outermost()
    theses._uuid(synthesis_id, "synthesis_id")
    with transaction.atomic():
        _read_snapshot()
        theses._owner(actor_id)
        attempt = DailySynthesisAttempt.objects.select_related("review__context__evidence").filter(
            owner_id=actor_id, pk=synthesis_id).first()
        if attempt is None:
            raise theses.ThesisUnavailable("Daily synthesis unavailable")
        thesis = theses._record(actor_id, str(attempt.thesis_id))
        return _response(attempt, thesis, as_utc(clock()))


def _existing(actor_id, command_id, digest):
    attempt = DailySynthesisAttempt.objects.select_related("review__context__evidence").filter(
        owner_id=actor_id, command_id=command_id).first()
    if attempt is not None and attempt.request_digest != digest:
        raise theses.ThesisConflict("Synthesis command belongs to different exact inputs")
    return attempt


def synthesize_review(actor_id, review_id, command_id, expected_review_digest, model_id,
                      provider_id, *, provider=None, clock=timezone.now, slot_token=None,
                      driver_review=False):
    gate()
    service.outermost()
    for field, value in (("review_id", review_id), ("command_id", command_id)):
        theses._uuid(value, field)
    require_digest(expected_review_digest, "expected_review_digest")
    if type(provider_id) is not str or provider_id not in PROVIDER_IDS:
        raise ValueError("Choose an explicit configured provider")
    if not is_explicit_model_id(model_id):
        raise ValueError("Choose an explicit catalogue model without tools or routing")
    if type(driver_review) is not bool:
        raise ValueError("driver_review requires an explicit boolean")
    request = {"review_id": review_id,
        "review_digest": expected_review_digest, "model_id": model_id, "provider_id": provider_id}
    if driver_review:
        request["driver_review"] = True
    digest = text_digest(canonical_json(request))
    # Saved identities are inspected before catalogue, keys or fresh admission.
    with transaction.atomic():
        _read_snapshot()
        theses._owner(actor_id)
        review = _review(actor_id, review_id)
        thesis = theses._record(actor_id, str(review.thesis_id))
        existing = _existing(actor_id, command_id, digest)
        if existing is not None:
            return _response(existing, thesis, as_utc(clock()), replayed=True)
        if review.digest != expected_review_digest:
            raise theses.ThesisConflict("Review digest differs from the reviewed exact digest")
        at = as_utc(clock())
        if _stale(review, thesis, at):
            raise theses.ThesisConflict("Review is stale; retain the digest and prepare a later reviewed interval")
        _context(review, driver_review=driver_review)
        source_ids = service._source_ids([item["source_id"] for item in review.context.evidence.source_manifest])
    if settings.MACRO_MODEL_PROVIDER != provider_id:
        raise theses.ThesisConflict("Provider changed; refresh the model catalogue")
    configuration = model_configuration(provider_id, driver_review=driver_review)
    if not settings.MACRO_MODEL_API_KEY:
        raise compilation.CompilationUnavailable("Configure provider credentials in the backend environment")
    try:
        adapter = provider or create_provider(provider_id, settings.MACRO_MODEL_API_KEY,
            timeout_seconds=configuration["timeout_seconds"], max_output_tokens=configuration["max_output_tokens"])
        catalog = adapter.list_models()
    except ProviderError:
        raise compilation.CompilationUnavailable("Model catalogue unavailable") from None
    model = next((item for item in catalog["models"] if item["id"] == model_id), None)
    if model is None or model["capabilities"].get("chat_completions") is False:
        raise ValueError("Selected model is no longer in the catalogue")
    with transaction.atomic():
        service._lock_sources(source_ids)
        thesis = lock_owner_thesis(actor_id, str(review.thesis_id), "default")
        briefs = lock_thesis_briefs(thesis)
        existing = _existing(actor_id, command_id, digest)
        if existing is not None:
            return _response(existing, thesis, _at(clock, thesis, briefs), replayed=True)
        review = _review(actor_id, review_id)
        lock_model_budget()
        if slot_token is not None:
            # Internal runner integration only. Owner/thesis protection is
            # already held, so scheduler's watch/slot locks follow safely.
            # The fence and admission commit together; a prior standalone
            # lease check would race catalogue or database waits.
            from macro_agent.scheduling import service as schedule
            lease, slot, _, watch, observed = schedule._protected_lease(actor_id, slot_token, clock)
            schedule._active(lease, slot, observed)
            selected = lease.recovery.watch_version if lease.recovery_id else slot.watch_version
            if (slot.kind != "daily_review" or str(slot.command_id) != command_id
                    or slot.thesis_id != thesis.pk or review.command_id != slot.command_id
                    or selected.configuration.get("daily_synthesis") != {"model_configuration": configuration}
                    or selected.configuration["provider"] != provider_id
                    or selected.configuration["model_id"] != model_id):
                raise schedule.ScheduleConflict("Synthesis does not match its exact reviewed daily slot")
            at = _at(lambda: observed, thesis, briefs)
        else:
            at = _at(clock, thesis, briefs)
        if _stale(review, thesis, at):
            raise theses.ThesisConflict("Review changed before synthesis admission")
        if not capacity_available(actor_id, at, configuration):
            raise compilation.CompilationBudgetExhausted("Shared private-model admission limit reached")
        context = _context(review, driver_review=driver_review)
        messages = build_synthesis_prompt(context)
        attempt = DailySynthesisAttempt.objects.create(owner_id=actor_id, thesis=thesis, review=review,
            command_id=command_id, request_digest=digest, review_digest=review.digest,
            context=context, context_digest=text_digest(canonical_json(context)), provider=provider_id,
            model_id=model_id, model_metadata={**model, "catalog_fetched_at": catalog["fetched_at"]},
            configuration={**configuration, "prompt_digest": text_digest(canonical_json(messages))},
            created_at=at, deadline_at=at + timedelta(seconds=configuration["timeout_seconds"] + 5))
    # Exactly one possible model POST, outside database locks and transactions.
    metadata, document, status, reason = {}, None, "failed", "invalid_model_output"
    try:
        metadata = adapter.complete(model_id, messages)
        document = validate_synthesis_document(metadata.pop("content"), context)
        status, reason = "synthesised", "completed"
    except ProviderError as error:
        metadata, reason = error.metadata, error.code
        status = "outcome_unknown" if reason in ("timeout", "outcome_unknown") else "failed"
    except (ValueError, TypeError, KeyError, UnicodeError):
        metadata.pop("content", None)
    with transaction.atomic():
        service._lock_sources(source_ids)
        thesis = lock_owner_thesis(actor_id, str(review.thesis_id), "default")
        briefs = lock_thesis_briefs(thesis)
        at = _at(clock, thesis, briefs)
        if at < attempt.created_at:
            raise theses.ThesisConflict("Trusted clock precedes synthesis admission")
        stale = _stale(review, thesis, at)
        if at >= attempt.deadline_at:
            status, reason = "outcome_unknown", "completion_deadline_exceeded"
        elif status == "synthesised" and stale:
            status, reason = "stale", "governing_inputs_changed"
        DailySynthesisResult.objects.create(attempt=attempt, status=status, document=document,
            provider_metadata=metadata, stop_reason=reason, stale_reasons=stale, finished_at=at)
        return _response(attempt, thesis, at)
