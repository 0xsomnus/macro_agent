"""Owner-authorized, durable continuation of an already planned investigation.

Scheduling is separate from research truth and never enrolls monitoring. Every
new remote admission checks the exact current lease inside its governing locks.
"""

from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from macro_agent.domain.time import as_utc
from macro_agent.theses import compilation, service as theses
from . import investigation
from .investigation_models import ResearchPlanResult
from .research_job_models import ResearchJob, ResearchJobAdmission, ResearchJobLease, ResearchJobOutcome, ResearchJobRevocation

POLICY = {"policy_version": "research-background-resume-2026-10-21-v1", "lease_seconds": 180,
    "max_leases": 12, "planning_allowed": False, "model_retries_allowed": False}
ELIGIBLE = {"discovering", "waiting_source", "ready_to_compile"}
TERMINAL = {"blocked", "completed", "revoked"}


class ResearchJobFenced(theses.ThesisConflict):
    pass


def _gate(*, execution=False):
    investigation._gate()
    if execution and getattr(settings, "MACRO_ENABLE_RESEARCH_BACKGROUND", False) is not True:
        raise compilation.CompilationDisabled("Internal background research is disabled")


def _job(actor_id, run_id, *, lock=False, skip_locked=False):
    rows = ResearchJob.objects.select_for_update(skip_locked=skip_locked) if lock else ResearchJob.objects
    value = rows.filter(run_id=run_id, owner_id=actor_id).first()
    if value is None and not skip_locked:
        raise theses.ThesisUnavailable("Background research unavailable")
    return value


def _at(clock, thesis, job=None):
    at = theses._instant(clock, thesis)
    if job is not None and at < job.changed_at:
        raise theses.ThesisConflict("Trusted clock precedes background research state")
    return at


def _wire(job, *, replayed=False):
    revoked = ResearchJobRevocation.objects.filter(job=job).first()
    leases = []
    for lease in job.leases.order_by("sequence"):
        outcome = ResearchJobOutcome.objects.filter(lease=lease).first()
        leases.append({"token": str(lease.pk), "sequence": lease.sequence,
            "admitted_at": lease.admitted_at.isoformat(), "deadline_at": lease.deadline_at.isoformat(),
            "admissions": [{"kind": "source" if item.source_attempt_id else "compilation",
                "admission_id": str(item.source_attempt_id or item.compilation_attempt_id),
                "admitted_at": item.admitted_at.isoformat()} for item in lease.admissions.order_by("admitted_at",
                    F("source_attempt__question_index").asc(nulls_last=True),
                    F("source_attempt__attempt_number").asc(nulls_last=True), "pk")],
            "outcome": {"status": outcome.status, "reason": outcome.reason,
                "finished_at": outcome.finished_at.isoformat()} if outcome else None})
    return {"job": {"id": str(job.pk), "run_id": str(job.run_id), "owner_id": str(job.owner_id),
        "enrollment_command_id": str(job.command_id), "request_digest": job.request_digest,
        "policy": job.policy, "provider": job.provider, "model_id": job.model_id,
        "model_configuration": job.model_configuration, "status": job.status,
        "next_due_at": job.next_due_at.isoformat() if job.next_due_at else None,
        "active_token": str(job.active_token) if job.active_token else None,
        "lease_deadline_at": job.lease_deadline_at.isoformat() if job.lease_deadline_at else None,
        "last_stop_reason": job.last_stop_reason, "created_at": job.created_at.isoformat(),
        "changed_at": job.changed_at.isoformat(),
        "revoked_at": revoked.created_at.isoformat() if revoked else None, "leases": leases},
        "replayed": replayed}


def inspect_job(actor_id, run_id, *, clock=timezone.now):
    _gate()
    with transaction.atomic():
        investigation.evidence._snapshot()
        theses._owner(actor_id)
        run = investigation._record(actor_id, run_id)
        job = _job(actor_id, run.pk)
        return _wire(job)


def _disposition(run, at):
    value = investigation._wire(run, at)["research"]
    status = value["status"]
    if status in ELIGIBLE:
        due = as_utc(timezone.datetime.fromisoformat(value["source_next_attempt_at"])) if value["source_next_attempt_at"] else at
        return "pending", due, value["source_stop_reason"] or status
    return ("completed" if status in {"compiled", "no_evidence"} else "blocked"), None, status


