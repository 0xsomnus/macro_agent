"""Protected daily authority, separate from factual-notice admission.

Sources, owner, thesis and all bound briefs are protected before observing time.
Retained reviews and original decisions never change. Current pointers and pending
notification intents change atomically; no external delivery belongs here.
"""

from django.db import connection, transaction
from django.utils import timezone

from macro_agent.domain.daily_publication import DailyPublicationCandidate, DailyPublicationState, decide_daily_publication
from macro_agent.domain.models import canonical_json, require_digest, text_digest
from macro_agent.domain.time import as_utc
from macro_agent.persistence.context_binding import _at, lock_owner_thesis, lock_thesis_briefs
from macro_agent.persistence.models import (
    AssessmentRecord, AuditTransition, BriefStateRecord, BriefVersion, CurrentAssessment,
    NotificationIntent, ReassessmentWork,
)
from macro_agent.theses import service as theses

from . import invalidation, service
from .models import DailyBrief, DailyPublication, DailyReview


RELATED = ("review__context__evidence", "assessment", "brief")


def _bound(value):
    if type(value) is not int or not 1 <= value <= 1000:
        raise ValueError("An explicit daily-publication fanout limit between one and 1000 is required")
    return value


def _request(review_id, digest, generation, fanout_limit):
    theses._uuid(review_id, "review_id")
    require_digest(digest, "expected_review_digest")
    if type(generation) is not int or not 0 <= generation <= 2**63 - 1:
        raise ValueError("expected_generation requires a nonnegative database integer")
    _bound(fanout_limit)
    return text_digest(canonical_json({"review_id": review_id, "review_digest": digest,
        "expected_generation": generation, "fanout_limit": fanout_limit}))


def _read_snapshot():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")


def _review(actor_id, review_id):
    row = DailyReview.objects.select_related("context__evidence").filter(pk=review_id, owner_id=actor_id).first()
    if row is None:
        raise theses.ThesisUnavailable("Daily review unavailable")
    return row


def _candidate(row, brief_id, command_id, generation):
    return DailyPublicationCandidate(command_id, str(row.owner_id), str(row.thesis_id), brief_id,
        str(row.pk), str(row.context_id), row.cutoff, row.digest, str(row.context.approval_id),
        row.context.exposure_digest, generation, canonical_json(row.content))


def _wire(row, thesis, at, *, replayed=False):
    review = service._wire(row.review, thesis, at)
    candidate = _candidate(row.review, row.brief_id, str(row.command_id), row.expected_generation)
    assessment = row.assessment
    binding = DailyBrief.objects.get(brief_id=row.brief_id)
    if (assessment.digest != candidate.digest or assessment.payload != candidate.payload
            or assessment.assessment_id != candidate.assessment_id
            or assessment.saved_at != row.published_at
            or row.request_digest != _request(str(row.review_id), row.review.digest,
                row.expected_generation, binding.fanout_limit)):
        raise theses.ThesisConflict("Retained daily publication failed integrity verification")
    if at < max(row.published_at, row.brief.changed_at):
        raise theses.ThesisConflict("Publication observation cannot precede protected history")
    reasons = list(review["current_disposition"]["stale_reasons"])
    pointed = CurrentAssessment.objects.filter(brief_id=row.brief_id, assessment_id=row.assessment_id).exists()
    if assessment.status != "current":
        reasons.extend(assessment.reasons)
    if not pointed:
        reasons.append("newer_publication" if row.brief.generation > row.expected_generation + 1
                       else "publication_not_current")
    version = BriefVersion.objects.filter(brief_id=row.brief_id, assessment_id=row.assessment_id).first()
    if assessment.status == "current" and (version is None or version.generation != row.expected_generation + 1):
        raise theses.ThesisConflict("Daily publication has no exact retained generation")
    intent = NotificationIntent.objects.filter(brief_id=row.brief_id, assessment_id=row.assessment_id).first()
    if intent is not None and at < intent.updated_at:
        raise theses.ThesisConflict("Publication observation precedes notification state")
    return {"publication": {"id": str(row.pk), "command_id": str(row.command_id),
        "review_id": str(row.review_id), "brief_id": row.brief_id,
        "assessment_id": assessment.assessment_id, "review_digest": row.review.digest,
        "expected_generation": row.expected_generation, "published_at": row.published_at.isoformat(),
        "original_decision": {"status": assessment.status, "reasons": assessment.reasons,
            "reassessment_required": assessment.reassessment_required},
        "generation_at_publication": version.generation if version else None},
        "current_disposition": {"status": "superseded" if reasons else "current",
            "reasons": sorted(set(reasons)), "observed_at": at.isoformat()},
        "notification_intent": {"id": intent.pk, "state": intent.state} if intent else None,
        "replayed": replayed, "review": review["review"]}


