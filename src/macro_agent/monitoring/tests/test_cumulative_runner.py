"""Reviewed cumulative runner opt-in, pinned dispatch and inert recovery."""

from copy import deepcopy
from datetime import timedelta
from io import StringIO
import json
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connections, transaction
from django.test import TransactionTestCase, override_settings

from macro_agent.domain.daily_review import DailyReviewLimits
from macro_agent.domain.cumulative_news import CUMULATIVE_SCHEMA_VERSION
from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.desk.models import DailyReview
from macro_agent.monitoring import capture, runner
from macro_agent.monitoring.models import NewsAnalysisAttempt, NewsAnalysisResult, SourceState
from macro_agent.monitoring.tests import test_runner as fixtures
from macro_agent.scheduling import service as schedule
from macro_agent.scheduling.configuration import configuration
from macro_agent.scheduling.models import AnalysisDispatch


class RecordedCumulativeProvider(fixtures.RecordedProvider):
    """Return valid recorded output while retaining the actual model inputs."""

    def __init__(self):
        super().__init__()
        self.contexts = []

    def complete(self, model_id, messages):
        result = super().complete(model_id, messages)
        context = json.loads(messages[1]["content"])
        self.contexts.append(context)
        document = json.loads(result["content"])
        document["schema_version"] = CUMULATIVE_SCHEMA_VERSION
        prior = [item["analysis_id"] for item in context["cumulative"]["analyses"]
                 if item["original_status"] in ("analysed", "stale") and item["document"] is not None]
        document["evidence_comparisons"] = ([{
            "prior_analysis_ids": prior, "fact_ids": ["f1"], "relationship": "unresolved",
            "explanation": "The earlier interpretation remains unresolved against the new fictional report.",
            "uncertainty": "Repeated fictional coverage does not establish independent evidence or a real macro regime.",
        }] if prior else [])
        return {**result, "content": json.dumps(document)}


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class PostgreSQLCumulativeRunnerTests(TransactionTestCase):
    setUp = fixtures.PostgreSQLRunnerTests.setUp
    clock = fixtures.PostgreSQLRunnerTests.clock
    batch = fixtures.PostgreSQLRunnerTests.batch
    tick = fixtures.PostgreSQLRunnerTests.tick
    news_slot = fixtures.PostgreSQLRunnerTests.news_slot

    def enable_cumulative(self, *, extra_source=False):
        current = schedule.current_watch(self.actor, self.watch)
        self.config = deepcopy(current["configuration"])
        self.config["model_configuration"] = runner.analysis.model_configuration("nanogpt", cumulative=True)
        if extra_source:
            contract = {"kind": "fictional_fixture", "label": "Second reviewed fictional context source"}
            source = SourceState.objects.create(pk="fixture-cumulative-background", contract=contract,
                contract_digest=text_digest(canonical_json(contract)))
            self.config["sources"].append({"source_id": source.pk, "contract_digest": source.contract_digest})
        return schedule.configure_watch(self.actor, self.thesis["id"], str(uuid4()),
            current["revision"], self.config, clock=self.clock)

    def claim(self):
        schedule.enqueue_due(self.actor, self.watch, kind="analysis", clock=self.clock)
        return schedule.claim_due(self.actor, "analysis", watch_id=self.watch, clock=self.clock)

    def request(self):
        result = {"source_id": fixtures.SOURCE, "expected_approval_id": self.config["approval_id"],
            "expected_exposure_digest": self.config["exposure_digest"],
            **{key: self.config[key] for key in ("provider", "model_id", "model_configuration")}}
        if self.config["model_configuration"]["context"] == "complete_retained_context":
            result.update(context_source_ids=[row["source_id"] for row in self.config["sources"]],
                          context_bounds=self.config["context_bounds"])
        return result

    def test_preview_opt_in_does_not_change_existing_watch_or_make_calls(self):
        legacy = runner.enrollment_preview(self.actor, self.thesis["id"])
        cumulative = runner.enrollment_preview(self.actor, self.thesis["id"], cumulative=True)
        self.assertEqual(legacy["model_configuration"]["context"],
                         "one_retained_report_and_approved_paper_book")
        self.assertEqual(cumulative["model_configuration"]["context"], "complete_retained_context")
        self.assertEqual(schedule.current_watch(self.actor, self.watch)["configuration"], self.config)
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.provider.catalog_calls, 0)

    def test_command_cumulative_flag_only_previews_reviewable_configuration(self):
        output = StringIO()
        call_command("desk_watch", owner=self.actor, thesis_id=self.thesis["id"],
                     preview=True, cumulative=True, stdout=output)
        self.assertEqual(json.loads(output.getvalue())["model_configuration"]["context"],
                         "complete_retained_context")
        with self.assertRaisesMessage(CommandError, "valid only with --preview"):
            call_command("desk_watch", owner=self.actor, thesis_id=self.thesis["id"],
                         config="does-not-exist.json", cumulative=True, stdout=StringIO())

    def test_only_exact_safe_legacy_or_cumulative_model_configuration_is_accepted(self):
        self.assertEqual(configuration(self.config), self.config)
        self.enable_cumulative()
        self.assertEqual(configuration(self.config), self.config)
        for field, value in (("context", "unknown_context_mode"),
                             ("prompt_version", "unreviewed-prompt"),
                             ("schema_version", "unreviewed-schema")):
            changed = deepcopy(self.config)
            changed["model_configuration"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                configuration(changed)

    def test_cumulative_dispatch_rejects_scope_bounds_and_missing_fields_before_marker(self):
        self.enable_cumulative(extra_source=True)
        lease = self.claim()
        original = self.request()
        changed_bounds = {**original["context_bounds"], "reports": 1}
        float_bounds = {**original["context_bounds"], "reports": float(original["context_bounds"]["reports"])}
        mutations = [
            {**original, "context_source_ids": [fixtures.SOURCE]},
            {**original, "context_source_ids": list(reversed(original["context_source_ids"]))},
            {**original, "context_bounds": changed_bounds},
            {**original, "context_bounds": float_bounds},
            {key: value for key, value in original.items() if key != "context_bounds"},
        ]
        for request in mutations:
            with self.subTest(request=request), self.assertRaises(ValueError):
                schedule.mark_analysis_started(self.actor, lease["token"], request, clock=self.clock)
            self.assertFalse(AnalysisDispatch.objects.exists())
        result = schedule.mark_analysis_started(self.actor, lease["token"], original, clock=self.clock)
        self.assertEqual(result["analysis_request"], original)
        self.assertFalse(NewsAnalysisAttempt.objects.exists())
        self.assertEqual(self.provider.calls, 0)

    def test_legacy_dispatch_shape_does_not_accept_unreviewed_cumulative_scope(self):
        lease = self.claim()
        original = self.request()
        with self.assertRaises(ValueError):
            schedule.mark_analysis_started(self.actor, lease["token"],
                {**original, "context_source_ids": [fixtures.SOURCE],
                 "context_bounds": self.config["context_bounds"]}, clock=self.clock)
        extended = {**original, "context_source_ids": [fixtures.SOURCE],
                    "context_bounds": self.config["context_bounds"]}
        with self.assertRaises(DatabaseError) as error:
            with transaction.atomic():
                AnalysisDispatch.objects.create(slot_id=lease["slot_id"], lease_id=lease["token"],
                    request=extended, request_digest=text_digest(canonical_json(extended)), started_at=self.at)
        self.assertEqual(getattr(error.exception.__cause__, "sqlstate", None), "23514")
        self.assertFalse(AnalysisDispatch.objects.exists())
        result = schedule.mark_analysis_started(self.actor, lease["token"], original, clock=self.clock)
        self.assertEqual(set(result["analysis_request"]), set(original))

    def test_sql_dispatch_guard_rejects_changed_scope_bounds_and_unreviewed_fields(self):
        self.enable_cumulative(extra_source=True)
        lease = self.claim()
        original = self.request()
        requests = [
            {**original, "context_source_ids": [fixtures.SOURCE]},
            {**original, "context_bounds": {**original["context_bounds"], "reports": 1}},
            {**original, "context_bounds": {**original["context_bounds"], "reports": 100.0}},
            {key: value for key, value in original.items() if key != "context_source_ids"},
            {**original, "extra": "not reviewed"},
        ]
        for request in requests:
            with self.subTest(request=request), self.assertRaises(DatabaseError) as error:
                with transaction.atomic():
                    AnalysisDispatch.objects.create(slot_id=lease["slot_id"], lease_id=lease["token"],
                        request=request, request_digest=text_digest(canonical_json(request)), started_at=self.at)
            self.assertEqual(getattr(error.exception.__cause__, "sqlstate", None), "23514")
            self.assertFalse(AnalysisDispatch.objects.exists())
        schedule.mark_analysis_started(self.actor, lease["token"], original, clock=self.clock)

    def test_runner_passes_complete_reviewed_manifest_and_typed_bounds_after_marker(self):
        self.enable_cumulative(extra_source=True)
        expected = self.request()

        def admitted(*args, **kwargs):
            self.assertEqual(AnalysisDispatch.objects.get().request, expected)
            self.assertEqual(kwargs["context_source_ids"], tuple(expected["context_source_ids"]))
            self.assertEqual(kwargs["context_limits"], DailyReviewLimits(**expected["context_bounds"]))
            return {"analysis": {"status": "queue_empty"}}

        with patch.object(runner.analysis, "analyse_next", side_effect=admitted):
            result = self.tick()
        self.assertEqual(result["processed"][0]["outcome"]["status"], "completed")
        self.assertFalse(NewsAnalysisAttempt.objects.exists())
        self.assertEqual(self.provider.calls, 0)

    def test_two_reports_accumulate_intraday_before_any_daily_review(self):
        self.enable_cumulative()
        self.provider = RecordedCumulativeProvider()
        first = self.tick()
        self.assertEqual(first["processed"][0]["outcome"]["status"], "completed")
        first_attempt = NewsAnalysisAttempt.objects.get()
        self.assertFalse(DailyReview.objects.exists())
        self.assertEqual(self.provider.contexts[0]["cumulative"]["analyses"], [])
        self.at += timedelta(seconds=61)
        capture.capture(fixtures.SOURCE, fixtures.CONTRACT,
            lambda: self.batch("report-2", "Second fictional development"), clock=self.clock)
        second = self.tick()
        self.assertEqual(second["processed"][0]["outcome"]["status"], "completed")
        self.assertEqual(self.provider.calls, 2)
        self.assertEqual(self.provider.catalog_calls, 2)
        self.assertFalse(DailyReview.objects.exists())
        context = self.provider.contexts[1]["cumulative"]
        self.assertIn(str(first_attempt.source_revision_id),
                      {item["revision_id"] for item in context["reports"]})
        self.assertIn(str(first_attempt.pk), {item["analysis_id"] for item in context["analyses"]})
        result = NewsAnalysisResult.objects.exclude(attempt=first_attempt).get()
        self.assertEqual(result.document["evidence_comparisons"][0]["prior_analysis_ids"],
                         [str(first_attempt.pk)])
        self.assertEqual(first_attempt.context["cumulative"]["analyses"], [])
        self.assertNotEqual(first_attempt.context["cumulative"]["context_id"], context["context_id"])

    def test_cumulative_result_commit_restart_recovers_without_configuration_keys_or_respend(self):
        self.enable_cumulative()
        self.provider = RecordedCumulativeProvider()
        with patch.object(schedule, "complete_slot", side_effect=fixtures.SimulatedCrash):
            with self.assertRaises(fixtures.SimulatedCrash):
                self.tick()
        result = NewsAnalysisResult.objects.get()
        original_context = deepcopy(result.attempt.context)
        self.assertEqual(result.status, "analysed")
        self.at += timedelta(seconds=31)
        connections.close_all()
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            recovered = self.tick()
        self.assertEqual(recovered["processed"][0]["outcome"]["status"], "completed")
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.provider.catalog_calls, 1)
        self.assertEqual(NewsAnalysisResult.objects.count(), 1)
        self.assertEqual(NewsAnalysisAttempt.objects.get().context, original_context)