def enroll(actor_id, run_id, command_id, expected_request_digest, *, clock=timezone.now):
    _gate(execution=True)
    command_id = theses._uuid(command_id, "command_id")
    if (type(expected_request_digest) is not str or len(expected_request_digest) != 64
            or any(char not in "0123456789abcdef" for char in expected_request_digest)):
        raise ValueError("expected_request_digest requires the exact saved research digest")
    run = investigation._record(actor_id, run_id)
    with transaction.atomic():
        theses._owner(actor_id, lock=True)
        thesis = theses._record(actor_id, str(run.thesis_id), lock=True)
        previous = ResearchJob.objects.filter(owner_id=actor_id, command_id=command_id).first()
        if previous:
            if previous.run_id != run.pk or previous.request_digest != expected_request_digest:
                raise theses.ThesisConflict("Enrollment command belongs to another request")
            return _wire(previous, replayed=True)
        if ResearchJob.objects.filter(run=run).exists():
            raise theses.ThesisConflict("Research already has a retained background enrollment")
        at = _at(clock, thesis)
        if run.request_digest != expected_request_digest:
            raise theses.ThesisConflict("Research differs from the reviewed request digest")
        if not run.execution_policy or not ResearchPlanResult.objects.filter(attempt__run=run, status="planned").exists():
            raise theses.ThesisConflict("Background continuation requires saved planned research with source recovery")
        status, due, reason = _disposition(run, at)
        if status != "pending":
            raise theses.ThesisConflict("Only unfinished eligible research can enroll background continuation")
        job = ResearchJob.objects.create(owner_id=actor_id, run=run, command_id=command_id,
            request_digest=expected_request_digest, provider=run.provider, model_id=run.model_id,
            compilation_command_id=investigation._command(run, "compile"),
            evidence_command_id=investigation._command(run, "evidence"),
            model_configuration=compilation._configuration(run.provider), policy=POLICY,
            status=status, next_due_at=due, last_stop_reason=reason, created_at=at, changed_at=at)
        return _wire(job)


def revoke(actor_id, run_id, command_id, *, clock=timezone.now):
    _gate()
    command_id = theses._uuid(command_id, "command_id")
    run = investigation._record(actor_id, run_id)
    with transaction.atomic():
        theses._owner(actor_id, lock=True)
        thesis = theses._record(actor_id, str(run.thesis_id), lock=True)
        job = _job(actor_id, run.pk, lock=True)
        previous = ResearchJobRevocation.objects.filter(owner_id=actor_id, command_id=command_id).first()
        if previous:
            if previous.job_id != job.pk:
                raise theses.ThesisConflict("Revocation command belongs to another enrollment")
            return _wire(job, replayed=True)
        if ResearchJobRevocation.objects.filter(job=job).exists():
            raise theses.ThesisConflict("Background continuation was already revoked by another command")
        at = _at(clock, thesis, job)
        ResearchJobRevocation.objects.create(job=job, owner_id=actor_id, command_id=command_id, created_at=at)
        if job.active_token:
            ResearchJobOutcome.objects.get_or_create(lease_id=job.active_token,
                defaults={"status": "revoked", "reason": "owner_revoked", "finished_at": at})
        job.status, job.next_due_at, job.active_token, job.lease_deadline_at = "revoked", None, None, None
        job.changed_at, job.last_stop_reason = at, "owner_revoked"
        job.save(update_fields=("status", "next_due_at", "active_token", "lease_deadline_at", "changed_at", "last_stop_reason"))
        return _wire(job)


def protect_execution(actor_id, run_id, token, *, clock, required_seconds=0,
                      command_id=None, provider_id=None, model_id=None, context=None):
    """Called after governing owner/thesis (and model-budget) locks are held."""
    compilation._gate()
    if getattr(settings, "MACRO_ENABLE_RESEARCH_BACKGROUND", False) is not True:
        raise compilation.CompilationDisabled("Internal background research is disabled")
    token = theses._uuid(token, "research_job_token")
    job = _job(actor_id, run_id, lock=True)
    lease = ResearchJobLease.objects.filter(pk=token, job=job).first()
    run = investigation._record(actor_id, str(run_id))
    thesis = theses._record(actor_id, str(run.thesis_id))
    at = _at(clock, thesis, job)
    if (job.policy != POLICY or job.request_digest != run.request_digest
            or job.provider != run.provider or job.model_id != run.model_id
            or lease is None or job.status != "running" or job.active_token != lease.pk
            or ResearchJobRevocation.objects.filter(job=job).exists()
            or at < lease.admitted_at or at + timedelta(seconds=required_seconds) >= lease.deadline_at):
        raise ResearchJobFenced("Background research lease expired, revoked or superseded")
    if job.model_configuration != compilation._configuration(run.provider):
        raise ResearchJobFenced("Pinned background model configuration changed")
    if command_id is not None and (str(command_id) != investigation._command(run, "compile")
            or provider_id != job.provider or model_id != job.model_id or context is None
            or context.thesis_id != run.thesis_id or context.owner_id != run.owner_id
            or str(context.command_id) != investigation._command(run, "evidence")
            or context.content.get("question_research", {}).get("run_id") != str(run.pk)
            or context.content.get("question_research", {}).get("run_request_digest") != run.request_digest):
        raise ResearchJobFenced("Compilation differs from the exact enrolled investigation")
    return at


def record_admission(token, at, *, source_attempt=None, compilation_attempt=None):
    """Retain the exact lease provenance within the protected node admission."""
    return ResearchJobAdmission.objects.create(lease_id=token, source_attempt=source_attempt,
        compilation_attempt=compilation_attempt, admitted_at=at)