def preview_publication(actor_id, review_id, fanout_limit, *, clock=timezone.now):
    service.gate()
    service.outermost()
    theses._uuid(review_id, "review_id")
    _bound(fanout_limit)
    with transaction.atomic():
        _read_snapshot()
        theses._owner(actor_id)
        review = _review(actor_id, review_id)
        thesis = theses._record(actor_id, str(review.thesis_id))
        binding = DailyBrief.objects.select_related("brief").filter(thesis=thesis).first()
        if binding and binding.fanout_limit != fanout_limit:
            raise theses.ThesisConflict("Daily stream fanout limit differs from its immutable activation")
        at = as_utc(clock())
        wire = service._wire(review, thesis, at)
        if binding and at < binding.brief.changed_at:
            raise theses.ThesisConflict("Preview observation precedes publication state")
        return {"review_id": str(review.pk), "review_digest": review.digest,
            "thesis_id": str(thesis.pk), "brief_id": binding.pk if binding else "daily:" + str(thesis.pk),
            "expected_generation": binding.brief.generation if binding else 0,
            "fanout_limit": fanout_limit, "current_disposition": wire["current_disposition"]}


def get_publication_command(actor_id, thesis_id, command_id, *, clock=timezone.now):
    service.gate()
    service.outermost()
    theses._uuid(command_id, "command_id")
    with transaction.atomic():
        _read_snapshot()
        theses._owner(actor_id)
        thesis = theses._record(actor_id, thesis_id)
        row = DailyPublication.objects.select_related(*RELATED).filter(
            owner_id=actor_id, thesis=thesis, command_id=command_id).first()
        if row is None:
            raise theses.ThesisUnavailable("Daily publication command unavailable")
        return _wire(row, thesis, as_utc(clock()), replayed=True)


def inspect_publication(actor_id, publication_id, *, clock=timezone.now):
    service.gate()
    service.outermost()
    theses._uuid(publication_id, "publication_id")
    with transaction.atomic():
        _read_snapshot()
        theses._owner(actor_id)
        row = DailyPublication.objects.select_related(*RELATED).filter(pk=publication_id, owner_id=actor_id).first()
        if row is None:
            raise theses.ThesisUnavailable("Daily publication unavailable")
        thesis = theses._record(actor_id, str(row.thesis_id))
        return _wire(row, thesis, as_utc(clock()))


def get_current_brief(actor_id, thesis_id, *, clock=timezone.now):
    service.gate()
    service.outermost()
    with transaction.atomic():
        _read_snapshot()
        theses._owner(actor_id)
        thesis = theses._record(actor_id, thesis_id)
        binding = DailyBrief.objects.select_related("brief").filter(thesis=thesis).first()
        row = None
        if binding:
            pointer = CurrentAssessment.objects.filter(brief=binding.brief).first()
            if pointer:
                row = DailyPublication.objects.select_related(*RELATED).filter(
                    owner_id=actor_id, brief=binding.brief, assessment_id=pointer.assessment_id).first()
                if row is None:
                    raise theses.ThesisConflict("Daily current pointer has no scoped publication")
        at = as_utc(clock())
        if at < thesis.changed_at or binding and at < binding.brief.changed_at:
            raise theses.ThesisConflict("Current observation precedes governing state")
        current = _wire(row, thesis, at) if row else None
        if current and current["current_disposition"]["status"] != "current":
            raise theses.ThesisConflict("Daily current pointer disagrees with governing state")
        # Adjacent interpretation has no publication authority. Read within this
        # same snapshot and exact published review, never fall back to history.
        current_synthesis = None
        if row:
            from . import synthesis
            from .synthesis_models import DailySynthesisAttempt
            attempt = DailySynthesisAttempt.objects.select_related("review__context__evidence").filter(
                owner_id=actor_id, review_id=row.review_id, result__status="synthesised"
            ).order_by("-created_at", "id").first()
            if attempt:
                candidate = synthesis._response(attempt, thesis, at)
                if candidate["current_disposition"]["status"] == "current":
                    current_synthesis = candidate
        return {"thesis_id": str(thesis.pk), "brief_id": binding.pk if binding else None,
            "generation": binding.brief.generation if binding else 0,
            "current_publication": current, "current_synthesis": current_synthesis,
            "observed_at": at.isoformat()}


def _retry(row, digest, thesis, at):
    if row.request_digest != digest:
        raise theses.ThesisConflict("Publication command belongs to different inputs")
    return _wire(row, thesis, at, replayed=True)


