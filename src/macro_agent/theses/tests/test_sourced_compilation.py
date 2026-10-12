"""Sourced compilation retains admission, rejects stale adoption and recovers."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.desk import evidence
from macro_agent.desk.models import ResearchEvidenceContext
from macro_agent.desk.tests.test_research_evidence import EvidenceFixtures, SOURCE
from macro_agent.monitoring.models import SourceState
from macro_agent.monitoring.tests import test_analysis as recorded_analysis
from macro_agent.theses import compilation, service
from macro_agent.theses.models import CompilationAttempt, CompilationBudget, CompilationResult
from .test_compilation import RecordedProvider, MODEL, document


def independent(callback):
    close_old_connections()
    try:
        return callback()
    finally:
        close_old_connections()


class SourcedProvider(RecordedProvider):
    def complete(self, model_id, messages):
        result = super().complete(model_id, messages)
        packet = json.loads(messages[-1]["content"])
        report = packet["evidence"]["reports"][0]
        value = document()
        value.update(attributed_claims=[{"claim_id": "rate", "revision_id": report["revision_id"],
            "field": "content", "exact_quote": "The committee left the rate at 4%."}], factual_conflicts=[],
            evidence_assessment={"summary": "The report supplies a policy observation, not a verified regime.",
                "supporting_claim_ids": ["rate"], "counter_claim_ids": [], "gaps": ["Market expectations unavailable."]})
        result["content"] = json.dumps(value)
        return result


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ALLOW_SYNTHETIC_SETUP=True, MACRO_ENABLE_MODEL_COMPILATION=True,
    MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="recorded-test-key",
    SETTINGS_MODULE="macro_agent.web.local_settings")
class SourcedCompilationPersistenceTests(EvidenceFixtures, TransactionTestCase):
    server_lock_wait = recorded_analysis.PostgreSQLNewsAnalysisTests.server_lock_wait

    def setUp(self):
        self.setup_evidence()
        self.saved = self.prepare()
        self.provider = SourcedProvider()
        CompilationBudget.objects.get_or_create(pk=1)

    def compile(self, command=None, **kwargs):
        return compilation.compile_thesis(self.actor, self.thesis["id"], command or str(uuid4()),
            self.thesis["revision"], MODEL, "nanogpt", evidence_context_id=self.saved["evidence"]["id"],
            provider=self.provider, **kwargs)

    def approve(self, draft, command=None, **kwargs):
        text, meaning = draft["draft"]["text_version"], draft["draft"]["interpretation"]
        return service.approve_thesis(self.actor, draft["id"], command or str(uuid4()), text["id"],
            text["text_digest"], meaning["id"], meaning["digest"], draft["revision"], **kwargs)

    def test_admission_and_source_packet_visible_independently_before_inference(self):
        def check():
            with ThreadPoolExecutor(max_workers=1) as pool:
                attempt = pool.submit(independent, lambda: CompilationAttempt.objects.select_related(
                    "evidence_context").get()).result(timeout=10)
            self.assertEqual(attempt.evidence_context.content, self.saved["evidence"]["content"])
            self.assertFalse(CompilationResult.objects.exists())
        self.provider.callback = check
        result = self.compile()
        self.assertEqual(result["compilation"]["status"], "compiled")
        card = result["thesis"]["draft"]["interpretation"]["review_card"]
        self.assertEqual(card["evidence"]["context"], self.saved["evidence"]["content"])
        self.assertIsNone(result["thesis"]["approved"])
        self.approve(result["thesis"])

    def test_correction_during_inference_retains_paid_result_as_stale_without_installation(self):
        def change():
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(independent, lambda: self.capture_report("Corrected report")).result(timeout=10)
        self.provider.callback = change
        result = self.compile()["compilation"]
        self.assertEqual(result["status"], "stale")
        self.assertIsNotNone(result["document"])
        self.assertIsNone(result["interpretation_version_id"])
        self.assertEqual(result["evidence_disposition"]["status"], "stale")
        self.assertEqual(self.provider.calls, 1)

    def test_withdrawal_during_inference_preserves_outcome_without_installation(self):
        def change():
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(independent, self.withdraw).result(timeout=10)
        self.provider.callback = change
        result = self.compile()["compilation"]
        self.assertEqual(result["status"], "stale")
        self.assertTrue(any("permission_unavailable" in reason for reason in
                            result["evidence_disposition"]["stale_reasons"]))

    def test_later_correction_changes_only_disposition_and_blocks_new_approval(self):
        command = str(uuid4())
        first = self.compile(command)
        self.capture_report("Corrected report")
        replay = self.compile(command)
        self.assertEqual(replay["compilation"]["status"], "compiled")
        self.assertEqual(replay["compilation"]["evidence_disposition"]["status"], "stale")
        with self.assertRaisesMessage(service.ThesisConflict, "Source evidence changed"):
            self.approve(first["thesis"])
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.provider.catalog_calls, 1)

    def test_approval_history_retry_survives_later_withdrawal_without_reactivation(self):
        result = self.compile()
        command = str(uuid4())
        first = self.approve(result["thesis"], command)
        self.withdraw()
        replay = self.approve(result["thesis"], command)
        self.assertTrue(replay["command"]["replayed"])
        self.assertEqual(replay["thesis"]["approved"], first["thesis"]["approved"])
        with self.assertRaises(service.ThesisConflict):
            self.approve(result["thesis"])

    def test_stale_preflight_uses_no_catalogue_or_inference(self):
        self.withdraw()
        with self.assertRaises(service.ThesisConflict):
            self.compile()
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.provider.catalog_calls, 0)
        self.assertFalse(CompilationAttempt.objects.exists())

    def test_crash_recovery_after_permission_change_requires_no_credentials(self):
        command = str(uuid4())
        with patch.object(self.provider, "complete", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                self.compile(command)
        attempt = CompilationAttempt.objects.get()
        self.withdraw()
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            result = self.compile(command, clock=lambda: attempt.deadline_at + timedelta(seconds=1))
        self.assertEqual(result["compilation"]["status"], "outcome_unknown")
        self.assertFalse(CompilationResult.objects.exists())
        self.assertEqual(self.provider.catalog_calls, 1)

    def test_sql_rejects_detached_source_context(self):
        self.compile()
        attempt = CompilationAttempt.objects.get()
        attempt.pk = uuid4()
        attempt.command_id = uuid4()
        attempt.evidence_context_id = None
        with self.assertRaises(IntegrityError), transaction.atomic():
            attempt.save(force_insert=True)

    def test_source_backed_approval_rejects_ambient_transaction(self):
        result = self.compile()
        with transaction.atomic(), self.assertRaises(RuntimeError):
            self.approve(result["thesis"])

    def _mutation(self, kind, clock=timezone.now):
        if kind == "permission":
            return self.withdraw(clock=clock)
        return self.capture_report("Corrected race report", clock=clock)

    def _pid(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            return cursor.fetchone()[0]

    def _source_first(self, kind, phase):
        inference, return_model, source_locked, release_source, writer_started = (Event() for _ in range(5))
        pids, ticks = {}, 0
        draft = self.compile()["thesis"] if phase == "approval" else None
        def source_clock():
            nonlocal ticks
            ticks += 1
            if ticks == (1 if kind == "permission" else 2):
                pids["source"] = self._pid()
                source_locked.set()
                if not release_source.wait(10):
                    raise AssertionError("Source transaction was not released")
            return timezone.now()
        def callback():
            inference.set()
            if not return_model.wait(10):
                raise AssertionError("Recorded inference was not released")
        def writer():
            pids["writer"] = self._pid()
            writer_started.set()
            if phase == "completion":
                return self.compile()
            try:
                self.approve(draft)
            except service.ThesisConflict:
                return "blocked"
            return "approved"
        with ThreadPoolExecutor(max_workers=2) as pool:
            if phase == "completion":
                self.provider.callback = callback
                writer_future = pool.submit(independent, writer)
                self.assertTrue(inference.wait(10))
            mutation_future = pool.submit(independent, lambda: self._mutation(kind, source_clock))
            try:
                self.assertTrue(source_locked.wait(10))
                if phase == "completion":
                    return_model.set()
                else:
                    writer_future = pool.submit(independent, writer)
                self.assertTrue(writer_started.wait(10))
                self.server_lock_wait(pids["writer"], pids["source"], "macro_monitoring_sourcestate")
            finally:
                return_model.set()
                release_source.set()
            mutation = mutation_future.result(timeout=10)
            result = writer_future.result(timeout=10)
        if phase == "completion":
            self.assertEqual(result["compilation"]["status"], "stale")
            self.assertIsNotNone(result["compilation"]["document"])
            changed_at = mutation["observed_at"] if kind == "permission" else mutation.finished_at.isoformat()
            self.assertGreaterEqual(result["compilation"]["finished_at"], changed_at)
        else:
            self.assertEqual(result, "blocked")
            self.assertIsNone(service.get_thesis(self.actor, self.thesis["id"])["approved"])

    def _writer_first(self, kind, phase):
        writer_locked, release_writer, source_started = (Event() for _ in range(3))
        pids = {}
        command = str(uuid4())
        draft = self.compile()["thesis"] if phase == "approval" else None
        def writer_clock():
            if phase == "approval" or self.provider.calls:
                pids["writer"] = self._pid()
                writer_locked.set()
                if not release_writer.wait(10):
                    raise AssertionError("Writer transaction was not released")
            return timezone.now()
        def writer():
            if phase == "completion":
                return self.compile(command, clock=writer_clock)
            return self.approve(draft, command, clock=writer_clock)
        def mutation():
            pids["source"] = self._pid()
            source_started.set()
            return self._mutation(kind)
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer_future = pool.submit(independent, writer)
            try:
                self.assertTrue(writer_locked.wait(10))
                mutation_future = pool.submit(independent, mutation)
                self.assertTrue(source_started.wait(10))
                self.server_lock_wait(pids["source"], pids["writer"], "macro_monitoring_sourcestate")
            finally:
                release_writer.set()
            result = writer_future.result(timeout=10)
            mutation_future.result(timeout=10)
        if phase == "completion":
            self.assertEqual(result["compilation"]["status"], "compiled")
            self.assertEqual(result["compilation"]["evidence_disposition"]["status"], "current")
            replay = self.compile(command)
            self.assertEqual(replay["compilation"]["status"], "compiled")
            self.assertEqual(replay["compilation"]["evidence_disposition"]["status"], "stale")
            self.assertEqual(self.provider.calls, 1)
        else:
            self.assertEqual(service.get_thesis(self.actor, self.thesis["id"])["approved"],
                             result["thesis"]["approved"])
            self.assertTrue(self.approve(draft, command)["command"]["replayed"])

    def test_permission_first_forces_completion_wait_and_samples_clock_after_wait(self):
        self._source_first("permission", "completion")

    def test_correction_first_forces_completion_wait_and_samples_clock_after_wait(self):
        self._source_first("correction", "completion")

    def test_completion_first_blocks_permission_then_preserves_original_compiled_result(self):
        self._writer_first("permission", "completion")

    def test_completion_first_blocks_correction_then_preserves_original_compiled_result(self):
        self._writer_first("correction", "completion")

    def test_permission_first_forces_approval_wait_then_blocks_new_adoption(self):
        self._source_first("permission", "approval")

    def test_correction_first_forces_approval_wait_then_blocks_new_adoption(self):
        self._source_first("correction", "approval")

    def test_approval_first_blocks_permission_then_preserves_approved_user_state(self):
        self._writer_first("permission", "approval")

    def test_approval_first_blocks_correction_then_preserves_approved_user_state(self):
        self._writer_first("correction", "approval")
