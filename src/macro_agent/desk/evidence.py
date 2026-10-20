"""Freeze selected retained source evidence independently of thesis approval.

Selection is explicit, current-only and bounded. Permission observations do not
grant new rights. All write paths protect sources before owner and thesis.
"""

from django.db import connection, transaction
from django.utils import timezone

from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.domain.source_evidence import (SOURCE_EVIDENCE_SCHEMA_VERSION,
    SOURCE_EVIDENCE_QUESTION_SCHEMA_VERSION, SOURCE_EVIDENCE_RECOVERY_SCHEMA_VERSION,
    validate_source_evidence)
from macro_agent.domain.time import as_utc
from macro_agent.monitoring.models import SourceRevision, SourceState
from macro_agent.monitoring.news_context import allowed_research_source as allowed_source
from macro_agent.theses import service as theses

from .models import SourceContractHead
from .permissions import contract_snapshot
from .research_models import ResearchEvidenceContext, ResearchEvidenceMember


GAPS = [
    "Explicitly selected retained reports do not establish broad market coverage or the current macro regime.",
    "Source statements and exact quotations establish attribution, not factual truth or semantic support.",
    "Consensus, current prices, valuation and instrument mapping are unavailable unless explicitly supported.",
]


def _gate():
    from macro_agent.theses.compilation import _gate as compilation_gate
    compilation_gate()
    if connection.vendor != "postgresql" or connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("Research evidence requires its own outermost PostgreSQL transaction")


def _validated(context):
    from macro_agent.monitoring.news_context import research_source_owned_by
    content = validate_source_evidence(context.content)
    if text_digest(canonical_json(content)) != context.digest:
        raise theses.ThesisConflict("Retained research evidence failed integrity verification")
    members = list(context.members.select_related("revision__report", "contract", "witness"))
    reports = {item["revision_id"]: item for item in content["reports"]}
    if len(members) != len(reports):
        raise theses.ThesisConflict("Retained research evidence membership is incomplete")
    for member in members:
        report = reports.get(str(member.revision_id))
        row = member.revision
        if not research_source_owned_by(row.report.source, context.owner_id):
            raise theses.ThesisConflict("Research evidence is outside its private investigation scope")
        if (report is None or report["source_id"] != row.report.source_id
                or report["contract_version_id"] != str(member.contract_id)
                or report["contract_digest"] != member.contract.digest
                or report["head_at_admission_id"] != str(member.head_at_admission_id)
                or member.witness_id != row.pk
                or report["title"] != row.payload["title"] or report["content"] != row.payload["content"]
                or report["source_url"] != row.payload["url"]
                or report["source_claimed_published_at"] != row.payload["published_at"]
                or report["system_received_at"] != row.system_received_at.isoformat()
                or report["availability_witness_at"] != member.witness.observed_by_at.isoformat()
                or text_digest(canonical_json(row.payload)) != row.digest):
            raise theses.ThesisConflict("Retained research evidence differs from its immutable inputs")
    if content["cutoff"] != context.created_at.isoformat():
        raise theses.ThesisConflict("Retained research cutoff differs from preparation time")
    if "question_research" in content:
        from .question_evidence import build_context, retained_contracts
        retained = content["question_research"]
        expected = build_context(context.owner_id, context.thesis_id, retained["run_id"],
                                 content["reports"], context.created_at, retained_contracts(retained))
        if expected != retained:
            raise theses.ThesisConflict("Retained investigation context differs from its exact lineage")
    return content


def get_context(actor_id, thesis_id, context_id):
    theses._uuid(context_id, "evidence_context_id")
    context = ResearchEvidenceContext.objects.filter(pk=context_id, owner_id=actor_id,
                                                     thesis_id=thesis_id).first()
    if context is None:
        raise theses.ThesisUnavailable("Research evidence unavailable")
    _validated(context)
    return context


def source_ids_for_context(context):
    content = _validated(context)
    ids = {item["source_id"] for item in content["reports"]}
    if "question_research" in content:
        ids.update(item["source_id"] for item in content["question_research"]["questions"])
    return sorted(ids)