def publish_review(actor_id, review_id, command_id, expected_review_digest,
                   expected_generation, fanout_limit, *, clock=timezone.now):
    service.gate()
    service.outermost()
    theses._uuid(command_id, "command_id")
    request_digest = _request(review_id, expected_review_digest, expected_generation, fanout_limit)
    # Read saved decisions before new admission. Revoked source permissions cannot
    # prevent inspection or turn an exact retry into another publication.
    with transaction.atomic():
        _read_snapshot()
        theses._owner(actor_id)
        review = _review(actor_id, review_id)
        thesis = theses._record(actor_id, str(review.thesis_id))
        old = DailyPublication.objects.select_related(*RELATED).filter(owner_id=actor_id, command_id=command_id).first()
        if old:
            return _retry(old, request_digest, thesis, as_utc(clock()))
        source_ids = service._source_ids([item["source_id"] for item in review.context.evidence.source_manifest])
    with transaction.atomic():
        service._lock_sources(source_ids)
        thesis = lock_owner_thesis(actor_id, str(review.thesis_id), "default")
        briefs = lock_thesis_briefs(thesis)
        old = DailyPublication.objects.select_related(*RELATED).filter(owner_id=actor_id, command_id=command_id).first()
        if old:
            return _retry(old, request_digest, thesis, _at(clock, thesis, briefs))
        review = _review(actor_id, review_id)
        if DailyPublication.objects.filter(review=review).exists():
            raise theses.ThesisConflict("This retained review already has an immutable publication decision")
        if review.digest != expected_review_digest:
            raise theses.ThesisConflict("Review digest changed; inspect the exact retained review")
        binding = DailyBrief.objects.select_related("brief").filter(thesis=thesis).first()
        if binding and binding.fanout_limit != fanout_limit:
            raise theses.ThesisConflict("Daily stream fanout limit differs from its immutable activation")
        at = _at(clock, thesis, briefs)
        disposition = service._wire(review, thesis, at)["current_disposition"]
        if binding is None:
            if BriefStateRecord.objects.filter(pk="daily:" + str(thesis.pk)).exists():
                raise theses.ThesisConflict("Daily stream identity is already used by another publication contract")
            brief = BriefStateRecord.objects.create(brief_id="daily:" + str(thesis.pk), owner_id=actor_id, changed_at=at)
            binding = DailyBrief.objects.create(brief=brief, owner_id=actor_id, thesis=thesis,
                fanout_limit=fanout_limit, created_at=at)
        brief = binding.brief
        latest = DailyReview.objects.filter(thesis=thesis).order_by("-cutoff").first()
        latest_published = DailyPublication.objects.filter(brief=brief, assessment__status="current").order_by("-review__cutoff").first()
        candidate = _candidate(review, brief.pk, command_id, expected_generation)
        state = DailyPublicationState(actor_id, str(thesis.pk), brief.generation, brief.changed_at,
            str(latest.pk) if latest else None, latest.cutoff if latest else None,
            latest_published.review.cutoff if latest_published else None,
            tuple(disposition["stale_reasons"]))
        decision = decide_daily_publication(candidate, state, at)
        if decision.status == "current":
            invalidation.check_publication_capacity(source_ids=source_ids, brief_id=brief.pk,
                                                   fanout_limit=fanout_limit)
        assessment = AssessmentRecord.objects.create(brief=brief, assessment_id=candidate.assessment_id,
            digest=candidate.digest, payload=candidate.payload, status=decision.status,
            reasons=list(decision.reasons), reassessment_required=decision.reassessment_required,
            observed_dependencies=[{"context_id": str(review.context_id), "review_digest": review.digest,
                "approval_id": str(review.context.approval_id), "exposure_digest": review.context.exposure_digest,
                "source_manifest": review.context.evidence.source_manifest}], saved_at=at)
        row = DailyPublication.objects.create(command_id=command_id, owner_id=actor_id, thesis=thesis,
            brief=brief, review=review, assessment=assessment, request_digest=request_digest,
            expected_generation=expected_generation, published_at=at)
        canceled = []
        if decision.status == "current":
            brief.generation += 1
            brief.changed_at = at
            brief.save(update_fields=("generation", "changed_at"))
            CurrentAssessment.objects.update_or_create(brief=brief, defaults={"assessment": assessment})
            BriefVersion.objects.create(brief=brief, generation=brief.generation, assessment=assessment, saved_at=at)
            canceled = list(NotificationIntent.objects.filter(brief=brief, state="pending").values_list("pk", flat=True))
            NotificationIntent.objects.filter(brief=brief, state="pending").update(state="canceled", updated_at=at)
            ReassessmentWork.objects.filter(brief=brief, state="pending").update(state="superseded", completed_at=at)
            NotificationIntent.objects.create(intent_id=candidate.intent_id, brief=brief, assessment=assessment,
                created_at=at, updated_at=at)
        elif decision.reassessment_required:
            ReassessmentWork.objects.get_or_create(brief=brief, context_digest=candidate.digest,
                defaults={"reason": ", ".join(decision.reasons), "created_at": at})
        AuditTransition.objects.create(brief=brief, kind="daily_publication", happened_at=at,
            detail={"publication_id": str(row.pk), "review_id": str(review.pk),
                "command_id": command_id, "status": decision.status, "reasons": list(decision.reasons),
                "generation": brief.generation, "canceled_intents": canceled})
        return _wire(row, thesis, at)
