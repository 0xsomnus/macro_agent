"""Bounded source-only recovery with committed shared transport reservations.

No lock spans transport. The provider root precedes source, owner and thesis
protection, and every admitted GET has its own exact immutable capture binding.
Paid nodes are outside this module and retain their one-shot semantics.
"""

from datetime import datetime, timedelta

from django.db import transaction

from macro_agent.domain.time import as_utc
from macro_agent.monitoring import capture, gdelt_research
from macro_agent.monitoring.models import CaptureAttempt, CaptureOutcome, SourceRevision, SourceState
from macro_agent.monitoring.research_policy import RECOVERY_POLICY, RETRY_REASONS, cooldown_until, retry_due_at
from macro_agent.theses import service as theses

from .investigation_models import (ResearchDiscoveryAttempt, ResearchDiscoveryReceipt,
    ResearchDiscoveryResult, ResearchSourceState)


PROVIDER = "gdelt"


def deadline(run):
    return run.created_at + timedelta(seconds=run.execution_policy["run_deadline_seconds"])


def _latest(run, index):
    return run.discoveries.filter(question_index=index).order_by("-attempt_number").first()


def _query_source_ids(run):
    return ["research-gdelt-" + run.id.hex + "-" + str(index)
        for index in range(run.bounds["max_questions"])]


def _permission_withdrawn(source_ids):
    from .permissions import permission_allows
    return any(permission_allows(source_id) is False for source_id in source_ids)


def _provider_due(at):
    row = ResearchSourceState.objects.filter(pk=PROVIDER).select_related("active_capture").first()
    if row is None:
        return at
    return max(at, row.next_request_at,
        row.active_capture.deadline_at + timedelta(seconds=RECOVERY_POLICY["base_backoff_seconds"])
        if row.active_capture_id else at)


def _node_state(run, attempt, at):
    if attempt is None:
        return "discovering", at, "not_admitted"
    result = ResearchDiscoveryResult.objects.filter(attempt=attempt).first()
    if result and result.status == "captured":
        return "captured", None, "snapshot_captured"
    if result:
        if result.metadata.get("retry_reason") not in {"timeout", "unavailable", "rate_limited"}:
            return "discovery_failed", None, result.stop_reason
        if attempt.attempt_number >= run.execution_policy["max_attempts_per_question"]:
            return "source_exhausted", None, "source_attempt_limit_reached"
        due = result.metadata.get("retry_due_at")
        if due is None:
            return "source_deadline", None, "source_cooldown_exceeds_run_deadline"
        return "discovering", as_utc(datetime.fromisoformat(due)), result.stop_reason
    admission = attempt.capture
    # Adopt committed receipts first, even after expiry, without a second GET.
    outcome = CaptureOutcome.objects.filter(attempt=admission).first()
    receipt = ResearchDiscoveryReceipt.objects.filter(attempt=attempt).first()
    if outcome and outcome.status == "captured" or receipt:
        return "discovering", at, "retained_capture_pending_adoption"
    if at < admission.deadline_at:
        return "waiting_source", admission.deadline_at, "source_request_in_progress"
    # Continuation records the original uncertainty before deciding whether a
    # source-only repeat fits its bounds. Reads themselves remain inert.
    return "discovering", at, "unrecorded_source_response"


def source_progress(run, plan, at):
    finish = deadline(run)
    value = {"status": "discovering", "deadline_at": finish.isoformat(),
        "next_attempt_at": None, "stop_reason": None}
    existing = SourceState.objects.filter(pk__in=_query_source_ids(run)).values_list("pk", flat=True)
    if _permission_withdrawn(existing):
        value.update(status="discovery_failed", stop_reason="source_permission_withdrawn")
        return value
    if plan is None or plan["status"] != "planned":
        if plan is None:
            if at >= finish:
                value.update(status="source_deadline", stop_reason="source_run_deadline_reached")
            elif _provider_due(at) >= finish - timedelta(
                    seconds=run.execution_policy["transport_timeout_seconds"] + 5):
                value.update(status="source_deadline", stop_reason="source_cooldown_exceeds_run_deadline")
        return value
    captured = []
    for index in range(len(plan["document"]["questions"])):
        attempt = _latest(run, index)
        status, due, reason = _node_state(run, attempt, at)
        if status == "captured":
            captured.append(ResearchDiscoveryResult.objects.get(attempt=attempt))
            continue
        if status == "discovering" and reason == "retained_capture_pending_adoption":
            value.update(status=status, next_attempt_at=at.isoformat(), stop_reason=reason)
            return value
        if at >= finish:
            value.update(status="source_deadline", stop_reason="source_run_deadline_reached")
            return value
        if status in {"source_exhausted", "source_deadline", "discovery_failed"}:
            value.update(status=status, stop_reason=reason)
            return value
        due = max(due, _provider_due(at))
        # A request must leave its entire transport and commit margin before
        # the source budget ends, rather than being admitted at the final tick.
        if due >= finish - timedelta(seconds=run.execution_policy["transport_timeout_seconds"] + 5):
            value.update(status="source_deadline", stop_reason="source_cooldown_exceeds_run_deadline")
            return value
        value.update(status="waiting_source" if due > at else "discovering",
            next_attempt_at=due.isoformat(), stop_reason=reason)
        return value
    value.update(status="ready_to_compile" if any(row.revision_ids for row in captured) else "no_evidence")
    return value


