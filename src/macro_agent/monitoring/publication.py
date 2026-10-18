"""Protected evolving driver briefs and qualified internal review intents.

Sources precede owner, thesis and sorted briefs. The exact admitted cumulative
analysis remains immutable. This path makes no model call or external delivery.
"""

from django.db import connection, transaction
from django.utils import timezone

from macro_agent.domain.models import canonical_json, require_digest, text_digest
from macro_agent.domain.news_publication import (POLICY_VERSION, NewsPublicationCandidate,
    decide_attention, decide_news_publication)
from macro_agent.domain.time import as_utc
from macro_agent.desk import invalidation, service as desk
from macro_agent.persistence.context_binding import _at, lock_owner_thesis, lock_thesis_briefs
from macro_agent.persistence.models import (AssessmentRecord, AuditTransition, BriefStateRecord,
    BriefVersion, CurrentAssessment, NotificationIntent, ReassessmentWork)
from macro_agent.theses import service as theses
from . import analysis
from .attention_models import NewsBrief, NewsPublication
from .models import NewsAnalysisAttempt

RELATED = ("attempt__admission_context__evidence", "attempt__result", "assessment", "brief", "predecessor__attempt__result", "attention_origin__attempt__admission_context__evidence")


def _policy(fanout_limit, policy_version):
    if type(fanout_limit) is not int or not 1 <= fanout_limit <= 1000 or policy_version != POLICY_VERSION:
        raise ValueError("News publication requires an explicit fanout limit from one to 1000 and exact review policy")


def _request(analysis_id, digest, generation, fanout_limit, policy_version):
    theses._uuid(analysis_id, "analysis_id")
    require_digest(digest, "expected_analysis_digest")
    if type(generation) is not int or not 0 <= generation <= 2**63-1:
        raise ValueError("expected_generation requires a nonnegative database integer")
    _policy(fanout_limit, policy_version)
    return text_digest(canonical_json({"analysis_id": analysis_id, "analysis_digest": digest,
        "expected_generation": generation, "fanout_limit": fanout_limit, "policy_version": policy_version}))


def _attempt(actor_id, analysis_id):
    row = NewsAnalysisAttempt.objects.select_related("admission_context__evidence", "result").filter(
        pk=analysis_id, owner_id=actor_id).first()
    if row is None:
        raise theses.ThesisUnavailable("News analysis unavailable")
    return row


def _content(row):
    try:
        result = row.result
    except AttributeError:
        raise theses.ThesisConflict("Only a completed retained driver analysis can be published") from None
    if row.admission_context_id is None or result.document is None:
        raise theses.ThesisConflict("News publication requires retained cumulative driver-review context")
    return canonical_json({"analysis_id": str(row.pk), "owner_id": str(row.owner_id),
        "thesis_id": str(row.thesis_id), "approval_id": str(row.approval_id),
        "exposure_digest": row.exposure_digest, "created_at": row.created_at.isoformat(),
        "finished_at": result.finished_at.isoformat(), "original_status": result.status,
        "original_stale_reasons": result.stale_reasons, "context_id": str(row.admission_context_id),
        "context_digest": row.context_digest, "context": row.context, "document": result.document,
        "model": {"provider": row.provider, "model_id": row.model_id,
            "configuration": row.configuration, "catalogue_metadata": row.model_metadata,
            "prompt_digest": row.prompt_digest, "provider_metadata": result.provider_metadata}})


def _candidate(row, command_id, generation, policy_version):
    content = _content(row)
    try:
        return NewsPublicationCandidate(command_id, str(row.owner_id), str(row.thesis_id),
            "news:" + str(row.thesis_id), str(row.pk), text_digest(content), generation,
            policy_version, content)
    except (ValueError, TypeError, KeyError) as error:
        raise theses.ThesisConflict("Retained news publication failed exact analysis validation") from error


def _context_current(row):
    with connection.cursor() as cursor:
        cursor.execute("SELECT desk_daily_context_current(%s)", [str(row.admission_context_id)])
        return cursor.fetchone()[0]


def _stale(row, thesis):
    reasons = analysis._stale_reasons(row, thesis)
    if not _context_current(row):
        reasons.append("retained_context_changed")
    return sorted(set(reasons))


