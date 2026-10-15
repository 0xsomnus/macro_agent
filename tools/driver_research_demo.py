"""Recorded broad research and driver review in a disposable PostgreSQL database.

This laboratory proof intentionally reuses recorded API-test adapters. It makes
no real model or network calls and never configures a watch or paper position.
"""

import argparse
from contextlib import contextmanager, ExitStack
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
from django.test import Client, override_settings
from django.test.runner import DiscoverRunner
from django.utils import timezone

from macro_agent.api.tests.test_compilation_api import MODEL_ID, RecordedModel
from macro_agent.api.tests.test_driver_research_api import (
    EXACT, DRIVER, RecordedDriverResearchModel, RecordedDriverSynthesisModel, assessed_drivers,
)
from macro_agent.desk import service as desk, synthesis
from macro_agent.domain import news_analysis
from macro_agent.domain.daily_review import DailyReviewLimits
from macro_agent.domain.models import canonical_json
from macro_agent.monitoring import analysis, capture
from macro_agent.monitoring.gates import require_local_proof
from macro_agent.monitoring.models import SourceRevision
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.positions.models import PositionRecord
from macro_agent.scheduling.models import WatchRecord
from macro_agent.theses import compilation
from macro_agent.theses.models import ApprovalRecord


@contextmanager
def cleanup_cursor(open_cursor):
    """Bound the temporary DROP separately from ordinary application queries.

    PostgreSQL may wait for a global checkpoint when dropping a test database.
    Concurrent suites can exceed the application's shorter statement limit.
    This setting belongs only to the short-lived maintenance connection.
    """
    with open_cursor() as cursor:
        cursor.execute("SET statement_timeout = '60000ms'")
        yield cursor


def teardown(runner, state, name):
    """Drop only this invocation's generated database, without killing sessions."""
    if not name.startswith("test_driver_research_demo_"):
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


class RecordedNoTradeNewsModel(RecordedModel):
    def complete(self, model_id, messages):
        metadata = super().complete(model_id, messages)
        context = json.loads(messages[1]["content"])
        source = context["source"]
        metadata["content"] = canonical_json({
            "schema_version": news_analysis.DRIVER_SCHEMA_VERSION,
            "attributed_facts": [{"fact_id": "cost-claim", "source_revision_id": source["revision_id"],
                "field": "title", "exact_quote": source["title"]}],
            "thesis_route": {"status": "review_needed", "fact_ids": ["cost-claim"],
                "explanation": "The fictional cost report warrants reviewing the proposed mechanism."},
            "trade_route": {"status": "not_identified", "fact_ids": [], "position_ids": [],
                "explanation": "No paper trade is attached."},
            "hypotheses": [{"hypothesis_id": "input-costs", "fact_ids": ["cost-claim"],
                "position_ids": [], "explanation": "An importer could face higher costs.",
                "transmission": "Replacement costs could compress margins.", "horizon": None,
                "assumptions": ["Costs cannot immediately be passed through."],
                "uncertainty": "Source truth and economic transmission are unverified.",
                "counter_case": "An importer might pass costs through or have hedges.",
                "signposts": ["Company cost and hedging disclosures."]}],
            "trader_questions": ["Would an adverse importer relationship change your research intent?"],
            "driver_assessment": assessed_drivers(context["approved_thesis"]["drivers"], "cost-claim"),
        })
        return metadata


