"""Private approved context plus one permitted, retained report observation.

Order for protected operations is source, owner, thesis, then model budget.
Read-only snapshots compute disposition instead of storing a current pointer.
"""

from dataclasses import asdict

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.persistence.context_binding import _resolved, lock_owner_thesis
from macro_agent.positions.service import MAX_POSITION_RECORDS
from macro_agent.theses import service as theses

from .models import DurableObservation, SourceState
from .sources import source_specs


LIMITATIONS = [
    "One retained report, not broad news coverage or a verified current macro regime.",
    "Exact excerpts establish attribution, not factual truth or semantic support.",
    "Thesis and trade connections are unverified model hypotheses for review.",
    "The complete attached-thesis paper book is not the user's whole portfolio.",
    "Instrument mapping, consensus, pricing and market reactions are unverified or unavailable.",
    "No thesis amendment, notice, execution or automatic paid retry is authorized.",
    "Source order is latest observed payload, not authoritative publisher revision order.",
    "Input observations and preparation times are not exact durable admission commit times.",
]


class NewsDisabled(PermissionError):
    pass


class NewsMissing(PermissionError):
    pass


class NewsConflict(ValueError):
    pass


def gate():
    name = settings.DATABASES["default"]["NAME"]
    if (settings.SETTINGS_MODULE != "macro_agent.web.local_settings"
            or not getattr(settings, "MACRO_ENABLE_NEWS_ANALYSIS", False)
            or not (name.endswith("_dev") or name.startswith("test_"))):
        raise NewsDisabled("Internal news review unavailable")


def allowed_source(row):
    if row.contract.get("kind") == "fictional_fixture":
        return bool(settings.MACRO_ALLOW_SYNTHETIC_SETUP and row.pk.startswith("fixture-"))
    if row.pk not in source_specs:
        return False
    contract = {**asdict(source_specs[row.pk]), "adapter_version": "rss-v1", "coverage": "bounded_snapshot"}
    return row.contract_digest == text_digest(canonical_json(contract))


def protected_source(source_id):
    row = SourceState.objects.select_for_update().filter(pk=source_id).first()
    if row is None or not allowed_source(row):
        raise NewsMissing("Source unavailable for internal analysis")
    return row


def resolve(thesis, approval_id):
    try:
        approval, inputs, digest = _resolved(thesis, approval_id, "default")
    except ValueError:
        raise NewsConflict("Review the current approved thesis and paper exposure") from None
    if len(inputs["exposure"]["positions"]) > MAX_POSITION_RECORDS:
        raise NewsConflict("Complete paper exposure book exceeds the internal bound")
    return approval, inputs, digest


def projected_positions(book):
    fields = ("status", "underlying", "direction", "quantity", "quantity_unit", "horizon",
              "product_id", "venue", "expiry", "quote_currency", "mapping_status")
    missing_fields = ("product_id", "venue", "quote_currency", "horizon", "quantity", "quantity_unit")
    return [{"position_id": row["position_id"], "version_id": row["version_id"],
        **{key: row["payload"][key] for key in fields},
        "missing_fields": [key for key in missing_fields if row["payload"][key] is None]}
        for row in book["positions"]]


def build_context(source, revision, inputs):
    from .capture import canonical_digest
    if canonical_digest(revision.payload) != revision.digest:
        raise NewsConflict("Retained source payload failed integrity verification")
    witness = DurableObservation.objects.filter(revision=revision).first()
    meaning, text, approval = inputs["interpretation"], inputs["text"], inputs["approval"]
    return {"source": {"source_key": source.pk, "report_id": revision.report_id,
        "native_id": revision.report.native_id, "revision_id": str(revision.pk),
        "digest": revision.digest, **{key: revision.payload[key] for key in ("title", "content", "url")},
        "published_at": revision.payload["published_at"],
        "received_at": revision.system_received_at.isoformat(),
        "availability_witness_at": witness.observed_by_at.isoformat() if witness else None,
        "is_fixture": source.contract["kind"] == "fictional_fixture"},
        "approved_thesis": {"thesis_id": inputs["thesis_id"], "thesis_version_id": text["version_id"],
            "approval_id": approval["version_id"], "interpretation_id": meaning["version_id"],
            "exact_text": text["exact_text"], "drivers": meaning["drivers"], "horizon": meaning["horizon"],
            "invalidation_signposts": meaning["invalidation_signposts"]},
        "positions": projected_positions(inputs["exposure"])}


def readonly_snapshot():
    if connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("News inspection requires its own read-only snapshot")
    return transaction.atomic()


def set_readonly():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")


def review_context(actor_id, thesis_id):
    gate()
    with readonly_snapshot():
        set_readonly()
        theses._owner(actor_id)
        thesis = theses._record(actor_id, thesis_id)
        if thesis.current_approval_id is None:
            raise NewsConflict("Approve exact text and interpretation before news review")
        approval, inputs, digest = resolve(thesis, str(thesis.current_approval_id))
        return {"thesis_id": str(thesis.pk), "approval_id": str(approval.pk), "exposure_digest": digest,
            "approved_exact_text": inputs["text"]["exact_text"],
            "approved_interpretation": {key: inputs["interpretation"][key] for key in
                ("drivers", "horizon", "invalidation_signposts")},
            "positions": projected_positions(inputs["exposure"]), "limitations": LIMITATIONS}


def news_catalog(actor_id):
    gate()
    with readonly_snapshot():
        set_readonly()
        theses._owner(actor_id)
        return {"sources": [{"id": row.pk, "label": row.contract["label"],
            "kind": row.contract["kind"], "current_reports": row.sourcereport_set.filter(current_revision__isnull=False).count()}
            for row in SourceState.objects.order_by("pk") if allowed_source(row)], "limitations": LIMITATIONS}
