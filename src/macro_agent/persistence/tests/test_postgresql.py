from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sys
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, connections, transaction
from django.test import Client, RequestFactory, TransactionTestCase, override_settings

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools"))
from domain_fixture import fixture_case
from macro_agent.application.publication import publish
from macro_agent.persistence.models import (AssessmentRecord, AuditTransition, BriefStateRecord,
    CurrentAssessment, DependencyHead, DependencyVersion, NotificationIntent, ReassessmentWork)
from macro_agent.persistence.publication_store import DjangoPublicationStore


class PausedStore:
    def __init__(self, store, read, release, backend_pid=None):
        self.store, self.read, self.release = store, read, release
        self.backend_pid = backend_pid

    @contextmanager
    def transaction(self, brief_id):
        with self.store.transaction(brief_id) as tx:
            wrapper = self

            class PausedTransaction:
                def state(self):
                    state = tx.state()
                    if wrapper.backend_pid is not None:
                        wrapper.backend_pid["pid"] = connections[wrapper.store.using].connection.info.backend_pid
                    wrapper.read.set()
                    if not wrapper.release.wait(10):
                        raise TimeoutError("publication was not released")
                    return state

                def existing(self, assessment_id):
                    return tx.existing(assessment_id)

                def save(self, candidate, decision, at):
                    return tx.save(candidate, decision, at)

            yield PausedTransaction()


def isolated_thread(function, *args):
    """Django keeps independent connections per thread; close every worker."""
    connections.close_all()
    try:
        return function(*args)
    finally:
        connections.close_all()


