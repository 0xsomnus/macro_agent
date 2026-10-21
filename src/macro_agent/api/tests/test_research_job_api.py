"""Session consent cannot become a background worker execution endpoint."""

import json
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.api.research_job_serializers import ResearchBackgroundResponseSerializer
from macro_agent.api.tests.test_investigation_api import EXACT, MODEL, RecordedResearchProvider, recorded_discovery
from macro_agent.desk import investigation, research_jobs
from macro_agent.desk.research_job_models import ResearchJob, ResearchJobAdmission, ResearchJobLease
from macro_agent.domain.time import parse_instant
from macro_agent.monitoring import gdelt_research
from macro_agent.monitoring.sources import SourceError
from macro_agent.theses import compilation
from macro_agent.theses.models import CompilationBudget


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    SETTINGS_MODULE="macro_agent.web.local_settings", MACRO_ENABLE_RESEARCH_DISCOVERY=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ENABLE_RESEARCH_BACKGROUND=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-unused-key")
class ResearchBackgroundAPITests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("Research background authority tests require PostgreSQL")
        CompilationBudget.objects.get_or_create(pk=1)
        self.owner = get_user_model().objects.create_user(username="background-api-owner")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)
        self.token = self.client.get("/api/v1/session/").json()["csrf_token"]
        self.provider = RecordedResearchProvider()
        self.at = timezone.now()
        for module, names in ((investigation, ("start_research",)),
                              (research_jobs, ("enroll", "inspect_job", "revoke"))):
            for name in names:
                original = getattr(module, name)
                def wrapped(*args, _original=original, **kwargs):
                    kwargs["clock"] = lambda: self.at
                    return _original(*args, **kwargs)
                mocked = patch.object(module, name, side_effect=wrapped)
                mocked.start()
                self.addCleanup(mocked.stop)
        for module in (investigation, compilation):
            mocked = patch.object(module, "create_provider", return_value=self.provider)
            mocked.start()
            self.addCleanup(mocked.stop)
        source_patch = patch.object(gdelt_research, "discover",
            side_effect=SourceError("rate_limited", retry_after_seconds=60))
        self.source = source_patch.start()
        self.addCleanup(source_patch.stop)
        body = {"command_id": str(uuid4()), "exact_question": EXACT, "provider_id": "nanogpt",
                "model_id": MODEL, "source_recovery": True}
        response = self.post(body, "/api/v1/research/")
        self.assertEqual(response.status_code, 200, response.content)
        self.research = response.json()["research"]
        self.assertEqual(self.research["status"], "waiting_source")
        self.path = f"/api/v1/research/{self.research['id']}/background/"
        self.command = {"command_id": str(uuid4()),
                        "expected_request_digest": self.research["request_digest"]}

    def post(self, body, path=None, *, csrf=True):
        headers = {"HTTP_X_CSRFTOKEN": self.token} if csrf else {}
        return self.client.post(path or self.path, json.dumps(body),
            content_type="application/json", **headers)

    def checked(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        value = response.json()
        serializer = ResearchBackgroundResponseSerializer(data=value)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        # The generated response contract must retain all server provenance.
        self.assertEqual(set(serializer.data["job"]), set(value["job"]))
        self.assertEqual(set(serializer.data["job"]["policy"]), set(value["job"]["policy"]))
        self.assertEqual(set(serializer.data["job"]["model_configuration"]),
                         set(value["job"]["model_configuration"]))
        return value

    def assert_no_work(self):
        self.assertEqual((self.provider.calls, self.provider.catalog_calls, self.source.call_count), (1, 1, 1))
        self.assertFalse(ResearchJobLease.objects.exists())

    def test_start_does_not_enroll_and_consent_replay_is_inert_without_credentials(self):
        self.assertFalse(ResearchJob.objects.exists())
        self.assertEqual(self.client.get(self.path).status_code, 404)
        first = self.checked(self.post(self.command))
        self.assertFalse(first["replayed"])
        job = first["job"]
        self.assertEqual(job["run_id"], self.research["id"])
        self.assertEqual(job["owner_id"], str(self.owner.pk))
        self.assertEqual(job["enrollment_command_id"], self.command["command_id"])
        self.assertEqual(job["request_digest"], self.research["request_digest"])
        self.assertEqual((job["provider"], job["model_id"]), ("nanogpt", MODEL))
        self.assertEqual(job["policy"], {"policy_version": "research-background-resume-2026-10-21-v1",
            "lease_seconds": 180, "max_leases": 12, "planning_allowed": False, "model_retries_allowed": False})
        with override_settings(SETTINGS_MODULE="macro_agent.web.local_settings", MACRO_MODEL_API_KEY=""):
            replay = self.checked(self.post(self.command))
            read = self.checked(self.client.get(self.path))
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["job"], first["job"])
        self.assertEqual(read["job"], first["job"])
        self.assertEqual(ResearchJob.objects.count(), 1)
        self.assertNotIn("recorded-unused-key", json.dumps(first))
        self.assert_no_work()

    def test_legacy_start_remains_unenrolled_with_worker_gate_enabled(self):
        body = {"command_id": str(uuid4()), "exact_question": EXACT,
                "provider_id": "nanogpt", "model_id": MODEL}
        response = self.post(body, "/api/v1/research/")
        self.assertEqual(response.status_code, 200, response.content)
        research = response.json()["research"]
        self.assertEqual(research["execution_policy"], {})
        self.assertFalse(ResearchJob.objects.exists())
        self.assertEqual(self.client.get(f"/api/v1/research/{research['id']}/background/").status_code, 404)
        self.assertEqual((self.provider.calls, self.source.call_count), (2, 2))

    def test_disabled_worker_keeps_inspection_and_revocation_available(self):
        first = self.checked(self.post(self.command))
        revoke = {"command_id": str(uuid4())}
        with override_settings(SETTINGS_MODULE="macro_agent.web.local_settings",
                MACRO_ENABLE_RESEARCH_BACKGROUND=False, MACRO_MODEL_API_KEY=""):
            self.checked(self.client.get(self.path))
            self.assertEqual(self.post(self.command).status_code, 404)
            stopped = self.checked(self.post(revoke, self.path + "revoke/"))
            replay = self.checked(self.post(revoke, self.path + "revoke/"))
        self.assertEqual(stopped["job"]["status"], "revoked")
        self.assertEqual(stopped["job"]["id"], first["job"]["id"])
        self.assertIsNotNone(stopped["job"]["revoked_at"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["job"], stopped["job"])
        self.assert_no_work()

    def test_old_enrollment_retry_does_not_reactivate_revoked_consent(self):
        self.checked(self.post(self.command))
        stopped = self.checked(self.post({"command_id": str(uuid4())}, self.path + "revoke/"))
        replay = self.checked(self.post(self.command))
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["job"], stopped["job"])
        self.assertEqual(self.post({**self.command, "command_id": str(uuid4())}).status_code, 409)
        self.assert_no_work()

    def test_session_csrf_and_foreign_staff_cannot_grant_inspect_or_revoke(self):
        self.assertEqual(self.post(self.command, csrf=False).status_code, 403)
        self.checked(self.post(self.command))
        other = get_user_model().objects.create_user(username="background-foreign", is_staff=True, is_superuser=True)
        self.client.force_login(other)
        self.token = self.client.get("/api/v1/session/").json()["csrf_token"]
        responses = [self.client.get(self.path), self.post(self.command),
                     self.post({"command_id": str(uuid4())}, self.path + "revoke/")]
        missing = self.client.get(f"/api/v1/research/{uuid4()}/background/")
        for response in responses:
            self.assertEqual(response.status_code, 404, response.content)
            self.assertEqual(response.json(), missing.json())
        self.client.logout()
        self.assertEqual(self.client.get(self.path).status_code, 403)
        self.assert_no_work()

    def test_strict_commands_reject_unknown_fields_coercion_and_duplicate_keys(self):
        for value in (1, True, None, {}, [], "A" * 64, "g" * 64, " " + "a" * 63):
            with self.subTest(value=value):
                self.assertEqual(self.post({**self.command, "expected_request_digest": value}).status_code, 400)
        for value in (1, True, None, {}, [], "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"):
            with self.subTest(command_id=value):
                self.assertEqual(self.post({**self.command, "command_id": value}).status_code, 400)
        for field in ("owner_id", "provider_id", "model_id", "policy", "next_due_at", "active_token"):
            self.assertEqual(self.post({**self.command, field: "client-authority"}).status_code, 400)
        raw = ('{"command_id":"' + self.command["command_id"] + '","command_id":"'
               + str(uuid4()) + '","expected_request_digest":"' + self.research["request_digest"] + '"}')
        self.assertEqual(self.client.post(self.path, raw, content_type="application/json",
            HTTP_X_CSRFTOKEN=self.token).status_code, 400)
        self.assertFalse(ResearchJob.objects.exists())
        self.assert_no_work()

    def test_reads_reject_query_parameters_and_revoke_rejects_extra_authority(self):
        self.checked(self.post(self.command))
        self.assertEqual(self.client.get(self.path + "?advance=true").status_code, 400)
        self.assertEqual(self.client.get(self.path + "?id=1&id=2").status_code, 400)
        self.assertEqual(self.post({**self.command, "expected_request_digest": "a" * 64}).status_code, 409)
        self.assertEqual(self.post({"command_id": str(uuid4()), "active_token": str(uuid4())},
            self.path + "revoke/").status_code, 400)
        self.assertEqual(self.post({"command_id": str(uuid4())}, self.path + "revoke/", csrf=False).status_code, 403)
        self.assert_no_work()

    def test_owner_read_retains_real_operator_lease_and_exact_node_admissions(self):
        self.checked(self.post(self.command))
        self.at += timedelta(seconds=60)
        source_calls = []
        def discovery(query, *, clock):
            source_calls.append(query)
            fixture = recorded_discovery(query, clock=clock)
            articles = [item["metadata"] for item in fixture.metadata["candidates"]]
            return gdelt_research.parse_metadata(json.dumps({"articles": articles}).encode(),
                query=query, received_at=clock(), policy_version=gdelt_research.RECOVERY_POLICY_VERSION)
        result = research_jobs.run_tick(str(self.owner.pk), self.research["id"],
            provider=self.provider, discovery=discovery, clock=lambda: self.at)
        self.assertEqual(result["job"]["status"], "completed", result)
        counts = (self.provider.calls, self.provider.catalog_calls, self.source.call_count, len(source_calls))
        self.assertEqual(counts, (2, 2, 1, 1))
        read = self.checked(self.client.get(self.path))
        self.assertEqual(read["job"], result["job"])
        self.assertEqual(len(read["job"]["leases"]), 1)
        lease = read["job"]["leases"][0]
        self.assertEqual(lease["outcome"]["status"], "completed")
        expected = [{"kind": "source" if item.source_attempt_id else "compilation",
            "admission_id": str(item.source_attempt_id or item.compilation_attempt_id),
            "admitted_at": item.admitted_at.isoformat()} for item in ResearchJobAdmission.objects.filter(
                lease_id=lease["token"]).order_by("admitted_at", "pk")]
        self.assertEqual({item["kind"] for item in expected}, {"source", "compilation"})
        self.assertEqual(lease["admissions"], expected)
        serialized = ResearchBackgroundResponseSerializer(data=read)
        self.assertTrue(serialized.is_valid(), serialized.errors)
        rendered = serialized.data["job"]["leases"][0]["admissions"]
        self.assertEqual(len(rendered), len(expected))
        for actual, retained in zip(rendered, expected):
            self.assertEqual(actual["kind"], retained["kind"])
            self.assertEqual(actual["admission_id"], retained["admission_id"])
            self.assertEqual(parse_instant(actual["admitted_at"]), parse_instant(retained["admitted_at"]))
        self.assertEqual((self.provider.calls, self.provider.catalog_calls, self.source.call_count, len(source_calls)), counts)
