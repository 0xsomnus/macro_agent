"""Own-input happy path with a fixed fictional event and no provider calls.

Admission observes committed user inputs in its own transaction. Publication
then protects owner, thesis and brief again, so an intervening governing change
cannot create a current notice from stale context. Nothing here watches news.
"""

from dataclasses import replace
import json
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from macro_agent.application.publication import publish
from macro_agent.domain.models import ContextSnapshot
from macro_agent.domain.routing import route_event
from macro_agent.domain.time import as_utc
from macro_agent.persistence.context_binding import CONTEXT_ROLES, ContextPending, enroll_synthetic
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent, ThesisBriefBinding
from macro_agent.persistence.publication_store import DjangoPublicationStore, context_digest
from macro_agent.positions.models import PositionRecord
from macro_agent.positions.representation import version_wire

from .fixtures import fixture_case


class RecordedNewsUnavailable(PermissionError):
    """Disabled, missing and foreign-owner contexts share opaque unavailability."""


class RecordedNewsConflict(ValueError):
    """The requested approval or recorded publication is no longer current."""


LIMITATIONS = [
    "Fictional recorded example, not live news or continuous monitoring.",
    "Source contracts, coverage, macro context and all twelve non-user-context roles remain synthetic.",
    "Screening is prescribed by the example; your thesis and trades were not analyzed for relevance.",
    "Portfolio consequences, counter-analysis and expectations remain unresolved.",
    "Instrument mappings are user declarations, not validated market exposures.",
    "Notification intent is local; external delivery is not configured.",
    "Input observation is conservative; exact admission commit time is not measured.",
]


def enabled(*, using="default") -> bool:
    """Production settings cannot expose source-fixture authority by a flag alone."""
    name = settings.DATABASES[using]["NAME"]
    return (getattr(settings, "SETTINGS_MODULE", None) == "macro_agent.web.local_settings"
            and getattr(settings, "MACRO_ALLOW_SYNTHETIC_SETUP", False) is True
            and type(name) is str and (name.endswith("_dev") or name.startswith("test_")))


def _canonical_uuid(value, name):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError(f"{name} requires a canonical UUID")
    return value


def _result(tx, current, base, *, thesis_id, replayed, snapshot_at):
    """Materialize the response while the publication protections remain held."""
    payload = json.loads(current.payload)
    expected = [{"field": claim.field, "value": json.loads(claim.value_json)} for claim in base.fact_claims]
    if (payload["facts"] != expected or payload["kind"] != "supported_factual_notice"
            or payload["portfolio_impact"] != "unresolved"):
        raise RecordedNewsConflict("current notice differs from the recorded example")
    binding = ThesisBriefBinding.objects.using(tx.using).get(brief=tx.brief)
    notice = NotificationIntent.objects.using(tx.using).filter(brief=tx.brief, assessment=current).first()
    if notice is None:
        raise RecordedNewsConflict("recorded notice lacks its local notification intent")
    positions = []
    for row in (PositionRecord.objects.using(tx.using).filter(thesis_id=thesis_id, owner_id=tx.actor_id)
                .select_related("current_version").order_by("id")):
        version = version_wire(row.current_version)
        positions.append({"position_id": str(row.pk), "version_id": version["id"], **{
            key: version[key] for key in ("status", "underlying", "direction", "quantity", "quantity_unit",
                                         "horizon", "mapping_status", "missing_fields")}})
    route = route_event(base.screening)
    return {
        "mode": "recorded_example", "synthetic": True, "monitoring": "not_configured",
        "model": "not_used", "provider_calls": 0, "provider_spend": 0,
        "thesis_id": thesis_id, "snapshot_at": snapshot_at.isoformat(),
        "brief": {"id": tx.brief.pk, "generation": tx.brief.generation, "context_status": binding.status,
                  "current_assessment_id": current.assessment_id,
                  "input_observed_at": binding.observed_at.isoformat(), "commit_time_measured": False},
        "notice": {"assessment_id": current.assessment_id, "kind": "supported_factual_notice",
                   "is_current": True, "replayed": replayed, "portfolio_impact": "unresolved",
                   "expectations": "unavailable", "facts": payload["facts"],
                   "notification": {"intent_id": notice.pk, "state": notice.state,
                                    "external_delivery": "not_configured"}},
        "source": {"event_id": base.event.event_id, "revision": base.event.revision,
                   "source_id": base.event.source_id, "synthetic": True,
                   "public_available_at": base.event.times.public_available_at.isoformat(),
                   "recorded_system_received_at": base.event.times.system_received_at.isoformat(),
                   "recorded_known_at": base.event.times.known_at.isoformat()},
        "screening": {"basis": "recorded_fixture", "route": route.route.value,
                      "reasons": list(route.reasons), "personalized_relevance": "unresolved"},
        "positions": positions, "limitations": list(LIMITATIONS),
    }


def recorded_news(actor_id, thesis_id, expected_approval_id, *, clock=timezone.now, using="default"):
    if not enabled(using=using):
        raise RecordedNewsUnavailable("recorded examples are unavailable")
    _canonical_uuid(thesis_id, "thesis_id")
    _canonical_uuid(expected_approval_id, "expected_approval_id")
    base, dependencies = fixture_case(owner_id=actor_id, event_id="fictional-port-disruption")
    brief_id = "recorded-news:" + thesis_id + ":port-disruption-v1"
    try:
        # Existing ready context is a no-op. New approval/exposure receives a new
        # immutable admission; old admissions cannot reactivate obsolete state.
        enroll_synthetic(actor_id, thesis_id, brief_id, expected_approval_id,
            tuple(pin for pin in dependencies if pin.role not in CONTEXT_ROLES),
            clock=clock, synthetic=True, using=using)
        store = DjangoPublicationStore(actor_id, using=using)
        with store.transaction(brief_id) as tx:
            state = tx.state()
            binding = ThesisBriefBinding.objects.using(using).get(brief=tx.brief)
            if str(binding.admitted_approval_id) != expected_approval_id:
                raise RecordedNewsConflict("approval changed after context admission")
            at = as_utc(clock())
            if at < state.changed_at:
                raise ValueError("recorded publication clock precedes protected state")
            identity = "recorded-news:" + context_digest(state.dependencies)
            current_pointer = CurrentAssessment.objects.using(using).filter(brief=tx.brief).select_related("assessment").first()
            if current_pointer is not None:
                if current_pointer.assessment.assessment_id != identity:
                    raise RecordedNewsConflict("another assessment is already current")
                return _result(tx, current_pointer.assessment, base, thesis_id=thesis_id, replayed=True, snapshot_at=at)
            if tx.existing(identity) is not None:
                raise RecordedNewsConflict("historical notice cannot become current again")
            candidate = replace(base, assessment_id=identity, run_id="run:" + identity,
                brief_id=brief_id, expected_generation=state.generation,
                snapshot=ContextSnapshot("snapshot:" + identity, at, state.dependencies))
            # The nested application boundary uses the same protections and
            # applies its normal compare/save protocol. No network call occurs.
            decision = publish(store, candidate, clock)
            if decision.status != "current":
                raise RecordedNewsConflict("recorded notice was superseded")
            tx.brief.refresh_from_db(using=using)
            current = CurrentAssessment.objects.using(using).select_related("assessment").get(brief=tx.brief).assessment
            return _result(tx, current, base, thesis_id=thesis_id, replayed=False,
                           snapshot_at=max(at, as_utc(current.saved_at)))
    except ContextPending as error:
        raise RecordedNewsConflict("current approval or exposure requires a fresh request") from error
    except PermissionError as error:
        raise RecordedNewsUnavailable("recorded example is unavailable") from error
