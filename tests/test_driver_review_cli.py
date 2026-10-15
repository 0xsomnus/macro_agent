"""Terminal driver profiles preserve exact receipts and durable paid-call intent."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import desk_cli
import review_morning
import review_news
import test_daily_driver_synthesis as daily
import test_research_cli as research_cli
import test_research_compilation as research
import test_review_news as news
from macro_agent.domain import research_compilation
from macro_agent.domain.daily_synthesis import DRIVER_SCHEMA_VERSION as DAILY_SCHEMA
from macro_agent.domain.driver_review import driver_assessment_example
from macro_agent.domain.models import CompiledThesisVersion, canonical_json, text_digest
from macro_agent.domain.news_analysis import DRIVER_SCHEMA_VERSION as NEWS_SCHEMA


def compilation_receipt():
    thesis_id, text_id, interpretation_id, attempt_id, packet_id, command_id = (
        str(uuid4()) for _ in range(6))
    output = research.result()
    card = research_compilation.build_review_card(output, research.EXACT, research.evidence())
    meaning = output["interpretation"]
    digest = CompiledThesisVersion(interpretation_id, text_id, tuple(meaning["drivers"]),
        meaning["horizon"], tuple(meaning["invalidation_signposts"]), datetime.now(timezone.utc),
        review_card_json=canonical_json(card)).digest
    text = {"id": text_id, "exact_text": research.EXACT, "text_digest": text_digest(research.EXACT)}
    thesis = {"id": thesis_id, "revision": 3, "draft": {"text_version": text,
        "interpretation": {"id": interpretation_id, "origin": "model_compilation", "digest": digest,
            "review_card": card, **meaning}}}
    return {"thesis": thesis, "compilation": {"id": attempt_id, "command_id": command_id,
        "status": "compiled", "provider": "nanogpt", "model_id": "fixture-model",
        "schema_version": research_compilation.SOURCED_SCHEMA_VERSION,
        "input_text_version": text, "interpretation_version_id": interpretation_id,
        "refinement_inputs": [], "is_current_draft": True, "document": output,
        "evidence_context": {"id": packet_id, "content": research.evidence()},
        "evidence_disposition": {"status": "current"}}}


def morning_receipt():
    context = daily.context()
    review_id, command_id = (str(uuid4()) for _ in range(2))
    context["review_id"] = review_id
    return {"synthesis": {"id": str(uuid4()), "command_id": command_id,
        "review_id": review_id, "review_digest": context["review_digest"], "context": context,
        "context_digest": text_digest(canonical_json(context)), "document": daily.document(context),
        "schema_version": DAILY_SCHEMA, "status": "synthesised", "provider": "nanogpt",
        "model_id": "fixture-model"}, "current_disposition": {"status": "current",
            "stale_reasons": [], "publication_authority": False}}


def news_receipt():
    result = news.result()
    result["analysis"]["context"]["driver_review"] = True
    output = result["analysis"]["document"]
    output["schema_version"] = NEWS_SCHEMA
    output["driver_assessment"] = driver_assessment_example(news.MEANING["drivers"])
    return result


class DriverReviewCLITests(unittest.TestCase):
    def test_source_profile_validates_and_renders_the_exact_v3_card(self):
        result = compilation_receipt()
        selection = {"provider_id": "nanogpt", "model_id": "fixture-model"}
        self.assertTrue(desk_cli._checked_current_compilation(result,
            result["thesis"]["id"], research.EXACT, selection))
        displayed = []
        desk_cli.render_compilation(result["compilation"], displayed.append)
        self.assertTrue(any("Proposed drivers" in line for line in displayed))
        self.assertTrue(any("Exploratory exposure candidates" in line for line in displayed))
        self.assertTrue(any("do not start monitoring" in line for line in displayed))
        changed = deepcopy(result)
        changed["thesis"]["draft"]["interpretation"]["review_card"]["document"]["proposed_drivers"] = []
        with self.assertRaisesRegex(desk_cli.WalkthroughError, "review card"):
            desk_cli._checked_current_compilation(changed, result["thesis"]["id"], research.EXACT, selection)

    def test_source_recovery_uses_saved_profile_without_catalogue_or_post(self):
        result = compilation_receipt()
        client = research_cli.Client(result)
        target = {"thesis_id": result["thesis"]["id"], "command_id": result["compilation"]["command_id"],
            "kind": "compilation", "exact_text": research.EXACT}
        displayed = []
        with patch.object(desk_cli, "select_model", side_effect=AssertionError("No catalogue on recovery")):
            recovered = desk_cli.recover_command(client, target, ask=lambda _: "trader",
                secret=lambda _: "private-password", say=displayed.append)
        self.assertEqual(recovered, result)
        self.assertEqual([call[0] for call in client.calls], ["GET"])
        self.assertTrue(any("Proposed drivers" in line for line in displayed))

    def test_source_profile_requires_retained_packet_before_login_or_requests(self):
        client = Mock()
        with self.assertRaisesRegex(desk_cli.WalkthroughError, "evidence-context"):
            desk_cli.compile_existing(client, str(uuid4()), driver_review=True)
        client.login.assert_not_called()
        client.request.assert_not_called()

    def test_source_profile_downgrade_is_rejected_without_approval_or_retry(self):
        result = compilation_receipt()
        result["compilation"]["schema_version"] = "source-backed-thesis-compilation-v1"
        client = research_cli.Client(result)
        with tempfile.TemporaryDirectory() as directory:
            journal = desk_cli.CommandJournal(Path(directory) / "source.jsonl")
            try:
                with self.assertRaisesRegex(desk_cli.WalkthroughError, "driver-review profile"):
                    desk_cli.compiled_review(client, result["thesis"],
                        selection={"provider_id": "nanogpt", "model_id": "fixture-model"}, trace={},
                        ask=lambda _: self.fail("No approval after profile downgrade"), say=lambda _: None,
                        journal=journal, evidence_context_id=result["compilation"]["evidence_context"]["id"],
                        driver_review=True)
                records = [json.loads(line) for line in journal.path.read_text().splitlines()]
                self.assertTrue(records[0]["detail"]["request"]["driver_review"])
            finally:
                journal.close()
        self.assertEqual([call[0] for call in client.calls], ["POST"])

    def test_morning_profile_flag_is_journalled_before_post_and_saved_recovery_needs_no_catalogue(self):
        result = morning_receipt()
        saved = result["synthesis"]
        retained = {"review": {"id": saved["review_id"], "digest": saved["review_digest"]},
            "current_disposition": {"status": "prepared"}}
        client = research_cli.Client(result, review=retained)
        displayed = []
        with tempfile.TemporaryDirectory() as directory:
            journal = desk_cli.CommandJournal(Path(directory) / "morning.jsonl")
            original = client.request
            def request(method, path, body=None):
                if method == "POST":
                    recorded = [json.loads(line) for line in journal.path.read_text().splitlines()]
                    self.assertTrue(recorded[0]["detail"]["request"]["driver_review"])
                    self.assertTrue(body["driver_review"])
                return original(method, path, body)
            client.request = request
            try:
                with patch.object(review_morning, "select_model", return_value={
                        "provider_id": "nanogpt", "model_id": "fixture-model"}):
                    review_morning.review_morning(client, saved["review_id"], command_id=saved["command_id"],
                        driver_review=True, journal=journal, ask=news.answers(["trader", "synthesise"]),
                        secret=lambda _: "private-password", say=displayed.append)
            finally:
                journal.close()
        recovery = research_cli.Client(result)
        with patch.object(review_morning, "select_model", side_effect=AssertionError("No catalogue on recovery")):
            review_morning.review_morning(recovery, saved["review_id"], command_id=saved["command_id"],
                recover=True, ask=lambda _: "trader", secret=lambda _: "password", say=displayed.append)
        self.assertEqual([call[0] for call in recovery.calls], ["GET"])
        self.assertTrue(any("Driver reassessment" in line for line in displayed))

    def test_morning_profile_downgrade_is_rejected_after_one_journalled_request(self):
        result = morning_receipt()
        result["synthesis"]["schema_version"] = "retained-daily-synthesis-v1"
        saved = result["synthesis"]
        retained = {"review": {"id": saved["review_id"], "digest": saved["review_digest"]},
            "current_disposition": {"status": "prepared"}}
        client = research_cli.Client(result, review=retained)
        with tempfile.TemporaryDirectory() as directory:
            journal = desk_cli.CommandJournal(Path(directory) / "downgrade.jsonl")
            try:
                with patch.object(review_morning, "select_model", return_value={
                        "provider_id": "nanogpt", "model_id": "fixture-model"}), self.assertRaisesRegex(
                        desk_cli.WalkthroughError, "driver-review profile"):
                    review_morning.review_morning(client, saved["review_id"], command_id=saved["command_id"],
                        driver_review=True, journal=journal, ask=news.answers(["trader", "synthesise"]),
                        secret=lambda _: "password", say=lambda _: None)
            finally:
                journal.close()
        self.assertEqual(sum(call[0] == "POST" for call in client.calls), 1)

    def test_news_profile_flag_is_retained_before_post_and_assessment_is_rendered(self):
        client = news.Client(response=news_receipt())
        displayed = []
        with tempfile.TemporaryDirectory() as directory:
            journal = review_news.ReviewJournal(Path(directory) / "news.jsonl")
            original = client.request
            def request(method, path, body=None):
                if method == "POST":
                    records = [json.loads(line) for line in journal.path.read_text().splitlines()]
                    requested = next(item for item in records if item["kind"] == "analysis_requested")
                    self.assertTrue(requested["detail"]["request"]["driver_review"])
                    self.assertTrue(body["driver_review"])
                return original(method, path, body)
            client.request = request
            try:
                review_news.review_one(client, news.THESIS, journal, requested_source=news.SOURCE,
                    requested_model=news.MODEL, driver_review=True, ask=news.answers(["trader", "run", ""]),
                    secret=lambda _: "password", say=displayed.append)
            finally:
                journal.close()
        self.assertEqual(sum(call[0] == "POST" for call in client.calls), 1)
        self.assertTrue(any("Driver reassessment" in line for line in displayed))
        self.assertTrue(client.logged_out)

    def test_news_profile_downgrade_cannot_be_presented_as_the_requested_review(self):
        client = news.Client(response=news.result())
        with tempfile.TemporaryDirectory() as directory:
            journal = review_news.ReviewJournal(Path(directory) / "news-downgrade.jsonl")
            try:
                with self.assertRaisesRegex(desk_cli.WalkthroughError, "driver-review profile"):
                    review_news.review_one(client, news.THESIS, journal, requested_source=news.SOURCE,
                        requested_model=news.MODEL, driver_review=True, ask=news.answers(["trader", "run"]),
                        secret=lambda _: "password", say=lambda _: None)
            finally:
                journal.close()
        self.assertEqual(sum(call[0] == "POST" for call in client.calls), 1)
        self.assertTrue(client.logged_out)
