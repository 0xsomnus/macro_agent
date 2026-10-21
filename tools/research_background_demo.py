"""Recorded background restart and budget proof in an isolated PostgreSQL database."""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
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

from macro_agent.api.research_job_serializers import ResearchBackgroundResponseSerializer
from macro_agent.api.tests.test_investigation_api import EXACT, MODEL, RecordedResearchProvider, recorded_discovery
from macro_agent.desk import investigation, research_jobs, search_budget
from macro_agent.monitoring import capture, gdelt_research
from macro_agent.monitoring.gates import require_local_proof
from macro_agent.monitoring.models import CaptureOutcome
from macro_agent.monitoring.sources import SourceError
from macro_agent.theses import compilation

from question_research_demo import no_implicit_actions, teardown


class RecordedInterruption(RuntimeError):
    pass


def demonstrate():
    actor = get_user_model().objects.create_user(username="fictional-background-owner", password="recorded-password")
    operator = get_user_model().objects.create_user(username="fictional-budget-reviewer", is_staff=True)
    client, provider = Client(enforce_csrf_checks=True), RecordedResearchProvider()
    at = timezone.now()
    exchanges = []

    def post(path, body):
        csrf = client.get("/api/v1/session/").json()["csrf_token"]
        response = client.post(path, json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
        assert response.status_code == 200, (response.status_code, response.json())
        return response.json()

    def get(path):
        response = client.get(path)
        assert response.status_code == 200, (response.status_code, response.json())
        return response.json()

    def discover(query, *, clock, policy_version):
        exchanges.append({"query": query, "at": clock().isoformat()})
        if len(exchanges) == 1:
            raise SourceError("rate_limited", retry_after_seconds=40)
        recorded = recorded_discovery(query, clock=clock)
        return gdelt_research.parse_metadata(json.dumps({"articles": [
            row["metadata"] for row in recorded.metadata["candidates"]]}).encode(),
            query=query, received_at=clock(), policy_version=policy_version)

    post("/api/v1/session/login/", {"username": actor.username, "password": "recorded-password"})
    with ExitStack() as stack:
        for module, names in ((investigation, ("start_research", "get_research")),
                              (research_jobs, ("enroll", "inspect_job", "revoke"))):
            for name in names:
                original = getattr(module, name)
                def call(*args, _original=original, **kwargs):
                    kwargs["clock"] = lambda: at
                    return _original(*args, **kwargs)
                stack.enter_context(patch.object(module, name, side_effect=call))
        for module in (investigation, compilation):
            stack.enter_context(patch.object(module, "create_provider", return_value=provider))
        stack.enter_context(patch.object(gdelt_research, "discover", side_effect=discover))
        initial = post("/api/v1/research/", {"command_id": str(uuid4()), "exact_question": EXACT,
            "provider_id": "nanogpt", "model_id": MODEL, "source_recovery": True})
        run_id, owner_id = initial["research"]["id"], str(actor.pk)
        original_plan = deepcopy(initial["research"]["plan"])
        assert initial["research"]["status"] == "waiting_source"
        # This fictional accounting exercise is independent of free GDELT calls.
        # Recording a bounded price does not configure an actual source/provider.
        price = search_budget.record_price_contract(str(operator.pk), {
            "schema_version": "search-request-price-v1", "provider_id": "recorded-search",
            "currency": "USD", "billing_basis": "per_request_upper_bound",
            "maximum_charge_microusd": 100_000,
            "pricing_reference": "https://example.invalid/recorded-price",
            "pricing_evidence_digest": "a" * 64}, clock=lambda: at)
        call_id = str(uuid4())
        reservation = search_budget.reserve_search(owner_id, run_id, call_id, price.pk, clock=lambda: at)
        try:
            search_budget.reserve_search(owner_id, run_id, str(uuid4()), price.pk, clock=lambda: at)
        except search_budget.SearchBudgetExhausted:
            pass
        else:
            raise AssertionError("A second reservation must exceed the investigation ceiling")
        consent = {"command_id": str(uuid4()), "expected_request_digest": initial["research"]["request_digest"]}
        base = f"/api/v1/research/{run_id}/background/"
        enrolled = post(base, consent)
        assert post(base, consent)["replayed"]
        at += timedelta(seconds=39)
        early = research_jobs.run_tick(owner_id, run_id, clock=lambda: at)
        assert (provider.calls, len(exchanges)) == (1, 1)
        at += timedelta(seconds=1)
        with patch.object(capture, "observe_capture", side_effect=RecordedInterruption()):
            try:
                research_jobs.run_tick(owner_id, run_id, clock=lambda: at)
            except RecordedInterruption:
                pass
            else:
                raise AssertionError("Expected interruption after committed source capture")
        assert CaptureOutcome.objects.filter(status="captured").count() == 1
        interrupted = get(base)
        old_token = interrupted["job"]["active_token"]
        connections.close_all()
        at += timedelta(seconds=181)
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_ENABLE_RESEARCH_BACKGROUND=False,
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            keyless = get(base)
            saved_hold = search_budget.reserve_search(owner_id, run_id, call_id, price.pk, clock=lambda: at)
        assert saved_hold["replayed"] and saved_hold["held_microusd"] == 100_000
        with patch.object(gdelt_research, "discover", side_effect=AssertionError("Retained capture must be adopted")):
            completed_job = research_jobs.run_tick(owner_id, run_id, clock=lambda: at)
        final = get(f"/api/v1/research/{run_id}/")
        assert completed_job["job"]["status"] == "completed", completed_job
        assert final["research"]["status"] == "compiled"
        assert final["research"]["plan"] == original_plan
        assert (provider.calls, len(exchanges)) == (2, 2)
        retained = get(base)
        serializer = ResearchBackgroundResponseSerializer(data=retained)
        assert serializer.is_valid(), serializer.errors
        kinds = [item["kind"] for lease in retained["job"]["leases"] for item in lease["admissions"]]
        assert sorted(kinds) == ["compilation", "source"]
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            replay = post(base, consent)
        assert replay["job"] == retained["job"] and replay["replayed"]
    assert all(value == 0 for value in no_implicit_actions().values())
    return {"scope": "Recorded source-only wait, background capture restart and separate search-accounting proof",
        "initial_research": initial, "background_enrollment": enrolled, "early_tick": early,
        "interrupted_job": interrupted, "keyless_inspection": keyless, "old_worker_token": old_token,
        "completed_job": retained, "completed_research": final,
        "fictional_accounting": {"reservation": reservation, "recovered_reservation": saved_hold,
            "second_reservation_blocked": True, "real_charge_usd": "0",
            "note": "Standalone recorded reservation; GDELT remains free and no paid provider is connected."},
        "recorded_model_calls": provider.calls, "recorded_source_exchanges": exchanges,
        "real_model_calls": 0, "real_source_calls": 0, "real_model_spend_usd": "0",
        "no_implicit_actions": no_implicit_actions(),
        "limits": ["Application exception and closed connections, not an operating-system crash.",
            "No paid search provider, source rights, live acquisition or analytical quality is established.",
            "Fictional maximum reservation is not a measured provider charge; reported model charges remain unknown."]}


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
            MACRO_ENABLE_RESEARCH_BACKGROUND=True, MACRO_MODEL_PROVIDER="nanogpt",
            MACRO_MODEL_API_KEY="recorded-unused-key", SETTINGS_MODULE="macro_agent.web.local_settings",
            PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]):
            result = demonstrate()
    finally:
        connections.close_all()
        teardown(runner, state, name)
    result["database_isolation"] = {"temporary_database": name,
        "dropped_after_trace": True, "existing_trader_records_used": False}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    if options.output.exists():
        parser.error("Refusing to overwrite a saved trace")
    value = isolated()
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print("Saved recorded background recovery and budget trace. Real model/source calls: 0. Temporary database removed.")
