"""Exact answer retention, rich approval and read-only recovery over sessions."""

import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase, override_settings

from macro_agent.api.compilation_serializers import CompilationResponseSerializer, RefinementResponseSerializer
from macro_agent.api.news_analysis_serializers import NewsReviewContextSerializer
from macro_agent.api.tests.test_compilation_api import MODEL_ID, RecordedModel
from macro_agent.theses import compilation, service
from macro_agent.theses.models import CompilationBudget, RefinementSubmission


class AnswerAwareModel(RecordedModel):
    def complete(self, model_id, messages):
        result = super().complete(model_id, messages)
        envelope = json.loads(messages[1]["content"])
        document = json.loads(result["content"])
        document["review_card"]["affected_assets"] = {"extracted": [{
            "text": "Gold, instrument mapping remains unverified.", "input_id": "thesis",
            "exact_quote": "Gold"}], "proposed": [], "gap": "No actual instrument supplied."}
        document["review_card"]["catalysts"]["proposed"] = [
            "Unverified candidate: investigate changes in real yields."]
        answers = envelope.get("refinement_inputs", [])
        if answers:
            answer = answers[0]
            document["interpretation"]["horizon"] = answer["exact_answer"]
            document["grounding"].append({"field": "horizon", "index": None,
                "input_id": answer["input_id"], "exact_quote": answer["exact_answer"]})
        result["content"] = json.dumps(document)
        return result


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_ENABLE_NEWS_ANALYSIS=True,
    MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="fixture-key",
    SETTINGS_MODULE="macro_agent.web.local_settings")
