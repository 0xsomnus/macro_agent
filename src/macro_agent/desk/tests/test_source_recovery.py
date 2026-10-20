"""Source repeats preserve paid admissions, complete lineage and global pacing."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from macro_agent.desk import investigation, permissions
from macro_agent.desk.models import ResearchEvidenceContext
from macro_agent.desk.investigation_models import (ResearchDiscoveryAttempt, ResearchDiscoveryReceipt,
    ResearchDiscoveryResult, ResearchPlanAttempt, ResearchRun, ResearchSourceState)
from macro_agent.monitoring import capture, gdelt_research
from macro_agent.monitoring.models import CaptureAttempt, SourceState
from macro_agent.monitoring.research_policy import MAX_RETRY_AFTER_SECONDS, RECOVERY_POLICY
from macro_agent.monitoring.sources import SourceError
from macro_agent.theses import service
from macro_agent.theses.models import CompilationAttempt, CompilationBudget

from .test_investigation import MODEL, QUESTION, RecordedDiscovery, ResearchProvider


class Clock:
    def __init__(self):
        self.at = timezone.now()

    def __call__(self):
        return self.at

    def advance(self, seconds):
        self.at += timedelta(seconds=seconds)


class RecoveryDiscovery(RecordedDiscovery):
    def __call__(self, query, *, clock):
        value = super().__call__(query, clock=clock)
        return gdelt_research.parse_metadata(json.dumps({"articles": [item["metadata"]
            for item in value.metadata["candidates"]]}).encode(), query=query,
            received_at=value.batch.received_at, policy_version=gdelt_research.RECOVERY_POLICY_VERSION)


@override_settings(MACRO_ENABLE_RESEARCH_DISCOVERY=True, MACRO_ENABLE_CONTINUOUS_DESK=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-research-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class SourceRecoveryTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="recovery-owner")
        self.other = get_user_model().objects.create_user(username="recovery-other")
        self.actor, self.command = str(self.owner.pk), str(uuid4())
        self.clock, self.provider, self.discovery = Clock(), ResearchProvider(questions=1), RecoveryDiscovery()
        CompilationBudget.objects.get_or_create(pk=1)

    def start(self, **kwargs):
        return investigation.start_research(self.actor, self.command, QUESTION, "nanogpt", MODEL,
            source_recovery=True, provider=self.provider, discovery=self.discovery, clock=self.clock, **kwargs)

    def resume(self, run=None):
        run = run or ResearchRun.objects.get(owner=self.owner)
        return investigation.continue_research(self.actor, str(run.pk), provider=self.provider,
            discovery=self.discovery, clock=self.clock)

    def test_timeout_pauses_then_only_source_is_repeated_with_exact_paid_plan(self):
        self.discovery.fail = SourceError("timeout")
        first = self.start()["research"]
        self.assertEqual(first["status"], "waiting_source")
        self.assertEqual(first["execution_policy"], dict(RECOVERY_POLICY))
        self.assertEqual(first["discoveries"][0]["recovery"]["retry_reason"], "timeout")
        self.assertIsNone(first["discoveries"][0]["metadata"])
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.discovery.calls, 1)
        self.resume()
        self.assertEqual(self.discovery.calls, 1)
        self.clock.advance(31)
        self.discovery.fail = None
        final = self.resume()["research"]
        self.assertEqual(final["status"], "compiled")
        self.assertEqual((self.provider.calls, self.discovery.calls), (2, 2))
        self.assertEqual(ResearchPlanAttempt.objects.count(), 1)
        self.assertEqual(CompilationAttempt.objects.count(), 1)
        self.assertEqual([item["attempt_number"] for item in final["discoveries"]], [1, 2])
        context = ResearchEvidenceContext.objects.get(pk=final["evidence_context_id"]).content
        self.assertEqual(context["schema_version"], "retained-source-evidence-v3")
        history = context["question_research"]["questions"][0]["attempts"]
        self.assertEqual([item["status"] for item in history], ["failed", "captured"])
        self.assertEqual(history[0]["metadata"]["retry_reason"], "timeout")
        self.assertEqual(history[1]["metadata"], {})
        self.assertEqual(history[1]["capture_id"], final["discoveries"][1]["capture_id"])

    def test_saved_start_reads_without_advancing_even_when_source_due(self):
        self.discovery.fail = SourceError("unavailable")
        first = self.start()
        self.clock.advance(31)
        self.discovery.fail = None
        with override_settings(MACRO_MODEL_API_KEY="", MACRO_MODEL_PROVIDER="openrouter",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            saved = self.start()
            read = investigation.get_research(self.actor, first["research"]["id"], clock=self.clock)
        self.assertTrue(saved["replayed"])
        self.assertEqual(read["research"]["status"], "discovering")
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 1))

    def test_retry_flag_is_part_of_request_identity_and_cannot_rewrite_old_runs(self):
        self.discovery.fail = SourceError("timeout")
        self.start()
        with self.assertRaises(service.ThesisConflict):
            investigation.start_research(self.actor, self.command, QUESTION, "nanogpt", MODEL,
                provider=self.provider, discovery=self.discovery, clock=self.clock)
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 1))

    def test_three_transport_attempts_are_terminal_without_second_paid_call(self):
        self.discovery.fail = SourceError("timeout")
        self.start()
        self.clock.advance(31)
        self.resume()
        self.clock.advance(61)
        final = self.resume()["research"]
        self.assertEqual(final["status"], "source_exhausted")
        self.clock.advance(500)
        self.resume()
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 3))
        self.assertEqual(CompilationAttempt.objects.count(), 0)

    def test_retry_after_is_not_shortened_and_shared_across_runs(self):
        self.discovery.fail = SourceError("rate_limited", retry_after_seconds=120)
        first = self.start()["research"]
        due = self.clock.at + timedelta(seconds=120)
        self.assertEqual(first["source_next_attempt_at"], due.isoformat())
        self.command = str(uuid4())
        other = self.start()["research"]
        self.assertEqual(other["status"], "waiting_source")
        self.assertEqual(other["source_next_attempt_at"], due.isoformat())
        self.assertEqual(self.discovery.calls, 1)
        self.clock.advance(31)
        self.resume(ResearchRun.objects.get(pk=first["id"]))
        self.assertEqual(self.discovery.calls, 1)

    def test_very_long_retry_after_blocks_safely_without_datetime_overflow(self):
        self.discovery.fail = SourceError("rate_limited", retry_after_seconds=MAX_RETRY_AFTER_SECONDS)
        first = self.start()["research"]
        self.assertEqual(first["status"], "source_deadline")
        self.assertIsNone(first["source_next_attempt_at"])
        self.assertEqual(ResearchSourceState.objects.get().next_request_at,
            datetime.max.replace(tzinfo=dt_timezone.utc))
        self.command = str(uuid4())
        calls = self.provider.calls
        other = self.start()["research"]
        self.assertEqual(other["status"], "source_deadline")
        self.assertIsNone(other["plan"])
        self.assertEqual(self.provider.calls, calls)
        self.assertEqual(self.discovery.calls, 1)
        original = investigation.get_research(self.actor, first["id"], clock=self.clock)["research"]
        self.assertEqual(original["plan"]["status"], "planned")
        self.assertEqual(original["discoveries"][0]["status"], "failed")

    def test_provider_floor_changed_during_catalogue_is_rechecked_before_paid_admission(self):
        original = self.provider.list_models

        def catalogue_with_cooldown():
            value = original()
            with transaction.atomic():
                root = ResearchSourceState.objects.create(id="gdelt", next_request_at=self.clock.at)
                root.next_request_at = datetime.max.replace(tzinfo=dt_timezone.utc)
                root.generation += 1
                root.save(update_fields=("next_request_at", "generation"))
            return value

        with patch.object(self.provider, "list_models", side_effect=catalogue_with_cooldown):
            final = self.start()["research"]
        self.assertEqual(final["status"], "source_deadline")
        self.assertIsNone(final["plan"])
        self.assertEqual((self.provider.calls, self.discovery.calls), (0, 0))
        self.assertEqual(ResearchPlanAttempt.objects.count(), 0)

    def test_nonretryable_metadata_failure_does_not_become_unavailable(self):
        self.discovery.fail = SourceError("invalid_json")
        first = self.start()["research"]
        self.assertEqual(first["status"], "discovery_failed")
        self.assertIsNone(first["discoveries"][0]["recovery"]["retry_reason"])
        self.clock.advance(31)
        self.resume()
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 1))

    def test_successful_queries_survive_waits_and_are_not_searched_again(self):
        self.provider.questions = 2
        first = self.start()["research"]
        self.assertEqual(first["status"], "waiting_source")
        self.assertEqual(self.discovery.calls, 1)
        self.clock.advance(5)
        final = self.resume()["research"]
        self.assertEqual(final["status"], "compiled")
        self.assertEqual((self.provider.calls, self.discovery.calls), (2, 2))
        self.assertEqual(ResearchDiscoveryAttempt.objects.count(), 2)

    def test_crash_after_capture_adopts_exact_work_after_restart_without_get(self):
        original = capture.observe_capture
        with patch.object(capture, "observe_capture", side_effect=RuntimeError("recorded interruption")):
            with self.assertRaises(RuntimeError):
                self.start()
        self.assertEqual(self.discovery.calls, 1)
        self.clock.advance(100)
        final = self.resume()["research"]
        self.assertEqual(final["status"], "compiled")
        self.assertEqual((self.provider.calls, self.discovery.calls), (2, 1))
        self.assertEqual(ResearchDiscoveryAttempt.objects.count(), 1)

    def test_uncertain_source_can_retry_after_original_disposition_is_saved(self):
        with patch.object(RecoveryDiscovery, "__call__", side_effect=RuntimeError("transport interruption")):
            with self.assertRaises(RuntimeError):
                self.start()
        self.clock.advance(26)
        first = self.resume()["research"]
        self.assertEqual(first["status"], "waiting_source")
        self.assertEqual(first["discoveries"][0]["status"], "outcome_unknown")
        self.assertEqual(ResearchDiscoveryAttempt.objects.count(), 1)
        self.clock.advance(31)
        final = self.resume()["research"]
        self.assertEqual(final["status"], "compiled")
        self.assertEqual(ResearchDiscoveryAttempt.objects.count(), 2)
        self.assertEqual(self.provider.calls, 2)

    def test_no_unadmitted_paid_plan_after_source_budget_expires(self):
        with patch.object(investigation, "continue_research", side_effect=RuntimeError("before plan")):
            with self.assertRaises(RuntimeError):
                self.start()
        self.clock.advance(1801)
        final = self.resume()["research"]
        self.assertEqual(final["status"], "source_deadline")
        self.assertEqual((self.provider.calls, self.discovery.calls), (0, 0))

    def test_dispatch_wait_cannot_use_an_expired_in_memory_transport_reservation(self):
        from macro_agent.desk import investigation_recovery
        original = investigation_recovery._admit

        def paused(*args, **kwargs):
            value = original(*args, **kwargs)
            if value:
                self.clock.advance(6)
            return value

        with patch.object(investigation_recovery, "_admit", side_effect=paused):
            first = self.start()["research"]
        self.assertEqual(first["status"], "waiting_source")
        self.assertEqual(first["discoveries"][0]["status"], "outcome_unknown")
        self.assertEqual(first["discoveries"][0]["stop_reason"], "capture_admission_expired")
        self.assertEqual(self.discovery.calls, 0)
        self.assertEqual(self.provider.calls, 1)

    def test_late_old_rate_limit_extends_floor_without_releasing_new_exchange(self):
        from macro_agent.desk import investigation_recovery
        with patch.object(investigation, "_finish_discovery", side_effect=RuntimeError("pause after admission")):
            with self.assertRaises(RuntimeError):
                self.start()
        old = ResearchDiscoveryAttempt.objects.get()
        self.clock.advance(56)
        due = self.clock.at + timedelta(seconds=120)
        self.command = str(uuid4())

        def late_response(query, *, clock):
            active = ResearchSourceState.objects.get().active_capture_id
            self.assertNotEqual(active, old.capture_id)
            investigation_recovery.record_result(old, old.capture, "failed",
                {"retry_after_seconds": 120}, "rate_limited", clock=clock)
            root = ResearchSourceState.objects.get()
            self.assertEqual(root.active_capture_id, active)
            self.assertEqual(root.next_request_at, due)
            return self.discovery(query, clock=clock)

        final = investigation.start_research(self.actor, self.command, QUESTION, "nanogpt", MODEL,
            source_recovery=True, provider=self.provider, discovery=late_response, clock=self.clock)["research"]
        self.assertEqual(final["status"], "compiled")
        root = ResearchSourceState.objects.get()
        self.assertIsNone(root.active_capture_id)
        self.assertEqual(root.next_request_at, due)
        self.assertEqual(self.discovery.calls, 1)

    def test_database_rejects_shortening_shared_cooldown(self):
        self.discovery.fail = SourceError("rate_limited", retry_after_seconds=120)
        self.start()
        with self.assertRaises(IntegrityError), transaction.atomic():
            root = ResearchSourceState.objects.select_for_update().get()
            root.next_request_at = self.clock.at
            root.generation += 1
            root.save(update_fields=("next_request_at", "generation"))

    def _withdraw(self, source):
        staff = get_user_model().objects.create_user(username="recovery-permission-staff", is_staff=True)
        permissions.set_source_permission(str(staff.pk), source.pk, source.contract_digest, False,
            "Recorded research permission withdrawal.", clock=self.clock)

    def test_permission_withdrawal_after_failed_attempt_stops_reads_and_continuation_visibly(self):
        self.discovery.fail = SourceError("timeout")
        first = self.start()["research"]
        self._withdraw(SourceState.objects.get())
        self.clock.advance(31)
        read = investigation.get_research(self.actor, first["id"], clock=self.clock)["research"]
        self.assertEqual(read["status"], "discovery_failed")
        self.assertEqual(read["source_stop_reason"], "source_permission_withdrawn")
        self.assertEqual(read["discoveries"], first["discoveries"])
        self.assertEqual(self.resume()["research"]["status"], "discovery_failed")
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 1))

    def test_withdrawn_captured_query_stops_remaining_query_search(self):
        self.provider.questions = 2
        first = self.start()["research"]
        captured = ResearchDiscoveryAttempt.objects.get()
        self._withdraw(SourceState.objects.get(pk=captured.source_id))
        self.clock.advance(5)
        final = self.resume()["research"]
        self.assertEqual(final["status"], "discovery_failed")
        self.assertEqual(final["source_stop_reason"], "source_permission_withdrawn")
        self.assertEqual(final["discoveries"], first["discoveries"])
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 1))

    def test_permission_race_at_protected_admission_uses_safe_conflict(self):
        from macro_agent.desk import investigation_recovery
        self.provider.questions = 2
        self.start()
        captured = ResearchDiscoveryAttempt.objects.get()
        self.clock.advance(5)
        self._withdraw(SourceState.objects.get(pk=captured.source_id))
        run = ResearchRun.objects.get()
        question = investigation.ResearchPlanResult.objects.get().document["questions"][1]
        with self.assertRaisesMessage(service.ThesisConflict, "permission was withdrawn"):
            investigation_recovery._admit(run, 1, question, clock=self.clock)
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 1))

    def test_permission_withdrawn_during_source_response_is_a_safe_conflict_with_retained_receipt(self):
        def withdrawal_during_response(query, *, clock):
            result = self.discovery(query, clock=clock)
            self._withdraw(SourceState.objects.get())
            return result

        with self.assertRaisesMessage(service.ThesisConflict, "permission was withdrawn"):
            investigation.start_research(self.actor, self.command, QUESTION, "nanogpt", MODEL,
                source_recovery=True, provider=self.provider, discovery=withdrawal_during_response,
                clock=self.clock)
        run = ResearchRun.objects.get()
        read = investigation.get_research(self.actor, str(run.pk), clock=self.clock)["research"]
        self.assertEqual(read["status"], "discovery_failed")
        self.assertEqual(read["source_stop_reason"], "source_permission_withdrawn")
        self.assertEqual(ResearchDiscoveryReceipt.objects.count(), 1)
        self.assertEqual(ResearchDiscoveryResult.objects.count(), 0)
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 1))
        self.assertEqual(self.resume()["research"]["status"], "discovery_failed")

    def test_withdrawal_during_rate_limit_keeps_safe_provider_cooldown_for_other_runs(self):
        def withdrawal_then_rate_limit(query, *, clock):
            self._withdraw(SourceState.objects.get())
            raise SourceError("rate_limited", retry_after_seconds=120)

        with self.assertRaisesMessage(service.ThesisConflict, "permission was withdrawn"):
            investigation.start_research(self.actor, self.command, QUESTION, "nanogpt", MODEL,
                source_recovery=True, provider=self.provider, discovery=withdrawal_then_rate_limit,
                clock=self.clock)
        run = ResearchRun.objects.get()
        saved = ResearchDiscoveryResult.objects.get()
        self.assertEqual(saved.status, "failed")
        self.assertEqual(saved.stop_reason, "rate_limited")
        self.assertEqual(saved.metadata["retry_after_seconds"], 120)
        self.assertEqual(saved.revision_ids, [])
        self.assertEqual(ResearchDiscoveryReceipt.objects.count(), 0)
        self.assertEqual(ResearchSourceState.objects.get().next_request_at,
            self.clock.at + timedelta(seconds=120))
        self.assertIsNone(ResearchSourceState.objects.get().active_capture_id)
        read = investigation.get_research(self.actor, str(run.pk), clock=self.clock)["research"]
        self.assertEqual(read["source_stop_reason"], "source_permission_withdrawn")
        self.clock.advance(56)
        self.command = str(uuid4())
        other = self.start()["research"]
        self.assertEqual(other["status"], "waiting_source")
        self.assertEqual(self.discovery.calls, 0)
        self.assertEqual(ResearchDiscoveryAttempt.objects.count(), 1)
        self.assertEqual(CompilationAttempt.objects.count(), 0)

    def test_database_rejects_wrong_capture_binding_and_unordered_retry(self):
        self.discovery.fail = SourceError("timeout")
        self.start()
        first = ResearchDiscoveryAttempt.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchDiscoveryAttempt.objects.create(run=first.run, question_index=0,
                attempt_number=2, question=first.question, source_id=first.source_id,
                contract=first.contract, admitted_at=self.clock.at, capture=first.capture)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchRun.objects.filter(pk=first.run_id).update(execution_policy={})

    def test_concurrent_continuations_admit_one_source_retry_and_one_compilation(self):
        self.discovery.fail = SourceError("timeout")
        self.start()
        self.clock.advance(31)
        self.discovery.fail = None
        run_id = str(ResearchRun.objects.get().pk)

        def worker():
            close_old_connections()
            try:
                return investigation.continue_research(self.actor, run_id, provider=self.provider,
                    discovery=self.discovery, clock=self.clock)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(self.discovery.calls, 2)
        self.assertEqual(self.provider.calls, 2)
        self.assertEqual(CompilationAttempt.objects.count(), 1)
        self.assertTrue(any(value["research"]["status"] == "compiled" for value in values))
