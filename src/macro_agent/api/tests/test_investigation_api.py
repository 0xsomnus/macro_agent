"""Exact, private question-led research over session/CSRF HTTP contracts."""

import io
import json
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone
from drf_spectacular.validation import validate_schema

from macro_agent.api.investigation_serializers import ResearchRunResponseSerializer
from macro_agent.desk import investigation
from macro_agent.desk.investigation_models import ResearchRun
from macro_agent.domain.compilation import SECTIONS
from macro_agent.monitoring import capture, gdelt_research
from macro_agent.monitoring.models import SourceRevision, SourceState
from macro_agent.monitoring.sources import SourceBatch, SourceItem
from macro_agent.persistence.models import CurrentAssessment, NotificationIntent
from macro_agent.positions.models import PositionRecord
from macro_agent.providers import ProviderError
from macro_agent.scheduling.models import WatchRecord
from macro_agent.theses import compilation
from macro_agent.theses.models import CompilationBudget


MODEL = "Qwen/Qwen3-4B"
EXACT = "  Could fictional helium supply disruption create a useful exposure idea?\r\nΔ"


class RecordedResearchProvider:
    """One recorded plan and one proposal, never current helium market facts."""

    def __init__(self):
        self.calls = 0
        self.catalog_calls = 0
        self.error = None

    def list_models(self):
        self.catalog_calls += 1
        return {"fetched_at": timezone.now().isoformat(), "models": [{"id": MODEL,
            "name": "Recorded research model", "context_length": 65536,
            "input_price_usd_per_million": None, "output_price_usd_per_million": None,
            "capabilities": {"tools": False, "chat_completions": True}}]}

    def complete(self, model_id, messages):
        self.calls += 1
        if self.error:
            raise ProviderError(self.error)
        supplied = json.loads(messages[1]["content"])
        if "exact_question" in supplied:
            document = {"schema_version": "research-plan-v1", "questions": [{"question_id": "supply",
                "question": "Could fictional supply disruption reach business cash flows?",
                "why_material": "An exposure idea depends on who bears higher input costs.",
                "evidence_to_seek": "A relevant supply observation and business exposure.",
                "counter_evidence_to_seek": "Substitutes, cost pass-through or offsetting supply.",
                "query": "fictional helium supply substitutes"}]}
        else:
            report = supplied["evidence"]["reports"][0]
            document = {"interpretation": {"drivers": [], "horizon": None, "invalidation_signposts": []},
                "grounding": [], "refinement_issues": [], "agent_hypotheses": [], "counter_case": None,
                "review_card": {section: {"extracted": [], "proposed": [],
                    "gap": "This recorded metadata does not settle the research question."} for section in SECTIONS},
                "attributed_claims": [{"claim_id": "headline", "revision_id": report["revision_id"],
                    "field": "title", "exact_quote": report["title"]}], "factual_conflicts": [],
                "evidence_assessment": {"summary": "A fictional headline motivates a qualified investigation.",
                    "supporting_claim_ids": ["headline"], "counter_claim_ids": [],
                    "gaps": ["No article body, verified prices or business cash-flow data."]},
                "proposed_drivers": [{"driver_id": "input-cost", "explanation": "Higher input costs may affect margins.",
                    "transmission": "A supply disruption could increase input costs if substitutes are unavailable.",
                    "supporting_claim_ids": ["headline"], "counter_claim_ids": [],
                    "assumptions": ["Costs cannot immediately be passed through."],
                    "uncertainty": "The headline does not establish the firm's actual cost exposure.",
                    "why_material": "An importer may lose rather than benefit from higher gas prices."}],
                "exposure_candidates": [{"candidate_id": "gas-business", "asset": "Fictional industrial gas business",
                    "expression": "Potential related-equity exposure, instrument availability unverified.",
                    "relationship": "Possible input-cost exposure, not direct commodity ownership.",
                    "claim_ids": ["headline"], "basis_risks": ["Business margins may diverge from gas prices."],
                    "verification_questions": ["What proportion of costs can be hedged or passed through?"],
                    "uncertainty": "No company financials or broker contract was supplied.",
                    "availability": "unverified"}]}
        return {"content": json.dumps(document), "usage": {"prompt_tokens": 10,
            "completion_tokens": 20, "total_tokens": 30}, "reported_cost_usd": None,
            "reported_model": MODEL, "provider_request_id": f"recorded-{self.calls}",
            "latency_ms": 1, "finish_reason": "stop"}


def recorded_discovery(query, *, clock):
    stamp = clock()
    body = json.dumps({"articles": [{"url": "https://example.invalid/fictional-helium",
        "url_mobile": "", "title": "FICTIONAL helium importer reports higher input costs",
        "seendate": stamp.strftime("%Y%m%dT%H%M%SZ"), "socialimage": "",
        "domain": "example.invalid", "language": "English", "sourcecountry": "Uganda"}]}).encode()
    return gdelt_research.parse_metadata(body, query=query, received_at=stamp)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    SETTINGS_MODULE="macro_agent.web.local_settings", MACRO_ENABLE_RESEARCH_DISCOVERY=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ENABLE_NEWS_ANALYSIS=True, MACRO_ALLOW_SYNTHETIC_SETUP=False,
    MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="recorded-internal-key")