class RefinementAPITests(TransactionTestCase):
    def setUp(self):
        CompilationBudget.objects.get_or_create(pk=1)
        self.owner = get_user_model().objects.create_user(username="refine-api-owner")
        self.other = get_user_model().objects.create_user(username="refine-api-staff", is_staff=True)
        self.actor = str(self.owner.pk)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)
        self.token = self.client.get("/api/v1/session/").json()["csrf_token"]
        self.text = "  Gold may benefit if real yields fall.\r\nΔ"
        self.empty = {"drivers": [], "horizon": None, "invalidation_signposts": []}
        self.thesis = service.create_thesis(self.actor, str(uuid4()), self.text, self.empty)["thesis"]
        self.base = f"/api/v1/theses/{self.thesis['id']}/"
        self.adapter = AnswerAwareModel()
        mocked = patch.object(compilation, "create_provider", return_value=self.adapter)
        self.constructor = mocked.start()
        self.addCleanup(mocked.stop)

    def post(self, suffix, body, *, client=None, token=None):
        return (client or self.client).post(self.base + suffix, json.dumps(body),
            content_type="application/json", HTTP_X_CSRFTOKEN=token or self.token)

    def compile(self, thesis=None, **extra):
        thesis = thesis or self.thesis
        response = self.post("compile/", {"command_id": str(uuid4()),
            "expected_revision": thesis["revision"], "provider_id": "nanogpt",
            "model_id": MODEL_ID, **extra})
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["compilation"]["status"], "compiled", data)
        serializer = CompilationResponseSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return data

    def answer_body(self, parent, **extra):
        return {"command_id": str(uuid4()), "expected_revision": parent["thesis"]["revision"],
            "parent_attempt_id": parent["compilation"]["id"],
            "answers": [{"question_index": 0, "exact_answer": "  Six weeks.\r\nΔ"}], **extra}

    def save(self, parent, body=None):
        response = self.post("refinements/", body or self.answer_body(parent))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        serializer = RefinementResponseSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return data

    def test_refinement_approval_and_news_context_preserve_exact_inputs_and_labels(self):
        first = self.compile()
        saved = self.save(first)
        self.assertEqual(saved["thesis"], first["thesis"])
        self.assertEqual(self.adapter.completion_calls, 1)
        second = self.compile(saved["thesis"], refinement_id=saved["refinement"]["id"])
        thesis = second["thesis"]
        draft = thesis["draft"]
        answer = saved["refinement"]["answers"][0]["exact_answer"]
        self.assertEqual(draft["text_version"]["exact_text"], self.text)
        self.assertEqual(draft["interpretation"]["horizon"], answer)
        card = draft["interpretation"]["review_card"]
        self.assertEqual(card["inputs"][0]["exact_text"], self.text)
        self.assertEqual(card["inputs"][1]["exact_answer"], answer)
        self.assertEqual(card["evidence"], {"status": "unavailable", "references": []})
        self.assertIsNone(thesis["approved"])
        command = {"command_id": str(uuid4()), "expected_revision": thesis["revision"],
            "thesis_version_id": draft["text_version"]["id"],
            "text_digest": draft["text_version"]["text_digest"],
            "interpretation_version_id": draft["interpretation"]["id"],
            "interpretation_digest": first["thesis"]["draft"]["interpretation"]["digest"]}
        self.assertEqual(self.post("approvals/", command).status_code, 409)
        command["command_id"] = str(uuid4())
        command["interpretation_digest"] = draft["interpretation"]["digest"]
        approved = self.post("approvals/", command)
        self.assertEqual(approved.status_code, 200, approved.content)
        context = self.client.get(self.base + "news-context/")
        self.assertEqual(context.status_code, 200, context.content)
        wire = NewsReviewContextSerializer(data=context.json())
        self.assertTrue(wire.is_valid(), wire.errors)
        self.assertEqual(context.json()["approved_interpretation"]["review_card"], card)
        self.assertEqual(card["document"]["review_card"]["catalysts"]["proposed"], [
            "Unverified candidate: investigate changes in real yields."])

    def test_answers_are_saved_without_credentials_or_model_allowance(self):
        first = self.compile()
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_COMPILATION_OWNER_ATTEMPTS_PER_DAY=0,
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            saved = self.save(first)
            recovered = self.client.get(self.base + "refinement-commands/" +
                saved["refinement"]["command_id"] + "/")
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()["refinement"]["answers"], saved["refinement"]["answers"])
        self.assertEqual(self.adapter.catalog_calls, 1)
        self.assertEqual(self.adapter.completion_calls, 1)
        self.assertEqual(RefinementSubmission.objects.count(), 1)

    def test_command_recovery_is_readonly_and_keeps_original_context_after_new_draft(self):
        command = str(uuid4())
        first = self.compile(command_id=command)
        saved = self.save(first)
        service.propose_thesis(self.actor, self.thesis["id"], str(uuid4()),
            "A different question.", self.empty, first["thesis"]["revision"])
        with override_settings(MACRO_MODEL_API_KEY="",
                SETTINGS_MODULE="macro_agent.web.local_settings"), patch.object(compilation,
                "create_provider", side_effect=AssertionError("Recovery cannot contact a provider")):
            result = self.client.get(self.base + f"compilation-commands/{command}/")
            inputs = self.client.get(self.base + "refinement-commands/" +
                saved["refinement"]["command_id"] + "/")
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()["compilation"]["is_current_draft"])
        self.assertEqual(result.json()["compilation"]["input_text_version"]["exact_text"], self.text)
        self.assertEqual(inputs.status_code, 200)
        self.assertFalse(inputs.json()["refinement"]["is_current_context"])
        self.assertEqual(inputs.json()["refinement"]["input_text_version"]["exact_text"], self.text)
        self.assertEqual(self.adapter.completion_calls, 1)

    def test_refinement_rejects_ambiguous_or_forged_inputs_without_provider_work(self):
        first = self.compile()
        valid = self.answer_body(first)
        bad = [[], {}, [{"question_index": True, "exact_answer": "weeks"}],
            [{"question_index": "0", "exact_answer": "weeks"}],
            [{"question_index": 0, "exact_answer": 1}],
            [{"question_index": 0, "exact_answer": " "}],
            [{"question_index": 0, "exact_answer": "x" * 2001}],
            [{"question_index": 0, "exact_answer": "weeks", "question": "forged"}],
            [{"question_index": 0, "exact_answer": "a"}, {"question_index": 0, "exact_answer": "b"}],
            [{"question_index": 31, "exact_answer": "weeks"}]]
        for answers in bad:
            with self.subTest(answers=answers):
                self.assertEqual(self.post("refinements/", {**valid, "answers": answers}).status_code, 400)
        self.assertEqual(self.post("refinements/", {**valid, "cumulative_inputs": []}).status_code, 400)
        encoded = json.dumps(valid)[:-1] + ',"answers":[]}'
        self.assertEqual(self.client.post(self.base + "refinements/", encoded,
            content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 400)
        self.assertFalse(RefinementSubmission.objects.exists())
        self.assertEqual(self.adapter.completion_calls, 1)

    def test_refinement_and_recovery_enforce_csrf_owner_scope_and_no_query_controls(self):
        first = self.compile()
        body = self.answer_body(first)
        self.assertEqual(self.client.post(self.base + "refinements/", json.dumps(body),
            content_type="application/json").status_code, 403)
        staff = Client(enforce_csrf_checks=True)
        staff.force_login(self.other)
        token = staff.get("/api/v1/session/").json()["csrf_token"]
        foreign = self.post("refinements/", body, client=staff, token=token)
        self.assertEqual(foreign.status_code, 404)
        saved = self.save(first)
        command_path = self.base + "refinement-commands/" + saved["refinement"]["command_id"] + "/"
        self.assertEqual(staff.get(command_path).status_code, 404)
        self.assertEqual(self.client.get(command_path + "?retry=1").status_code, 400)
        self.assertEqual(self.client.get(self.base + f"compilation-commands/{uuid4()}/").status_code, 404)
        self.assertEqual(self.adapter.completion_calls, 1)
