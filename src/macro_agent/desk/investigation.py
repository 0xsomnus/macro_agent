"""Bounded, explicitly initiated question to retained-source research.

Each paid admission is immutable before inference. Retrying the initial command
only reads history; explicit continuation advances nodes that have not run.
Research never approves a thesis, starts monitoring or creates a position.
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid5

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.utils import timezone

from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.domain.time import as_utc
from macro_agent.monitoring import capture
from macro_agent.monitoring.models import CaptureAttempt, CaptureOutcome, SourceRevision, SourceState
from macro_agent.monitoring.sources import SourceBatch, SourceError, SourceItem
from macro_agent.providers import PROVIDER_IDS, ProviderError, create_provider, is_explicit_model_id
from macro_agent.theses import compilation, service as theses
from macro_agent.theses.model_budget import capacity_available, lock_model_budget
from macro_agent.theses.models import CompilationAttempt

from . import evidence
from .investigation_models import (ResearchDiscoveryAttempt, ResearchDiscoveryReceipt,
    ResearchDiscoveryResult, ResearchPlanAttempt, ResearchPlanResult, ResearchRun,
    ResearchSourceState)


BOUNDS = {"max_model_calls": 2, "max_questions": 3, "max_results_per_question": 4,
          "max_selected_reports": 12}
GAPS = [
    "This is explicitly initiated research, not monitoring, approval or a position.",
    "Discovery uses bounded metadata and headlines, not publisher article bodies or verified macro context.",
    "Provider relevance order selects up to four results per question; this is not an exhaustive or independent source-quality assessment.",
    "Counter-evidence is requested, but its presence or absence does not establish that competing explanations were adequately covered.",
    "Exact source quotations prove attribution, not truth, semantic support or causation.",
    "Prices, valuation, market expectations and instrument availability remain unverified or unavailable.",
    "Call and result bounds do not establish a guaranteed monetary ceiling; unknown costs remain unknown.",
]


def _gate():
    compilation._gate()
    if not getattr(settings, "MACRO_ENABLE_RESEARCH_DISCOVERY", False):
        raise compilation.CompilationDisabled("Internal question-led research unavailable")
    if connection.vendor != "postgresql" or connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("Question-led research requires its own outermost PostgreSQL transaction")


def _command(run, node):
    return str(uuid5(UUID(str(run.pk)), node))


def _capture_gate():
    from macro_agent.monitoring.gates import require_local_proof
    try:
        require_local_proof()
    except PermissionDenied:
        raise compilation.CompilationDisabled("Enable the internal capture proof before question-led research") from None


def _request(exact_question, provider_id, model_id, execution_policy=None):
    value = {"exact_question": exact_question, "provider_id": provider_id,
        "model_id": model_id, "bounds": BOUNDS, "graph_version": "question-research-v1"}
    if execution_policy:
        value.update(graph_version="question-research-v2", execution_policy=execution_policy)
    return text_digest(canonical_json(value))


def _record(actor_id, run_id):
    theses._uuid(run_id, "run_id")
    run = ResearchRun.objects.filter(pk=run_id, owner_id=actor_id).first()
    if run is None:
        raise theses.ThesisUnavailable("Research unavailable")
    from macro_agent.domain.research_recovery_policy import validate_recovery_policy
    try:
        if run.execution_policy != {}:
            validate_recovery_policy(run.execution_policy)
    except (TypeError, ValueError):
        raise theses.ThesisConflict("Retained research recovery policy failed integrity verification") from None
    if (run.request_digest != _request(run.exact_question, run.provider, run.model_id, run.execution_policy)
            or run.bounds != BOUNDS or run.initial_text.exact_text != run.exact_question
            or run.initial_text.thesis_id != run.thesis_id):
        raise theses.ThesisConflict("Retained research request failed integrity verification")
    return run


def _draft_current(run, thesis):
    return (thesis.latest_text_id == run.initial_text_id and thesis.revision == run.initial_revision
            and thesis.current_approval_id is None)


def _metadata(value):
    fields = ("usage", "reported_cost_usd", "reported_model", "provider_request_id", "latency_ms")
    return {field: value[field] for field in fields if field in value}


def _plan_wire(run, at):
    attempt = ResearchPlanAttempt.objects.filter(run=run).first()
    if attempt is None:
        return None
    result = ResearchPlanResult.objects.filter(attempt=attempt).first()
    if text_digest(canonical_json(attempt.messages)) != attempt.prompt_digest:
        raise theses.ThesisConflict("Retained research prompt failed integrity verification")
    if result and result.document is not None:
        from macro_agent.domain import research_plan
        research_plan.parse_plan(canonical_json(result.document), run.exact_question)
    return {"attempt_id": str(attempt.pk),
        "status": result.status if result else ("outcome_unknown" if at >= attempt.deadline_at else "running"),
        "document": result.document if result else None,
        "stop_reason": result.stop_reason if result else "response_not_recorded",
        "provider_metadata": result.provider_metadata if result else {},
        "created_at": attempt.created_at.isoformat(),
        "finished_at": result.finished_at.isoformat() if result else None}


def _discoveries_wire(run, at):
    values = []
    for attempt in run.discoveries.order_by("question_index", "attempt_number"):
        result = ResearchDiscoveryResult.objects.filter(attempt=attempt).first()
        admission = attempt.capture or CaptureAttempt.objects.filter(source_id=attempt.source_id).order_by("sequence").first()
        outcome = CaptureOutcome.objects.filter(attempt=admission).first() if admission else None
        # A durable captured batch remains recoverable after its transport
        # lease ends. Expiry alone cannot turn captured work into uncertainty.
        pending_status = ("running" if outcome and outcome.status == "captured" else
            "outcome_unknown" if admission and at >= admission.deadline_at else "running")
        values.append({"attempt_id": str(attempt.pk), "attempt_number": attempt.attempt_number,
            "question_index": attempt.question_index,
            "question_id": attempt.question["question_id"], "source_id": attempt.source_id,
            "status": result.status if result else pending_status,
            "capture_id": str(result.capture_id) if result and result.capture_id else None,
            "revision_ids": result.revision_ids if result else [],
            "metadata": result.metadata or None if result and (
                not run.execution_policy or result.status == "captured") else None,
            "recovery": result.metadata if result and run.execution_policy and result.status != "captured" else None,
            "stop_reason": result.stop_reason if result else "response_not_recorded",
            "admitted_at": attempt.admitted_at.isoformat(),
            "deadline_at": admission.deadline_at.isoformat() if admission else None,
            "finished_at": result.finished_at.isoformat() if result else None})
    return values


def _known_total(plan_cost, compilation_cost, *, complete):
    if not complete or plan_cost is None or compilation_cost is None:
        return None
    try:
        values = [Decimal(plan_cost), Decimal(compilation_cost)]
        if any(not value.is_finite() or value < 0 for value in values):
            return None
        return str(sum(values))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _wire(run, at, *, replayed=False):
    thesis = theses._record(str(run.owner_id), str(run.thesis_id))
    plan = _plan_wire(run, at)
    discoveries = _discoveries_wire(run, at)
    context = evidence.ResearchEvidenceContext.objects.filter(owner_id=run.owner_id,
        command_id=_command(run, "evidence")).first()
    compile_attempt = CompilationAttempt.objects.filter(owner_id=run.owner_id,
        command_id=_command(run, "compile")).first()
    compiled = compilation._response(compile_attempt, thesis, at) if compile_attempt else None
    status = "planning"
    if plan:
        status = {"planned": "discovering", "failed": "plan_failed", "stale": "stale",
                  "outcome_unknown": "plan_uncertain", "running": "planning"}[plan["status"]]
        if plan["status"] == "planned":
            expected = len(plan["document"]["questions"])
            if any(item["status"] == "failed" for item in discoveries):
                status = "discovery_failed"
            elif any(item["status"] == "outcome_unknown" for item in discoveries):
                status = "discovery_uncertain"
            elif len(discoveries) == expected and all(item["status"] == "captured" for item in discoveries):
                status = "ready_to_compile" if any(item["revision_ids"] for item in discoveries) else "no_evidence"
    if compiled:
        status = {"compiled": "compiled", "failed": "compile_failed", "stale": "stale",
                  "outcome_unknown": "compile_uncertain", "running": "compiling"}[compiled["compilation"]["status"]]
        if (compiled["compilation"]["status"] == "compiled"
                and not compiled["compilation"]["is_current_draft"]):
            status = "stale"
    elif not _draft_current(run, thesis):
        status = "stale"
    if context and evidence.context_stale_reasons(context, at):
        status = "stale"
    recovery = None
    if run.execution_policy:
        from .investigation_recovery import source_progress
        recovery = source_progress(run, plan, at)
        if status in {"discovering", "discovery_failed", "discovery_uncertain", "ready_to_compile", "no_evidence"} or (
                status == "planning" and plan is None and recovery["status"] == "source_deadline"):
            status = recovery["status"]
    planning_cost = plan["provider_metadata"].get("reported_cost_usd") if plan else None
    compilation_cost = compiled["compilation"]["reported_cost_usd"] if compiled else None
    return {"research": {"id": str(run.pk), "command_id": str(run.command_id),
        "request_digest": run.request_digest, "exact_question": run.exact_question,
        "thesis_id": str(run.thesis_id), "initial_thesis_revision": run.initial_revision,
        "provider": run.provider, "model_id": run.model_id, "bounds": run.bounds,
        "execution_policy": run.execution_policy,
        "source_deadline_at": recovery["deadline_at"] if recovery else None,
        "source_next_attempt_at": recovery["next_attempt_at"] if recovery else None,
        "source_stop_reason": recovery["stop_reason"] if recovery else None,
        "created_at": run.created_at.isoformat(), "status": status, "plan": plan,
        "discoveries": discoveries, "evidence_context_id": str(context.pk) if context else None,
        "compilation": compiled, "gaps": GAPS,
        "authority": {"monitoring_started": False, "thesis_approved": False, "positions_created": False},
        "costs": {"planning_reported_cost_usd": planning_cost,
            "compilation_reported_cost_usd": compilation_cost,
            "total_known_cost_usd": _known_total(planning_cost, compilation_cost,
                complete=bool(compiled and plan))}}, "replayed": replayed}


def get_research(actor_id, run_id, *, clock=timezone.now):
    _gate()
    with transaction.atomic():
        evidence._snapshot()
        theses._owner(actor_id)
        run = _record(actor_id, run_id)
        return _wire(run, as_utc(clock()))


def get_research_command(actor_id, command_id, *, clock=timezone.now):
    _gate()
    command_id = theses._uuid(command_id, "command_id")
    with transaction.atomic():
        evidence._snapshot()
        theses._owner(actor_id)
        run = ResearchRun.objects.filter(owner_id=actor_id, command_id=command_id).first()
        if run is None:
            raise theses.ThesisUnavailable("Research unavailable")
        return _wire(_record(actor_id, str(run.pk)), as_utc(clock()), replayed=True)


def start_research(actor_id, command_id, exact_question, provider_id, model_id,
                   *, source_recovery=False, provider=None, discovery=None, clock=timezone.now):
    _gate()
    command_id = theses._uuid(command_id, "command_id")
    exact_question = theses._text(exact_question, "exact_question", theses.TEXT_LIMIT)
    if type(provider_id) is not str or provider_id not in PROVIDER_IDS or not is_explicit_model_id(model_id):
        raise ValueError("Choose a configured provider and explicit catalogue model")
    if type(source_recovery) is not bool:
        raise ValueError("source_recovery requires an explicit boolean")
    from macro_agent.monitoring.research_policy import RECOVERY_POLICY
    policy = dict(RECOVERY_POLICY) if source_recovery else {}
    digest = _request(exact_question, provider_id, model_id, policy)
    with transaction.atomic():
        evidence._snapshot()
        theses._owner(actor_id)
        saved = ResearchRun.objects.filter(owner_id=actor_id, command_id=command_id).first()
        if saved:
            if saved.request_digest != digest:
                raise theses.ThesisConflict("Research command belongs to another request")
            return _wire(_record(actor_id, str(saved.pk)), as_utc(clock()), replayed=True)
    _capture_gate()
    # The derived create command recovers a crash before the research lineage is
    # saved. Empty interpretation records no trader conviction or mandate.
    draft_command = str(uuid5(UUID(command_id), "research-question-draft"))
    draft = theses.create_thesis(actor_id, draft_command, exact_question,
        {"drivers": [], "horizon": None, "invalidation_signposts": []}, clock=clock)["thesis"]
    with transaction.atomic():
        theses._owner(actor_id, lock=True)
        thesis = theses._record(actor_id, draft["id"], lock=True)
        if (thesis.latest_text.exact_text != exact_question or thesis.current_approval_id is not None
                or thesis.latest_interpretation.drivers or thesis.latest_interpretation.horizon is not None
                or thesis.latest_interpretation.invalidation_signposts):
            raise theses.ThesisConflict("Question draft changed before research lineage was saved")
        run, created = ResearchRun.objects.get_or_create(owner_id=actor_id, command_id=command_id,
            defaults={"request_digest": digest, "exact_question": exact_question, "thesis": thesis,
                "initial_text": thesis.latest_text, "initial_revision": thesis.revision,
                "provider": provider_id, "model_id": model_id, "bounds": BOUNDS,
                "execution_policy": policy,
                "created_at": theses._instant(clock, thesis)})
        if run.request_digest != digest:
            raise theses.ThesisConflict("Research command belongs to another request")
    if not created:
        value = get_research(actor_id, str(run.pk), clock=clock)
        value["replayed"] = True
        return value
    return continue_research(actor_id, str(run.pk), provider=provider, discovery=discovery, clock=clock)


def _plan(run, *, provider, clock):
    from macro_agent.domain import research_plan
    if ResearchPlanAttempt.objects.filter(run=run).exists():
        return
    if settings.MACRO_MODEL_PROVIDER != run.provider:
        raise theses.ThesisConflict("Provider changed; research keeps its explicitly selected provider")
    if not settings.MACRO_MODEL_API_KEY:
        raise compilation.CompilationUnavailable("Configure provider credentials in the backend environment")
    configuration = {**compilation._configuration(run.provider),
        "schema_version": research_plan.SCHEMA_VERSION, "prompt_version": research_plan.PROMPT_VERSION,
        "context": "exact_research_question", "cost_category": "private_investigation"}
    adapter = provider or create_provider(run.provider, settings.MACRO_MODEL_API_KEY,
        timeout_seconds=configuration["timeout_seconds"], max_output_tokens=configuration["max_output_tokens"])
    try:
        catalog = adapter.list_models()
    except ProviderError:
        raise compilation.CompilationUnavailable("Model catalogue unavailable") from None
    model = next((item for item in catalog["models"] if item["id"] == run.model_id), None)
    if model is None or model["capabilities"].get("chat_completions") is False:
        raise ValueError("Selected model is no longer in the catalogue")
    messages = research_plan.build_plan_prompt(run.exact_question)
    with transaction.atomic():
        if run.execution_policy:
            from .investigation_recovery import _root
            _root(run.created_at)
        theses._owner(str(run.owner_id), lock=True)
        thesis = theses._record(str(run.owner_id), str(run.thesis_id), lock=True)
        if ResearchPlanAttempt.objects.filter(run=run).exists():
            return
        if not _draft_current(run, thesis):
            return
        lock_model_budget()
        at = theses._instant(clock, thesis)
        if run.execution_policy:
            from .investigation_recovery import deadline, _provider_due
            if (at >= deadline(run) or _provider_due(at) >= deadline(run) -
                    timedelta(seconds=run.execution_policy["transport_timeout_seconds"] + 5)):
                return
        if not capacity_available(str(run.owner_id), at, configuration):
            raise compilation.CompilationBudgetExhausted("Private research admission limit reached")
        attempt = ResearchPlanAttempt.objects.create(run=run, owner_id=run.owner_id, thesis=thesis,
            command_id=_command(run, "plan"), configuration=configuration,
            model_metadata={**model, "catalog_fetched_at": catalog["fetched_at"]}, messages=messages,
            prompt_digest=text_digest(canonical_json(messages)), created_at=at,
            deadline_at=at + timedelta(seconds=configuration["timeout_seconds"] + 5))
    metadata, document, status, reason = {}, None, "failed", "invalid_model_output"
    try:
        response = adapter.complete(run.model_id, messages)
        metadata = _metadata(response)
        document = research_plan.parse_plan(response["content"], run.exact_question)
        status, reason = "planned", "completed"
    except ProviderError as error:
        metadata, reason = _metadata(error.metadata), error.code
        status = "outcome_unknown" if reason in ("timeout", "outcome_unknown") else "failed"
    except (ValueError, TypeError, KeyError):
        pass
    with transaction.atomic():
        theses._owner(str(run.owner_id), lock=True)
        thesis = theses._record(str(run.owner_id), str(run.thesis_id), lock=True)
        at = theses._instant(clock, thesis)
        if at >= attempt.deadline_at:
            status, reason = "outcome_unknown", "completion_deadline_exceeded"
        elif status == "planned" and not _draft_current(run, thesis):
            status, reason = "stale", "research_question_changed"
        ResearchPlanResult.objects.create(attempt=attempt, document=document, status=status,
            provider_metadata=metadata, stop_reason=reason, finished_at=at)


def _serialize_batch(batch):
    return {"items": [item.payload() for item in batch.items], "received_at": batch.received_at.isoformat(),
        "coverage": batch.coverage, "truncated": batch.truncated, "transport_digest": batch.transport_digest}


def _deserialize_batch(value):
    return SourceBatch(tuple(SourceItem(item["id"], item["title"], item["url"],
        as_utc(timezone.datetime.fromisoformat(item["published_at"])) if item["published_at"] else None,
        item["content"]) for item in value["items"]),
        as_utc(timezone.datetime.fromisoformat(value["received_at"])), value["coverage"],
        value["truncated"], value["transport_digest"])


def _discovery_result(attempt, capture_attempt, status, metadata, code, *, clock):
    if attempt.run.execution_policy:
        from .investigation_recovery import record_result
        return record_result(attempt, capture_attempt, status, metadata, code, clock=clock)
    with transaction.atomic():
        if capture_attempt:
            SourceState.objects.select_for_update().get(pk=attempt.source_id)
        theses._owner(str(attempt.run.owner_id), lock=True)
        thesis = theses._record(str(attempt.run.owner_id), str(attempt.run.thesis_id), lock=True)
        ids = list(SourceRevision.objects.filter(capturemembership__capture=capture_attempt)
            .order_by("pk").values_list("pk", flat=True)) if status == "captured" else []
        return ResearchDiscoveryResult.objects.get_or_create(attempt=attempt, defaults={
            "capture": capture_attempt, "status": status, "revision_ids": [str(item) for item in ids],
            "metadata": metadata, "stop_reason": code, "finished_at": theses._instant(clock, thesis)})[0]


def _discover(run, index, question, *, discovery, clock):
    if run.execution_policy:
        from .investigation_recovery import discover
        return discover(run, index, question, discovery=discovery, clock=clock)
    from macro_agent.monitoring import gdelt_research
    source_id = "research-gdelt-" + run.id.hex + "-" + str(index)
    contract = gdelt_research.contract(source_id, question["query"])
    with transaction.atomic():
        theses._owner(str(run.owner_id), lock=True)
        thesis = theses._record(str(run.owner_id), str(run.thesis_id), lock=True)
        if not _draft_current(run, thesis):
            return
        attempt, _ = ResearchDiscoveryAttempt.objects.get_or_create(run=run, question_index=index,
            defaults={"question": question, "source_id": source_id, "contract": contract,
                      "admitted_at": theses._instant(clock, thesis)})
        if attempt.question != question or attempt.contract != contract:
            raise theses.ThesisConflict("Research discovery differs from its retained plan")
    if ResearchDiscoveryResult.objects.filter(attempt=attempt).exists():
        return
    # A source belongs to exactly this question node. A committed capture can be
    # adopted after restart without another GET, including after witness loss.
    capture_attempt = CaptureAttempt.objects.filter(source_id=source_id).order_by("sequence").first()
    receipt = ResearchDiscoveryReceipt.objects.filter(attempt=attempt).first()
    if capture_attempt is None:
        try:
            capture_attempt = capture.admit_capture(source_id, contract, clock=clock)
            capture_attempt._transport_owned = True
        except capture.CaptureBusy:
            return
    outcome = CaptureOutcome.objects.filter(attempt=capture_attempt).first()
    if outcome is not None:
        if outcome.status == "captured":
            capture.observe_capture(capture_attempt.pk, clock=clock)
        _discovery_result(attempt, capture_attempt, outcome.status if outcome.status == "captured" else
            ("outcome_unknown" if outcome.status == "outcome_unknown" else "failed"),
            receipt.metadata if receipt else {}, outcome.code, clock=clock)
        return
    if capture_attempt.admitted_at < attempt.admitted_at:
        raise theses.ThesisConflict("Research capture predates its node admission")
    return _finish_discovery(attempt, capture_attempt, receipt, discovery=discovery, clock=clock)


def _finish_discovery(attempt, capture_attempt, receipt, *, discovery, clock):
    from macro_agent.monitoring import gdelt_research
    if receipt is None:
        # A separate query lock is not held over transport. Admission identity
        # itself fences transport; the caller marks only freshly admitted rows.
        if getattr(capture_attempt, "_transport_owned", False) is not True:
            if as_utc(clock()) >= capture_attempt.deadline_at:
                _discovery_result(attempt, capture_attempt, "outcome_unknown", {},
                    "capture_response_not_recorded", clock=clock)
            return
        if attempt.run.execution_policy:
            transport_budget = timedelta(seconds=attempt.run.execution_policy["transport_timeout_seconds"])
            if as_utc(clock()) >= capture_attempt.deadline_at - transport_budget:
                _discovery_result(attempt, capture_attempt, "outcome_unknown", {},
                    "capture_admission_expired", clock=clock)
                return
        try:
            if discovery is None and attempt.run.execution_policy:
                search = gdelt_research.discover(attempt.question["query"], clock=clock,
                    policy_version=attempt.contract["policy_version"])
            else:
                search = (discovery or gdelt_research.discover)(attempt.question["query"], clock=clock)
            batch = search.batch
            if type(batch) is not SourceBatch or len(batch.items) > 4:
                raise SourceError("invalid_batch")
            # Persist selected and excluded discovery metadata before capture
            # receipt publication, so recovery preserves the selection trace.
            with transaction.atomic():
                SourceState.objects.select_for_update().get(pk=attempt.source_id)
                theses._owner(str(attempt.run.owner_id), lock=True)
                if attempt.run.execution_policy:
                    at = as_utc(clock())
                    if (batch.received_at < capture_attempt.admitted_at
                            or batch.received_at > at or at >= capture_attempt.deadline_at
                            or batch.received_at >= capture_attempt.deadline_at):
                        raise SourceError("timeout")
                receipt = ResearchDiscoveryReceipt.objects.create(attempt=attempt, capture=capture_attempt,
                    batch=_serialize_batch(batch), metadata=search.metadata, received_at=batch.received_at)
        except SourceError as error:
            try:
                capture.fail_capture(capture_attempt.pk, error.code, clock=clock)
            except capture.CaptureFenced:
                pass
            except PermissionError:
                if not attempt.run.execution_policy:
                    raise
                # A safe transport disposition still governs provider pacing.
                # Retaining its code and delay does not process source content.
                metadata = {"retry_after_seconds": error.retry_after_seconds}
                _discovery_result(attempt, capture_attempt, "failed", metadata, error.code, clock=clock)
                raise theses.ThesisConflict("A required research source permission was withdrawn") from None
            metadata = ({"retry_after_seconds": error.retry_after_seconds}
                        if attempt.run.execution_policy else {})
            _discovery_result(attempt, capture_attempt, "failed", metadata, error.code, clock=clock)
            return
    try:
        batch = _deserialize_batch(receipt.batch)
        capture.commit_batch(capture_attempt.pk, batch, clock=clock)
        capture.observe_capture(capture_attempt.pk, clock=clock)
        _discovery_result(attempt, capture_attempt, "captured", receipt.metadata, "snapshot_captured", clock=clock)
    except capture.CaptureFenced:
        outcome = CaptureOutcome.objects.filter(attempt=capture_attempt).first()
        if outcome is not None and outcome.status == "captured":
            capture.observe_capture(capture_attempt.pk, clock=clock)
            _discovery_result(attempt, capture_attempt, "captured", receipt.metadata,
                "snapshot_captured", clock=clock)
        else:
            _discovery_result(attempt, capture_attempt, "outcome_unknown", receipt.metadata,
                "capture_admission_expired", clock=clock)


def continue_research(actor_id, run_id, *, provider=None, discovery=None, clock=timezone.now):
    _gate()
    value = get_research(actor_id, run_id, clock=clock)
    if value["research"]["status"] in {"stale", "compiled", "plan_failed", "plan_uncertain",
            "compile_failed", "compile_uncertain", "compiling", "discovery_failed", "discovery_uncertain",
            "source_exhausted", "source_deadline", "no_evidence"}:
        return value
    run = _record(actor_id, run_id)
    _capture_gate()
    if ResearchPlanAttempt.objects.filter(run=run).exists():
        if not ResearchPlanResult.objects.filter(attempt__run=run, status="planned").exists():
            return value
    else:
        _plan(run, provider=provider, clock=clock)
    result = ResearchPlanResult.objects.filter(attempt__run=run, status="planned").first()
    if result is None:
        return get_research(actor_id, run_id, clock=clock)
    for index, question in enumerate(result.document["questions"]):
        _discover(run, index, question, discovery=discovery, clock=clock)
        saved = ResearchDiscoveryResult.objects.filter(attempt__run=run, attempt__question_index=index,
            status="captured").first()
        if saved is None or saved.status != "captured":
            return get_research(actor_id, run_id, clock=clock)
    revisions = sorted({revision for result in ResearchDiscoveryResult.objects.filter(attempt__run=run, status="captured")
        for revision in result.revision_ids})
    if not revisions:
        return get_research(actor_id, run_id, clock=clock)
    if len(revisions) > BOUNDS["max_selected_reports"]:
        raise theses.ThesisConflict("Complete research evidence exceeds its graph bound")
    # Saved v1 packets remain exact history. A restart cannot silently upgrade
    # their request or approval identity to the new investigation context.
    previous_packet = evidence.ResearchEvidenceContext.objects.filter(owner_id=actor_id,
        command_id=_command(run, "evidence")).first()
    contextual = previous_packet is None or "question_research" in previous_packet.content
    packet = evidence.prepare_evidence(actor_id, str(run.thesis_id), _command(run, "evidence"), revisions,
        question_run_id=str(run.pk) if contextual else None, clock=clock)
    if packet["current_disposition"]["status"] != "current":
        return get_research(actor_id, run_id, clock=clock)
    compilation.compile_thesis(actor_id, str(run.thesis_id), _command(run, "compile"), run.initial_revision,
        run.model_id, run.provider, evidence_context_id=packet["evidence"]["id"], driver_review=True,
        provider=provider, clock=clock)
    return get_research(actor_id, run_id, clock=clock)
