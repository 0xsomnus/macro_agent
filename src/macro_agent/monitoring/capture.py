"""Admit one bounded fetch, then commit receipts and work together.

No network or model call holds database protection. Expired admissions are
fenced; unseen payloads advance observed heads, not source-authoritative facts.
"""

from datetime import timedelta
from hashlib import sha256
import json

from django.db import connection, transaction
from django.utils import timezone

from macro_agent.domain.time import as_utc

from .gates import require_local_proof
from .models import (CaptureAttempt, CaptureMembership, CaptureOutcome,
                     DurableObservation, ScreeningWork, SourceReport,
                     SourceRevision, SourceState)


class CaptureBusy(ValueError):
    pass


class CaptureFenced(ValueError):
    pass


def canonical_digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def admit_capture(source_id, contract, *, clock=timezone.now):
    require_local_proof(synthetic=contract.get("kind") == "fictional_fixture")
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValueError("Capture admission must commit before transport")
    digest = canonical_digest(contract)
    with transaction.atomic():
        SourceState.objects.get_or_create(pk=source_id, defaults={
            "contract": contract, "contract_digest": digest})
        source = SourceState.objects.select_for_update().get(pk=source_id)
        from macro_agent.desk.permissions import permission_allows
        if permission_allows(source.pk) is False:
            raise PermissionError("Source processing permission was withdrawn")
        now = as_utc(clock())
        if source.contract_digest != digest:
            raise ValueError("Source contract changed; review under a new source identity")
        if source.active_capture:
            active = CaptureAttempt.objects.get(pk=source.active_capture)
            if active.deadline_at > now:
                raise CaptureBusy("Source already has an active bounded capture")
            CaptureOutcome.objects.get_or_create(attempt=active, defaults={
                "status": "outcome_unknown", "code": "capture_lease_expired", "finished_at": now})
        attempt = CaptureAttempt.objects.create(source=source,
            sequence=source.capture_sequence + 1, admitted_at=now,
            deadline_at=now + timedelta(seconds=30), contract_digest=digest)
        source.capture_sequence = attempt.sequence
        source.active_capture = attempt.id
        source.save(update_fields=("capture_sequence", "active_capture"))
    return attempt


def _protected_attempt(attempt_id, clock):
    attempt = CaptureAttempt.objects.get(pk=attempt_id)
    source = SourceState.objects.select_for_update().get(pk=attempt.source_id)
    from macro_agent.desk.permissions import permission_allows
    if permission_allows(source.pk) is False:
        raise PermissionError("Source processing permission was withdrawn")
    now = as_utc(clock())
    if source.active_capture != attempt.id or now >= attempt.deadline_at:
        raise CaptureFenced("Capture admission expired or was replaced")
    return attempt, source, now


def fail_capture(attempt_id, code, *, clock=timezone.now):
    require_local_proof()
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValueError("Failure disposition must own its transaction")
    with transaction.atomic():
        attempt, source, now = _protected_attempt(attempt_id, clock)
        result = CaptureOutcome.objects.create(attempt=attempt, status="failed", code=code, finished_at=now)
        source.active_capture = None
        source.save(update_fields=("active_capture",))
    return result


