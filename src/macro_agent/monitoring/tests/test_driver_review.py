"""Opted-in driver review keeps immutable paid admission and inert recovery."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from unittest.mock import patch
from uuid import uuid4

from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase, override_settings

from macro_agent.domain.driver_review import driver_assessment_example
from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.domain.news_analysis import DRIVER_SCHEMA_VERSION, DRIVER_PROMPT_VERSION
from macro_agent.desk import service as desk
from macro_agent.monitoring import analysis
from macro_agent.monitoring.models import NewsAnalysisAttempt, NewsAnalysisResult, NewsReviewReceipt
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.theses import service as theses

from . import test_analysis as recorded
from . import test_cumulative_analysis as cumulative


class RecordedDriverProvider(recorded.RecordedProvider):
    cumulative = False

    def complete(self, model_id, messages):
        metadata = super().complete(model_id, messages)
        context = json.loads(messages[1]["content"])
        document = json.loads(metadata["content"])
        if self.cumulative:
            prior = [item["analysis_id"] for item in context["cumulative"]["analyses"]
                     if item["original_status"] in ("analysed", "stale") and item["document"] is not None]
            document["evidence_comparisons"] = ([{"prior_analysis_ids": prior, "fact_ids": ["f1"],
                "relationship": "unresolved", "explanation": "Earlier mechanism support remains unresolved.",
                "uncertainty": "These are model interpretations, not independently verified causal evidence."}]
                if prior else [])
        document["schema_version"] = DRIVER_SCHEMA_VERSION
        document["driver_assessment"] = driver_assessment_example(context["approved_thesis"]["drivers"])
        driver = document["driver_assessment"]["approved_drivers"][0]
        driver["premise"].update(status="supports", claim_ids=["f1"],
            reasoning="The fictional policy announcement is reported in this retained passage.")
        driver["mechanism"].update(status="challenges", claim_ids=["f1"],
            reasoning="Reported funding stress could impair the proposed transmission.")
        document["driver_assessment"]["attention"].update(status="review_recommended",
            driver_indices=[0], claim_ids=["f1"],
            reasoning="A reported funding constraint could alter a consequential approved transmission.")
        metadata["content"] = json.dumps(document)
        return metadata


@override_settings(MACRO_ENABLE_NEWS_ANALYSIS=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ALLOW_SYNTHETIC_SETUP=True, MACRO_ENABLE_MODEL_COMPILATION=True,
    MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="recorded-test-key",
    SETTINGS_MODULE="macro_agent.web.local_settings")
class PostgreSQLDriverReviewTests(TransactionTestCase):
    approve = recorded.PostgreSQLNewsAnalysisTests.approve
    approval_id = recorded.PostgreSQLNewsAnalysisTests.approval_id
    item = recorded.PostgreSQLNewsAnalysisTests.item
    batch = recorded.PostgreSQLNewsAnalysisTests.batch
    capture_item = recorded.PostgreSQLNewsAnalysisTests.capture_item
    reviewed = recorded.PostgreSQLNewsAnalysisTests.reviewed
    analyse = recorded.PostgreSQLNewsAnalysisTests.analyse

    def setUp(self):
        recorded.PostgreSQLNewsAnalysisTests.setUp(self)
        self.provider = RecordedDriverProvider()

    def test_admission_commits_profile_and_exact_approved_drivers_without_publication_authority(self):
        before = theses.get_thesis(self.actor, self.thesis["id"])
        command = str(uuid4())
        def callback():
            with ThreadPoolExecutor(max_workers=1) as pool:
                attempt = pool.submit(recorded.independent, lambda: NewsAnalysisAttempt.objects.get()).result(timeout=10)
            self.assertTrue(attempt.context["driver_review"])
            self.assertTrue(attempt.configuration["driver_review"])
            self.assertEqual(attempt.configuration["schema_version"], DRIVER_SCHEMA_VERSION)
            self.assertEqual(attempt.configuration["prompt_version"], DRIVER_PROMPT_VERSION)
            self.assertFalse(NewsAnalysisResult.objects.exists())
        self.provider.callback = callback
        response = self.analyse(command, driver_review=True)["analysis"]
        self.assertEqual(response["status"], "analysed")
        review = response["document"]["driver_assessment"]
        self.assertEqual(review["approved_drivers"][0]["exact_driver"], recorded.MEANING["drivers"][0])
        self.assertEqual(review["price_observation"]["status"], "unavailable")
        self.assertEqual(theses.get_thesis(self.actor, self.thesis["id"]), before)
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertIsNone(response["reported_cost_usd"])

    def test_saved_command_keeps_profile_without_catalogue_key_or_respending(self):
        command = str(uuid4())
        reviewed = self.reviewed()
        first = self.analyse(command, reviewed=reviewed, driver_review=True)["analysis"]
        with override_settings(MACRO_MODEL_PROVIDER="openrouter", MACRO_MODEL_API_KEY="",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            replay = self.analyse(command, reviewed=reviewed, driver_review=True)["analysis"]
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["document"], replay["document"])
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (1, 1))
        with self.assertRaises(analysis.NewsConflict):
            self.analyse(command, reviewed=reviewed)

    def test_failed_new_profile_output_preserves_paid_attempt_without_retry(self):
        original = self.provider.complete
        def incomplete(model_id, messages):
            result = original(model_id, messages)
            doc = json.loads(result["content"])
            doc["driver_assessment"]["approved_drivers"] = []
            result["content"] = json.dumps(doc)
            return result
        self.provider.complete = incomplete
        command = str(uuid4())
        first = self.analyse(command, driver_review=True)["analysis"]
        self.assertEqual((first["status"], first["stop_reason"]), ("failed", "invalid_model_output"))
        self.assertIsNone(first["document"])
        self.assertEqual(first["usage"]["total_tokens"], 150)
        self.analyse(command, driver_review=True)
        self.assertEqual(self.analyse(driver_review=True)["analysis"]["status"], "queue_empty")
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (1, 1))

    def test_unknown_admission_after_crash_survives_without_new_call(self):
        command = str(uuid4())
        with patch.object(self.provider, "complete", side_effect=RuntimeError("recorded interruption")):
            with self.assertRaises(RuntimeError):
                self.analyse(command, driver_review=True)
        attempt = NewsAnalysisAttempt.objects.get()
        recovered = analysis.get_news_command(self.actor, self.thesis["id"], command,
            clock=lambda: attempt.deadline_at)["analysis"]
        self.assertEqual(recovered["status"], "outcome_unknown")
        self.assertTrue(recovered["context"]["driver_review"])
        self.assertEqual((self.provider.calls, self.provider.catalog_calls), (0, 1))
        self.assertEqual(NewsReviewReceipt.objects.count(), 1)

    def test_source_correction_during_inference_changes_disposition_without_changing_approved_text(self):
        before = theses.get_thesis(self.actor, self.thesis["id"])
        self.provider.callback = lambda: self.capture_item(title="Corrected fictional announcement")
        response = self.analyse(driver_review=True)["analysis"]
        self.assertEqual(response["status"], "stale")
        self.assertEqual(response["document"]["schema_version"], DRIVER_SCHEMA_VERSION)
        self.assertIn("observed_source_revision_changed", response["stale_reasons"])
        self.assertEqual(theses.get_thesis(self.actor, self.thesis["id"]), before)

    def test_profile_boolean_is_strict_and_legacy_false_keeps_request_identity(self):
        for flag in (None, 1, "true", [], {}):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                self.analyse(driver_review=flag)
        legacy = analysis.model_configuration("nanogpt")
        self.assertEqual(legacy, analysis.model_configuration("nanogpt", driver_review=False))
        self.provider = recorded.RecordedProvider()
        command = str(uuid4())
        first = self.analyse(command)["analysis"]
        replay = self.analyse(command, driver_review=False)["analysis"]
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["document"], replay["document"])
        self.assertNotIn("driver_review", NewsAnalysisAttempt.objects.get().configuration)

    def test_sql_rejects_missing_or_mismatched_driver_profile_binding(self):
        self.analyse(driver_review=True)
        row = NewsAnalysisAttempt.objects.get()
        original = {field.name: deepcopy(getattr(row, field.name)) for field in row._meta.fields
                    if field.name not in ("id", "command_id")}
        mutations = (
            ("context", lambda value: value.pop("driver_review")),
            ("configuration", lambda value: value.pop("driver_review")),
            ("context", lambda value: value.update(driver_review=False)),
            ("configuration", lambda value: value.update(prompt_version="retained-news-analysis-prompt-v2")),
        )
        for name, mutate in mutations:
            values = deepcopy(original)
            mutate(values[name])
            values["context_digest"] = text_digest(canonical_json(values["context"]))
            values["command_id"] = uuid4()
            with self.subTest(name=name), self.assertRaises(DatabaseError), transaction.atomic():
                NewsAnalysisAttempt.objects.create(**values)


@override_settings(MACRO_ENABLE_NEWS_ANALYSIS=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class PostgreSQLCumulativeDriverReviewTests(TransactionTestCase):
    approve = recorded.PostgreSQLNewsAnalysisTests.approve
    approval_id = recorded.PostgreSQLNewsAnalysisTests.approval_id
    item = recorded.PostgreSQLNewsAnalysisTests.item
    batch = recorded.PostgreSQLNewsAnalysisTests.batch
    capture_item = recorded.PostgreSQLNewsAnalysisTests.capture_item
    reviewed = recorded.PostgreSQLNewsAnalysisTests.reviewed
    background = cumulative.PostgreSQLCumulativeAnalysisTests.background
    cumulative = cumulative.PostgreSQLCumulativeAnalysisTests.cumulative

    def setUp(self):
        recorded.PostgreSQLNewsAnalysisTests.setUp(self)
        self.provider = RecordedDriverProvider()
        self.provider.cumulative = True
        self.background()

    def test_cumulative_new_profile_admits_exact_retained_context_and_earlier_review(self):
        first = self.cumulative(driver_review=True)["analysis"]
        self.assertEqual(first["status"], "analysed")
        original = NewsAnalysisAttempt.objects.get(pk=first["id"])
        self.assertEqual(original.configuration["schema_version"], DRIVER_SCHEMA_VERSION)
        self.assertIsNotNone(original.admission_context_id)
        desk.observe_analysis_results(self.actor, self.thesis["id"],
            (recorded.SOURCE, cumulative.BACKGROUND), limit=10)
        self.capture_item(native="report-2", title="Later fictional development")
        second = self.cumulative(driver_review=True)["analysis"]
        self.assertEqual(second["status"], "analysed")
        prior = second["context"]["cumulative"]["analyses"]
        self.assertEqual([item["analysis_id"] for item in prior], [first["id"]])
        self.assertEqual(prior[0]["document"], first["document"])
        self.assertEqual(second["document"]["evidence_comparisons"][0]["prior_analysis_ids"], [first["id"]])
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