def lock_context_sources(context):
    ids = source_ids_for_context(context)
    sources = list(SourceState.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    if [source.pk for source in sources] != ids:
        raise theses.ThesisUnavailable("Research source unavailable")
    return sources


def context_stale_reasons(context, at=None):
    content = _validated(context)
    reasons = set()
    bounds = [context.created_at]
    for member in context.members.select_related("revision__report__source",
            "revision__report__current_revision", "contract"):
        source = member.revision.report.source
        head = SourceContractHead.objects.select_related("version").filter(source=source).first()
        if (head is None or head.version_id != member.contract_id
                or source.contract_digest != member.contract.digest or source.contract != member.contract.contract):
            reasons.add("research_source_contract_changed:" + source.pk)
        if not allowed_source(source, context.owner_id):
            reasons.add("research_source_permission_unavailable:" + source.pk)
        current = member.revision.report.current_revision
        if current is None or current.pk != member.head_at_admission_id:
            reasons.add("research_report_corrected:" + str(member.revision.report_id))
        if current is not None:
            bounds.append(current.system_received_at)
        if head is not None:
            bounds.append(head.version.observed_at)
    if "question_research" in content:
        from .question_evidence import retained_contracts
        for source_id, contract in retained_contracts(content["question_research"]).items():
            source = contract.source
            head = SourceContractHead.objects.select_related("version").filter(source=source).first()
            if (head is None or head.version_id != contract.pk
                    or source.contract_digest != contract.digest or source.contract != contract.contract):
                reasons.add("research_source_contract_changed:" + source_id)
            if not allowed_source(source, context.owner_id):
                reasons.add("research_source_permission_unavailable:" + source_id)
            if head is not None:
                bounds.append(head.version.observed_at)
    if at is not None and any(as_utc(at) < bound for bound in bounds):
        raise theses.ThesisConflict("Research observation cannot precede retained or present source state")
    return sorted(reasons)


def _wire(context, at, replayed=False):
    content = _validated(context)
    stale = context_stale_reasons(context, at)
    return {"evidence": {"id": str(context.pk), "command_id": str(context.command_id),
        "thesis_id": str(context.thesis_id), "digest": context.digest, "content": content,
        "created_at": context.created_at.isoformat()},
        "current_disposition": {"status": "stale" if stale else "current", "stale_reasons": stale,
                                "observed_at": at.isoformat()}, "replayed": replayed}


def _snapshot():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")


def get_evidence(actor_id, thesis_id, context_id, *, clock=timezone.now):
    _gate()
    with transaction.atomic():
        _snapshot()
        theses._owner(actor_id)
        theses._record(actor_id, thesis_id)
        context = get_context(actor_id, thesis_id, context_id)
        return _wire(context, as_utc(clock()))


def get_evidence_command(actor_id, thesis_id, command_id, *, clock=timezone.now):
    _gate()
    theses._uuid(command_id, "command_id")
    with transaction.atomic():
        _snapshot()
        theses._owner(actor_id)
        theses._record(actor_id, thesis_id)
        context = ResearchEvidenceContext.objects.filter(owner_id=actor_id,
            thesis_id=thesis_id, command_id=command_id).first()
        if context is None:
            raise theses.ThesisUnavailable("Research evidence unavailable")
        return _wire(context, as_utc(clock()), replayed=True)


def prepare_evidence(actor_id, thesis_id, command_id, revision_ids, *, question_run_id=None,
                     clock=timezone.now):
    _gate()
    theses._uuid(thesis_id, "thesis_id")
    theses._uuid(command_id, "command_id")
    if type(revision_ids) not in (list, tuple) or not 1 <= len(revision_ids) <= 16:
        raise ValueError("Select one to sixteen unique current source revisions")
    revision_ids = [theses._uuid(item, "revision_id") for item in revision_ids]
    if len(set(revision_ids)) != len(revision_ids):
        raise ValueError("Selected revisions must be unique")
    revision_ids = sorted(revision_ids)
    request = {"thesis_id": thesis_id, "revision_ids": revision_ids}
    if question_run_id is not None:
        request["question_run_id"] = theses._uuid(str(question_run_id), "question_run_id")
    digest = text_digest(canonical_json(request))
    # Recovery compares the retained request before current rights or heads.
    with transaction.atomic():
        _snapshot()
        theses._owner(actor_id)
        theses._record(actor_id, thesis_id)
        saved = ResearchEvidenceContext.objects.filter(owner_id=actor_id, command_id=command_id).first()
        if saved is not None:
            if str(saved.thesis_id) != thesis_id or saved.request_digest != digest:
                raise theses.ThesisConflict("Research command belongs to another request")
            return _wire(saved, as_utc(clock()), replayed=True)
        ids = sorted(set(SourceRevision.objects.filter(pk__in=revision_ids)
                         .values_list("report__source_id", flat=True)))
        if question_run_id is not None:
            from .question_evidence import source_ids
            ids = sorted(set(ids) | set(source_ids(actor_id, thesis_id, question_run_id)))
    with transaction.atomic():
        sources = list(SourceState.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
        theses._owner(actor_id, lock=True)
        thesis = theses._record(actor_id, thesis_id, lock=True)
        saved = ResearchEvidenceContext.objects.filter(owner_id=actor_id, command_id=command_id).first()
        if saved is not None:
            if str(saved.thesis_id) != thesis_id or saved.request_digest != digest:
                raise theses.ThesisConflict("Research command belongs to another request")
            return _wire(saved, theses._instant(clock, thesis), replayed=True)
        rows = list(SourceRevision.objects.filter(pk__in=revision_ids).select_related(
            "report", "durableobservation").order_by("pk"))
        if [str(row.pk) for row in rows] != revision_ids or [row.pk for row in sources] != ids:
            raise theses.ThesisUnavailable("Selected research evidence unavailable")
        if any(row.report.current_revision_id != row.pk for row in rows):
            raise theses.ThesisConflict("Select current source revisions after reviewing corrections")
        if any(getattr(row, "durableobservation", None) is None for row in rows):
            raise theses.ThesisConflict("Selected research evidence requires a conservative durable witness")
        at = theses._instant(clock, thesis)
        contracts = {source.pk: contract_snapshot(source, actor_id, at, research=True) for source in sources}
        if any(contract.observed_at > at for contract in contracts.values()):
            raise theses.ThesisConflict("Research preparation precedes source permission observation")
        reports = [{"revision_id": str(row.pk), "source_id": row.report.source_id,
            "title": row.payload["title"], "content": row.payload["content"], "source_url": row.payload["url"],
            "source_claimed_published_at": row.payload["published_at"],
            "system_received_at": row.system_received_at.isoformat(),
            "availability_witness_at": row.durableobservation.observed_by_at.isoformat(),
            "contract_version_id": str(contracts[row.report.source_id].pk),
            "contract_digest": contracts[row.report.source_id].digest,
            "head_at_admission_id": str(row.pk)} for row in rows]
        content = {"schema_version": SOURCE_EVIDENCE_SCHEMA_VERSION,
            "cutoff": at.isoformat(), "reports": reports, "gaps": GAPS}
        if question_run_id is not None:
            from .question_evidence import build_context
            content["schema_version"] = SOURCE_EVIDENCE_QUESTION_SCHEMA_VERSION
            content["question_research"] = build_context(actor_id, thesis_id,
                                                         question_run_id, reports, at, contracts)
            if content["question_research"]["schema_version"] == "question-research-context-v2":
                content["schema_version"] = SOURCE_EVIDENCE_RECOVERY_SCHEMA_VERSION
        content = validate_source_evidence(content)
        context = ResearchEvidenceContext.objects.create(owner_id=actor_id, thesis=thesis,
            command_id=command_id, request_digest=digest, content=content,
            digest=text_digest(canonical_json(content)), created_at=at)
        ResearchEvidenceMember.objects.bulk_create([ResearchEvidenceMember(context=context, revision=row,
            contract=contracts[row.report.source_id], witness=row.durableobservation,
            head_at_admission=row) for row in rows])
        return _wire(context, at)
