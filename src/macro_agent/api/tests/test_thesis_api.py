"""Real session, CSRF, ownership, and exact-approval HTTP regressions."""

import hashlib
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from drf_spectacular.validation import validate_schema

from macro_agent.theses.models import ApprovalRecord, CommandReceipt, TextVersionRecord, ThesisRecord


COLLECTION = "/api/v1/theses/"
SESSION = "/api/v1/session/"
LOGIN = "/api/v1/session/login/"
LOGOUT = "/api/v1/session/logout/"


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ThesisAPITests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("HTTP authority evidence requires PostgreSQL, not a SQLite substitute")
        self.owner = get_user_model().objects.create_user(username="api-owner", password="fixture-secret")
        self.other = get_user_model().objects.create_user(username="api-other", password="other-secret")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)
        self.token = self.client.get(SESSION).json()["csrf_token"]

    def command(self, text="Rates can weaken the currency."):
        return {
            "command_id": str(uuid.uuid4()), "text": text,
            "interpretation": {
                "drivers": ["policy rates"], "horizon": "next quarter",
                "invalidation_signposts": ["rate divergence reverses"],
            },
        }

    def post(self, path, body, *, client=None, token=None):
        return (client or self.client).post(
            path, data=json.dumps(body, ensure_ascii=True), content_type="application/json",
            HTTP_X_CSRFTOKEN=token or self.token,
        )

    def create(self, command=None):
        command = command or self.command()
        response = self.post(COLLECTION, command)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def approval_command(self, detail):
        draft = detail["draft"]
        return {
            "command_id": str(uuid.uuid4()), "expected_revision": detail["revision"],
            "thesis_version_id": draft["text_version"]["id"],
            "text_digest": draft["text_version"]["text_digest"],
            "interpretation_version_id": draft["interpretation"]["id"],
            "interpretation_digest": draft["interpretation"]["digest"],
        }

    def approve(self, detail):
        command = self.approval_command(detail)
        path = f"{COLLECTION}{detail['id']}/approvals/"
        response = self.post(path, command)
        self.assertEqual(response.status_code, 200, response.content)
        return command, response.json()

    def proposal(self, detail, text="An amended user view."):
        command = {**self.command(text), "expected_revision": detail["revision"]}
        response = self.post(f"{COLLECTION}{detail['id']}/proposals/", command)
        self.assertEqual(response.status_code, 201, response.content)
        return command, response.json()

    def test_anonymous_thesis_and_schema_access_is_denied(self):
        client = Client(enforce_csrf_checks=True)
        for path in (COLLECTION, "/api/v1/schema/", f"{COLLECTION}{uuid.uuid4()}/history/"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 403)
        self.assertEqual(self.post(COLLECTION, self.command(), client=client).status_code, 403)
        self.assertFalse(ThesisRecord.objects.exists())

    def test_anonymous_session_bootstrap_returns_masked_csrf_token(self):
        response = Client(enforce_csrf_checks=True).get(SESSION)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["authenticated"], False)
        self.assertIsNone(response.json()["user"])
        self.assertEqual(len(response.json()["csrf_token"]), 64)
        self.assertTrue(response.cookies["csrftoken"]["httponly"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_anonymous_login_requires_csrf_and_uses_django_session(self):
        client = Client(enforce_csrf_checks=True)
        credentials = {"username": self.owner.username, "password": "fixture-secret"}
        rejected = client.post(LOGIN, json.dumps(credentials), content_type="application/json")
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(client.get(SESSION).json()["authenticated"], False)
        before = client.cookies["csrftoken"].value
        token = client.get(SESSION).json()["csrf_token"]
        accepted = self.post(LOGIN, credentials, client=client, token=token)
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.assertEqual(accepted.json()["user"]["id"], str(self.owner.pk))
        self.assertNotEqual(client.cookies["csrftoken"].value, before)
        self.assertEqual(client.get(COLLECTION).status_code, 200)

    def test_login_does_not_disclose_account_existence(self):
        client = Client(enforce_csrf_checks=True)
        token = client.get(SESSION).json()["csrf_token"]
        bodies = []
        for username in ("does-not-exist", self.owner.username):
            response = self.post(LOGIN, {"username": username, "password": "wrong"}, client=client, token=token)
            self.assertEqual(response.status_code, 403)
            bodies.append(response.json())
        self.assertEqual(bodies[0], bodies[1])

    def test_login_rejects_unknown_fields_coercion_and_duplicate_keys(self):
        client = Client(enforce_csrf_checks=True)
        token = client.get(SESSION).json()["csrf_token"]
        credentials = {"username": self.owner.username, "password": "fixture-secret"}
        for body in ({**credentials, "actor_id": str(self.owner.pk)}, {**credentials, "password": 123}):
            with self.subTest(body=body.keys()):
                self.assertEqual(self.post(LOGIN, body, client=client, token=token).status_code, 400)
        duplicate = '{"username":"api-owner","password":"wrong","password":"fixture-secret"}'
        response = client.post(LOGIN, duplicate, content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(client.get(SESSION).json()["authenticated"], False)
        response = client.post(LOGIN, credentials, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 415)

    def test_logout_requires_csrf_and_removes_session_identity(self):
        before = self.client.cookies["csrftoken"].value
        self.assertEqual(self.client.post(LOGOUT, "{}", content_type="application/json").status_code, 403)
        self.assertEqual(self.client.get(SESSION).json()["authenticated"], True)
        response = self.post(LOGOUT, {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["authenticated"], False)
        self.assertNotEqual(self.client.cookies["csrftoken"].value, before)
        self.assertEqual(self.client.get(COLLECTION).status_code, 403)

    def test_authenticated_commands_require_valid_csrf(self):
        for headers in ({}, {"HTTP_X_CSRFTOKEN": "0" * 64}):
            response = self.client.post(COLLECTION, json.dumps(self.command()), content_type="application/json", **headers)
            self.assertEqual(response.status_code, 403)
        self.assertFalse(ThesisRecord.objects.exists())

    def test_exact_text_preserves_whitespace_and_unicode_composition(self):
        text = "  Café and e\u0301\r\n政策 \U0001f680\t "
        result = self.create(self.command(text))
        saved = result["thesis"]["draft"]["text_version"]
        self.assertEqual(saved["exact_text"], text)
        self.assertEqual(saved["text_digest"], hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(TextVersionRecord.objects.get(pk=saved["id"]).exact_text, text)
        self.assertIsNone(result["thesis"]["approved"])
        self.assertEqual(result["thesis"]["draft"]["interpretation"]["origin"], "user_supplied")
        self.assertEqual(result["thesis"]["monitoring"], "not_configured")

    def test_unresolved_interpretation_remains_empty_and_null(self):
        command = self.command()
        command["interpretation"] = {"drivers": [], "horizon": None, "invalidation_signposts": []}
        meaning = self.create(command)["thesis"]["draft"]["interpretation"]
        for key, value in command["interpretation"].items():
            self.assertEqual(meaning[key], value)

    def test_inputs_reject_client_authority_and_type_coercion(self):
        base = self.command()
        invalid = [
            {**base, "text": 1}, {**base, "text": True}, {**base, "command_id": True},
            {**base, "actor_id": str(self.owner.pk)}, {**base, "owner_id": str(self.owner.pk)},
            {**base, "role": "user"}, {**base, "created_at": "2026-01-01T00:00:00Z"},
            {**base, "current_approval": str(uuid.uuid4())},
            {**base, "interpretation": {**base["interpretation"], "known_at": "2026-01-01T00:00:00Z"}},
            {**base, "interpretation": {**base["interpretation"], "origin": "model_compiled"}},
            {**base, "interpretation": {**base["interpretation"], "drivers": [7]}},
            {**base, "interpretation": {**base["interpretation"], "drivers": "rates"}},
        ]
        for body in invalid:
            with self.subTest(keys=list(body)):
                self.assertEqual(self.post(COLLECTION, body).status_code, 400)
        self.assertFalse(ThesisRecord.objects.exists())

    def test_json_decoder_rejects_ambiguous_invalid_and_oversized_bodies(self):
        bodies = [
            b'{"text":"a","text":"b"}', b'{"a":"\\ud800"}', b'{"a":"\\u0000"}',
            b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e999}', b'[]', b'{"a":"\xff"}',
            b'{"a":"' + b'x' * (128 * 1024) + b'"}',
        ]
        for body in bodies:
            with self.subTest(prefix=body[:20]):
                response = self.client.post(COLLECTION, body, content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
                self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(ThesisRecord.objects.exists())

    def test_only_utf8_json_is_accepted_for_commands(self):
        body = json.dumps(self.command())
        for media_type in ("text/plain", "application/json; charset=iso-8859-1"):
            response = self.client.post(COLLECTION, body, content_type=media_type, HTTP_X_CSRFTOKEN=self.token)
            self.assertEqual(response.status_code, 415)
        response = self.client.post(COLLECTION, body, content_type="application/json; charset=utf-8", HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(response.status_code, 201, response.content)

    def test_field_and_array_limits_are_enforced(self):
        base = self.command()
        invalid = [
            {**base, "text": "x" * 20001},
            {**base, "interpretation": {**base["interpretation"], "drivers": [str(i) for i in range(33)]}},
            {**base, "interpretation": {**base["interpretation"], "horizon": "x" * 1001}},
            {**base, "interpretation": {**base["interpretation"], "invalidation_signposts": ["x"] * 33}},
        ]
        for body in invalid:
            self.assertEqual(self.post(COLLECTION, body).status_code, 400)
        self.assertFalse(ThesisRecord.objects.exists())

    def test_revision_numbers_are_not_coerced(self):
        detail = self.create()["thesis"]
        path = f"{COLLECTION}{detail['id']}/proposals/"
        for revision in (True, "1", 1.0, 0):
            response = self.post(path, {**self.command(), "expected_revision": revision})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(TextVersionRecord.objects.count(), 1)

    def test_lists_are_owner_scoped_and_pagination_is_bounded(self):
        detail = self.create()["thesis"]
        response = self.client.get(COLLECTION + "?limit=1&offset=0")
        self.assertEqual([item["id"] for item in response.json()["theses"]], [detail["id"]])
        other = Client(enforce_csrf_checks=True)
        other.force_login(self.other)
        self.assertEqual(other.get(COLLECTION).json()["theses"], [])
        for query in ("actor_id=x", "limit=0", "limit=101", "offset=-1", "offset=1000001", "limit=1&limit=1", "offset=true"):
            self.assertEqual(self.client.get(COLLECTION + "?" + query).status_code, 400)

    def test_foreign_and_missing_theses_share_opaque_responses(self):
        detail = self.create()["thesis"]
        other = Client(enforce_csrf_checks=True)
        other.force_login(self.other)
        token = other.get(SESSION).json()["csrf_token"]
        missing_id = str(uuid.uuid4())
        for suffix in ("", "history/"):
            foreign = other.get(f"{COLLECTION}{detail['id']}/{suffix}")
            missing = other.get(f"{COLLECTION}{missing_id}/{suffix}")
            self.assertEqual(foreign.status_code, 404)
            self.assertEqual(foreign.json(), missing.json())
        for suffix, command in (
                ("proposals/", {**self.command(), "expected_revision": detail["revision"]}),
                ("approvals/", self.approval_command(detail))):
            foreign = self.post(f"{COLLECTION}{detail['id']}/{suffix}", command, client=other, token=token)
            missing = self.post(f"{COLLECTION}{missing_id}/{suffix}", command, client=other, token=token)
            self.assertEqual(foreign.status_code, 404)
            self.assertEqual(foreign.json(), missing.json())
        self.assertFalse(ApprovalRecord.objects.exists())

    def test_approval_requires_exact_displayed_digests_and_latest_revision(self):
        detail = self.create()["thesis"]
        path = f"{COLLECTION}{detail['id']}/approvals/"
        for change in ({"text_digest": "0" * 64}, {"interpretation_digest": "0" * 64}, {"expected_revision": detail["revision"] + 1}):
            response = self.post(path, {**self.approval_command(detail), **change})
            self.assertEqual(response.status_code, 409, response.content)
        self.assertFalse(ApprovalRecord.objects.exists())
        _, result = self.approve(detail)
        self.assertEqual(result["thesis"]["approved"]["text_version"], detail["draft"]["text_version"])
        self.assertEqual(result["thesis"]["approved"]["interpretation"], detail["draft"]["interpretation"])

    def test_proposals_preserve_approved_state_and_immutable_history(self):
        first = self.create()["thesis"]
        _, approved = self.approve(first)
        _, proposed = self.proposal(approved["thesis"])
        self.assertEqual(proposed["thesis"]["approved"], approved["thesis"]["approved"])
        _, second = self.approve(proposed["thesis"])
        history = self.client.get(f"{COLLECTION}{first['id']}/history/").json()
        self.assertEqual(len(history["text_versions"]), 2)
        self.assertEqual(len(history["interpretations"]), 2)
        self.assertEqual(len(history["approvals"]), 2)
        self.assertEqual(history["text_versions"][0], first["draft"]["text_version"])
        self.assertEqual(history["thesis"], second["thesis"])
        self.assertEqual(history["history_limit"], 100)
        self.assertEqual(history["truncated"], False)
        self.assertEqual(history["replay_scope"], "approval_effective_time_history")

    def test_history_truncation_is_visible_and_preserves_current_detail(self):
        first = self.create()["thesis"]
        _, second = self.proposal(first, "Second version.")
        _, third = self.proposal(second["thesis"], "Third version.")
        with patch("macro_agent.theses.service.HISTORY_LIMIT", 2):
            response = self.client.get(f"{COLLECTION}{first['id']}/history/")
        self.assertEqual(response.status_code, 200)
        history = response.json()
        self.assertEqual(history["history_limit"], 2)
        self.assertEqual(history["truncated"], True)
        self.assertEqual(history["thesis"], third["thesis"])
        for name in ("text_versions", "interpretations", "audit"):
            self.assertEqual(len(history[name]), 2)
        self.assertEqual(history["text_versions"][0], first["draft"]["text_version"])
        self.assertEqual(history["text_versions"][1], second["thesis"]["draft"]["text_version"])

    def test_retry_preserves_saved_result_and_reports_current_disposition(self):
        create = self.command()
        first = self.create(create)
        again = self.create(create)
        self.assertEqual(first["command"]["result"], again["command"]["result"])
        self.assertEqual(again["command"]["replayed"], True)
        approval, approved = self.approve(first["thesis"])
        _, proposed = self.proposal(approved["thesis"])
        _, latest = self.approve(proposed["thesis"])
        response = self.post(f"{COLLECTION}{first['thesis']['id']}/approvals/", approval)
        self.assertEqual(response.status_code, 200, response.content)
        retry = response.json()
        self.assertEqual(retry["command"]["result"], approved["command"]["result"])
        self.assertEqual(retry["command"]["replayed"], True)
        self.assertEqual(retry["command"]["is_current_approval"], False)
        self.assertEqual(retry["thesis"], latest["thesis"])
        self.assertEqual(CommandReceipt.objects.count(), 4)
        self.assertEqual(ApprovalRecord.objects.count(), 2)
        self.assertEqual(TextVersionRecord.objects.count(), 2)

    def test_reusing_command_identity_with_changed_payload_conflicts(self):
        command = self.command()
        self.create(command)
        response = self.post(COLLECTION, {**command, "text": "Changed exact text."})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ThesisRecord.objects.count(), 1)

    def test_authenticated_schema_covers_explicit_thesis_contracts(self):
        response = self.client.get("/api/v1/schema/")
        self.assertEqual(response.status_code, 200, response.content)
        schema = response.json()
        validate_schema(schema)
        self.assertTrue({
            COLLECTION, COLLECTION + "{thesis_id}/",
            COLLECTION + "{thesis_id}/proposals/",
            COLLECTION + "{thesis_id}/approvals/",
            COLLECTION + "{thesis_id}/history/",
        }.issubset(schema["paths"]))
        self.assertNotIn(SESSION, schema["paths"])
        for name in ("CreateThesisRequest", "ProposeThesisRequest", "ApproveThesisRequest", "InterpretationInputRequest"):
            self.assertEqual(schema["components"]["schemas"][name]["additionalProperties"], False)
        approval_fields = schema["components"]["schemas"]["ApproveThesisRequest"]["properties"]
        for name in ("text_digest", "interpretation_digest"):
            self.assertEqual(approval_fields[name]["pattern"], "^[0-9a-f]{64}$")
            self.assertEqual(approval_fields[name]["minLength"], 64)
            self.assertEqual(approval_fields[name]["maxLength"], 64)
        create = schema["paths"][COLLECTION]["post"]
        self.assertEqual(create["security"], [{"cookieAuth": []}])
        self.assertEqual(set(create["requestBody"]["content"]), {"application/json"})
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.get("/api/v1/schema/?version=unreviewed").status_code, 400)

    def test_generic_crud_and_history_writes_are_not_exposed(self):
        detail = self.create()["thesis"]
        path = f"{COLLECTION}{detail['id']}/"
        for method in (self.client.patch, self.client.delete, self.client.put):
            response = method(path, "{}", content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
            self.assertEqual(response.status_code, 405)
        self.assertEqual(self.post(path + "history/", {}).status_code, 405)
        self.assertEqual(ThesisRecord.objects.count(), 1)
