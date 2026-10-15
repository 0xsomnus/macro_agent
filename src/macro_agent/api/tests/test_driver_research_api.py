"""Opted-in research and driver review preserve private authority boundaries."""

import json
from unittest.mock import patch
from uuid import uuid4

from django.test import Client, TransactionTestCase, override_settings

from macro_agent.api.compilation_serializers import CompilationResponseSerializer
from macro_agent.api.news_analysis_serializers import NewsAnalysisResponseSerializer
from macro_agent.api.synthesis_serializers import SynthesisResponseSerializer
from macro_agent.api.tests import test_compilation_api as model_fixtures
from macro_agent.api.tests import test_desk_api as fixtures
from macro_agent.api.tests import test_news_analysis_api as news_fixtures
from macro_agent.api.tests import test_research_engine_api as research_fixtures
from macro_agent.desk import synthesis
from macro_agent.domain import daily_synthesis, news_analysis, research_compilation
from macro_agent.domain.driver_review import driver_assessment_example
from macro_agent.domain.models import canonical_json
from macro_agent.monitoring import analysis, capture
from macro_agent.monitoring.models import NewsAnalysisAttempt, SourceRevision
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.positions.models import PositionRecord
from macro_agent.scheduling.models import WatchRecord
from macro_agent.theses import compilation
from macro_agent.theses.models import ApprovalRecord, CompilationAttempt, CompilationBudget


EXACT = "  A disruption may affect helionite.\r\nCan we research possible exposure? Δ"
DRIVER = "A disruption may affect helionite."


class RecordedDriverResearchModel(model_fixtures.RecordedModel):
    def complete(self, model_id, messages):
        metadata = super().complete(model_id, messages)
        document = json.loads(metadata["content"])
        report = json.loads(messages[1]["content"])["evidence"]["reports"][0]
        document["interpretation"]["drivers"] = [DRIVER]
        document["grounding"][0]["exact_quote"] = DRIVER
        document.update(attributed_claims=[{"claim_id": "source-claim", "revision_id": report["revision_id"],
            "field": "title", "exact_quote": report["title"]}], factual_conflicts=[],
            evidence_assessment={"summary": "A fictional report motivates input-cost research.",
                "supporting_claim_ids": ["source-claim"], "counter_claim_ids": [],
                "gaps": ["No verified price, firm accounts or instrument availability."]},
            proposed_drivers=[{"driver_id": "replacement-costs",
                "explanation": "Importers may face adverse input costs rather than benefit.",
                "transmission": "Higher replacement costs could compress margins.",
                "supporting_claim_ids": ["source-claim"], "counter_claim_ids": [],
                "assumptions": ["Costs cannot immediately be passed on."],
                "uncertainty": "The fictional report does not establish firm sensitivity.",
                "why_material": "Indirect equity exposure could have the opposite sign."}],
            exposure_candidates=[{"candidate_id": "importer-equity",
                "asset": "Fictional helionite importer equity",
                "expression": "Research equity or a derivative if a suitable instrument exists.",
                "relationship": "Input-cost exposure may harm importer margins.",
                "claim_ids": ["source-claim"],
                "basis_risks": ["Equity returns can diverge from commodity prices."],
                "verification_questions": ["Does an accessible suitable instrument exist?"],
                "uncertainty": "Neither availability nor the economic relationship is verified.",
                "availability": "unverified"}])
        metadata["content"] = canonical_json(document)
        return metadata


def assessed_drivers(drivers, claim_id):
    assessment = driver_assessment_example(drivers)
    for review in assessment["approved_drivers"]:
        review["premise"].update(status="supports", claim_ids=[claim_id],
            reasoning="The retained fictional report supports the stated condition.")
        review["mechanism"].update(status="challenges", claim_ids=[claim_id],
            reasoning="The report motivates a competing mechanism; causation remains unresolved.")
    assessment["progression"].update(status="progressing", claim_ids=[claim_id],
        reasoning="The reported development could advance the idea despite the attribution question.")
    assessment["attention"].update(status="review_recommended", driver_indices=list(range(len(drivers))),
        claim_ids=[claim_id], reasoning="Review the central proposed mechanism before relying on it.")
    return assessment


class RecordedDriverSynthesisModel(research_fixtures.RecordedSynthesisModel):
    def complete(self, model_id, messages):
        metadata = super().complete(model_id, messages)
        document = json.loads(metadata["content"])
        context = json.loads(messages[1]["content"])
        document["schema_version"] = daily_synthesis.DRIVER_SCHEMA_VERSION
        document["driver_assessment"] = assessed_drivers(
            context["original_inputs"]["approved_user"]["interpretation"]["drivers"], "policy")
        metadata["content"] = canonical_json(document)
        return metadata


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="fixture-key",
    SETTINGS_MODULE="macro_agent.web.local_settings")