def _root(at):
    ResearchSourceState.objects.get_or_create(pk=PROVIDER, defaults={"next_request_at": at})
    return ResearchSourceState.objects.select_for_update().get(pk=PROVIDER)


def record_result(attempt, admission, status, metadata, code, *, clock):
    with transaction.atomic():
        root = _root(attempt.admitted_at)
        sources = list(SourceState.objects.select_for_update()
            .filter(pk__in=_query_source_ids(attempt.run)).order_by("pk"))
        theses._owner(str(attempt.run.owner_id), lock=True)
        thesis = theses._record(str(attempt.run.owner_id), str(attempt.run.thesis_id), lock=True)
        at = theses._instant(clock, thesis)
        if attempt.capture_id != admission.pk or admission.source_id != attempt.source_id:
            raise theses.ThesisConflict("Research response differs from its exact source admission")
        if status == "captured" and _permission_withdrawn(row.pk for row in sources):
            raise theses.ThesisConflict("A required research source permission was withdrawn")
        saved = ResearchDiscoveryResult.objects.filter(attempt=attempt).first()
        if saved:
            return saved
        if status == "captured":
            ids = list(SourceRevision.objects.filter(capturemembership__capture=admission)
                .order_by("pk").values_list("pk", flat=True))
            next_due = max(at, admission.admitted_at + timedelta(seconds=RECOVERY_POLICY["minimum_spacing_seconds"]))
        else:
            reason = RETRY_REASONS.get(code)
            retry_after = metadata.get("retry_after_seconds")
            due = retry_due_at(finished_at=at, attempt_number=attempt.attempt_number,
                deadline_at=deadline(attempt.run), retry_after_seconds=retry_after) if reason else None
            metadata = {"retry_after_seconds": retry_after, "retry_reason": reason,
                "retry_due_at": due.isoformat() if due else None}
            ids = []
            next_due = cooldown_until(finished_at=at, attempt_number=attempt.attempt_number,
                retry_after_seconds=retry_after) if reason else at
        result = ResearchDiscoveryResult.objects.create(attempt=attempt, capture=admission,
            status=status, revision_ids=[str(item) for item in ids], metadata=metadata,
            stop_reason=code, finished_at=at)
        changed = next_due > root.next_request_at or root.active_capture_id == admission.pk
        root.next_request_at = max(root.next_request_at, next_due)
        if root.active_capture_id == admission.pk:
            root.active_capture = None
        if changed:
            root.generation += 1
            root.save(update_fields=("active_capture", "next_request_at", "generation"))
        return result


