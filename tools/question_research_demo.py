"""Recorded question-led research through the session/CSRF API in PostgreSQL.

The disposable laboratory records a rough question, automatic named discovery,
capture recovery and sourced proposals. All model and discovery responses are
fictional. It never accesses existing trader records or makes real API calls.
"""

import argparse
from contextlib import contextmanager, ExitStack
from copy import deepcopy
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

from macro_agent.api.investigation_serializers import ResearchRunResponseSerializer
from macro_agent.api.tests.test_investigation_api import (
    EXACT, MODEL, RecordedResearchProvider, recorded_discovery,
)
from macro_agent.desk import investigation
from macro_agent.desk.investigation_models import (
    ResearchDiscoveryReceipt, ResearchDiscoveryResult, ResearchPlanAttempt, ResearchRun,
)
from macro_agent.monitoring import capture, gdelt_research
from macro_agent.monitoring.gates import require_local_proof
from macro_agent.monitoring.models import CaptureAttempt, CaptureOutcome, DurableObservation, SourceRevision
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.positions.models import PositionRecord
from macro_agent.scheduling.models import WatchRecord
from macro_agent.theses import compilation
from macro_agent.theses.models import ApprovalRecord, CompilationAttempt


@contextmanager
def cleanup_cursor(open_cursor):
    """The DROP timeout belongs only to this temporary maintenance session."""
    with open_cursor() as cursor:
        cursor.execute("SET statement_timeout = '60000ms'")
        yield cursor


def teardown(runner, state, name):
    """Drop this generated database without terminating another session."""
    if not name.startswith("test_question_research_demo_"):
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


class InterruptedAfterCapture(RuntimeError):
    """A process interruption boundary, not an operating-system crash."""


COUNTER_QUERY = "fictional helium replacement supply offsets"


class ContextResearchProvider(RecordedResearchProvider):
    """Record one supporting question and one separately empty counter search."""

    def __init__(self):
        super().__init__()
        self.compilation_context = None

    def complete(self, model_id, messages):
        supplied = json.loads(messages[1]["content"])
        response = super().complete(model_id, messages)
        if "exact_question" in supplied:
            document = json.loads(response["content"])
            document["questions"].append({"question_id": "offsets",
                "question": "Could replacement supply offset this fictional disruption?",
                "why_material": "Replacement supply could undermine the proposed scarcity mechanism.",
                "evidence_to_seek": "Attributed evidence about replacement gas supply.",
                "counter_evidence_to_seek": "Evidence that replacement capacity is unavailable.",
                "query": COUNTER_QUERY})
            response["content"] = json.dumps(document)
        else:
            self.compilation_context = supplied
        return response


def no_implicit_actions():
    return {"watches": WatchRecord.objects.count(), "approvals": ApprovalRecord.objects.count(),
        "positions": PositionRecord.objects.count(), "current_assessments": CurrentAssessment.objects.count(),
        "notification_intents": NotificationIntent.objects.count()}


