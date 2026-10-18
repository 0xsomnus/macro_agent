"""Question-led research preserves evidence, intent and paid-call recovery."""

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.domain.compilation import SECTIONS
from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.monitoring import capture, gdelt_research
from macro_agent.monitoring.models import CaptureAttempt, CaptureOutcome, SourceRevision
from macro_agent.monitoring.sources import SourceBatch, SourceError, SourceItem
from macro_agent.providers import ProviderError
from macro_agent.theses import compilation, service
from macro_agent.theses.models import CompilationAttempt, CompilationBudget, ThesisRecord

from macro_agent.desk import evidence, investigation, permissions
from macro_agent.desk.investigation_models import (ResearchDiscoveryAttempt,
    ResearchDiscoveryReceipt, ResearchDiscoveryResult, ResearchPlanAttempt, ResearchPlanResult, ResearchRun)


MODEL = "example/research-cheap"
QUESTION = "  Could a disruption affect unfamiliar helionite exposure?\r\nΔ\r\n"


def plan_document(count=2):
    return {"schema_version": "research-plan-v1", "questions": [{
        "question_id": "q" + str(index),
        "question": "What explains the proposed relationship?" if index == 0 else "What could offset the relationship?",
        "why_material": "The trade idea depends on this unverified mechanism.",
        "evidence_to_seek": "Attributed supply disruption and downstream costs.",
        "counter_evidence_to_seek": "Replacement supply, substitution and company cost offsets.",
        "query": "helionite supply disruption" if index == 0 else "helionite replacement supply importer costs",
    } for index in range(count)]}


def compilation_document(context):
    report = context["evidence"]["reports"][0]
    return {"interpretation": {"drivers": [], "horizon": None, "invalidation_signposts": []},
        "grounding": [], "refinement_issues": [], "agent_hypotheses": [], "counter_case": None,
        "review_card": {section: {"extracted": [], "proposed": [], "gap": "Unresolved."}
                        for section in SECTIONS},
        "attributed_claims": [{"claim_id": "source-headline", "revision_id": report["revision_id"],
                               "field": "title", "exact_quote": report["title"]}],
        "factual_conflicts": [], "evidence_assessment": {"summary": "A bounded headline-level research result.",
            "supporting_claim_ids": [], "counter_claim_ids": ["source-headline"],
            "gaps": ["No article-level evidence, verified prices or instrument availability."]},
        "proposed_drivers": [{"driver_id": "importer-costs", "explanation": "Input costs may offset a demand benefit.",
            "transmission": "Higher input costs could reduce importer margins.",
            "supporting_claim_ids": [], "counter_claim_ids": ["source-headline"],
            "assumptions": ["Costs cannot be passed on immediately."],
            "uncertainty": "The headline does not establish the magnitude or company exposure.",
            "why_material": "An importer is not equivalent to direct commodity exposure."}],
        "exposure_candidates": [{"candidate_id": "indirect-equity", "asset": "Helionite-related equity research",
            "expression": "Investigate whether an accessible indirect equity instrument exists.",
            "relationship": "Input costs may adversely affect importers.", "claim_ids": ["source-headline"],
            "basis_risks": ["Company margins can diverge from commodity prices."],
            "verification_questions": ["Is a suitable instrument available?"],
            "uncertainty": "Neither listing nor economic exposure is verified.", "availability": "unverified"}]}


class ResearchProvider:
    def __init__(self, *, questions=2, fail=None, callback=None):
        self.questions, self.fail, self.callback = questions, fail, callback
        self.calls = self.catalog_calls = 0

    def list_models(self):
        self.catalog_calls += 1
        assert not connection.in_atomic_block
        return {"fetched_at": timezone.now().isoformat(), "models": [{"id": MODEL,
            "name": "Recorded research model", "capabilities": {"chat_completions": True},
            "input_price_usd_per_million": None, "output_price_usd_per_million": None}]}

    def complete(self, model_id, messages):
        self.calls += 1
        assert not connection.in_atomic_block
        context = json.loads(messages[1]["content"])
        role = "compilation" if "evidence" in context else "plan"
        if self.callback:
            self.callback(role)
        if self.fail and role == "plan":
            raise self.fail
        document = compilation_document(context) if role == "compilation" else plan_document(self.questions)
        return {"content": canonical_json(document), "reported_model": model_id,
            "provider_request_id": "recorded-" + role,
            "usage": {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50},
            "reported_cost_usd": None, "latency_ms": 1}


