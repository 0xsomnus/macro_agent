"""Complete retained evidence, frozen private contexts and read-only disposition."""

from dataclasses import asdict
from datetime import datetime

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from macro_agent.domain.daily_review import (
    DailyReviewLimits, DailyReviewPeriod, DailyReviewScope, RetainedNewsAnalysis,
    RetainedReport, ReviewIssue, ReviewCapacityExceeded, SourceContractReference, build_daily_review,
)
from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.domain.time import as_utc
from macro_agent.monitoring.gates import require_local_proof
from macro_agent.monitoring.models import (
    CaptureOutcome, NewsAnalysisAttempt, NewsAnalysisResult, ScreeningWork,
    SourceRevision, SourceState,
)
from macro_agent.monitoring.news_context import allowed_source
from macro_agent.persistence.context_binding import _at, _resolved, book_digest, lock_owner_thesis
from macro_agent.positions.representation import exposure_book
from macro_agent.positions.service import MAX_POSITION_RECORDS
from macro_agent.theses import compilation, service as theses

from .models import (
    AnalysisResultObservation, ContextExposure, DailyReview, EvidenceAnalysis, EvidenceRevision,
    EvidenceSet, EvidenceSource, PrivateContext, SourceContractHead,
)
from .permissions import contract_snapshot


class DeskDisabled(PermissionError):
    pass


def gate():
    require_local_proof()
    if getattr(settings, "MACRO_ENABLE_CONTINUOUS_DESK", False) is not True:
        raise DeskDisabled("Internal continuous desk is disabled")


def outermost():
    if connection.vendor != "postgresql" or connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("Desk operations require their own outermost PostgreSQL transaction")


def _source_ids(value):
    if type(value) not in (list, tuple) or not 1 <= len(value) <= 16:
        raise ValueError("An explicit manifest of one to sixteen source identities is required")
    result = [theses._text(item, "source_id", 128) for item in value]
    if len(set(result)) != len(result):
        raise ValueError("Source identities must be unique")
    return sorted(result)


def _lock_sources(source_ids):
    sources = list(SourceState.objects.select_for_update().filter(pk__in=source_ids).order_by("pk"))
    if [source.pk for source in sources] != source_ids:
        raise theses.ThesisUnavailable("A manifest source is unavailable")
    return sources


def _bounded(query, bound, label):
    rows = list(query[:bound + 1])
    if len(rows) > bound:
        raise ReviewCapacityExceeded(f"Complete {label} exceeds its configured bound; no records were discarded")
    return rows


def _status(attempt, result, thesis, exposure, sources, heads):
    reasons = []
    source = sources[attempt.source_revision.report.source_id]
    if attempt.approval_id != thesis.current_approval_id:
        reasons.append("approved_meaning_changed")
    if attempt.exposure_digest != exposure:
        reasons.append("paper_exposure_changed")
    if heads[attempt.source_revision.report_id] != attempt.source_revision_id:
        reasons.append("observed_source_revision_changed")
    if source.contract != attempt.resolved_inputs["source_contract"]:
        reasons.append("source_contract_changed")
    if not allowed_source(source):
        reasons.append("source_contract_unavailable")
    original = result.stale_reasons if result else []
    reasons = sorted(set(reasons + original))
    status = "stale" if reasons or result and result.status == "stale" else (
        "current" if result and result.status == "analysed" else "unresolved")
    return status, reasons


def _present_observation(thesis, source_ids):
    """Share governing reads only within the caller's coherent read snapshot.

    Never cache this across transactions. Each review still compares its own
    immutable source/revision membership through the single disposition rule.
    """
    return {
        "book": exposure_book(str(thesis.pk)),
        "heads": {head.source_id: head for head in SourceContractHead.objects.filter(
            source_id__in=source_ids).select_related("version")},
        "allowed": {source.pk: allowed_source(source) for source in
            SourceState.objects.filter(pk__in=source_ids)},
    }


