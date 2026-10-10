"""Synthetic PostgreSQL trace with recorded inference and controlled time.

Run with the explicit local database/fixture gates. This creates immutable
fictional history under a fresh account, then disables that account. It never
contacts a model or news service and does not activate an unattended watch.
"""

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
from django.test import override_settings
from django.utils import timezone

from macro_agent.desk import service as desk
from macro_agent.desk.models import DailyReview
from macro_agent.monitoring import capture, news_context, runner
from macro_agent.monitoring.models import NewsAnalysisResult, SourceState
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.positions import service as positions
from macro_agent.scheduling import service as schedule
from macro_agent.theses import service as theses


class Crash(BaseException):
    pass


class RecordedProvider:
    calls = 0
    catalog_calls = 0

    def list_models(self):
        assert not connection.in_atomic_block
        self.catalog_calls += 1
        return {"fetched_at": timezone.now().isoformat(), "models": [{"id": "recorded/desk",
            "name": "Fictional recorded model", "context_length": 32768,
            "input_price_usd_per_million": None, "output_price_usd_per_million": None,
            "capabilities": {"chat_completions": True}}]}

    def complete(self, model_id, messages):
        assert not connection.in_atomic_block
        self.calls += 1
        context = json.loads(messages[1]["content"])
        document = json.loads((ROOT / "fixtures/news_analysis_response.json").read_text())
        document["attributed_facts"][0]["source_revision_id"] = context["source"]["revision_id"]
        ids = [row["position_id"] for row in context["positions"] if row["status"] == "open"]
        document["trade_route"]["position_ids"] = ids
        document["hypotheses"][0]["position_ids"] = ids
        return {"content": json.dumps(document), "reported_model": model_id,
            "provider_request_id": "fictional-recorded-desk-request",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "reported_cost_usd": None, "finish_reason": "stop", "latency_ms": 1}


def demonstrate():
    runner.gate()
    from macro_agent.monitoring.gates import require_local_proof
    require_local_proof(synthetic=True)
    user = get_user_model().objects.create_user(username="desk-trace-" + uuid4().hex, password=None)
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
        source = "fixture-desk-trace-" + uuid4().hex[:8]
        contract = {"kind": "fictional_fixture", "label": "Fictional desk restart trace",
                    "coverage": "bounded_snapshot"}
        quote = ("The fictional central bank cut its policy rate and opened a temporary "
                 "liquidity facility following reports of funding stress.")
        def batch(native="report-1", title="Fictional policy and funding announcement"):
            item = SourceItem(native, title, "https://example.invalid/desk-report", at - timedelta(days=1), quote)
            return SourceBatch((item,), at, "bounded_snapshot", False, sha256(b"fictional transport").hexdigest())
        capture.capture(source, contract, batch, clock=clock)
        at += timedelta(seconds=1)
        try:
            capture.capture(source, contract, lambda: batch("report-2"), clock=clock,
                after_commit=lambda: (_ for _ in ()).throw(Crash()))
        except Crash:
            pass
        preview = runner.enrollment_preview(actor, thesis["id"])
        cutoff = (at + timedelta(hours=1)).replace(second=0, microsecond=0)
        config = {"schema_version": "internal-desk-watch-v1",
            "approval_id": preview["thesis"]["approval_id"],
            "exposure_digest": preview["thesis"]["exposure_digest"],
            "sources": [{"source_id": source, "contract_digest": SourceState.objects.get(pk=source).contract_digest}],
            "provider": "nanogpt", "model_id": "recorded/desk",
            "model_configuration": runner.analysis.model_configuration("nanogpt"),
            "capture_interval_seconds": 60, "analysis_interval_seconds": 60, "lease_seconds": 30,
            "timezone": "UTC", "daily_time": cutoff.strftime("%H:%M"),
            "daily_start_date": cutoff.date().isoformat(), "daily_backlog_limit": 8,
            "context_bounds": {"reports": 100, "analyses": 100, "exposure_versions": 200,
                "issues": 100, "source_contracts": 16, "encoded_bytes": 1000000},
            "allowances": {"window_seconds": 604800, "analysis_dispatches": 1,
                "inflight_slots": 1, "unresolved_slots": 1}}
        watch = schedule.configure_watch(actor, thesis["id"], str(uuid4()), 0, config, clock=clock)
        provider = RecordedProvider()
        def tick(role):
            return runner.run_tick(actor, watch["watch_id"], role, loaders={source: batch},
                                   provider=provider, clock=clock)
        connections.close_all()
        recovered_capture = tick("capture")
        try:
            with patch.object(schedule, "complete_slot", side_effect=Crash):
                tick("analysis")
        except Crash:
            pass
        assert NewsAnalysisResult.objects.filter(attempt__owner=user).count() == 1
        at += timedelta(seconds=31)
        connections.close_all()
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            recovered_analysis = tick("analysis")
        at = cutoff + timedelta(hours=1)
        late = tick("analysis")
        first = DailyReview.objects.get(owner=user)
        original = desk.inspect_review(actor, str(first.pk), clock=clock)
        tick("analysis")
        assert DailyReview.objects.filter(owner=user).count() == 1
        at += timedelta(days=1)
        second = tick("analysis")
        later = DailyReview.objects.filter(owner=user).order_by("-cutoff").first()
        assert later.context.predecessor_id == first.context_id
        at += timedelta(seconds=1)
        capture.capture(source, contract, lambda: batch(title="Corrected fictional policy headline"), clock=clock)
        corrected = desk.inspect_review(actor, str(first.pk), clock=clock)
        assert original["review"] == corrected["review"]
        assert corrected["current_disposition"]["status"] == "stale"
        assert provider.calls == 1
        return {"scope": "fictional PostgreSQL trace with controlled clock and recorded model adapter",
            "configuration_values": "demonstration only, not operating defaults",
            "watch": watch, "capture_restart": recovered_capture,
            "analysis_result_restart_without_key": recovered_analysis,
            "late_daily_tick": late, "second_daily_tick": second,
            "original_review": original, "after_source_correction": corrected,
            "inspection": schedule.inspect_watch(actor, watch["watch_id"]),
            "recorded_model_calls": provider.calls, "recorded_catalogue_calls": provider.catalog_calls,
            "real_model_calls": 0, "real_network_calls": 0, "real_model_spend_usd": "0",
            "compute_storage_cost": "not measured", "account_disabled_after_trace": True,
            "limits": ["No live analytical quality or week-long process supervision proof.",
                "No cumulative LLM macro context, daily publication or external delivery.",
                "Postcommit witnesses are observations, not exact durable commit times."]}
    finally:
        user.is_active = False
        user.save(update_fields=("is_active",))
        connections.close_all()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite an existing trace")
    with override_settings(MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="recorded-only",
                           SETTINGS_MODULE="macro_agent.web.local_settings"):
        result = demonstrate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Saved fictional trace. Real network/model calls: 0. Temporary account disabled.")