def demonstrate():
    user = get_user_model().objects.create_user(
        username="fictional-helionite-research", password="recorded-only-password")
    client = Client(enforce_csrf_checks=True)

    def post(path, body, expected=200):
        token = client.get("/api/v1/session/").json()["csrf_token"]
        response = client.post(path, json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        if response.status_code != expected:
            raise AssertionError((path, response.status_code, response.json()))
        return response.json()

    post("/api/v1/session/login/", {"username": user.username, "password": "recorded-only-password"})
    source_id = "fixture-driver-research-trace"
    contract = {"kind": "fictional_fixture", "label": "Fictional helionite report", "coverage": "bounded_snapshot"}

    def capture_report(title):
        at = timezone.now()
        item = SourceItem("helionite-report", title, "https://example.invalid/helionite",
            at - timedelta(days=1), "Synthetic report: helionite importers face higher replacement costs.")
        return capture.capture(source_id, contract, lambda: SourceBatch((item,), timezone.now(),
            "bounded_snapshot", False, sha256(title.encode()).hexdigest()))

    capture_report("Fictional helionite importers report higher replacement costs")
    draft = post("/api/v1/theses/", {"command_id": str(uuid4()), "text": EXACT,
        "interpretation": {"drivers": [], "horizon": None, "invalidation_signposts": []}}, 201)["thesis"]
    path = f"/api/v1/theses/{draft['id']}"
    revision = SourceRevision.objects.get(report__source_id=source_id)
    packet = post(path + "/evidence/", {"command_id": str(uuid4()), "revision_ids": [str(revision.pk)]})
    compiler, news, morning = RecordedDriverResearchModel(), RecordedNoTradeNewsModel(), RecordedDriverSynthesisModel()
    with patch.object(compilation, "create_provider", return_value=compiler), \
            patch.object(analysis, "create_provider", return_value=news), \
            patch.object(synthesis, "create_provider", return_value=morning):
        compile_command = {"command_id": str(uuid4()), "expected_revision": draft["revision"],
            "provider_id": "nanogpt", "model_id": MODEL_ID,
            "evidence_context_id": packet["evidence"]["id"], "driver_review": True}
        compiled = post(path + "/compile/", compile_command)
        assert compiled["compilation"]["status"] == "compiled", compiled
        no_implicit_actions = {"watches": WatchRecord.objects.count(), "positions": PositionRecord.objects.count(),
            "approvals": ApprovalRecord.objects.count(), "notification_intents": NotificationIntent.objects.count()}
        assert no_implicit_actions == {"watches": 0, "positions": 0, "approvals": 0, "notification_intents": 0}
        proposed = compiled["thesis"]
        text, meaning = proposed["draft"]["text_version"], proposed["draft"]["interpretation"]
        approved = post(path + "/approvals/", {"command_id": str(uuid4()),
            "expected_revision": proposed["revision"], "thesis_version_id": text["id"],
            "text_digest": text["text_digest"], "interpretation_version_id": meaning["id"],
            "interpretation_digest": meaning["digest"]})["thesis"]
        assert approved["approved"]["interpretation"]["drivers"] == [DRIVER]
        context_response = client.get(path + "/news-context/")
        assert context_response.status_code == 200, context_response.content
        context = context_response.json()
        news_command = {"command_id": str(uuid4()), "expected_approval_id": approved["approved"]["approval"]["id"],
            "expected_exposure_digest": context["exposure_digest"], "source_id": source_id,
            "provider_id": "nanogpt", "model_id": MODEL_ID, "driver_review": True}
        analysed = post(path + "/analyse-next/", news_command)
        assert analysed["analysis"]["status"] == "analysed", analysed
        actor = str(user.pk)
        desk.observe_analysis_results(actor, draft["id"], [source_id], 100)
        cutoff = timezone.now()
        retained = desk.create_review(actor, draft["id"], str(uuid4()), cutoff - timedelta(days=1), cutoff,
            [source_id], DailyReviewLimits(100, 100, 200, 300, 16, 2_000_000))
        review = retained["review"]
        synth_command = {"command_id": str(uuid4()), "expected_review_digest": review["digest"],
            "provider_id": "nanogpt", "model_id": MODEL_ID, "driver_review": True}
        fresh = post(f"/api/v1/daily-reviews/{review['id']}/synthesise/", synth_command)
        assert fresh["synthesis"]["status"] == "synthesised", fresh
    connections.close_all()
    capture_report("Fictional correction: importer replacement-cost claim is disputed")
    with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
            SETTINGS_MODULE="macro_agent.web.local_settings"), \
            patch.object(compilation, "create_provider", side_effect=AssertionError("No recovery provider")), \
            patch.object(analysis, "create_provider", side_effect=AssertionError("No recovery provider")), \
            patch.object(synthesis, "create_provider", side_effect=AssertionError("No recovery provider")):
        recovered_compilation = client.get(path + f"/compilation-commands/{compile_command['command_id']}/").json()
        recovered_news = client.get(path + f"/news-commands/{news_command['command_id']}/").json()
        recovered_morning = client.get(
            f"/api/v1/daily-reviews/{review['id']}/synthesis-commands/{synth_command['command_id']}/").json()
    assert recovered_compilation["compilation"]["document"] == compiled["compilation"]["document"]
    assert recovered_compilation["compilation"]["evidence_disposition"]["status"] == "stale"
    assert recovered_news["analysis"]["document"] == analysed["analysis"]["document"]
    assert recovered_news["analysis"]["current_disposition"] == "stale"
    assert recovered_morning["synthesis"] == fresh["synthesis"]
    assert recovered_morning["current_disposition"]["status"] == "stale"
    retained_thesis = client.get(path + "/").json()
    assert retained_thesis["approved"]["text_version"]["exact_text"] == EXACT
    assert retained_thesis["approved"]["interpretation"]["drivers"] == [DRIVER]
    assert retained_thesis["approved"]["approval"] == approved["approved"]["approval"]
    assert (WatchRecord.objects.count(), PositionRecord.objects.count(),
        CurrentAssessment.objects.count(), NotificationIntent.objects.count()) == (0, 0, 0, 0)
    return {"scope": "Fictional unfamiliar-asset research and driver-review API proof",
        "evidence": packet, "research_compilation": compiled,
        "no_implicit_actions_after_research": no_implicit_actions, "explicit_approval": approved,
        "explicit_news_review_without_trade": analysed, "explicit_retained_daily_review": retained,
        "explicit_morning_synthesis": fresh,
        "recovery_after_connection_restart_and_source_correction": {
            "compilation": recovered_compilation, "news": recovered_news, "morning": recovered_morning,
            "approved_thesis": retained_thesis},
        "recorded_model_calls": {"compilation": compiler.completion_calls,
            "news": news.completion_calls, "morning": morning.completion_calls},
        "real_model_calls": 0, "real_network_calls": 0, "real_model_spend_usd": "0",
        "limits": ["Helionite and its report are fictional, not financial research.",
            "Quotes establish retained attribution, not source truth, causation or useful live model reasoning.",
            "Research does not initiate monitoring, attach a position, or approve trader intent.",
            "Separate explicit commands approve intent and request news and morning reviews in this proof.",
            "Driver attention is an analytical recommendation; there is no live alert publication or external delivery.",
            "No verified prices, prospective entry assessment or instrument availability are supplied.",
            "Reported model costs remain unknown; fixture catalogue prices are estimates only.",
            "Connection restart tests recovery receipts, not an operating-system crash."]}


def isolated():
    require_local_proof(synthetic=True)
    desk.gate()
    if connection.vendor != "postgresql":
        raise RuntimeError("PostgreSQL is required")
    name = "test_driver_research_demo_" + uuid4().hex[:16]
    connection.settings_dict["TEST"]["NAME"] = name
    runner = DiscoverRunner(interactive=False, verbosity=0, keepdb=False)
    state = runner.setup_databases()
    try:
        with override_settings(MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
                MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="recorded-unused-key",
                PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
                SETTINGS_MODULE="macro_agent.web.local_settings"):
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
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("Saved fictional driver research trace. Temporary database dropped; real model/network calls: 0.")
