"""PostgreSQL authority, inference races, admission and crash dispositions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.providers import ProviderError
from macro_agent.theses import compilation, service
from macro_agent.theses.models import CompilationAttempt, CompilationBudget, CompilationResult, InterpretationRecord, TextVersionRecord


EXACT = "  Gold may benefit if real yields fall.\r\nΔ\r\n"
MODEL = "example/cheap"
EMPTY = {"drivers": [], "horizon": None, "invalidation_signposts": []}


def document():
    return {"interpretation": {**EMPTY, "drivers": ["Falling real yields may support gold."]},
        "grounding": [{"field": "drivers", "index": 0, "exact_quote": "Gold may benefit if real yields fall."}],
        "refinement_issues": [{"kind": "missing_detail", "exact_quote": None,
            "explanation": "No horizon is supplied.", "question": "Over what period?"}],
        "agent_hypotheses": [], "counter_case": "Unverified: another driver may dominate."}


class RecordedProvider:
    def __init__(self, callback=None):
        self.callback = callback
        self.calls = 0
        self.catalog_calls = 0

    def list_models(self):
        self.catalog_calls += 1
        return {"fetched_at": timezone.now().isoformat(), "models": [{"id": MODEL, "name": "Test model",
            "context_length": 32768, "input_price_usd_per_million": "1",
            "output_price_usd_per_million": "2", "capabilities": {"chat_completions": True}}]}

    def complete(self, model_id, messages):
        self.calls += 1
        if connection.in_atomic_block:
            raise AssertionError("inference must not retain a transaction or locks")
        if self.callback:
            self.callback()
        return {"content": json.dumps(document()), "reported_model": model_id,
            "provider_request_id": "recorded-request", "usage": {"prompt_tokens": 100,
                "completion_tokens": 50, "total_tokens": 150},
            "reported_cost_usd": None, "finish_reason": "stop", "latency_ms": 1}


@override_settings(MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
                   MACRO_MODEL_API_KEY="test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class CompilationPersistenceTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="compile-persistence")
        self.actor = str(self.owner.pk)
        self.thesis = service.create_thesis(self.actor, str(uuid4()), EXACT, EMPTY)["thesis"]
        self.provider = RecordedProvider()
        CompilationBudget.objects.get_or_create(pk=1)

    def compile(self, command=None, **kwargs):
        return compilation.compile_thesis(self.actor, self.thesis["id"], command or str(uuid4()),
            self.thesis["revision"], MODEL, "nanogpt", provider=self.provider, **kwargs)

    def approval(self, thesis):
        text, meaning = thesis["draft"]["text_version"], thesis["draft"]["interpretation"]
        return service.approve_thesis(self.actor, thesis["id"], str(uuid4()), text["id"],
            text["text_digest"], meaning["id"], meaning["digest"], thesis["revision"])

    def test_model_proposal_and_explicit_approval_have_distinct_authority(self):
        result = self.compile()
        self.assertEqual(result["thesis"]["draft"]["text_version"]["exact_text"], EXACT)
        self.assertEqual(TextVersionRecord.objects.count(), 1)
        self.assertIsNone(result["thesis"]["approved"])
        self.assertEqual(result["thesis"]["draft"]["interpretation"]["origin"], "model_compilation")
        self.assertIsNone(result["thesis"]["draft"]["interpretation"]["horizon"])
        self.assertEqual(result["compilation"]["estimated_cost_usd"], "0.0002")
        self.assertIsNone(result["compilation"]["reported_cost_usd"])
        approved = self.approval(result["thesis"])
        self.assertEqual(approved["thesis"]["approved"]["interpretation"]["digest"],
                         result["thesis"]["draft"]["interpretation"]["digest"])
        self.assertEqual(approved["thesis"]["approved"]["text_version"]["exact_text"], EXACT)

    def test_duplicate_command_never_spends_again_and_cannot_reactivate_history(self):
        command = str(uuid4())
        first = self.compile(command)
        newer = service.propose_thesis(self.actor, self.thesis["id"], str(uuid4()),
            EXACT + " New intent.", EMPTY, first["thesis"]["revision"])["thesis"]
        again = self.compile(command)
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.provider.catalog_calls, 1)
        self.assertEqual(again["compilation"]["id"], first["compilation"]["id"])
        self.assertEqual(again["compilation"]["status"], "compiled")
        self.assertFalse(again["compilation"]["is_current_draft"])
        self.assertEqual(again["thesis"]["revision"], newer["revision"])

    def test_independent_writer_during_inference_prevents_stale_installation(self):
        def writer():
            close_old_connections()
            try:
                service.propose_thesis(self.actor, self.thesis["id"], str(uuid4()),
                    EXACT + " New intent.", EMPTY, self.thesis["revision"])
            finally:
                close_old_connections()
        def concurrent_change():
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(writer).result(timeout=5)
        self.provider.callback = concurrent_change
        result = self.compile()
        self.assertEqual(result["compilation"]["status"], "stale")
        self.assertFalse(result["compilation"]["is_current_draft"])
        self.assertIsNotNone(result["compilation"]["document"])
        self.assertIsNone(result["compilation"]["interpretation_version_id"])
        self.assertTrue(result["thesis"]["draft"]["text_version"]["exact_text"].endswith(" New intent."))
        self.assertEqual(InterpretationRecord.objects.filter(origin="model_compilation").count(), 0)

    def test_existing_approval_remains_active_during_recompilation(self):
        approved = self.approval(self.thesis)["thesis"]
        self.thesis = approved
        result = self.compile()
        self.assertEqual(result["thesis"]["approved"], approved["approved"])
        self.assertNotEqual(result["thesis"]["draft"]["interpretation"]["id"],
                            approved["approved"]["interpretation"]["id"])

    def test_independent_approval_during_inference_retains_result_as_stale(self):
        def approve():
            close_old_connections()
            try:
                self.approval(self.thesis)
            finally:
                close_old_connections()
        def change():
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(approve).result(timeout=5)
        self.provider.callback = change
        result = self.compile()
        self.assertEqual(result["compilation"]["status"], "stale")
        self.assertEqual(result["thesis"]["approved"]["interpretation"]["origin"], "user_supplied")
        self.assertEqual(result["thesis"]["draft"]["interpretation"]["origin"], "user_supplied")

    def test_crash_after_admission_is_unknown_and_same_command_is_not_retried(self):
        command = str(uuid4())
        with patch.object(self.provider, "complete", side_effect=RuntimeError("simulated process crash")):
            with self.assertRaises(RuntimeError):
                self.compile(command)
        attempt = CompilationAttempt.objects.get()
        again = self.compile(command, clock=lambda: attempt.deadline_at + timedelta(seconds=1))
        self.assertEqual(again["compilation"]["status"], "outcome_unknown")
        self.assertIsNone(again["compilation"]["reported_cost_usd"])
        self.assertFalse(CompilationResult.objects.exists())
        self.assertEqual(self.provider.catalog_calls, 1)

    def test_timeout_and_invalid_output_preserve_cost_uncertainty_and_draft(self):
        with patch.object(self.provider, "complete", side_effect=ProviderError("outcome_unknown")):
            result = self.compile()
        self.assertEqual(result["compilation"]["status"], "outcome_unknown")
        self.assertEqual(result["thesis"]["revision"], self.thesis["revision"])
        with patch.object(self.provider, "complete", return_value={"content": "not JSON",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}):
            malformed = self.compile()
        self.assertEqual(malformed["compilation"]["status"], "failed")
        self.assertEqual(malformed["compilation"]["estimated_cost_usd"], "0.0002")
        self.assertFalse(malformed["compilation"]["is_current_draft"])

    def test_owner_budget_counts_failed_calls_and_unknown_admissions(self):
        with override_settings(MACRO_COMPILATION_OWNER_ATTEMPTS_PER_DAY=1,
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            with patch.object(self.provider, "complete", side_effect=ProviderError("authentication")):
                self.compile()
            with self.assertRaises(compilation.CompilationBudgetExhausted):
                self.compile()
        self.assertEqual(CompilationAttempt.objects.count(), 1)

    def test_aggregate_budget_serializes_independent_owners(self):
        other = get_user_model().objects.create_user(username="compile-budget-other")
        other_thesis = service.create_thesis(str(other.pk), str(uuid4()), EXACT, EMPTY)["thesis"]
        barrier = Barrier(2)
        def execute(actor, thesis):
            close_old_connections()
            adapter = RecordedProvider()
            original = adapter.list_models
            def catalog():
                data = original()
                barrier.wait(timeout=5)
                return data
            adapter.list_models = catalog
            try:
                result = compilation.compile_thesis(actor, thesis["id"], str(uuid4()),
                    thesis["revision"], MODEL, "nanogpt", provider=adapter)
                return result["compilation"]["status"]
            except compilation.CompilationBudgetExhausted:
                return "blocked"
            finally:
                close_old_connections()
        with override_settings(MACRO_COMPILATION_ATTEMPTS_PER_DAY=1,
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            with ThreadPoolExecutor(max_workers=2) as pool:
                tasks = [pool.submit(execute, self.actor, self.thesis),
                         pool.submit(execute, str(other.pk), other_thesis)]
                outcomes = [task.result(timeout=10) for task in tasks]
        self.assertCountEqual(outcomes, ["compiled", "blocked"])
        self.assertEqual(CompilationAttempt.objects.count(), 1)

    def test_database_rejects_history_mutation_and_cross_attempt_provenance(self):
        first = self.compile()
        self.thesis = first["thesis"]
        second = self.compile()
        for model in (CompilationAttempt, CompilationResult):
            with self.subTest(model=model), self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.all().delete()
        original = InterpretationRecord.objects.get(pk=first["compilation"]["interpretation_version_id"])
        other = service.create_thesis(self.actor, str(uuid4()), EXACT, EMPTY)["thesis"]
        with self.assertRaises(IntegrityError), transaction.atomic():
            original.pk = uuid4()
            original.compilation_id = second["compilation"]["id"]
            original.thesis_id = other["id"]
            original.text_version_id = other["draft"]["text_version"]["id"]
            original.save(force_insert=True)
