"""Recorded driver-attention session/CSRF proof in disposable PostgreSQL.

All sources and model replies are fictional. This trace does not send alerts,
use real model credentials, or inspect existing trader records.
"""

import argparse
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import django
django.setup()

from django.db import connection, connections
from django.test import Client, override_settings
from django.test.runner import DiscoverRunner

from macro_agent.api.news_publication_serializers import NewsPublicationDetailSerializer
from macro_agent.domain.news_publication import POLICY_VERSION
from macro_agent.desk import service as desk
from macro_agent.monitoring import analysis
from macro_agent.monitoring.gates import require_local_proof
from macro_agent.monitoring.tests import test_news_publication as fixtures
from macro_agent.persistence.models import AuditTransition, CurrentAssessment, NotificationIntent
from macro_agent.scheduling.models import WatchRecord


@contextmanager
def cleanup_cursor(open_cursor):
    """Only this generated database's maintenance session gets a DROP timeout."""
    with open_cursor() as cursor:
        cursor.execute("SET statement_timeout = '60000ms'")
        yield cursor


def teardown(runner, state, name):
    if not name.startswith("test_driver_attention_demo_"):
        raise RuntimeError("Unexpected demo database name")
    with ExitStack() as patches:
        for database, _, destroy in state:
            if not destroy:
                continue
            if database.vendor != "postgresql" or database.settings_dict["NAME"] != name:
                raise RuntimeError("Refusing cleanup outside the generated demo database")
            open_cursor = database.creation._nodb_cursor
            patches.enter_context(patch.object(database.creation, "_nodb_cursor",
                side_effect=lambda original=open_cursor: cleanup_cursor(original)))
        runner.teardown_databases(state)