class RecordedDiscovery:
    def __init__(self, *, count=2, fail=None):
        self.count, self.fail, self.calls = count, fail, 0

    def __call__(self, query, *, clock):
        self.calls += 1
        assert not connection.in_atomic_block
        if self.fail:
            raise self.fail
        slug = text_digest(query)[:12]
        articles = [{"url": "https://publisher.example/" + slug + "/" + str(index),
            "title": "Synthetic importer costs may offset the helionite exposure idea " + str(index),
            "seendate": "20261016T090000Z", "domain": "publisher.example",
            "language": "English", "sourcecountry": "United States"}
            for index in range(self.count)]
        return gdelt_research.parse_metadata(json.dumps({"articles": articles}).encode(),
            query=query, received_at=clock())


@override_settings(MACRO_ENABLE_RESEARCH_DISCOVERY=True, MACRO_ENABLE_CONTINUOUS_DESK=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-research-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class QuestionResearchTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="question-owner")
        self.other = get_user_model().objects.create_user(username="question-other")
        self.actor = str(self.owner.pk)
        self.provider, self.discovery = ResearchProvider(), RecordedDiscovery()
        self.command = str(uuid4())
        CompilationBudget.objects.get_or_create(pk=1)

    def start(self, **kwargs):
        return investigation.start_research(self.actor, self.command, QUESTION, "nanogpt", MODEL,
            provider=self.provider, discovery=self.discovery, **kwargs)

    def resume(self, **kwargs):
        run = ResearchRun.objects.get()
        return investigation.continue_research(self.actor, str(run.pk), provider=self.provider,
                                              discovery=self.discovery, **kwargs)

    def test_rough_question_gets_sourced_counter_analysis_without_hand_selection_or_authority(self):
        value = self.start()["research"]
        self.assertEqual(value["status"], "compiled")
        self.assertEqual(value["exact_question"], QUESTION)
        self.assertEqual(self.provider.calls, 2)
        self.assertEqual(self.discovery.calls, 2)
        self.assertEqual(ResearchPlanAttempt.objects.count(), 1)
        self.assertEqual(CompilationAttempt.objects.count(), 1)
        self.assertEqual(SourceRevision.objects.count(), 4)
        self.assertEqual(value["compilation"]["thesis"]["draft"]["text_version"]["exact_text"], QUESTION)
        self.assertIsNone(value["compilation"]["thesis"]["approved"])
        self.assertEqual(value["compilation"]["compilation"]["document"]["interpretation"]["drivers"], [])
        self.assertTrue(all(not flag for flag in value["authority"].values()))
        self.assertIsNone(value["costs"]["total_known_cost_usd"])
        from macro_agent.scheduling.models import WatchRecord
        from macro_agent.positions.models import PositionRecord
        self.assertEqual(WatchRecord.objects.count(), 0)
        self.assertEqual(PositionRecord.objects.count(), 0)

    def test_saved_post_and_get_recover_before_keys_catalogues_or_discovery(self):
        first = self.start()
        counts = self.provider.calls, self.provider.catalog_calls, self.discovery.calls
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            again = self.start()
            by_command = investigation.get_research_command(self.actor, self.command)
            by_id = investigation.get_research(self.actor, first["research"]["id"])
        self.assertTrue(again["replayed"])
        self.assertTrue(by_command["replayed"])
        self.assertEqual(by_id["research"]["status"], "compiled")
        self.assertEqual(counts, (self.provider.calls, self.provider.catalog_calls, self.discovery.calls))

    def test_same_command_cannot_change_question_or_selected_provider(self):
        self.start()
        with self.assertRaises(service.ThesisConflict):
            investigation.start_research(self.actor, self.command, QUESTION + "changed", "nanogpt", MODEL,
                provider=self.provider, discovery=self.discovery)
        self.assertEqual(self.provider.calls, 2)

    def test_uncertain_planning_call_is_never_resent_by_post_or_explicit_continue(self):
        self.provider.fail = ProviderError("outcome_unknown")
        self.assertEqual(self.start()["research"]["status"], "plan_uncertain")
        self.provider.fail = None
        self.start()
        self.resume()
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.discovery.calls, 0)

    def test_crash_after_paid_admission_remains_readable_without_result_or_resend(self):
        self.provider.fail = RuntimeError("simulated process death")
        with self.assertRaises(RuntimeError):
            self.start()
        self.assertEqual(ResearchPlanAttempt.objects.count(), 1)
        self.assertEqual(ResearchPlanResult.objects.count(), 0)
        self.provider.fail = None
        self.resume()
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.discovery.calls, 0)

    def test_no_results_is_qualified_terminal_without_invented_thesis_or_second_paid_call(self):
        self.discovery.count = 0
        value = self.start()["research"]
        self.assertEqual(value["status"], "no_evidence")
        self.assertIsNone(value["compilation"])
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(CompilationAttempt.objects.count(), 0)
        self.resume()
        self.assertEqual(self.discovery.calls, 2)

    def test_saturated_search_retains_excluded_candidate_and_explicit_limits(self):
        self.discovery.count = 5
        value = self.start()["research"]
        self.assertEqual(SourceRevision.objects.count(), 8)
        for discovery in value["discoveries"]:
            self.assertTrue(discovery["metadata"]["candidate_cap_reached"])
            self.assertFalse(discovery["metadata"]["coverage_complete"])
            self.assertEqual(len(discovery["metadata"]["candidates"]), 5)
            self.assertFalse(discovery["metadata"]["candidates"][-1]["selected"])

    def test_restart_after_capture_commit_recovers_without_repeating_fetch_or_paid_plan(self):
        original = capture.observe_capture
        with patch.object(capture, "observe_capture", side_effect=RuntimeError("crash after capture")):
            with self.assertRaises(RuntimeError):
                self.start()
        self.assertEqual(CaptureOutcome.objects.filter(status="captured").count(), 1)
        self.assertEqual(ResearchDiscoveryReceipt.objects.count(), 1)
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.discovery.calls, 1)
        after_lease = CaptureAttempt.objects.get().deadline_at + timedelta(seconds=1)
        saved = investigation.get_research_command(self.actor, self.command, clock=lambda: after_lease)
        self.assertEqual(saved["research"]["status"], "discovering")
        with patch.object(capture, "observe_capture", wraps=original):
            self.assertEqual(self.resume(clock=lambda: after_lease)["research"]["status"], "compiled")
        self.assertEqual(self.discovery.calls, 2)
        self.assertEqual(self.provider.calls, 2)

    def test_restart_with_retained_transport_receipt_commits_it_without_a_second_get(self):
        with patch.object(capture, "commit_batch", side_effect=RuntimeError("crash before capture commit")):
            with self.assertRaises(RuntimeError):
                self.start()
        self.assertEqual(ResearchDiscoveryReceipt.objects.count(), 1)
        self.assertEqual(SourceRevision.objects.count(), 0)
        self.assertEqual(self.resume()["research"]["status"], "compiled")
        self.assertEqual(self.discovery.calls, 2)
        self.assertEqual(self.provider.calls, 2)

    def test_adapter_failure_is_visible_and_explicit_continue_does_not_loop(self):
        self.discovery.fail = SourceError("rate_limited")
        value = self.start()["research"]
        self.assertEqual(value["status"], "discovery_failed")
        self.assertEqual(value["discoveries"][0]["stop_reason"], "rate_limited")
        self.assertIsNone(value["discoveries"][0]["metadata"])
        self.discovery.fail = None
        self.resume()
        self.assertEqual(self.discovery.calls, 1)
        self.assertEqual(self.provider.calls, 1)

    @override_settings(MACRO_COMPILATION_OWNER_ATTEMPTS_PER_DAY=1,
                       SETTINGS_MODULE="macro_agent.web.local_settings")
    def test_plan_and_compilation_share_private_allowance_and_resume_only_unadmitted_call(self):
        with self.assertRaises(compilation.CompilationBudgetExhausted):
            self.start()
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(CompilationAttempt.objects.count(), 0)
        self.assertEqual(investigation.get_research_command(self.actor, self.command)["research"]["status"], "ready_to_compile")
        with override_settings(MACRO_COMPILATION_OWNER_ATTEMPTS_PER_DAY=2,
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            self.assertEqual(self.resume()["research"]["status"], "compiled")
        self.assertEqual(self.provider.calls, 2)
        self.assertEqual(self.discovery.calls, 2)

    def test_other_owner_cannot_inspect_or_continue_private_question(self):
        value = self.start()["research"]
        for callback in (
            lambda: investigation.get_research(str(self.other.pk), value["id"]),
            lambda: investigation.get_research_command(str(self.other.pk), self.command),
            lambda: investigation.continue_research(str(self.other.pk), value["id"], provider=self.provider),
        ):
            with self.assertRaises(service.ThesisUnavailable):
                callback()
        self.assertEqual(self.provider.calls, 2)

    def test_later_edit_changes_disposition_without_rewriting_saved_plan_or_compilation(self):
        value = self.start()["research"]
        draft = value["compilation"]["thesis"]
        service.propose_thesis(self.actor, draft["id"], str(uuid4()), "Changed question", {
            "drivers": [], "horizon": None, "invalidation_signposts": []}, draft["revision"])
        later = investigation.get_research(self.actor, value["id"])["research"]
        self.assertEqual(later["status"], "stale")
        self.assertEqual(later["plan"], value["plan"])
        self.assertEqual(later["compilation"]["compilation"]["document"],
                         value["compilation"]["compilation"]["document"])
        self.resume()
        self.assertEqual(self.provider.calls, 2)

    def test_database_protects_all_research_history_from_rewrite(self):
        self.start()
        models = (ResearchRun, ResearchPlanAttempt, ResearchPlanResult, ResearchDiscoveryAttempt,
                  ResearchDiscoveryReceipt, ResearchDiscoveryResult)
        for model in models:
            item = model.objects.first()
            with self.subTest(model=model.__name__), self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.filter(pk=item.pk).delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchRun.objects.update(exact_question="Fabricated")

    def test_cross_owner_plan_admission_is_rejected_by_database(self):
        self.provider.fail = RuntimeError("stop after admission")
        with self.assertRaises(RuntimeError):
            self.start()
        existing = ResearchPlanAttempt.objects.get()
        values = {field.name: getattr(existing, field.name) for field in existing._meta.fields
                  if field.name not in ("id", "run", "command_id", "owner")}
        # Use a second valid question lineage, then try to bind the first
        # owner's admission to another actor outside application services.
        self.provider.fail = ProviderError("outcome_unknown")
        investigation.start_research(str(self.other.pk), str(uuid4()), QUESTION, "nanogpt", MODEL,
            provider=self.provider, discovery=self.discovery)
        run = ResearchRun.objects.get(owner=self.other)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchPlanAttempt.objects.create(run=run, command_id=uuid4(), owner=self.owner, **values)

    def test_changed_question_during_planning_retains_stale_result_without_discovery(self):
        def edit(role):
            if role == "plan":
                run = ResearchRun.objects.get()
                service.propose_thesis(self.actor, str(run.thesis_id), str(uuid4()), "A different research question",
                    {"drivers": [], "horizon": None, "invalidation_signposts": []}, run.initial_revision)
        self.provider.callback = edit
        value = self.start()["research"]
        self.assertEqual(value["status"], "stale")
        self.assertEqual(value["plan"]["status"], "stale")
        self.assertEqual(self.discovery.calls, 0)

    def test_local_experiment_gate_rejects_before_creating_question_or_using_keys(self):
        with override_settings(MACRO_ENABLE_RESEARCH_DISCOVERY=False), self.assertRaises(compilation.CompilationDisabled):
            self.start()
        self.assertEqual(ThesisRecord.objects.count(), 0)
        self.assertEqual(self.provider.calls, 0)

    def test_capture_gate_is_checked_before_creating_question_or_paying_for_plan(self):
        with override_settings(MACRO_ENABLE_MONITORING_PROOF=False,
                SETTINGS_MODULE="macro_agent.web.local_settings"):
            with self.assertRaises(compilation.CompilationDisabled):
                self.start()
        self.assertEqual(ResearchRun.objects.count(), 0)
        self.assertEqual(self.provider.calls, 0)

    def test_guessed_revision_cannot_import_another_owners_private_research(self):
        value = self.start()["research"]
        other_draft = service.create_thesis(str(self.other.pk), str(uuid4()), "A private other question",
            {"drivers": [], "horizon": None, "invalidation_signposts": []})["thesis"]
        revision = value["discoveries"][0]["revision_ids"][0]
        with self.assertRaises(service.ThesisConflict):
            evidence.prepare_evidence(str(self.other.pk), other_draft["id"], str(uuid4()), [revision])

    def test_source_correction_during_compilation_retains_stale_result_and_original_question(self):
        def correct(role):
            if role != "compilation":
                return
            revision = SourceRevision.objects.select_related("report__source").first()
            source = revision.report.source
            item = SourceItem(revision.report.native_id, "Synthetic correction changes the reported cost shock",
                revision.payload["url"], None, revision.payload["content"])
            capture.capture(source.pk, source.contract, lambda: SourceBatch((item,), timezone.now(),
                "bounded_snapshot", False, "b" * 64))
        self.provider.callback = correct
        value = self.start()["research"]
        self.assertEqual(value["status"], "stale")
        self.assertEqual(value["compilation"]["compilation"]["status"], "stale")
        self.assertIsNone(value["compilation"]["compilation"]["interpretation_version_id"])
        self.assertEqual(value["compilation"]["thesis"]["draft"]["text_version"]["exact_text"], QUESTION)
        self.assertEqual(self.provider.calls, 2)

    def test_permission_withdrawal_keeps_readable_history_and_prevents_new_model_work(self):
        value = self.start()["research"]
        staff = get_user_model().objects.create_user(username="research-permission-staff", is_staff=True)
        source = SourceRevision.objects.select_related("report__source").first().report.source
        permissions.set_source_permission(str(staff.pk), source.pk, source.contract_digest, False,
            "Recorded withdrawal of internal research processing.")
        later = investigation.get_research(self.actor, value["id"])["research"]
        self.assertEqual(later["status"], "stale")
        self.assertEqual(later["plan"], value["plan"])
        self.assertEqual(self.resume()["research"]["status"], "stale")
        self.assertEqual(self.provider.calls, 2)
        self.assertEqual(self.discovery.calls, 2)

    def test_losing_capture_commit_race_adopts_captured_receipt_instead_of_uncertain(self):
        original = capture.commit_batch
        raced = False

        def independent_resume():
            close_old_connections()
            try:
                return self.resume()
            finally:
                close_old_connections()

        def interleave(*args, **kwargs):
            nonlocal raced
            result = original(*args, **kwargs)
            if not raced:
                raced = True
                with ThreadPoolExecutor(max_workers=1) as pool:
                    other = pool.submit(independent_resume).result(timeout=20)
                self.assertEqual(other["research"]["status"], "compiled")
            return result

        with patch.object(capture, "commit_batch", side_effect=interleave):
            value = self.start()["research"]
        self.assertEqual(value["status"], "compiled")
        self.assertEqual(self.provider.calls, 2)
        self.assertEqual(self.discovery.calls, 2)
        self.assertEqual(ResearchDiscoveryResult.objects.filter(status="outcome_unknown").count(), 0)

    def test_expired_unrecorded_discovery_is_uncertain_on_read_and_never_refetched(self):
        with patch.object(investigation, "_finish_discovery", side_effect=RuntimeError("process died before transport")):
            with self.assertRaises(RuntimeError):
                self.start()
        run = ResearchRun.objects.get()
        deadline = CaptureAttempt.objects.get().deadline_at
        value = investigation.get_research(self.actor, str(run.pk), clock=lambda: deadline + timedelta(seconds=1))
        self.assertEqual(value["research"]["status"], "discovery_uncertain")
        self.resume(clock=lambda: deadline + timedelta(seconds=1))
        self.assertEqual(self.discovery.calls, 0)
        self.assertEqual(self.provider.calls, 1)
