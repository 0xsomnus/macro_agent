"""Private session research, exact sourced review and no-call recovery."""

from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import json
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.test import Client, TransactionTestCase, override_settings
from drf_spectacular.validation import validate_schema

from macro_agent.api.compilation_serializers import CompilationResponseSerializer
from macro_agent.api.research_serializers import EvidenceResponseSerializer
from macro_agent.api.synthesis_serializers import SynthesisResponseSerializer
from macro_agent.api.tests import test_compilation_api as model_fixtures
from macro_agent.api.tests import test_desk_api as fixtures
from macro_agent.desk import permissions, synthesis
from macro_agent.desk.models import DailyReview
from macro_agent.desk.research_models import ResearchEvidenceContext, ResearchEvidenceMember
from macro_agent.desk.synthesis_models import DailySynthesisAttempt, DailySynthesisResult
from macro_agent.domain import daily_synthesis, sourced_compilation
from macro_agent.domain.models import canonical_json
from macro_agent.monitoring import capture
from macro_agent.monitoring.models import SourceRevision, SourceState
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.positions import service as positions
from macro_agent.theses import compilation, service as theses
from macro_agent.theses.models import ApprovalRecord, CompilationAttempt, CompilationBudget


class RecordedSourcedModel(model_fixtures.RecordedModel):
    def complete(self, model_id, messages):
        metadata = super().complete(model_id, messages)
        data = json.loads(messages[1]["content"])
        document = json.loads(metadata["content"])
        document["interpretation"]["drivers"] = ["Easier policy may support equities."]
        document["grounding"][0]["exact_quote"] = "Easier policy may support equities."
        report = data["evidence"]["reports"][0]
        document.update(attributed_claims=[{"claim_id": "policy", "revision_id": report["revision_id"],
            "field": "title", "exact_quote": report["title"]}], factual_conflicts=[],
            evidence_assessment={"summary": "A fictional report is retained for review.",
                "supporting_claim_ids": ["policy"], "counter_claim_ids": [],
                "gaps": ["Current macro context and market expectations remain unavailable."]})
        metadata["content"] = canonical_json(document)
        return metadata


class RecordedSynthesisModel(model_fixtures.RecordedModel):
    def complete(self, model_id, messages):
        metadata = super().complete(model_id, messages)
        context = json.loads(messages[1]["content"])
        reports = [item for group in ("new", "background") for item in context["review"]["reports"][group]]
        claims = [{"claim_id": "policy", "source_revision_id": reports[0]["revision_id"], "source_field": "title",
            "quote": reports[0]["payload"]["title"]}] if reports else []
        refs = ["policy"] if claims else []
        section = {"text": "The possible policy effect remains conditional.", "claim_ids": refs,
                   "prior_analysis_ids": [], "uncertainty": "The report does not establish transmission."}
        effect = {"effect": "supports" if claims else "unresolved", "reasoning": section["text"],
                  **{key: section[key] for key in ("claim_ids", "prior_analysis_ids", "uncertainty")}}
        book = context["original_inputs"]["approved_user"]["exposure"]["positions"]
        metadata["content"] = canonical_json({"schema_version": daily_synthesis.SCHEMA_VERSION,
            "attributed_claims": claims, "overview": section, "thesis_effect": effect,
            "trade_effects": [{**effect, "position_id": row["position_id"],
                "effect": "potential_risk" if claims else "unresolved"}
                for row in book if row["payload"]["status"] == "open"],
            "counter_case": deepcopy(section), "watch_questions": ["Does transmission improve?"],
            "gaps": ["The current macro regime remains unavailable."]})
        return metadata


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="fixture-key",
    SETTINGS_MODULE="macro_agent.web.local_settings")