class DriverResearchAPITests(TransactionTestCase):
    capture = fixtures.DailyReviewReadAPITests.capture
    review = fixtures.DailyReviewReadAPITests.review
    post = research_fixtures.ResearchEngineAPITests.post
    prepare = research_fixtures.ResearchEngineAPITests.prepare
    evidence_path = research_fixtures.ResearchEngineAPITests.evidence_path
    synthesis_path = research_fixtures.ResearchEngineAPITests.synthesis_path

    def setUp(self):
        fixtures.DailyReviewReadAPITests.setUp(self)
        CompilationBudget.objects.get_or_create(pk=1)
        self.revision_id = str(SourceRevision.objects.get(report__source_id=fixtures.SOURCE).pk)
        self.source_model, self.synthesis_model = RecordedDriverResearchModel(), RecordedDriverSynthesisModel()
        for module, adapter in ((compilation, self.source_model), (synthesis, self.synthesis_model)):
            mocked = patch.object(module, "create_provider", return_value=adapter)
            mocked.start()
            self.addCleanup(mocked.stop)

    def compile_driver(self):
        created = self.post("/api/v1/theses/", {"command_id": str(uuid4()), "text": EXACT,
            "interpretation": {"drivers": [], "horizon": None, "invalidation_signposts": []}})
        self.assertEqual(created.status_code, 201, created.content)
        draft = created.json()["thesis"]
        _, packet = self.prepare(thesis_id=draft["id"])
        command = {"command_id": str(uuid4()), "expected_revision": draft["revision"],
            "provider_id": "nanogpt", "model_id": model_fixtures.MODEL_ID,
            "evidence_context_id": packet["evidence"]["id"], "driver_review": True}
        path = f"/api/v1/theses/{draft['id']}/compile/"
        response = self.post(path, command)
        self.assertEqual(response.status_code, 200, response.content)
        saved = response.json()
        self.assertEqual(saved["compilation"]["status"], "compiled", saved)
        return draft, packet, command, saved

    def approval_body(self, saved):
        thesis = saved["thesis"]
        text, meaning = thesis["draft"]["text_version"], thesis["draft"]["interpretation"]
        return {"command_id": str(uuid4()), "expected_revision": thesis["revision"],
            "thesis_version_id": text["id"], "text_digest": text["text_digest"],
            "interpretation_version_id": meaning["id"], "interpretation_digest": meaning["digest"]}

    def test_broad_research_roundtrip_approval_keeps_proposals_separate_and_creates_no_monitor(self):
        before = (WatchRecord.objects.count(), PositionRecord.objects.count(), NotificationIntent.objects.count())
        draft, packet, command, saved = self.compile_driver()
        serializer = CompilationResponseSerializer(data=saved)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        represented = CompilationResponseSerializer(instance=saved).data
        document = saved["compilation"]["document"]
        self.assertEqual(represented["compilation"]["document"]["proposed_drivers"], document["proposed_drivers"])
        self.assertEqual(represented["compilation"]["document"]["exposure_candidates"], document["exposure_candidates"])
        self.assertEqual(saved["compilation"]["schema_version"], research_compilation.SOURCED_SCHEMA_VERSION)
        card = saved["thesis"]["draft"]["interpretation"]["review_card"]
        self.assertEqual(card["schema_version"], research_compilation.CARD_SCHEMA_VERSION)
        self.assertEqual(card["inputs"][0]["exact_text"], EXACT)
        self.assertEqual(card["evidence"]["context"], packet["evidence"]["content"])
        self.assertEqual(represented["thesis"]["draft"]["interpretation"]["review_card"], card)
        self.assertIsNone(saved["thesis"]["approved"])
        self.assertEqual(saved["thesis"]["monitoring"], "not_configured")
        self.assertEqual(document["exposure_candidates"][0]["availability"], "unverified")
        self.assertNotIn("monitoring_coverage", document["exposure_candidates"][0])
        response = self.post(f"/api/v1/theses/{draft['id']}/approvals/", self.approval_body(saved))
        self.assertEqual(response.status_code, 200, response.content)
        approved = response.json()["thesis"]["approved"]
        self.assertEqual(approved["text_version"]["exact_text"], EXACT)
        self.assertEqual(approved["interpretation"]["drivers"], [DRIVER])
        self.assertEqual(approved["interpretation"]["review_card"], card)
        self.assertEqual(approved["interpretation"]["origin"], "model_compilation")
        self.assertEqual(before, (WatchRecord.objects.count(), PositionRecord.objects.count(),
                                 NotificationIntent.objects.count()))
        attempt = CompilationAttempt.objects.get(command_id=command["command_id"])
        self.assertEqual(str(attempt.evidence_context_id), packet["evidence"]["id"])
        self.assertEqual(attempt.configuration["prompt_version"], research_compilation.PROMPT_VERSION)
        self.assertEqual((self.source_model.catalog_calls, self.source_model.completion_calls), (1, 1))

    def test_correction_blocks_new_approval_and_recovery_needs_no_provider_or_key(self):
        draft, _, command, saved = self.compile_driver()
        self.capture(title="A corrected fictional source")
        before = ApprovalRecord.objects.count()
        path = f"/api/v1/theses/{draft['id']}"
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch.object(compilation, "create_provider", side_effect=AssertionError("No provider on recovery")), \
                patch.object(capture, "capture", side_effect=AssertionError("No source fetch on recovery")):
            for route in (f"{path}/compilation-commands/{command['command_id']}/",
                          f"{path}/compilations/{saved['compilation']['id']}/"):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200, response.content)
                recovered = response.json()["compilation"]
                self.assertEqual(recovered["document"], saved["compilation"]["document"])
                self.assertEqual(recovered["status"], "compiled")
                self.assertEqual(recovered["evidence_disposition"]["status"], "stale")
            replay = self.post(path + "/compile/", command)
            self.assertEqual(replay.status_code, 200, replay.content)
            denied = self.post(path + "/approvals/", self.approval_body(saved))
            self.assertEqual(denied.status_code, 409, denied.content)
        self.assertEqual(ApprovalRecord.objects.count(), before)
        self.assertEqual(CompilationAttempt.objects.count(), 1)
        self.assertEqual((self.source_model.catalog_calls, self.source_model.completion_calls), (1, 1))

    def test_driver_compilation_requires_source_packet_and_rejects_boolean_coercion(self):
        path = f"/api/v1/theses/{self.thesis['id']}/compile/"
        _, packet = self.prepare()
        command = {"command_id": str(uuid4()), "expected_revision": self.thesis["revision"],
            "provider_id": "nanogpt", "model_id": model_fixtures.MODEL_ID,
            "evidence_context_id": packet["evidence"]["id"]}
        for value in ("true", "false", 1, 0, None, [], {}):
            with self.subTest(value=value):
                response = self.post(path, {**command, "driver_review": value})
                self.assertEqual(response.status_code, 400, response.content)
        no_packet = {key: value for key, value in command.items() if key != "evidence_context_id"}
        response = self.post(path, {**no_packet, "driver_review": True})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(CompilationAttempt.objects.exists())
        self.assertEqual((self.source_model.catalog_calls, self.source_model.completion_calls), (0, 0))

    def test_driver_profile_still_requires_csrf_and_owner_scope(self):
        _, packet = self.prepare()
        path = f"/api/v1/theses/{self.thesis['id']}/compile/"
        command = {"command_id": str(uuid4()), "expected_revision": self.thesis["revision"],
            "provider_id": "nanogpt", "model_id": model_fixtures.MODEL_ID,
            "evidence_context_id": packet["evidence"]["id"], "driver_review": True}
        self.assertEqual(self.post(path, command, token=False).status_code, 403)
        foreign = Client(enforce_csrf_checks=True)
        foreign.force_login(self.other)
        denied = self.post(path, command, client=foreign)
        self.assertEqual(denied.status_code, 404, denied.content)
        self.assertEqual(denied.json(), self.post(f"/api/v1/theses/{uuid4()}/compile/", command,
                                                  client=foreign).json())
        self.assertFalse(CompilationAttempt.objects.exists())
        self.assertEqual(self.source_model.catalog_calls, 0)

    def test_daily_driver_review_roundtrip_has_no_trade_or_notification_requirement(self):
        review = self.review()["review"]
        command = {"command_id": str(uuid4()), "expected_review_digest": review["digest"],
            "provider_id": "nanogpt", "model_id": model_fixtures.MODEL_ID, "driver_review": True}
        response = self.post(self.synthesis_path(review["id"]), command)
        self.assertEqual(response.status_code, 200, response.content)
        saved = response.json()
        self.assertEqual(saved["synthesis"]["status"], "synthesised", saved)
        serializer = SynthesisResponseSerializer(data=saved)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        represented = SynthesisResponseSerializer(instance=saved).data
        assessment = saved["synthesis"]["document"]["driver_assessment"]
        self.assertEqual(represented["synthesis"]["document"]["driver_assessment"], assessment)
        self.assertEqual(assessment["approved_drivers"][0]["exact_driver"], fixtures.MEANING["drivers"][0])
        self.assertEqual(assessment["approved_drivers"][0]["mechanism"]["status"], "challenges")
        self.assertEqual(assessment["progression"]["status"], "progressing")
        self.assertEqual(assessment["attention"]["status"], "review_recommended")
        self.assertEqual(assessment["price_observation"]["status"], "unavailable")
        self.assertEqual(assessment["entry_assessment"]["status"], "not_assessed")
        self.assertEqual(saved["synthesis"]["context"]["review"], review["content"])
        self.assertFalse(saved["current_disposition"]["publication_authority"])
        self.assertFalse(PositionRecord.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertFalse(CurrentAssessment.objects.exists())

    def test_daily_driver_profile_rejects_coerced_boolean_before_model_work(self):
        review = self.review()["review"]
        command = {"command_id": str(uuid4()), "expected_review_digest": review["digest"],
            "provider_id": "nanogpt", "model_id": model_fixtures.MODEL_ID}
        for value in ("true", 1, 0, None):
            with self.subTest(value=value):
                response = self.post(self.synthesis_path(review["id"]), {**command, "driver_review": value})
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual((self.synthesis_model.catalog_calls, self.synthesis_model.completion_calls), (0, 0))


class RecordedDriverNewsModel(news_fixtures.RecordedNewsModel):
    def complete(self, model_id, messages):
        metadata = super().complete(model_id, messages)
        context = json.loads(messages[1]["content"])
        document = json.loads(metadata["content"])
        document["schema_version"] = news_analysis.DRIVER_SCHEMA_VERSION
        document["driver_assessment"] = assessed_drivers(context["approved_thesis"]["drivers"], "f1")
        metadata["content"] = canonical_json(document)
        return metadata


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    MACRO_ENABLE_NEWS_ANALYSIS=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="fixture-key", MACRO_ALLOW_SYNTHETIC_SETUP=True,
    SETTINGS_MODULE="macro_agent.web.local_settings")
