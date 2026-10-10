"""Protected admission-time context from the complete retained evidence set.

This module neither selects sources nor opens transactions. The application
caller owns source, owner and thesis protection, and samples ``at`` afterwards.
Preflight is read-only; only model admission persists relational membership.
"""

from datetime import timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from django.db import connection

from macro_agent.domain.daily_review import DailyReviewLimits, ReviewCapacityExceeded
from macro_agent.domain.cumulative_news import CUMULATIVE_POLICY_VERSION, cumulative_digest
from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.domain.time import as_utc
from macro_agent.monitoring.models import SourceRevision
from macro_agent.monitoring.news_context import allowed_source
from macro_agent.positions.service import MAX_POSITION_RECORDS
from macro_agent.theses import service as theses

from . import service
from .models import DailyReview, PrivateContext, SourceContractHead, SourceContractVersion
from .permissions import contract_snapshot


POLICY_VERSION = CUMULATIVE_POLICY_VERSION


def _contract(source, actor_id, at, persist):
    if persist:
        return contract_snapshot(source, actor_id, at)
    if not allowed_source(source):
        raise theses.ThesisConflict("Source is outside the current permitted adapter manifest")
    if text_digest(canonical_json(source.contract)) != source.contract_digest:
        raise theses.ThesisConflict("Source contract failed integrity verification")
    head = SourceContractHead.objects.select_related("version").filter(source=source).first()
    if head is not None:
        if (head.version.contract != source.contract or head.version.digest != source.contract_digest
                or not head.version.permitted):
            raise theses.ThesisConflict("Source permission or contract is unavailable")
        return head.version
    # An unsaved value allows the same typed eligibility contract during
    # preflight. It grants no permission and does not become retained identity.
    return SourceContractVersion(id=uuid5(NAMESPACE_URL, "macro-agent:preflight:" + source.pk + ":" + source.contract_digest),
        source=source, contract=source.contract, digest=source.contract_digest,
        permitted=True, reviewer_id=actor_id, observed_at=at,
        provenance="existing_allowlisted_adapter_manifest",
        reason="Transient observation of the existing adapter manifest; no rights review or row is created.")


def _predecessor(actor_id, thesis, at):
    cumulative = PrivateContext.objects.select_related("evidence").filter(owner_id=actor_id,
        thesis=thesis, evidence__policy_version=POLICY_VERSION).order_by("-evidence__cutoff", "-pk").first()
    review = DailyReview.objects.select_related("context__evidence").filter(
        owner_id=actor_id, thesis=thesis).order_by("-cutoff", "-pk").first()
    candidates = [item for item in (cumulative, review.context if review else None) if item is not None]
    previous = max(candidates, key=lambda item: (item.evidence.cutoff, item.prepared_at, str(item.pk)), default=None)
    if previous is not None and (previous.evidence.cutoff >= at or previous.prepared_at >= at):
        raise theses.ThesisConflict("Analysis context must continue a strictly earlier retained cutoff")
    return previous


def _start(source_ids, at, predecessor):
    if predecessor is not None:
        return predecessor.evidence.cutoff
    first = SourceRevision.objects.filter(report__source_id__in=source_ids).order_by(
        "system_received_at", "pk").values_list("system_received_at", flat=True).first()
    # An observed receipt starts the initial interval, not an invented earlier
    # macro regime. One microsecond ensures the first receipt can be new.
    return min(first or at, at) - timedelta(microseconds=1)


