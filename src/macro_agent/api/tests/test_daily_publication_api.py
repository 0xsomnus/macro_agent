"""Real session publication, strict commands and private read-only recovery."""

from io import StringIO
import json
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.test import Client, TransactionTestCase, override_settings

from macro_agent.api.daily_publication_serializers import (
    CurrentDailyBriefSerializer, DailyPublicationDetailSerializer, DailyPublicationPreviewSerializer,
)
from macro_agent.api.tests import test_desk_api as fixtures
from macro_agent.desk.models import DailyReview, EvidenceSet, PrivateContext
from macro_agent.monitoring import analysis, capture
from macro_agent.monitoring.models import NewsAnalysisAttempt
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.positions import service as positions


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ALLOW_SYNTHETIC_SETUP=True, SETTINGS_MODULE="macro_agent.web.local_settings")
class DailyPublicationAPITests(TransactionTestCase):
    setUp = fixtures.DailyReviewReadAPITests.setUp
    capture = fixtures.DailyReviewReadAPITests.capture
    review = fixtures.DailyReviewReadAPITests.review

    def current_path(self):
        return f"/api/v1/theses/{self.thesis['id']}/daily-brief/"

    def preview_path(self, review_id):
        return f"/api/v1/daily-reviews/{review_id}/publication-preview/"

    def publish_path(self, review_id):
        return f"/api/v1/daily-reviews/{review_id}/publish/"

    def detail_path(self, publication_id):
        return f"/api/v1/daily-publications/{publication_id}/"

    def preview(self, review_id):
        response = self.client.get(self.preview_path(review_id) + "?fanout_limit=100")
        self.assertEqual(response.status_code, 200, response.content)
        serializer = DailyPublicationPreviewSerializer(data=response.json())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return response.json()

    def command(self, preview):
        return {"command_id": str(uuid4()), "expected_review_digest": preview["review_digest"],
                "expected_generation": preview["expected_generation"], "fanout_limit": 100}

    def post(self, review_id, command, *, token=True, raw=False):
        headers = ({"HTTP_X_CSRFTOKEN": self.client.get("/api/v1/session/").json()["csrf_token"]}
                   if token else {})
        return self.client.post(self.publish_path(review_id), command if raw else json.dumps(command),
                                content_type="application/json", **headers)

    def publish(self):
        original = self.review()["review"]
        preview = self.preview(original["id"])
        command = self.command(preview)
        response = self.post(original["id"], command)
        self.assertEqual(response.status_code, 200, response.content)
        serializer = DailyPublicationDetailSerializer(data=response.json())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return original, command, response.json()

    def test_session_preview_publish_current_and_detail_preserve_exact_review(self):
        original, command, saved = self.publish()
        self.assertEqual(saved["review"], original)
        self.assertEqual(saved["review"]["original_inputs"]["approved_user"]["text"]["exact_text"], fixtures.EXACT)
        self.assertEqual(saved["publication"]["command_id"], command["command_id"])
        self.assertEqual(saved["publication"]["original_decision"]["status"], "current")
        self.assertEqual(saved["notification_intent"]["state"], "pending")
        current = self.client.get(self.current_path())
        self.assertEqual(current.status_code, 200, current.content)
        serializer = CurrentDailyBriefSerializer(data=current.json())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(current.json()["current_publication"]["publication"], saved["publication"])
        detail = self.client.get(self.detail_path(saved["publication"]["id"]))
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.json()["publication"], saved["publication"])
        self.assertEqual(detail.json()["review"], original)
        for response in (current, detail):
            self.assertEqual(response["Cache-Control"], "no-store")

    def test_preview_and_unpublished_current_reads_create_no_state_or_historical_fallback(self):
        original = self.review()["review"]
        before = [model.objects.count() for model in
                  (DailyReview, PrivateContext, EvidenceSet, CurrentAssessment, NotificationIntent)]
        self.preview(original["id"])
        current = self.client.get(self.current_path())
        self.assertEqual(current.status_code, 200, current.content)
        self.assertIsNone(current.json()["current_publication"])
        self.assertEqual(current.json()["generation"], 0)
        after = [model.objects.count() for model in
                 (DailyReview, PrivateContext, EvidenceSet, CurrentAssessment, NotificationIntent)]
        self.assertEqual(before, after)

    def test_csrf_is_required_before_publication_and_foreign_staff_cannot_publish_or_read(self):
        original = self.review()["review"]
        command = self.command(self.preview(original["id"]))
        self.assertEqual(self.post(original["id"], command, token=False).status_code, 403)
        self.assertEqual(NotificationIntent.objects.count(), 0)
        saved = self.post(original["id"], command).json()
        foreign = Client(enforce_csrf_checks=True)
        foreign.force_login(self.other)
        paths = ((self.current_path(), f"/api/v1/theses/{uuid4()}/daily-brief/"),
            (self.preview_path(original["id"]) + "?fanout_limit=100",
             self.preview_path(str(uuid4())) + "?fanout_limit=100"),
            (self.detail_path(saved["publication"]["id"]), self.detail_path(str(uuid4()))))
        for path, missing in paths:
            with self.subTest(path=path):
                denied = foreign.get(path)
                self.assertEqual(denied.status_code, 404)
                self.assertEqual(denied.json(), foreign.get(missing).json())
                self.assertEqual(Client().get(path).status_code, 403)
        token = foreign.get("/api/v1/session/").json()["csrf_token"]
        denied = foreign.post(self.publish_path(original["id"]), json.dumps(command),
            content_type="application/json", HTTP_X_CSRFTOKEN=token)
        missing = foreign.post(self.publish_path(str(uuid4())), json.dumps(command),
            content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(denied.json(), missing.json())

    def test_strict_write_rejects_unknown_fields_duplicate_keys_and_coercion_before_writes(self):
        original = self.review()["review"]
        command = self.command(self.preview(original["id"]))
        mutations = [{**command, "owner_id": self.actor},
            {**command, "expected_generation": True}, {**command, "expected_generation": "0"},
            {**command, "expected_generation": 0.0}, {**command, "fanout_limit": "100"},
            {**command, "fanout_limit": True}, {**command, "fanout_limit": 1001},
            {**command, "expected_review_digest": 123},
            {**command, "expected_review_digest": command["expected_review_digest"].upper()},
            {**command, "expected_review_digest": " " + command["expected_review_digest"]},
            {name: value for name, value in command.items() if name != "fanout_limit"}]
        for changed in mutations:
            with self.subTest(changed=changed):
                self.assertEqual(self.post(original["id"], changed).status_code, 400)
        raw = json.dumps(command)[:-1] + ',"fanout_limit":100}'
        self.assertEqual(self.post(original["id"], raw, raw=True).status_code, 400)
        self.assertEqual(NotificationIntent.objects.count(), 0)

    def test_strict_read_queries_require_explicit_fanout_and_disallow_hidden_actions(self):
        original, _, saved = self.publish()
        preview = self.preview_path(original["id"])
        for query in ("", "?fanout_limit=0", "?fanout_limit=1001", "?fanout_limit=true",
                      "?fanout_limit=1.0", "?fanout_limit=+1", "?fanout_limit=%201",
                      "?fanout_limit=1&fanout_limit=2", "?fanout_limit=100&retry=1"):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(preview + query).status_code, 400)
        for path in (self.current_path(), self.detail_path(saved["publication"]["id"])):
            self.assertEqual(self.client.get(path + "?retry=1").status_code, 400)

    def test_wrong_review_digest_is_rejected_before_publication_or_intent(self):
        original = self.review()["review"]
        command = self.command(self.preview(original["id"]))
        response = self.post(original["id"], {**command, "expected_review_digest": "0" * 64})
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(NotificationIntent.objects.count(), 0)
        self.assertIsNone(self.client.get(self.current_path()).json()["current_publication"])

    def test_saved_command_retry_after_exposure_change_preserves_original_and_does_not_reactivate(self):
        original, command, saved = self.publish()
        positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
                                  self.thesis["approved"]["approval"]["id"], fixtures.DECLARATION)
        replay = self.post(original["id"], command)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json()["publication"], saved["publication"])
        self.assertTrue(replay.json()["replayed"])
        self.assertEqual(replay.json()["current_disposition"]["status"], "superseded")
        self.assertEqual(replay.json()["notification_intent"]["state"], "canceled")
        self.assertIsNone(self.client.get(self.current_path()).json()["current_publication"])
        self.assertEqual(NotificationIntent.objects.count(), 1)
        changed = {**command, "fanout_limit": 99}
        self.assertEqual(self.post(original["id"], changed).status_code, 409)

    def test_stale_review_attempt_retains_superseded_decision_and_no_notification_intent(self):
        original = self.review()["review"]
        self.capture(title="Corrected report before publication")
        preview = self.preview(original["id"])
        self.assertEqual(preview["current_disposition"]["status"], "stale")
        response = self.post(original["id"], self.command(preview))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["publication"]["original_decision"]["status"], "superseded")
        self.assertEqual(response.json()["review"], original)
        self.assertIsNone(response.json()["notification_intent"])
        self.assertEqual(NotificationIntent.objects.count(), 0)

    def test_publication_and_gets_need_no_model_keys_or_source_fetches(self):
        original = self.review()["review"]
        before = NewsAnalysisAttempt.objects.count()
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_ENABLE_MODEL_COMPILATION=False,
                               MACRO_ENABLE_NEWS_ANALYSIS=False,
                               SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch.object(analysis, "create_provider", side_effect=AssertionError("No models")), \
                patch.object(capture, "capture", side_effect=AssertionError("No source requests")):
            preview = self.preview(original["id"])
            response = self.post(original["id"], self.command(preview))
            self.assertEqual(response.status_code, 200, response.content)
            for path in (self.current_path(), self.detail_path(response.json()["publication"]["id"])):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(NewsAnalysisAttempt.objects.count(), before)

    def test_disabled_local_or_continuous_gates_hide_publication_routes(self):
        original, command, saved = self.publish()
        for changes in ({"MACRO_ENABLE_CONTINUOUS_DESK": False},
                        {"MACRO_ENABLE_MONITORING_PROOF": False},
                        {"SETTINGS_MODULE": "macro_agent.web.settings"}):
            with self.subTest(changes=changes), override_settings(**changes):
                for path in (self.current_path(), self.preview_path(original["id"]) + "?fanout_limit=100",
                             self.detail_path(saved["publication"]["id"])):
                    self.assertEqual(self.client.get(path).status_code, 404)
                self.assertEqual(self.post(original["id"], command).status_code, 404)

    def test_generated_openapi_describes_strict_authority_and_separate_decisions(self):
        output = StringIO()
        call_command("spectacular", "--validate", "--fail-on-warn", "--format", "openapi-json", stdout=output)
        schema = json.loads(output.getvalue())
        current = schema["paths"]["/api/v1/theses/{thesis_id}/daily-brief/"]
        detail = schema["paths"]["/api/v1/daily-publications/{publication_id}/"]
        publish = schema["paths"]["/api/v1/daily-reviews/{review_id}/publish/"]
        preview = schema["paths"]["/api/v1/daily-reviews/{review_id}/publication-preview/"]
        self.assertEqual(set(current), {"get"})
        self.assertEqual(set(detail), {"get"})
        self.assertEqual(set(preview), {"get"})
        self.assertEqual(set(publish), {"post"})
        self.assertEqual(publish["post"]["security"], [{"cookieAuth": []}])
        components = schema["components"]["schemas"]
        command = components["PublishDailyReviewRequest"]
        self.assertFalse(command["additionalProperties"])
        self.assertEqual(set(command["required"]),
                         {"command_id", "expected_review_digest", "expected_generation", "fanout_limit"})
        self.assertEqual(set(components["DailyPublicationDetail"]["required"]),
                         {"publication", "current_disposition", "notification_intent", "review", "replayed"})
