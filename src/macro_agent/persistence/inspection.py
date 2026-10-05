"""Coherent owner-scoped report, using a PostgreSQL read-only snapshot."""

import json

from django.db import transaction

from ..domain.models import require_text
from ..domain.publication import BriefState, pin_dict
from .models import (
    AssessmentRecord, AuditTransition, BriefStateRecord, BriefVersion, ContextAdmission,
    CurrentAssessment, DependencyVersion, NotificationIntent, ReassessmentWork, ThesisBriefBinding,
)
from .publication_store import canonical_actor, current_dependencies, require_postgresql


def inspect_brief(actor_id: str, brief_id: str, *, using: str = "default") -> dict:
    """Return a fully materialized report without writing or logging access.

    This is deliberately outermost: SET TRANSACTION must precede all queries.
    A caller with an active transaction must finish it before requesting a report.
    """
    actor_id = canonical_actor(actor_id)
    require_text(brief_id, "brief_id")
    connection = require_postgresql(using)
    if connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("inspection requires its own outermost read-only transaction")
    with transaction.atomic(using=using):
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        brief = BriefStateRecord.objects.using(using).filter(
            brief_id=brief_id, owner_id=actor_id, owner__is_active=True).first()
        if brief is None:
            raise PermissionError("brief is unavailable to this actor")
        state = BriefState(str(brief.owner_id), brief.generation,
                           current_dependencies(brief_id, using), brief.changed_at)
        current = CurrentAssessment.objects.using(using).filter(brief=brief).select_related("assessment").first()
        current_id = current.assessment.assessment_id if current is not None else None
        assessments = []
        for record in AssessmentRecord.objects.using(using).filter(brief=brief).order_by("id"):
            assessments.append({
                "assessment_id": record.assessment_id, "digest": record.digest,
                "payload": json.loads(record.payload),
                "decision": {"status": record.status, "reasons": record.reasons,
                             "reassessment_required": record.reassessment_required},
                "observed_dependencies": record.observed_dependencies,
                "is_current": record.assessment_id == current_id,
                "saved_at": record.saved_at.isoformat(),
            })
        report = {
            "brief_id": brief_id, "owner_id": str(brief.owner_id),
            "generation": brief.generation, "changed_at": brief.changed_at.isoformat(),
            "current_assessment_id": current_id,
            "current_dependencies": [pin_dict(pin) for pin in state.dependencies],
            "assessments": assessments,
        }
        binding = ThesisBriefBinding.objects.using(using).filter(brief=brief).first()
        report["thesis_binding"] = None if binding is None else {
            "thesis_id": str(binding.thesis_id), "status": binding.status,
            "admitted_approval_id": str(binding.admitted_approval_id) if binding.admitted_approval_id else None,
            "admitted_exposure_digest": binding.admitted_exposure_digest,
            "input_observed_at": binding.observed_at.isoformat() if binding.observed_at else None,
            "commit_time_measured": False,
        }
        report["context_admissions"] = [{
            "id": str(item.pk), "approval_id": str(item.approval_id),
            "exposure_digest": item.exposure_digest, "input_digest": item.input_digest,
            "input_observed_at": item.input_observed_at.isoformat(),
            "admission_effective_at": item.admission_effective_at.isoformat(),
            "resolved_inputs": item.resolved_inputs, "pins": item.pins,
        } for item in ContextAdmission.objects.using(using).filter(brief=brief)
             .order_by("input_observed_at", "id")]
        report["dependency_history"] = [{
            "brief_id": brief_id, "role": version.role, "version_id": version.version_id,
            "digest": version.digest, "known_at": version.known_at.isoformat(),
        } for version in DependencyVersion.objects.using(using).filter(brief=brief).order_by("role", "known_at", "version_id")]
        report["brief_versions"] = [{
            "brief_id": brief_id, "generation": version.generation,
            "assessment_id": version.assessment.assessment_id, "saved_at": version.saved_at.isoformat(),
        } for version in BriefVersion.objects.using(using).filter(brief=brief).select_related("assessment").order_by("generation")]
        report["notifications"] = [{
            "intent_id": intent.intent_id, "brief_id": brief_id,
            "assessment_id": intent.assessment.assessment_id, "state": intent.state,
            "created_at": intent.created_at.isoformat(), "updated_at": intent.updated_at.isoformat(),
        } for intent in NotificationIntent.objects.using(using).filter(brief=brief).select_related("assessment").order_by("created_at", "intent_id")]
        report["reassessment"] = [{
            "brief_id": brief_id, "context_digest": work.context_digest, "reason": work.reason,
            "created_at": work.created_at.isoformat(), "state": work.state,
            "completed_at": work.completed_at.isoformat() if work.completed_at else None,
        } for work in ReassessmentWork.objects.using(using).filter(brief=brief).order_by("created_at", "context_digest")]
        report["audit"] = [{
            "sequence": entry.sequence, "brief_id": brief_id, "kind": entry.kind,
            "happened_at": entry.happened_at.isoformat(), "detail": entry.detail,
        } for entry in AuditTransition.objects.using(using).filter(brief=brief).order_by("sequence")]
        return report
