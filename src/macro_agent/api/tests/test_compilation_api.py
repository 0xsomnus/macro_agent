"""Session, ownership and strict wire evidence with a recorded model adapter."""

import copy
import io
import json
import uuid
from contextlib import redirect_stderr
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone
from drf_spectacular.validation import validate_schema

from macro_agent.api.compilation_serializers import (
    CompilationResponseSerializer, ModelCatalogResponseSerializer,
)
from macro_agent.domain.compilation import SECTIONS
from macro_agent.providers.nanogpt import ProviderError
from macro_agent.theses import compilation, service as theses
from macro_agent.theses.models import CompilationAttempt, CompilationBudget


MODEL_ID = "Qwen/Qwen3-4B"


class RecordedModel:
    def __init__(self):
        self.catalog_calls = 0
        self.completion_calls = 0
        self.error = None
        self.catalog_error = False

    def list_models(self):
        self.catalog_calls += 1
        if self.catalog_error:
            raise ProviderError("unavailable")
        return {"fetched_at": timezone.now().isoformat(), "models": [{
            "id": MODEL_ID, "name": "Recorded Qwen model", "context_length": 65536,
            "input_price_usd_per_million": "1", "output_price_usd_per_million": "2",
            "capabilities": {"tools": False},
        }]}

    def complete(self, model_id, messages):
        self.completion_calls += 1
        if self.error:
            raise ProviderError(self.error)
        return {"content": json.dumps({
            "interpretation": {"drivers": ["Falling real yields may support gold."],
                               "horizon": None, "invalidation_signposts": []},
            "grounding": [{"field": "drivers", "index": 0, "input_id": "thesis",
                           "exact_quote": "Gold may benefit if real yields fall."}],
            "refinement_issues": [{"kind": "missing_detail", "exact_quote": None, "input_id": None,
                                   "explanation": "The trader supplied no horizon.",
                                   "question": "What horizon do you intend?"}],
            "agent_hypotheses": [],
            "counter_case": "Unverified hypothesis: other drivers may offset this path.",
            "review_card": {name: {"extracted": [], "proposed": [],
                "gap": "Not resolved by this recorded test response."} for name in SECTIONS},
        }), "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "reported_cost_usd": None, "reported_model": MODEL_ID,
            "provider_request_id": "recorded-request", "latency_ms": 12,
            "finish_reason": "stop"}


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
                   MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
                   MACRO_MODEL_API_KEY="fixture-key",
                   MACRO_ALLOW_SYNTHETIC_SETUP=False,
                   SETTINGS_MODULE="macro_agent.web.local_settings")
