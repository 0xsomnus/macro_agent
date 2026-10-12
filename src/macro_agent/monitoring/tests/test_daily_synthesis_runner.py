"""Fresh morning opt-in, fenced admission, digest fallback and restart recovery."""
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.db import connections
from django.test import TransactionTestCase, override_settings
from macro_agent.desk import publication, synthesis
from macro_agent.desk.models import DailySynthesisAttempt, DailySynthesisResult
from macro_agent.desk.tests import test_synthesis as recorded
from macro_agent.monitoring import runner
from macro_agent.monitoring.tests import test_daily_publication_runner as daily
from macro_agent.monitoring.tests import test_runner as fixtures
from macro_agent.scheduling import service as schedule
from macro_agent.scheduling.configuration import configuration


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER='nanogpt',
    MACRO_MODEL_API_KEY='recorded-test-key', SETTINGS_MODULE='macro_agent.web.local_settings')
class DailySynthesisRunnerTests(TransactionTestCase):
    setUp = fixtures.PostgreSQLRunnerTests.setUp
    clock = fixtures.PostgreSQLRunnerTests.clock
    batch = fixtures.PostgreSQLRunnerTests.batch
    tick = fixtures.PostgreSQLRunnerTests.tick
    daily_lease = daily.DailyPublicationRunnerTests.daily_lease

    def enable(self):
        current = schedule.current_watch(self.actor, self.watch)
        self.config = deepcopy(current['configuration'])
        self.config.update(daily_publication={'fanout_limit': 100},
            daily_synthesis={'model_configuration': synthesis.model_configuration('nanogpt')})
        schedule.configure_watch(self.actor, self.thesis['id'], str(uuid4()),
            current['revision'], self.config, clock=self.clock)
        self.provider = recorded.RecordedSynthesisProvider()

    def current(self):
        return publication.get_current_brief(self.actor, self.thesis['id'], clock=self.clock)

    def test_opt_in_requires_publication_and_exact_pinned_configuration(self):
        selected = {'model_configuration': synthesis.model_configuration('nanogpt')}
        for extra in ({'daily_synthesis': selected},
                      {'daily_publication': {'fanout_limit': 100}, 'daily_synthesis': {}},
                      {'daily_publication': {'fanout_limit': 100}, 'daily_synthesis': True}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                configuration({**self.config, **extra})
        self.enable()
        self.assertEqual(configuration(self.config), self.config)

    def test_digest_publishes_before_inference_and_current_read_attaches_exact_synthesis(self):
        self.enable()
        self.provider.callback = lambda: self.assertIsNotNone(self.current()['current_publication'])
        result = runner.execute_lease(self.daily_lease(), provider=self.provider, clock=self.clock)
        self.assertEqual(result['outcome']['status'], 'completed')
        saved = result['outcome']['payload']['synthesis']
        current = self.current()
        self.assertEqual(current['current_synthesis']['synthesis']['id'], saved['synthesis']['id'])
        self.assertEqual(current['current_publication']['review']['id'], saved['review_id'])
        self.assertEqual(self.provider.calls, 1)

    def test_model_unavailable_leaves_digest_current_and_slot_completed(self):
        self.enable()
        with override_settings(MACRO_MODEL_API_KEY='', SETTINGS_MODULE='macro_agent.web.local_settings'):
            result = runner.execute_lease(self.daily_lease(), provider=self.provider, clock=self.clock)
        self.assertEqual(result['outcome']['status'], 'completed')
        self.assertEqual(result['outcome']['payload']['synthesis']['fallback'], 'retained_daily_digest')
        self.assertIsNotNone(self.current()['current_publication'])
        self.assertIsNone(self.current()['current_synthesis'])
        self.assertFalse(DailySynthesisAttempt.objects.exists())
        self.assertEqual(self.provider.calls, 0)

    def test_result_committed_before_scheduler_crash_recovers_without_keys_or_respend(self):
        self.enable()
        lease = self.daily_lease()
        with patch.object(schedule, 'complete_slot', side_effect=fixtures.SimulatedCrash):
            with self.assertRaises(fixtures.SimulatedCrash):
                runner.execute_lease(lease, provider=self.provider, clock=self.clock)
        saved = self.current()['current_synthesis']['synthesis']
        self.at += timedelta(seconds=31)
        connections.close_all()
        next_lease = schedule.claim_due(self.actor, 'daily_review', watch_id=self.watch, clock=self.clock)
        with override_settings(MACRO_MODEL_API_KEY='', SETTINGS_MODULE='macro_agent.web.local_settings'):
            result = runner.execute_lease(next_lease, provider=self.provider, clock=self.clock)
        self.assertEqual(result['outcome']['payload']['synthesis']['synthesis'], saved)
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(DailySynthesisAttempt.objects.count(), 1)

    def test_crash_after_admission_is_recovered_as_unknown_without_another_model_call(self):
        self.enable()
        self.provider.callback = lambda: (_ for _ in ()).throw(fixtures.SimulatedCrash())
        lease = self.daily_lease()
        with self.assertRaises(fixtures.SimulatedCrash):
            runner.execute_lease(lease, provider=self.provider, clock=self.clock)
        self.assertEqual(DailySynthesisAttempt.objects.count(), 1)
        self.assertFalse(DailySynthesisResult.objects.exists())
        self.at += timedelta(seconds=100)
        next_lease = schedule.claim_due(self.actor, 'daily_review', watch_id=self.watch, clock=self.clock)
        result = runner.execute_lease(next_lease, provider=self.provider, clock=self.clock)
        self.assertEqual(result['outcome']['payload']['synthesis']['synthesis']['status'], 'outcome_unknown')
        self.assertEqual(self.provider.calls, 1)
        self.assertIsNotNone(self.current()['current_publication'])

    def test_catalogue_wait_that_expires_lease_cannot_admit_paid_call(self):
        self.enable()
        lease = self.daily_lease()
        original = self.provider.list_models
        def delayed():
            self.at += timedelta(seconds=31)
            return original()
        self.provider.list_models = delayed
        result = runner.execute_lease(lease, provider=self.provider, clock=self.clock)
        self.assertEqual(result['outcome']['status'], 'lease_lost')
        self.assertFalse(DailySynthesisAttempt.objects.exists())
        self.assertEqual(self.provider.calls, 0)
        self.assertIsNotNone(self.current()['current_publication'])

    def test_source_correction_clears_current_digest_and_adjacent_synthesis_together(self):
        self.enable()
        runner.execute_lease(self.daily_lease(), provider=self.provider, clock=self.clock)
        saved = self.current()['current_synthesis']['synthesis']
        self.at += timedelta(seconds=1)
        runner.capture.capture(fixtures.SOURCE, fixtures.CONTRACT,
            lambda: self.batch(title='Fictional correction'), clock=self.clock)
        current = self.current()
        self.assertIsNone(current['current_publication'])
        self.assertIsNone(current['current_synthesis'])
        history = synthesis.inspect_synthesis(self.actor, saved['id'], clock=self.clock)
        self.assertEqual(history['synthesis'], saved)
        self.assertEqual(history['current_disposition']['status'], 'stale')

    def test_shared_private_call_ceiling_blocks_synthesis_but_preserves_digest(self):
        self.enable()
        with patch.object(synthesis, 'capacity_available', return_value=False):
            result = runner.execute_lease(self.daily_lease(), provider=self.provider, clock=self.clock)
        self.assertEqual(result['outcome']['status'], 'completed')
        self.assertEqual(result['outcome']['payload']['synthesis']['code'], 'CompilationBudgetExhausted')
        self.assertEqual(self.provider.calls, 0)
        self.assertIsNotNone(self.current()['current_publication'])