def demonstrate():
    user = get_user_model().objects.create_user(username="fictional-question-research",
        password="fictional-local-password")
    client = Client(enforce_csrf_checks=True)

    def post(path, body):
        token = client.get("/api/v1/session/").json()["csrf_token"]
        response = client.post(path, json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        if response.status_code != 200:
            raise AssertionError((path, response.status_code, response.json()))
        return response.json()

    def get(path):
        response = client.get(path)
        if response.status_code != 200:
            raise AssertionError((path, response.status_code, response.json()))
        return response.json()

    post("/api/v1/session/login/", {"username": user.username, "password": "fictional-local-password"})
    provider = ContextResearchProvider()
    queries = []

    def discovery(query, *, clock):
        queries.append(query)
        if query == COUNTER_QUERY:
            return gdelt_research.parse_metadata(b'{"articles":[]}',
                query=query, received_at=clock())
        # Reuse the API test's fictional article shape and expand its bounded
        # result set so the trace includes the explicitly excluded fifth row.
        fixture = recorded_discovery(query, clock=clock)
        first = fixture.metadata["candidates"][0]["metadata"]
        articles = []
        for index in range(5):
            article = deepcopy(first)
            article["url"] += "/candidate-" + str(index)
            article["title"] += " [fictional candidate " + str(index + 1) + "]"
            articles.append(article)
        return gdelt_research.parse_metadata(json.dumps({"articles": articles}).encode(),
            query=query, received_at=clock())

    body = {"command_id": str(uuid4()), "exact_question": EXACT,
            "provider_id": "nanogpt", "model_id": MODEL}
    with patch.object(investigation, "create_provider", return_value=provider), \
            patch.object(compilation, "create_provider", return_value=provider), \
            patch.object(gdelt_research, "discover", side_effect=discovery):
        with patch.object(capture, "observe_capture",
                side_effect=InterruptedAfterCapture("Recorded interruption after capture commit")):
            try:
                post("/api/v1/research/", body)
            except InterruptedAfterCapture:
                pass
            else:
                raise AssertionError("The intended capture interruption was not exercised")
        assert provider.calls == 1 and len(queries) == 1
        assert ResearchPlanAttempt.objects.count() == 1
        assert ResearchDiscoveryReceipt.objects.count() == 1
        assert CaptureOutcome.objects.filter(status="captured").count() == 1
        assert SourceRevision.objects.count() == 4 and DurableObservation.objects.count() == 0
        assert not ResearchDiscoveryResult.objects.exists() and not CompilationAttempt.objects.exists()
        interrupted = get(f"/api/v1/research-commands/{body['command_id']}/")
        run_id = interrupted["research"]["id"]
        assert interrupted["research"]["status"] == "discovering"
        query = interrupted["research"]["plan"]["document"]["questions"][0]["query"]
        assert queries == [query]
        assert interrupted["research"]["exact_question"] == EXACT
        connections.close_all()
        recovered_before_continue = get(f"/api/v1/research/{run_id}/")
        assert recovered_before_continue["research"]["plan"] == interrupted["research"]["plan"]
        def remaining_discovery(next_query, *, clock):
            if next_query == query:
                raise AssertionError("Captured search cannot be fetched twice")
            return discovery(next_query, clock=clock)
        with patch.object(gdelt_research, "discover", side_effect=remaining_discovery):
            completed = post(f"/api/v1/research/{run_id}/continue/", {})
    research = completed["research"]
    assert research["status"] == "compiled", completed
    serializer = ResearchRunResponseSerializer(data=completed)
    assert serializer.is_valid(), serializer.errors
    assert provider.calls == 2 and queries == [query, COUNTER_QUERY]
    assert provider.catalog_calls == 2
    assert SourceRevision.objects.count() == 4 and DurableObservation.objects.count() == 4
    assert CaptureAttempt.objects.count() == 2
    assert research["exact_question"] == EXACT
    assert research["compilation"]["thesis"]["draft"]["text_version"]["exact_text"] == EXACT
    assert research["compilation"]["compilation"]["document"]["interpretation"]["drivers"] == []
    selection = research["discoveries"][0]["metadata"]
    assert selection["query"] == query and selection["returned_candidate_count"] == 5
    assert selection["selected_count"] == 4 and selection["candidate_cap_reached"] is True
    assert selection["candidates"][-1]["selected"] is False
    assert selection["candidates"][-1]["exclusion_reason"] == "explicit_selection_limit"
    packet = research["compilation"]["compilation"]["evidence_context"]["content"]
    workflow = packet["question_research"]
    assert packet["schema_version"] == "retained-source-evidence-v2"
    assert provider.compilation_context["evidence"]["question_research"] == workflow
    assert workflow["evidence_depth"] == "headline_metadata_only"
    assert workflow["coverage_complete"] is False
    saturated, empty = workflow["questions"]
    assert saturated["returned_candidate_count"] == 5 and saturated["excluded_count"] == 1
    assert saturated["candidate_cap_reached"] is True
    assert empty["planned_question"]["query"] == COUNTER_QUERY
    assert empty["returned_candidate_count"] == 0 and empty["revision_ids"] == []
    assert empty["selected_count"] == 0 and empty["status"] == "captured"
    assert {revision for item in workflow["questions"] for revision in item["revision_ids"]} == {
        item["revision_id"] for item in packet["reports"]}
    assert all(value is None for value in research["costs"].values())
    assert all(count == 0 for count in no_implicit_actions().values())
    original_counts = no_implicit_actions()
    original_compilation = research["compilation"]["compilation"]
    original_packet = original_compilation["evidence_context"]
    original_document = original_compilation["document"]
    original_plan = research["plan"]
    before_correction_observed_at = original_compilation["evidence_disposition"]["observed_at"]

    # A separate recorded source revision changes observed disposition without
    # changing the user's question, immutable proposal or original evidence.
    connections.close_all()
    revision = SourceRevision.objects.select_related("report__source").get(
        pk=research["discoveries"][0]["revision_ids"][0])
    source = revision.report.source
    corrected_title = "FICTIONAL CORRECTION: the earlier importer-cost report is disputed"
    item = SourceItem(revision.report.native_id, corrected_title, revision.payload["url"],
        None, revision.payload["content"])
    capture.capture(source.pk, source.contract, lambda: SourceBatch((item,), timezone.now(),
        "bounded_snapshot", False, sha256(corrected_title.encode()).hexdigest()))
    connections.close_all()
    with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
            SETTINGS_MODULE="macro_agent.web.local_settings"), \
            patch.object(investigation, "create_provider", side_effect=AssertionError("No recovery model call")), \
            patch.object(compilation, "create_provider", side_effect=AssertionError("No recovery model call")), \
            patch.object(gdelt_research, "discover", side_effect=AssertionError("No recovery search")):
        after_correction = get(f"/api/v1/research/{run_id}/")
        command_recovery = get(f"/api/v1/research-commands/{body['command_id']}/")
        initial_post_retry = post("/api/v1/research/", body)
        continue_after_correction = post(f"/api/v1/research/{run_id}/continue/", {})
    for recovered in (after_correction, command_recovery, initial_post_retry, continue_after_correction):
        record = recovered["research"]
        assert record["status"] == "stale"
        assert record["plan"] == original_plan
        assert record["compilation"]["compilation"]["document"] == original_document
        assert record["compilation"]["compilation"]["evidence_context"] == original_packet
        assert record["compilation"]["compilation"]["status"] == "compiled"
        assert record["compilation"]["compilation"]["evidence_disposition"]["status"] == "stale"
        assert record["compilation"]["thesis"]["draft"]["text_version"]["exact_text"] == EXACT
    assert command_recovery["replayed"] and initial_post_retry["replayed"]
    assert original_counts == no_implicit_actions()
    assert provider.calls == 2 and len(queries) == 2
    assert ResearchRun.objects.count() == 1
    return {"scope": "Fictional rough-question to sourced-proposal session API proof",
        "initial_request": body, "interruption_after_durable_capture": interrupted,
        "read_after_connection_restart": recovered_before_continue,
        "completed_after_explicit_continuation": completed,
        "recovery_after_source_correction_and_key_provider_removal": after_correction,
        "verified_recovery_paths": {"get_by_id": True, "get_by_command": True,
            "initial_post_retry_is_read_only": initial_post_retry["replayed"],
            "explicit_continue_is_read_only_after_correction": True,
            "original_plan_preserved": True, "original_source_packet_preserved": True,
            "original_compilation_document_preserved": True,
            "observed_disposition_before_correction": "current",
            "observed_disposition_after_correction": "stale",
            "observed_at_before_correction": before_correction_observed_at,
            "observed_at_after_correction": after_correction["research"]["compilation"]["compilation"]["evidence_disposition"]["observed_at"]},
        "no_implicit_actions": original_counts,
        "recorded_model_calls": {"planning": 1, "compilation": 1, "total": provider.calls},
        "recorded_discovery_calls": len(queries), "executed_queries": queries,
        "research_context_checks": {"plan_and_all_query_outcomes_reached_compilation": True,
            "saturated_selection_and_empty_counter_search_preserved": True,
            "selected_revision_union_matches_packet": True,
            "context_is_not_trader_intent_or_quotable_source_evidence": True},
        "real_model_calls": 0, "real_network_calls": 0, "real_model_spend_usd": "0",
        "limits": ["All headlines, businesses and reasoning are fictional recordings, not financial research.",
            "The bounded GDELT-shaped selection is metadata only, not article-level evidence or comprehensive source discovery.",
            "A named counter-evidence question does not prove that counter-evidence was adequately researched.",
            "Exact quotations establish attribution, not truth, semantic support, causation or live model usefulness.",
            "Availability, price, valuation, expectations and company exposure remain unverified.",
            "Research creates no monitoring, approval, position, current assessment or notification.",
            "The recovery proof closes database connections and interrupts application execution; it is not an operating-system crash.",
            "Recorded model costs remain unknown. Zero real spending refers only to this fixture demonstration."]}


def isolated():
    require_local_proof(synthetic=True)
    if connection.vendor != "postgresql":
        raise RuntimeError("PostgreSQL is required")
    name = "test_question_research_demo_" + uuid4().hex[:16]
    connection.settings_dict["TEST"]["NAME"] = name
    runner = DiscoverRunner(interactive=False, verbosity=0, keepdb=False)
    state = runner.setup_databases()
    try:
        with override_settings(MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_ENABLE_RESEARCH_DISCOVERY=True,
                MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ENABLE_CONTINUOUS_DESK=True,
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
    print("Saved fictional question research trace. Temporary database dropped; real model/network calls: 0.")
