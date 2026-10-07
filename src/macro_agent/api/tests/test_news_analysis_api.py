"""Real session/CSRF, owner isolation and explicit retained-news wire evidence."""

import copy
import io
import json
from pathlib import Path
import uuid
from contextlib import redirect_stderr
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.api.news_analysis_serializers import (
    NewsAnalysisResponseSerializer, NewsCatalogResponseSerializer,
    NewsReviewContextSerializer,
)
from macro_agent.monitoring import analysis, capture
from macro_agent.monitoring.models import NewsAnalysisAttempt, ScreeningWork
from macro_agent.monitoring.sources import load_recorded
from macro_agent.persistence.models import NotificationIntent
from macro_agent.providers import ProviderError


ROOT = Path(__file__).resolve().parents[4]
SOURCE = "fixture-news-api"
MODEL = "example/model"
EXACT = "  Policy easing may support equities over a few months.\r\nΔ\r\n"
MEANING = {"drivers": ["Policy easing"], "horizon": "A few months", "invalidation_signposts": []}


class RecordedNewsModel:
    def __init__(self):
        self.catalog_calls = 0
        self.completion_calls = 0
        self.error = None

    def list_models(self):
        self.catalog_calls += 1
        return {"fetched_at": timezone.now().isoformat(), "models": [{
            "id": MODEL, "name": "Recorded model", "context_length": 65536,
            "input_price_usd_per_million": "1", "output_price_usd_per_million": "2",
            "capabilities": {"chat_completions": True}}]}

    def complete(self, model_id, messages):
        self.completion_calls += 1
        if self.error:
            raise ProviderError(self.error)
        context = json.loads(messages[1]["content"])
        document = json.loads((ROOT / "fixtures" / "news_analysis_response.json").read_text())
        position_id = context["positions"][0]["position_id"]
        document["attributed_facts"][0]["source_revision_id"] = context["source"]["revision_id"]
        document["trade_route"]["position_ids"] = [position_id]
        document["hypotheses"][0]["position_ids"] = [position_id]
        return {"content": json.dumps(document), "usage": {
            "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "reported_cost_usd": None, "reported_model": MODEL,
            "provider_request_id": "recorded-news-request", "latency_ms": 12, "finish_reason": "stop"}


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
                   MACRO_ENABLE_NEWS_ANALYSIS=True, MACRO_ENABLE_MONITORING_PROOF=True,
                   MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
                   MACRO_MODEL_API_KEY="fixture-private-key", MACRO_ALLOW_SYNTHETIC_SETUP=True,
                   SETTINGS_MODULE="macro_agent.web.local_settings")
