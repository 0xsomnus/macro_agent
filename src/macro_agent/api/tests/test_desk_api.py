"""Real private sessions and read-only retained-review snapshot evidence."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import io
import json
from contextlib import redirect_stderr
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection, connections, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from macro_agent.api.desk_serializers import DailyReviewDetailSerializer, DailyReviewListSerializer
from macro_agent.desk import permissions, reading, service
from macro_agent.desk.models import DailyReview, EvidenceSet, PrivateContext
from macro_agent.domain.daily_review import DailyReviewLimits
from macro_agent.monitoring import analysis, capture
from macro_agent.monitoring.models import NewsAnalysisAttempt, SourceRevision, SourceState
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.positions import service as positions
from macro_agent.positions.models import PositionRecord
from macro_agent.theses import service as theses


SOURCE = "fixture-daily-api"
CONTRACT = {"kind": "fictional_fixture", "label": "Fictional daily read feed",
            "coverage": "bounded_snapshot"}
EXACT = "  Easier policy may support equities.\r\nΔ\r\n"
MEANING = {"drivers": ["Easier policy"], "horizon": "medium term",
           "invalidation_signposts": ["Policy transmission fails"]}
LIMITS = DailyReviewLimits(reports=100, analyses=100, exposure_versions=200,
                          issues=300, source_contracts=16, encoded_bytes=2_000_000)
DECLARATION = {"underlying": "NQ", "direction": "long", "quantity": None,
    "quantity_unit": None, "horizon": None, "product_id": None, "venue": None,
    "expiry": None, "quote_currency": None}


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ALLOW_SYNTHETIC_SETUP=True, SETTINGS_MODULE="macro_agent.web.local_settings")
class DailyReviewReadAPITests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("Daily review HTTP snapshot evidence requires PostgreSQL")
        self.owner = get_user_model().objects.create_user(username="daily-api-owner", password="recorded-password")
        self.other = get_user_model().objects.create_user(username="daily-api-staff", is_staff=True,
                                                         is_superuser=True)
        self.actor = str(self.owner.pk)
        draft = theses.create_thesis(self.actor, str(uuid4()), EXACT, MEANING)["thesis"]
        text, meaning = draft["draft"]["text_version"], draft["draft"]["interpretation"]
        self.thesis = theses.approve_thesis(self.actor, draft["id"], str(uuid4()),
            text["id"], text["text_digest"], meaning["id"], meaning["digest"], draft["revision"])["thesis"]
        self.list_path = f"/api/v1/theses/{self.thesis['id']}/daily-reviews/"
        self.client = Client(enforce_csrf_checks=True)
        token = self.client.get("/api/v1/session/").json()["csrf_token"]
        response = self.client.post("/api/v1/session/login/", json.dumps({
            "username": self.owner.username, "password": "recorded-password"}),
            content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200, response.content)
        self.capture()

    def capture(self, title="Fictional policy report", native="report-1"):
        item = SourceItem(native, title, "https://example.invalid/daily-report",
            timezone.now() - timedelta(days=1), "Fictional retained passage. " * 500)
        return capture.capture(SOURCE, CONTRACT, lambda: SourceBatch((item,), timezone.now(),
            "bounded_snapshot", False, sha256(b"daily-api transport").hexdigest()))

    def review(self):
        cutoff = timezone.now()
        previous = DailyReview.objects.filter(owner=self.owner).order_by("-cutoff").first()
        return service.create_review(self.actor, self.thesis["id"], str(uuid4()),
            previous.cutoff if previous else cutoff - timedelta(days=1), cutoff, [SOURCE], LIMITS)

    def detail_path(self, review_id):
        return f"/api/v1/daily-reviews/{review_id}/"

    def get_list(self, query=""):
        response = self.client.get(self.list_path + query)
        self.assertEqual(response.status_code, 200, response.content)
        serializer = DailyReviewListSerializer(data=response.json())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return response

    def test_real_session_lists_compact_retained_summaries_and_exact_detail(self):
        original = self.review()
        response = self.get_list()
        result, summary = response.json(), response.json()["reviews"][0]
        self.assertEqual(result["total"], 1)
        self.assertFalse(result["has_more"])
        self.assertFalse(result["publication_authority"])
        self.assertEqual(summary["id"], original["review"]["id"])
        self.assertEqual(summary["original_outcome"], "prepared")
        self.assertEqual(summary["current_disposition"]["status"], "prepared")
        self.assertEqual(summary["current_disposition"]["observed_at"], result["observed_at"])
        self.assertEqual(summary["counts"]["reports"], {"new": 1, "background": 0, "deferred": 0})
        self.assertEqual(summary["source_manifest"], original["review"]["evidence_set"]["source_manifest"])
        self.assertNotIn("content", summary)
        self.assertNotIn("original_inputs", summary)
        self.assertNotIn("Fictional retained passage", response.content.decode())
        detail = self.client.get(self.detail_path(summary["id"]))
        self.assertEqual(detail.status_code, 200, detail.content)
        serializer = DailyReviewDetailSerializer(data=detail.json())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(detail.json()["review"], original["review"])
        self.assertEqual(detail.json()["review"]["original_inputs"]["approved_user"]["text"]["exact_text"], EXACT)
        self.assertLess(len(response.content), len(detail.content) // 5)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(detail["Cache-Control"], "no-store")

    def test_bounded_pagination_has_stable_order_total_and_empty_page(self):
        originals = [self.review()["review"] for _ in range(3)]
        first = self.get_list("?limit=2&offset=0").json()
        second = self.get_list("?limit=2&offset=2").json()
        empty = self.get_list("?limit=2&offset=1000000").json()
        ids = [item["id"] for item in first["reviews"] + second["reviews"]]
        self.assertEqual(ids, [item["id"] for item in reversed(originals)])
        self.assertEqual((first["total"], second["total"], empty["total"]), (3, 3, 3))
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        self.assertEqual(empty["reviews"], [])
        self.assertFalse(empty["has_more"])
        self.assertEqual(first["observed_at"], first["reviews"][0]["current_disposition"]["observed_at"])
        self.assertEqual(first["observed_at"], first["reviews"][1]["current_disposition"]["observed_at"])

    def test_empty_owned_thesis_has_a_real_empty_page_without_fetching(self):
        result = self.get_list().json()
        self.assertEqual(result["reviews"], [])
        self.assertEqual(result["total"], 0)
        self.assertFalse(result["has_more"])

    def test_page_observes_shared_governing_state_once_without_loading_full_content(self):
        for _ in range(5):
            self.review()
        with CaptureQueriesContext(connection) as queries:
            result = reading.list_reviews(self.actor, self.thesis["id"])
        self.assertEqual(len(result["reviews"]), 5)
        statements = [query["sql"] for query in queries.captured_queries]
        self.assertEqual(sum(f'FROM "{PositionRecord._meta.db_table}"' in sql for sql in statements), 1)
        # One head set plus one permission lookup for the single shared source,
        # independent of the number of saved daily reviews in this page.
        self.assertEqual(sum('FROM "macro_desk_sourcecontracthead"' in sql for sql in statements), 2)
        self.assertFalse(any('"macro_desk_dailyreview"."content",' in sql for sql in statements))
        self.assertFalse(any('."payload"' in sql for sql in statements))

    def test_anonymous_and_staff_foreign_ids_do_not_disclose_private_reviews(self):
        original = self.review()["review"]
        anonymous = Client(enforce_csrf_checks=True)
        self.assertEqual(anonymous.get(self.list_path).status_code, 403)
        self.assertEqual(anonymous.get(self.detail_path(original["id"])).status_code, 403)
        foreign = Client(enforce_csrf_checks=True)
        foreign.force_login(self.other)
        absent_list = f"/api/v1/theses/{uuid4()}/daily-reviews/"
        absent_detail = self.detail_path(str(uuid4()))
        for path, absent in ((self.list_path, absent_list), (self.detail_path(original["id"]), absent_detail)):
            response = foreign.get(path)
            missing = foreign.get(absent)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), missing.json())
        self.assertEqual(self.client.get(absent_detail).json(), foreign.get(absent_detail).json())

    def test_local_and_continuous_gates_hide_routes_before_authentication(self):
        original = self.review()["review"]
        paths = (self.list_path, self.detail_path(original["id"]))
        for changes in ({"MACRO_ENABLE_CONTINUOUS_DESK": False},
                        {"MACRO_ENABLE_MONITORING_PROOF": False},
                        {"SETTINGS_MODULE": "macro_agent.web.settings"}):
            with self.subTest(changes=changes), override_settings(**changes):
                for client in (self.client, Client(enforce_csrf_checks=True)):
                    for path in paths:
                        self.assertEqual(client.get(path).status_code, 404)
        database = deepcopy(settings.DATABASES)
        database["default"]["NAME"] = "macro_agent_production"
        with patch.object(service.settings, "DATABASES", database):
            for path in paths:
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_strict_queries_reject_unknown_repeated_and_coerced_pagination(self):
        queries = ("?owner_id=" + self.actor, "?limit=0", "?limit=101", "?limit=true",
            "?limit=1.0", "?limit=+1", "?limit=%201", "?limit=1&limit=2", "?offset=-1",
            "?offset=1000001", "?offset=0&offset=0", "?retry=1")
        for query in queries:
            with self.subTest(query=query):
                self.assertEqual(self.client.get(self.list_path + query).status_code, 400)
        original = self.review()["review"]
        for query in ("?limit=1", "?retry=1", "?owner_id=" + self.actor):
            self.assertEqual(self.client.get(self.detail_path(original["id"]) + query).status_code, 400)

    def test_stale_present_dependencies_do_not_rewrite_saved_review_or_grant_authority(self):
        original = self.review()["review"]
        self.capture(title="Corrected fictional report")
        positions.create_position(self.actor, self.thesis["id"], str(uuid4()),
            self.thesis["approved"]["approval"]["id"], DECLARATION)
        source = SourceState.objects.get(pk=SOURCE)
        permissions.set_source_permission(str(self.other.pk), SOURCE, source.contract_digest, False,
                                          "Explicit test withdrawal")
        summary = self.get_list().json()["reviews"][0]
        detail = self.client.get(self.detail_path(original["id"]))
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.json()["review"], original)
        self.assertEqual(summary["original_outcome"], "prepared")
        self.assertEqual(summary["current_disposition"]["status"], "stale")
        self.assertEqual(summary["current_disposition"]["stale_reasons"],
                         detail.json()["current_disposition"]["stale_reasons"])
        self.assertIn("paper_exposure_changed", summary["current_disposition"]["stale_reasons"])
        self.assertIn("source_contract_or_permission_changed:" + SOURCE,
                      summary["current_disposition"]["stale_reasons"])
        self.assertFalse(summary["current_disposition"]["publication_authority"])

    def test_all_gets_remain_read_only_without_provider_configuration_or_network(self):
        original = self.review()["review"]
        def counts():
            return [model.objects.count() for model in (DailyReview, PrivateContext, EvidenceSet,
                SourceRevision, NewsAnalysisAttempt, CurrentAssessment, NotificationIntent)]
        before = counts()
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_ENABLE_MODEL_COMPILATION=False,
                               MACRO_ENABLE_NEWS_ANALYSIS=False,
                               SETTINGS_MODULE="macro_agent.web.local_settings"), \
                patch.object(analysis, "create_provider", side_effect=AssertionError("No model calls")) as provider, \
                patch.object(capture, "capture", side_effect=AssertionError("No source fetches")) as source:
            self.get_list()
            detail = self.client.get(self.detail_path(original["id"]))
            self.assertEqual(detail.status_code, 200, detail.content)
            provider.assert_not_called()
            source.assert_not_called()
        self.assertEqual(before, counts())
        for path in (self.list_path, self.detail_path(original["id"])):
            for method in ("post", "put", "patch", "delete"):
                self.assertEqual(getattr(self.client, method)(path, "{}", content_type="application/json").status_code, 403)
            token = self.client.get("/api/v1/session/").json()["csrf_token"]
            self.assertEqual(self.client.post(path, "{}", content_type="application/json",
                HTTP_X_CSRFTOKEN=token).status_code, 405)

    def test_count_page_and_disposition_share_read_only_repeatable_snapshot(self):
        original = self.review()["review"]
        observed = {}
        def writer():
            connections.close_all()
            try:
                self.capture(title="Committed during the read snapshot")
                self.review()
            finally:
                connections.close_all()
        def clock():
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                observed["isolation"] = cursor.fetchone()[0]
                cursor.execute("SHOW transaction_read_only")
                observed["read_only"] = cursor.fetchone()[0]
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(writer).result(timeout=20)
            return timezone.now()
        result = reading.list_reviews(self.actor, self.thesis["id"], clock=clock)
        self.assertEqual(observed, {"isolation": "repeatable read", "read_only": "on"})
        self.assertEqual(result["total"], 1)
        self.assertEqual([row["id"] for row in result["reviews"]], [original["id"]])
        self.assertEqual(result["reviews"][0]["current_disposition"]["status"], "prepared")
        later = self.get_list().json()
        self.assertEqual(later["total"], 2)
        self.assertEqual(later["reviews"][1]["current_disposition"]["status"], "stale")

    def test_direct_service_rejects_ambient_transaction_and_backdated_observation(self):
        original = self.review()["review"]
        with transaction.atomic(), self.assertRaises(RuntimeError):
            reading.list_reviews(self.actor, self.thesis["id"])
        for values in ({"limit": True}, {"offset": "0"}, {"limit": 0}, {"offset": -1}):
            with self.subTest(values=values), self.assertRaises((ValueError, TypeError)):
                reading.list_reviews(self.actor, self.thesis["id"], **values)
        with self.assertRaises(theses.ThesisConflict):
            reading.list_reviews(self.actor, self.thesis["id"],
                clock=lambda: DailyReview.objects.get(pk=original["id"]).prepared_at - timedelta(microseconds=1))

    def test_generated_openapi_explicitly_describes_read_only_envelopes(self):
        stderr, output = io.StringIO(), io.StringIO()
        with redirect_stderr(stderr):
            call_command("spectacular", "--validate", "--fail-on-warn", "--format", "openapi-json", stdout=output)
        self.assertEqual(stderr.getvalue(), "")
        schema = json.loads(output.getvalue())
        collection = schema["paths"]["/api/v1/theses/{thesis_id}/daily-reviews/"]
        detail = schema["paths"]["/api/v1/daily-reviews/{review_id}/"]
        self.assertEqual(set(collection), {"get"})
        self.assertEqual(set(detail), {"get"})
        for operation in (collection["get"], detail["get"]):
            self.assertEqual(operation["security"], [{"cookieAuth": []}])
            self.assertIn("inference or write fallback", operation["description"])
            self.assertEqual(set(operation["responses"]), {"200", "400", "403", "404", "409"})
        self.assertEqual({parameter["name"] for parameter in collection["get"]["parameters"]},
                         {"thesis_id", "limit", "offset"})
        self.assertEqual({parameter["name"] for parameter in detail["get"]["parameters"]}, {"review_id"})
        components = schema["components"]["schemas"]
        self.assertEqual(set(components["DailyReviewDetail"]["required"]),
                         {"review", "current_disposition", "replayed"})
        self.assertIn("total", components["DailyReviewList"]["required"])
        self.assertNotIn("content", components["DailyReviewSummary"]["properties"])
