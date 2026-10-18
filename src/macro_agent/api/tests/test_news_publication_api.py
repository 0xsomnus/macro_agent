"""Private publication authority, immutable recovery and exact retained analysis."""

import io
import json
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.test import Client, TransactionTestCase, override_settings

from macro_agent.api.news_publication_serializers import NewsPublicationDetailSerializer
from macro_agent.domain.news_publication import POLICY_VERSION
from macro_agent.monitoring import publication
from macro_agent.monitoring.attention_models import NewsPublication
from macro_agent.monitoring.tests import test_news_publication as fixtures


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    SETTINGS_MODULE="macro_agent.web.local_settings", MACRO_ENABLE_CONTINUOUS_DESK=True,
    MACRO_ENABLE_NEWS_ANALYSIS=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="recorded-test-key")
class NewsPublicationAPITests(TransactionTestCase):
    def setUp(self):
        self.case = fixtures.NewsPublicationTests("runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.case.owner)
        self.analysis = self.case.analysed()
        self.preview_path = f"/api/v1/news-analyses/{self.analysis['id']}/publication-preview/"
        self.path = f"/api/v1/news-analyses/{self.analysis['id']}/publish/"
        self.thesis_id = self.case.thesis["id"]

    def post(self, command, *, client=None, csrf=True, raw=False):
        client = client or self.client
        headers = {"HTTP_X_CSRFTOKEN": client.get("/api/v1/session/").json()["csrf_token"]} if csrf else {}
        return client.post(self.path, command if raw else json.dumps(command),
            content_type="application/json", **headers)

    def command(self):
        result = self.client.get(self.preview_path,
            {"fanout_limit": 10, "policy_version": POLICY_VERSION})
        self.assertEqual(result.status_code, 200, result.content)
        value = result.json()
        return {"command_id": str(uuid4()), "expected_analysis_digest": value["analysis_digest"],
            "expected_generation": value["expected_generation"], "fanout_limit": 10,
            "policy_version": POLICY_VERSION}

    def test_publication_preserves_exact_analysis_and_separate_authority(self):
        response = self.post(self.command())
        self.assertEqual(response.status_code, 200, response.content)
        value = response.json()
        serializer = NewsPublicationDetailSerializer(data=value)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        represented = NewsPublicationDetailSerializer(value).data
        self.assertEqual(represented["analysis"]["document"], self.analysis["document"])
        self.assertEqual(value["publication"]["attention_decision"]["status"], "review_requested")
        self.assertEqual(value["notification_intent"]["state"], "pending")
        self.assertEqual(self.case.provider.calls, 1)
        current = self.client.get(f"/api/v1/theses/{self.thesis_id}/news-brief/").json()
        self.assertEqual(current["current_publication"]["publication"], value["publication"])

    def test_strict_commands_and_csrf_cannot_publish(self):
        command = self.command()
        self.assertEqual(self.post(command, csrf=False).status_code, 403)
        for changes in ({"fanout_limit": True}, {"fanout_limit": "10"},
                        {"expected_generation": "0"}, {"policy_version": "arbitrary"},
                        {"extra": True}):
            with self.subTest(changes=changes):
                self.assertEqual(self.post({**command, **changes}).status_code, 400)
        duplicate = json.dumps(command)[:-1] + ',"command_id":"' + command["command_id"] + '"}'
        self.assertEqual(self.post(duplicate, raw=True).status_code, 400)
        self.assertFalse(NewsPublication.objects.exists())

    def test_foreign_staff_cannot_read_preview_current_or_publish(self):
        self.case.other.is_staff = True
        self.case.other.is_superuser = True
        self.case.other.save(update_fields=("is_staff", "is_superuser"))
        foreign = Client(enforce_csrf_checks=True)
        foreign.force_login(self.case.other)
        command = self.command()
        self.assertEqual(foreign.get(self.preview_path,
            {"fanout_limit": 10, "policy_version": POLICY_VERSION}).status_code, 404)
        self.assertEqual(self.post(command, client=foreign).status_code, 404)
        self.assertEqual(foreign.get(f"/api/v1/theses/{self.thesis_id}/news-brief/").status_code, 404)

    def test_source_correction_cancels_current_and_saved_retry_does_not_reactivate(self):
        command = self.command()
        saved = self.post(command).json()
        self.case.background("Corrected source after internal driver publication")
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            with patch("macro_agent.theses.compilation.create_provider", side_effect=AssertionError("No model")):
                retry = self.post(command)
                recovered = self.client.get(f"/api/v1/theses/{self.thesis_id}/news-publication-commands/{command['command_id']}/")
                current = self.client.get(f"/api/v1/theses/{self.thesis_id}/news-brief/")
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(recovered.status_code, 200, recovered.content)
        self.assertEqual(recovered.json()["publication"], saved["publication"])
        self.assertEqual(recovered.json()["current_disposition"]["status"], "superseded")
        self.assertEqual(recovered.json()["notification_intent"]["state"], "canceled")
        self.assertIsNone(current.json()["current_publication"])
        self.assertEqual(NewsPublication.objects.count(), 1)

    def test_schema_includes_separate_typed_publication_and_research(self):
        output = io.StringIO()
        call_command("spectacular", "--validate", "--fail-on-warn", "--format", "openapi-json", stdout=output)
        schema = json.loads(output.getvalue())
        self.assertIn("/api/v1/research/", schema["paths"])
        self.assertIn("/api/v1/news-analyses/{analysis_id}/publish/", schema["paths"])
        component = schema["components"]["schemas"]["PublishNewsRequest"]
        self.assertFalse(component["additionalProperties"])
        self.assertIn("expected_analysis_digest", component["required"])