def _sources(row):
    if row.admission_context_id is None:
        raise theses.ThesisConflict("News publication requires a retained cumulative context")
    return desk._source_ids([item["source_id"] for item in row.admission_context.evidence.source_manifest])


def _preserve_attention_origin(origin, attempt, protected_source_ids):
    """Carry existing work only when its exact dependencies remain protected.

    No source lock can be acquired after owner/thesis protection. The complete
    origin membership must already be contained in the newly admitted context.
    """
    from macro_agent.desk.models import EvidenceRevision, EvidenceSource
    original = origin.attempt
    if (origin.attention_decision["status"] != "review_requested"
            or not set(_sources(original)).issubset(protected_source_ids)
            or not _context_current(original)):
        raise theses.ThesisConflict("Pending review dependencies require the complete current original evidence before publication")
    old_evidence = original.admission_context.evidence_id
    new_evidence = attempt.admission_context.evidence_id
    for model, fields in ((EvidenceSource, ("source_id", "contract_id")),
                          (EvidenceRevision, ("revision_id", "head_at_preparation_id"))):
        previous = set(model.objects.filter(evidence_id=old_evidence).values_list(*fields))
        current = set(model.objects.filter(evidence_id=new_evidence).values_list(*fields))
        if not previous.issubset(current):
            raise theses.ThesisConflict("Pending review evidence cannot disappear or change while its work is carried")


def _snapshot():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")


def _wire(row, thesis, at, *, replayed=False):
    binding = NewsBrief.objects.get(brief_id=row.brief_id)
    candidate = _candidate(row.attempt, str(row.command_id), row.expected_generation, binding.policy_version)
    if (row.analysis_digest != candidate.analysis_digest or row.assessment.payload != candidate.payload
            or row.assessment.digest != candidate.digest or row.assessment.assessment_id != candidate.assessment_id
            or row.assessment.saved_at != row.published_at or row.request_digest != _request(str(row.attempt_id),
                row.analysis_digest, row.expected_generation, binding.fanout_limit, binding.policy_version)):
        raise theses.ThesisConflict("Retained news publication failed integrity verification")
    if at < max(row.published_at, row.brief.changed_at):
        raise theses.ThesisConflict("News observation cannot precede protected publication state")
    reasons = _stale(row.attempt, thesis)
    if row.assessment.status != "current":
        reasons.extend(row.assessment.reasons)
    pointed = CurrentAssessment.objects.filter(brief_id=row.brief_id, assessment_id=row.assessment_id).exists()
    if not pointed:
        reasons.append("newer_publication" if row.brief.generation > row.expected_generation+1 else "publication_not_current")
    version = BriefVersion.objects.filter(brief_id=row.brief_id, assessment_id=row.assessment_id).first()
    if row.assessment.status == "current" and (version is None or version.generation != row.expected_generation+1):
        raise theses.ThesisConflict("News publication has no exact retained generation")
    intent = NotificationIntent.objects.filter(brief_id=row.brief_id, assessment_id=row.assessment_id).first()
    if intent and at < intent.updated_at:
        raise theses.ThesisConflict("News observation precedes notification state")
    return {"publication": {"id": str(row.pk), "command_id": str(row.command_id),
        "analysis_id": str(row.attempt_id), "analysis_digest": row.analysis_digest,
        "brief_id": row.brief_id, "assessment_id": row.assessment.assessment_id,
        "expected_generation": row.expected_generation, "published_at": row.published_at.isoformat(),
        "original_decision": {"status": row.assessment.status, "reasons": row.assessment.reasons,
            "reassessment_required": row.assessment.reassessment_required},
        "generation_at_publication": version.generation if version else None,
        "attention_decision": row.attention_decision,
        "predecessor_publication_id": str(row.predecessor_id) if row.predecessor_id else None,
        "slot_lease_token": str(row.slot_lease_id) if row.slot_lease_id else None,
        "attention_origin_publication_id": (str(row.attention_origin_id or row.pk)
            if row.attention_decision["status"] in ("review_requested", "review_carried") else None)},
        "current_disposition": {"status": "superseded" if reasons else "current",
            "reasons": sorted(set(reasons)), "observed_at": at.isoformat()},
        "notification_intent": {"id": intent.pk, "state": intent.state} if intent else None,
        "analysis": analysis._response(row.attempt, thesis, at)["analysis"], "replayed": replayed}