def fence_dispatch(actor_id, run_id, token, *, clock, required_seconds):
    """No admission here; recheck cancellation and lease immediately before GET."""
    run = investigation._record(actor_id, run_id)
    with transaction.atomic():
        theses._owner(actor_id, lock=True)
        theses._record(actor_id, str(run.thesis_id), lock=True)
        return protect_execution(actor_id, run_id, token, clock=clock, required_seconds=required_seconds)


def _claim(actor_id, run_id, *, clock):
    run = investigation._record(actor_id, run_id)
    with transaction.atomic():
        # Skip another worker without waiting behind its aggregate admission.
        from django.contrib.auth import get_user_model
        if get_user_model().objects.select_for_update(skip_locked=True).filter(pk=actor_id, is_active=True).first() is None:
            return None
        thesis = theses.ThesisRecord.objects.select_for_update(skip_locked=True).filter(pk=run.thesis_id, owner_id=actor_id).first()
        if thesis is None:
            return None
        job = _job(actor_id, run.pk, lock=True, skip_locked=True)
        if job is None:
            return None
        at = _at(clock, thesis, job)
        if job.status in TERMINAL or job.status == "running" and at < job.lease_deadline_at:
            return None
        if job.next_due_at is not None and job.next_due_at > at:
            return None
        if job.active_token:
            ResearchJobOutcome.objects.get_or_create(lease_id=job.active_token,
                defaults={"status": "expired", "reason": "worker_lease_expired", "finished_at": at})
        status, due, reason = _disposition(run, at)
        if status == "pending" and job.attempt_count >= POLICY["max_leases"]:
            status, due, reason = "blocked", None, "background_lease_limit_reached"
        if status != "pending" or due > at:
            job.status, job.next_due_at, job.last_stop_reason = status, due, reason
            job.active_token, job.lease_deadline_at, job.changed_at = None, None, at
            job.save(update_fields=("status", "next_due_at", "last_stop_reason", "active_token", "lease_deadline_at", "changed_at"))
            return None
        lease = ResearchJobLease.objects.create(job=job, sequence=job.attempt_count + 1,
            admitted_at=at, deadline_at=at + timedelta(seconds=POLICY["lease_seconds"]))
        job.status, job.active_token, job.lease_deadline_at = "running", lease.pk, lease.deadline_at
        job.attempt_count, job.changed_at = lease.sequence, at
        job.save(update_fields=("status", "active_token", "lease_deadline_at", "attempt_count", "changed_at"))
        return lease


def _finish(actor_id, run_id, token, *, reason=None, clock):
    run = investigation._record(actor_id, run_id)
    with transaction.atomic():
        theses._owner(actor_id, lock=True)
        thesis = theses._record(actor_id, str(run.thesis_id), lock=True)
        job = _job(actor_id, run.pk, lock=True)
        at = _at(clock, thesis, job)
        if job.active_token != token or job.status != "running":
            return _wire(job)
        if at >= job.lease_deadline_at:
            ResearchJobOutcome.objects.get_or_create(lease_id=token,
                defaults={"status": "expired", "reason": "worker_lease_expired", "finished_at": at})
            # Leave expired lease current for a future protected claim to recover.
            return _wire(job)
        if reason:
            status, due = "blocked", None
        else:
            status, due, reason = _disposition(run, at)
        ResearchJobOutcome.objects.create(lease_id=token, status=status, reason=reason, finished_at=at)
        job.status, job.next_due_at, job.last_stop_reason = status, due, reason
        job.active_token, job.lease_deadline_at, job.changed_at = None, None, at
        job.save(update_fields=("status", "next_due_at", "last_stop_reason", "active_token", "lease_deadline_at", "changed_at"))
        return _wire(job)


def run_tick(actor_id, run_id, *, provider=None, discovery=None, clock=timezone.now):
    _gate(execution=True)
    lease = _claim(actor_id, run_id, clock=clock)
    if lease is None:
        return inspect_job(actor_id, run_id, clock=clock)
    reason = None
    try:
        investigation.continue_research(actor_id, run_id, provider=provider, discovery=discovery,
            clock=clock, research_job_token=str(lease.pk))
    except ResearchJobFenced:
        reason = "worker_lease_or_configuration_changed"
    except compilation.CompilationBudgetExhausted:
        reason = "private_model_allowance_exhausted"
    except compilation.CompilationUnavailable:
        reason = "selected_provider_unavailable"
    except compilation.CompilationDisabled:
        reason = "research_configuration_disabled"
    except (theses.ThesisConflict, theses.ThesisUnavailable, ValueError, PermissionError):
        # Arbitrary exception text can contain private/provider data; retain only a safe code.
        reason = "research_requires_review"
    return _finish(actor_id, run_id, lease.pk, reason=reason, clock=clock)