class NewsAnalysisAPITests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("News analysis HTTP authority evidence requires PostgreSQL")
        self.owner = get_user_model().objects.create_user(username="news-api-owner", password="recorded-password")
        self.other = get_user_model().objects.create_user(username="news-api-staff", is_staff=True, is_superuser=True)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)
        self.token = self.client.get("/api/v1/session/").json()["csrf_token"]
        contract = {"label": "Fictional monitoring feed", "kind": "fictional_fixture",
            "adapter_version": "recorded-json-v1", "rights": "repository fictional fixture",
            "coverage": "bounded_snapshot", "max_items": 100, "max_bytes": 1048576}
        capture.capture(SOURCE, contract, lambda: load_recorded(ROOT / "fixtures" / "news_analysis_case.json"))
        created = self.post("/api/v1/theses/", {"command_id": str(uuid.uuid4()), "text": EXACT,
            "interpretation": MEANING})
        self.assertEqual(created.status_code, 201, created.content)
        thesis = created.json()["thesis"]
        self.thesis_id = thesis["id"]
        self.path = f"/api/v1/theses/{self.thesis_id}/analyse-next/"
        self.context_path = f"/api/v1/theses/{self.thesis_id}/news-context/"
        draft = thesis["draft"]
        approval = self.post(f"/api/v1/theses/{self.thesis_id}/approvals/", {
            "command_id": str(uuid.uuid4()), "expected_revision": thesis["revision"],
            "thesis_version_id": draft["text_version"]["id"], "text_digest": draft["text_version"]["text_digest"],
            "interpretation_version_id": draft["interpretation"]["id"],
            "interpretation_digest": draft["interpretation"]["digest"]})
        self.assertEqual(approval.status_code, 200, approval.content)
        self.approval_id = approval.json()["thesis"]["approved"]["approval"]["id"]
        position = self.post(f"/api/v1/theses/{self.thesis_id}/positions/", {
            "command_id": str(uuid.uuid4()), "expected_approval_id": self.approval_id,
            "position": {"underlying": "NQ", "direction": "long", "product_id": None,
                "venue": None, "expiry": None, "quote_currency": None, "horizon": None,
                "quantity": None, "quantity_unit": None}})
        self.assertEqual(position.status_code, 201, position.content)
        self.position_id = position.json()["position"]["id"]
        context = self.client.get(self.context_path)
        self.assertEqual(context.status_code, 200, context.content)
        self.preview = context.json()
        self.adapter = RecordedNewsModel()
        mocked = patch.object(analysis, "create_provider", return_value=self.adapter)
        self.constructor = mocked.start()
        self.addCleanup(mocked.stop)

    def body(self, **changes):
        return {"command_id": str(uuid.uuid4()), "expected_approval_id": self.approval_id,
            "expected_exposure_digest": self.preview["exposure_digest"], "source_id": SOURCE,
            "provider_id": "nanogpt", "model_id": MODEL, **changes}

    def post(self, path, body, *, client=None, token=None):
        return (client or self.client).post(path, json.dumps(body), content_type="application/json",
            HTTP_X_CSRFTOKEN=token or self.token)

    def analysed(self, body=None):
        response = self.post(self.path, self.body() if body is None else body)
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        serializer = NewsAnalysisResponseSerializer(data=result)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return result

    def detail_path(self, attempt_id, *, thesis_id=None):
        return f"/api/v1/theses/{thesis_id or self.thesis_id}/news-analyses/{attempt_id}/"

    def test_one_report_automatically_selected_with_independent_routes_and_no_approval_or_alert(self):
        result = self.analysed()["analysis"]
        self.assertEqual(result["status"], "analysed")
        self.assertEqual(result["current_disposition"], "current")
        self.assertEqual(result["context"]["approved_thesis"]["exact_text"], EXACT)
        self.assertEqual(result["document"]["thesis_route"]["status"], "potential")
        self.assertEqual(result["document"]["trade_route"]["position_ids"], [self.position_id])
        self.assertEqual(result["estimated_cost_usd"], "0.00005")
        thesis = self.client.get(f"/api/v1/theses/{self.thesis_id}/").json()
        self.assertEqual(thesis["approved"]["approval"]["id"], self.approval_id)
        self.assertEqual(thesis["approved"]["text_version"]["exact_text"], EXACT)
        self.assertEqual(ScreeningWork.objects.get().state, "pending")
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertEqual(self.adapter.completion_calls, 1)
        self.assertNotIn("fixture-private-key", json.dumps(result))

    def test_saved_command_retry_and_detail_are_owner_scoped_history_without_model_calls(self):
        command = self.body()
        first = self.analysed(command)["analysis"]
        retry = self.analysed(command)["analysis"]
        self.assertEqual(first["id"], retry["id"])
        self.assertTrue(retry["replayed"])
        detail = self.client.get(self.detail_path(first["id"]))
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.json()["analysis"]["document"], first["document"])
        self.assertEqual(self.adapter.catalog_calls, 1)
        self.assertEqual(self.adapter.completion_calls, 1)

    def test_staff_foreign_and_missing_theses_and_attempts_are_opaque(self):
        first = self.analysed()["analysis"]
        staff = Client(enforce_csrf_checks=True)
        staff.force_login(self.other)
        token = staff.get("/api/v1/session/").json()["csrf_token"]
        foreign = self.post(self.path, self.body(), client=staff, token=token)
        missing = self.post(f"/api/v1/theses/{uuid.uuid4()}/analyse-next/", self.body(), client=staff, token=token)
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json(), missing.json())
        foreign_context = staff.get(self.context_path)
        missing_context = staff.get(f"/api/v1/theses/{uuid.uuid4()}/news-context/")
        self.assertEqual(foreign_context.status_code, 404)
        self.assertEqual(foreign_context.json(), missing_context.json())
        foreign_detail = staff.get(self.detail_path(first["id"]))
        missing_detail = staff.get(self.detail_path(str(uuid.uuid4())))
        own_missing = self.client.get(self.detail_path(str(uuid.uuid4())))
        self.assertEqual(foreign_detail.status_code, 404)
        self.assertEqual(foreign_detail.json(), missing_detail.json())
        self.assertEqual(foreign_detail.json(), own_missing.json())
        self.assertEqual(self.adapter.completion_calls, 1)

    def test_real_login_rotated_csrf_and_anonymous_requests_protect_analysis(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(self.context_path).status_code, 403)
        self.assertEqual(client.get("/api/v1/news/sources/").status_code, 403)
        self.assertEqual(client.get(f"/api/v1/theses/{self.thesis_id}/news-commands/{uuid.uuid4()}/").status_code, 403)
        self.assertEqual(self.post(self.path, self.body(), client=client).status_code, 403)
        token = client.get("/api/v1/session/").json()["csrf_token"]
        login = self.post("/api/v1/session/login/", {"username": self.owner.username,
            "password": "recorded-password"}, client=client, token=token)
        self.assertEqual(login.status_code, 200, login.content)
        rotated = login.json()["csrf_token"]
        self.assertNotEqual(rotated, token)
        self.assertEqual(self.post(self.path, self.body(), client=client, token=token).status_code, 403)
        self.assertEqual(client.post(self.path, json.dumps(self.body()), content_type="application/json").status_code, 403)
        self.assertEqual(self.post(self.path, self.body(), client=client, token=rotated).status_code, 200)
        self.assertEqual(self.adapter.completion_calls, 1)

    def test_gate_hides_all_routes_before_authentication(self):
        paths = ("/api/v1/news/sources/", self.context_path, self.detail_path(str(uuid.uuid4())),
            f"/api/v1/theses/{self.thesis_id}/news-commands/{uuid.uuid4()}/")
        for changes in ({"MACRO_ENABLE_NEWS_ANALYSIS": False}, {"SETTINGS_MODULE": "macro_agent.web.settings"}):
            with self.subTest(changes=changes), override_settings(**changes):
                for client in (self.client, Client(enforce_csrf_checks=True)):
                    self.assertEqual(self.post(self.path, self.body(), client=client).status_code, 404)
                    for path in paths:
                        self.assertEqual(client.get(path).status_code, 404)
        database = copy.deepcopy(settings.DATABASES)
        database["default"]["NAME"] = "macro_agent_production"
        with patch.object(analysis.settings, "DATABASES", database):
            self.assertEqual(self.post(self.path, self.body()).status_code, 404)
        self.assertFalse(NewsAnalysisAttempt.objects.exists())
        self.assertEqual(self.adapter.catalog_calls, 0)

    def test_strict_requests_reject_duplicate_keys_unknown_fields_coercion_and_queries(self):
        bodies = [self.body(command_id=1), self.body(expected_approval_id=True),
            self.body(expected_exposure_digest=1), self.body(expected_exposure_digest="b" * 63),
            self.body(source_id=1), self.body(provider_id=True), self.body(model_id=1),
            self.body(model_id="auto"), self.body(owner_id=str(self.owner.pk)),
            self.body(article_id=str(uuid.uuid4())), self.body(api_key="private"), {}]
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(self.post(self.path, body).status_code, 400)
        encoded = json.dumps(self.body())
        duplicate = encoded[:-1] + ',"model_id":"example/model"}'
        self.assertEqual(self.client.post(self.path, duplicate, content_type="application/json",
            HTTP_X_CSRFTOKEN=self.token).status_code, 400)
        self.assertEqual(self.post(self.path + "?model=other", self.body()).status_code, 400)
        for path in (self.context_path, "/api/v1/news/sources/", self.detail_path(str(uuid.uuid4()))):
            self.assertEqual(self.client.get(path + "?retry=1").status_code, 400)
        self.assertEqual(self.client.post(self.path, "{}", content_type="text/plain",
            HTTP_X_CSRFTOKEN=self.token).status_code, 415)
        self.assertFalse(NewsAnalysisAttempt.objects.exists())
        self.assertEqual(self.adapter.catalog_calls, 0)

    def test_catalog_and_preview_are_explicit_scoped_and_do_not_call_a_model(self):
        catalog = self.client.get("/api/v1/news/sources/")
        self.assertEqual(catalog.status_code, 200, catalog.content)
        serializer = NewsCatalogResponseSerializer(data=catalog.json())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(catalog.json()["sources"][0]["current_reports"], 1)
        serializer = NewsReviewContextSerializer(data=self.preview)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(self.preview["approved_exact_text"], EXACT)
        self.assertEqual(self.preview["positions"][0]["position_id"], self.position_id)
        self.assertEqual(catalog["Cache-Control"], "no-store")
        with override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=False, SETTINGS_MODULE="macro_agent.web.local_settings"):
            self.assertEqual(self.client.get("/api/v1/news/sources/").json()["sources"], [])
            self.assertEqual(self.post(self.path, self.body()).status_code, 404)
        self.assertEqual(self.adapter.catalog_calls, 0)

    def test_failure_remains_unresolved_and_next_request_does_not_retry_paid_or_uncertain_work(self):
        self.adapter.error = "outcome_unknown"
        first = self.analysed()["analysis"]
        self.assertEqual(first["status"], "outcome_unknown")
        self.assertEqual(first["current_disposition"], "unresolved")
        self.assertIsNone(first["document"])
        self.assertEqual(first["unresolved_attempt_count"], 1)
        next_result = self.analysed()["analysis"]
        self.assertEqual(next_result["status"], "queue_empty")
        self.assertEqual(next_result["unresolved_attempt_count"], 1)
        self.assertEqual(self.adapter.completion_calls, 1)
        self.assertEqual(ScreeningWork.objects.get().state, "pending")

    def test_conflicts_budget_and_provider_unavailable_use_safe_statuses(self):
        self.assertEqual(self.post(self.path, self.body(expected_approval_id=str(uuid.uuid4()))).status_code, 409)
        self.assertEqual(self.post(self.path, self.body(expected_exposure_digest="0" * 64)).status_code, 409)
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            self.assertEqual(self.post(self.path, self.body()).status_code, 503)
        with patch.object(analysis, "analyse_next", side_effect=analysis.NewsBudgetExhausted("fixture-private-key")):
            response = self.post(self.path, self.body())
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("fixture-private-key", response.content.decode())
        self.assertFalse(NewsAnalysisAttempt.objects.exists())

    def test_generated_openapi_has_explicit_nested_analysis_and_strict_session_command(self):
        stderr, output = io.StringIO(), io.StringIO()
        with redirect_stderr(stderr):
            call_command("spectacular", "--validate", "--fail-on-warn", "--format", "openapi-json", stdout=output)
        self.assertEqual(stderr.getvalue(), "")
        schema = json.loads(output.getvalue())
        operation = schema["paths"]["/api/v1/theses/{thesis_id}/analyse-next/"]["post"]
        self.assertEqual(operation["security"], [{"cookieAuth": []}])
        reference = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
        request = schema["components"]["schemas"][reference]
        self.assertEqual(request["additionalProperties"], False)
        self.assertEqual(set(request["required"]), {"command_id", "expected_approval_id",
            "expected_exposure_digest", "source_id", "provider_id", "model_id"})
        self.assertIn("Inspect status even on HTTP 200", operation["description"])
        self.assertIn("429", operation["responses"])
        self.assertIn("503", operation["responses"])
        self.assertEqual(self.client.get(self.path).status_code, 405)
        recovery = schema["paths"]["/api/v1/theses/{thesis_id}/news-commands/{command_id}/"]["get"]
        self.assertEqual(recovery["security"], [{"cookieAuth": []}])
        self.assertIn("no model catalogue call", recovery["description"])
        self.assertEqual({parameter["name"] for parameter in recovery["parameters"]}, {"command_id", "thesis_id"})

    def test_command_receipt_recovery_is_read_only_and_includes_saved_empty_queue(self):
        command = self.body()
        first = self.analysed(command)["analysis"]
        path = f"/api/v1/theses/{self.thesis_id}/news-commands/{command['command_id']}/"
        recovered = self.client.get(path)
        self.assertEqual(recovered.status_code, 200, recovered.content)
        serializer = NewsAnalysisResponseSerializer(data=recovered.json())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(recovered.json()["analysis"]["id"], first["id"])
        self.assertEqual(recovered["Cache-Control"], "no-store")
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_ENABLE_MODEL_COMPILATION=False,
                SETTINGS_MODULE="macro_agent.web.local_settings"):
            unavailable_provider_recovery = self.client.get(path)
            self.assertEqual(unavailable_provider_recovery.status_code, 200, unavailable_provider_recovery.content)
            self.assertEqual(unavailable_provider_recovery.json()["analysis"]["id"], first["id"])
        empty_command = self.body()
        empty = self.analysed(empty_command)["analysis"]
        self.assertEqual(empty["status"], "queue_empty")
        empty_path = f"/api/v1/theses/{self.thesis_id}/news-commands/{empty_command['command_id']}/"
        empty_recovered = self.client.get(empty_path)
        self.assertEqual(empty_recovered.status_code, 200, empty_recovered.content)
        self.assertEqual(empty_recovered.json()["analysis"]["status"], "queue_empty")
        self.assertEqual(self.adapter.catalog_calls, 1)
        self.assertEqual(self.adapter.completion_calls, 1)
        self.assertEqual(self.client.get(path + "?retry=1").status_code, 400)
        self.assertEqual(self.client.post(path, "{}", content_type="application/json",
            HTTP_X_CSRFTOKEN=self.token).status_code, 405)

    def test_foreign_and_missing_command_receipts_are_opaque_without_provider_calls(self):
        command = self.body()
        self.analysed(command)
        staff = Client(enforce_csrf_checks=True)
        staff.force_login(self.other)
        path = f"/api/v1/theses/{self.thesis_id}/news-commands/{command['command_id']}/"
        foreign = staff.get(path)
        missing = staff.get(f"/api/v1/theses/{self.thesis_id}/news-commands/{uuid.uuid4()}/")
        own_missing = self.client.get(f"/api/v1/theses/{self.thesis_id}/news-commands/{uuid.uuid4()}/")
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json(), missing.json())
        self.assertEqual(foreign.json(), own_missing.json())
        self.assertEqual(self.adapter.catalog_calls, 1)
        self.assertEqual(self.adapter.completion_calls, 1)