def _present(row, thesis, at, *, observation=None):
    context = row.context
    if observation is None:
        observation = _present_observation(thesis, [reference["source_id"] for reference in
                                                   context.evidence.source_manifest])
    book = observation["book"]
    bounds = [row.prepared_at, thesis.changed_at, *(datetime.fromisoformat(
        position["payload"]["accepted_at"]) for position in book["positions"])]
    stale = []
    if thesis.current_approval_id != context.approval_id:
        stale.append("approved_meaning_changed")
    if book_digest(book) != context.exposure_digest:
        stale.append("paper_exposure_changed")
    for source_id, contract_id, source_digest, contract_digest in context.evidence.sources.values_list(
            "source_id", "contract_id", "source__contract_digest", "contract__digest"):
        head = observation["heads"].get(source_id)
        if head is not None:
            bounds.append(head.version.observed_at)
        if (head is None or head.version_id != contract_id
                or source_digest != contract_digest
                or not observation["allowed"].get(source_id, False)):
            stale.append("source_contract_or_permission_changed:" + source_id)
    for report_id, original_head_id, current_head_id, received_at in context.evidence.revisions.values_list(
            "revision__report_id", "head_at_preparation_id", "revision__report__current_revision_id",
            "revision__report__current_revision__system_received_at"):
        if received_at is not None:
            bounds.append(received_at)
        if current_head_id != original_head_id:
            stale.append("included_report_corrected:" + str(report_id))
    if any(at < bound for bound in bounds):
        raise theses.ThesisConflict("Disposition observation cannot precede the retained or present state")
    return {"status": "stale" if stale else "prepared", "stale_reasons": sorted(set(stale)),
            "observed_at": at.isoformat(), "publication_authority": False}


def _wire(row, thesis, at, *, replayed=False):
    if text_digest(canonical_json(row.content)) != row.digest:
        raise theses.ThesisConflict("Retained daily review failed integrity verification")
    return {"review": {"id": str(row.pk), "command_id": str(row.command_id),
        "context_id": str(row.context_id), "evidence_set_id": str(row.context.evidence_id),
        "evidence_set": {"id": str(row.context.evidence_id),
            "policy_version": row.context.evidence.policy_version,
            "limits": row.context.evidence.limits, "source_manifest": row.context.evidence.source_manifest},
        "predecessor_id": str(row.context.predecessor_id) if row.context.predecessor_id else None,
        "start": row.start.isoformat(), "cutoff": row.cutoff.isoformat(),
        "prepared_at": row.prepared_at.isoformat(), "original_outcome": row.original_outcome,
        "digest": row.digest, "content": row.content, "original_inputs": row.context.resolved_inputs},
        "current_disposition": _present(row, thesis, at), "replayed": replayed}


def inspect_review(actor_id, review_id, *, clock=timezone.now):
    gate()
    outermost()
    theses._uuid(review_id, "review_id")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        theses._owner(actor_id)
        row = DailyReview.objects.select_related("context__evidence").filter(pk=review_id, owner_id=actor_id).first()
        if row is None:
            raise theses.ThesisUnavailable("Daily review unavailable")
        thesis = theses._record(actor_id, str(row.thesis_id))
        return _wire(row, thesis, as_utc(clock()))


def get_review_command(actor_id, thesis_id, command_id, *, clock=timezone.now):
    gate()
    outermost()
    theses._uuid(command_id, "command_id")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        theses._owner(actor_id)
        thesis = theses._record(actor_id, thesis_id)
        row = DailyReview.objects.select_related("context__evidence").filter(
            owner_id=actor_id, thesis=thesis, command_id=command_id).first()
        if row is None:
            raise theses.ThesisUnavailable("Daily review command unavailable")
        return _wire(row, thesis, as_utc(clock()), replayed=True)


def observe_analysis_results(actor_id, thesis_id, source_ids, limit, *, clock=timezone.now):
    """Observe committed results now; missing earlier witnesses are never backfilled."""
    gate()
    outermost()
    source_ids = _source_ids(source_ids)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("An explicit analysis-observation bound between one and 1000 is required")
    with transaction.atomic():
        _lock_sources(source_ids)
        thesis = lock_owner_thesis(actor_id, thesis_id, "default")
        rows = _bounded(NewsAnalysisResult.objects.filter(attempt__owner_id=actor_id,
            attempt__thesis=thesis, attempt__source_revision__report__source_id__in=source_ids,
            analysisresultobservation__isnull=True).select_related("attempt").order_by("attempt_id"),
            limit, "analysis-result observations")
        at = _at(clock, thesis)
        if any(at < row.finished_at for row in rows):
            raise theses.ThesisConflict("Observation clock precedes a committed result")
        observations = [AnalysisResultObservation.objects.create(result=row, observed_by_at=at) for row in rows]
        return {"observed_analysis_ids": [str(item.pk) for item in observations],
                "observed_by_at": at.isoformat(), "method": "postcommit_read", "exact_commit_time": False}


