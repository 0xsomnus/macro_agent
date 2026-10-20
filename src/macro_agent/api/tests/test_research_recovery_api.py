"""Session research recovery cannot resend paid work or bypass saved cooldown."""

from datetime import timedelta
import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.api.investigation_serializers import ResearchRunResponseSerializer
from macro_agent.api.tests.test_investigation_api import EXACT, MODEL, RecordedResearchProvider, recorded_discovery
from macro_agent.desk import investigation
from macro_agent.monitoring import gdelt_research
from macro_agent.monitoring.sources import SourceError
from macro_agent.theses import compilation
from macro_agent.theses.models import CompilationBudget


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    SETTINGS_MODULE="macro_agent.web.local_settings", MACRO_ENABLE_RESEARCH_DISCOVERY=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="recorded-unused-key")
class ResearchRecoveryAPITests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("Research recovery authority tests require PostgreSQL")
        CompilationBudget.objects.get_or_create(pk=1)
        self.actor = get_user_model().objects.create_user(username="research-recovery-api")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.actor)
        self.token = self.client.get("/api/v1/session/").json()["csrf_token"]
        self.provider = RecordedResearchProvider()
        self.at = timezone.now()
        self.source_calls = 0
        for name in ("start_research", "continue_research", "get_research", "get_research_command"):
            original = getattr(investigation, name)
            def wrapped(*args, _original=original, **kwargs):
                kwargs["clock"] = lambda: self.at
                return _original(*args, **kwargs)
            mocked = patch.object(investigation, name, side_effect=wrapped)
            mocked.start()
            self.addCleanup(mocked.stop)
        for module in (investigation, compilation):
            mocked = patch.object(module, "create_provider", return_value=self.provider)
            mocked.start()
            self.addCleanup(mocked.stop)
        mocked = patch.object(gdelt_research, "discover", side_effect=self.discover)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.body = {"command_id": str(uuid4()), "exact_question": EXACT,
            "provider_id": "nanogpt", "model_id": MODEL, "source_recovery": True}

    def discover(self, query, *, clock, policy_version):
        self.source_calls += 1
        if self.source_calls == 1:
            raise SourceError("rate_limited", retry_after_seconds=45)
        fixture = recorded_discovery(query, clock=clock)
        articles = [item["metadata"] for item in fixture.metadata["candidates"]]
        return gdelt_research.parse_metadata(json.dumps({"articles": articles}).encode(),
            query=query, received_at=clock(), policy_version=policy_version)

    def post(self, body, path="/api/v1/research/"):
        return self.client.post(path, json.dumps(body), content_type="application/json",
            HTTP_X_CSRFTOKEN=self.token)

    def checked(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        value = response.json()
        serializer = ResearchRunResponseSerializer(data=value)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return value

    def test_rate_limited_run_waits_and_resumes_with_same_plan_and_visible_history(self):
        initial = self.checked(self.post(self.body))
        run_id = initial["research"]["id"]
        self.assertEqual(initial["research"]["status"], "waiting_source")
        self.assertEqual(initial["research"]["discoveries"][0]["recovery"]["retry_reason"], "rate_limited")
        self.assertEqual((self.provider.calls, self.source_calls), (1, 1))
        self.at += timedelta(seconds=44)
        self.assertEqual(self.checked(self.post({}, f"/api/v1/research/{run_id}/continue/"))["research"]["status"],
                         "waiting_source")
        self.checked(self.client.get(f"/api/v1/research/{run_id}/"))
        self.checked(self.post(self.body))
        self.assertEqual((self.provider.calls, self.source_calls), (1, 1))
        self.at += timedelta(seconds=1)
        final = self.checked(self.post({}, f"/api/v1/research/{run_id}/continue/"))
        self.assertEqual(final["research"]["status"], "compiled")
        self.assertEqual((self.provider.calls, self.source_calls), (2, 2))
        self.assertEqual(final["research"]["plan"], initial["research"]["plan"])
        metadata = final["research"]["discoveries"][-1]["metadata"]
        self.assertEqual(metadata["schema_version"], "gdelt-research-selection-v2")
        self.assertEqual(metadata["policy_version"], gdelt_research.RECOVERY_POLICY_VERSION)
        self.assertEqual(metadata["adapter_version"], gdelt_research.RECOVERY_ADAPTER_VERSION)
        packet = final["research"]["compilation"]["compilation"]["evidence_context"]["content"]
        self.assertEqual(packet["schema_version"], "retained-source-evidence-v3")
        self.assertEqual([item["status"] for item in packet["question_research"]["questions"][0]["attempts"]],
                         ["failed", "captured"])
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            replay = self.checked(self.post(self.body))
            self.assertEqual(replay["research"]["compilation"]["compilation"]["document"],
                             final["research"]["compilation"]["compilation"]["document"])
        self.assertEqual((self.provider.calls, self.source_calls), (2, 2))

    def test_client_cannot_coerce_recovery_policy_or_supply_retry_authority(self):
        for value in (1, "true", None, {}):
            with self.subTest(value=value):
                self.assertEqual(self.post({**self.body, "source_recovery": value}).status_code, 400)
        self.assertEqual(self.post({**self.body, "max_attempts": 100}).status_code, 400)
        self.assertEqual((self.provider.calls, self.source_calls), (0, 0))

    def test_saved_command_cannot_change_its_recovery_contract(self):
        original = self.checked(self.post(self.body))
        changed = self.post({**self.body, "source_recovery": False})
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(original["research"]["status"], "waiting_source")
        self.assertEqual((self.provider.calls, self.source_calls), (1, 1))

    def test_missing_csrf_and_foreign_reads_cannot_advance_or_inspect_run(self):
        anonymous_write = self.client.post("/api/v1/research/", json.dumps(self.body), content_type="application/json")
        self.assertEqual(anonymous_write.status_code, 403)
        saved = self.checked(self.post(self.body))
        run_id = saved["research"]["id"]
        other = get_user_model().objects.create_user(username="foreign-recovery-staff", is_staff=True, is_superuser=True)
        self.client.force_login(other)
        self.token = self.client.get("/api/v1/session/").json()["csrf_token"]
        self.assertEqual(self.client.get(f"/api/v1/research/{run_id}/").status_code, 404)
        self.assertEqual(self.post({}, f"/api/v1/research/{run_id}/continue/").status_code, 404)
        self.assertEqual((self.provider.calls, self.source_calls), (1, 1))
