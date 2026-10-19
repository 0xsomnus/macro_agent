"""Reconstruct compact investigation context from exact immutable records.

The context records what was asked and acquired. It is neither source evidence,
trader belief nor proof that absent search results rule out an explanation.
"""

from macro_agent.domain import research_plan
from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.domain.question_research_context import validate_question_research_context
from macro_agent.monitoring import gdelt_research
from macro_agent.monitoring.models import CaptureMembership, CaptureOutcome
from macro_agent.theses import service as theses

from .investigation_models import (ResearchDiscoveryReceipt, ResearchDiscoveryResult,
    ResearchPlanAttempt, ResearchPlanResult)
from .models import SourceContractVersion


SCHEMA_VERSION = "question-research-context-v1"


def _digest(value):
    return text_digest(canonical_json(value))


def _conflict():
    raise theses.ThesisConflict("Retained question research differs from its exact immutable records")


def source_ids(actor_id, thesis_id, run_id):
    """Discover the complete immutable source set before ordered protection."""
    from .investigation import _record
    run = _record(str(actor_id), str(run_id))
    if str(run.thesis_id) != str(thesis_id):
        raise theses.ThesisUnavailable("Research unavailable")
    return sorted(run.discoveries.values_list("source_id", flat=True))


def build_context(actor_id, thesis_id, run_id, reports, cutoff, contracts):
    """Use server-resolved lineage only, including captured empty searches."""
    # A late import avoids a cycle through the research orchestration service.
    from .investigation import _record
    run = _record(str(actor_id), str(run_id))
    if str(run.thesis_id) != str(thesis_id):
        raise theses.ThesisUnavailable("Research unavailable")
    plan = ResearchPlanAttempt.objects.filter(run=run, owner_id=actor_id, thesis_id=thesis_id).first()
    result = ResearchPlanResult.objects.filter(attempt=plan, status="planned").first() if plan else None
    if plan is None or result is None:
        _conflict()
    if (plan.prompt_digest != _digest(plan.messages)
            or plan.messages != research_plan.build_plan_prompt(run.exact_question)):
        _conflict()
    document = research_plan.parse_plan(canonical_json(result.document), run.exact_question)
    attempts = list(run.discoveries.order_by("question_index"))
    if len(attempts) != len(document["questions"]):
        _conflict()
    observed_times = [run.created_at, plan.created_at, result.finished_at]
    questions = []
    for index, (question, attempt) in enumerate(zip(document["questions"], attempts)):
        source_id = "research-gdelt-" + run.id.hex + "-" + str(index)
        contract = contracts.get(source_id)
        receipt = ResearchDiscoveryReceipt.objects.filter(attempt=attempt).select_related("capture").first()
        outcome = ResearchDiscoveryResult.objects.filter(attempt=attempt, status="captured").first()
        if (attempt.question_index != index or attempt.question != question
                or attempt.source_id != source_id or receipt is None or outcome is None
                or outcome.capture_id != receipt.capture_id
                or receipt.capture.source_id != source_id
                or attempt.contract != gdelt_research.contract(source_id, question["query"])
                or receipt.capture.contract_digest != _digest(attempt.contract)
                or outcome.metadata != receipt.metadata or contract is None
                or contract.source_id != source_id or contract.contract != attempt.contract
                or contract.digest != _digest(contract.contract) or not contract.permitted
                or contract.observed_at > cutoff):
            _conflict()
        captured = CaptureOutcome.objects.filter(attempt=receipt.capture, status="captured").first()
        if captured is None:
            _conflict()
        metadata = receipt.metadata
        try:
            candidates = metadata["candidates"]
            if type(candidates) is not list:
                _conflict()
            # Reconstruct the v1 selection using retained metadata, without an
            # external request. Re-encoding need not reproduce transport bytes.
            parsed = gdelt_research.parse_metadata(canonical_json({"articles": [
                candidate["metadata"] for candidate in candidates]}).encode("utf-8"),
                query=question["query"], received_at=receipt.received_at)
            reconstructed = dict(parsed.metadata)
            reconstructed["transport_digest"] = receipt.batch["transport_digest"]
            if (metadata != reconstructed or receipt.batch != {
                    "items": [item.payload() for item in parsed.batch.items],
                    "received_at": parsed.batch.received_at.isoformat(),
                    "coverage": parsed.batch.coverage, "truncated": parsed.batch.truncated,
                    "transport_digest": receipt.batch["transport_digest"]}
                    or captured.transport_digest != receipt.batch["transport_digest"]
                    or captured.received_at != receipt.received_at):
                _conflict()
        except (KeyError, TypeError, ValueError, gdelt_research.SourceError):
            _conflict()
        rows = list(CaptureMembership.objects.filter(capture=receipt.capture)
            .select_related("revision__report").order_by("revision_id"))
        revisions = [str(member.revision_id) for member in rows]
        payloads = {member.revision.report.native_id: member.revision.payload for member in rows}
        items = {item["id"]: item for item in receipt.batch["items"]}
        if (outcome.revision_ids != revisions or len(payloads) != len(rows)
                or payloads != items or captured.item_count != len(items)
                or any(member.revision.report.source_id != source_id for member in rows)):
            _conflict()
        exclusions = {}
        for candidate in metadata["candidates"]:
            if not candidate["selected"]:
                reason = candidate["exclusion_reason"]
                exclusions[reason] = exclusions.get(reason, 0) + 1
        questions.append({"question_index": index, "planned_question": question,
            "source_id": source_id, "discovery_attempt_id": str(attempt.pk),
            "contract_version_id": str(contract.pk), "contract_digest": contract.digest,
            "receipt_id": str(receipt.pk), "receipt_digest": _digest({
                "attempt_id": str(receipt.attempt_id), "capture_id": str(receipt.capture_id),
                "batch": receipt.batch, "metadata": receipt.metadata,
                "received_at": receipt.received_at.isoformat()}),
            "result_id": str(outcome.pk), "result_digest": _digest({
                "attempt_id": str(outcome.attempt_id), "capture_id": str(outcome.capture_id),
                "status": outcome.status, "revision_ids": outcome.revision_ids,
                "metadata": outcome.metadata, "stop_reason": outcome.stop_reason,
                "finished_at": outcome.finished_at.isoformat()}),
            "capture_id": str(receipt.capture_id), "status": outcome.status,
            "returned_candidate_count": metadata["returned_candidate_count"],
            "selected_count": metadata["selected_count"],
            "excluded_count": len(candidates) - metadata["selected_count"],
            "exclusion_counts": exclusions,
            "candidate_cap_reached": metadata["candidate_cap_reached"],
            "revision_ids": revisions})
        observed_times.extend([attempt.admitted_at, receipt.capture.admitted_at,
            receipt.received_at, captured.finished_at, outcome.finished_at])
    if any(observed > cutoff for observed in observed_times):
        _conflict()
    value = {"schema_version": SCHEMA_VERSION, "run_id": str(run.pk),
        "run_request_digest": run.request_digest,
        "exact_question_digest": text_digest(run.exact_question),
        "plan_attempt_id": str(plan.pk), "plan_prompt_digest": plan.prompt_digest,
        "plan_result_id": str(result.pk), "plan_result_digest": _digest({
            "attempt_id": str(result.attempt_id), "status": result.status,
            "document": result.document, "provider_metadata": result.provider_metadata,
            "stop_reason": result.stop_reason, "finished_at": result.finished_at.isoformat()}),
        "evidence_depth": "headline_metadata_only", "coverage_complete": False,
        "questions": questions}
    try:
        return validate_question_research_context(value, reports)
    except (TypeError, ValueError):
        _conflict()


def retained_contracts(context):
    """Resolve exact original contracts without substituting current heads."""
    questions = context["questions"]
    rows = {str(row.pk): row for row in SourceContractVersion.objects.filter(
        pk__in=[item["contract_version_id"] for item in questions])}
    contracts = {}
    for item in questions:
        row = rows.get(item["contract_version_id"])
        if row is None or row.source_id != item["source_id"] or row.digest != item["contract_digest"]:
            _conflict()
        contracts[row.source_id] = row
    return contracts