def create_review(actor_id, thesis_id, command_id, start, cutoff, source_ids, limits,
                  *, clock=timezone.now):
    gate()
    outermost()
    command_id = theses._uuid(command_id, "command_id")
    source_ids = _source_ids(source_ids)
    if type(limits) is not DailyReviewLimits:
        raise ValueError("Explicit typed daily-review limits are required")
    start, cutoff = as_utc(start), as_utc(cutoff)
    if start >= cutoff or len(source_ids) > limits.source_contracts:
        raise ValueError("Reporting interval or source-manifest bound is invalid")
    request_digest = text_digest(canonical_json({"thesis_id": thesis_id, "start": start.isoformat(),
        "cutoff": cutoff.isoformat(), "source_ids": source_ids, "limits": asdict(limits)}))
    # Historical identity remains inspectable even after permission withdrawal.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        theses._owner(actor_id)
        thesis = theses._record(actor_id, thesis_id)
        old = DailyReview.objects.select_related("context__evidence").filter(owner_id=actor_id, command_id=command_id).first()
        if old is not None:
            if old.thesis_id != thesis.pk or old.request_digest != request_digest:
                raise theses.ThesisConflict("Review command belongs to different inputs")
            return _wire(old, thesis, as_utc(clock()), replayed=True)
    with transaction.atomic():
        sources = _lock_sources(source_ids)
        thesis = lock_owner_thesis(actor_id, thesis_id, "default")
        old = DailyReview.objects.select_related("context__evidence").filter(owner_id=actor_id, command_id=command_id).first()
        if old is not None:
            if old.thesis_id != thesis.pk or old.request_digest != request_digest:
                raise theses.ThesisConflict("Review command belongs to different inputs")
            return _wire(old, thesis, as_utc(clock()), replayed=True)
        if thesis.current_approval_id is None:
            raise theses.ThesisConflict("Approve exact thesis meaning before daily review")
        approval, resolved, exposure = _resolved(thesis, str(thesis.current_approval_id), "default")
        if len(resolved["exposure"]["positions"]) > MAX_POSITION_RECORDS:
            raise ReviewCapacityExceeded("Complete attached exposure exceeds the existing internal record bound")
        predecessor = DailyReview.objects.select_related("context__evidence").filter(
            owner_id=actor_id, thesis=thesis).order_by("-cutoff").first()
        if predecessor is not None and (predecessor.cutoff != start or cutoff <= predecessor.cutoff):
            raise theses.ThesisConflict("Review must continue the latest retained cutoff; missed older slots cannot replace it")
        at = _at(clock, thesis, resolved=resolved)
        period = DailyReviewPeriod(start, cutoff, at)
        contracts = [contract_snapshot(source, actor_id, at) for source in sources]
        if any(item.observed_at > at for item in contracts):
            raise theses.ThesisConflict("Preparation clock precedes source permission state")
        revisions = _bounded(SourceRevision.objects.filter(report__source_id__in=source_ids)
            .select_related("report", "report__current_revision", "durableobservation")
            .order_by("system_received_at", "id"), limits.reports, "retained source revisions")
        attempts = _bounded(NewsAnalysisAttempt.objects.filter(owner_id=actor_id, thesis=thesis,
            source_revision__report__source_id__in=source_ids).select_related(
                "source_revision__report", "result", "result__analysisresultobservation")
            .order_by("created_at", "id"), limits.analyses, "retained private analyses")
        by_source = {source.pk: source for source in sources}
        by_contract = {item.source_id: item for item in contracts}
        heads = {row.report_id: row.report.current_revision_id for row in revisions}
        reports, analyses, issues = [], [], []
        for row in revisions:
            contract, witness = by_contract[row.report.source_id], getattr(row, "durableobservation", None)
            reports.append(RetainedReport(str(row.pk), str(row.report_id), row.report.source_id,
                str(contract.pk), contract.digest, canonical_json(row.payload), row.digest,
                row.system_received_at, witness.observed_by_at if witness else None))
            if heads[row.report_id] != row.pk:
                issues.append(ReviewIssue("superseded:" + str(row.pk), "coverage_gap",
                    canonical_json({"code": "historical_source_revision", "head_at_preparation": str(heads[row.report_id])}),
                    source_id=row.report.source_id))
        for attempt in attempts:
            result = getattr(attempt, "result", None)
            witness = getattr(result, "analysisresultobservation", None) if result else None
            disposition, reasons = _status(attempt, result, thesis, exposure, by_source, heads)
            metadata = result.provider_metadata if result else {}
            analyses.append(RetainedNewsAnalysis(str(attempt.pk), actor_id, thesis_id,
                str(attempt.source_revision_id), attempt.created_at, result.finished_at if result else None,
                witness.observed_by_at if witness else None, result.status if result else None,
                tuple(result.stale_reasons) if result else (), disposition, tuple(reasons),
                canonical_json(attempt.context), canonical_json(result.document) if result and result.document is not None else None,
                canonical_json({"reported_cost_usd": metadata.get("reported_cost_usd"),
                    "estimated_cost_usd": compilation._estimate(attempt, metadata)}), result.stop_reason if result else None))
        work = _bounded(ScreeningWork.objects.filter(revision__report__source_id__in=source_ids)
            .exclude(state="superseded").select_related("revision__report").order_by("revision_id"),
            limits.issues, "screening-work diagnostics")
        for row in work:
            issues.append(ReviewIssue("screening:" + str(row.pk), "unresolved_work",
                canonical_json({"state": row.state, "attempt_count": row.attempt_count,
                    "lease_until": row.lease_until.isoformat() if row.lease_until else None,
                    "decision": "relevance_unresolved"}), source_id=row.revision.report.source_id))
        for source in sources:
            latest = CaptureOutcome.objects.filter(attempt__source=source).order_by("-attempt__sequence").first()
            if (source.last_successful_capture_at is not None and at < source.last_successful_capture_at
                    or latest is not None and at < latest.finished_at):
                raise theses.ThesisConflict("Preparation observation cannot precede retained source health")
            issues.append(ReviewIssue("coverage:" + source.pk, "coverage_gap", canonical_json({
                "coverage": "bounded_snapshot", "complete_market_coverage": False,
                "last_successful_capture_at": source.last_successful_capture_at.isoformat() if source.last_successful_capture_at else None,
                "last_outcome": latest.status if latest else None,
                "last_code": latest.code if latest else None,
                "active_capture_id": str(source.active_capture) if source.active_capture else None}), source_id=source.pk))
        scope = DailyReviewScope(actor_id, thesis_id, str(approval.pk), str(approval.interpretation_id),
            exposure, tuple(item["version_id"] for item in resolved["exposure"]["positions"]),
            tuple(SourceContractReference(item.source_id, str(item.pk), item.digest) for item in contracts),
            str(predecessor.context_id) if predecessor else None, None)
        candidate = build_daily_review(period=period, scope=scope, reports=tuple(reports), analyses=tuple(analyses),
            issues=tuple(issues), limits=limits)
        source_snapshots = [{"source_id": item.source_id, "version_id": str(item.pk), "digest": item.digest,
            "contract": item.contract, "provenance": item.provenance, "reviewer_id": str(item.reviewer_id),
            "reason": item.reason, "observed_at": item.observed_at.isoformat(), "permitted": item.permitted,
            "parent_id": str(item.parent_id) if item.parent_id else None} for item in contracts]
        original_inputs = {"approved_user": resolved, "source_contracts": source_snapshots,
            "starting_macro_context": {"status": "unavailable"},
            "predecessor_assessment": {"status": "unavailable", "reason": "No cumulative model assessment is implemented."},
            "changes_since_predecessor": {"approved_meaning_changed": bool(predecessor and predecessor.context.approval_id != approval.pk),
                "exposure_changed": bool(predecessor and predecessor.context.exposure_digest != exposure)}}
        if len(canonical_json({"review": candidate.to_dict(), "inputs": original_inputs}).encode("utf-8")) > limits.encoded_bytes:
            raise ReviewCapacityExceeded("Complete review and private context exceed the configured encoded bound")
        manifest = [{"source_id": item.source_id, "version_id": str(item.pk), "digest": item.digest,
            "provenance": item.provenance, "observed_at": item.observed_at.isoformat(), "permitted": item.permitted}
            for item in contracts]
        evidence = EvidenceSet.objects.create(owner_id=actor_id, thesis=thesis, start=start, cutoff=cutoff,
            prepared_at=at, limits=asdict(limits), source_manifest=manifest)
        EvidenceSource.objects.bulk_create([EvidenceSource(evidence=evidence, source_id=item.source_id,
            contract=item) for item in contracts])
        EvidenceRevision.objects.bulk_create([EvidenceRevision(evidence=evidence, revision=row,
            contract=by_contract[row.report.source_id], witness=getattr(row, "durableobservation", None),
            head_at_preparation_id=heads[row.report_id]) for row in revisions])
        EvidenceAnalysis.objects.bulk_create([EvidenceAnalysis(evidence=evidence, attempt=attempt,
            result=getattr(attempt, "result", None), witness=getattr(getattr(attempt, "result", None),
                "analysisresultobservation", None)) for attempt in attempts])
        context = PrivateContext.objects.create(owner_id=actor_id, thesis=thesis, approval=approval,
            interpretation_id=approval.interpretation_id, evidence=evidence,
            predecessor=predecessor.context if predecessor else None, exposure_digest=exposure,
            resolved_inputs=original_inputs, prepared_at=at)
        ContextExposure.objects.bulk_create([ContextExposure(context=context,
            position_id=position["position_id"], version_id=position["version_id"])
            for position in resolved["exposure"]["positions"]])
        row = DailyReview.objects.create(owner_id=actor_id, thesis=thesis, command_id=command_id,
            context=context, request_digest=request_digest, start=start, cutoff=cutoff, prepared_at=at,
            content=candidate.to_dict(), digest=candidate.digest)
        return _wire(row, thesis, at)
