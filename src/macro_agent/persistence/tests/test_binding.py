"""PostgreSQL evidence for committed context admission and publication ordering."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
from uuid import UUID, uuid4
import sys

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, connections, transaction
from django.test import RequestFactory, TransactionTestCase, override_settings

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools"))
from domain_fixture import fixture_case

from macro_agent.application.publication import publish
from macro_agent.domain.exposure import DECLARATION_FIELDS
from macro_agent.domain.models import ContextSnapshot, canonical_json, text_digest
from macro_agent.persistence.context_binding import (
    CONTEXT_ROLES, ContextPending, enroll_synthetic, invalidate_thesis_briefs, refresh_context,
)
from macro_agent.persistence.models import (
    AuditTransition, BriefStateRecord, ContextAdmission, CurrentAssessment, DependencyVersion,
    NotificationIntent, ReassessmentWork, ThesisBriefBinding,
)
from macro_agent.persistence.publication_store import DjangoPublicationStore
from macro_agent.positions import service as positions
from macro_agent.theses import service as theses
from macro_agent.theses.models import ApprovalRecord, ThesisRecord


def isolated(function, *args):
    connections.close_all()
    try:
        return function(*args)
    finally:
        connections.close_all()


@override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=True)
class PostgreSQLBindingTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("binding evidence requires PostgreSQL")
        self.owner = get_user_model().objects.create_user(username="binding-owner")
        self.other = get_user_model().objects.create_user(username="binding-other")
        self.actor = str(self.owner.pk)
        self.at = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)
        self.meaning = {"drivers": ["Real yields"], "horizon": None,
                        "invalidation_signposts": ["Sustained real-yield rise"]}
        self.created = theses.create_thesis(self.actor, str(uuid4()), "  exact thesis\r\n", self.meaning,
                                            clock=lambda: self.at)
        self.thesis_id = self.created["thesis"]["id"]
        self.approved = self.approve(self.created, 1)
        self.approval_id = self.approved["command"]["result"]["approval_id"]
        self.base, dependencies = fixture_case(owner_id=self.actor)
        self.fixtures = tuple(pin for pin in dependencies if pin.role not in CONTEXT_ROLES)
        self.brief_id = "bound-fixture-brief"
        self.store = DjangoPublicationStore(self.actor)

    def approve(self, previous, seconds):
        row = previous["thesis"]
        draft = row["draft"]
        return theses.approve_thesis(
            self.actor, self.thesis_id, str(uuid4()), draft["text_version"]["id"],
            draft["text_version"]["text_digest"], draft["interpretation"]["id"],
            draft["interpretation"]["digest"], row["revision"],
            clock=lambda: self.at + timedelta(seconds=seconds))

    def enroll(self, *, seconds=2, brief_id=None):
        return enroll_synthetic(self.actor, self.thesis_id, brief_id or self.brief_id,
                                self.approval_id, self.fixtures, synthetic=True,
                                clock=lambda: self.at + timedelta(seconds=seconds))

    def candidate(self, *, seconds=3, assessment_id="bound-first"):
        with self.store.transaction(self.brief_id) as tx:
            state = tx.state()
        return replace(self.base, assessment_id=assessment_id, run_id="run:" + assessment_id,
                       brief_id=self.brief_id, expected_generation=state.generation,
                       snapshot=ContextSnapshot("snapshot:" + assessment_id,
                                                self.at + timedelta(seconds=seconds), state.dependencies))

    def revise_thesis(self, *, seconds=4):
        current = theses.get_thesis(self.actor, self.thesis_id)
        return theses.propose_thesis(self.actor, self.thesis_id, str(uuid4()), "Revised exact thesis",
                                     self.meaning, current["revision"],
                                     clock=lambda: self.at + timedelta(seconds=seconds))

    def paper_position(self, *, seconds=4):
        declaration = {field: None for field in DECLARATION_FIELDS}
        declaration.update(underlying="XAU", direction="long", quantity="2.00", quantity_unit="units")
        return positions.create_position(self.actor, self.thesis_id, str(uuid4()), self.approval_id,
                                          declaration, clock=lambda: self.at + timedelta(seconds=seconds))

    def assert_wait(self, waiter, blocker):
        deadline, observed = monotonic() + 5, None
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT state, wait_event_type, query, pg_blocking_pids(pid) "
                               "FROM pg_stat_activity WHERE pid=%s", [waiter])
                observed = cursor.fetchone()
            if (observed and observed[0] == "active" and observed[1] == "Lock"
                    and "FOR UPDATE" in observed[2] and blocker in observed[3]):
                return
            sleep(0.01)
        self.fail(f"no actual PostgreSQL lock wait: {observed!r}")

    @contextmanager
    def db_guard(self, sqlstate):
        with self.assertRaises(DatabaseError) as raised:
            with transaction.atomic():
                yield
        self.assertEqual(raised.exception.__cause__.sqlstate, sqlstate)

    def test_admission_resolves_real_exact_approval_and_conservative_observation(self):
        result = self.enroll()
        admission = ContextAdmission.objects.get(pk=result["admission_id"])
        self.assertEqual(admission.resolved_inputs["text"]["exact_text"], "  exact thesis\r\n")
        self.assertEqual(admission.resolved_inputs["exposure"]["positions"], [])
        self.assertEqual(admission.input_observed_at, self.at + timedelta(seconds=2))
        self.assertNotEqual(admission.input_observed_at,
                            ApprovalRecord.objects.get(pk=self.approval_id).approved_at)
        meaning = self.approved["thesis"]["draft"]["interpretation"]
        self.assertEqual(admission.resolved_inputs["interpretation"]["digest"], meaning["digest"])
        pins = {item["role"]: item for item in result["pins"]}
        self.assertEqual(pins["compiled_thesis"]["digest"], meaning["digest"])
        self.assertEqual(pins["activation"]["version_id"], self.approval_id)
        report = self.store.inspect(self.brief_id)
        self.assertEqual(report["thesis_binding"]["status"], "ready")
        self.assertFalse(report["thesis_binding"]["commit_time_measured"])
        self.assertEqual(report["context_admissions"][0]["resolved_inputs"], admission.resolved_inputs)

    def test_outermost_transaction_gate_and_synthetic_scope(self):
        with transaction.atomic():
            with self.assertRaisesRegex(RuntimeError, "outermost"):
                self.enroll()
        with override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=False):
            with self.assertRaises(PermissionError):
                self.enroll()
        with self.assertRaises(ValueError):
            enroll_synthetic(self.actor, self.thesis_id, self.brief_id, self.approval_id,
                             self.fixtures[:-1], synthetic=True, clock=lambda: self.at)
        self.assertEqual(BriefStateRecord.objects.count(), 0)

    def test_foreign_missing_and_existing_unbound_brief_cannot_enroll(self):
        with self.assertRaises(PermissionError):
            enroll_synthetic(str(self.other.pk), self.thesis_id, self.brief_id,
                             self.approval_id, self.fixtures, synthetic=True)
        self.store.bootstrap_synthetic(self.base.brief_id, self.base.snapshot.dependencies,
                                        self.base.snapshot.cutoff, synthetic=True)
        with self.assertRaises(PermissionError):
            self.enroll(brief_id=self.base.brief_id)
        self.assertEqual(ThesisBriefBinding.objects.count(), 0)

    def test_exact_retry_preserves_pins_and_no_extra_history(self):
        original = self.enroll()
        retry = self.enroll(seconds=3)
        self.assertTrue(retry["replayed"])
        self.assertEqual(original["pins"], retry["pins"])
        self.assertEqual(ContextAdmission.objects.count(), 1)
        self.assertEqual(DependencyVersion.objects.count(), 16)
        self.assertEqual(AuditTransition.objects.count(), 1)

    def test_proposal_keeps_approved_publication_context(self):
        self.enroll()
        candidate = self.candidate()
        self.revise_thesis()
        self.assertEqual(ThesisBriefBinding.objects.get().status, "ready")
        self.assertEqual(publish(self.store, candidate, self.at + timedelta(seconds=5)).status, "current")

    def test_new_approval_cancels_pending_delivery_and_old_admission_cannot_restore(self):
        self.enroll()
        candidate = self.candidate()
        publish(self.store, candidate, self.at + timedelta(seconds=3))
        proposed = self.revise_thesis()
        new = self.approve(proposed, 5)
        self.assertEqual(ThesisBriefBinding.objects.get().status, "pending")
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertEqual(NotificationIntent.objects.get().state, "canceled")
        with self.assertRaises(ContextPending):
            publish(self.store, candidate, self.at + timedelta(seconds=6))
        with self.assertRaises(ContextPending):
            refresh_context(self.actor, self.thesis_id, self.approval_id,
                            clock=lambda: self.at + timedelta(seconds=6))
        current_id = new["command"]["result"]["approval_id"]
        refreshed = refresh_context(self.actor, self.thesis_id, current_id,
                                    clock=lambda: self.at + timedelta(seconds=6))
        self.assertEqual(refreshed["briefs"][0]["status"], "ready")
        self.assertEqual(publish(self.store, candidate, self.at + timedelta(seconds=7)).status, "superseded")
        self.assertEqual(NotificationIntent.objects.get().state, "canceled")

    def test_full_paper_book_including_closed_versions_controls_exposure_pin(self):
        self.enroll()
        paper = self.paper_position()
        self.assertEqual(ThesisBriefBinding.objects.get().status, "pending")
        refresh_context(self.actor, self.thesis_id, self.approval_id,
                        clock=lambda: self.at + timedelta(seconds=5))
        first = ContextAdmission.objects.order_by("input_observed_at").last()
        self.assertEqual(first.resolved_inputs["exposure"]["positions"][0]["payload"]["quantity"], "2.00")
        positions.close_position(self.actor, paper["position"]["id"], str(uuid4()),
                                 paper["position"]["revision"], self.approval_id,
                                 clock=lambda: self.at + timedelta(seconds=6))
        refresh_context(self.actor, self.thesis_id, self.approval_id,
                        clock=lambda: self.at + timedelta(seconds=7))
        latest = ContextAdmission.objects.order_by("input_observed_at").last()
        self.assertNotEqual(first.exposure_digest, latest.exposure_digest)
        self.assertEqual(latest.resolved_inputs["exposure"]["positions"][0]["payload"]["status"], "closed")
        self.assertEqual(latest.exposure_digest,
                         text_digest(canonical_json(latest.resolved_inputs["exposure"])))

    def test_bound_exposure_cannot_be_advanced_using_fixture_override(self):
        self.enroll()
        with self.store.transaction(self.brief_id) as tx:
            previous = next(pin for pin in tx.state().dependencies if pin.role == "exposure")
        with self.assertRaises(PermissionError):
            self.store.advance_evidence(self.brief_id, previous, previous,
                                        self.at + timedelta(seconds=3))

    def test_admission_audit_failure_rolls_back_binding_heads_and_all_history(self):
        with patch.object(AuditTransition.objects, "using") as using:
            using.return_value.create.side_effect = RuntimeError("injected audit failure")
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.enroll()
        self.assertEqual(BriefStateRecord.objects.count(), 0)
        self.assertEqual(ThesisBriefBinding.objects.count(), 0)
        self.assertEqual(ContextAdmission.objects.count(), 0)
        self.assertEqual(DependencyVersion.objects.count(), 0)
        self.assertEqual(ReassessmentWork.objects.count(), 0)

    def test_approval_invalidation_failure_rolls_back_approval_and_two_briefs(self):
        self.enroll()
        self.enroll(brief_id="bound-second")
        proposed = self.revise_thesis()
        original_audit = AuditTransition.objects.using
        calls = [0]
        def wrapped(using):
            manager = original_audit(using)
            real_create = manager.create
            def create(*args, **kwargs):
                if kwargs.get("kind") == "context_pending":
                    calls[0] += 1
                    if calls[0] == 2:
                        raise RuntimeError("second brief failure")
                return real_create(*args, **kwargs)
            manager.create = create
            return manager
        with patch.object(AuditTransition.objects, "using", side_effect=wrapped):
            with self.assertRaisesRegex(RuntimeError, "second brief"):
                self.approve(proposed, 5)
        self.assertEqual(ApprovalRecord.objects.count(), 1)
        self.assertEqual(ThesisRecord.objects.get().current_approval_id, UUID(self.approval_id))
        self.assertEqual(set(ThesisBriefBinding.objects.values_list("status", flat=True)), {"ready"})
        self.assertEqual(AuditTransition.objects.filter(kind="context_pending").count(), 0)

    def test_database_owner_scope_history_and_identity_guards(self):
        self.enroll()
        binding, admission = ThesisBriefBinding.objects.get(), ContextAdmission.objects.get()
        with self.db_guard("23514"):
            ThesisBriefBinding.objects.filter(pk=binding.pk).update(owner=self.other)
        with self.db_guard("23514"):
            ContextAdmission.objects.filter(pk=admission.pk).update(input_digest="a" * 64)
        foreign = theses.create_thesis(str(self.other.pk), str(uuid4()), "foreign", self.meaning,
                                       clock=lambda: self.at)
        with self.db_guard("23503"):
            BriefStateRecord.objects.create(brief_id="bad-binding", owner=self.owner,
                                             changed_at=self.at)
            ThesisBriefBinding.objects.create(brief_id="bad-binding", owner=self.owner,
                                               thesis_id=foreign["thesis"]["id"],
                                               created_at=self.at, status="pending")

    def test_bound_admin_is_owner_scoped_and_read_only(self):
        self.enroll()
        factory = RequestFactory()
        self.owner.is_staff = self.owner.is_superuser = True
        self.owner.save(update_fields=("is_staff", "is_superuser"))
        self.other.is_staff = self.other.is_superuser = True
        self.other.save(update_fields=("is_staff", "is_superuser"))
        for model in (ThesisBriefBinding, ContextAdmission):
            model_admin = admin.site._registry[model]
            request = factory.get("/admin/")
            request.user = self.owner
            self.assertEqual(model_admin.get_queryset(request).count(), 1)
            self.assertFalse(model_admin.has_change_permission(request, model.objects.get()))
            self.assertFalse(model_admin.has_add_permission(request))
            request.user = self.other
            self.assertEqual(model_admin.get_queryset(request).count(), 0)
            self.assertFalse(model_admin.has_view_permission(request, model.objects.get()))

    def test_admission_waits_for_committed_approval_then_samples_clock(self):
        held, attempted, release, sampled = (Event() for _ in range(4))
        pids = {}
        proposed = self.revise_thesis(seconds=2)
        new_id = {}
        def approval_holder():
            with transaction.atomic():
                result = self.approve(proposed, 3)
                new_id["id"] = result["command"]["result"]["approval_id"]
                pids["blocker"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("approval not released")
        def admission_waiter():
            def observe(execute, sql, params, many, context):
                if "FOR UPDATE" in sql and get_user_model()._meta.db_table in sql:
                    pids["waiter"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                return execute(sql, params, many, context)
            def clock():
                sampled.set()
                self.assertTrue(release.is_set())
                return self.at + timedelta(seconds=4)
            with connection.execute_wrapper(observe):
                return enroll_synthetic(self.actor, self.thesis_id, self.brief_id, new_id["id"],
                                        self.fixtures, synthetic=True, clock=clock)
        with ThreadPoolExecutor(max_workers=2) as pool:
            holder = pool.submit(isolated, approval_holder)
            try:
                self.assertTrue(held.wait(10))
                waiter = pool.submit(isolated, admission_waiter)
                self.assertTrue(attempted.wait(10))
                self.assert_wait(pids["waiter"], pids["blocker"])
                self.assertFalse(sampled.is_set())
            finally:
                release.set()
            holder.result(timeout=15)
            result = waiter.result(timeout=15)
        self.assertEqual(ContextAdmission.objects.get().approval_id, UUID(new_id["id"]))
        self.assertTrue(sampled.is_set())
        self.assertEqual(result["input_observed_at"], (self.at + timedelta(seconds=4)).isoformat())

    def test_publication_first_blocks_approval_then_invalidation_cancels_notice(self):
        self.enroll()
        candidate = self.candidate()
        proposed = self.revise_thesis(seconds=4)
        held, attempted, release = Event(), Event(), Event()
        pids = {}
        @contextmanager
        def paused(brief_id):
            with self.store.transaction(brief_id) as tx:
                pids["blocker"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("publication not released")
                yield tx
        class Store:
            transaction = staticmethod(paused)
        def approval_waiter():
            def observe(execute, sql, params, many, context):
                if "FOR UPDATE" in sql and get_user_model()._meta.db_table in sql:
                    pids["waiter"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                return execute(sql, params, many, context)
            with connection.execute_wrapper(observe):
                return self.approve(proposed, 6)
        with ThreadPoolExecutor(max_workers=2) as pool:
            publisher = pool.submit(isolated, publish, Store(), candidate,
                                    self.at + timedelta(seconds=5))
            try:
                self.assertTrue(held.wait(10))
                approver = pool.submit(isolated, approval_waiter)
                self.assertTrue(attempted.wait(10))
                self.assert_wait(pids["waiter"], pids["blocker"])
            finally:
                release.set()
            self.assertEqual(publisher.result(timeout=15).status, "current")
            approver.result(timeout=15)
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertEqual(NotificationIntent.objects.get().state, "canceled")
        self.assertEqual(ThesisBriefBinding.objects.get().status, "pending")

    def test_same_text_reapproval_preserves_first_observation_and_historical_retry(self):
        self.enroll()
        first = {item["role"]: item for item in ContextAdmission.objects.get().pins}
        new = self.approve(self.approved, 4)
        current_id = new["command"]["result"]["approval_id"]
        refreshed = refresh_context(self.actor, self.thesis_id, current_id,
                                    clock=lambda: self.at + timedelta(seconds=5))
        pins = {item["role"]: item for item in refreshed["briefs"][0]["pins"]}
        self.assertEqual(pins["user_thesis"], first["user_thesis"])
        self.assertEqual(pins["compiled_thesis"], first["compiled_thesis"])
        self.assertNotEqual(pins["activation"], first["activation"])
        draft = self.created["thesis"]["draft"]
        result = theses.approve_thesis(
            self.actor, self.thesis_id, self.approved["command"]["command_id"],
            draft["text_version"]["id"], draft["text_version"]["text_digest"],
            draft["interpretation"]["id"], draft["interpretation"]["digest"],
            self.created["thesis"]["revision"], clock=lambda: self.at + timedelta(seconds=6))
        self.assertTrue(result["command"]["replayed"])
        self.assertFalse(result["command"]["is_current_approval"])
        self.assertEqual(ThesisBriefBinding.objects.get().status, "ready")
        with self.store.transaction(self.brief_id) as tx:
            self.assertEqual(tx.state().dependencies,
                             tuple(sorted(tx.state().dependencies, key=lambda pin: pin.role)))

    def test_admission_waiting_on_rolled_back_approval_does_not_use_it(self):
        proposed = self.revise_thesis(seconds=2)
        held, attempted, release = Event(), Event(), Event()
        ids, pids = {}, {}
        def holder():
            try:
                with transaction.atomic():
                    result = self.approve(proposed, 3)
                    ids["id"] = result["command"]["result"]["approval_id"]
                    pids["blocker"] = connection.connection.info.backend_pid
                    held.set()
                    if not release.wait(10):
                        raise TimeoutError("approval not released")
                    raise RuntimeError("rollback approval")
            except RuntimeError as error:
                if str(error) != "rollback approval":
                    raise
        def waiter():
            def observe(execute, sql, params, many, context):
                if "FOR UPDATE" in sql and get_user_model()._meta.db_table in sql:
                    pids["waiter"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                return execute(sql, params, many, context)
            with connection.execute_wrapper(observe):
                return enroll_synthetic(self.actor, self.thesis_id, self.brief_id, ids["id"],
                                        self.fixtures, synthetic=True,
                                        clock=lambda: self.at + timedelta(seconds=4))
        with ThreadPoolExecutor(max_workers=2) as pool:
            approval = pool.submit(isolated, holder)
            try:
                self.assertTrue(held.wait(10))
                admission = pool.submit(isolated, waiter)
                self.assertTrue(attempted.wait(10))
                self.assert_wait(pids["waiter"], pids["blocker"])
            finally:
                release.set()
            approval.result(timeout=15)
            with self.assertRaises(ContextPending):
                admission.result(timeout=15)
        self.assertFalse(ContextAdmission.objects.exists())
        self.assertFalse(BriefStateRecord.objects.exists())
        self.assertFalse(ApprovalRecord.objects.filter(pk=ids["id"]).exists())

    def test_approval_first_blocks_waiting_publication_then_fails_closed(self):
        self.enroll()
        candidate = self.candidate()
        proposed = self.revise_thesis(seconds=4)
        held, attempted, release = Event(), Event(), Event()
        pids = {}
        def holder():
            with transaction.atomic():
                self.approve(proposed, 5)
                pids["blocker"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("approval not released")
        def waiter():
            def observe(execute, sql, params, many, context):
                if "FOR UPDATE" in sql and get_user_model()._meta.db_table in sql:
                    pids["waiter"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                return execute(sql, params, many, context)
            with connection.execute_wrapper(observe):
                return publish(self.store, candidate, self.at + timedelta(seconds=6))
        with ThreadPoolExecutor(max_workers=2) as pool:
            approver = pool.submit(isolated, holder)
            try:
                self.assertTrue(held.wait(10))
                publisher = pool.submit(isolated, waiter)
                self.assertTrue(attempted.wait(10))
                self.assert_wait(pids["waiter"], pids["blocker"])
            finally:
                release.set()
            approver.result(timeout=15)
            with self.assertRaises(ContextPending):
                publisher.result(timeout=15)
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())

    def test_refresh_failure_on_second_brief_rolls_back_all_admissions(self):
        self.enroll()
        self.enroll(brief_id="bound-second")
        proposed = self.revise_thesis()
        new = self.approve(proposed, 5)
        before = list(DependencyVersion.objects.order_by("pk").values())
        original = AuditTransition.objects.using
        calls = [0]
        def wrapped(using):
            manager = original(using)
            create = manager.create
            def inject(*args, **kwargs):
                if kwargs.get("kind") == "context_admitted":
                    calls[0] += 1
                    if calls[0] == 2:
                        raise RuntimeError("second refresh failure")
                return create(*args, **kwargs)
            manager.create = inject
            return manager
        with patch.object(AuditTransition.objects, "using", side_effect=wrapped):
            with self.assertRaisesRegex(RuntimeError, "second refresh"):
                refresh_context(self.actor, self.thesis_id, new["command"]["result"]["approval_id"],
                                clock=lambda: self.at + timedelta(seconds=6))
        self.assertEqual(ContextAdmission.objects.count(), 2)
        self.assertEqual(list(DependencyVersion.objects.order_by("pk").values()), before)
        self.assertEqual(set(ThesisBriefBinding.objects.values_list("status", flat=True)), {"pending"})

    def test_ready_binding_must_match_exact_admitted_heads(self):
        self.enroll()
        from macro_agent.domain.models import PinnedDependency
        from macro_agent.persistence.models import DependencyHead
        fake = PinnedDependency("activation", "fake-approval", "a" * 64,
                               self.at + timedelta(seconds=3))
        # Simulate a bypass of the service ordering. Scoped SQL links alone do
        # not establish approval authority; the protected read must reject it.
        version = DependencyVersion.objects.create(brief_id=self.brief_id, role=fake.role,
            version_id=fake.version_id, digest=fake.digest, known_at=fake.known_at)
        DependencyHead.objects.filter(brief_id=self.brief_id, role="activation").update(version=version)
        with self.assertRaises(ContextPending):
            with self.store.transaction(self.brief_id):
                self.fail("altered authority heads were accepted")

    def test_fixture_registration_cannot_preempt_bound_user_context(self):
        self.enroll()
        from macro_agent.domain.models import PinnedDependency
        before = self.store.inspect(self.brief_id)
        for role in CONTEXT_ROLES:
            with self.subTest(role=role), self.assertRaises(PermissionError):
                self.store.register_synthetic_dependency(self.brief_id,
                    PinnedDependency(role, "untrusted-context", "a" * 64,
                                     self.at + timedelta(seconds=3)), synthetic=True)
        self.assertEqual(self.store.inspect(self.brief_id), before)

    def test_exposure_first_blocks_waiting_publication_then_fails_closed(self):
        self.enroll()
        candidate = self.candidate()
        held, attempted, release = Event(), Event(), Event()
        pids = {}
        def holder():
            with transaction.atomic():
                self.paper_position(seconds=4)
                pids["blocker"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("exposure change not released")
        def waiter():
            def observe(execute, sql, params, many, context):
                if "FOR UPDATE" in sql and get_user_model()._meta.db_table in sql:
                    pids["waiter"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                return execute(sql, params, many, context)
            with connection.execute_wrapper(observe):
                return publish(self.store, candidate, self.at + timedelta(seconds=5))
        with ThreadPoolExecutor(max_workers=2) as pool:
            exposure = pool.submit(isolated, holder)
            try:
                self.assertTrue(held.wait(10))
                publisher = pool.submit(isolated, waiter)
                self.assertTrue(attempted.wait(10))
                self.assert_wait(pids["waiter"], pids["blocker"])
            finally:
                release.set()
            exposure.result(timeout=15)
            with self.assertRaises(ContextPending):
                publisher.result(timeout=15)
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertFalse(NotificationIntent.objects.exists())

    def test_publication_first_blocks_exposure_change_then_cancels_notice(self):
        self.enroll()
        candidate = self.candidate()
        held, attempted, release = Event(), Event(), Event()
        pids = {}
        @contextmanager
        def paused(brief_id):
            with self.store.transaction(brief_id) as tx:
                pids["blocker"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("publication not released")
                yield tx
        class Store:
            transaction = staticmethod(paused)
        def writer():
            def observe(execute, sql, params, many, context):
                if "FOR UPDATE" in sql and get_user_model()._meta.db_table in sql:
                    pids["waiter"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                return execute(sql, params, many, context)
            with connection.execute_wrapper(observe):
                return self.paper_position(seconds=5)
        with ThreadPoolExecutor(max_workers=2) as pool:
            publisher = pool.submit(isolated, publish, Store(), candidate,
                                    self.at + timedelta(seconds=3))
            try:
                self.assertTrue(held.wait(10))
                exposure = pool.submit(isolated, writer)
                self.assertTrue(attempted.wait(10))
                self.assert_wait(pids["waiter"], pids["blocker"])
            finally:
                release.set()
            self.assertEqual(publisher.result(timeout=15).status, "current")
            exposure.result(timeout=15)
        self.assertFalse(CurrentAssessment.objects.exists())
        self.assertEqual(NotificationIntent.objects.get().state, "canceled")
        self.assertEqual(ThesisBriefBinding.objects.get().status, "pending")

    def test_approval_clock_waits_until_every_bound_brief_is_protected(self):
        self.enroll()
        proposed = self.revise_thesis(seconds=4)
        held, attempted, release, sampled = (Event() for _ in range(4))
        pids = {}
        def holder():
            with transaction.atomic():
                BriefStateRecord.objects.select_for_update().get(pk=self.brief_id)
                pids["blocker"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("brief protection not released")
        def waiter():
            row = proposed["thesis"]
            draft = row["draft"]
            def observe(execute, sql, params, many, context):
                if "FOR UPDATE" in sql and "macro_brief_states" in sql:
                    pids["waiter"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                return execute(sql, params, many, context)
            def clock():
                sampled.set()
                self.assertTrue(release.is_set())
                return self.at + timedelta(seconds=5)
            with connection.execute_wrapper(observe):
                return theses.approve_thesis(
                    self.actor, self.thesis_id, str(uuid4()), draft["text_version"]["id"],
                    draft["text_version"]["text_digest"], draft["interpretation"]["id"],
                    draft["interpretation"]["digest"], row["revision"], clock=clock)
        with ThreadPoolExecutor(max_workers=2) as pool:
            blocker = pool.submit(isolated, holder)
            try:
                self.assertTrue(held.wait(10))
                approval = pool.submit(isolated, waiter)
                self.assertTrue(attempted.wait(10))
                self.assert_wait(pids["waiter"], pids["blocker"])
                self.assertFalse(sampled.is_set())
            finally:
                release.set()
            blocker.result(timeout=15)
            approval.result(timeout=15)
        self.assertTrue(sampled.is_set())
        self.assertEqual(ThesisBriefBinding.objects.get().status, "pending")
