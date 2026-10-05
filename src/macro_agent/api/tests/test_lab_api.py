"""Real PostgreSQL gates, session authority and recorded currentness evidence."""

import copy
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from drf_spectacular.validation import validate_schema

from macro_agent.api.lab_serializers import RecordedNewsResponseSerializer
from macro_agent.lab import recorded_news as service
from macro_agent.persistence.models import (
    AssessmentRecord, ContextAdmission, CurrentAssessment, NotificationIntent, ThesisBriefBinding,
)
from macro_agent.positions import service as positions
from macro_agent.theses import service as theses


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
                   MACRO_ALLOW_SYNTHETIC_SETUP=True, SETTINGS_MODULE="macro_agent.web.local_settings")
class RecordedNewsAPITests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("recorded happy-path authority evidence requires PostgreSQL")
        self.owner = get_user_model().objects.create_user(username="recorded-owner")
        self.other = get_user_model().objects.create_user(username="recorded-other", is_staff=True, is_superuser=True)
        self.actor = str(self.owner.pk)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)
        self.token = self.client.get("/api/v1/session/").json()["csrf_token"]
        self.text = "  A discretionary view about EUR/USD.\r\nThis is my exact text."
        draft = theses.create_thesis(self.actor, self.command_id(), self.text, self.meaning())["thesis"]
        self.thesis = self.approve(draft)["thesis"]
        self.thesis_id = self.thesis["id"]
        self.approval_id = self.thesis["approved"]["approval"]["id"]
        self.position = positions.create_position(self.actor, self.thesis_id, self.command_id(),
            self.approval_id, self.declaration())["position"]
        self.path = f"/api/v1/lab/theses/{self.thesis_id}/recorded-news/"

    def command_id(self):
        return str(uuid.uuid4())

    def meaning(self):
        return {"drivers": ["Relative policy rates"], "horizon": None, "invalidation_signposts": []}

    def declaration(self, **changes):
        return {"underlying": " EUR/USD ", "direction": "short", "product_id": None,
                "venue": None, "expiry": None, "quote_currency": None,
                "horizon": "Several weeks", "quantity": "0.5000", "quantity_unit": "lots", **changes}

    def approve(self, draft):
        version = draft["draft"]
        return theses.approve_thesis(self.actor, draft["id"], self.command_id(),
            thesis_version_id=version["text_version"]["id"], text_digest=version["text_version"]["text_digest"],
            interpretation_version_id=version["interpretation"]["id"],
            interpretation_digest=version["interpretation"]["digest"], expected_revision=draft["revision"])

    def new_approval(self):
        current = theses.get_thesis(self.actor, self.thesis_id)
        proposed = theses.propose_thesis(self.actor, self.thesis_id, self.command_id(),
            self.text + " An explicit amendment.", self.meaning(), current["revision"])["thesis"]
        approved = self.approve(proposed)["thesis"]
        self.approval_id = approved["approved"]["approval"]["id"]
        return approved

    def post(self, body=None, *, path=None, client=None, token=None):
        return (client or self.client).post(path or self.path,
            json.dumps(body if body is not None else {"expected_approval_id": self.approval_id}),
            content_type="application/json", HTTP_X_CSRFTOKEN=token or self.token)

    def example(self):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        serializer = RecordedNewsResponseSerializer(data=result)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return result

    def revise(self, quantity="1.0000"):
        self.position = positions.revise_position(self.actor, self.position["id"], self.command_id(),
            self.position["revision"], self.approval_id, self.declaration(quantity=quantity))["position"]

    def test_own_inputs_remain_exact_and_impacts_are_explicitly_unresolved(self):
        result = self.example()
        self.assertEqual(theses.get_thesis(self.actor, self.thesis_id)["approved"]["text_version"]["exact_text"], self.text)
        self.assertEqual(result["positions"][0]["underlying"], " EUR/USD ")
        self.assertEqual(result["positions"][0]["quantity"], "0.5000")
        self.assertEqual(result["positions"][0]["quantity_unit"], "lots")
        self.assertEqual(result["positions"][0]["horizon"], "Several weeks")
        self.assertEqual(result["positions"][0]["mapping_status"], "user_declared_unverified")
        self.assertIn("venue", result["positions"][0]["missing_fields"])
        self.assertEqual(result["notice"]["portfolio_impact"], "unresolved")
        self.assertEqual(result["screening"]["personalized_relevance"], "unresolved")
        self.assertEqual(result["source"]["event_id"], "fictional-port-disruption")
        self.assertIn("Fictional", result["notice"]["facts"][0]["value"])
        self.assertEqual(result["monitoring"], "not_configured")
        self.assertEqual(result["model"], "not_used")
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["provider_spend"], 0)
        self.assertEqual(result["notice"]["notification"]["external_delivery"], "not_configured")
        admission = ContextAdmission.objects.get()
        self.assertEqual(admission.resolved_inputs["text"]["exact_text"], self.text)
        self.assertEqual(admission.resolved_inputs["exposure"]["positions"][0]["payload"]["quantity"], "0.5000")
        self.assertEqual(result["brief"]["commit_time_measured"], False)
        self.assertEqual(len(admission.pins), 4)

    def test_same_context_retry_has_no_new_assessment_admission_or_interrupt(self):
        first, second = self.example(), self.example()
        self.assertFalse(first["notice"]["replayed"])
        self.assertTrue(second["notice"]["replayed"])
        self.assertEqual(first["brief"], second["brief"])
        self.assertEqual(first["notice"]["assessment_id"], second["notice"]["assessment_id"])
        self.assertEqual(AssessmentRecord.objects.count(), 1)
        self.assertEqual(ContextAdmission.objects.count(), 1)
        self.assertEqual(NotificationIntent.objects.count(), 1)

    def test_exposure_change_cancels_obsolete_notice_and_publishes_fresh_context(self):
        first = self.example()
        self.revise()
        self.assertIsNone(CurrentAssessment.objects.first())
        self.assertEqual(ThesisBriefBinding.objects.get().status, "pending")
        self.assertEqual(NotificationIntent.objects.get().state, "canceled")
        next_result = self.example()
        self.assertEqual(next_result["positions"][0]["quantity"], "1.0000")
        self.assertNotEqual(first["notice"]["assessment_id"], next_result["notice"]["assessment_id"])
        self.assertEqual(next_result["brief"]["generation"], 2)
        self.assertEqual(NotificationIntent.objects.filter(state="pending").count(), 1)
        self.assertEqual(NotificationIntent.objects.filter(state="canceled").count(), 1)
        self.assertEqual(self.example()["notice"]["assessment_id"], next_result["notice"]["assessment_id"])

    def test_exposure_changed_between_admission_and_publication_fails_closed(self):
        original = service.enroll_synthetic
        def admit_then_change(*args, **kwargs):
            result = original(*args, **kwargs)
            self.revise()
            return result
        with patch.object(service, "enroll_synthetic", side_effect=admit_then_change):
            response = self.post()
        self.assertEqual(response.status_code, 409, response.content)
        self.assertFalse(AssessmentRecord.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertEqual(ThesisBriefBinding.objects.get().status, "pending")
        self.assertEqual(self.example()["positions"][0]["quantity"], "1.0000")

    def test_approval_changed_between_admission_and_publication_fails_closed(self):
        original = service.enroll_synthetic
        def admit_then_change(*args, **kwargs):
            result = original(*args, **kwargs)
            self.new_approval()
            return result
        with patch.object(service, "enroll_synthetic", side_effect=admit_then_change):
            response = self.post()
        self.assertEqual(response.status_code, 409, response.content)
        self.assertFalse(AssessmentRecord.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertEqual(ThesisBriefBinding.objects.get().status, "pending")
        self.assertTrue(self.example()["notice"]["is_current"])

    def test_stale_approval_cannot_enroll_or_reactivate_old_notice(self):
        first = self.example()
        old = self.approval_id
        self.new_approval()
        self.assertEqual(self.post({"expected_approval_id": old}).status_code, 409)
        new = self.example()
        self.assertNotEqual(first["notice"]["assessment_id"], new["notice"]["assessment_id"])
        self.assertEqual(self.post({"expected_approval_id": old}).status_code, 409)
        self.assertEqual(self.example()["notice"]["assessment_id"], new["notice"]["assessment_id"])
        self.assertEqual(AssessmentRecord.objects.count(), 2)

    def test_unapproved_thesis_is_not_implicitly_approved(self):
        draft = theses.create_thesis(self.actor, self.command_id(), "A new unapproved view.", self.meaning())["thesis"]
        response = self.post(path=f"/api/v1/lab/theses/{draft['id']}/recorded-news/")
        self.assertEqual(response.status_code, 409)
        self.assertFalse(ContextAdmission.objects.exists())
        self.assertIsNone(theses.get_thesis(self.actor, draft["id"])["approved"])

    def test_closed_positions_remain_visible_with_no_reopening(self):
        self.example()
        positions.close_position(self.actor, self.position["id"], self.command_id(),
            self.position["revision"], self.approval_id)
        result = self.example()
        self.assertEqual(result["positions"][0]["status"], "closed")
        self.assertEqual(result["positions"][0]["quantity"], "0.5000")
        binding = ThesisBriefBinding.objects.get()
        admission = ContextAdmission.objects.get(brief=binding.brief, approval_id=binding.admitted_approval_id,
                                                 exposure_digest=binding.admitted_exposure_digest)
        self.assertEqual(len(admission.resolved_inputs["exposure"]["positions"]), 1)

    def test_anonymous_and_missing_csrf_requests_cannot_create_fixture_state(self):
        self.assertEqual(self.post(client=Client(enforce_csrf_checks=True)).status_code, 403)
        self.assertEqual(self.client.post(self.path, json.dumps({"expected_approval_id": self.approval_id}), content_type="application/json").status_code, 403)
        self.assertFalse(ThesisBriefBinding.objects.exists())

    def test_foreign_owner_staff_and_missing_theses_are_indistinguishable(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.other)
        token = client.get("/api/v1/session/").json()["csrf_token"]
        foreign = self.post(client=client, token=token)
        missing = self.post(path=f"/api/v1/lab/theses/{uuid.uuid4()}/recorded-news/", client=client, token=token)
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json(), missing.json())
        self.assertFalse(ThesisBriefBinding.objects.exists())

    def test_setup_flag_off_returns_opaque_404(self):
        with override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=False):
            response = self.post()
            anonymous = self.post(client=Client(enforce_csrf_checks=True))
            with self.assertRaises(service.RecordedNewsUnavailable):
                service.recorded_news(self.actor, self.thesis_id, self.approval_id)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(anonymous.status_code, 404)
        self.assertFalse(ThesisBriefBinding.objects.exists())

    def test_production_settings_cannot_enable_route_with_synthetic_flag_alone(self):
        with override_settings(SETTINGS_MODULE="macro_agent.web.settings", MACRO_ALLOW_SYNTHETIC_SETUP=True):
            response = self.post()
            with self.assertRaises(service.RecordedNewsUnavailable):
                service.recorded_news(self.actor, self.thesis_id, self.approval_id)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ThesisBriefBinding.objects.exists())

    def test_database_gate_requires_explicit_development_or_test_name(self):
        database = copy.deepcopy(settings.DATABASES)
        database["default"]["NAME"] = "macro_agent_production"
        with patch.object(service.settings, "DATABASES", database):
            response = self.post()
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ThesisBriefBinding.objects.exists())

    def test_strict_request_rejects_coercion_authority_fields_duplicates_and_query(self):
        for body in ({}, {"expected_approval_id": None}, {"expected_approval_id": 1},
                     {"expected_approval_id": self.approval_id.upper()},
                     {"expected_approval_id": self.approval_id, "owner_id": self.actor},
                     {"expected_approval_id": self.approval_id, "source_id": "invented"},
                     {"expected_approval_id": self.approval_id, "synthetic": True}):
            self.assertEqual(self.post(body).status_code, 400)
        duplicate = '{"expected_approval_id":"' + self.approval_id + '","expected_approval_id":"' + self.approval_id + '"}'
        self.assertEqual(self.client.post(self.path, duplicate, content_type="application/json", HTTP_X_CSRFTOKEN=self.token).status_code, 400)
        self.assertEqual(self.post(path=self.path + "?source_id=x").status_code, 400)
        self.assertEqual(self.client.post(self.path, "{}", content_type="text/plain", HTTP_X_CSRFTOKEN=self.token).status_code, 415)
        self.assertFalse(ThesisBriefBinding.objects.exists())

    def test_schema_marks_development_fixture_and_strict_session_contract(self):
        response = self.client.get("/api/v1/schema/")
        self.assertEqual(response.status_code, 200, response.content)
        schema = response.json()
        validate_schema(schema)
        operation = schema["paths"]["/api/v1/lab/theses/{thesis_id}/recorded-news/"]["post"]
        self.assertEqual(operation["security"], [{"cookieAuth": []}])
        self.assertIn("Development-only fictional event", operation["description"])
        reference = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        request = schema["components"]["schemas"][reference]
        self.assertEqual(request["additionalProperties"], False)
        self.assertEqual(request["required"], ["expected_approval_id"])
        self.assertIn("409", operation["responses"])
        self.assertEqual(self.client.get(self.path).status_code, 405)
