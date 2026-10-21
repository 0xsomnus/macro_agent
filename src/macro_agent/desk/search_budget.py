"""Protected internal search reservations, with no provider/network activation.

USD integer millionths are the only monetary unit. One global lock precedes
sorted account locks and the research thesis. It protects derived sums rather
than a replenishable balance. No lock can span a provider request.
"""

import re
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import BigIntegerField, F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from macro_agent.domain.models import canonical_json, require_digest, text_digest
from macro_agent.domain.time import as_utc
from macro_agent.theses import service as theses

from .investigation_models import ResearchRun
from .search_budget_models import (
    SearchBudgetRoot, SearchPriceContract, SearchReservation, SearchSettlement,
)
from .service import gate, outermost


MONTHLY_CAP_MICROUSD = 10_000_000
INVESTIGATION_CAP_MICROUSD = 100_000
PRICE_SCHEMA = "search-request-price-v1"
PRICE_FIELDS = {"schema_version", "provider_id", "currency", "billing_basis",
                "maximum_charge_microusd", "pricing_reference", "pricing_evidence_digest"}
PROVENANCE_FIELDS = {"kind", "reference", "evidence_digest"}


class SearchBudgetExhausted(theses.ThesisConflict):
    """Saved research must pause; no request was admitted."""


def _amount(value, label, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= INVESTIGATION_CAP_MICROUSD:
        raise ValueError(f"{label} requires bounded integer USD millionths")
    return value


def _price(document):
    if type(document) is not dict or set(document) != PRICE_FIELDS:
        raise ValueError("An exact bounded per-request price contract is required")
    if (document["schema_version"] != PRICE_SCHEMA or document["currency"] != "USD"
            or document["billing_basis"] != "per_request_upper_bound"
            or type(document["provider_id"]) is not str
            or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", document["provider_id"]) is None):
        raise ValueError("Unsupported price identity, currency or billing basis")
    _amount(document["maximum_charge_microusd"], "maximum_charge_microusd")
    theses._text(document["pricing_reference"], "pricing_reference", 512)
    require_digest(document["pricing_evidence_digest"], "pricing_evidence_digest")
    # Copies protect the retained identity against mutation by the caller.
    return dict(document)


def _provenance(value, charge):
    if type(value) is not dict or set(value) != PROVENANCE_FIELDS:
        raise ValueError("Exact charge evidence provenance is required")
    kind = "provider_zero_charge_confirmation" if charge == 0 else "provider_charge_record"
    if value["kind"] != kind:
        raise ValueError("A charge requires a provider record; zero requires explicit confirmation")
    theses._text(value["reference"], "reference", 512)
    require_digest(value["evidence_digest"], "evidence_digest")
    return dict(value)


def _root():
    # Recreate after a test flush; the constraint prevents a second budget root.
    SearchBudgetRoot.objects.get_or_create(pk=1)
    return SearchBudgetRoot.objects.select_for_update().get(pk=1)


def _accounts(*identities):
    # Reconciliation can involve a separate operator. Never acquire its row
    # before a lower-sorted owner while other publication writers run.
    result = {}
    for identity in sorted(set(identities)):
        theses._uuid(identity, "actor_id")
        actor = get_user_model().objects.select_for_update().filter(pk=identity).first()
        if actor is None:
            raise theses.ThesisUnavailable("Search accounting operation unavailable")
        result[identity] = actor
    return result


def _staff(actor):
    if not actor.is_active or not actor.is_staff:
        raise theses.ThesisUnavailable("Search accounting operation unavailable")


def _run(actor_id, run_id):
    run = ResearchRun.objects.filter(pk=run_id, owner_id=actor_id).first()
    if run is None:
        raise theses.ThesisUnavailable("Research unavailable")
    return run


def _spent(rows):
    value = rows.aggregate(total=Sum(Coalesce(F("settlement__actual_charge_microusd"),
        F("maximum_charge_microusd"), output_field=BigIntegerField())))
    return value["total"] or 0


def _wire(row, *, replayed=False):
    settled = SearchSettlement.objects.filter(reservation=row).first()
    return {"call_id": str(row.pk), "owner_id": str(row.owner_id), "run_id": str(row.run_id),
        "price_contract_digest": row.price_contract_id,
        "maximum_charge_microusd": row.maximum_charge_microusd,
        "month_start": row.month_start.isoformat(), "created_at": row.created_at.isoformat(),
        "actual_charge_microusd": None if settled is None else settled.actual_charge_microusd,
        "held_microusd": row.maximum_charge_microusd if settled is None else 0,
        "replayed": replayed}


def record_price_contract(operator_id, document, *, clock=timezone.now):
    """Named operator evidence only. Retaining a price does not enable its source.

    No HTTP endpoint exposes this service and no price contract is preconfigured.
    Retention/model-processing permission and provider activation remain separate.
    """
    gate()
    outermost()
    document = _price(document)
    digest = text_digest(canonical_json(document))
    with transaction.atomic():
        _root()
        operator = _accounts(operator_id)[operator_id]
        _staff(operator)
        saved = SearchPriceContract.objects.filter(pk=digest).first()
        if saved is not None:
            return saved
        return SearchPriceContract.objects.create(digest=digest, document=document,
            provider_id=document["provider_id"],
            maximum_charge_microusd=document["maximum_charge_microusd"],
            reviewed_by=operator, reviewed_at=as_utc(clock()))


def reserve_search(actor_id, run_id, call_id, price_contract_digest, *, clock=timezone.now):
    """Reserve before a paid lookup; callers cannot supply a price or another owner."""
    gate()
    outermost()
    run_id = theses._uuid(run_id, "run_id")
    call_id = theses._uuid(call_id, "call_id")
    require_digest(price_contract_digest, "price_contract_digest")
    # An exact saved identity is inert before current eligibility or pricing.
    theses._owner(actor_id)
    saved = SearchReservation.objects.filter(pk=call_id).first()
    if saved is not None:
        return _replay(saved, actor_id, run_id, price_contract_digest)
    with transaction.atomic():
        _root()
        actor = _accounts(actor_id)[actor_id]
        if not actor.is_active:
            raise theses.ThesisUnavailable("Research unavailable")
        run = _run(actor_id, run_id)
        thesis = theses._record(actor_id, str(run.thesis_id), lock=True)
        saved = SearchReservation.objects.filter(pk=call_id).first()
        if saved is not None:
            return _replay(saved, actor_id, run_id, price_contract_digest)
        price = SearchPriceContract.objects.filter(pk=price_contract_digest).first()
        if price is None:
            raise theses.ThesisConflict("No retained per-request price contract exists")
        document = _price(price.document)
        if (text_digest(canonical_json(document)) != price.digest
                or price.provider_id != document["provider_id"]
                or price.maximum_charge_microusd != document["maximum_charge_microusd"]):
            raise theses.ThesisConflict("Retained price contract failed integrity verification")
        at = theses._instant(clock, thesis)
        if at < run.created_at or at < price.reviewed_at:
            raise theses.ThesisConflict("Search reservation cannot precede its retained dependencies")
        if (thesis.revision != run.initial_revision or thesis.latest_text_id != run.initial_text_id
                or thesis.current_approval_id is not None):
            raise theses.ThesisConflict("Research input changed before search reservation")
        month = date(at.year, at.month, 1)
        rows = SearchReservation.objects.all()
        amount = price.maximum_charge_microusd
        if _spent(rows.filter(month_start=month)) + amount > MONTHLY_CAP_MICROUSD:
            raise SearchBudgetExhausted("Shared UTC-month search budget exhausted")
        if _spent(rows.filter(run=run)) + amount > INVESTIGATION_CAP_MICROUSD:
            raise SearchBudgetExhausted("Investigation lifetime search budget exhausted")
        row = SearchReservation.objects.create(id=call_id, owner_id=actor_id, run=run,
            price_contract=price, maximum_charge_microusd=amount, month_start=month, created_at=at)
        return _wire(row)


def _replay(row, actor_id, run_id, price_digest):
    if str(row.owner_id) != actor_id:
        raise theses.ThesisUnavailable("Search reservation unavailable")
    if str(row.run_id) != run_id or row.price_contract_id != price_digest:
        raise theses.ThesisConflict("Search call identity belongs to another exact request")
    return _wire(row, replayed=True)


def settle_search(operator_id, call_id, actual_charge_microusd, provenance, *, clock=timezone.now):
    """One immutable named-operator reconciliation, never a timeout release.

    A provider response or HTTP failure alone cannot establish its final charge.
    """
    gate()
    outermost()
    call_id = theses._uuid(call_id, "call_id")
    charge = _amount(actual_charge_microusd, "actual_charge_microusd", zero=True)
    provenance = _provenance(provenance, charge)
    with transaction.atomic():
        _root()
        row = SearchReservation.objects.filter(pk=call_id).first()
        if row is None:
            raise theses.ThesisUnavailable("Search reservation unavailable")
        accounts = _accounts(operator_id, str(row.owner_id))
        _staff(accounts[operator_id])
        theses._record(str(row.owner_id), str(row.run.thesis_id), lock=True)
        saved = SearchSettlement.objects.filter(reservation=row).first()
        if saved is not None:
            if (str(saved.operator_id) != operator_id or saved.actual_charge_microusd != charge
                    or saved.provenance != provenance):
                raise theses.ThesisConflict("A search settlement cannot be rewritten")
            return _wire(row, replayed=True)
        if charge > row.maximum_charge_microusd:
            raise theses.ThesisConflict("Known charge exceeds its reserved maximum")
        at = as_utc(clock())
        if at < row.created_at:
            raise theses.ThesisConflict("Charge evidence cannot precede its reservation")
        SearchSettlement.objects.create(reservation=row, actual_charge_microusd=charge,
            operator=accounts[operator_id], provenance=provenance, recorded_at=at)
        return _wire(row)


def get_reservation(actor_id, call_id):
    gate()
    theses._owner(actor_id)
    call_id = theses._uuid(call_id, "call_id")
    row = SearchReservation.objects.filter(pk=call_id, owner_id=actor_id).first()
    if row is None:
        raise theses.ThesisUnavailable("Search reservation unavailable")
    return _wire(row)
