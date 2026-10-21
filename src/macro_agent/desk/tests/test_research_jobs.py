"""Background continuation proves consent, fencing, recovery and exact lineage."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, transaction
from django.test import TransactionTestCase, override_settings

from macro_agent.desk import investigation, investigation_recovery, research_jobs
from macro_agent.desk.investigation_models import ResearchDiscoveryAttempt, ResearchPlanAttempt, ResearchRun
from macro_agent.desk.research_job_models import ResearchJob, ResearchJobAdmission, ResearchJobLease, ResearchJobOutcome
from macro_agent.monitoring import capture
from macro_agent.monitoring.sources import SourceError
from macro_agent.theses import compilation, service
from macro_agent.theses.models import CompilationAttempt, CompilationBudget
from .test_investigation import MODEL, QUESTION, ResearchProvider
from .test_source_recovery import Clock, RecoveryDiscovery


@override_settings(MACRO_ENABLE_RESEARCH_DISCOVERY=True, MACRO_ENABLE_RESEARCH_BACKGROUND=True,
    MACRO_ENABLE_MONITORING_PROOF=True, MACRO_ALLOW_SYNTHETIC_SETUP=True,
    MACRO_ENABLE_MODEL_COMPILATION=True, MACRO_MODEL_PROVIDER="nanogpt",
    MACRO_MODEL_API_KEY="recorded-research-key", SETTINGS_MODULE="macro_agent.web.local_settings")
class ResearchJobTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="research-worker-owner")
        self.other = get_user_model().objects.create_user(username="research-worker-other")
        self.actor, self.command = str(self.owner.pk), str(uuid4())
        self.clock, self.provider, self.discovery = Clock(), ResearchProvider(questions=1), RecoveryDiscovery()
        self.discovery.fail = SourceError("rate_limited", retry_after_seconds=40)
        CompilationBudget.objects.get_or_create(pk=1)
        self.run = investigation.start_research(self.actor, self.command, QUESTION, "nanogpt", MODEL,
            source_recovery=True, provider=self.provider, discovery=self.discovery, clock=self.clock)["research"]
        self.enrollment_command = str(uuid4())

    def enroll(self):
        return research_jobs.enroll(self.actor, self.run["id"], self.enrollment_command,
            self.run["request_digest"], clock=self.clock)

    def tick(self):
        return research_jobs.run_tick(self.actor, self.run["id"], provider=self.provider,
            discovery=self.discovery, clock=self.clock)

    def due(self):
        self.clock.advance(40)
        self.discovery.fail = None

    def test_background_resume_retains_exact_plan_and_admission_provenance(self):
        enrolled = self.enroll()["job"]
        self.assertEqual(enrolled["policy"], research_jobs.POLICY)
        self.assertEqual(enrolled["status"], "pending")
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 1))
        self.tick()
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 1))
        self.due()
        # Both admissions share the fixture clock. Reverse UUID order must not
        # place compilation ahead of the source evidence it consumed.
        identities = [UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
            UUID("00000000-0000-0000-0000-000000000001")]
        with patch.object(ResearchJobAdmission._meta.get_field("id"), "_get_default", side_effect=identities):
            result = self.tick()["job"]
        self.assertEqual((result["status"], result["last_stop_reason"]), ("completed", "compiled"))
        self.assertEqual((self.provider.calls, self.discovery.calls), (2, 2))
        self.assertEqual(ResearchPlanAttempt.objects.count(), 1)
        self.assertEqual(CompilationAttempt.objects.count(), 1)
        self.assertEqual([item["kind"] for item in result["leases"][0]["admissions"]], ["source", "compilation"])
        self.assertEqual(ResearchJobAdmission.objects.count(), 2)
        self.tick()
        self.assertEqual((self.provider.calls, self.discovery.calls), (2, 2))

    def test_enrollment_and_command_retry_never_require_credentials_or_advance(self):
        self.enroll()
        self.due()
        with override_settings(MACRO_MODEL_API_KEY="", SETTINGS_MODULE="macro_agent.web.local_settings"):
            self.assertTrue(self.enroll()["replayed"])
            self.assertEqual(research_jobs.inspect_job(self.actor, self.run["id"])["job"]["status"], "pending")
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 1))

    def test_wrong_digest_and_other_owner_have_no_job_authority(self):
        with self.assertRaises(service.ThesisConflict):
            research_jobs.enroll(self.actor, self.run["id"], str(uuid4()), "0" * 64, clock=self.clock)
        self.enroll()
        with self.assertRaises(service.ThesisUnavailable):
            research_jobs.inspect_job(str(self.other.pk), self.run["id"])
        with self.assertRaises(service.ThesisUnavailable):
            research_jobs.revoke(str(self.other.pk), self.run["id"], str(uuid4()))

    def test_revoke_is_one_way_and_readable_when_execution_disabled(self):
        self.enroll()
        command = str(uuid4())
        with override_settings(MACRO_ENABLE_RESEARCH_BACKGROUND=False, MACRO_MODEL_API_KEY="",
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            result = research_jobs.revoke(self.actor, self.run["id"], command, clock=self.clock)
            self.assertEqual(result["job"]["status"], "revoked")
            self.assertTrue(research_jobs.revoke(self.actor, self.run["id"], command, clock=self.clock)["replayed"])
            self.assertEqual(research_jobs.inspect_job(self.actor, self.run["id"])["job"]["status"], "revoked")
            with self.assertRaises(compilation.CompilationDisabled):
                self.tick()
        self.due()
        self.tick()
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 1))
        with self.assertRaises(service.ThesisConflict):
            research_jobs.enroll(self.actor, self.run["id"], str(uuid4()), self.run["request_digest"])

    def test_background_cannot_plan_without_existing_planned_result(self):
        with patch.object(investigation, "_plan"):
            unplanned = investigation.start_research(self.actor, str(uuid4()), QUESTION + "Second", "nanogpt", MODEL,
                source_recovery=True, provider=self.provider, discovery=self.discovery, clock=self.clock)["research"]
        with self.assertRaises(service.ThesisConflict):
            research_jobs.enroll(self.actor, unplanned["id"], str(uuid4()), unplanned["request_digest"], clock=self.clock)
        with self.assertRaises(service.ThesisConflict):
            investigation.continue_research(self.actor, unplanned["id"], provider=self.provider,
                discovery=self.discovery, clock=self.clock, research_job_token=str(uuid4()))
        self.assertEqual(self.provider.calls, 1)

    def test_configuration_change_stops_before_new_source_request(self):
        self.enroll()
        self.due()
        with override_settings(MACRO_COMPILATION_MAX_OUTPUT_TOKENS=129,
                               SETTINGS_MODULE="macro_agent.web.local_settings"):
            result = self.tick()["job"]
        self.assertEqual(result["status"], "blocked")
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 1))

    def test_expiry_between_source_admission_and_get_dispatch_prevents_get(self):
        self.enroll()
        self.due()
        original = investigation_recovery._admit
        def delayed(*args, **kwargs):
            value = original(*args, **kwargs)
            self.clock.advance(181)
            return value
        with patch.object(investigation_recovery, "_admit", side_effect=delayed):
            self.tick()
        self.assertEqual(self.discovery.calls, 1)
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(ResearchJobOutcome.objects.get().status, "expired")

    def test_source_admission_clock_is_sampled_after_job_protection(self):
        self.enroll()
        self.due()
        lease = research_jobs._claim(self.actor, self.run["id"], clock=self.clock)
        run = ResearchRun.objects.get(pk=self.run["id"])
        question = run.plan_attempt.result.document["questions"][0]
        protected = []
        original = research_jobs._job
        def observed_job(*args, **kwargs):
            value = original(*args, **kwargs)
            if kwargs.get("lock"):
                protected.append(value.pk)
            return value
        def observed_clock():
            self.assertTrue(protected, "Admission sampled time before acquiring the job lock")
            return self.clock()
        with patch.object(research_jobs, "_job", side_effect=observed_job):
            admitted = investigation_recovery._admit(run, 0, question,
                clock=observed_clock, research_job_token=str(lease.pk))
        self.assertIsNotNone(admitted)

    def test_flag_disable_between_admission_and_dispatch_prevents_get(self):
        self.enroll()
        self.due()
        original = investigation_recovery._admit
        flag = override_settings(MACRO_ENABLE_RESEARCH_BACKGROUND=False)
        def disabled(*args, **kwargs):
            value = original(*args, **kwargs)
            flag.enable()
            return value
        try:
            with patch.object(investigation_recovery, "_admit", side_effect=disabled):
                result = self.tick()["job"]
        finally:
            flag.disable()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.discovery.calls, 1)

    def test_revoke_during_catalogue_blocks_compilation_admission(self):
        self.enroll()
        self.due()
        original = self.provider.list_models
        def revoked():
            result = original()
            research_jobs.revoke(self.actor, self.run["id"], str(uuid4()), clock=self.clock)
            return result
        with patch.object(self.provider, "list_models", side_effect=revoked):
            result = self.tick()["job"]
        self.assertEqual(result["status"], "revoked")
        self.assertEqual(CompilationAttempt.objects.count(), 0)
        self.assertEqual(self.provider.calls, 1)

    def test_expiry_during_catalogue_blocks_compilation_admission(self):
        self.enroll()
        self.due()
        original = self.provider.list_models
        def delayed():
            result = original()
            self.clock.advance(181)
            return result
        with patch.object(self.provider, "list_models", side_effect=delayed):
            self.tick()
        self.assertEqual(CompilationAttempt.objects.count(), 0)
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(ResearchJobOutcome.objects.get().status, "expired")

    def test_restart_after_model_admission_never_resends_paid_call(self):
        self.enroll()
        self.due()
        def interrupted(model, messages):
            raise RuntimeError("simulated process exit after durable admission")
        with patch.object(self.provider, "complete", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.tick()
        self.assertEqual(CompilationAttempt.objects.count(), 1)
        self.clock.advance(181)
        result = self.tick()["job"]
        self.assertEqual(result["last_stop_reason"], "compile_uncertain")
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 2))
        self.tick()
        self.assertEqual(CompilationAttempt.objects.count(), 1)

    def test_expiry_after_compilation_commit_prevents_first_model_dispatch(self):
        self.enroll()
        self.due()
        original = research_jobs.record_admission
        def delayed(*args, **kwargs):
            result = original(*args, **kwargs)
            if kwargs.get("compilation_attempt") is not None:
                self.clock.advance(181)
            return result
        with patch.object(research_jobs, "record_admission", side_effect=delayed):
            self.tick()
        self.assertEqual(CompilationAttempt.objects.count(), 1)
        self.assertEqual(self.provider.calls, 1)

    def test_restart_adopts_committed_capture_after_worker_lease_expiry(self):
        self.enroll()
        self.due()
        with patch.object(capture, "observe_capture", side_effect=RuntimeError("simulated capture interruption")):
            with self.assertRaises(RuntimeError):
                self.tick()
        self.assertEqual(self.discovery.calls, 2)
        self.clock.advance(181)
        result = self.tick()["job"]
        self.assertEqual(result["status"], "completed")
        self.assertEqual((self.provider.calls, self.discovery.calls), (2, 2))
        self.assertEqual([item["outcome"]["status"] for item in result["leases"]], ["expired", "completed"])

    def test_late_old_worker_finish_cannot_replace_new_lease(self):
        self.enroll()
        self.due()
        first = research_jobs._claim(self.actor, self.run["id"], clock=self.clock)
        self.clock.advance(181)
        second = research_jobs._claim(self.actor, self.run["id"], clock=self.clock)
        result = research_jobs._finish(self.actor, self.run["id"], first.pk, clock=self.clock)["job"]
        self.assertEqual(result["active_token"], str(second.pk))
        self.assertEqual(result["status"], "running")

    def test_expired_outcome_can_be_retired_by_later_revocation(self):
        self.enroll()
        self.due()
        lease = research_jobs._claim(self.actor, self.run["id"], clock=self.clock)
        self.clock.advance(181)
        research_jobs._finish(self.actor, self.run["id"], lease.pk, clock=self.clock)
        result = research_jobs.revoke(self.actor, self.run["id"], str(uuid4()), clock=self.clock)["job"]
        self.assertEqual(result["status"], "revoked")
        self.assertEqual(result["leases"][0]["outcome"]["status"], "expired")

    def test_twelve_crashed_leases_retain_complete_history_then_stop(self):
        self.due()
        with patch.object(compilation, "compile_thesis"):
            investigation.continue_research(self.actor, self.run["id"], provider=self.provider,
                discovery=self.discovery, clock=self.clock)
        self.enroll()
        for _ in range(12):
            self.assertIsNotNone(research_jobs._claim(self.actor, self.run["id"], clock=self.clock))
            self.clock.advance(181)
        self.assertIsNone(research_jobs._claim(self.actor, self.run["id"], clock=self.clock))
        result = research_jobs.inspect_job(self.actor, self.run["id"])["job"]
        self.assertEqual((result["status"], result["last_stop_reason"]), ("blocked", "background_lease_limit_reached"))
        self.assertEqual(len(result["leases"]), 12)
        self.assertTrue(all(item["outcome"]["status"] == "expired" for item in result["leases"]))
        self.assertEqual((self.provider.calls, self.discovery.calls), (1, 2))

    def test_concurrent_workers_claim_only_one_exact_run(self):
        self.enroll()
        self.due()
        def claim():
            close_old_connections()
            try:
                lease = research_jobs._claim(self.actor, self.run["id"], clock=self.clock)
                return str(lease.pk) if lease else None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual(ResearchJobLease.objects.count(), 1)

    def test_independent_connection_revocation_while_catalogue_waits(self):
        self.enroll()
        self.due()
        entered, released = Event(), Event()
        original = self.provider.list_models
        def blocked_catalogue():
            result = original()
            entered.set()
            self.assertTrue(released.wait(10))
            return result
        def run():
            close_old_connections()
            try:
                return self.tick()
            finally:
                close_old_connections()
        with patch.object(self.provider, "list_models", side_effect=blocked_catalogue):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(run)
                self.assertTrue(entered.wait(10))
                research_jobs.revoke(self.actor, self.run["id"], str(uuid4()), clock=self.clock)
                released.set()
                result = future.result(timeout=10)["job"]
        self.assertEqual(result["status"], "revoked")
        self.assertEqual(CompilationAttempt.objects.count(), 0)

    def test_raw_mutation_rejects_scope_pins_history_and_terminal_reactivation(self):
        self.enroll()
        job = ResearchJob.objects.get()
        for values in ({"owner_id": self.other.pk}, {"model_id": "different/model"}, {"policy": {}},
                       {"status": "running", "active_token": uuid4()}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                ResearchJob.objects.filter(pk=job.pk).update(**values)
        self.due()
        lease = research_jobs._claim(self.actor, self.run["id"], clock=self.clock)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchJob.objects.filter(pk=job.pk).update(status="pending", active_token=None, lease_deadline_at=None)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchJobLease.objects.filter(pk=lease.pk).update(sequence=2)
        research_jobs.revoke(self.actor, self.run["id"], str(uuid4()), clock=self.clock)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchJob.objects.filter(pk=job.pk).update(status="pending", next_due_at=self.clock())

    def test_foreign_source_admission_cannot_be_linked_to_lease(self):
        self.enroll()
        self.due()
        lease = research_jobs._claim(self.actor, self.run["id"], clock=self.clock)
        previous = ResearchDiscoveryAttempt.objects.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResearchJobAdmission.objects.create(lease=lease, source_attempt=previous, admitted_at=self.clock())

    def test_repeated_source_failure_saves_actual_cooldown_due(self):
        self.enroll()
        self.clock.advance(40)
        self.discovery.fail = SourceError("rate_limited", retry_after_seconds=120)
        result = self.tick()["job"]
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["next_due_at"], (self.clock.at + timedelta(seconds=120)).isoformat())
        self.tick()
        self.assertEqual(self.discovery.calls, 2)
