"""Exact refinement inputs, immutable review authority and paid-call recovery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings

from macro_agent.domain.models import CompiledThesisVersion, canonical_json, text_digest
from macro_agent.persistence.context_binding import _resolved
from macro_agent.providers import ProviderError
from macro_agent.theses import compilation, service
from macro_agent.theses.models import (
    CompilationAttempt, CompilationBudget, CompilationResult, InterpretationRecord,
    RefinementSubmission, TextVersionRecord,
)
from macro_agent.theses.tests.test_compilation import EMPTY, EXACT, MODEL, RecordedProvider, document


class AnswerProvider(RecordedProvider):
    def complete(self, model_id, messages):
        result = super().complete(model_id, messages)
        envelope = json.loads(messages[1]["content"])
        inputs = envelope["refinement_inputs"]
        result_document = document()
        if inputs:
            answer = inputs[-1]
            result_document["interpretation"]["horizon"] = answer["exact_answer"]
            result_document["grounding"].append({"field": "horizon", "index": None,
                "input_id": answer["input_id"], "exact_quote": answer["exact_answer"]})
        result["content"] = json.dumps(result_document)
        return result


@override_settings(MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
                   MACRO_MODEL_API_KEY="test-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class RefinementPersistenceTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="refinement-persistence")
        self.actor = str(self.owner.pk)
        self.thesis = service.create_thesis(self.actor, str(uuid4()), EXACT, EMPTY)["thesis"]
        self.provider = AnswerProvider()
        CompilationBudget.objects.get_or_create(pk=1)
        self.parent = self.compile()
        self.thesis = self.parent["thesis"]

    def compile(self, command=None, **kwargs):
        return compilation.compile_thesis(self.actor, self.thesis["id"], command or str(uuid4()),
            self.thesis["revision"], MODEL, "nanogpt", provider=self.provider, **kwargs)

    def save(self, command=None, answers=None, parent=None, **kwargs):
        return compilation.save_refinement(self.actor, self.thesis["id"], command or str(uuid4()),
            self.thesis["revision"], parent or self.parent["compilation"]["id"],
            answers if answers is not None else [{"question_index": 0, "exact_answer": "six weeks"}],
            **kwargs)

    def approve(self):
        text, meaning = self.thesis["draft"]["text_version"], self.thesis["draft"]["interpretation"]
        return service.approve_thesis(self.actor, self.thesis["id"], str(uuid4()), text["id"],
            text["text_digest"], meaning["id"], meaning["digest"], self.thesis["revision"])

    def test_saving_exact_answers_is_provider_free_and_does_not_change_approval_or_draft(self):
        self.thesis = self.approve()["thesis"]
        answer = "  Six weeks.\r\nΔ  "
        before = self.thesis
        saved = self.save(answers=[{"question_index": 0, "exact_answer": answer}])
        self.assertEqual(saved["thesis"], before)
        self.assertEqual((self.provider.catalog_calls, self.provider.calls), (1, 1))
        item = saved["refinement"]["cumulative_inputs"][0]
        self.assertEqual(item["exact_answer"], answer)
        self.assertEqual(item["question"], "Over what period?")
        self.assertEqual(item["parent_attempt_id"], self.parent["compilation"]["id"])
        self.assertTrue(item["input_id"].startswith("answer:" + saved["refinement"]["id"]))
        self.assertEqual(saved["refinement"]["input_text_version"]["exact_text"], EXACT)
        self.assertEqual(TextVersionRecord.objects.count(), 1)

    def test_independent_connection_sees_saved_answers_and_admission_before_inference(self):
        saved = self.save()["refinement"]
        command = str(uuid4())
        def inspect():
            close_old_connections()
            try:
                attempt = CompilationAttempt.objects.get(command_id=command)
                return (str(attempt.refinement_id), attempt.refinement.cumulative_inputs,
                        attempt.text_version.exact_text, CompilationResult.objects.filter(attempt=attempt).exists())
            finally:
                close_old_connections()
        def callback():
            with ThreadPoolExecutor(max_workers=1) as pool:
                observed = pool.submit(inspect).result(timeout=5)
            self.assertEqual(observed, (saved["id"], saved["cumulative_inputs"], EXACT, False))
        self.provider.callback = callback
        result = self.compile(command, refinement_id=saved["id"])
        self.assertEqual(result["compilation"]["status"], "compiled")
        meaning = result["thesis"]["draft"]["interpretation"]
        self.assertEqual(meaning["horizon"], "six weeks")
        self.assertEqual(meaning["review_card"]["inputs"][1:], saved["cumulative_inputs"])
        self.assertIsNone(result["thesis"]["approved"])
        self.assertEqual(result["thesis"]["draft"]["text_version"]["exact_text"], EXACT)

    def test_model_switch_derives_current_saved_answers_without_caller_history(self):
        saved = self.save()["refinement"]
        first = self.compile(refinement_id=saved["id"])
        self.thesis = first["thesis"]
        switched = self.compile()
        self.assertEqual(switched["compilation"]["refinement_id"], saved["id"])
        self.assertEqual(switched["compilation"]["refinement_inputs"], saved["cumulative_inputs"])
        self.assertEqual(switched["thesis"]["draft"]["interpretation"]["horizon"], "six weeks")

    def test_saved_command_replay_remains_historical_without_network(self):
        saved_command, compile_command = str(uuid4()), str(uuid4())
        old_revision = self.thesis["revision"]
        saved = self.save(saved_command)["refinement"]
        result = self.compile(compile_command, refinement_id=saved["id"])
        self.thesis = service.propose_thesis(self.actor, self.thesis["id"], str(uuid4()),
            EXACT + " New view.", EMPTY, result["thesis"]["revision"])["thesis"]
        replay = compilation.save_refinement(self.actor, self.thesis["id"], saved_command,
            old_revision, self.parent["compilation"]["id"],
            [{"question_index": 0, "exact_answer": "six weeks"}])
        with override_settings(MACRO_MODEL_PROVIDER="openrouter", MACRO_MODEL_API_KEY="",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            recovered = compilation.compile_thesis(self.actor, self.thesis["id"], compile_command,
                old_revision, MODEL, "nanogpt", refinement_id=saved["id"], provider=self.provider)
        self.assertTrue(replay["refinement"]["replayed"])
        self.assertFalse(replay["refinement"]["is_current_context"])
        self.assertFalse(recovered["compilation"]["is_current_draft"])
        self.assertEqual(recovered["compilation"]["input_text_version"]["exact_text"], EXACT)
        self.assertEqual((self.provider.catalog_calls, self.provider.calls), (2, 2))

    def test_fresh_stale_parent_or_submission_fails_before_catalogue(self):
        saved = self.save()["refinement"]
        other = self.compile()
        self.thesis = other["thesis"]
        with self.assertRaises(service.ThesisConflict):
            self.save()
        with self.assertRaises(service.ThesisConflict):
            self.compile(refinement_id=saved["id"])
        self.assertEqual((self.provider.catalog_calls, self.provider.calls), (2, 2))

    def test_parent_changed_during_catalogue_is_rechecked_before_admission(self):
        saved = self.save()["refinement"]
        original = self.provider.list_models
        def catalogue():
            catalog = original()
            service.propose_thesis(self.actor, self.thesis["id"], str(uuid4()),
                EXACT + " New view.", EMPTY, self.thesis["revision"])
            return catalog
        self.provider.list_models = catalogue
        with self.assertRaises(service.ThesisConflict):
            self.compile(refinement_id=saved["id"])
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(CompilationAttempt.objects.count(), 1)

    def test_change_during_refined_inference_keeps_result_stale_and_answers_recoverable(self):
        saved = self.save()["refinement"]
        def writer():
            close_old_connections()
            try:
                service.propose_thesis(self.actor, self.thesis["id"], str(uuid4()),
                    EXACT + " New view.", EMPTY, self.thesis["revision"])
            finally:
                close_old_connections()
        def change():
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(writer).result(timeout=5)
        self.provider.callback = change
        result = self.compile(refinement_id=saved["id"])
        self.assertEqual(result["compilation"]["status"], "stale")
        self.assertIsNone(result["compilation"]["interpretation_version_id"])
        self.assertEqual(result["compilation"]["refinement_inputs"], saved["cumulative_inputs"])
        self.assertEqual(InterpretationRecord.objects.filter(origin="model_compilation").count(), 1)

    def test_unknown_attempt_recovery_by_command_preserves_answers_and_makes_no_retry(self):
        saved_command, command = str(uuid4()), str(uuid4())
        saved = self.save(saved_command)["refinement"]
        with patch.object(self.provider, "complete", side_effect=RuntimeError("simulated process crash")):
            with self.assertRaises(RuntimeError):
                self.compile(command, refinement_id=saved["id"])
        attempt = CompilationAttempt.objects.get(command_id=command)
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            recovered = compilation.get_compilation_command(self.actor, self.thesis["id"], command,
                clock=lambda: attempt.deadline_at + timedelta(seconds=1))
            answers = compilation.get_refinement_command(self.actor, self.thesis["id"], saved_command)
        self.assertEqual(recovered["compilation"]["status"], "outcome_unknown")
        self.assertEqual(recovered["compilation"]["refinement_inputs"], saved["cumulative_inputs"])
        self.assertEqual(answers["refinement"]["id"], saved["id"])
        self.assertEqual((self.provider.catalog_calls, self.provider.calls), (2, 1))
        self.assertFalse(CompilationResult.objects.filter(attempt=attempt).exists())

    def test_foreign_parent_submission_and_recovery_are_unavailable(self):
        other = get_user_model().objects.create_user(username="foreign-refinement")
        saved = self.save()["refinement"]
        for action in (
            lambda: compilation.save_refinement(str(other.pk), self.thesis["id"], str(uuid4()),
                self.thesis["revision"], self.parent["compilation"]["id"],
                [{"question_index": 0, "exact_answer": "a week"}]),
            lambda: compilation.get_refinement(str(other.pk), self.thesis["id"], saved["id"]),
            lambda: compilation.get_compilation_command(str(other.pk), self.thesis["id"], str(uuid4())),
        ):
            with self.assertRaises(service.ThesisUnavailable):
                action()
        self.assertEqual((self.provider.catalog_calls, self.provider.calls), (1, 1))

    def test_answer_validation_rejects_forged_history_duplicates_and_coercion(self):
        invalid = [[], [{"question_index": True, "exact_answer": "x"}],
            [{"question_index": 1, "exact_answer": "x"}],
            [{"question_index": 0, "exact_answer": "x", "question": "forged"}],
            [{"question_index": 0, "exact_answer": "x"}] * 2,
            [{"question_index": 0, "exact_answer": "\x00"}],
            [{"question_index": 0, "exact_answer": "x" * 2001}]]
        for answers in invalid:
            with self.subTest(answers=answers), self.assertRaises((ValueError, TypeError)):
                self.save(answers=answers)
        self.assertFalse(RefinementSubmission.objects.exists())

    def test_caller_transactions_are_rejected_before_saving_answers(self):
        with transaction.atomic(), self.assertNumQueries(0):
            with self.assertRaises(RuntimeError):
                self.save()
        connection.set_autocommit(False)
        try:
            with self.assertNumQueries(0), self.assertRaises(RuntimeError):
                self.save()
        finally:
            connection.rollback()
            connection.set_autocommit(True)
        self.assertFalse(RefinementSubmission.objects.exists())

    def test_cumulative_answers_retain_prior_inputs_and_reject_overflow_without_truncation(self):
        many = document()
        many["refinement_issues"] = [{"kind": "missing_detail", "input_id": None,
            "exact_quote": None, "explanation": "A consequential detail is absent.",
            "question": f"Clarify detail {index}?"} for index in range(16)]
        with patch("macro_agent.theses.tests.test_refinement.document", return_value=many):
            self.parent = self.compile()
            self.thesis = self.parent["thesis"]
            saved = self.save(answers=[{"question_index": index, "exact_answer": "x" * 1000}
                                      for index in range(16)])["refinement"]
            refined = self.compile(refinement_id=saved["id"])
        self.assertEqual(refined["compilation"]["status"], "compiled")
        self.parent, self.thesis = refined, refined["thesis"]
        with self.assertRaises(ValueError):
            self.save()
        self.assertEqual(RefinementSubmission.objects.count(), 1)
        self.assertEqual(len(saved["cumulative_inputs"]), 16)
        self.assertEqual(sum(len(item["exact_answer"]) for item in saved["cumulative_inputs"]), 16000)

    def test_second_submission_extends_history_and_database_rejects_replacing_prefix(self):
        first = self.save()["refinement"]
        self.parent = self.compile(refinement_id=first["id"])
        self.thesis = self.parent["thesis"]
        second = self.save(answers=[{"question_index": 0, "exact_answer": "seven weeks"}])["refinement"]
        self.assertEqual(second["cumulative_inputs"][:-1], first["cumulative_inputs"])
        self.assertEqual(second["cumulative_inputs"][-1]["exact_answer"], "seven weeks")
        row = RefinementSubmission.objects.get(pk=second["id"])
        row.pk, row.command_id = uuid4(), uuid4()
        row.cumulative_inputs[0]["exact_answer"] = "forged earlier answer"
        with self.assertRaises(IntegrityError), transaction.atomic():
            row.save(force_insert=True)

    def test_legacy_hash_and_card_bound_approval_reconstruct_together(self):
        raw = service.create_thesis(self.actor, str(uuid4()), EXACT, EMPTY)["thesis"]
        meaning = raw["draft"]["interpretation"]
        value = CompiledThesisVersion(meaning["id"], meaning["text_version_id"], (), None, (),
            InterpretationRecord.objects.get(pk=meaning["id"]).known_at)
        expected = text_digest(canonical_json({"version_id": value.version_id,
            "thesis_version_id": value.thesis_version_id, "drivers": [], "horizon": None,
            "invalidation_signposts": [], "known_at": value.known_at.isoformat()}))
        self.assertEqual(value.digest, expected)
        self.assertIsNone(meaning["review_card"])
        saved = self.save()["refinement"]
        self.thesis = self.compile(refinement_id=saved["id"])["thesis"]
        approved = self.approve()["thesis"]
        row = service._record(self.actor, self.thesis["id"])
        approval, inputs, _ = _resolved(row, approved["approved"]["approval"]["id"], "default")
        self.assertEqual(inputs["interpretation"]["review_card"]["inputs"][1:], saved["cumulative_inputs"])
        self.assertEqual(approval.interpretation.digest, service.interpretation_value(approval.interpretation).digest)
        self.assertEqual(inputs["text"]["exact_text"], EXACT)

    def test_approval_hash_covers_proposed_card_content_without_adopting_it_as_intent(self):
        text, meaning = self.thesis["draft"]["text_version"], self.thesis["draft"]["interpretation"]
        record = InterpretationRecord.objects.get(pk=meaning["id"])
        card = json.loads(json.dumps(meaning["review_card"]))
        card["document"]["review_card"]["affected_assets"]["proposed"] = ["An unverified oil exposure."]
        changed = CompiledThesisVersion(str(record.pk), str(record.text_version_id),
            tuple(record.drivers), record.horizon, tuple(record.invalidation_signposts),
            record.known_at, review_card_json=canonical_json(card))
        self.assertNotEqual(changed.digest, meaning["digest"])
        with self.assertRaises(service.ThesisConflict):
            service.approve_thesis(self.actor, self.thesis["id"], str(uuid4()), text["id"],
                text["text_digest"], meaning["id"], changed.digest, self.thesis["revision"])
        approved = self.approve()["thesis"]
        self.assertEqual(approved["approved"]["interpretation"]["drivers"], meaning["drivers"])
        self.assertEqual(approved["approved"]["interpretation"]["review_card"], meaning["review_card"])

    def test_database_rejects_answer_mutation_and_cross_thesis_refinement(self):
        saved = self.save()["refinement"]
        submission = RefinementSubmission.objects.get(pk=saved["id"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            RefinementSubmission.objects.filter(pk=submission.pk).update(answers=[])
        with self.assertRaises(IntegrityError), transaction.atomic():
            RefinementSubmission.objects.filter(pk=submission.pk).delete()
        other = service.create_thesis(self.actor, str(uuid4()), EXACT, EMPTY)["thesis"]
        submission.pk = uuid4()
        submission.command_id = uuid4()
        submission.thesis_id = other["id"]
        submission.text_version_id = other["draft"]["text_version"]["id"]
        with self.assertRaises(IntegrityError), transaction.atomic():
            submission.save(force_insert=True)