class CompilationAPITests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("compilation API authority evidence requires PostgreSQL")
        CompilationBudget.objects.get_or_create(pk=1)
        self.owner = get_user_model().objects.create_user(username="compile-owner", password="recorded-password")
        self.other = get_user_model().objects.create_user(username="compile-staff", is_staff=True, is_superuser=True)
        self.actor = str(self.owner.pk)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)
        self.token = self.client.get("/api/v1/session/").json()["csrf_token"]
        self.text = "  Gold may benefit if real yields fall.\r\nΔ"
        self.meaning = {"drivers": [], "horizon": None, "invalidation_signposts": []}
        self.thesis = theses.create_thesis(self.actor, self.command_id(), self.text, self.meaning)["thesis"]
        self.thesis_id = self.thesis["id"]
        self.path = f"/api/v1/theses/{self.thesis_id}/compile/"
        self.adapter = RecordedModel()
        mocked = patch.object(compilation, "create_provider", return_value=self.adapter)
        self.constructor = mocked.start()
        self.addCleanup(mocked.stop)

    def command_id(self):
        return str(uuid.uuid4())

    def body(self, **changes):
        return {"command_id": self.command_id(), "expected_revision": self.thesis["revision"],
                "provider_id": "nanogpt", "model_id": MODEL_ID, **changes}

    def post(self, body=None, *, path=None, client=None, token=None):
        return (client or self.client).post(path or self.path, json.dumps(self.body() if body is None else body),
            content_type="application/json", HTTP_X_CSRFTOKEN=token or self.token)

    def compiled(self, body=None):
        response = self.post(body)
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        serializer = CompilationResponseSerializer(data=result)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return result

    def detail_path(self, attempt_id, *, thesis_id=None):
        return f"/api/v1/theses/{thesis_id or self.thesis_id}/compilations/{attempt_id}/"

    def test_compiled_model_draft_preserves_exact_text_and_does_not_approve(self):
        result = self.compiled()
        attempt = result["compilation"]
        self.assertEqual(attempt["status"], "compiled")
        self.assertTrue(attempt["is_current_draft"])
        self.assertEqual(attempt["usage"]["total_tokens"], 30)
        self.assertIsNone(attempt["reported_cost_usd"])
        self.assertEqual(attempt["estimated_cost_usd"], "0.00005")
        self.assertEqual(attempt["provider_request_id"], "recorded-request")
        self.assertEqual(result["thesis"]["draft"]["text_version"]["exact_text"], self.text)
        self.assertEqual(result["thesis"]["draft"]["interpretation"]["origin"], "model_compilation")
        self.assertIsNone(result["thesis"]["approved"])
        self.assertEqual(result["thesis"]["monitoring"], "not_configured")
        self.assertNotIn("fixture-key", json.dumps(result))
        self.assertIn("Current macro context", " ".join(attempt["limitations"]))
        self.assertEqual(self.adapter.completion_calls, 1)
        saved = CompilationAttempt.objects.get()
        self.assertEqual(json.loads(saved.messages[1]["content"])["exact_text"], self.text)

    def test_saved_retry_and_detail_do_not_initiate_more_model_calls(self):
        body = self.body()
        first = self.compiled(body)
        second = self.compiled(body)
        self.assertEqual(first["compilation"]["id"], second["compilation"]["id"])
        detail = self.client.get(self.detail_path(first["compilation"]["id"]))
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.json()["compilation"], second["compilation"])
        self.assertEqual(self.adapter.completion_calls, 1)
        self.assertEqual(self.adapter.catalog_calls, 1)

    def test_real_login_csrf_and_session_rotation_protect_compilation(self):
        client = Client(enforce_csrf_checks=True)
        token = client.get("/api/v1/session/").json()["csrf_token"]
        login = client.post("/api/v1/session/login/", json.dumps({
            "username": self.owner.username, "password": "recorded-password",
        }), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(login.status_code, 200, login.content)
        rotated = login.json()["csrf_token"]
        self.assertNotEqual(rotated, token)
        self.assertEqual(self.post(client=client, token=token).status_code, 403)
        self.assertEqual(self.post(client=client, token=rotated).status_code, 200)
        self.assertEqual(self.adapter.completion_calls, 1)

    def test_anonymous_and_missing_csrf_requests_do_not_call_provider(self):
        anonymous = Client(enforce_csrf_checks=True)
        self.assertEqual(self.post(client=anonymous).status_code, 403)
        self.assertEqual(anonymous.get("/api/v1/models/").status_code, 403)
        self.assertEqual(self.client.post(self.path, json.dumps(self.body()),
            content_type="application/json").status_code, 403)
        self.assertFalse(CompilationAttempt.objects.exists())
        self.assertEqual(self.adapter.catalog_calls, 0)

    def test_staff_foreign_and_missing_theses_and_attempts_are_opaque(self):
        compiled = self.compiled()
        staff = Client(enforce_csrf_checks=True)
        staff.force_login(self.other)
        token = staff.get("/api/v1/session/").json()["csrf_token"]
        foreign = self.post(client=staff, token=token)
        missing = self.post(path=f"/api/v1/theses/{uuid.uuid4()}/compile/", client=staff, token=token)
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json(), missing.json())
        foreign_detail = staff.get(self.detail_path(compiled["compilation"]["id"]))
        missing_detail = staff.get(self.detail_path(str(uuid.uuid4())))
        own_missing = self.client.get(self.detail_path(str(uuid.uuid4())))
        self.assertEqual(foreign_detail.status_code, 404)
        self.assertEqual(foreign_detail.json(), missing_detail.json())
        self.assertEqual(own_missing.json(), foreign_detail.json())
        self.assertEqual(self.adapter.completion_calls, 1)

    def test_model_catalog_is_explicit_normalized_and_contains_no_key(self):
        response = self.client.get("/api/v1/models/")
        self.assertEqual(response.status_code, 200, response.content)
        catalog = response.json()
        serializer = ModelCatalogResponseSerializer(data=catalog)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(catalog["provider"], "nanogpt")
        self.assertTrue(catalog["credentials_configured"])
        self.assertEqual(catalog["models"][0]["id"], MODEL_ID)
        self.assertNotIn("fixture-key", json.dumps(catalog))
        self.assertEqual(self.adapter.completion_calls, 0)
        self.constructor.assert_called_once()

    def test_gate_off_and_production_settings_hide_all_routes(self):
        paths = ("/api/v1/models/", self.detail_path(str(uuid.uuid4())))
        for changes in ({"MACRO_ENABLE_MODEL_COMPILATION": False},
                        {"SETTINGS_MODULE": "macro_agent.web.settings"}):
            with self.subTest(changes=changes), override_settings(**changes):
                self.assertEqual(self.post().status_code, 404)
                self.assertEqual(self.post(client=Client(enforce_csrf_checks=True)).status_code, 404)
                for path in paths:
                    self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.adapter.catalog_calls, 0)
        self.assertFalse(CompilationAttempt.objects.exists())

    def test_database_gate_is_independent_of_synthetic_source_permission(self):
        database = copy.deepcopy(settings.DATABASES)
        database["default"]["NAME"] = "macro_agent_production"
        with patch.object(compilation.settings, "DATABASES", database):
            self.assertEqual(self.post().status_code, 404)
            self.assertEqual(self.client.get("/api/v1/models/").status_code, 404)
        # This test class explicitly has the unrelated synthetic gate disabled.
        self.assertFalse(settings.MACRO_ALLOW_SYNTHETIC_SETUP)
        self.assertEqual(self.post().status_code, 200)

    def test_strict_request_rejects_duplicates_coercion_keys_and_queries(self):
        bodies = [self.body(command_id=1), self.body(expected_revision=True),
                  self.body(expected_revision="1"), self.body(model_id=1),
                  self.body(provider_id="unknown"), self.body(provider_id=True),
                  self.body(model_id=MODEL_ID + ":search"), self.body(model_id="auto"),
                  self.body(owner_id=self.actor), self.body(api_key="fixture-key"),
                  self.body(provider="nanogpt"), self.body(prompt="custom policy"),
                  self.body(interpretation=self.meaning), {}]
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(self.post(body).status_code, 400)
        encoded = json.dumps(self.body())
        duplicate = encoded[:-1] + ',"model_id":"' + MODEL_ID + '"}'
        self.assertEqual(self.client.post(self.path, duplicate, content_type="application/json",
            HTTP_X_CSRFTOKEN=self.token).status_code, 400)
        self.assertEqual(self.post(path=self.path + "?provider=other").status_code, 400)
        self.assertEqual(self.client.get("/api/v1/models/?model=x").status_code, 400)
        self.assertEqual(self.client.get(self.detail_path(str(uuid.uuid4())) + "?retry=1").status_code, 400)
        self.assertEqual(self.client.post(self.path, "{}", content_type="text/plain",
            HTTP_X_CSRFTOKEN=self.token).status_code, 415)
        self.assertFalse(CompilationAttempt.objects.exists())
        self.assertEqual(self.adapter.catalog_calls, 0)

    def test_operational_failures_and_admission_limit_have_safe_statuses(self):
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            response = self.post()
            self.assertEqual(response.status_code, 503, response.content)
        self.adapter.catalog_error = True
        self.assertEqual(self.client.get("/api/v1/models/").status_code, 503)
        self.assertEqual(self.post().status_code, 503)
        self.adapter.catalog_error = False
        with patch.object(compilation, "compile_thesis", side_effect=compilation.CompilationBudgetExhausted("fixture-key private message")):
            response = self.post()
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("fixture-key", response.content.decode())
        self.assertFalse(CompilationAttempt.objects.exists())

    def test_catalog_provider_pin_mismatch_conflicts_before_a_provider_call(self):
        response = self.post(self.body(provider_id="openrouter"))
        self.assertEqual(response.status_code, 409, response.content)
        self.assertFalse(CompilationAttempt.objects.exists())
        self.assertEqual(self.adapter.catalog_calls, 0)
        self.assertEqual(self.adapter.completion_calls, 0)

    def test_provider_failure_and_unknown_outcome_are_explicit_200_dispositions(self):
        for code, expected in (("authentication", "failed"), ("outcome_unknown", "outcome_unknown")):
            with self.subTest(code=code):
                self.adapter.error = code
                result = self.compiled()
                self.assertEqual(result["compilation"]["status"], expected)
                self.assertFalse(result["compilation"]["is_current_draft"])
                self.assertIsNone(result["compilation"]["document"])
                self.assertIsNone(result["compilation"]["estimated_cost_usd"])
                self.assertIsNone(result["thesis"]["approved"])
        self.assertEqual(self.adapter.completion_calls, 2)

    def test_running_and_stale_history_do_not_assert_a_current_draft(self):
        result = self.compiled()
        attempt_id = result["compilation"]["id"]
        current = result["thesis"]
        theses.propose_thesis(self.actor, self.thesis_id, self.command_id(), self.text + " New intent.",
                             self.meaning, current["revision"])
        history = self.client.get(self.detail_path(attempt_id)).json()
        self.assertEqual(history["compilation"]["status"], "compiled")
        self.assertFalse(history["compilation"]["is_current_draft"])
        with patch.object(compilation, "get_compilation", return_value={
                **history, "compilation": {**history["compilation"], "status": "running",
                                          "finished_at": None, "document": None,
                                          "interpretation_version_id": None}}):
            response = self.client.get(self.detail_path(attempt_id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["compilation"]["status"], "running")

    def test_schema_uses_strict_session_contract_and_all_attempt_dispositions(self):
        stderr = io.StringIO()
        schema_output = io.StringIO()
        with redirect_stderr(stderr):
            call_command("spectacular", "--validate", "--fail-on-warn", "--format", "openapi-json",
                         stdout=schema_output)
        self.assertEqual(stderr.getvalue(), "")
        schema = json.loads(schema_output.getvalue())
        validate_schema(schema)
        operation = schema["paths"]["/api/v1/theses/{thesis_id}/compile/"]["post"]
        self.assertEqual(operation["security"], [{"cookieAuth": []}])
        self.assertIn("Inspect status even on HTTP 200", operation["description"])
        reference = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        request = schema["components"]["schemas"][reference]
        self.assertEqual(request["additionalProperties"], False)
        self.assertEqual(set(request["required"]), {"command_id", "expected_revision", "provider_id", "model_id"})
        self.assertIn("429", operation["responses"])
        self.assertIn("503", operation["responses"])
        self.assertEqual(self.client.get(self.path).status_code, 405)
        self.assertEqual(self.client.post("/api/v1/models/", "{}", content_type="application/json",
            HTTP_X_CSRFTOKEN=self.token).status_code, 405)
