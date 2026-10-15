"""Reviewed driver profiles cross runner admission and restart boundaries intact."""

from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch
from uuid import uuid4

from django.db import connections
from django.test import TransactionTestCase, override_settings

from macro_agent.domain.driver_review import driver_assessment_example
from macro_agent.domain.models import canonical_json
from macro_agent.domain.news_analysis import DRIVER_SCHEMA_VERSION
from macro_agent.desk import publication, synthesis
from macro_agent.desk.models import DailySynthesisAttempt, DailySynthesisResult
from macro_agent.desk.tests import test_driver_synthesis as morning
from macro_agent.monitoring import capture, runner
from macro_agent.monitoring.models import NewsAnalysisAttempt
from macro_agent.monitoring.tests import test_cumulative_runner as cumulative
from macro_agent.monitoring.tests import test_daily_publication_runner as daily
from macro_agent.monitoring.tests import test_runner as recorded
from macro_agent.scheduling import service as schedule
from macro_agent.scheduling.configuration import configuration
from macro_agent.scheduling.models import AnalysisDispatch


class DriverNewsProvider(cumulative.RecordedCumulativeProvider):
    def complete(self, model_id, messages):
        metadata = super().complete(model_id, messages)
        context = json.loads(messages[1]["content"])
        output = json.loads(metadata["content"])
        output["schema_version"] = DRIVER_SCHEMA_VERSION
        output["driver_assessment"] = driver_assessment_example(context["approved_thesis"]["drivers"])
        metadata["content"] = canonical_json(output)
        return metadata


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class DriverReviewRunnerTests(TransactionTestCase):
    setUp = recorded.PostgreSQLRunnerTests.setUp
    clock = recorded.PostgreSQLRunnerTests.clock
    batch = recorded.PostgreSQLRunnerTests.batch
    tick = recorded.PostgreSQLRunnerTests.tick
    daily_lease = daily.DailyPublicationRunnerTests.daily_lease

    def enable(self, *, daily_synthesis=False):
        current = schedule.current_watch(self.actor, self.watch)
        self.config = deepcopy(current["configuration"])
        self.config["model_configuration"] = runner.analysis.model_configuration(
            "nanogpt", cumulative=True, driver_review=True)
        if daily_synthesis:
            self.config.update(daily_publication={"fanout_limit": 100}, daily_synthesis={
                "model_configuration": synthesis.model_configuration("nanogpt", driver_review=True)})
        schedule.configure_watch(self.actor, self.thesis["id"], str(uuid4()),
            current["revision"], self.config, clock=self.clock)

    def test_preview_does_not_activate_profile_and_only_exact_reviewed_configuration_is_accepted(self):
        preview = runner.enrollment_preview(self.actor, self.thesis["id"], cumulative=True, driver_review=True)
        self.assertTrue(preview["model_configuration"]["driver_review"])
        self.assertNotIn("driver_review", schedule.current_watch(self.actor, self.watch)["configuration"]["model_configuration"])
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (0, 0))
        self.enable(daily_synthesis=True)
        self.assertEqual(configuration(self.config), self.config)
        for kind in ("boolean", "news_prompt", "daily_prompt", "daily_schema"):
            changed = deepcopy(self.config)
            if kind == "boolean":
                changed["model_configuration"]["driver_review"] = 1
            elif kind == "news_prompt":
                changed["model_configuration"]["prompt_version"] = "retained-news-analysis-prompt-v3"
            else:
                changed["daily_synthesis"]["model_configuration"][
                    "prompt_version" if kind == "daily_prompt" else "schema_version"] = "retained-daily-synthesis-v1"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                configuration(changed)

    def test_cumulative_runner_pins_profile_and_retains_new_profile_predecessor(self):
        self.enable()
        self.provider = DriverNewsProvider()
        first = self.tick()
        self.assertEqual(first["processed"][0]["outcome"]["status"], "completed")
        attempt = NewsAnalysisAttempt.objects.get()
        self.assertTrue(attempt.context["driver_review"])
        self.assertTrue(AnalysisDispatch.objects.get().request["model_configuration"]["driver_review"])
        self.assertEqual(attempt.configuration["schema_version"], DRIVER_SCHEMA_VERSION)
        self.at += timedelta(seconds=61)
        capture.capture(recorded.SOURCE, recorded.CONTRACT,
            lambda: self.batch("report-2", "Second fictional development"), clock=self.clock)
        second = self.tick()
        self.assertEqual(second["processed"][0]["outcome"]["status"], "completed")
        prior = self.provider.contexts[1]["cumulative"]["analyses"]
        self.assertEqual(prior[0]["analysis_id"], str(attempt.pk))
        self.assertEqual(prior[0]["document"]["schema_version"], DRIVER_SCHEMA_VERSION)
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (2, 2))

    def test_news_recovery_inspects_saved_profile_before_keys_without_paid_retry(self):
        self.enable()
        self.provider = DriverNewsProvider()
        with patch.object(schedule, "complete_slot", side_effect=recorded.SimulatedCrash):
            with self.assertRaises(recorded.SimulatedCrash):
                self.tick()
        self.at += timedelta(seconds=31)
        connections.close_all()
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                SETTINGS_MODULE="macro_agent.web.local_settings"):
            recovered = self.tick()
        self.assertEqual(recovered["processed"][0]["outcome"]["status"], "completed")
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (1, 1))
        self.assertEqual(NewsAnalysisAttempt.objects.count(), 1)

    def test_daily_runner_admits_selected_profile_under_live_lease_and_attaches_exact_review(self):
        self.enable(daily_synthesis=True)
        provider = morning.DriverSynthesisProvider()
        result = runner.execute_lease(self.daily_lease(), provider=provider, clock=self.clock)
        saved = result["outcome"]["payload"]["synthesis"]["synthesis"]
        self.assertEqual(saved["status"], "synthesised")
        self.assertEqual(saved["schema_version"], synthesis.DRIVER_SCHEMA_VERSION)
        self.assertTrue(saved["context"]["driver_review"])
        current = publication.get_current_brief(self.actor, self.thesis["id"], clock=self.clock)
        self.assertEqual(current["current_synthesis"]["synthesis"]["id"], saved["id"])
        self.assertEqual(current["current_publication"]["review"]["id"], saved["review_id"])
        self.assertEqual(provider.calls, 1)

    def test_daily_profile_recovery_keeps_saved_result_without_respending(self):
        self.enable(daily_synthesis=True)
        provider = morning.DriverSynthesisProvider()
        lease = self.daily_lease()
        with patch.object(schedule, "complete_slot", side_effect=recorded.SimulatedCrash):
            with self.assertRaises(recorded.SimulatedCrash):
                runner.execute_lease(lease, provider=provider, clock=self.clock)
        saved = publication.get_current_brief(self.actor, self.thesis["id"], clock=self.clock)["current_synthesis"]
        self.at += timedelta(seconds=31)
        connections.close_all()
        renewed = schedule.claim_due(self.actor, "daily_review", watch_id=self.watch, clock=self.clock)
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            result = runner.execute_lease(renewed, provider=provider, clock=self.clock)
        self.assertEqual(result["outcome"]["payload"]["synthesis"]["synthesis"], saved["synthesis"])
        self.assertEqual(DailySynthesisAttempt.objects.count(), 1)
        self.assertEqual(DailySynthesisResult.objects.count(), 1)
        self.assertEqual((provider.calls, provider.catalog_calls), (1, 1))

    def test_expired_daily_lease_cannot_admit_driver_profile_after_catalogue_wait(self):
        self.enable(daily_synthesis=True)
        provider = morning.DriverSynthesisProvider()
        lease = self.daily_lease()
        original = provider.list_models
        def delay():
            self.at += timedelta(seconds=31)
            return original()
        provider.list_models = delay
        result = runner.execute_lease(lease, provider=provider, clock=self.clock)
        self.assertEqual(result["outcome"]["status"], "lease_lost")
        self.assertFalse(DailySynthesisAttempt.objects.exists())
        self.assertEqual(provider.calls, 0)
        self.assertIsNotNone(publication.get_current_brief(
            self.actor, self.thesis["id"], clock=self.clock)["current_publication"])
