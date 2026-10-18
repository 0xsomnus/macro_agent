"""Explicit watch publication, protected lease admission and inert restart."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.db import connections
from django.test import TransactionTestCase, override_settings

from macro_agent.domain.news_publication import POLICY_VERSION
from macro_agent.monitoring import analysis, publication, runner
from macro_agent.monitoring.attention_models import NewsPublication
from macro_agent.monitoring.models import NewsAnalysisAttempt, NewsAnalysisResult
from macro_agent.monitoring.tests import test_runner as fixtures
from macro_agent.monitoring.tests.test_driver_review import RecordedDriverProvider
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.positions import service as positions
from macro_agent.scheduling import service as schedule
from macro_agent.scheduling.configuration import configuration


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class AttentionRunnerTests(TransactionTestCase):
    setUp = fixtures.PostgreSQLRunnerTests.setUp
    clock = fixtures.PostgreSQLRunnerTests.clock
    batch = fixtures.PostgreSQLRunnerTests.batch
    tick = fixtures.PostgreSQLRunnerTests.tick

    def enable(self, *, publication_enabled=True):
        current = schedule.current_watch(self.actor, self.watch)
        self.config = deepcopy(current["configuration"])
        self.config["model_configuration"] = analysis.model_configuration("nanogpt", cumulative=True, driver_review=True)
        if publication_enabled:
            self.config["news_publication"] = {"fanout_limit": 100, "policy_version": POLICY_VERSION}
        schedule.configure_watch(self.actor, self.thesis["id"], str(uuid4()), current["revision"], self.config, clock=self.clock)
        self.provider = RecordedDriverProvider(); self.provider.cumulative = True

    def lease(self):
        schedule.enqueue_due(self.actor, self.watch, kind="analysis", clock=self.clock)
        return schedule.claim_due(self.actor, "analysis", watch_id=self.watch, clock=self.clock)

    def test_exact_opt_in_profile_publishes_analysis_and_internal_review_once(self):
        self.enable()
        self.assertEqual(configuration(self.config), self.config)
        lease = self.lease()
        result = runner.execute_lease(lease, provider=self.provider, clock=self.clock)
        self.assertEqual(result["outcome"]["status"], "completed")
        saved = result["outcome"]["payload"]["news_publication"]
        self.assertEqual(saved["publication"]["attention_decision"]["status"], "review_requested")
        self.assertEqual(saved["publication"]["slot_lease_token"], lease["token"])
        self.assertEqual(result["publication"], "internal_driver_news")
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(NotificationIntent.objects.filter(state="pending").count(), 1)

    def test_model_attention_without_publication_option_has_no_current_or_intent_authority(self):
        self.enable(publication_enabled=False)
        result = runner.execute_lease(self.lease(), provider=self.provider, clock=self.clock)
        self.assertEqual(result["outcome"]["status"], "completed")
        self.assertNotIn("news_publication", result["outcome"]["payload"])
        self.assertEqual(NewsAnalysisResult.objects.get().document["driver_assessment"]["attention"]["status"], "review_recommended")
        self.assertFalse(NewsPublication.objects.exists())
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())

    def test_expired_lease_after_analysis_cannot_publish_then_recovery_reuses_saved_analysis(self):
        self.enable()
        lease = self.lease()
        original = publication.preview_publication
        def expire_before_publication(*args, **kwargs):
            self.at += timedelta(seconds=31)
            return original(*args, **kwargs)
        with patch.object(publication, "preview_publication", side_effect=expire_before_publication):
            first = runner.execute_lease(lease, provider=self.provider, clock=self.clock)
        self.assertEqual(first["outcome"]["status"], "lease_lost")
        self.assertEqual(NewsAnalysisResult.objects.get().status, "analysed")
        self.assertFalse(NewsPublication.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
        connections.close_all()
        recovered_lease = schedule.claim_due(self.actor, "analysis", watch_id=self.watch, clock=self.clock)
        self.assertEqual(recovered_lease["mode"], "recover")
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            saved = runner.execute_lease(recovered_lease, provider=self.provider, clock=self.clock)
        self.assertEqual(saved["outcome"]["status"], "completed")
        self.assertEqual(saved["outcome"]["payload"]["news_publication"]["publication"]["slot_lease_token"], recovered_lease["token"])
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (1, 1))
        self.assertEqual(NewsPublication.objects.count(), 1)

    def test_watch_replacement_during_analysis_cannot_admit_automatic_publication(self):
        self.enable()
        lease = self.lease()
        def replace_watch():
            current = schedule.current_watch(self.actor, self.watch)
            changed = deepcopy(current["configuration"])
            changed["daily_backlog_limit"] += 1
            schedule.configure_watch(self.actor, self.thesis["id"], str(uuid4()), current["revision"], changed, clock=self.clock)
        self.provider.callback = replace_watch
        result = runner.execute_lease(lease, provider=self.provider, clock=self.clock)
        self.assertEqual(result["outcome"]["status"], "blocked")
        self.assertEqual(NewsAnalysisResult.objects.get().status, "analysed")
        self.assertFalse(NewsPublication.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())

    def test_restart_recovers_canceled_publication_before_fresh_lease_or_provider_authority(self):
        self.enable()
        lease = self.lease()
        with patch.object(schedule, "complete_slot", side_effect=fixtures.SimulatedCrash):
            with self.assertRaises(fixtures.SimulatedCrash):
                runner.execute_lease(lease, provider=self.provider, clock=self.clock)
        original = publication.get_publication_command(self.actor, self.thesis["id"], lease["command_id"], clock=self.clock)
        self.at += timedelta(seconds=1)
        position = positions.get_position(self.actor, self.position["id"])
        positions.revise_position(self.actor, self.position["id"], str(uuid4()), position["revision"], self.approval,
            {**fixtures.DECLARATION, "quantity": "2", "quantity_unit": "paper contracts"}, clock=self.clock)
        self.at += timedelta(seconds=31)
        connections.close_all()
        recovered_lease = schedule.claim_due(self.actor, "analysis", watch_id=self.watch, clock=self.clock)
        with patch.object(publication, "publish_analysis", side_effect=AssertionError("Saved publication wins")), \
                override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter", SETTINGS_MODULE="macro_agent.web.local_settings"):
            result = runner.execute_lease(recovered_lease, provider=self.provider, clock=self.clock)
        recovered = result["outcome"]["payload"]["news_publication"]
        self.assertEqual(recovered["publication"], original["publication"])
        self.assertEqual(recovered["notification_intent"]["state"], "canceled")
        self.assertEqual(recovered["current_disposition"]["status"], "superseded")
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (1, 1))
        self.assertEqual((NewsAnalysisAttempt.objects.count(), NewsPublication.objects.count()), (1, 1))

    def test_publication_configuration_requires_exact_cumulative_driver_profile(self):
        for selected in (None, {}, {"fanout_limit": True, "policy_version": POLICY_VERSION},
                         {"fanout_limit": 100, "policy_version": "unsupported"}):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                configuration({**self.config, "news_publication": selected})
        with self.assertRaises(ValueError):
            configuration({**self.config, "news_publication": {"fanout_limit": 100, "policy_version": POLICY_VERSION}})
