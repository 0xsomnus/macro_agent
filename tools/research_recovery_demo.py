"""Fictional rate-limit recovery through the session API and PostgreSQL.

Every source and model response is recorded. No existing trader records, live
source request or paid model call is used. The temporary database is removed.
"""

import argparse
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

from macro_agent.api.investigation_serializers import ResearchRunResponseSerializer
from macro_agent.api.tests.test_investigation_api import EXACT, MODEL, RecordedResearchProvider, recorded_discovery
from macro_agent.desk import investigation
from macro_agent.desk.investigation_models import ResearchDiscoveryResult
from macro_agent.monitoring import capture, gdelt_research
from macro_agent.monitoring.gates import require_local_proof
from macro_agent.monitoring.models import CaptureOutcome
from macro_agent.monitoring.sources import SourceError
from macro_agent.theses import compilation

from question_research_demo import no_implicit_actions, teardown


class RecordedInterruption(RuntimeError):
    pass


def demonstrate():
    actor = get_user_model().objects.create_user(username="fictional-source-recovery",
        password="fictional-recorded-password")
    client = Client(enforce_csrf_checks=True)
    provider = RecordedResearchProvider()
    at = timezone.now()
    source_calls = []

    def post(path, body):
        token = client.get("/api/v1/session/").json()["csrf_token"]
        response = client.post(path, json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        assert response.status_code == 200, (response.status_code, response.json())
        return response.json()

    def get(path):
        response = client.get(path)
        assert response.status_code == 200, (response.status_code, response.json())
        return response.json()

    def discover(query, *, clock, policy_version):
        source_calls.append({"query": query, "at": clock().isoformat(), "policy_version": policy_version})
        if len(source_calls) == 1:
            raise SourceError("rate_limited", retry_after_seconds=40)
        fixture = recorded_discovery(query, clock=clock)
        return gdelt_research.parse_metadata(json.dumps({"articles": [
            item["metadata"] for item in fixture.metadata["candidates"]]}).encode(),
            query=query, received_at=clock(), policy_version=policy_version)

    post("/api/v1/session/login/", {"username": actor.username, "password": "fictional-recorded-password"})
    body = {"command_id": str(uuid4()), "exact_question": EXACT,
        "provider_id": "nanogpt", "model_id": MODEL, "source_recovery": True}
    from contextlib import ExitStack
    with ExitStack() as stack:
        for name in ("start_research", "continue_research", "get_research", "get_research_command"):
            original = getattr(investigation, name)
            def wrapped(*args, _original=original, **kwargs):
                kwargs["clock"] = lambda: at
                return _original(*args, **kwargs)
            stack.enter_context(patch.object(investigation, name, side_effect=wrapped))
        for module in (investigation, compilation):
            stack.enter_context(patch.object(module, "create_provider", return_value=provider))
        stack.enter_context(patch.object(gdelt_research, "discover", side_effect=discover))
        initial = post("/api/v1/research/", body)
        run_id = initial["research"]["id"]
        assert initial["research"]["status"] == "waiting_source"
        assert (provider.calls, len(source_calls)) == (1, 1)
        original_plan = deepcopy(initial["research"]["plan"])
        connections.close_all()
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            recovered = get(f"/api/v1/research/{run_id}/")
            repeated_start = post("/api/v1/research/", body)
        assert recovered["research"]["plan"] == original_plan and repeated_start["replayed"]
        at += timedelta(seconds=39)
        early = post(f"/api/v1/research/{run_id}/continue/", {})
        assert early["research"]["status"] == "waiting_source"
        assert (provider.calls, len(source_calls)) == (1, 1)
        at += timedelta(seconds=1)
        with patch.object(capture, "observe_capture", side_effect=RecordedInterruption()):
            try:
                post(f"/api/v1/research/{run_id}/continue/", {})
            except RecordedInterruption:
                pass
            else:
                raise AssertionError("Expected interruption after durable capture")
        assert CaptureOutcome.objects.filter(status="captured").count() == 1
        assert ResearchDiscoveryResult.objects.filter(status="captured").count() == 0
        assert (provider.calls, len(source_calls)) == (1, 2)
        connections.close_all()
        at += timedelta(seconds=90)
        interrupted = get(f"/api/v1/research/{run_id}/")
        with patch.object(gdelt_research, "discover", side_effect=AssertionError("No second successful GET")):
            final = post(f"/api/v1/research/{run_id}/continue/", {})
        assert final["research"]["status"] == "compiled", final
        validator = ResearchRunResponseSerializer(data=final)
        assert validator.is_valid(), validator.errors
        assert (provider.calls, len(source_calls)) == (2, 2)
        assert final["research"]["plan"] == original_plan
        packet = final["research"]["compilation"]["compilation"]["evidence_context"]["content"]
        assert packet["schema_version"] == "retained-source-evidence-v3"
        attempts = packet["question_research"]["questions"][0]["attempts"]
        assert [item["status"] for item in attempts] == ["failed", "captured"]
        assert attempts[0]["metadata"]["retry_after_seconds"] == 40
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch.object(gdelt_research, "discover", side_effect=AssertionError("Saved state only")):
            finished_retry = post("/api/v1/research/", body)
            finished_continue = post(f"/api/v1/research/{run_id}/continue/", {})
        assert finished_retry["research"]["compilation"] == final["research"]["compilation"]
        assert finished_continue["research"]["compilation"] == final["research"]["compilation"]
    assert all(value == 0 for value in no_implicit_actions().values())
    return {"scope": "Fictional rate-limit, saved-plan and captured-receipt recovery proof",
        "request": body, "after_rate_limit": initial, "keyless_read_after_restart": recovered,
        "before_cooldown_expired": early, "after_captured_response_interruption": interrupted,
        "completed": final, "recorded_source_attempts": source_calls,
        "checks": {"saved_plan_reused": True, "early_continue_makes_no_source_request": True,
            "committed_capture_adopted_beyond_lease": True, "original_failure_retained": True,
            "historical_retries_inert": True},
        "recorded_model_calls": provider.calls, "recorded_source_calls": len(source_calls),
        "real_model_calls": 0, "real_source_calls": 0, "real_model_spend_usd": "0",
        "no_implicit_actions": no_implicit_actions(), "fallback_provider_configured": False,
        "limits": ["Fictional recordings do not prove live GDELT availability or analytical quality.",
            "The interruption uses an application exception and closed connections, not an OS crash.",
            "No alternate source provider is configured or automatically substituted.",
            "Recorded model charges stay unknown; real source/model calls are zero."]}


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
            MACRO_ENABLE_MONITORING_PROOF=True, MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="recorded-unused-key",
            PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
            SETTINGS_MODULE="macro_agent.web.local_settings"):
            value = demonstrate()
    finally:
        connections.close_all()
        teardown(runner, state, name)
    value["database_isolation"] = {"temporary_database": name, "dropped_after_trace": True,
        "existing_trader_records_used": False}
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    if options.output.exists():
        parser.error("Refusing to overwrite a saved trace")
    value = isolated()
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print("Saved fictional source-recovery trace. Real source/model calls: 0. Temporary database removed.")