def preview_publication(actor_id, analysis_id, fanout_limit, policy_version, *, clock=timezone.now):
    desk.gate(); desk.outermost()
    theses._uuid(analysis_id, "analysis_id"); _policy(fanout_limit, policy_version)
    with transaction.atomic():
        _snapshot(); theses._owner(actor_id)
        attempt = _attempt(actor_id, analysis_id)
        thesis = theses._record(actor_id, str(attempt.thesis_id))
        binding = NewsBrief.objects.select_related("brief").filter(thesis=thesis).first()
        if binding and (binding.fanout_limit, binding.policy_version) != (fanout_limit, policy_version):
            raise theses.ThesisConflict("News stream differs from its immutable reviewed configuration")
        candidate = _candidate(attempt, str(attempt.pk), binding.brief.generation if binding else 0, policy_version)
        at = as_utc(clock())
        if at < max(thesis.changed_at, attempt.result.finished_at, binding.brief.changed_at if binding else thesis.changed_at):
            raise theses.ThesisConflict("Preview observation precedes retained news state")
        return {"analysis_id": str(attempt.pk), "analysis_digest": candidate.analysis_digest,
            "thesis_id": str(thesis.pk), "brief_id": candidate.brief_id,
            "expected_generation": candidate.expected_generation, "fanout_limit": fanout_limit,
            "policy_version": policy_version, "current_disposition": {"stale_reasons": _stale(attempt, thesis),
                "observed_at": at.isoformat()}}


def _retry(row, digest, thesis, at):
    if row.request_digest != digest:
        raise theses.ThesisConflict("Publication command belongs to different news inputs")
    return _wire(row, thesis, at, replayed=True)


def get_publication_command(actor_id, thesis_id, command_id, *, clock=timezone.now):
    desk.gate(); desk.outermost(); theses._uuid(command_id, "command_id")
    with transaction.atomic():
        _snapshot(); theses._owner(actor_id); thesis = theses._record(actor_id, thesis_id)
        row = NewsPublication.objects.select_related(*RELATED).filter(owner_id=actor_id, thesis=thesis,
            command_id=command_id).first()
        if row is None:
            raise theses.ThesisUnavailable("News publication command unavailable")
        return _wire(row, thesis, as_utc(clock()), replayed=True)


def inspect_publication(actor_id, publication_id, *, clock=timezone.now):
    desk.gate(); desk.outermost(); theses._uuid(publication_id, "publication_id")
    with transaction.atomic():
        _snapshot(); theses._owner(actor_id)
        row = NewsPublication.objects.select_related(*RELATED).filter(owner_id=actor_id, pk=publication_id).first()
        if row is None:
            raise theses.ThesisUnavailable("News publication unavailable")
        return _wire(row, theses._record(actor_id, str(row.thesis_id)), as_utc(clock()))


def get_current_brief(actor_id, thesis_id, *, clock=timezone.now):
    desk.gate(); desk.outermost()
    with transaction.atomic():
        _snapshot(); theses._owner(actor_id); thesis = theses._record(actor_id, thesis_id)
        binding = NewsBrief.objects.select_related("brief").filter(thesis=thesis).first()
        row = None
        if binding:
            pointer = CurrentAssessment.objects.filter(brief=binding.brief).first()
            if pointer:
                row = NewsPublication.objects.select_related(*RELATED).filter(owner_id=actor_id,
                    brief=binding.brief, assessment_id=pointer.assessment_id).first()
                if row is None:
                    raise theses.ThesisConflict("News current pointer has no scoped publication")
        at = as_utc(clock())
        if at < thesis.changed_at or binding and at < binding.brief.changed_at:
            raise theses.ThesisConflict("News observation precedes governing state")
        current = _wire(row, thesis, at) if row else None
        if current and current["current_disposition"]["status"] != "current":
            raise theses.ThesisConflict("News current pointer disagrees with protected governing state")
        return {"thesis_id": str(thesis.pk), "brief_id": binding.pk if binding else None,
            "generation": binding.brief.generation if binding else 0,
            "current_publication": current, "observed_at": at.isoformat()}