class ResearchEngineAPITests(TransactionTestCase):
    capture = fixtures.DailyReviewReadAPITests.capture
    review = fixtures.DailyReviewReadAPITests.review

    def setUp(self):
        fixtures.DailyReviewReadAPITests.setUp(self)
        CompilationBudget.objects.get_or_create(pk=1)
        self.token = self.client.get("/api/v1/session/").json()["csrf_token"]
        self.revision_id = str(SourceRevision.objects.get(report__source_id=fixtures.SOURCE).pk)
        self.source_model = RecordedSourcedModel()
        self.synthesis_model = RecordedSynthesisModel()
        for module, adapter in ((compilation, self.source_model), (synthesis, self.synthesis_model)):
            mocked = patch.object(module, "create_provider", return_value=adapter)
            mocked.start()
            self.addCleanup(mocked.stop)

    def evidence_path(self, thesis_id=None):
        return f"/api/v1/theses/{thesis_id or self.thesis['id']}/evidence/"

    def evidence_command_path(self, command, thesis_id=None):
        return f"/api/v1/theses/{thesis_id or self.thesis['id']}/evidence-commands/{command}/"

    def evidence_detail_path(self, context_id, thesis_id=None):
        return self.evidence_path(thesis_id) + context_id + "/"

    def synthesis_path(self, review_id):
        return f"/api/v1/daily-reviews/{review_id}/synthesise/"

    def synthesis_command_path(self, review_id, command_id):
        return f"/api/v1/daily-reviews/{review_id}/synthesis-commands/{command_id}/"

    def synthesis_detail_path(self, attempt_id):
        return f"/api/v1/daily-syntheses/{attempt_id}/"

    def post(self, path, body, *, client=None, token=True, raw=False):
        current = client or self.client
        headers = ({"HTTP_X_CSRFTOKEN": current.get("/api/v1/session/").json()["csrf_token"]}
                   if token else {})
        return current.post(path, body if raw else json.dumps(body), content_type="application/json", **headers)

    def prepare(self, *, thesis_id=None):
        command = {"command_id": str(uuid4()), "revision_ids": [self.revision_id]}
        response = self.post(self.evidence_path(thesis_id), command)
        self.assertEqual(response.status_code, 200, response.content)
        serializer = EvidenceResponseSerializer(data=response.json())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return command, response.json()

    def compile_source(self):
        draft = theses.create_thesis(self.actor, str(uuid4()), fixtures.EXACT,
            {"drivers": [], "horizon": None, "invalidation_signposts": []})["thesis"]
        _, prepared = self.prepare(thesis_id=draft["id"])
        command = {"command_id": str(uuid4()), "expected_revision": draft["revision"],
            "provider_id": "nanogpt", "model_id": model_fixtures.MODEL_ID,
            "evidence_context_id": prepared["evidence"]["id"]}
        path = f"/api/v1/theses/{draft['id']}/compile/"
        response = self.post(path, command)
        self.assertEqual(response.status_code, 200, response.content)
        serializer = CompilationResponseSerializer(data=response.json())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return draft, prepared, command, response.json()

    def synthesize(self):
        positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
            self.thesis["approved"]["approval"]["id"], fixtures.DECLARATION)
        review = self.review()["review"]
        command = {"command_id": str(uuid4()), "expected_review_digest": review["digest"],
            "provider_id": "nanogpt", "model_id": model_fixtures.MODEL_ID}
        response = self.post(self.synthesis_path(review["id"]), command)
        self.assertEqual(response.status_code, 200, response.content)
        serializer = SynthesisResponseSerializer(data=response.json())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return review, command, response.json()

    def test_prepare_retains_exact_source_and_has_no_thesis_or_model_authority(self):
        before_approvals = ApprovalRecord.objects.count()
        command, saved = self.prepare()
        source = SourceRevision.objects.get(pk=self.revision_id)
        report = saved["evidence"]["content"]["reports"][0]
        self.assertEqual(report["content"], source.payload["content"])
        self.assertEqual(report["title"], source.payload["title"])
        self.assertEqual(report["revision_id"], report["head_at_admission_id"])
        self.assertEqual(saved["evidence"]["command_id"], command["command_id"])
        self.assertEqual(saved["current_disposition"]["status"], "current")
        self.assertEqual(ResearchEvidenceMember.objects.count(), 1)
        self.assertEqual(ApprovalRecord.objects.count(), before_approvals)
        self.assertEqual(CompilationAttempt.objects.count(), 0)
        self.assertEqual(self.source_model.catalog_calls, 0)

    def test_evidence_recovery_after_correction_preserves_original_without_fetches_or_writes(self):
        command, original = self.prepare()
        self.capture(title="Fictional correction")
        before = (ResearchEvidenceContext.objects.count(), ResearchEvidenceMember.objects.count())
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch.object(capture, "capture", side_effect=AssertionError("GET must not fetch")):
            for path in (self.evidence_detail_path(original["evidence"]["id"]),
                         self.evidence_command_path(command["command_id"])):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["evidence"], original["evidence"])
                self.assertEqual(response.json()["current_disposition"]["status"], "stale")
                self.assertEqual(response["Cache-Control"], "no-store")
            replay = self.post(self.evidence_path(), command)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertTrue(replay.json()["replayed"])
        self.assertEqual(before, (ResearchEvidenceContext.objects.count(), ResearchEvidenceMember.objects.count()))

    def test_evidence_writes_require_csrf_and_reject_unknown_duplicate_and_coerced_fields(self):
        valid = {"command_id": str(uuid4()), "revision_ids": [self.revision_id]}
        self.assertEqual(self.post(self.evidence_path(), valid, token=False).status_code, 403)
        mutations = [{**valid, "owner_id": self.actor}, {**valid, "revision_ids": self.revision_id},
            {**valid, "revision_ids": [self.revision_id, self.revision_id]},
            {**valid, "revision_ids": []}, {**valid, "revision_ids": [True]},
            {**valid, "command_id": 5}]
        for body in mutations:
            with self.subTest(body=body):
                self.assertEqual(self.post(self.evidence_path(), body).status_code, 400)
        duplicate = json.dumps(valid)[:-1] + ',"revision_ids":[]}'
        self.assertEqual(self.post(self.evidence_path(), duplicate, raw=True).status_code, 400)
        self.assertEqual(ResearchEvidenceContext.objects.count(), 0)

    def test_evidence_foreign_staff_and_missing_ids_are_opaque(self):
        command, saved = self.prepare()
        foreign = Client(enforce_csrf_checks=True)
        foreign.force_login(self.other)
        pairs = ((self.evidence_detail_path(saved["evidence"]["id"]), self.evidence_detail_path(str(uuid4()))),
                 (self.evidence_command_path(command["command_id"]), self.evidence_command_path(str(uuid4()))))
        for path, absent in pairs:
            denied = foreign.get(path)
            self.assertEqual(denied.status_code, 404)
            self.assertEqual(denied.json(), foreign.get(absent).json())
            self.assertEqual(Client().get(path).status_code, 403)
            self.assertEqual(self.client.get(path + "?retry=1").status_code, 400)
        body = {"command_id": str(uuid4()), "revision_ids": [self.revision_id]}
        denied = self.post(self.evidence_path(), body, client=foreign)
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(denied.json(), self.post(self.evidence_path(str(uuid4())), body, client=foreign).json())

    def test_sourced_compilation_roundtrip_binds_exact_card_without_approval(self):
        draft, prepared, command, saved = self.compile_source()
        attempt = saved["compilation"]
        self.assertEqual(attempt["status"], "compiled")
        self.assertEqual(attempt["schema_version"], sourced_compilation.SOURCED_SCHEMA_VERSION)
        self.assertEqual(attempt["evidence_context"]["content"], prepared["evidence"]["content"])
        card = saved["thesis"]["draft"]["interpretation"]["review_card"]
        self.assertEqual(card["evidence"], {"status": "retained_sources", "context": prepared["evidence"]["content"]})
        self.assertEqual(card["inputs"][0]["exact_text"], fixtures.EXACT)
        self.assertIsNone(saved["thesis"]["approved"])
        self.assertEqual(self.source_model.completion_calls, 1)
        lookup = f"/api/v1/theses/{draft['id']}/compilation-commands/{command['command_id']}/"
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch.object(compilation, "create_provider", side_effect=AssertionError("Recovery cannot call")):
            response = self.client.get(lookup)
            self.assertEqual(response.status_code, 200, response.content)
            replay = self.post(f"/api/v1/theses/{draft['id']}/compile/", command)
            self.assertEqual(replay.status_code, 200, replay.content)
        recovered = response.json()["compilation"]
        original_disposition = attempt.pop("evidence_disposition")
        observed_disposition = recovered.pop("evidence_disposition")
        self.assertEqual(recovered, attempt)
        self.assertEqual(observed_disposition["status"], original_disposition["status"])
        self.assertEqual(observed_disposition["stale_reasons"], original_disposition["stale_reasons"])
        self.assertEqual(CompilationAttempt.objects.count(), 1)

    def test_sourced_compile_rejects_unknown_or_foreign_context_before_model_work(self):
        command, prepared = self.prepare()
        path = f"/api/v1/theses/{self.thesis['id']}/compile/"
        valid = {"command_id": str(uuid4()), "expected_revision": self.thesis["revision"],
            "provider_id": "nanogpt", "model_id": model_fixtures.MODEL_ID,
            "evidence_context_id": prepared["evidence"]["id"]}
        self.assertEqual(self.post(path, {**valid, "source_text": "Forged article"}).status_code, 400)
        self.assertEqual(self.post(path, {**valid, "evidence_context_id": True}).status_code, 400)
        other = theses.create_thesis(self.actor, str(uuid4()), fixtures.EXACT, fixtures.MEANING)["thesis"]
        wrong = {**valid, "expected_revision": other["revision"]}
        self.assertEqual(self.post(f"/api/v1/theses/{other['id']}/compile/", wrong).status_code, 404)
        self.assertEqual(self.source_model.catalog_calls, 0)
        self.assertEqual(CompilationAttempt.objects.count(), 0)

    def test_synthesis_keeps_digest_unchanged_and_separates_thesis_from_trade_effect(self):
        review, command, saved = self.synthesize()
        result = saved["synthesis"]
        self.assertEqual(result["status"], "synthesised")
        self.assertEqual(result["context"]["review"], review["content"])
        self.assertEqual(result["document"]["thesis_effect"]["effect"], "supports")
        self.assertEqual(result["document"]["trade_effects"][0]["effect"], "potential_risk")
        self.assertEqual(result["command_id"], command["command_id"])
        self.assertFalse(saved["current_disposition"]["publication_authority"])
        self.assertEqual(NotificationIntent.objects.count(), 0)
        self.assertEqual(CurrentAssessment.objects.count(), 0)
        self.assertEqual(DailyReview.objects.get(pk=review["id"]).digest, review["digest"])

    def test_synthesis_retry_and_gets_after_correction_are_read_only_and_keep_original_decision(self):
        review, command, original = self.synthesize()
        self.capture(title="Changed after synthesis")
        before = (DailySynthesisAttempt.objects.count(), DailySynthesisResult.objects.count())
        paths = (self.synthesis_detail_path(original["synthesis"]["id"]),
                 self.synthesis_command_path(review["id"], command["command_id"]))
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch.object(synthesis, "create_provider", side_effect=AssertionError("No retry")), \
                patch.object(capture, "capture", side_effect=AssertionError("No source call")):
            for path in paths:
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["synthesis"], original["synthesis"])
                self.assertEqual(response.json()["current_disposition"]["status"], "stale")
                self.assertEqual(response["Cache-Control"], "no-store")
            replay = self.post(self.synthesis_path(review["id"]), command)
            self.assertEqual(replay.status_code, 200, replay.content)
            self.assertTrue(replay.json()["replayed"])
        self.assertEqual(before, (DailySynthesisAttempt.objects.count(), DailySynthesisResult.objects.count()))
        self.assertEqual(self.synthesis_model.completion_calls, 1)

    def test_synthesis_writes_require_csrf_and_strict_exact_command(self):
        review = self.review()["review"]
        valid = {"command_id": str(uuid4()), "expected_review_digest": review["digest"],
            "provider_id": "nanogpt", "model_id": model_fixtures.MODEL_ID}
        self.assertEqual(self.post(self.synthesis_path(review["id"]), valid, token=False).status_code, 403)
        for changed in ({**valid, "publish": True}, {**valid, "owner_id": self.actor},
                        {**valid, "expected_review_digest": True}, {**valid, "model_id": 7}):
            self.assertEqual(self.post(self.synthesis_path(review["id"]), changed).status_code, 400)
        raw = json.dumps(valid)[:-1] + ',"expected_review_digest":"' + review["digest"] + '"}'
        self.assertEqual(self.post(self.synthesis_path(review["id"]), raw, raw=True).status_code, 400)
        wrong = {**valid, "expected_review_digest": "0" * 64}
        self.assertEqual(self.post(self.synthesis_path(review["id"]), wrong).status_code, 409)
        self.assertEqual(self.synthesis_model.catalog_calls, 0)
        self.assertEqual(DailySynthesisAttempt.objects.count(), 0)

    def test_synthesis_private_scope_includes_staff_and_command_recovery(self):
        review, command, saved = self.synthesize()
        foreign = Client(enforce_csrf_checks=True)
        foreign.force_login(self.other)
        paths = ((self.synthesis_detail_path(saved["synthesis"]["id"]), self.synthesis_detail_path(str(uuid4()))),
            (self.synthesis_command_path(review["id"], command["command_id"]),
             self.synthesis_command_path(str(uuid4()), str(uuid4()))))
        for path, absent in paths:
            self.assertEqual(foreign.get(path).status_code, 404)
            self.assertEqual(foreign.get(path).json(), foreign.get(absent).json())
            self.assertEqual(Client().get(path).status_code, 403)
            self.assertEqual(self.client.get(path + "?retry=1").status_code, 400)
        denied = self.post(self.synthesis_path(review["id"]), command, client=foreign)
        missing = self.post(self.synthesis_path(str(uuid4())), command, client=foreign)
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(denied.json(), missing.json())
        self.assertEqual(self.synthesis_model.completion_calls, 1)

    def test_missing_recovery_is_missing_and_cannot_create_evidence_or_synthesis(self):
        review = self.review()["review"]
        for path in (self.evidence_command_path(str(uuid4())),
                     self.synthesis_command_path(review["id"], str(uuid4()))):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(ResearchEvidenceContext.objects.count(), 0)
        self.assertEqual(DailySynthesisAttempt.objects.count(), 0)
        self.assertEqual(self.source_model.catalog_calls + self.synthesis_model.catalog_calls, 0)

    def test_permission_withdrawal_preserves_saved_packets_but_blocks_new_compilation(self):
        _, prepared = self.prepare()
        source = SourceState.objects.get(pk=fixtures.SOURCE)
        permissions.set_source_permission(str(self.other.pk), fixtures.SOURCE,
            source.contract_digest, False, "Explicit recorded API withdrawal")
        detail = self.client.get(self.evidence_detail_path(prepared["evidence"]["id"]))
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.json()["current_disposition"]["status"], "stale")
        body = {"command_id": str(uuid4()), "expected_revision": self.thesis["revision"],
            "provider_id": "nanogpt", "model_id": model_fixtures.MODEL_ID,
            "evidence_context_id": prepared["evidence"]["id"]}
        response = self.post(f"/api/v1/theses/{self.thesis['id']}/compile/", body)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(self.source_model.catalog_calls, 0)

    def test_generated_schema_describes_strict_session_research_and_separate_synthesis(self):
        errors, output = StringIO(), StringIO()
        with redirect_stderr(errors):
            call_command("spectacular", "--validate", "--fail-on-warn", "--format", "openapi-json", stdout=output)
        self.assertEqual(errors.getvalue(), "")
        schema = json.loads(output.getvalue())
        validate_schema(schema)
        selected = schema["paths"]["/api/v1/theses/{thesis_id}/evidence/"]
        synthesis_path = schema["paths"]["/api/v1/daily-reviews/{review_id}/synthesise/"]
        self.assertEqual(set(selected), {"post"})
        self.assertEqual(set(synthesis_path), {"post"})
        for operation in (selected["post"], synthesis_path["post"]):
            self.assertEqual(operation["security"], [{"cookieAuth": []}])
            reference = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
            self.assertIs(schema["components"]["schemas"][reference]["additionalProperties"], False)
        components = schema["components"]["schemas"]
        reference = schema["paths"]["/api/v1/theses/{thesis_id}/compile/"]["post"][
            "requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        self.assertIn("evidence_context_id", components[reference]["properties"])
        self.assertNotIn("evidence_context_id", components[reference]["required"])
        self.assertIn("429", synthesis_path["post"]["responses"])
        self.assertIn("503", synthesis_path["post"]["responses"])