def _project(assembly, predecessor, at, context_id):
    retained = assembly["candidate"].to_dict()
    contracts = {item.source_id: item for item in assembly["contracts"]}
    revision_rows = {str(item.pk): item for item in assembly["revisions"]}
    attempts = {str(item.pk): item for item in assembly["attempts"]}
    for attempt in attempts.values():
        if text_digest(canonical_json(attempt.context)) != attempt.context_digest:
            raise theses.ThesisConflict("Retained analysis context failed integrity verification")
    reports, analyses = [], []
    for section in ("new", "background"):
        for item in retained["reports"][section]:
            row = revision_rows[item["revision_id"]]
            contract = contracts[item["source_id"]]
            reports.append({**item["payload"], "revision_id": item["revision_id"],
                "report_id": item["report_id"], "source_key": item["source_id"],
                "digest": item["payload_digest"], "received_at": item["received_at"],
                "availability_witness_at": item["availability_witness_at"], "section": section,
                "head_at_preparation_id": str(assembly["heads"][row.report_id]),
                "is_current_revision": assembly["heads"][row.report_id] == row.pk,
                "source_contract_digest": contract.digest,
                "source_contract_provenance": contract.provenance})
        for item in retained["analyses"][section]:
            attempt = attempts[item["analysis_id"]]
            analyses.append({"analysis_id": item["analysis_id"], "document": item["document"],
                "original_status": item["original_status"],
                "current_disposition": item["current_disposition"],
                "stale_reasons": item["current_stale_reasons"],
                "original_stale_reasons": item["original_stale_reasons"],
                "approval_id": str(attempt.approval_id),
                "interpretation_id": attempt.context["approved_thesis"].get("interpretation_id"),
                "exposure_digest": attempt.exposure_digest, "context_digest": attempt.context_digest,
                "source_revision_id": item["source_revision_id"], "section": section,
                "created_at": item["created_at"], "finished_at": item["finished_at"],
                "availability_witness_at": item["availability_witness_at"],
                "disposition_observed_at": item["disposition_observed_at"],
                "stop_reason": item["stop_reason"], "costs": item["costs"],
                "provider": attempt.provider, "model_id": attempt.model_id})
    gaps = [*retained["limitations"],
        "Starting macro context is unavailable; retained reports do not establish the current regime.",
        "Prior analyses are model interpretations, not independently verified facts."]
    gaps.extend(canonical_json(item) for item in retained["issues"])
    if predecessor is not None:
        changes = assembly["original_inputs"]["changes_since_predecessor"]
        gaps.append(canonical_json({"changes_since_predecessor": changes}))
    envelope = {"context_id": str(context_id), "cutoff": at.isoformat(),
        "policy_version": POLICY_VERSION, "reports": reports, "analyses": analyses,
        "deferred_reports": [{"revision_id": item["revision_id"], "reason": item["deferred_reason"]}
            for item in retained["reports"]["deferred"]],
        "deferred_analyses": [{"analysis_id": item["analysis_id"], "reason": item["deferred_reason"]}
            for item in retained["analyses"]["deferred"]],
        "gaps": gaps, "predecessor_context_id": str(predecessor.pk) if predecessor else None}
    envelope["digest"] = cumulative_digest(envelope)
    return envelope


def build_analysis_context(actor_id, thesis, approval, resolved, exposure, sources,
                           focus_revision, limits, at, *, persist=False):
    """Return the complete eligible context, optionally persist it at admission.

    Every retained selected-source revision and private analysis is either
    supplied or explicitly deferred. Bounds reject instead of truncating.
    """
    if connection.vendor != "postgresql" or not connection.in_atomic_block:
        raise RuntimeError("Analysis context requires protected PostgreSQL transaction state")
    if type(limits) is not DailyReviewLimits or type(persist) is not bool:
        raise ValueError("Explicit typed context limits and persistence mode are required")
    at = as_utc(at)
    if (str(thesis.owner_id) != actor_id or approval.thesis_id != thesis.pk
            or approval.pk != thesis.current_approval_id or resolved["thesis_id"] != str(thesis.pk)):
        raise theses.ThesisUnavailable("Analysis context unavailable")
    source_ids = [source.pk for source in sources]
    if (not source_ids or source_ids != sorted(set(source_ids))
            or len(source_ids) > limits.source_contracts
            or focus_revision.report.source_id not in source_ids):
        raise ValueError("Protected sources require a complete sorted unique explicit manifest")
    if (len(resolved["exposure"]["positions"]) > MAX_POSITION_RECORDS
            or len(resolved["exposure"]["positions"]) > limits.exposure_versions):
        raise ReviewCapacityExceeded("Complete attached exposure exceeds its configured bound")
    predecessor = _predecessor(actor_id, thesis, at)
    start = _start(source_ids, at, predecessor)
    contracts = [_contract(source, actor_id, at, persist) for source in sources]
    if any(contract.observed_at > at for contract in contracts):
        raise theses.ThesisConflict("Preparation clock precedes source permission state")
    assembly = service._assemble_evidence(actor_id, thesis, approval, resolved, exposure,
        sources, contracts, start, at, at, limits, predecessor, include_original_context=False)
    context_id = uuid4()
    envelope = _project(assembly, predecessor, at, context_id)
    if str(focus_revision.pk) not in {item["revision_id"] for item in envelope["reports"]}:
        raise theses.ThesisConflict("Focus report requires an eligible conservative availability witness")
    original_inputs = {**assembly["original_inputs"], "cumulative": envelope,
        "predecessor_assessment": {"status": "retained_model_interpretations" if envelope["analyses"] else "unavailable",
            "analysis_ids": [item["analysis_id"] for item in envelope["analyses"]],
            "publication_authority": False}}
    if len(canonical_json(original_inputs).encode("utf-8")) > limits.encoded_bytes:
        raise ReviewCapacityExceeded("Complete cumulative context exceeds its configured encoded bound")
    context = None
    if persist:
        context = service._persist_private_context(actor_id, thesis, approval, resolved, exposure,
            assembly, start, at, at, limits, predecessor, original_inputs=original_inputs,
            context_id=context_id, policy_version=POLICY_VERSION)
    return context, envelope