def publish_analysis(actor_id, analysis_id, command_id, expected_analysis_digest,
                     expected_generation, fanout_limit, policy_version, *, clock=timezone.now, slot_token=None):
    desk.gate(); desk.outermost(); theses._uuid(command_id, "command_id")
    request_digest = _request(analysis_id, expected_analysis_digest, expected_generation, fanout_limit, policy_version)
    with transaction.atomic():
        _snapshot(); theses._owner(actor_id)
        attempt = _attempt(actor_id, analysis_id)
        thesis = theses._record(actor_id, str(attempt.thesis_id))
        old = NewsPublication.objects.select_related(*RELATED).filter(owner_id=actor_id, command_id=command_id).first()
        if old:
            return _retry(old, request_digest, thesis, as_utc(clock()))
        source_ids = _sources(attempt)
    with transaction.atomic():
        desk._lock_sources(source_ids)
        thesis = lock_owner_thesis(actor_id, str(attempt.thesis_id), "default")
        briefs = lock_thesis_briefs(thesis)
        old = NewsPublication.objects.select_related(*RELATED).filter(owner_id=actor_id, command_id=command_id).first()
        if old:
            return _retry(old, request_digest, thesis, _at(clock, thesis, briefs))
        attempt = _attempt(actor_id, analysis_id)
        if NewsPublication.objects.filter(attempt=attempt).exists():
            raise theses.ThesisConflict("This retained analysis already has an immutable publication decision")
        binding = NewsBrief.objects.select_related("brief").filter(thesis=thesis).first()
        if binding and (binding.fanout_limit, binding.policy_version) != (fanout_limit, policy_version):
            raise theses.ThesisConflict("News stream differs from its immutable reviewed configuration")
        candidate = _candidate(attempt, command_id, expected_generation, policy_version)
        if candidate.analysis_digest != expected_analysis_digest:
            raise theses.ThesisConflict("Analysis digest differs; inspect the exact retained analysis")
        if slot_token is not None:
            from macro_agent.scheduling import service as schedule
            lease, slot, _, watch, observed = schedule._protected_lease(actor_id, slot_token, clock)
            schedule._active(lease, slot, observed)
            selected = lease.recovery.watch_version if lease.recovery_id else slot.watch_version
            expected_sources = [{"source_id": item["source_id"], "contract_digest": item["digest"]}
                for item in attempt.admission_context.evidence.source_manifest]
            configured_sources = selected.configuration["sources"]
            if (slot.kind != "analysis" or slot.thesis_id != thesis.pk
                    or str(slot.command_id) != command_id or attempt.command_id != slot.command_id
                    or watch.current_version_id != selected.pk
                    or selected.configuration.get("news_publication") != {
                        "fanout_limit": fanout_limit, "policy_version": policy_version}
                    or selected.configuration["model_configuration"] != attempt.configuration
                    or selected.configuration["provider"] != attempt.provider
                    or selected.configuration["model_id"] != attempt.model_id
                    or selected.configuration["approval_id"] != str(attempt.approval_id)
                    or selected.configuration["exposure_digest"] != attempt.exposure_digest
                    or sorted(configured_sources, key=lambda item: item["source_id"]) != expected_sources):
                raise schedule.ScheduleConflict("News publication does not match its exact current reviewed analysis slot")
            at = _at(lambda: observed, thesis, briefs)
        else:
            at = _at(clock, thesis, briefs)
        from .cumulative import check_cumulative_clock
        check_cumulative_clock(attempt, at)
        if at < attempt.result.finished_at:
            raise theses.ThesisConflict("Publication observation precedes retained analysis completion")
        if binding is None:
            if BriefStateRecord.objects.filter(pk=candidate.brief_id).exists():
                raise theses.ThesisConflict("News stream identity is already used by another contract")
            brief = BriefStateRecord.objects.create(brief_id=candidate.brief_id, owner_id=actor_id, changed_at=at)
            binding = NewsBrief.objects.create(brief=brief, owner_id=actor_id, thesis=thesis,
                fanout_limit=fanout_limit, policy_version=policy_version, created_at=at)
        brief = binding.brief
        latest = NewsAnalysisAttempt.objects.filter(thesis=thesis, approval_id=attempt.approval_id,
            exposure_digest=attempt.exposure_digest, admission_context__isnull=False,
            context__driver_review=True, result__status="analysed").order_by("-created_at", "-id").first()
        decision = decide_news_publication(candidate, owner_id=actor_id, thesis_id=str(thesis.pk),
            generation=brief.generation, changed_at=brief.changed_at,
            latest_analysis_id=str(latest.pk) if latest else None, stale_reasons=_stale(attempt, thesis), at=at)
        predecessor = NewsPublication.objects.select_related("attempt__result").filter(brief=brief,
            assessment__status="current").order_by("-expected_generation").first()
        pending_predecessor = predecessor is not None and NotificationIntent.objects.filter(
            brief=brief, assessment_id=predecessor.assessment_id, state="pending").exists()
        active_predecessor = predecessor is not None and CurrentAssessment.objects.filter(
            brief=brief, assessment_id=predecessor.assessment_id).exists()
        prior_signatures = [predecessor.attention_decision["signal_digest"]] if pending_predecessor else []
        import json
        attention = decide_attention(json.loads(candidate.content_json),
            previous_document=predecessor.attempt.result.document if active_predecessor else None,
            prior_signatures=prior_signatures)
        attention_origin = None
        if decision.status == "current" and pending_predecessor and attention["status"] != "review_requested":
            attention_origin = predecessor.attention_origin or predecessor
            _preserve_attention_origin(attention_origin, attempt, source_ids)
            attention = {"policy_version": POLICY_VERSION, "status": "review_carried",
                "reason": "The earlier pending qualified review remains unresolved and follows the evolving brief; this carries internal work without requesting another interruption.",
                "signal_digest": predecessor.attention_decision["signal_digest"], "kind": "qualified_driver_review"}
        if decision.status != "current":
            attention = {"policy_version": POLICY_VERSION, "status": "superseded", "reason": "Stale or superseded analysis has no current attention authority.",
                "signal_digest": None, "kind": "qualified_driver_review"}
        else:
            invalidation.check_publication_capacity(source_ids=source_ids, brief_id=brief.pk, fanout_limit=fanout_limit)
        assessment = AssessmentRecord.objects.create(brief=brief, assessment_id=candidate.assessment_id,
            digest=candidate.digest, payload=candidate.payload, status=decision.status, reasons=list(decision.reasons),
            reassessment_required=decision.reassessment_required,
            observed_dependencies=[{"context_id": str(attempt.admission_context_id), "analysis_digest": candidate.analysis_digest,
                "approval_id": str(attempt.approval_id), "exposure_digest": attempt.exposure_digest,
                "source_manifest": attempt.admission_context.evidence.source_manifest}], saved_at=at)
        row = NewsPublication.objects.create(command_id=command_id, owner_id=actor_id, thesis=thesis, brief=brief,
            attempt=attempt, assessment=assessment, request_digest=request_digest, analysis_digest=candidate.analysis_digest,
            expected_generation=expected_generation, predecessor=predecessor, attention_origin=attention_origin,
            attention_decision=attention, slot_lease_id=slot_token, published_at=at)
        canceled = []
        if decision.status == "current":
            brief.generation += 1; brief.changed_at = at
            brief.save(update_fields=("generation", "changed_at"))
            CurrentAssessment.objects.update_or_create(brief=brief, defaults={"assessment": assessment})
            BriefVersion.objects.create(brief=brief, generation=brief.generation, assessment=assessment, saved_at=at)
            canceled = list(NotificationIntent.objects.filter(brief=brief, state="pending").values_list("pk", flat=True))
            NotificationIntent.objects.filter(brief=brief, state="pending").update(state="canceled", updated_at=at)
            ReassessmentWork.objects.filter(brief=brief, state="pending").update(state="superseded", completed_at=at)
            if attention["status"] in ("review_requested", "review_carried"):
                NotificationIntent.objects.create(intent_id=candidate.intent_id, brief=brief, assessment=assessment,
                    created_at=at, updated_at=at)
        elif decision.reassessment_required:
            ReassessmentWork.objects.get_or_create(brief=brief, context_digest=candidate.digest,
                defaults={"reason": ", ".join(decision.reasons), "created_at": at})
        AuditTransition.objects.create(brief=brief, kind="news_publication", happened_at=at,
            detail={"publication_id": str(row.pk), "analysis_id": str(attempt.pk), "command_id": command_id,
                "status": decision.status, "reasons": list(decision.reasons), "generation": brief.generation,
                "attention_decision": attention, "canceled_intents": canceled, "slot_lease_token": slot_token})
        return _wire(row, thesis, at)