class InvestigationAPITests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("Research API authority tests require PostgreSQL")
        CompilationBudget.objects.get_or_create(pk=1)
        self.owner = get_user_model().objects.create_user(username="research-owner", password="recorded")
        self.other = get_user_model().objects.create_user(username="research-other", is_staff=True, is_superuser=True)
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)
        self.token = self.client.get("/api/v1/session/").json()["csrf_token"]
        self.provider = RecordedResearchProvider()
        self.discovery_calls = 0
        for module in (investigation, compilation):
            mocked = patch.object(module, "create_provider", return_value=self.provider)
            mocked.start()
            self.addCleanup(mocked.stop)
        mocked = patch.object(gdelt_research, "discover", side_effect=self.discovery)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.path = "/api/v1/research/"

    def discovery(self, query, *, clock):
        self.discovery_calls += 1
        return recorded_discovery(query, clock=clock)

    def body(self, **changes):
        return {"command_id": str(uuid4()), "exact_question": EXACT,
            "provider_id": "nanogpt", "model_id": MODEL, **changes}

    def post(self, body=None, *, path=None, client=None, token=None):
        return (client or self.client).post(path or self.path,
            json.dumps(self.body() if body is None else body), content_type="application/json",
            HTTP_X_CSRFTOKEN=token or self.token)

    def completed(self, body=None):
        response = self.post(body)
        self.assertEqual(response.status_code, 200, response.content)
        value = response.json()
        self.assertEqual(value["research"]["status"], "compiled", value)
        serializer = ResearchRunResponseSerializer(data=value)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return value

    def test_rough_unfamiliar_asset_question_reaches_sourced_proposals_without_monitoring(self):
        value = self.completed()
        research = value["research"]
        self.assertEqual(research["exact_question"], EXACT)
        self.assertEqual(research["compilation"]["thesis"]["draft"]["text_version"]["exact_text"], EXACT)
        document = research["compilation"]["compilation"]["document"]
        self.assertEqual(document["interpretation"]["drivers"], [])
        self.assertEqual(document["proposed_drivers"][0]["supporting_claim_ids"], ["headline"])
        self.assertEqual(document["exposure_candidates"][0]["availability"], "unverified")
        self.assertEqual(research["authority"], {"monitoring_started": False,
            "thesis_approved": False, "positions_created": False})
        self.assertFalse(WatchRecord.objects.exists())
        self.assertFalse(PositionRecord.objects.exists())
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())
        self.assertIsNone(research["costs"]["total_known_cost_usd"])
        self.assertEqual((self.provider.calls, self.discovery_calls), (2, 1))
        self.assertNotIn("recorded-internal-key", json.dumps(value))

    def test_saved_post_retry_get_and_continue_are_keyless_reads_without_respending(self):
        body = self.body()
        value = self.completed(body)
        run_id = value["research"]["id"]
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                SETTINGS_MODULE="macro_agent.web.local_settings"):
            retry = self.post(body)
            detail = self.client.get(f"/api/v1/research/{run_id}/")
            command = self.client.get(f"/api/v1/research-commands/{body['command_id']}/")
            continued = self.post({}, path=f"/api/v1/research/{run_id}/continue/")
        for label, response in (("retry", retry), ("detail", detail), ("command", command), ("continue", continued)):
            self.assertEqual(response.status_code, 200, (label, response.content))
            actual, expected = deepcopy(response.json()["research"]), deepcopy(value["research"])
            # Current permission/source disposition is observed afresh on a
            # read, while immutable attempts, quotations and proposals persist.
            for research in (actual, expected):
                research["compilation"]["compilation"]["evidence_disposition"].pop("observed_at")
            self.assertEqual(actual, expected, label)
        self.assertTrue(retry.json()["replayed"])
        self.assertEqual((self.provider.calls, self.provider.catalog_calls, self.discovery_calls), (2, 2, 1))

    def test_session_authentication_and_csrf_precede_research_side_effects(self):
        anonymous = Client(enforce_csrf_checks=True)
        self.assertEqual(self.post(client=anonymous).status_code, 403)
        response = self.client.post(self.path, json.dumps(self.body()), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ResearchRun.objects.exists())
        self.assertEqual((self.provider.calls, self.discovery_calls), (0, 0))

    def test_staff_cannot_read_or_continue_another_owners_research(self):
        body = self.body()
        value = self.completed(body)
        run_id = value["research"]["id"]
        other = Client(enforce_csrf_checks=True)
        other.force_login(self.other)
        token = other.get("/api/v1/session/").json()["csrf_token"]
        for path in (f"/api/v1/research/{run_id}/", f"/api/v1/research-commands/{body['command_id']}/"):
            self.assertEqual(other.get(path).status_code, 404)
        self.assertEqual(self.post({}, path=f"/api/v1/research/{run_id}/continue/", client=other, token=token).status_code, 404)
        self.assertEqual((self.provider.calls, self.discovery_calls), (2, 1))

    def test_duplicate_unknown_and_coerced_inputs_are_rejected_before_admission(self):
        for body in (self.body(exact_question=123), self.body(exact_question=True),
                     self.body(command_id=123), self.body(model_id=123),
                     self.body(api_key="not-accepted"), self.body(approved=True), self.body(exact_question=" ")):
            with self.subTest(body=body):
                self.assertEqual(self.post(body).status_code, 400)
        raw_body = json.dumps(self.body())[:-1] + ',"exact_question":"replacement"}'
        duplicate = self.client.post(self.path, raw_body, content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(duplicate.status_code, 400)
        self.assertFalse(ResearchRun.objects.exists())
        self.assertEqual((self.provider.calls, self.discovery_calls), (0, 0))

    def test_changed_request_cannot_reuse_an_admitted_command(self):
        body = self.body()
        self.completed(body)
        response = self.post(dict(body, exact_question=EXACT + "changed"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ResearchRun.objects.count(), 1)
        self.assertEqual((self.provider.calls, self.discovery_calls), (2, 1))

    def test_uncertain_plan_remains_visible_and_is_never_automatically_retried(self):
        self.provider.error = "timeout"
        response = self.post()
        self.assertEqual(response.status_code, 200, response.content)
        research = response.json()["research"]
        self.assertEqual(research["status"], "plan_uncertain")
        self.assertEqual(research["plan"]["status"], "outcome_unknown")
        continued = self.post({}, path=f"/api/v1/research/{research['id']}/continue/")
        self.assertEqual(continued.status_code, 200)
        self.assertEqual(continued.json()["research"]["status"], "plan_uncertain")
        self.assertEqual((self.provider.calls, self.discovery_calls), (1, 0))

    def test_changed_source_stales_research_without_rewriting_original_proposal(self):
        value = self.completed()
        research = value["research"]
        source = SourceState.objects.get(pk=research["discoveries"][0]["source_id"])
        revision = SourceRevision.objects.get(pk=research["discoveries"][0]["revision_ids"][0])
        payload = revision.payload

        def loader():
            return SourceBatch((SourceItem(payload["id"], "FICTIONAL corrected cost report", payload["url"],
                None, payload["content"]),), timezone.now(), "bounded_snapshot", False, "a" * 64)

        capture.capture(source.pk, source.contract, loader)
        response = self.client.get(f"/api/v1/research/{research['id']}/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["research"]["status"], "stale")
        self.assertEqual(response.json()["research"]["compilation"]["compilation"]["document"],
            research["compilation"]["compilation"]["document"])
        self.assertEqual((self.provider.calls, self.discovery_calls), (2, 1))

    def test_serialized_representation_retains_discovery_trace_and_research_proposals(self):
        value = self.completed()
        represented = ResearchRunResponseSerializer(value).data
        self.assertEqual(represented["research"]["discoveries"][0]["metadata"]["candidates"][0]["metadata"]["title"],
            value["research"]["discoveries"][0]["metadata"]["candidates"][0]["metadata"]["title"])
        for field in ("proposed_drivers", "exposure_candidates", "attributed_claims"):
            self.assertEqual(represented["research"]["compilation"]["compilation"]["document"][field],
                value["research"]["compilation"]["compilation"]["document"][field])
        self.assertEqual(represented["research"]["exact_question"], EXACT)

    def test_disabled_routes_and_unknown_query_or_continuation_fields_do_not_execute(self):
        with override_settings(MACRO_ENABLE_RESEARCH_DISCOVERY=False):
            self.assertEqual(self.post().status_code, 404)
        value = self.completed()
        run_id = value["research"]["id"]
        self.assertEqual(self.client.get(f"/api/v1/research/{run_id}/?refresh=1").status_code, 400)
        self.assertEqual(self.post({"retry": True}, path=f"/api/v1/research/{run_id}/continue/").status_code, 400)
        self.assertEqual((self.provider.calls, self.discovery_calls), (2, 1))

    def test_capture_gate_is_checked_before_any_planning_charge(self):
        with override_settings(MACRO_ENABLE_MONITORING_PROOF=False,
                SETTINGS_MODULE="macro_agent.web.local_settings"):
            response = self.post()
        self.assertEqual(response.status_code, 404, response.content)
        self.assertFalse(ResearchRun.objects.exists())
        self.assertEqual((self.provider.calls, self.discovery_calls), (0, 0))

    def test_generated_openapi_contains_explicit_research_and_discovery_shapes(self):
        output = io.StringIO()
        call_command("spectacular", format="openapi-json", stdout=output)
        schema = json.loads(output.getvalue())
        validate_schema(schema)
        for path in ("/api/v1/research/", "/api/v1/research/{run_id}/",
                     "/api/v1/research/{run_id}/continue/", "/api/v1/research-commands/{command_id}/"):
            self.assertIn(path, schema["paths"])
        properties = schema["components"]["schemas"]["ResearchSelection"]["properties"]
        self.assertIn("candidates", properties)
        self.assertIn("candidate_cap_reached", properties)
        self.assertEqual((self.provider.calls, self.discovery_calls), (0, 0))


if __name__ == "__main__":
    raise SystemExit("Run through Django's PostgreSQL test runner.")
