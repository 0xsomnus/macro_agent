"""Recorded cumulative-context proof in a unique, temporary PostgreSQL database.

Explicit local development, monitoring, news, continuous-desk and synthetic
gates are required. The temporary database is created, migrated and dropped.
No existing account/watch is used and no model/news service is contacted.
"""

import argparse
from copy import deepcopy
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

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import override_settings
from django.test.runner import DiscoverRunner
from django.utils import timezone

from macro_agent.domain.cumulative_news import CUMULATIVE_SCHEMA_VERSION
from macro_agent.desk.models import DailyReview
from macro_agent.monitoring import analysis, capture, runner
from macro_agent.monitoring.gates import require_local_proof
from macro_agent.monitoring.models import NewsAnalysisAttempt, NewsAnalysisResult, SourceState
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.positions import service as positions
from macro_agent.scheduling import service as schedule
from macro_agent.scheduling.models import AnalysisDispatch
from macro_agent.theses import service as theses


MODEL = "recorded/cumulative-desk"
FUNDING = "Fictional lenders reported persistent funding stress and tighter credit conditions."
EASING = ("The fictional central bank cut its policy rate and opened a temporary "
          "liquidity facility following reports of funding stress.")


class Crash(BaseException):
    """Simulate process loss after immutable result persistence."""


class RecordedProvider:
    def __init__(self):
        self.calls = 0
        self.catalog_calls = 0

    def list_models(self):
        assert not connection.in_atomic_block
        self.catalog_calls += 1
        return {"fetched_at": timezone.now().isoformat(), "models": [{"id": MODEL,
            "name": "Recorded fictional cumulative model", "context_length": 32768,
            "input_price_usd_per_million": None, "output_price_usd_per_million": None,
            "capabilities": {"chat_completions": True}}]}

    def complete(self, model_id, messages):
        assert not connection.in_atomic_block
        self.calls += 1
        context = json.loads(messages[1]["content"])
        prior = context["cumulative"]["analyses"]
        ids = [row["position_id"] for row in context["positions"] if row["status"] == "open"]
        if prior:
            document = json.loads((ROOT / "fixtures/cumulative_news_response.json").read_text(encoding="utf-8"))
            earlier = next(row for row in context["cumulative"]["reports"] if FUNDING in row["content"])
            document["attributed_facts"][1]["source_revision_id"] = earlier["revision_id"]
            document["evidence_comparisons"][0]["prior_analysis_ids"] = [prior[0]["analysis_id"]]
        else:
            document = json.loads((ROOT / "fixtures/news_analysis_response.json").read_text(encoding="utf-8"))
            document["schema_version"] = CUMULATIVE_SCHEMA_VERSION
            document["attributed_facts"][0]["exact_quote"] = FUNDING
            document["evidence_comparisons"] = []
            document["thesis_route"]["explanation"] = (
                "Reported funding stress could obstruct the approved easier-policy transmission mechanism.")
            document["trade_route"]["explanation"] = (
                "Tighter funding could create a nearer-term adverse path for the fictional NQ long.")
            document["hypotheses"][0].update(
                explanation="Unverified hypothesis: persistent funding stress could offset expected policy support.",
                transmission="If tighter funding restrains credit, easier policy may not support activity over the holding period.",
                assumptions=["The fictional funding report is relevant to the trader's expected policy transmission."],
                uncertainty="No verified current regime, market reaction, expectations or leverage data are supplied.",
                counter_case="A subsequent policy response could contain the reported funding constraints.",
                signposts=["Investigate permitted subsequent evidence on funding conditions and policy measures."])
        document["attributed_facts"][0]["source_revision_id"] = context["source"]["revision_id"]
        document["trade_route"]["position_ids"] = ids
        document["hypotheses"][0]["position_ids"] = ids
        return {"content": json.dumps(document), "reported_model": model_id,
            "provider_request_id": "fictional-cumulative-request-" + str(self.calls),
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "reported_cost_usd": None, "finish_reason": "stop", "latency_ms": 1}


