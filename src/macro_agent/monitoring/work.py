"""Bounded deterministic recovery work with fenced leases and no paid effects."""

from datetime import timedelta
from uuid import uuid4

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from macro_agent.domain.routing import Screening, Severity, route_event
from macro_agent.domain.time import as_utc

from .gates import require_local_proof
from .models import (DurableObservation, ScreeningAttempt, ScreeningResult,
                     ScreeningWork, SourceReport, SourceState)


class WorkFenced(ValueError):
    pass


def unresolved_decision():
    decision = route_event(Screening(resolved=False, credible=False, urgent=False,
        potential_severity=Severity.LOW, thesis_impact=False, trade_impact=False,
        plausible_transmission=False, broad_disruption=False, novel=False,
        classifier_available=False))
    return {"route": decision.route.value, "state": decision.state.value,
            "reasons": list(decision.reasons), "early_notice": False,
            "personalized": False, "model_calls": 0,
            "limitation": "No classifier or portfolio assessment is implemented"}


def claim_work(*, lease_seconds=30, clock=timezone.now):
    require_local_proof()
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValueError("Lease admission must commit before processing")
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
        raise ValueError("Lease seconds must be between 1 and 300")

    # This finite queue snapshot is only a selection hint. Recheck eligibility
    # using the trusted clock after source->work protection. Include running
    # leases so recovery also works with an injected clock, without sampling it
    # before protection. Receipt/identity ordering prevents a busy first source
    # with newer arrivals from starving older work belonging to another source.
    candidates = ScreeningWork.objects.filter(
        Q(state="pending") | Q(state="running")
    ).order_by("revision__system_received_at", "revision_id").values_list(
        "pk", "revision__report__source_id")
    unavailable_sources = set()
    # Chunking bounds fetch memory, not eligibility. There is no first-N cutoff
    # that could hide runnable work behind locked rows or live leases. A claim
    # can scan the current queue; work_once separately bounds processed records.
    for work_id, source_id in candidates.iterator(chunk_size=100):
        if source_id in unavailable_sources:
            continue
        with transaction.atomic():
            source = SourceState.objects.select_for_update(skip_locked=True).filter(
                pk=source_id).first()
            if source is None:
                unavailable_sources.add(source_id)
                continue
            work = ScreeningWork.objects.select_for_update(skip_locked=True).filter(
                pk=work_id).first()
            if work is None:
                continue
            now = as_utc(clock())
            if not (work.state == "pending" or (
                    work.state == "running" and work.lease_until <= now)):
                continue
            revision = work.revision
            if SourceReport.objects.get(pk=revision.report_id).current_revision_id != revision.id:
                raise ValueError("Work head is inconsistent")
            DurableObservation.objects.get_or_create(revision=revision,
                defaults={"observed_by_at": now})
            attempt = ScreeningAttempt.objects.create(token=uuid4(), work=work,
                sequence=work.attempt_count + 1, admitted_at=now,
                deadline_at=now + timedelta(seconds=lease_seconds))
            work.state = "running"
            work.active_token = attempt.token
            work.lease_until = attempt.deadline_at
            work.attempt_count = attempt.sequence
            work.save(update_fields=("state", "active_token", "lease_until", "attempt_count"))
        return attempt
    return None


def complete_work(token, *, clock=timezone.now):
    require_local_proof()
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValueError("Completion must own its transaction")
    attempt = ScreeningAttempt.objects.select_related("work__revision__report").get(pk=token)
    decision = unresolved_decision()  # Independent of models, no network side effects.
    with transaction.atomic():
        SourceState.objects.select_for_update().get(pk=attempt.work.revision.report.source_id)
        work = ScreeningWork.objects.select_for_update().get(pk=attempt.work_id)
        now = as_utc(clock())
        head = SourceReport.objects.get(pk=attempt.work.revision.report_id).current_revision_id
        if (work.state != "running" or work.active_token != token
                or now >= attempt.deadline_at or head != work.revision_id):
            raise WorkFenced("Work lease expired, was replaced, or input was superseded")
        result = ScreeningResult.objects.create(attempt=attempt, finished_at=now, decision=decision)
        work.state = "completed"
        work.active_token = None
        work.lease_until = None
        work.save(update_fields=("state", "active_token", "lease_until"))
    return result


def work_once(*, limit=10, lease_seconds=30):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Work limit must be between 1 and 100")
    results = []
    for _ in range(limit):
        attempt = claim_work(lease_seconds=lease_seconds)
        if attempt is None:
            break
        try:
            result = complete_work(attempt.token)
        except WorkFenced:
            results.append({"token": str(attempt.token), "disposition": "fenced"})
        else:
            results.append({"token": str(attempt.token), "disposition": "completed", "decision": result.decision})
    return results
