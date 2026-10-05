"""PostgreSQL-backed session, authority, and paper-position wire regressions."""

import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from drf_spectacular.validation import validate_schema


THESIS_COLLECTION = "/api/v1/theses/"
POSITION_COLLECTION = "/api/v1/positions/"
SESSION = "/api/v1/session/"


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PositionAPITests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("Paper-position HTTP authority evidence requires PostgreSQL")
        self.owner = get_user_model().objects.create_user(username="position-api-owner")
        self.other = get_user_model().objects.create_user(username="position-api-other")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)
        self.token = self.client.get(SESSION).json()["csrf_token"]
        self.thesis = self.create_thesis()
        self.approved = self.approve_thesis(self.thesis)
        self.collection = f"{THESIS_COLLECTION}{self.thesis['id']}/positions/"

    def post(self, path, body, *, client=None, token=None):
        return (client or self.client).post(
            path, json.dumps(body, ensure_ascii=True), content_type="application/json",
            HTTP_X_CSRFTOKEN=token or self.token,
        )

    def thesis_command(self):
        return {
            "command_id": str(uuid.uuid4()), "text": "Gold may benefit if real yields decline.",
            "interpretation": {
                "drivers": ["real yields"], "horizon": None,
                "invalidation_signposts": ["real yields rise"],
            },
        }

    def create_thesis(self):
        response = self.post(THESIS_COLLECTION, self.thesis_command())
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["thesis"]

    def approve_thesis(self, detail):
        draft = detail["draft"]
        response = self.post(f"{THESIS_COLLECTION}{detail['id']}/approvals/", {
            "command_id": str(uuid.uuid4()), "expected_revision": detail["revision"],
            "thesis_version_id": draft["text_version"]["id"],
            "text_digest": draft["text_version"]["text_digest"],
            "interpretation_version_id": draft["interpretation"]["id"],
            "interpretation_digest": draft["interpretation"]["digest"],
        })
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["thesis"]

    def new_thesis_approval(self):
        current = self.client.get(f"{THESIS_COLLECTION}{self.thesis['id']}/").json()
        response = self.post(f"{THESIS_COLLECTION}{self.thesis['id']}/proposals/", {
            **self.thesis_command(), "expected_revision": current["revision"],
        })
        self.assertEqual(response.status_code, 201, response.content)
        return self.approve_thesis(response.json()["thesis"])

    def declaration(self, **changes):
        return {
            "underlying": "XAU", "direction": "long", "product_id": None,
            "venue": None, "expiry": None, "quote_currency": None, "horizon": None,
            "quantity": None, "quantity_unit": None, **changes,
        }

    def create_command(self, declaration=None):
        return {
            "command_id": str(uuid.uuid4()),
            "expected_approval_id": self.approved["approved"]["approval"]["id"],
            "position": declaration or self.declaration(),
        }

    def create(self, command=None):
        response = self.post(self.collection, command or self.create_command())
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def guards(self, position):
        return {
            "command_id": str(uuid.uuid4()), "expected_revision": position["revision"],
            "expected_approval_id": self.approved["approved"]["approval"]["id"],
        }

    def revise(self, position, declaration=None, command=None):
        command = command or {**self.guards(position), "position": declaration or self.declaration(direction="short")}
        response = self.post(f"{POSITION_COLLECTION}{position['id']}/revisions/", command)
        self.assertEqual(response.status_code, 201, response.content)
        return command, response.json()

    def close(self, position, command=None):
        command = command or self.guards(position)
        response = self.post(f"{POSITION_COLLECTION}{position['id']}/close/", command)
        self.assertEqual(response.status_code, 200, response.content)
        return command, response.json()

    def history(self, position):
        response = self.client.get(f"{POSITION_COLLECTION}{position['id']}/history/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_anonymous_position_reads_and_commands_are_denied(self):
        position = self.create()["position"]
        client = Client(enforce_csrf_checks=True)
        for path in (self.collection, f"{POSITION_COLLECTION}{position['id']}/",
                     f"{POSITION_COLLECTION}{position['id']}/history/"):
            self.assertEqual(client.get(path).status_code, 403)
        self.assertEqual(self.post(self.collection, self.create_command(), client=client).status_code, 403)
        self.assertEqual(len(self.history(position)["versions"]), 1)

    def test_all_position_writes_require_csrf(self):
        position = self.create()["position"]
        commands = (
            (self.collection, self.create_command()),
            (f"{POSITION_COLLECTION}{position['id']}/revisions/",
             {**self.guards(position), "position": self.declaration(direction="short")}),
            (f"{POSITION_COLLECTION}{position['id']}/close/", self.guards(position)),
        )
        for path, command in commands:
            for headers in ({}, {"HTTP_X_CSRFTOKEN": "0" * 64}):
                response = self.client.post(path, json.dumps(command), content_type="application/json", **headers)
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self.history(position)["position"], position)
        self.assertEqual(len(self.history(position)["versions"]), 1)

    def test_incomplete_mapping_remains_explicit_without_invented_size_or_coverage(self):
        declaration = self.declaration(underlying="  XAU global context\n")
        result = self.create(self.create_command(declaration))
        position, version = result["position"], result["position"]["current_version"]
        self.assertEqual(position["original_approval_id"], self.approved["approved"]["approval"]["id"])
        for name, value in declaration.items():
            self.assertEqual(version[name], value)
        self.assertEqual(version["paper"], True)
        self.assertEqual(version["status"], "open")
        self.assertEqual(version["mapping_status"], "user_declared_unverified")
        self.assertEqual(position["mapping_status"], "user_declared_unverified")
        self.assertEqual(position["monitoring"], "not_configured")
        for name in ("product_id", "venue", "quantity", "quantity_unit", "horizon"):
            self.assertIn(name, version["missing_fields"])
        self.assertNotIn("owner_id", position)

    def test_quantity_is_an_exact_user_declaration_and_expiry_is_not_coerced(self):
        declaration = self.declaration(
            product_id="  MY-GOLD-CONTRACT  ", venue="fictional venue", expiry="2028-02-29",
            quote_currency="USD", horizon="  several weeks  ", quantity="1.2500", quantity_unit="contracts",
        )
        position = self.create(self.create_command(declaration))["position"]
        for name, value in declaration.items():
            self.assertEqual(position["current_version"][name], value)
        self.assertEqual(self.client.get(f"{POSITION_COLLECTION}{position['id']}/").json(), position)

    def test_declaration_keys_are_required_even_when_their_values_can_be_null(self):
        base = self.create_command()
        for name in base["position"]:
            command = {**base, "position": {key: value for key, value in base["position"].items() if key != name}}
            self.assertEqual(self.post(self.collection, command).status_code, 400, name)
        for name in ("underlying", "direction"):
            self.assertEqual(self.post(self.collection, {**base, "position": self.declaration(**{name: None})}).status_code, 400)
        self.assertEqual(self.client.get(self.collection).json()["positions"], [])

    def test_server_authority_fixed_state_and_coercion_are_rejected(self):
        base = self.create_command()
        invalid = [
            {**base, "owner_id": str(self.owner.pk)}, {**base, "actor_id": str(self.owner.pk)},
            {**base, "accepted_at": "2026-10-05T00:00:00Z"}, {**base, "expected_approval_id": True},
            {**base, "command_id": "ABCDEF00-1234-1234-1234-123456789abc"},
        ]
        for field, value in (("paper", False), ("status", "closed"), ("mapping_status", "verified"),
                             ("reviewed_approval_id", base["expected_approval_id"]), ("underlying", 7),
                             ("direction", True), ("quantity", 1.25), ("quantity", 1),
                             ("expiry", 20261005), ("horizon", False), ("venue", [])):
            invalid.append({**base, "position": {**base["position"], field: value}})
        for command in invalid:
            self.assertEqual(self.post(self.collection, command).status_code, 400)
        self.assertEqual(self.client.get(self.collection).json()["positions"], [])

    def test_quantity_rejects_ambiguous_out_of_range_and_unpaired_values(self):
        for value in ("01", "1e3", "+1", "-1", "0", "0.000", "1.", " 1", "1\n",
                      "1.1234567890123", "9" * 29, "NaN", "Infinity"):
            response = self.post(self.collection, self.create_command(self.declaration(quantity=value, quantity_unit="contracts")))
            self.assertEqual(response.status_code, 400, value)
        for declaration in (self.declaration(quantity="1"), self.declaration(quantity_unit="contracts")):
            self.assertEqual(self.post(self.collection, self.create_command(declaration)).status_code, 400)
        self.assertEqual(self.client.get(self.collection).json()["positions"], [])

    def test_expiry_requires_valid_exact_gregorian_date(self):
        for value in ("2026-02-29", "2026-13-01", "20261005", "2026-W41-1", "2026-10-05Z", "0000-01-01"):
            self.assertEqual(self.post(self.collection, self.create_command(self.declaration(expiry=value))).status_code, 400, value)
        self.assertEqual(self.client.get(self.collection).json()["positions"], [])

    def test_declaration_field_limits_and_direction_are_enforced(self):
        for field, limit in (("underlying", 128), ("product_id", 256), ("venue", 128),
                             ("quote_currency", 16), ("quantity_unit", 64), ("horizon", 1000)):
            declaration = self.declaration(**{field: "x" * (limit + 1)})
            if field == "quantity_unit":
                declaration["quantity"] = "1"
            self.assertEqual(self.post(self.collection, self.create_command(declaration)).status_code, 400, field)
        for direction in ("LONG", "buy", "", " long "):
            self.assertEqual(self.post(self.collection, self.create_command(self.declaration(direction=direction))).status_code, 400)

    def test_position_parser_rejects_duplicate_invalid_and_oversized_json(self):
        bodies = (
            '{"position":{"underlying":"XAU","underlying":"ES"}}',
            '{"position":{"underlying":"\\ud800"}}', '{"position":{"underlying":"\\u0000"}}',
            '{"position":{"quantity":1e999}}', '{"position":"' + "x" * (128 * 1024) + '"}',
        )
        for body in bodies:
            response = self.client.post(self.collection, body, content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(self.collection).json()["positions"], [])

    def test_foreign_and_missing_position_resources_are_indistinguishable(self):
        position = self.create()["position"]
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.other)
        token = client.get(SESSION).json()["csrf_token"]
        missing = str(uuid.uuid4())
        for suffix in ("", "history/"):
            foreign = client.get(f"{POSITION_COLLECTION}{position['id']}/{suffix}")
            absent = client.get(f"{POSITION_COLLECTION}{missing}/{suffix}")
            self.assertEqual(foreign.status_code, 404)
            self.assertEqual(foreign.json(), absent.json())
        foreign = client.get(self.collection)
        absent = client.get(f"{THESIS_COLLECTION}{missing}/positions/")
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json(), absent.json())
        for suffix, command in (("revisions/", {**self.guards(position), "position": self.declaration()}),
                                ("close/", self.guards(position))):
            foreign = self.post(f"{POSITION_COLLECTION}{position['id']}/{suffix}", command, client=client, token=token)
            absent = self.post(f"{POSITION_COLLECTION}{missing}/{suffix}", command, client=client, token=token)
            self.assertEqual(foreign.status_code, 404)
            self.assertEqual(foreign.json(), absent.json())
        foreign = self.post(self.collection, self.create_command(), client=client, token=token)
        absent = self.post(f"{THESIS_COLLECTION}{missing}/positions/", self.create_command(), client=client, token=token)
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json(), absent.json())
        self.assertEqual(self.history(position)["position"], position)

    def test_create_requires_current_explicit_approval(self):
        unapproved = self.create_thesis()
        response = self.post(f"{THESIS_COLLECTION}{unapproved['id']}/positions/", self.create_command())
        self.assertEqual(response.status_code, 409)
        self.new_thesis_approval()
        self.assertEqual(self.post(self.collection, self.create_command()).status_code, 409)
        self.assertEqual(self.client.get(self.collection).json()["positions"], [])

    def test_unapproved_thesis_proposal_preserves_attachment_authority_and_exact_approved_text(self):
        response = self.post(f"{THESIS_COLLECTION}{self.thesis['id']}/proposals/", {
            **self.thesis_command(), "text": "A proposed but unapproved replacement.",
            "expected_revision": self.approved["revision"],
        })
        self.assertEqual(response.status_code, 201, response.content)
        proposed = response.json()["thesis"]
        self.assertEqual(proposed["approved"], self.approved["approved"])
        position = self.create()["position"]
        _, revised = self.revise(position)
        self.close(revised["position"])
        self.assertEqual(self.client.get(f"{THESIS_COLLECTION}{self.thesis['id']}/").json(), proposed)

    def test_current_approval_is_reviewed_without_rewriting_existing_attachment(self):
        position = self.create()["position"]
        stale = {**self.guards(position), "position": self.declaration(direction="short")}
        self.approved = self.new_thesis_approval()
        self.assertEqual(self.post(f"{POSITION_COLLECTION}{position['id']}/revisions/", stale).status_code, 409)
        self.assertEqual(self.post(f"{POSITION_COLLECTION}{position['id']}/close/", {key: value for key, value in stale.items() if key != "position"}).status_code, 409)
        _, revised = self.revise(position)
        self.assertEqual(revised["position"]["original_approval_id"], position["original_approval_id"])
        self.assertEqual(revised["position"]["current_version"]["reviewed_approval_id"], self.approved["approved"]["approval"]["id"])

    def test_revision_guards_are_strict_and_stale_writes_leave_history_unchanged(self):
        position = self.create()["position"]
        path = f"{POSITION_COLLECTION}{position['id']}/revisions/"
        base = {**self.guards(position), "position": self.declaration(direction="short")}
        for revision in (True, "1", 1.0, 0):
            self.assertEqual(self.post(path, {**base, "expected_revision": revision}).status_code, 400)
        _, revised = self.revise(position)
        self.assertEqual(self.post(path, base).status_code, 409)
        self.assertEqual(self.post(f"{POSITION_COLLECTION}{position['id']}/close/", self.guards(position)).status_code, 409)
        history = self.history(position)
        self.assertEqual(history["position"], revised["position"])
        self.assertEqual(len(history["versions"]), 2)

    def test_revision_close_and_history_preserve_every_exact_declaration(self):
        first = self.create()["position"]
        _, revised = self.revise(first, self.declaration(direction="short", quantity="0.5000", quantity_unit="contracts"))
        _, closed = self.close(revised["position"])
        history = self.history(first)
        self.assertEqual(history["versions"][0], first["current_version"])
        self.assertEqual(history["versions"][1], revised["position"]["current_version"])
        self.assertEqual(history["versions"][2], closed["position"]["current_version"])
        self.assertEqual(history["versions"][2]["status"], "closed")
        self.assertEqual(history["versions"][2]["quantity"], "0.5000")
        self.assertEqual(history["position"], closed["position"])
        self.assertEqual(history["replay_scope"], "position_effective_time_history")
        self.assertEqual(history["history_limit"], 100)
        self.assertEqual(history["truncated"], False)
        self.assertEqual([item["kind"] for item in history["audit"]], ["create", "revise", "close"])

    def test_closed_position_cannot_be_reopened_or_reclosed_as_new_command(self):
        position = self.create()["position"]
        _, closed = self.close(position)
        current = closed["position"]
        self.assertEqual(self.post(f"{POSITION_COLLECTION}{position['id']}/revisions/", {
            **self.guards(current), "position": self.declaration(),
        }).status_code, 409)
        self.assertEqual(self.post(f"{POSITION_COLLECTION}{position['id']}/close/", self.guards(current)).status_code, 409)
        self.assertEqual(len(self.history(position)["versions"]), 2)

    def test_historical_retries_return_original_results_and_current_disposition(self):
        create = self.create_command()
        first = self.create(create)
        revise, revised = self.revise(first["position"])
        close, closed = self.close(revised["position"])
        self.approved = self.new_thesis_approval()
        for path, command, original, current in (
            (self.collection, create, first, False),
            (f"{POSITION_COLLECTION}{first['position']['id']}/revisions/", revise, revised, False),
            (f"{POSITION_COLLECTION}{first['position']['id']}/close/", close, closed, True),
        ):
            response = self.post(path, command)
            self.assertIn(response.status_code, (200, 201), response.content)
            result = response.json()
            self.assertEqual(result["command"]["result"], original["command"]["result"])
            self.assertEqual(result["command"]["replayed"], True)
            self.assertEqual(result["command"]["is_current_version"], current)
            self.assertEqual(result["position"], closed["position"])
        self.assertEqual(len(self.history(first["position"])["versions"]), 3)

    def test_reused_command_id_with_changed_declaration_conflicts(self):
        command = self.create_command()
        first = self.create(command)
        changed = {**command, "position": self.declaration(direction="short")}
        self.assertEqual(self.post(self.collection, changed).status_code, 409)
        self.assertEqual(self.history(first["position"])["position"], first["position"])
        self.assertEqual(len(self.client.get(self.collection).json()["positions"]), 1)

    def test_history_truncation_is_visible_and_current_version_is_preserved(self):
        first = self.create()["position"]
        _, second = self.revise(first)
        _, third = self.revise(second["position"], self.declaration(direction="long"))
        with patch("macro_agent.positions.service.HISTORY_LIMIT", 2):
            history = self.history(first)
        self.assertEqual(history["position"], third["position"])
        self.assertEqual(history["history_limit"], 2)
        self.assertEqual(history["truncated"], True)
        self.assertEqual(history["versions"], [first["current_version"], second["position"]["current_version"]])
        self.assertEqual(len(history["audit"]), 2)

    def test_collection_pagination_and_query_rejection_are_bounded(self):
        first, second = self.create()["position"], self.create()["position"]
        response = self.client.get(self.collection + "?limit=1&offset=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["positions"], [first])
        self.assertEqual(response.json()["has_more"], True)
        self.assertEqual(self.client.get(self.collection + "?limit=1&offset=1").json()["positions"], [second])
        for query in ("owner_id=x", "limit=0", "limit=101", "offset=-1", "offset=1000001", "limit=1&limit=1", "offset=true"):
            self.assertEqual(self.client.get(self.collection + "?" + query).status_code, 400)
        self.assertEqual(self.client.get(f"{POSITION_COLLECTION}{first['id']}/?at=2026-10-05").status_code, 400)
        self.assertEqual(self.client.get(f"{POSITION_COLLECTION}{first['id']}/history/?limit=1").status_code, 400)
        self.assertEqual(self.post(self.collection + "?actor_id=x", self.create_command()).status_code, 400)

    def test_schema_describes_strict_paper_contracts_and_private_session_authority(self):
        response = self.client.get("/api/v1/schema/")
        self.assertEqual(response.status_code, 200, response.content)
        schema = response.json()
        validate_schema(schema)
        declarations = schema["components"]["schemas"]["PositionDeclarationRequest"]
        self.assertEqual(declarations["additionalProperties"], False)
        self.assertEqual(set(declarations["required"]), set(self.declaration()))
        self.assertNotIn("owner_id", declarations["properties"])
        self.assertNotIn("paper", declarations["properties"])
        for name in ("CreatePositionRequest", "RevisePositionRequest", "ClosePositionRequest"):
            self.assertEqual(schema["components"]["schemas"][name]["additionalProperties"], False)
        create = schema["paths"]["/api/v1/theses/{thesis_id}/positions/"]["post"]
        self.assertEqual(create["security"], [{"cookieAuth": []}])
        self.assertEqual(set(create["requestBody"]["content"]), {"application/json"})
        self.assertIn("409", create["responses"])

    def test_generic_crud_and_history_writes_are_not_exposed(self):
        position = self.create()["position"]
        path = f"{POSITION_COLLECTION}{position['id']}/"
        for method in (self.client.put, self.client.patch, self.client.delete):
            response = method(path, "{}", content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
            self.assertEqual(response.status_code, 405)
        self.assertEqual(self.post(path + "history/", {}).status_code, 405)
        self.assertEqual(self.history(position)["position"], position)