def demonstrate():
    runner.gate()
    require_local_proof(synthetic=True)
    assert connection.settings_dict["NAME"].startswith("test_cumulative_context_demo_")
    user = get_user_model().objects.create_user(username="fictional-cumulative-trader", password=None)
    actor = str(user.pk)
    try:
        draft = theses.create_thesis(actor, str(uuid4()), "  Easier policy may support equities.\r\nΔ\r\n",
            {"drivers": ["Easier policy"], "horizon": "medium term",
             "invalidation_signposts": ["Policy transmission fails"]})["thesis"]
        text, meaning = draft["draft"]["text_version"], draft["draft"]["interpretation"]
        thesis = theses.approve_thesis(actor, draft["id"], str(uuid4()), text["id"], text["text_digest"],
            meaning["id"], meaning["digest"], draft["revision"])["thesis"]
        positions.create_position(actor, thesis["id"], str(uuid4()), thesis["approved"]["approval"]["id"],
            {"underlying": "NQ", "direction": "long", "quantity": None, "quantity_unit": None,
             "horizon": None, "product_id": None, "venue": None, "expiry": None, "quote_currency": None})
        at = timezone.now() + timedelta(seconds=1)

        def clock():
            return at

        source = "fixture-cumulative-trace"
        contract = {"kind": "fictional_fixture", "label": "Fictional cumulative context trace",
                    "coverage": "bounded_snapshot"}

        def batch(native, title, content):
            item = SourceItem(native, title, "https://example.invalid/" + native,
                              at - timedelta(days=1), content)
            return SourceBatch((item,), at, "bounded_snapshot", False,
                               sha256(content.encode("utf-8")).hexdigest())

        capture.capture(source, contract, lambda: batch("funding", "Fictional funding constraints", FUNDING), clock=clock)
        preview = runner.enrollment_preview(actor, thesis["id"], cumulative=True)
        daily_at = (at + timedelta(hours=3)).replace(second=0, microsecond=0)
        config = {"schema_version": "internal-desk-watch-v1",
            "approval_id": preview["thesis"]["approval_id"],
            "exposure_digest": preview["thesis"]["exposure_digest"],
            "sources": [{"source_id": source, "contract_digest": SourceState.objects.get(pk=source).contract_digest}],
            "provider": "nanogpt", "model_id": MODEL, "model_configuration": preview["model_configuration"],
            "capture_interval_seconds": 60, "analysis_interval_seconds": 60, "lease_seconds": 30,
            "timezone": "UTC", "daily_time": daily_at.strftime("%H:%M"),
            "daily_start_date": daily_at.date().isoformat(), "daily_backlog_limit": 8,
            "context_bounds": {"reports": 100, "analyses": 100, "exposure_versions": 200,
                "issues": 100, "source_contracts": 16, "encoded_bytes": 1_000_000},
            "allowances": {"window_seconds": 3600, "analysis_dispatches": 2,
                "inflight_slots": 1, "unresolved_slots": 1}}
        watch = schedule.configure_watch(actor, thesis["id"], str(uuid4()), 0, config, clock=clock)
        provider = RecordedProvider()

        def tick():
            return runner.run_tick(actor, watch["watch_id"], "analysis", provider=provider, clock=clock)

        first_tick = tick()
        first_attempt = NewsAnalysisAttempt.objects.get()
        assert NewsAnalysisResult.objects.get().status == "analysed"
        assert not DailyReview.objects.exists()
        at += timedelta(seconds=61)
        capture.capture(source, contract, lambda: batch("easing", "Fictional policy response", EASING), clock=clock)
        try:
            with patch.object(schedule, "complete_slot", side_effect=Crash):
                tick()
        except Crash:
            pass
        second_attempt = NewsAnalysisAttempt.objects.exclude(pk=first_attempt.pk).get()
        second_result = NewsAnalysisResult.objects.get(attempt=second_attempt)
        assert second_result.status == "analysed"
        assert second_result.document["evidence_comparisons"][0]["relationship"] == "offsets"
        assert second_result.document["evidence_comparisons"][0]["prior_analysis_ids"] == [str(first_attempt.pk)]
        assert second_attempt.admission_context.predecessor_id == first_attempt.admission_context_id
        original_context = deepcopy(second_attempt.context)
        before_restart = {"recorded_model_calls": provider.calls, "recorded_catalogue_calls": provider.catalog_calls}
        at += timedelta(seconds=31)
        connections.close_all()
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            with patch.object(analysis, "model_configuration", side_effect=AssertionError("Recovery cannot resolve model configuration")):
                recovered = tick()
        assert recovered["processed"][0]["outcome"]["status"] == "completed"
        assert provider.calls == provider.catalog_calls == 2
        assert not DailyReview.objects.exists()
        second_attempt.refresh_from_db()
        assert second_attempt.context == original_context
        first = analysis.get_analysis(actor, thesis["id"], str(first_attempt.pk), clock=clock)
        second = analysis.get_analysis(actor, thesis["id"], str(second_attempt.pk), clock=clock)
        assert first["analysis"]["current_disposition"] == "current"
        assert second["analysis"]["current_disposition"] == "current"
        return {"scope": "Recorded fictional PostgreSQL cumulative-context trace in a unique temporary database",
            "configuration_values": "demonstration inputs, not operating defaults",
            "approved_thesis": thesis, "reviewed_watch": watch,
            "first_tick": first_tick, "first_analysis": first, "second_analysis": second,
            "context_lineage": {
                "first_context_id": str(first_attempt.admission_context_id),
                "second_context_id": str(second_attempt.admission_context_id),
                "second_predecessor_context_id": str(second_attempt.admission_context.predecessor_id),
                "first_cumulative_digest": first_attempt.context["cumulative"]["digest"],
                "second_cumulative_digest": second_attempt.context["cumulative"]["digest"],
                "first_prompt_context_digest": first_attempt.context_digest,
                "second_prompt_context_digest": second_attempt.context_digest},
            "dispatch_requests": [row.request for row in AnalysisDispatch.objects.order_by("started_at")],
            "before_result_restart": before_restart, "recovery_without_key": recovered,
            "daily_reviews_created": DailyReview.objects.count(),
            "recorded_model_calls": provider.calls, "recorded_catalogue_calls": provider.catalog_calls,
            "real_model_calls": 0, "real_network_calls": 0, "real_model_spend_usd": "0",
            "compute_storage_cost": "not measured", "fictional_account_disabled_after_trace": True,
            "limits": ["Recorded reasoning is fixture content, not live model usefulness.",
                "Complete means the eligible retained selected-source set within explicit bounds, not broad macro coverage.",
                "No current daily publication, external delivery, broker access or unattended live watch.",
                "Controlled times and postcommit witnesses do not establish exact commit timestamps.",
                "This sequential trace does not replace independent database race tests or a supervised weekly pilot."]}
    finally:
        user.is_active = False
        user.save(update_fields=("is_active",))
        connections.close_all()


def isolated_demonstration():
    require_local_proof(synthetic=True)
    runner.gate()
    if connection.vendor != "postgresql":
        raise RuntimeError("The cumulative trace requires PostgreSQL")
    temporary_name = "test_cumulative_context_demo_" + uuid4().hex[:16]
    connection.settings_dict["TEST"]["NAME"] = temporary_name
    test_runner = DiscoverRunner(interactive=False, verbosity=0, keepdb=False)
    database_state = test_runner.setup_databases()
    try:
        with override_settings(MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="recorded-only",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            with patch.object(analysis, "create_provider", side_effect=AssertionError("Real provider forbidden")), \
                 patch.object(runner, "fetch_source", side_effect=AssertionError("Live feed forbidden")):
                result = demonstrate()
    finally:
        test_runner.teardown_databases(database_state)
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
    print("Saved fictional cumulative trace. Temporary database dropped; real network/model calls: 0.")
