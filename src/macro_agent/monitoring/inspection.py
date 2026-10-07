"""Coherent read-only capture/work evidence, with visible report bounds."""

from django.db import connection, transaction
from django.db.models import Count
from django.utils import timezone

from .gates import require_local_proof
from .models import (CaptureAttempt, CaptureOutcome, DurableObservation,
                     ScreeningResult, ScreeningWork, SourceRevision, SourceState)


def instant(value):
    return value.isoformat() if value is not None else None


def inspect_source(source_id):
    require_local_proof()
    if connection.in_atomic_block:
        raise ValueError("Inspection must own its read-only snapshot")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        now = timezone.now()
        source = SourceState.objects.get(pk=source_id)
        latest = CaptureAttempt.objects.filter(source=source).order_by("-sequence").first()
        latest_outcome = CaptureOutcome.objects.filter(attempt=latest).first() if latest else None
        health_state = (latest_outcome.status if latest_outcome else
            ("outcome_unknown" if latest and now >= latest.deadline_at else "fetching") if latest else "never_checked")
        works = ScreeningWork.objects.filter(revision__report__source=source)
        by_state = dict(works.values("state").annotate(count=Count("state")).values_list("state", "count"))
        revisions_qs = SourceRevision.objects.filter(report__source=source)
        revisions = list(revisions_qs.select_related("report").order_by("system_received_at", "id")[:100])
        witnesses = {row.revision_id: row for row in DurableObservation.objects.filter(revision__in=revisions)}
        revision_rows = [{"id": str(row.id), "native_id": row.report.native_id,
            "observation_revision": row.observation_revision, "digest": row.digest,
            "payload": row.payload, "is_current_observation": row.report.current_revision_id == row.id,
            "source_order": "unverified", "source_claimed_published_at": instant(row.source_claimed_published_at),
            "public_available_at": None, "system_received_at": instant(row.system_received_at),
            "durable_observed_by_at": instant(witnesses[row.id].observed_by_at) if row.id in witnesses else None,
            "availability_precision": "conservative_postcommit_upper_bound" if row.id in witnesses else "not_yet_observed",
            "capture_attempt_id": str(row.capture_id)} for row in revisions]
        work_rows = []
        for work in works.filter(revision__in=revisions).prefetch_related("attempts").order_by("revision_id"):
            attempts = list(work.attempts.order_by("sequence")[:100])
            results = {row.attempt_id: row for row in ScreeningResult.objects.filter(attempt__in=attempts)}
            evidence = []
            for attempt in attempts:
                result = results.get(attempt.token)
                disposition = "completed" if result else (
                    "superseded" if work.state == "superseded" else
                    "lease_expired" if now >= attempt.deadline_at else "in_flight")
                evidence.append({"token": str(attempt.token), "sequence": attempt.sequence,
                    "admitted_at": instant(attempt.admitted_at), "deadline_at": instant(attempt.deadline_at),
                    "rule_version": attempt.rule_version, "attempt_disposition": disposition,
                    "original_decision": result.decision if result else None,
                    "finished_at": instant(result.finished_at) if result else None})
            work_rows.append({"revision_id": str(work.revision_id), "current_disposition": work.state,
                "lease_until": instant(work.lease_until), "attempt_count": work.attempt_count,
                "attempts_truncated": work.attempt_count > len(attempts), "attempts": evidence})
        captures = []
        for attempt in CaptureAttempt.objects.filter(source=source).order_by("sequence")[:100]:
            outcome = CaptureOutcome.objects.filter(attempt=attempt).first()
            captures.append({"id": str(attempt.id), "sequence": attempt.sequence,
                "contract_digest": attempt.contract_digest, "admitted_at": instant(attempt.admitted_at),
                "deadline_at": instant(attempt.deadline_at),
                "status": outcome.status if outcome else ("outcome_unknown" if now >= attempt.deadline_at else "fetching"),
                "code": outcome.code if outcome else None,
                "item_count": outcome.item_count if outcome else None,
                "new_revision_count": outcome.new_revision_count if outcome else None,
                "transport_digest": outcome.transport_digest if outcome else None,
                "received_at": instant(outcome.received_at) if outcome else None,
                "outcome_precommit_sampled_at": instant(outcome.finished_at) if outcome else None,
                "coverage": outcome.coverage if outcome else None})
        return {"source": {"id": source.id, "label": source.contract["label"], "kind": source.contract["kind"],
                "contract_digest": source.contract_digest, "contract": source.contract},
            "health": {"last_attempt_state": health_state,
                "last_successful_capture_at": instant(source.last_successful_capture_at),
                "latest_failure_code": latest_outcome.code if latest_outcome and latest_outcome.status != "captured" else None,
                "coverage": "bounded_snapshot", "absence_is_deletion": False,
                "continuity": "unproven", "freshness_sla": None},
            "counts": {"reports": source.sourcereport_set.count(), "revisions": revisions_qs.count(),
                **{key: by_state.get(key, 0) for key in ("pending", "running", "completed", "superseded")}},
            "revisions": revision_rows, "work": work_rows, "captures": captures,
            "revisions_truncated": revisions_qs.count() > len(revisions),
            "captures_truncated": source.capture_sequence > len(captures),
            "limitations": ["no_personalized_analysis", "no_notifications", "no_full_operational_replay",
                "source_order_unverified", "no_model_calls", "no_production_daemon"]}
