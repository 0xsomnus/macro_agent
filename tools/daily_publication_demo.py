"""Fictional daily publication/restart/correction trace in a temporary database."""

import argparse
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test.runner import DiscoverRunner
from django.utils import timezone

from macro_agent.desk import permissions, publication, service
from macro_agent.domain.daily_review import DailyReviewLimits
from macro_agent.monitoring import analysis, capture
from macro_agent.monitoring.gates import require_local_proof
from macro_agent.monitoring.models import SourceState
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.persistence.models import AuditTransition
from macro_agent.positions import service as positions
from macro_agent.theses import service as theses


def demonstrate():
    user = get_user_model().objects.create_user(username="fictional-daily-trader")
    staff = get_user_model().objects.create_user(username="fictional-permission-reviewer", is_staff=True)
    actor = str(user.pk)
    draft = theses.create_thesis(actor, str(uuid4()), "  Easier policy could support equities.\r\nΔ\r\n",
        {"drivers": ["Easier policy"], "horizon": "weeks to months",
         "invalidation_signposts": ["Policy transmission fails"]})["thesis"]
    text, meaning = draft["draft"]["text_version"], draft["draft"]["interpretation"]
    thesis = theses.approve_thesis(actor, draft["id"], str(uuid4()), text["id"], text["text_digest"],
        meaning["id"], meaning["digest"], draft["revision"])["thesis"]
    positions.create_position(actor, thesis["id"], str(uuid4()), thesis["approved"]["approval"]["id"],
        {"underlying": "NQ", "direction": "long", "quantity": None, "quantity_unit": None,
         "horizon": None, "product_id": None, "venue": None, "expiry": None, "quote_currency": None})
    source_id = "fixture-daily-publication-trace"
    contract = {"kind": "fictional_fixture", "label": "Fictional daily publication trace", "coverage": "bounded_snapshot"}
    def capture_report(content):
        item = SourceItem("policy-report", "Fictional policy report", "https://example.invalid/policy",
            timezone.now() - timedelta(days=1), content)
        return capture.capture(source_id, contract, lambda: SourceBatch((item,), timezone.now(),
            "bounded_snapshot", False, sha256(content.encode("utf-8")).hexdigest()))
    capture_report("Fictional source reports a policy easing measure.")
    cutoff = timezone.now()
    # Demonstration inputs, never hidden operating defaults.
    limits = DailyReviewLimits(100, 100, 200, 300, 16, 2_000_000)
    first = service.create_review(actor, thesis["id"], str(uuid4()), cutoff-timedelta(days=1), cutoff,
        [source_id], limits)
    preview = publication.preview_publication(actor, first["review"]["id"], 10)
    command = str(uuid4())
    saved = publication.publish_review(actor, preview["review_id"], command, preview["review_digest"],
        preview["expected_generation"], 10)
    # Separate connections simulate receipt recovery without rebuilding content.
    connections.close_all()
    recovered = publication.get_publication_command(actor, thesis["id"], command)
    assert recovered["publication"] == saved["publication"] and recovered["replayed"]
    capture_report("Fictional correction: the policy measure is conditional, not yet enacted.")
    canceled = publication.inspect_publication(actor, saved["publication"]["id"])
    assert canceled["publication"] == saved["publication"]
    assert canceled["notification_intent"]["state"] == "canceled"
    assert publication.get_current_brief(actor, thesis["id"])["current_publication"] is None
    retry = publication.publish_review(actor, preview["review_id"], command, preview["review_digest"], 0, 10)
    assert retry["replayed"] and retry["current_disposition"]["status"] == "superseded"
    later_cutoff = timezone.now()
    later = service.create_review(actor, thesis["id"], str(uuid4()), cutoff, later_cutoff, [source_id], limits)
    latest = publication.publish_review(actor, later["review"]["id"], str(uuid4()), later["review"]["digest"], 1, 10)
    assert latest["publication"]["generation_at_publication"] == 2
    source = SourceState.objects.get(pk=source_id)
    permissions.set_source_permission(str(staff.pk), source_id, source.contract_digest, False,
        "Fictional explicit withdrawal demonstrates cancellation.")
    withdrawn = publication.inspect_publication(actor, latest["publication"]["id"])
    assert withdrawn["notification_intent"]["state"] == "canceled"
    assert publication.get_current_brief(actor, thesis["id"])["current_publication"] is None
    return {"scope": "Fictional isolated PostgreSQL daily publication trace",
        "configuration_values": "demonstration inputs, not operating defaults",
        "approved_thesis": thesis, "first_review": first, "publication_preview": preview,
        "first_publication": saved, "restart_receipt": recovered,
        "after_correction": canceled, "historical_retry": retry,
        "later_publication": latest, "after_permission_withdrawal": withdrawn,
        "transitions": list(AuditTransition.objects.order_by("sequence").values("sequence", "brief_id", "kind", "detail")),
        "real_model_calls": 0, "real_network_calls": 0, "real_model_spend_usd": "0",
        "compute_storage_cost": "not measured",
        "limits": ["This deterministic digest contains no fresh model synthesis or verified macro regime.",
            "Only a fictional bounded source is covered; live rights and source fit remain separate gates.",
            "Saved notification intents are internal; external delivery is unavailable.",
            "Separate connections prove receipt recovery, not operating-system crash or production readiness.",
            "Independent PostgreSQL race tests supplement this sequential trace."]}


def isolated_demonstration():
    require_local_proof(synthetic=True)
    service.gate()
    if connection.vendor != "postgresql":
        raise RuntimeError("The trace requires PostgreSQL")
    temporary_name = "test_daily_publication_demo_" + uuid4().hex[:16]
    connection.settings_dict["TEST"]["NAME"] = temporary_name
    runner = DiscoverRunner(interactive=False, verbosity=0, keepdb=False)
    state = runner.setup_databases()
    try:
        with patch.object(analysis, "create_provider", side_effect=AssertionError("Real providers forbidden")):
            result = demonstrate()
    finally:
        runner.teardown_databases(state)
    result["database_isolation"] = {"temporary_database": temporary_name,
        "dropped_after_trace": True, "existing_trader_records_used": False}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite an existing trace")
    result = isolated_demonstration()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Saved fictional daily publication trace. Temporary database dropped; real model/network calls: 0.")