def commit_batch(attempt_id, batch, *, clock=timezone.now):
    # SourceBatch validates bounds and types at the adapter boundary; reject
    # non-contract objects even if an internal caller supplies their fields.
    from .sources import SourceBatch
    require_local_proof()
    if not isinstance(batch, SourceBatch) or batch.truncated:
        raise ValueError("A complete bounded SourceBatch is required")
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValueError("Receipt commit must own its transaction")
    with transaction.atomic():
        attempt, source, now = _protected_attempt(attempt_id, clock)
        require_local_proof(synthetic=source.contract["kind"] == "fictional_fixture")
        if batch.received_at < attempt.admitted_at or batch.received_at > now:
            raise ValueError("Actual receipt must fall inside the capture admission")
        new_count = 0
        for item in batch.items:
            report, _ = SourceReport.objects.get_or_create(source=source, native_id=item.native_id)
            revision = SourceRevision.objects.filter(report=report, digest=item.digest).first()
            if revision is None:
                revision = SourceRevision.objects.create(report=report,
                    observation_revision=report.revision_count + 1, digest=item.digest,
                    payload=item.payload(), source_claimed_published_at=item.published_at,
                    system_received_at=batch.received_at, capture=attempt)
                # Supersession and new work share the receipt transaction.
                ScreeningWork.objects.filter(revision__report=report).exclude(
                    state="superseded").update(state="superseded", active_token=None, lease_until=None)
                ScreeningWork.objects.create(revision=revision)
                report.revision_count = revision.observation_revision
                report.current_revision = revision
                report.save(update_fields=("revision_count", "current_revision"))
                new_count += 1
            # A repeated older payload is retained as a receipt, never promoted.
            CaptureMembership.objects.create(capture=attempt, revision=revision)
        result = CaptureOutcome.objects.create(attempt=attempt, status="captured", code="snapshot_captured",
            finished_at=now, received_at=batch.received_at, transport_digest=batch.transport_digest,
            item_count=len(batch.items), new_revision_count=new_count, coverage=batch.coverage)
        source.active_capture = None
        source.last_successful_capture_at = now
        source.save(update_fields=("active_capture", "last_successful_capture_at"))
    return result


def observe_capture(attempt_id, *, clock=timezone.now):
    """Recoverable postcommit witness; it is an upper bound, not exact known_at."""
    require_local_proof()
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValueError("Observation requires already committed input")
    attempt = CaptureAttempt.objects.get(pk=attempt_id)
    with transaction.atomic():
        SourceState.objects.select_for_update().get(pk=attempt.source_id)
        revisions = SourceRevision.objects.filter(capturemembership__capture=attempt)
        now = as_utc(clock())
        for revision in revisions:
            if now < revision.system_received_at:
                raise ValueError("Observation clock predates receipt")
            DurableObservation.objects.get_or_create(revision=revision,
                defaults={"observed_by_at": now})


def observe_retained(source_ids, limit, *, clock=timezone.now):
    """Reconcile missing receipt witnesses after restart in explicit batches.

    This observes already committed revisions, including ones no longer in a
    feed snapshot. A late witness cannot establish availability before it was
    actually observed. Batching here does not truncate a daily evidence set.
    """
    require_local_proof()
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValueError("Observation requires already committed input")
    if type(limit) is not int or not 1 <= limit <= 2**31 - 1:
        raise ValueError("Receipt observation requires an explicit positive bound")
    if type(source_ids) not in (list, tuple) or not source_ids or len(set(source_ids)) != len(source_ids):
        raise ValueError("Receipt observation requires unique source identities")
    with transaction.atomic():
        sources = list(SourceState.objects.select_for_update().filter(pk__in=source_ids).order_by("pk"))
        if len(sources) != len(source_ids):
            raise ValueError("Selected source is unavailable")
        rows = list(SourceRevision.objects.filter(report__source_id__in=source_ids,
            durableobservation__isnull=True).order_by("system_received_at", "pk")[:limit + 1])
        now = as_utc(clock())
        for revision in rows[:limit]:
            if now < revision.system_received_at:
                raise ValueError("Observation clock predates receipt")
            DurableObservation.objects.create(revision=revision, observed_by_at=now)
    return {"observed_revision_ids": [str(row.pk) for row in rows[:limit]],
            "observed_by_at": now.isoformat(), "more_pending": len(rows) > limit,
            "batch_limit": limit, "exact_commit_time": False}


def capture(source_id, contract, loader, *, clock=timezone.now, after_commit=None):
    from .sources import SourceError
    attempt = admit_capture(source_id, contract, clock=clock)
    try:
        batch = loader()
    except SourceError as error:
        return fail_capture(attempt.id, error.code, clock=clock)
    result = commit_batch(attempt.id, batch, clock=clock)
    if after_commit is not None:
        after_commit()  # Fault injection proves receipts/work survive this crash.
    observe_capture(attempt.id, clock=clock)
    return result