def _admit(run, index, question, *, clock, research_job_token=None):
    from .investigation import _draft_current
    source_id = "research-gdelt-" + run.id.hex + "-" + str(index)
    contract = gdelt_research.contract(source_id, question["query"],
        policy_version=gdelt_research.RECOVERY_POLICY_VERSION)
    # The initial timestamp only seeds a new root; all admission decisions use
    # the trusted clock after the complete protection set has been acquired.
    with transaction.atomic():
        root = _root(run.created_at)
        SourceState.objects.get_or_create(pk=source_id, defaults={"contract": contract,
            "contract_digest": capture.canonical_digest(contract)})
        sources = {row.pk: row for row in SourceState.objects.select_for_update()
            .filter(pk__in=_query_source_ids(run)).order_by("pk")}
        source = sources[source_id]
        theses._owner(str(run.owner_id), lock=True)
        thesis = theses._record(str(run.owner_id), str(run.thesis_id), lock=True)
        if research_job_token is not None:
            from .research_jobs import protect_execution
            at = protect_execution(str(run.owner_id), str(run.pk), research_job_token,
                clock=clock, required_seconds=RECOVERY_POLICY["transport_timeout_seconds"] + 5)
        else:
            at = theses._instant(clock, thesis)
        if _permission_withdrawn(sources):
            raise theses.ThesisConflict("A required research source permission was withdrawn")
        if not _draft_current(run, thesis):
            return None
        if source.contract != contract or source.contract_digest != capture.canonical_digest(contract):
            raise theses.ThesisConflict("Research source differs from its pinned recovery contract")
        previous = _latest(run, index)
        status, due, _ = _node_state(run, previous, at)
        if status != "discovering" or due > at:
            return None
        if root.next_request_at > at:
            return None
        if root.active_capture_id:
            active = CaptureAttempt.objects.get(pk=root.active_capture_id)
            if active.deadline_at + timedelta(seconds=RECOVERY_POLICY["base_backoff_seconds"]) > at:
                return None
        if at + timedelta(seconds=RECOVERY_POLICY["transport_timeout_seconds"] + 5) >= deadline(run):
            return None
        number = previous.attempt_number + 1 if previous else 1
        if number > RECOVERY_POLICY["max_attempts_per_question"]:
            return None
        if source.active_capture:
            active = CaptureAttempt.objects.get(pk=source.active_capture)
            if active.deadline_at > at:
                return None
            CaptureOutcome.objects.get_or_create(attempt=active, defaults={
                "status": "outcome_unknown", "code": "capture_lease_expired", "finished_at": at})
        admission = CaptureAttempt.objects.create(source=source, sequence=source.capture_sequence + 1,
            admitted_at=at, deadline_at=at + timedelta(seconds=RECOVERY_POLICY["transport_timeout_seconds"] + 5),
            contract_digest=source.contract_digest)
        attempt = ResearchDiscoveryAttempt.objects.create(run=run, question_index=index,
            attempt_number=number, question=question, source_id=source_id, contract=contract,
            admitted_at=at, capture=admission)
        if research_job_token is not None:
            from .research_jobs import record_admission
            record_admission(research_job_token, at, source_attempt=attempt)
        source.capture_sequence, source.active_capture = admission.sequence, admission.pk
        source.save(update_fields=("capture_sequence", "active_capture"))
        root.active_capture = admission
        root.next_request_at = max(root.next_request_at,
            at + timedelta(seconds=RECOVERY_POLICY["minimum_spacing_seconds"]))
        root.generation += 1
        root.save(update_fields=("active_capture", "next_request_at", "generation"))
        admission._transport_owned = True
        return attempt, admission


def discover(run, index, question, *, discovery, clock, research_job_token=None):
    try:
        return _discover(run, index, question, discovery=discovery, clock=clock,
            research_job_token=research_job_token)
    except PermissionError:
        raise theses.ThesisConflict("A required research source permission was withdrawn") from None


def _discover(run, index, question, *, discovery, clock, research_job_token=None):
    from .investigation import _finish_discovery
    previous = _latest(run, index)
    if previous and not ResearchDiscoveryResult.objects.filter(attempt=previous).exists():
        if previous.question != question or previous.capture_id is None:
            raise theses.ThesisConflict("Research source differs from its retained plan and admission")
        admission = previous.capture
        receipt = ResearchDiscoveryReceipt.objects.filter(attempt=previous).first()
        outcome = CaptureOutcome.objects.filter(attempt=admission).first()
        if outcome:
            if outcome.status == "captured":
                capture.observe_capture(admission.pk, clock=clock)
            record_result(previous, admission, outcome.status if outcome.status == "captured" else
                "outcome_unknown" if outcome.status == "outcome_unknown" else "failed",
                receipt.metadata if receipt else {}, outcome.code, clock=clock)
        else:
            _finish_discovery(previous, admission, receipt, discovery=discovery, clock=clock,
                research_job_token=research_job_token)
        # Recovery first persists the original disposition. Do not immediately
        # turn an expired unknown exchange into another request in this turn.
        return
    admitted = _admit(run, index, question, clock=clock, research_job_token=research_job_token)
    if admitted is None:
        return
    attempt, admission = admitted
    return _finish_discovery(attempt, admission, None, discovery=discovery, clock=clock,
        research_job_token=research_job_token)
