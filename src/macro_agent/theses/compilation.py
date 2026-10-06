"""One private model call, outside locks, followed by a protected draft proposal.

This internal text-only compiler has no fact sources or monitoring authority.
Durable admission is never retried implicitly, including after an unknown outcome.
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from macro_agent.domain.compilation import PROMPT_VERSION, SCHEMA_VERSION, build_messages, parse_compilation
from macro_agent.domain.models import CompiledThesisVersion, canonical_json, text_digest
from macro_agent.providers import PROVIDER_IDS, create_provider, ProviderError, is_explicit_model_id

from . import service
from .models import CompilationAttempt, CompilationBudget, CompilationResult, InterpretationRecord, AuditTransition


LIMITATIONS = [
    "Text-grounded model proposal, not verified facts or investment analysis.",
    "Current macro context, source verification and consensus data are unavailable.",
    "Quoted text supports attribution, not semantic accuracy or the causal argument.",
    "Agent additions and counter-cases remain unverified hypotheses.",
    "Monitoring and external notification delivery are not configured.",
]
UNKNOWN_USAGE = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}


class CompilationDisabled(PermissionError):
    pass


class CompilationUnavailable(RuntimeError):
    """Operational failure; caller errors never include provider bodies or keys."""


class CompilationBudgetExhausted(RuntimeError):
    pass


def _gate():
    database = settings.DATABASES["default"]["NAME"]
    if (settings.SETTINGS_MODULE != "macro_agent.web.local_settings"
            or getattr(settings, "MACRO_ENABLE_MODEL_COMPILATION", False) is not True
            or not (database.endswith("_dev") or database.startswith("test_"))):
        raise CompilationDisabled("internal compilation unavailable")


def _configuration(provider_id):
    values = {
        "max_output_tokens": settings.MACRO_COMPILATION_MAX_OUTPUT_TOKENS,
        "timeout_seconds": settings.MACRO_COMPILATION_TIMEOUT_SECONDS,
        "owner_attempts_per_day": settings.MACRO_COMPILATION_OWNER_ATTEMPTS_PER_DAY,
        "aggregate_attempts_per_day": settings.MACRO_COMPILATION_ATTEMPTS_PER_DAY,
    }
    bounds = {"max_output_tokens": (128, 4000), "timeout_seconds": (1, 60),
              "owner_attempts_per_day": (1, 100), "aggregate_attempts_per_day": (1, 1000)}
    for name, (lower, upper) in bounds.items():
        if type(values[name]) is not int or not lower <= values[name] <= upper:
            raise CompilationUnavailable("invalid internal compilation limits")
    return {**values, "provider": provider_id, "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION, "calls_per_attempt": 1, "automatic_retries": 0,
            "cost_category": "private_context", "context": "exact_thesis_text_only"}


def model_catalog(actor_id, *, provider=None):
    _gate()
    service._owner(actor_id)
    provider_id = settings.MACRO_MODEL_PROVIDER
    if provider_id not in PROVIDER_IDS:
        raise CompilationUnavailable("configured model provider unavailable")
    try:
        catalog = (provider or create_provider(provider_id, settings.MACRO_MODEL_API_KEY,
                                                timeout_seconds=10)).list_models()
    except ProviderError:
        raise CompilationUnavailable("model catalogue unavailable") from None
    return {**catalog, "provider": provider_id, "compilation_enabled": True,
            "credentials_configured": bool(settings.MACRO_MODEL_API_KEY),
            "models": [item for item in catalog["models"] if is_explicit_model_id(item["id"])
                       and item["capabilities"].get("chat_completions") is not False]}


def _estimate(attempt, metadata):
    usage = metadata.get("usage", UNKNOWN_USAGE)
    try:
        terms = []
        for tokens, price in (("prompt_tokens", "input_price_usd_per_million"),
                              ("completion_tokens", "output_price_usd_per_million")):
            count, rate = usage.get(tokens), attempt.model_metadata.get(price)
            if type(count) is not int or count < 0 or rate is None:
                return None
            rate = Decimal(rate)
            if not rate.is_finite() or rate < 0:
                return None
            terms.append(Decimal(count) * rate / Decimal(1_000_000))
        return str(sum(terms))
    except (ValueError, TypeError, InvalidOperation):
        return None


def _response(attempt, thesis, at):
    result = CompilationResult.objects.filter(attempt=attempt).select_related("interpretation").first()
    metadata = result.provider_metadata if result else {}
    status = result.status if result else ("outcome_unknown" if at >= attempt.deadline_at else "running")
    interpretation_id = str(result.interpretation_id) if result and result.interpretation_id else None
    return {
        "compilation": {
            "id": str(attempt.pk), "status": status, "provider": attempt.provider,
            "model_id": attempt.model_id, "created_at": attempt.created_at.isoformat(),
            "finished_at": result.finished_at.isoformat() if result else None,
            "document": result.document if result else None,
            "interpretation_version_id": interpretation_id,
            "is_current_draft": bool(interpretation_id
                and str(thesis.latest_interpretation_id) == interpretation_id
                and thesis.latest_text_id == attempt.text_version_id),
            "usage": metadata.get("usage", UNKNOWN_USAGE),
            "reported_cost_usd": metadata.get("reported_cost_usd"),
            "estimated_cost_usd": _estimate(attempt, metadata),
            "reported_model": metadata.get("reported_model"),
            "provider_request_id": metadata.get("provider_request_id"),
            "latency_ms": metadata.get("latency_ms"),
            "stop_reason": result.stop_reason if result else ("response_not_recorded" if status == "outcome_unknown" else None),
            "limitations": LIMITATIONS,
        },
        "thesis": service._detail(thesis),
    }


def _existing(actor_id, thesis, command_id, digest):
    attempt = CompilationAttempt.objects.filter(owner_id=actor_id, command_id=command_id).first()
    if attempt and (attempt.request_digest != digest or attempt.thesis_id != thesis.pk):
        raise service.ThesisConflict("compilation command already belongs to another request")
    return attempt


def get_compilation(actor_id, thesis_id, attempt_id, *, clock=timezone.now):
    _gate()
    attempt_id = service._uuid(attempt_id, "attempt_id")
    with transaction.atomic():
        service._owner(actor_id, lock=True)
        thesis = service._record(actor_id, thesis_id, lock=True)
        attempt = CompilationAttempt.objects.filter(pk=attempt_id, thesis=thesis, owner_id=actor_id).first()
        if attempt is None:
            raise service.ThesisUnavailable("compilation unavailable")
        return _response(attempt, thesis, service._instant(clock, thesis))


def compile_thesis(actor_id, thesis_id, command_id, expected_revision, model_id, provider_id,
                   *, provider=None, clock=timezone.now):
    _gate()
    if connection.in_atomic_block:
        raise RuntimeError("compilation requires durable admission outside a caller transaction")
    command_id = service._uuid(command_id, "command_id")
    thesis_id = service._uuid(thesis_id, "thesis_id")
    revision = service._revision(expected_revision)
    if type(provider_id) is not str or provider_id not in PROVIDER_IDS:
        raise ValueError("choose a configured provider")
    if not is_explicit_model_id(model_id):
        raise ValueError("choose an explicit catalogue model without extra tools or routing")
    digest = text_digest(canonical_json({"thesis_id": thesis_id, "expected_revision": revision,
                                         "model_id": model_id, "provider_id": provider_id}))
    # Ownership and saved-command comparison precede all network work.
    with transaction.atomic():
        service._owner(actor_id, lock=True)
        thesis = service._record(actor_id, thesis_id, lock=True)
        existing = _existing(actor_id, thesis, command_id, digest)
        if existing:
            return _response(existing, thesis, service._instant(clock, thesis))
        if thesis.revision != revision:
            raise service.ThesisConflict("thesis changed; review the current draft")
    if settings.MACRO_MODEL_PROVIDER != provider_id:
        raise service.ThesisConflict("provider changed; refresh the model catalogue")
    configuration = _configuration(provider_id)
    if not settings.MACRO_MODEL_API_KEY:
        raise CompilationUnavailable("configure provider credentials in the backend environment")
    try:
        adapter = provider or create_provider(provider_id, settings.MACRO_MODEL_API_KEY,
            timeout_seconds=configuration["timeout_seconds"],
            max_output_tokens=configuration["max_output_tokens"])
        catalog = adapter.list_models()
    except ProviderError:
        raise CompilationUnavailable("model catalogue unavailable") from None
    model = next((item for item in catalog["models"] if item["id"] == model_id), None)
    if model is None or model["capabilities"].get("chat_completions") is False:
        raise ValueError("selected model is no longer in the catalogue")
    with transaction.atomic():
        service._owner(actor_id, lock=True)
        thesis = service._record(actor_id, thesis_id, lock=True)
        existing = _existing(actor_id, thesis, command_id, digest)
        if existing:
            return _response(existing, thesis, service._instant(clock, thesis))
        if thesis.revision != revision:
            raise service.ThesisConflict("thesis changed; review the current draft")
        # All aggregate admissions use this lock after owner and thesis locks.
        CompilationBudget.objects.get_or_create(pk=1)
        CompilationBudget.objects.select_for_update().get(pk=1)
        at = service._instant(clock, thesis)
        attempts = CompilationAttempt.objects.filter(created_at__gt=at - timedelta(days=1))
        if (attempts.count() >= configuration["aggregate_attempts_per_day"]
                or attempts.filter(owner_id=actor_id).count() >= configuration["owner_attempts_per_day"]
                or attempts.filter(owner_id=actor_id, result__isnull=True, deadline_at__gt=at).exists()):
            raise CompilationBudgetExhausted("compilation admission limit reached")
        messages = build_messages(thesis.latest_text.exact_text)
        attempt = CompilationAttempt.objects.create(owner_id=actor_id, thesis=thesis,
            command_id=command_id, text_version=thesis.latest_text,
            provider=provider_id,
            expected_revision=revision, request_digest=digest, model_id=model_id,
            model_metadata={**model, "catalog_fetched_at": catalog["fetched_at"]},
            configuration=configuration, messages=messages,
            prompt_digest=text_digest(canonical_json(messages)), created_at=at,
            deadline_at=at + timedelta(seconds=configuration["timeout_seconds"] + 5))
        AuditTransition.objects.create(thesis=thesis, kind="compilation_admitted", at=at,
            detail={"attempt_id": str(attempt.pk), "actor_id": actor_id,
                    "text_digest": thesis.latest_text.text_digest, "revision": revision})
    # No database locks, transaction, tools, fact retrieval or implicit retry here.
    metadata, document, status, reason = {}, None, "failed", "invalid_model_output"
    try:
        metadata = adapter.complete(model_id, messages)
        document = parse_compilation(metadata.pop("content"), attempt.text_version.exact_text)
        status, reason = "compiled", "completed"
    except ProviderError as error:
        metadata = error.metadata
        reason = error.code
        status = "outcome_unknown" if error.code in ("timeout", "outcome_unknown") else "failed"
    except (ValueError, TypeError, KeyError):
        # Preserve normalized usage when a paid response fails validation.
        metadata.pop("content", None)
    with transaction.atomic():
        service._owner(actor_id, lock=True)
        thesis = service._record(actor_id, thesis_id, lock=True)
        at = service._instant(clock, thesis)
        if at < attempt.created_at:
            raise service.ThesisConflict("trusted clock precedes compilation admission")
        interpretation = None
        if at >= attempt.deadline_at:
            status, reason = "outcome_unknown", "completion_deadline_exceeded"
        elif status == "compiled" and (thesis.revision != revision
                or thesis.latest_text_id != attempt.text_version_id):
            status, reason = "stale", "thesis_revision_changed"
        elif status == "compiled":
            meaning = document["interpretation"]
            value = CompiledThesisVersion(str(uuid4()), str(attempt.text_version_id),
                tuple(meaning["drivers"]), meaning["horizon"],
                tuple(meaning["invalidation_signposts"]), at)
            interpretation = InterpretationRecord.objects.create(id=value.version_id,
                thesis=thesis, text_version_id=attempt.text_version_id, compilation=attempt,
                drivers=meaning["drivers"], horizon=meaning["horizon"],
                invalidation_signposts=meaning["invalidation_signposts"], known_at=at,
                digest=value.digest, origin="model_compilation")
            thesis.latest_interpretation = interpretation
            thesis.revision += 1
            thesis.changed_at = at
            thesis.save(update_fields=("latest_interpretation", "revision", "changed_at"))
        CompilationResult.objects.create(attempt=attempt, status=status, stop_reason=reason,
            finished_at=at, document=document, interpretation=interpretation,
            provider_metadata=metadata)
        AuditTransition.objects.create(thesis=thesis, kind="compilation_finished", at=at,
            detail={"attempt_id": str(attempt.pk), "actor_id": actor_id, "status": status,
                    "stop_reason": reason, "interpretation_version_id": str(interpretation.pk) if interpretation else None})
        return _response(attempt, thesis, at)