@override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=True)
class PostgreSQLPublicationTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("These are PostgreSQL tests, not SQLite substitutes")
        self.owner = get_user_model().objects.create_user(username="fixture-owner")
        self.other = get_user_model().objects.create_user(username="other-owner")
        self.store = DjangoPublicationStore(str(self.owner.pk))
        self.candidate, dependencies = fixture_case(owner_id=str(self.owner.pk))
        self.initial = self.candidate.snapshot.cutoff
        corrected, _ = fixture_case("fresh", revision=2, owner_id=str(self.owner.pk))
        self.correction = corrected.snapshot.dependency("event_revision")
        self.previous = self.candidate.snapshot.dependency("event_revision")
        self.store.bootstrap_synthetic(self.candidate.brief_id, dependencies, self.initial, synthetic=True)

    def report(self):
        return self.store.inspect(self.candidate.brief_id)

    def correct(self, store=None):
        store = store or self.store
        store.register_synthetic_dependency(self.candidate.brief_id, self.correction, synthetic=True)
        store.advance_evidence(self.candidate.brief_id, self.correction, self.previous,
                               self.correction.known_at)

    def assert_server_lock_wait(self, waiter_pid, blocker_pid, timeout=5):
        """Observe the actual guarded query blocked in PostgreSQL, before release."""
        deadline = monotonic() + timeout
        observed = None
        while monotonic() < deadline:
            # Autocommit gives each observation a fresh statistics snapshot.
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT state, wait_event_type, query, pg_blocking_pids(pid) "
                    "FROM pg_stat_activity WHERE pid = %s", [waiter_pid])
                observed = cursor.fetchone()
            if (observed is not None and observed[0] == "active" and observed[1] == "Lock"
                    and "FOR UPDATE" in observed[2] and "macro_brief_states" in observed[2]
                    and blocker_pid in observed[3]):
                return
            sleep(0.01)
        self.fail(f"guarded query did not wait on backend {blocker_pid}: {observed!r}")

    @contextmanager
    def assert_database_guard(self, message):
        with self.assertRaises(DatabaseError) as raised:
            with transaction.atomic():
                yield
        self.assertEqual(getattr(raised.exception.__cause__, "sqlstate", None), "23514")
        self.assertIn(message, str(raised.exception))

    def test_correction_first_retains_stale_analysis_without_notice(self):
        started, corrected = Event(), Event()

        def old_work():
            started.set()
            if not corrected.wait(10):
                raise TimeoutError("correction did not commit")
            return publish(self.store, self.candidate, self.correction.known_at + timedelta(seconds=1))

        def correction_work():
            if not started.wait(10):
                raise TimeoutError("analysis did not start")
            self.correct(DjangoPublicationStore(str(self.owner.pk)))
            corrected.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            old = executor.submit(isolated_thread, old_work)
            fresh = executor.submit(isolated_thread, correction_work)
            fresh.result(timeout=15)
            self.assertEqual(old.result(timeout=15).status, "superseded")
        report = self.report()
        self.assertIsNone(report["current_assessment_id"])
        self.assertEqual(report["notifications"], [])
        self.assertEqual(len(report["assessments"]), 1)
        self.assertEqual(report["reassessment"][0]["state"], "pending")
        candidate, _ = fixture_case("fresh", revision=2, owner_id=str(self.owner.pk))
        publish(self.store, candidate, self.correction.known_at + timedelta(seconds=2))
        self.assertEqual(self.report()["reassessment"][0]["state"], "completed")

    def test_publication_lock_blocks_correction_until_commit(self):
        self.store.register_synthetic_dependency(self.candidate.brief_id, self.correction, synthetic=True)
        read, release, attempted, head_read, finished = (Event() for _ in range(5))
        holder_pid, waiter_pid = {}, {}
        paused = PausedStore(self.store, read, release, holder_pid)

        def correction_work():
            def observe(execute, sql, params, many, context):
                if sql.lstrip().upper().startswith("SELECT") and "macro_brief_states" in sql and "FOR UPDATE" in sql:
                    waiter_pid["pid"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                result = execute(sql, params, many, context)
                if sql.lstrip().upper().startswith("SELECT") and "macro_dependency_heads" in sql:
                    head_read.set()
                return result

            try:
                with connection.execute_wrapper(observe):
                    DjangoPublicationStore(str(self.owner.pk)).advance_evidence(
                        self.candidate.brief_id, self.correction, self.previous, self.correction.known_at)
            finally:
                finished.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            publication = executor.submit(isolated_thread, publish, paused, self.candidate,
                                          self.initial + timedelta(seconds=1))
            try:
                self.assertTrue(read.wait(10))
                correction = executor.submit(isolated_thread, correction_work)
                self.assertTrue(attempted.wait(10))
                self.assert_server_lock_wait(waiter_pid["pid"], holder_pid["pid"])
                self.assertFalse(head_read.is_set())
                self.assertFalse(finished.is_set())
            finally:
                release.set()
            self.assertEqual(publication.result(timeout=15).status, "current")
            correction.result(timeout=15)
        self.assertTrue(head_read.is_set())
        self.assertTrue(finished.is_set())
        report = self.report()
        self.assertIsNone(report["current_assessment_id"])
        self.assertEqual(report["assessments"][0]["decision"]["status"], "current")
        self.assertFalse(report["assessments"][0]["is_current"])
        self.assertEqual(report["notifications"][0]["state"], "canceled")

    def test_clock_is_sampled_after_a_waiting_publisher_reads_correction(self):
        held, attempted, read, release = Event(), Event(), Event(), Event()
        holder_pid, waiter_pid = {}, {}
        fake_now = [self.initial]
        no_pause = Event()
        no_pause.set()
        paused = PausedStore(self.store, read, no_pause)

        def hold_correction():
            store = DjangoPublicationStore(str(self.owner.pk))
            with store.transaction(self.candidate.brief_id):
                self.correct(store)
                holder_pid["pid"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("correction commit not released")

        def observed_publication():
            def observe(execute, sql, params, many, context):
                if sql.lstrip().upper().startswith("SELECT") and "macro_brief_states" in sql and "FOR UPDATE" in sql:
                    waiter_pid["pid"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                return execute(sql, params, many, context)

            def clock():
                self.assertTrue(read.is_set())
                return fake_now[0]

            with connection.execute_wrapper(observe):
                return publish(paused, self.candidate, clock)

        with ThreadPoolExecutor(max_workers=2) as executor:
            correction = executor.submit(isolated_thread, hold_correction)
            try:
                self.assertTrue(held.wait(10))
                publication = executor.submit(isolated_thread, observed_publication)
                self.assertTrue(attempted.wait(10))
                self.assert_server_lock_wait(waiter_pid["pid"], holder_pid["pid"])
                self.assertFalse(read.is_set())
                fake_now[0] = self.correction.known_at + timedelta(seconds=1)
            finally:
                release.set()
            correction.result(timeout=15)
            self.assertEqual(publication.result(timeout=15).status, "superseded")
        self.assertEqual(self.report()["assessments"][0]["saved_at"], fake_now[0].isoformat())

    def test_unrelated_brief_can_progress_while_another_is_locked(self):
        other_candidate = replace(self.candidate, brief_id="unrelated-brief")
        self.store.bootstrap_synthetic(other_candidate.brief_id, other_candidate.snapshot.dependencies,
                                       self.initial, synthetic=True)
        read, release = Event(), Event()
        with ThreadPoolExecutor(max_workers=2) as executor:
            held = executor.submit(isolated_thread, publish, PausedStore(self.store, read, release),
                                   self.candidate, self.initial + timedelta(seconds=1))
            try:
                self.assertTrue(read.wait(10))
                independent = executor.submit(isolated_thread, publish, self.store, other_candidate,
                                              self.initial + timedelta(seconds=1))
                self.assertEqual(independent.result(timeout=5).status, "current")
            finally:
                release.set()
            held.result(timeout=15)

    def test_outbox_failure_rolls_back_all_state_and_previous_notice(self):
        publish(self.store, self.candidate, self.initial)
        before = self.report()
        new, _ = fixture_case("material-update", expected_generation=1, owner_id=str(self.owner.pk))
        from django.db.models.query import QuerySet
        original = QuerySet.create

        def failing_create(queryset, **values):
            if queryset.model is NotificationIntent:
                raise RuntimeError("injected outbox failure")
            return original(queryset, **values)

        with patch.object(QuerySet, "create", failing_create):
            with self.assertRaisesRegex(RuntimeError, "outbox failure"):
                publish(self.store, new, self.initial + timedelta(seconds=1))
        self.assertEqual(self.report(), before)

    def test_late_run_and_retry_cannot_replace_newer_state(self):
        publish(self.store, self.candidate, self.initial)
        before = self.report()
        publish(self.store, self.candidate, self.initial + timedelta(seconds=1))
        self.assertEqual(before, self.report())
        late, _ = fixture_case("late", owner_id=str(self.owner.pk))
        self.assertEqual(publish(self.store, late, self.initial + timedelta(seconds=2)).status, "superseded")
        self.assertEqual(self.report()["current_assessment_id"], self.candidate.assessment_id)
        self.correct()
        after = self.report()
        self.assertEqual(publish(self.store, self.candidate, self.correction.known_at).status, "superseded")
        self.assertEqual(after, self.report())

    def test_nonmaterial_update_preserves_valid_pending_material_notice(self):
        publish(self.store, self.candidate, self.initial)
        new, _ = fixture_case("nonmaterial", expected_generation=1, owner_id=str(self.owner.pk))
        publish(self.store, replace(new, material_change=False), self.initial + timedelta(seconds=1))
        self.assertEqual(len(self.report()["notifications"]), 1)
        self.assertTrue(self.store.mark_delivered(self.candidate.intent_id, self.initial + timedelta(seconds=2)))

    def test_equal_time_old_head_cannot_be_reactivated(self):
        replacement = replace(self.previous, version_id="fixture-new-equal-time", digest="1" * 64)
        self.store.register_synthetic_dependency(self.candidate.brief_id, replacement, synthetic=True)
        self.store.advance_evidence(self.candidate.brief_id, replacement, self.previous,
                                   self.initial + timedelta(seconds=1))
        before = self.report()
        self.store.advance_evidence(self.candidate.brief_id, replacement, replacement,
                                   self.initial + timedelta(seconds=2))
        self.assertEqual(self.report(), before)
        with self.assertRaises(ValueError):
            self.store.advance_evidence(self.candidate.brief_id, self.previous, replacement,
                                       self.initial + timedelta(seconds=2))
        self.assertEqual(publish(self.store, self.candidate, self.initial + timedelta(seconds=3)).status,
                         "superseded")

    def test_owner_is_enforced_for_reads_writes_and_local_ack(self):
        publish(self.store, self.candidate, self.initial)
        foreign = DjangoPublicationStore(str(self.other.pk))
        for operation in (lambda: foreign.inspect(self.candidate.brief_id),
                          lambda: publish(foreign, self.candidate, self.initial),
                          lambda: foreign.mark_delivered(self.candidate.intent_id, self.initial)):
            with self.assertRaises(PermissionError):
                operation()
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        with self.assertRaises(PermissionError):
            self.report()

    def test_arbitrary_and_authority_heads_cannot_be_changed(self):
        with self.assertRaises(PermissionError):
            self.store.advance_evidence(self.candidate.brief_id, self.correction,
                                        self.previous, self.correction.known_at)
        activation = self.candidate.snapshot.dependency("activation")
        with self.assertRaises(PermissionError):
            self.store.advance_evidence(self.candidate.brief_id, activation, activation, self.initial)
        with override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=False), self.assertRaises(PermissionError):
            self.store.register_synthetic_dependency(self.candidate.brief_id, self.correction, synthetic=True)

    def test_inspection_is_read_only_and_does_not_mutate_records(self):
        publish(self.store, self.candidate, self.initial)
        before = self.report()
        queries = []

        def observe(execute, sql, params, many, context):
            queries.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(observe):
            self.assertEqual(self.report(), before)
        self.assertTrue(any("REPEATABLE READ, READ ONLY" in sql for sql in queries))
        self.assertFalse(any(sql.lstrip().upper().startswith(("UPDATE", "DELETE", "INSERT")) for sql in queries))
        with transaction.atomic(), self.assertRaises(RuntimeError):
            self.report()

    def test_postgresql_enforces_immutable_history_and_scoped_heads(self):
        publish(self.store, self.candidate, self.initial)
        record = AssessmentRecord.objects.get(brief_id=self.candidate.brief_id)
        for mutate in (lambda: AssessmentRecord.objects.filter(pk=record.pk).update(payload="{}"),
                       lambda: AuditTransition.objects.filter(brief_id=self.candidate.brief_id).delete()):
            with self.assertRaises(DatabaseError), transaction.atomic():
                mutate()
        another = replace(self.candidate, brief_id="other-scope")
        self.store.bootstrap_synthetic(another.brief_id, another.snapshot.dependencies, self.initial, synthetic=True)
        wrong = DependencyVersion.objects.filter(brief_id=another.brief_id, role="event_revision").get()
        with self.assertRaises(DatabaseError), transaction.atomic():
            DependencyHead.objects.filter(brief_id=self.candidate.brief_id, role="event_revision").update(version=wrong)
        with self.assertRaises(DatabaseError), transaction.atomic():
            BriefStateRecord.objects.filter(pk=self.candidate.brief_id).update(owner=self.other)

    def test_head_and_current_pointer_identities_are_fixed(self):
        publish(self.store, self.candidate, self.initial)
        head = DependencyHead.objects.get(brief_id=self.candidate.brief_id, role="event_revision")
        with self.assert_database_guard("dependency head identity is immutable"):
            DependencyHead.objects.filter(pk=head.pk).update(id=head.pk + 10000)
        with self.assert_database_guard("governing dependency head cannot be deleted"):
            DependencyHead.objects.filter(pk=head.pk).delete()
        another = replace(self.candidate, brief_id="pointer-scope")
        self.store.bootstrap_synthetic(another.brief_id, another.snapshot.dependencies,
                                       self.initial, synthetic=True)
        with self.assert_database_guard("current assessment brief identity is immutable"):
            CurrentAssessment.objects.filter(brief_id=self.candidate.brief_id).update(brief_id=another.brief_id)

    def test_terminal_reassessment_identity_and_result_cannot_be_rewritten(self):
        self.correct()
        fresh, _ = fixture_case("fresh", revision=2, owner_id=str(self.owner.pk))
        publish(self.store, fresh, self.correction.known_at + timedelta(seconds=1))
        work = ReassessmentWork.objects.get(brief_id=self.candidate.brief_id)
        self.assertEqual(work.state, "completed")
        with self.assert_database_guard("reassessment work identity is immutable"):
            ReassessmentWork.objects.filter(pk=work.pk).update(reason="rewritten")
        with self.assert_database_guard("terminal reassessment work cannot change"):
            ReassessmentWork.objects.filter(pk=work.pk).update(state="pending", completed_at=None)
        with self.assert_database_guard("terminal reassessment work cannot change"):
            ReassessmentWork.objects.filter(pk=work.pk).update(completed_at=work.completed_at + timedelta(seconds=1))
        with self.assert_database_guard("reassessment work cannot be deleted"):
            ReassessmentWork.objects.filter(pk=work.pk).delete()

    def test_brief_and_notification_progress_cannot_move_backwards(self):
        publish(self.store, self.candidate, self.initial)
        with self.assert_database_guard("brief generation cannot move backwards"):
            BriefStateRecord.objects.filter(pk=self.candidate.brief_id).update(generation=0)
        with self.assert_database_guard("brief changed_at cannot move backwards"):
            BriefStateRecord.objects.filter(pk=self.candidate.brief_id).update(changed_at=self.initial - timedelta(seconds=1))
        self.store.mark_delivered(self.candidate.intent_id, self.initial + timedelta(seconds=2))
        with self.assert_database_guard("notification timestamp cannot move backwards"):
            NotificationIntent.objects.filter(pk=self.candidate.intent_id).update(updated_at=self.initial + timedelta(seconds=1))

    def test_readonly_inspection_stays_coherent_across_a_committed_correction(self):
        publish(self.store, self.candidate, self.initial)
        self.store.register_synthetic_dependency(self.candidate.brief_id, self.correction, synthetic=True)
        before = self.report()
        snapshot_started, release = Event(), Event()

        def inspect_while_correction_commits():
            def observe(execute, sql, params, many, context):
                result = execute(sql, params, many, context)
                if (sql.lstrip().upper().startswith("SELECT") and "macro_brief_states" in sql
                        and not snapshot_started.is_set()):
                    snapshot_started.set()
                    if not release.wait(10):
                        raise TimeoutError("read-only snapshot was not released")
                return result

            with connection.execute_wrapper(observe):
                return DjangoPublicationStore(str(self.owner.pk)).inspect(self.candidate.brief_id)

        with ThreadPoolExecutor(max_workers=1) as executor:
            reader = executor.submit(isolated_thread, inspect_while_correction_commits)
            try:
                self.assertTrue(snapshot_started.wait(10))
                self.store.advance_evidence(self.candidate.brief_id, self.correction, self.previous,
                                           self.correction.known_at)
            finally:
                release.set()
            self.assertEqual(reader.result(timeout=15), before)
        after = self.report()
        self.assertIsNone(after["current_assessment_id"])
        self.assertEqual(after["notifications"][0]["state"], "canceled")
        event_head = next(pin for pin in after["current_dependencies"] if pin["role"] == "event_revision")
        self.assertEqual(event_head["version_id"], self.correction.version_id)

    def test_notification_identity_and_terminal_state_are_protected(self):
        publish(self.store, self.candidate, self.initial)
        for mutate in (lambda: NotificationIntent.objects.filter(pk=self.candidate.intent_id).update(intent_id="forged"),
                       lambda: NotificationIntent.objects.filter(pk=self.candidate.intent_id).delete()):
            with self.assertRaises(DatabaseError), transaction.atomic():
                mutate()
        self.store.mark_delivered(self.candidate.intent_id, self.initial + timedelta(seconds=1))
        with self.assertRaises(DatabaseError), transaction.atomic():
            NotificationIntent.objects.filter(pk=self.candidate.intent_id).update(state="pending")

    def test_readonly_admin_is_owner_scoped_and_blocks_domain_crud(self):
        self.owner.is_staff = self.owner.is_superuser = True
        self.owner.save(update_fields=["is_staff", "is_superuser"])
        foreign = DjangoPublicationStore(str(self.other.pk))
        foreign.bootstrap_synthetic("foreign-brief", self.candidate.snapshot.dependencies, self.initial, synthetic=True)
        request = RequestFactory().get("/admin/")
        request.user = self.owner
        model_admin = admin.site._registry[BriefStateRecord]
        self.assertEqual(list(model_admin.get_queryset(request).values_list("brief_id", flat=True)),
                         [self.candidate.brief_id])
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        foreign_brief = BriefStateRecord.objects.get(pk="foreign-brief")
        self.assertFalse(model_admin.has_view_permission(request, foreign_brief))

    def test_admin_http_requires_login_and_blocks_foreign_views_and_domain_edits(self):
        url = f"/admin/macro_persistence/briefstaterecord/{self.candidate.brief_id}/change/"
        self.assertEqual(self.client.get(url).status_code, 302)
        self.owner.is_staff = self.owner.is_superuser = True
        self.owner.save(update_fields=["is_staff", "is_superuser"])
        foreign = DjangoPublicationStore(str(self.other.pk))
        foreign.bootstrap_synthetic("foreign-brief", self.candidate.snapshot.dependencies,
                                    self.initial, synthetic=True)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 200)
        foreign_url = "/admin/macro_persistence/briefstaterecord/foreign-brief/change/"
        self.assertEqual(self.client.get(foreign_url).status_code, 302)
        self.assertEqual(self.client.post(url, {"generation": 99}).status_code, 403)
        self.assertEqual(BriefStateRecord.objects.get(pk=self.candidate.brief_id).generation, 0)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        permitted_url = "/admin/macro_web/user/add/"
        self.assertEqual(csrf_client.get(permitted_url).status_code, 200)
        self.assertEqual(csrf_client.post(permitted_url, {"username": "csrf-fixture"}).status_code, 403)

    def test_health_endpoint_declares_only_foundation_scope(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scope"], "foundation")
