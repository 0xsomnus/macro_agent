"""Reviewed daily publication, retained recovery and no paid-model coupling."""

from copy import deepcopy
from datetime import timedelta
from io import StringIO
import json
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test import TransactionTestCase, override_settings

from macro_agent.desk import publication, service as desk
from macro_agent.desk.models import DailyReview
from macro_agent.monitoring import runner
from macro_agent.monitoring.tests import test_runner as fixtures
from macro_agent.persistence.models import NotificationIntent
from macro_agent.positions import service as positions
from macro_agent.scheduling import service as schedule
from macro_agent.scheduling.configuration import configuration


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class DailyPublicationRunnerTests(TransactionTestCase):
    setUp = fixtures.PostgreSQLRunnerTests.setUp
    clock = fixtures.PostgreSQLRunnerTests.clock
    batch = fixtures.PostgreSQLRunnerTests.batch
    tick = fixtures.PostgreSQLRunnerTests.tick

    def enable_publication(self):
        current = schedule.current_watch(self.actor, self.watch)
        self.config = deepcopy(current["configuration"])
        self.config["daily_publication"] = {"fanout_limit": 100}
        return schedule.configure_watch(self.actor, self.thesis["id"], str(uuid4()),
                                        current["revision"], self.config, clock=self.clock)

    def daily_lease(self):
        self.at = self.cutoff + timedelta(seconds=1)
        schedule.enqueue_due(self.actor, self.watch, kind="daily_review", clock=self.clock)
        return schedule.claim_due(self.actor, "daily_review", watch_id=self.watch, clock=self.clock)

    def test_old_watch_remains_assembly_only_and_opt_in_requires_exact_bounded_shape(self):
        self.assertEqual(configuration(self.config), self.config)
        for value in (None, True, {}, {"fanout_limit": True}, {"fanout_limit": "100"},
                      {"fanout_limit": 0}, {"fanout_limit": 1001},
                      {"fanout_limit": 100, "notify": True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                configuration({**self.config, "daily_publication": value})
        response = runner.execute_lease(self.daily_lease(), clock=self.clock)
        self.assertEqual(response["outcome"]["status"], "completed")
        self.assertNotIn("publication", response["outcome"]["payload"])
        self.assertEqual(DailyReview.objects.count(), 1)
        self.assertEqual(NotificationIntent.objects.count(), 0)
        self.assertIsNone(publication.get_current_brief(self.actor, self.thesis["id"],
                                                       clock=self.clock)["current_publication"])

    def test_reviewed_opt_in_publishes_late_review_without_model_configuration_or_calls(self):
        self.enable_publication()
        lease = self.daily_lease()
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            result = runner.execute_lease(lease, clock=self.clock)
        payload = result["outcome"]["payload"]
        self.assertEqual(result["outcome"]["status"], "completed")
        self.assertTrue(payload["late"])
        self.assertEqual(payload["publication"]["publication"]["original_decision"]["status"], "current")
        current = publication.get_current_brief(self.actor, self.thesis["id"], clock=self.clock)
        self.assertEqual(current["current_publication"]["publication"]["id"],
                         payload["publication"]["publication"]["id"])
        self.assertEqual(NotificationIntent.objects.count(), 1)
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.provider.catalog_calls, 0)

    def test_commit_before_slot_completion_restart_reads_saved_publication_without_new_intent(self):
        self.enable_publication()
        lease = self.daily_lease()
        with patch.object(schedule, "complete_slot", side_effect=fixtures.SimulatedCrash):
            with self.assertRaises(fixtures.SimulatedCrash):
                runner.execute_lease(lease, clock=self.clock)
        review = DailyReview.objects.get()
        original = publication.get_publication_command(self.actor, self.thesis["id"],
                                                        str(review.command_id), clock=self.clock)
        self.at += timedelta(seconds=31)
        connections.close_all()
        renewed = schedule.claim_due(self.actor, "daily_review", watch_id=self.watch, clock=self.clock)
        with patch.object(publication, "preview_publication", side_effect=AssertionError("No new preview")), \
                patch.object(publication, "publish_review", side_effect=AssertionError("No new publication")), \
                patch.object(desk, "create_review", side_effect=AssertionError("No review regeneration")), \
                override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                                  SETTINGS_MODULE="macro_agent.web.local_settings"):
            result = runner.execute_lease(renewed, clock=self.clock)
        recovered = result["outcome"]["payload"]["publication"]
        self.assertEqual(recovered["publication"], original["publication"])
        self.assertTrue(recovered["replayed"])
        self.assertEqual(DailyReview.objects.count(), 1)
        self.assertEqual(NotificationIntent.objects.count(), 1)
        self.assertEqual(self.provider.calls, 0)

    def test_correction_after_publication_before_restart_preserves_original_and_canceled_intent(self):
        self.enable_publication()
        lease = self.daily_lease()
        with patch.object(schedule, "complete_slot", side_effect=fixtures.SimulatedCrash):
            with self.assertRaises(fixtures.SimulatedCrash):
                runner.execute_lease(lease, clock=self.clock)
        current = positions.get_position(self.actor, self.position["id"])
        self.at += timedelta(seconds=1)
        positions.revise_position(self.actor, self.position["id"], str(uuid4()), current["revision"],
            self.approval, {**fixtures.DECLARATION, "quantity": "2", "quantity_unit": "paper contracts"},
            clock=self.clock)
        self.at += timedelta(seconds=31)
        renewed = schedule.claim_due(self.actor, "daily_review", watch_id=self.watch, clock=self.clock)
        with patch.object(publication, "publish_review", side_effect=AssertionError("No replacement")):
            result = runner.execute_lease(renewed, clock=self.clock)
        saved = result["outcome"]["payload"]["publication"]
        self.assertEqual(result["outcome"]["status"], "completed")
        self.assertEqual(saved["publication"]["original_decision"]["status"], "current")
        self.assertEqual(saved["current_disposition"]["status"], "superseded")
        self.assertEqual(saved["notification_intent"]["state"], "canceled")
        self.assertEqual(NotificationIntent.objects.count(), 1)
        self.assertEqual(DailyReview.objects.count(), 1)

    def test_stale_saved_review_is_a_conclusive_superseded_decision_without_regeneration(self):
        self.enable_publication()
        lease = self.daily_lease()
        from datetime import datetime
        original = desk.create_review(self.actor, self.thesis["id"], lease["command_id"],
            datetime.fromisoformat(lease["period_start"]), datetime.fromisoformat(lease["cutoff"]),
            [fixtures.SOURCE], runner.DailyReviewLimits(**self.config["context_bounds"]), clock=self.clock)
        self.at += timedelta(seconds=1)
        positions.create_position(self.actor, self.thesis["id"], str(uuid4()), self.approval,
                                  fixtures.DECLARATION, clock=self.clock)
        result = runner.execute_lease(lease, clock=self.clock)
        saved = result["outcome"]["payload"]["publication"]
        self.assertEqual(result["outcome"]["status"], "completed")
        self.assertEqual(saved["publication"]["original_decision"]["status"], "superseded")
        self.assertEqual(saved["review"], original["review"])
        self.assertIsNone(saved["notification_intent"])
        self.assertEqual(DailyReview.objects.count(), 1)
        self.assertEqual(self.provider.calls, 0)

    def test_slot_completion_fencing_does_not_report_a_retained_publication_as_none(self):
        self.enable_publication()
        lease = self.daily_lease()
        with patch.object(schedule, "complete_slot", side_effect=schedule.ScheduleFenced):
            result = runner.execute_lease(lease, clock=self.clock)
        self.assertEqual(result["outcome"]["status"], "lease_lost")
        self.assertEqual(result["publication"], "internal_daily")
        self.assertEqual(runner._publication_state([result]), "internal_daily")
        self.assertEqual(NotificationIntent.objects.count(), 1)

    def test_cli_requires_explicit_reviewed_generation_digest_and_bound_without_watch_enrollment(self):
        lease = self.daily_lease()
        runner.execute_lease(lease, clock=self.clock)
        review = DailyReview.objects.get()
        output = StringIO()
        original_preview = publication.preview_publication
        with patch.object(publication, "preview_publication", side_effect=lambda *args, **kwargs:
                          original_preview(*args, **kwargs, clock=self.clock)):
            call_command("desk_publish", owner=self.actor, review_id=str(review.pk), preview=True,
                         fanout_limit=100, stdout=output)
        preview = json.loads(output.getvalue())
        self.assertEqual(preview["review_id"], str(review.pk))
        self.assertEqual(NotificationIntent.objects.count(), 0)
        with self.assertRaises(CommandError):
            call_command("desk_publish", owner=self.actor, review_id=str(review.pk),
                         fanout_limit=100, stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("desk_publish", owner=self.actor, review_id=str(review.pk), preview=True,
                         command_id=str(uuid4()), fanout_limit=100, stdout=StringIO())
        # The fixture clock is ahead of wall time; pass a saved observation clock
        # to the shared application service while testing command argument wiring.
        original_publish = publication.publish_review
        with patch.object(publication, "publish_review", side_effect=lambda *args, **kwargs:
                          original_publish(*args, **kwargs, clock=self.clock)):
            call_command("desk_publish", owner=self.actor, review_id=str(review.pk),
                command_id=str(uuid4()), expected_generation=preview["expected_generation"],
                expected_review_digest=preview["review_digest"], fanout_limit=100, stdout=StringIO())
        self.assertEqual(NotificationIntent.objects.count(), 1)
        self.assertNotIn("daily_publication", schedule.current_watch(self.actor, self.watch)["configuration"])