def demonstrate():
    # Import the fixture module rather than exposing an imported TestCase class
    # to unittest discovery. Its setup creates records only in this test DB.
    case = fixtures.NewsPublicationTests("runTest")
    case.setUp()
    case.owner.set_password("fictional-local-password")
    case.owner.save(update_fields=("password",))
    client = Client(enforce_csrf_checks=True)

    def get(path, query=None):
        response = client.get(path, query or {})
        if response.status_code != 200:
            raise AssertionError((path, response.status_code, response.json()))
        return response.json()

    def post(path, body):
        csrf = get("/api/v1/session/")["csrf_token"]
        response = client.post(path, json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
        if response.status_code != 200:
            raise AssertionError((path, response.status_code, response.json()))
        return response.json()

    post("/api/v1/session/login/", {"username": case.owner.username, "password": "fictional-local-password"})
    thesis_id = case.thesis["id"]
    approved_before = get(f"/api/v1/theses/{thesis_id}/")
    closed = post(f"/api/v1/positions/{case.position['id']}/close/", {
        "command_id": str(uuid4()), "expected_revision": case.position["revision"],
        "expected_approval_id": case.approval_id})
    context = get(f"/api/v1/theses/{thesis_id}/news-context/")
    assert all(item["status"] == "closed" for item in context["positions"])
    assert not WatchRecord.objects.exists()
    first_analysis = case.analysed()
    assert first_analysis["status"] == "analysed"
    assert first_analysis["document"]["trade_route"]["position_ids"] == []
    assert first_analysis["document"]["driver_assessment"]["attention"]["status"] == "review_recommended"
    assert not CurrentAssessment.objects.exists() and not NotificationIntent.objects.exists()
    analysis_only = {"current_assessments": 0, "notification_intents": 0,
        "reason": "The model recommendation alone has no publication authority."}

    def publish(output):
        preview = get(f"/api/v1/news-analyses/{output['id']}/publication-preview/", {
            "fanout_limit": 10, "policy_version": POLICY_VERSION})
        command = {"command_id": str(uuid4()), "expected_analysis_digest": preview["analysis_digest"],
            "expected_generation": preview["expected_generation"], "fanout_limit": 10,
            "policy_version": POLICY_VERSION}
        saved = post(f"/api/v1/news-analyses/{output['id']}/publish/", command)
        serializer = NewsPublicationDetailSerializer(data=saved)
        assert serializer.is_valid(), serializer.errors
        assert saved["analysis"]["document"] == output["document"]
        return preview, command, saved

    first_preview, first_command, first = publish(first_analysis)
    assert first["publication"]["attention_decision"]["status"] == "review_requested"
    assert first["publication"]["attention_origin_publication_id"] == first["publication"]["id"]
    assert first["notification_intent"]["state"] == "pending"
    assert first["publication"]["generation_at_publication"] == 1
    first_current = get(f"/api/v1/theses/{thesis_id}/news-brief/")
    assert first_current["current_publication"]["publication"] == first["publication"]

    desk.observe_analysis_results(case.actor, thesis_id,
        (fixtures.recorded.SOURCE, fixtures.cumulative.BACKGROUND), limit=10)
    case.capture_item(native="report-2", title="Another fictional report repeats the same retained development")
    second_analysis = case.analysed()
    second_preview, second_command, carried = publish(second_analysis)
    assert carried["publication"]["attention_decision"]["status"] == "review_carried"
    assert carried["publication"]["attention_origin_publication_id"] == first["publication"]["id"]
    assert carried["publication"]["predecessor_publication_id"] == first["publication"]["id"]
    assert carried["publication"]["generation_at_publication"] == 2
    assert carried["notification_intent"]["state"] == "pending"
    assert NotificationIntent.objects.filter(state="pending").count() == 1
    assert NotificationIntent.objects.get(pk=first["notification_intent"]["id"]).state == "canceled"
    assert not WatchRecord.objects.exists()
    current_carried = get(f"/api/v1/theses/{thesis_id}/news-brief/")
    assert current_carried["current_publication"]["publication"] == carried["publication"]

    connections.close_all()
    recovered = get(f"/api/v1/theses/{thesis_id}/news-publication-commands/{second_command['command_id']}/")
    assert recovered["replayed"] and recovered["publication"] == carried["publication"]
    case.background("FICTIONAL CORRECTION: the earlier funding constraint is disputed")
    current_after_correction = get(f"/api/v1/theses/{thesis_id}/news-brief/")
    assert current_after_correction["current_publication"] is None
    assert not CurrentAssessment.objects.exists()
    assert NotificationIntent.objects.filter(state="pending").count() == 0
    with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                           SETTINGS_MODULE="macro_agent.web.local_settings"):
        keyless_receipt = get(f"/api/v1/theses/{thesis_id}/news-publication-commands/{second_command['command_id']}/")
        exact_retry = post(f"/api/v1/news-analyses/{second_analysis['id']}/publish/", second_command)
    assert keyless_receipt["publication"] == carried["publication"] == exact_retry["publication"]
    assert keyless_receipt["current_disposition"]["status"] == "superseded"
    assert keyless_receipt["notification_intent"]["state"] == "canceled"
    assert exact_retry["replayed"]
    approved_after = get(f"/api/v1/theses/{thesis_id}/")
    assert approved_after == approved_before
    assert case.provider.calls == 2 and case.provider.catalog_calls == 2
    post("/api/v1/session/logout/", {})
    return {"scope": "Fictional cumulative driver analysis and qualified internal attention through the session/CSRF API",
        "approved_thesis": approved_before, "closed_paper_declaration": closed,
        "approved_context_with_no_open_positions": context,
        "analysis_without_publication_authority": analysis_only,
        "first_analysis": first_analysis, "first_preview": first_preview,
        "first_publication": first, "first_current_brief": first_current,
        "second_analysis": second_analysis, "second_preview": second_preview,
        "carried_publication": carried, "current_carried_brief": current_carried,
        "restart_receipt": recovered, "current_after_correction": current_after_correction,
        "keyless_recovery_after_correction": keyless_receipt, "exact_retry_after_correction": exact_retry,
        "transitions": list(AuditTransition.objects.order_by("sequence").values("sequence", "brief_id", "kind", "detail")),
        "new_qualified_review_requests": 1, "carried_review_updates": 1,
        "remaining_pending_intents": 0, "external_deliveries": 0,
        "implicit_watches_created": 0, "recorded_model_calls": case.provider.calls,
        "recorded_catalogue_calls": case.provider.catalog_calls, "real_model_calls": 0,
        "real_network_calls": 0, "real_model_spend_usd": "0",
        "limits": ["All sources and model responses are fictional recordings, not financial research or live coverage.",
            "Publication is a separate protected admission; model attention recommendations alone grant no authority.",
            "A carried intent preserves unresolved internal work and its original evidence, rather than requesting another interruption.",
            "No external notification transport, delivery acknowledgement or verified materiality is demonstrated.",
            "Exact quotations establish attribution, not factual truth, semantic support or causal attribution.",
            "No verified market-price history or prospective entry assessment is available.",
            "Closing a fictional paper declaration preserves its history; there are no open positions during either analysis.",
            "Connection restart proves retained receipt recovery, not an operating-system crash.",
            "Recorded provider costs remain unknown; zero real spending describes this fixture demonstration only."]}


def isolated():
    require_local_proof(synthetic=True)
    desk.gate()
    if connection.vendor != "postgresql":
        raise RuntimeError("PostgreSQL is required")
    name = "test_driver_attention_demo_" + uuid4().hex[:16]
    connection.settings_dict["TEST"]["NAME"] = name
    runner = DiscoverRunner(interactive=False, verbosity=0, keepdb=False)
    state = runner.setup_databases()
    try:
        if connection.settings_dict["NAME"] != name:
            raise RuntimeError("Unexpected non-isolated demonstration database")
        with override_settings(MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
                MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_MODEL_PROVIDER="nanogpt",
                MACRO_MODEL_API_KEY="fictional-unused-key", SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch.object(analysis, "create_provider", side_effect=AssertionError("Real providers forbidden")):
            result = demonstrate()
    finally:
        connections.close_all()
        teardown(runner, state, name)
    result["database_isolation"] = {"temporary_database": name, "dropped_after_trace": True,
        "existing_trader_records_used": False, "teardown_statement_timeout_ms": 60_000}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite an existing trace")
    result = isolated()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Saved fictional driver-attention API trace. Temporary database dropped; real model/network calls: 0.")
