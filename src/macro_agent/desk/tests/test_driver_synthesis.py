"""Pinned morning driver-review admissions retain recovery and authority limits."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.test import TransactionTestCase, override_settings

from macro_agent.domain.daily_synthesis import DRIVER_SCHEMA_VERSION
from macro_agent.domain.driver_review import driver_assessment_example
from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.monitoring.tests import test_analysis as news
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.theses import service as theses
from macro_agent.desk import publication, synthesis
from macro_agent.desk.models import DailySynthesisAttempt, DailySynthesisResult
from . import test_synthesis as recorded


class DriverSynthesisProvider(recorded.RecordedSynthesisProvider):
    def complete(self, model_id, messages):
        metadata = super().complete(model_id, messages)
        context = json.loads(messages[1]["content"])
        if context.get("driver_review"):
            document = json.loads(metadata["content"])
            document["schema_version"] = DRIVER_SCHEMA_VERSION
            document["driver_assessment"] = driver_assessment_example(
                context["original_inputs"]["approved_user"]["interpretation"]["drivers"])
            metadata["content"] = canonical_json(document)
        return metadata


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class DailyDriverSynthesisPersistenceTests(TransactionTestCase):
    capture = recorded.DailySynthesisTests.capture
    review = recorded.DailySynthesisTests.review
    approve = recorded.DailySynthesisTests.approve
    approval_id = recorded.DailySynthesisTests.approval_id
    replace_approval = recorded.DailySynthesisTests.replace_approval

    def setUp(self):
        recorded.DailySynthesisTests.setUp(self)
        self.provider = DriverSynthesisProvider()

    def synthesize(self, review=None, command=None, *, driver_review=True, **kwargs):
        review = review or self.review()
        return synthesis.synthesize_review(self.actor, review["review"]["id"], command or str(uuid4()),
            review["review"]["digest"], news.MODEL, "nanogpt", provider=self.provider,
            driver_review=driver_review, **kwargs)

    def test_profile_is_committed_before_model_call_without_publication_authority(self):
        review = self.review()
        def callback():
            with ThreadPoolExecutor(max_workers=1) as pool:
                attempt = pool.submit(news.independent, lambda: DailySynthesisAttempt.objects.get()).result(timeout=10)
            self.assertTrue(attempt.context["driver_review"])
            self.assertEqual(attempt.configuration["schema_version"], DRIVER_SCHEMA_VERSION)
            self.assertFalse(DailySynthesisResult.objects.exists())
            self.assertFalse(connection.in_atomic_block)
        self.provider.callback = callback
        result = self.synthesize(review)
        self.assertEqual(result["synthesis"]["status"], "synthesised")
        self.assertEqual(result["synthesis"]["document"]["driver_assessment"]["approved_drivers"][0]["exact_driver"],
            news.MEANING["drivers"][0])
        self.assertEqual(result["synthesis"]["context_digest"],
            text_digest(canonical_json(result["synthesis"]["context"])))
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertFalse(result["current_disposition"]["publication_authority"])

    def test_saved_profile_recovers_before_credentials_or_current_configuration(self):
        review, command = self.review(), str(uuid4())
        saved = self.synthesize(review, command)
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                SETTINGS_MODULE="macro_agent.web.local_settings"), patch.object(
                synthesis, "model_configuration", side_effect=AssertionError("Fresh configuration consulted on recovery")):
            replay = self.synthesize(review, command)
            read = synthesis.get_synthesis_command(self.actor, review["review"]["id"], command)
            inspect = synthesis.inspect_synthesis(self.actor, saved["synthesis"]["id"])
        self.assertEqual(saved["synthesis"], replay["synthesis"])
        self.assertEqual(saved["synthesis"], read["synthesis"])
        self.assertEqual(saved["synthesis"], inspect["synthesis"])
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (1, 1))

    def test_profile_cannot_change_under_saved_command(self):
        review, command = self.review(), str(uuid4())
        self.synthesize(review, command)
        with self.assertRaises(theses.ThesisConflict):
            self.synthesize(review, command, driver_review=False)
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (1, 1))

    def test_correction_during_driver_review_retains_stale_result(self):
        self.provider.callback = lambda: self.capture(title="Corrected retained source")
        result = self.synthesize()
        self.assertEqual(result["synthesis"]["status"], "stale")
        self.assertIsNotNone(result["synthesis"]["document"]["driver_assessment"])
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())

    def test_current_brief_reads_exact_profile_without_new_publication(self):
        review = self.review()
        row = review["review"]
        published = publication.publish_review(self.actor, row["id"], str(uuid4()), row["digest"], 0, 10)
        self.synthesize(review)
        current = publication.get_current_brief(self.actor, self.thesis["id"])["current_publication"]
        self.assertEqual(current["publication"], published["publication"])
        self.assertEqual((CurrentAssessment.objects.count(), NotificationIntent.objects.count()), (1, 1))

    def test_invalid_driver_identity_retains_usage_and_digest_fallback(self):
        original = self.provider.complete
        def invalid(model, messages):
            metadata = original(model, messages)
            document = json.loads(metadata["content"])
            document["driver_assessment"]["approved_drivers"][0]["exact_driver"] = "Agent replaced approved intent"
            metadata["content"] = canonical_json(document)
            return metadata
        self.provider.complete = invalid
        result = self.synthesize()
        self.assertEqual(result["synthesis"]["status"], "failed")
        self.assertEqual(result["synthesis"]["stop_reason"], "invalid_model_output")
        self.assertEqual(result["synthesis"]["usage"]["total_tokens"], 150)
        self.assertIsNone(result["synthesis"]["document"])

    def test_legacy_request_digest_is_identical_and_has_no_profile_field(self):
        review, command = self.review(), str(uuid4())
        saved = self.synthesize(review, command, driver_review=False)
        replay = synthesis.synthesize_review(self.actor, review["review"]["id"], command,
            review["review"]["digest"], news.MODEL, "nanogpt", provider=self.provider)
        attempt = DailySynthesisAttempt.objects.get()
        expected = {"review_id": review["review"]["id"], "review_digest": review["review"]["digest"],
            "model_id": news.MODEL, "provider_id": "nanogpt"}
        self.assertEqual(attempt.request_digest, text_digest(canonical_json(expected)))
        self.assertNotIn("driver_review", saved["synthesis"]["context"])
        self.assertEqual(saved["synthesis"], replay["synthesis"])

    def test_non_boolean_profile_is_rejected_before_any_model_request(self):
        review = self.review()
        for value in (1, "true", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.synthesize(review, driver_review=value)
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (0, 0))
        self.assertFalse(DailySynthesisAttempt.objects.exists())