class DriverNewsAPITests(TransactionTestCase):
    post = news_fixtures.NewsAnalysisAPITests.post
    body = news_fixtures.NewsAnalysisAPITests.body

    def setUp(self):
        news_fixtures.NewsAnalysisAPITests.setUp(self)
        self.adapter = RecordedDriverNewsModel()
        self.constructor.return_value = self.adapter

    def test_news_driver_roundtrip_preserves_reassessment_and_has_no_publication_authority(self):
        command = self.body(driver_review=True)
        response = self.post(self.path, command)
        self.assertEqual(response.status_code, 200, response.content)
        saved = response.json()
        self.assertEqual(saved["analysis"]["status"], "analysed", saved)
        serializer = NewsAnalysisResponseSerializer(data=saved)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        represented = NewsAnalysisResponseSerializer(instance=saved).data
        assessment = saved["analysis"]["document"]["driver_assessment"]
        self.assertEqual(represented["analysis"]["document"]["driver_assessment"], assessment)
        self.assertEqual(assessment["approved_drivers"][0]["exact_driver"], news_fixtures.MEANING["drivers"][0])
        self.assertEqual(assessment["attention"]["status"], "review_recommended")
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertFalse(CurrentAssessment.objects.exists())
        lookup = f"/api/v1/theses/{self.thesis_id}/news-commands/{command['command_id']}/"
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch.object(analysis, "create_provider", side_effect=AssertionError("No recovery inference")):
            recovery = self.client.get(lookup)
        self.assertEqual(recovery.status_code, 200, recovery.content)
        self.assertEqual(recovery.json()["analysis"]["document"], saved["analysis"]["document"])
        self.assertEqual(self.adapter.completion_calls, 1)

    def test_news_driver_profile_rejects_coerced_boolean_before_any_call(self):
        for value in ("true", "false", 1, 0, None):
            with self.subTest(value=value):
                response = self.post(self.path, self.body(driver_review=value))
                self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(NewsAnalysisAttempt.objects.exists())
        self.assertEqual((self.adapter.catalog_calls, self.adapter.completion_calls), (0, 0))
