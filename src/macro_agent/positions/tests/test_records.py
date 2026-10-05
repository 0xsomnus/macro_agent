"""Independent PostgreSQL checks for paper exposure and protected commands."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
import uuid

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, connections, transaction
from django.db.models.query import QuerySet
from django.test import RequestFactory, TransactionTestCase, override_settings

from macro_agent.domain.exposure import DECLARATION_FIELDS
from macro_agent.domain.models import ContextSnapshot
from macro_agent.application.publication import publish
from macro_agent.persistence import models as publication_models
from macro_agent.persistence.binding_models import ContextAdmission, ThesisBriefBinding
from macro_agent.persistence.context_binding import CONTEXT_ROLES, enroll_synthetic
from macro_agent.persistence.publication_store import DjangoPublicationStore, current_dependencies
from macro_agent.positions import service
from macro_agent.positions.models import AuditTransition, CommandReceipt, PositionRecord, PositionVersion
from macro_agent.theses import service as thesis_service
from macro_agent.theses.models import ThesisRecord
from tools.domain_fixture import fixture_case


MODELS = (PositionRecord, PositionVersion, CommandReceipt, AuditTransition)
PUBLICATION_MODELS = (
    publication_models.BriefStateRecord, publication_models.DependencyVersion,
    publication_models.DependencyHead, publication_models.AssessmentRecord,
    publication_models.CurrentAssessment, publication_models.NotificationIntent,
    publication_models.ReassessmentWork, publication_models.AuditTransition,
    ThesisBriefBinding, ContextAdmission,
)


def isolated_thread(function, *args):
    connections.close_all()
    try:
        return function(*args)
    finally:
        connections.close_all()


@override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=True)
class PostgreSQLPositionTestCase(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("Paper exposure persistence checks require PostgreSQL")
        self.owner = get_user_model().objects.create_user(username="position-owner")
        self.other = get_user_model().objects.create_user(username="position-other")
        self.at = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)
        self.thesis = self.approved_thesis(self.owner)
        self.thesis_id = self.thesis["id"]
        self.approval_id = self.thesis["approved"]["approval"]["id"]

    def approved_thesis(self, owner, *, approve=True):
        created = thesis_service.create_thesis(
            str(owner.pk), str(uuid.uuid4()), "  Gold may benefit from lower real yields.\n",
            {"drivers": ["Real yields"], "horizon": None, "invalidation_signposts": []},
            clock=lambda: self.at,
        )["thesis"]
        if not approve:
            return created
        draft = created["draft"]
        return thesis_service.approve_thesis(
            str(owner.pk), created["id"], str(uuid.uuid4()), draft["text_version"]["id"],
            draft["text_version"]["text_digest"], draft["interpretation"]["id"],
            draft["interpretation"]["digest"], created["revision"],
            clock=lambda: self.at + timedelta(seconds=1),
        )["thesis"]

    def declaration(self, **changes):
        return {"underlying": "XAU", "direction": "long", "product_id": None,
                "venue": None, "expiry": None, "quote_currency": None, "horizon": None,
                "quantity": None, "quantity_unit": None, **changes}

    def create(self, *, actor=None, thesis_id=None, command_id=None, approval_id=None,
               declaration=None, at=None):
        return service.create_position(
            str((actor or self.owner).pk), thesis_id or self.thesis_id,
            command_id or str(uuid.uuid4()), approval_id or self.approval_id,
            declaration or self.declaration(), clock=lambda: at or self.at + timedelta(seconds=2),
        )

    def revise(self, detail, *, command_id=None, declaration=None, at=None):
        return service.revise_position(
            str(self.owner.pk), detail["id"], command_id or str(uuid.uuid4()),
            detail["revision"], self.approval_id, declaration or self.declaration(direction="short"),
            clock=lambda: at or self.at + timedelta(seconds=3),
        )

    def close(self, detail, *, command_id=None, at=None):
        return service.close_position(
            str(self.owner.pk), detail["id"], command_id or str(uuid.uuid4()),
            detail["revision"], self.approval_id,
            clock=lambda: at or self.at + timedelta(seconds=4),
        )

    def state(self, *, include_publication=False):
        models = (*MODELS, *PUBLICATION_MODELS) if include_publication else MODELS
        return {model._meta.label: list(model.objects.order_by(model._meta.pk.name).values())
                for model in models}

    @contextmanager
    def assert_database_guard(self, state="23514", message=None):
        with self.assertRaises(DatabaseError) as raised:
            with transaction.atomic():
                yield
        self.assertEqual(getattr(raised.exception.__cause__, "sqlstate", None), state)
        if message:
            self.assertIn(message, str(raised.exception))

    def raw_mutation(self, record, assignments=None, params=(), *, delete=False):
        quote = connection.ops.quote_name
        table, key = quote(record._meta.db_table), quote(record._meta.pk.column)
        sql = (f"DELETE FROM {table} WHERE {key} = %s" if delete else
               f"UPDATE {table} SET {assignments or f'{key} = {key}'} WHERE {key} = %s")
        with connection.cursor() as cursor:
            cursor.execute(sql, [*params, record.pk])

    def version_values(self, row, **changes):
        previous = row.current_version
        return {"id": uuid.uuid4(), "position": row, "owner": self.owner,
                "thesis_id": self.thesis_id, "reviewed_approval_id": self.approval_id,
                "parent": previous, "paper": True, "status": "open",
                "mapping_status": "user_declared_unverified", "digest": "d" * 64,
                "accepted_at": self.at + timedelta(seconds=5),
                **{name: getattr(previous, name) for name in DECLARATION_FIELDS}, **changes}

    def server_lock_wait(self, waiter_pid, blocker_pid, table, timeout=5):
        deadline, observed = monotonic() + timeout, None
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT state, wait_event_type, query, pg_blocking_pids(pid) "
                               "FROM pg_stat_activity WHERE pid = %s", [waiter_pid])
                observed = cursor.fetchone()
            if (observed and observed[0] == "active" and observed[1] == "Lock"
                    and "FOR UPDATE" in observed[2] and table in observed[2]
                    and blocker_pid in observed[3]):
                return
            sleep(0.01)
        self.fail(f"Expected independent PostgreSQL lock wait on {table}: {observed!r}")


class PostgreSQLPositionSchemaTests(PostgreSQLPositionTestCase):
    def test_raw_sql_cannot_update_or_delete_history(self):
        detail = self.create()["position"]
        row = PositionRecord.objects.get(pk=detail["id"])
        records = (row.current_version, row.command_receipts.get(), row.audit_transitions.get())
        before = self.state()
        for record in records:
            for delete in (False, True):
                with self.subTest(model=record._meta.label, delete=delete):
                    with self.assert_database_guard(message="immutable paper position history"):
                        self.raw_mutation(record, delete=delete)
        self.assertEqual(before, self.state())

    def test_aggregate_identity_owner_thesis_and_original_approval_are_stable(self):
        detail = self.create()["position"]
        row = PositionRecord.objects.get(pk=detail["id"])
        another = self.approved_thesis(self.owner)
        before = self.state()
        for assignment, params in (
            ("id = %s", [uuid.uuid4()]), ("owner_id = %s", [self.other.pk]),
            ("thesis_id = %s", [another["id"]]),
            ("original_approval_id = %s", [another["approved"]["approval"]["id"]]),
            ("created_at = %s", [self.at]),
        ):
            with self.subTest(assignment=assignment), self.assert_database_guard(message="immutable"):
                self.raw_mutation(row, assignment, params)
        with self.assert_database_guard(message="cannot be deleted"):
            self.raw_mutation(row, delete=True)
        self.assertEqual(before, self.state())

    def test_parent_current_approval_owner_and_audit_scopes_are_sql_guarded(self):
        own = PositionRecord.objects.get(pk=self.create()["position"]["id"])
        foreign_thesis = self.approved_thesis(self.other)
        foreign = PositionRecord.objects.get(pk=self.create(
            actor=self.other, thesis_id=foreign_thesis["id"],
            approval_id=foreign_thesis["approved"]["approval"]["id"],
        )["position"]["id"])
        with self.assert_database_guard("23503"):
            PositionRecord.objects.create(owner=self.other, thesis_id=self.thesis_id,
                original_approval_id=self.approval_id, created_at=self.at, changed_at=self.at)
        for changes in ({"owner": self.other}, {"thesis_id": foreign.thesis_id},
                        {"reviewed_approval_id": foreign.original_approval_id},
                        {"parent": foreign.current_version}):
            with self.subTest(changes=changes), self.assert_database_guard("23503"):
                PositionVersion.objects.create(**self.version_values(own, **changes))
        with self.assert_database_guard():
            self.raw_mutation(own, "current_version_id = %s, revision = revision + 1, changed_at = %s",
                              [foreign.current_version_id, foreign.changed_at])
        with self.assert_database_guard("23503"):
            AuditTransition.objects.create(position=own, thesis_id=foreign.thesis_id,
                                           kind="foreign", at=self.at, detail={})
        with self.assert_database_guard("23503"):
            CommandReceipt.objects.create(position=own, owner=self.other, thesis_id=self.thesis_id,
                command_id=uuid.uuid4(), kind="create", request_digest="a" * 64,
                result={}, saved_at=self.at)

    def test_quantity_calendar_and_shape_are_database_guarded(self):
        row = PositionRecord.objects.get(pk=self.create()["position"]["id"])
        invalid = (
            {"quantity": "0", "quantity_unit": "contracts"},
            {"quantity": "1e3", "quantity_unit": "contracts"},
            {"quantity": "01", "quantity_unit": "contracts"},
            {"quantity": "1"}, {"quantity_unit": "contracts"},
            {"quantity": "1.0000000000001", "quantity_unit": "contracts"},
            {"quantity": "9" * 29, "quantity_unit": "contracts"},
            {"expiry": "2026-02-29"}, {"expiry": "0000-01-01"},
            {"expiry": "2026-10-5"}, {"paper": False},
            {"mapping_status": "verified"}, {"direction": "other"},
            {"status": "other"}, {"product_id": " "},
        )
        before = self.state()
        for changes in invalid:
            with self.subTest(changes=changes), self.assert_database_guard():
                PositionVersion.objects.create(**self.version_values(row, **changes))
        self.assertEqual(before, self.state())

    def test_raw_pointer_cannot_reactivate_old_version_or_reopen_closed_position(self):
        detail = self.create()["position"]
        row = PositionRecord.objects.get(pk=detail["id"])
        initial_version = row.current_version_id
        self.close(detail)
        row.refresh_from_db()
        before = self.state()
        with self.assert_database_guard(message="closed parent"):
            PositionVersion.objects.create(**self.version_values(row))
        with self.assert_database_guard():
            self.raw_mutation(row, "current_version_id = %s, revision = revision + 1, changed_at = %s",
                              [initial_version, self.at + timedelta(seconds=5)])
        self.assertEqual(before, self.state())

    def test_current_pointer_requires_next_revision_parent_and_matching_effective_time(self):
        row = PositionRecord.objects.get(pk=self.create()["position"]["id"])
        successor = PositionVersion.objects.create(**self.version_values(row))
        for revision, changed_at in ((row.revision, successor.accepted_at),
                                     (row.revision + 2, successor.accepted_at),
                                     (row.revision + 1, successor.accepted_at + timedelta(seconds=1))):
            with self.subTest(revision=revision, at=changed_at), self.assert_database_guard():
                self.raw_mutation(row, "current_version_id = %s, revision = %s, changed_at = %s",
                                  [successor.pk, revision, changed_at])
        with self.assert_database_guard(message="progress requires"):
            self.raw_mutation(row, "revision = revision + 1")

    def test_version_cannot_predate_position_reviewed_approval_or_parent(self):
        row = PositionRecord.objects.get(pk=self.create()["position"]["id"])
        with self.assert_database_guard(message="cannot predate"):
            PositionVersion.objects.create(**self.version_values(row, accepted_at=self.at))
        next_version = PositionVersion.objects.create(**self.version_values(row))
        with self.assert_database_guard(message="cannot predate"):
            PositionVersion.objects.create(**self.version_values(row, parent=next_version,
                accepted_at=next_version.accepted_at - timedelta(seconds=1)))


class PostgreSQLPositionServiceTests(PostgreSQLPositionTestCase):
    def test_attachment_requires_current_approved_thesis_and_preserves_exact_context(self):
        unapproved = self.approved_thesis(self.owner, approve=False)
        before = self.state()
        with self.assertRaises(service.PositionConflict):
            self.create(thesis_id=unapproved["id"])
        with self.assertRaises(service.PositionConflict):
            self.create(approval_id=str(uuid.uuid4()))
        self.assertEqual(before, self.state())
        declared = self.declaration(product_id="  cafe\u0301\r\nproduct  ", quantity="1.00",
                                    quantity_unit=" contracts ", horizon=" months ")
        response = self.create(declaration=declared)["position"]
        version = response["current_version"]
        for field in DECLARATION_FIELDS:
            self.assertEqual(version[field], declared[field])
        self.assertEqual(response["mapping_status"], "user_declared_unverified")
        self.assertIn("venue", version["missing_fields"])

    def test_private_services_reject_foreign_and_inactive_owners(self):
        detail = self.create()["position"]
        before = self.state()
        calls = (
            lambda: service.get_position(str(self.other.pk), detail["id"]),
            lambda: service.position_history(str(self.other.pk), detail["id"]),
            lambda: service.list_positions(str(self.other.pk), self.thesis_id),
            lambda: service.create_position(str(self.other.pk), self.thesis_id, str(uuid.uuid4()),
                self.approval_id, self.declaration()),
            lambda: service.revise_position(str(self.other.pk), detail["id"], str(uuid.uuid4()),
                detail["revision"], self.approval_id, self.declaration()),
            lambda: service.close_position(str(self.other.pk), detail["id"], str(uuid.uuid4()),
                detail["revision"], self.approval_id),
        )
        for call in calls:
            with self.assertRaises(service.PositionUnavailable):
                call()
        self.assertEqual(before, self.state())
        self.owner.is_active = False
        self.owner.save(update_fields=("is_active",))
        with self.assertRaises(service.PositionUnavailable):
            self.revise(detail)
        with self.assertRaises(service.PositionUnavailable):
            service.get_position(str(self.owner.pk), detail["id"])

    def test_retries_preserve_original_result_without_reopening_or_reapplying_versions(self):
        create_command, revise_command, close_command = (str(uuid.uuid4()) for _ in range(3))
        created = self.create(command_id=create_command)
        revised = self.revise(created["position"], command_id=revise_command)
        closed = self.close(revised["position"], command_id=close_command)
        before = self.state()
        retries = (
            (created, self.create(command_id=create_command)),
            (revised, self.revise(created["position"], command_id=revise_command)),
            (closed, self.close(revised["position"], command_id=close_command)),
        )
        for original, retry in retries:
            self.assertTrue(retry["command"]["replayed"])
            self.assertEqual(retry["command"]["result"], original["command"]["result"])
            self.assertEqual(retry["position"], closed["position"])
        self.assertFalse(retries[0][1]["command"]["is_current_version"])
        self.assertFalse(retries[1][1]["command"]["is_current_version"])
        self.assertTrue(retries[2][1]["command"]["is_current_version"])
        self.assertEqual(before, self.state())

    def test_stale_revision_changed_command_and_closed_revision_make_no_changes(self):
        command = str(uuid.uuid4())
        created = self.create(command_id=command)["position"]
        revised = self.revise(created)["position"]
        before = self.state()
        with self.assertRaises(service.PositionConflict):
            self.revise(created)
        with self.assertRaises(service.PositionConflict):
            self.create(command_id=command, declaration=self.declaration(direction="short"))
        self.assertEqual(before, self.state())
        closed = self.close(revised)["position"]
        before = self.state()
        with self.assertRaises(service.PositionConflict):
            self.revise(closed)
        with self.assertRaises(service.PositionConflict):
            self.close(closed)
        self.assertEqual(before, self.state())

    def test_thesis_amendment_preserves_position_history_and_requires_new_approval_review(self):
        created = self.create()["position"]
        before = self.state()
        proposed = thesis_service.propose_thesis(
            str(self.owner.pk), self.thesis_id, str(uuid.uuid4()),
            "Gold may benefit from a different reviewed driver.",
            {"drivers": ["Central-bank demand"], "horizon": "months", "invalidation_signposts": []},
            self.thesis["revision"], clock=lambda: self.at + timedelta(seconds=3),
        )["thesis"]
        draft = proposed["draft"]
        approved = thesis_service.approve_thesis(
            str(self.owner.pk), self.thesis_id, str(uuid.uuid4()), draft["text_version"]["id"],
            draft["text_version"]["text_digest"], draft["interpretation"]["id"],
            draft["interpretation"]["digest"], proposed["revision"],
            clock=lambda: self.at + timedelta(seconds=4),
        )["thesis"]
        self.assertEqual(before, self.state())
        current = service.get_position(str(self.owner.pk), created["id"])
        self.assertEqual(current["original_approval_id"], self.approval_id)
        self.assertEqual(current["current_version"]["reviewed_approval_id"], self.approval_id)
        with self.assertRaises(service.PositionConflict):
            self.revise(created, at=self.at + timedelta(seconds=5))
        new_approval = approved["approved"]["approval"]["id"]
        revised = service.revise_position(
            str(self.owner.pk), created["id"], str(uuid.uuid4()), created["revision"],
            new_approval, self.declaration(), clock=lambda: self.at + timedelta(seconds=5),
        )["position"]
        self.assertEqual(revised["original_approval_id"], self.approval_id)
        self.assertEqual(revised["current_version"]["reviewed_approval_id"], new_approval)

    def test_record_bound_counts_closed_records_and_retry_precedes_bound(self):
        command = str(uuid.uuid4())
        with patch.object(service, "MAX_POSITION_RECORDS", 2):
            first = self.create(command_id=command)["position"]
            self.close(first)
            self.create()
            before = self.state()
            with self.assertRaises(service.PositionConflict):
                self.create()
            retried = self.create(command_id=command)
            self.assertTrue(retried["command"]["replayed"])
            self.assertEqual(before, self.state())

    def test_receipt_failure_rolls_back_create_revise_close_and_bound_invalidation(self):
        detail = self.create()["position"]
        candidate, dependencies = fixture_case(owner_id=str(self.owner.pk))
        fixture_inputs = tuple(pin for pin in dependencies if pin.role not in CONTEXT_ROLES)
        enrolled_at = self.at + timedelta(seconds=10)
        enroll_synthetic(str(self.owner.pk), self.thesis_id, candidate.brief_id,
                         self.approval_id, fixture_inputs, clock=lambda: enrolled_at, synthetic=True)
        bound = replace(candidate, snapshot=ContextSnapshot("position-rollback-snapshot",
            enrolled_at, current_dependencies(candidate.brief_id, "default")))
        publish(DjangoPublicationStore(str(self.owner.pk)), bound, lambda: enrolled_at)
        self.assertEqual(publication_models.NotificationIntent.objects.filter(state="pending").count(), 1)
        before = self.state(include_publication=True)
        original_create = QuerySet.create

        def fail_receipt(queryset, **values):
            if queryset.model is CommandReceipt:
                raise RuntimeError("injected position receipt failure")
            return original_create(queryset, **values)

        for command in (
            lambda: self.create(at=self.at + timedelta(seconds=20)),
            lambda: self.revise(detail, at=self.at + timedelta(seconds=20)),
            lambda: self.close(detail, at=self.at + timedelta(seconds=20)),
        ):
            with patch.object(QuerySet, "create", fail_receipt):
                with self.assertRaisesRegex(RuntimeError, "receipt failure"):
                    command()
            self.assertEqual(before, self.state(include_publication=True))

    def test_private_history_is_readonly_coherent_and_explicit_about_effective_time(self):
        detail = self.create()["position"]
        revised = self.revise(detail)["position"]
        before, queries = self.state(), []

        def observe(execute, sql, params, many, context):
            queries.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(observe):
            history = service.position_history(str(self.owner.pk), revised["id"])
        self.assertEqual(history["position"], revised)
        self.assertEqual([row["kind"] for row in history["audit"]], ["create", "revise"])
        self.assertEqual(len(history["versions"]), 2)
        self.assertEqual(history["replay_scope"], "position_effective_time_history")
        self.assertFalse(history["truncated"])
        self.assertTrue(any("REPEATABLE READ, READ ONLY" in sql for sql in queries))
        self.assertFalse(any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                             for sql in queries))
        self.assertEqual(before, self.state())

    def test_equal_instant_history_follows_accepted_transitions_instead_of_uuid_order(self):
        identities = [uuid.UUID(int=value) for value in (10, 3, 2, 1)]
        same_time = self.at + timedelta(seconds=2)
        with patch.object(service, "uuid4", side_effect=identities):
            created = self.create(at=same_time)["position"]
            revised = self.revise(created, at=same_time)["position"]
            closed = self.close(revised, at=same_time)["position"]
        history = service.position_history(str(self.owner.pk), created["id"])
        expected = [created["current_version"]["id"], revised["current_version"]["id"],
                    closed["current_version"]["id"]]
        self.assertEqual([version["id"] for version in history["versions"]], expected)
        self.assertEqual([row["detail"]["version_id"] for row in history["audit"]], expected)
        self.assertEqual([row["detail"]["revision"] for row in history["audit"]], [1, 2, 3])

    def test_admin_scope_and_readonly_guards_include_superusers(self):
        own = self.create()["position"]
        foreign_thesis = self.approved_thesis(self.other)
        foreign = self.create(actor=self.other, thesis_id=foreign_thesis["id"],
            approval_id=foreign_thesis["approved"]["approval"]["id"])["position"]
        self.owner.is_staff = self.owner.is_superuser = True
        self.owner.save(update_fields=("is_staff", "is_superuser"))
        request = RequestFactory().get("/admin/")
        request.user = self.owner
        self.client.force_login(self.owner)
        before = self.state()
        for model in MODELS:
            owner_lookup = "position__owner" if model is AuditTransition else "owner"
            own_rows = model.objects.filter(**{owner_lookup: self.owner})
            foreign_row = model.objects.filter(**{owner_lookup: self.other}).first()
            own_row = own_rows.first()
            inspector = admin.site._registry[model]
            with self.subTest(model=model._meta.label):
                self.assertEqual(set(inspector.get_queryset(request).values_list("pk", flat=True)),
                                 set(own_rows.values_list("pk", flat=True)))
                self.assertFalse(inspector.has_view_permission(request, foreign_row))
                self.assertTrue(inspector.has_view_permission(request, own_row))
                self.assertFalse(inspector.has_add_permission(request))
                self.assertFalse(inspector.has_change_permission(request, own_row))
                self.assertFalse(inspector.has_delete_permission(request, own_row))
                base = f"/admin/{model._meta.app_label}/{model._meta.model_name}"
                self.assertEqual(self.client.get(f"{base}/{own_row.pk}/change/").status_code, 200)
                self.assertEqual(self.client.get(f"{base}/{foreign_row.pk}/change/").status_code, 302)
                self.assertEqual(self.client.post(f"{base}/{own_row.pk}/change/", {}).status_code, 403)
        self.assertEqual(before, self.state())


class PostgreSQLPositionConcurrencyTests(PostgreSQLPositionTestCase):
    def test_same_create_command_has_one_position_across_connections(self):
        command = str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=2) as executor:
            calls = [executor.submit(isolated_thread, lambda: self.create(command_id=command))
                     for _ in range(2)]
            results = [call.result(timeout=15) for call in calls]
        self.assertEqual(results[0]["position"]["id"], results[1]["position"]["id"])
        self.assertEqual(sorted(row["command"]["replayed"] for row in results), [False, True])
        self.assertEqual(PositionRecord.objects.count(), 1)
        self.assertEqual(PositionVersion.objects.count(), 1)
        self.assertEqual(CommandReceipt.objects.count(), 1)

    def test_history_snapshot_survives_a_committed_closure_between_reads(self):
        initial = self.create()["position"]
        before = service.position_history(str(self.owner.pk), initial["id"])
        started, release = Event(), Event()

        def reader():
            def observe(execute, sql, params, many, context):
                result = execute(sql, params, many, context)
                if (sql.lstrip().upper().startswith("SELECT")
                        and 'FROM "macro_paper_positions"' in sql and not started.is_set()):
                    started.set()
                    if not release.wait(10):
                        raise TimeoutError("position history snapshot not released")
                return result

            with connection.execute_wrapper(observe):
                return service.position_history(str(self.owner.pk), initial["id"])

        with ThreadPoolExecutor(max_workers=1) as executor:
            during = executor.submit(isolated_thread, reader)
            try:
                self.assertTrue(started.wait(10))
                self.close(initial)
            finally:
                release.set()
            self.assertEqual(during.result(timeout=15), before)
        after = service.position_history(str(self.owner.pk), initial["id"])
        self.assertEqual(after["position"]["current_version"]["status"], "closed")
        self.assertEqual(len(after["versions"]), 2)
        self.assertEqual([row["kind"] for row in after["audit"]], ["create", "close"])

    def assert_command_clock_wait(self, lock_model):
        detail = self.create()["position"]
        held, attempted, release, clock_called = (Event() for _ in range(4))
        holder_pid, waiter_pid, completed = {}, {}, []
        owner_table, thesis_table, position_table = (
            get_user_model()._meta.db_table, ThesisRecord._meta.db_table, PositionRecord._meta.db_table,
        )
        lock_table = lock_model._meta.db_table
        at = self.at + timedelta(seconds=10)

        def holder():
            with transaction.atomic():
                key = (self.owner.pk if lock_model is get_user_model() else
                       self.thesis_id if lock_model is ThesisRecord else detail["id"])
                lock_model.objects.select_for_update().get(pk=key)
                holder_pid["pid"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("paper position protection not released")

        def waiter():
            def observe(execute, sql, params, many, context):
                guarded = sql.lstrip().upper().startswith("SELECT") and "FOR UPDATE" in sql
                target = None
                if guarded:
                    target = ("position" if position_table in sql else "thesis" if thesis_table in sql
                              else "owner" if owner_table in sql else None)
                    if lock_table in sql:
                        waiter_pid["pid"] = context["connection"].connection.info.backend_pid
                        attempted.set()
                result = execute(sql, params, many, context)
                if target:
                    completed.append(target)
                return result

            def clock():
                self.assertEqual(completed, ["owner", "thesis", "position"])
                clock_called.set()
                return at

            with connection.execute_wrapper(observe):
                return service.revise_position(str(self.owner.pk), detail["id"], str(uuid.uuid4()),
                    detail["revision"], self.approval_id, self.declaration(direction="short"), clock=clock)

        with ThreadPoolExecutor(max_workers=2) as executor:
            protected = executor.submit(isolated_thread, holder)
            try:
                self.assertTrue(held.wait(10))
                command = executor.submit(isolated_thread, waiter)
                self.assertTrue(attempted.wait(10))
                self.server_lock_wait(waiter_pid["pid"], holder_pid["pid"], lock_table)
                self.assertFalse(clock_called.is_set())
            finally:
                release.set()
            protected.result(timeout=15)
            result = command.result(timeout=15)
        self.assertEqual(result["command"]["result"]["accepted_at"], at.isoformat())
        self.assertTrue(clock_called.is_set())

    def test_revision_clock_waits_for_account_lock(self):
        self.assert_command_clock_wait(get_user_model())

    def test_revision_clock_waits_for_thesis_lock(self):
        self.assert_command_clock_wait(ThesisRecord)

    def test_revision_clock_waits_for_position_lock(self):
        self.assert_command_clock_wait(PositionRecord)

    def test_position_clock_waits_until_all_bound_brief_rows_are_protected(self):
        initial = self.create()["position"]
        _, dependencies = fixture_case(owner_id=str(self.owner.pk))
        fixture_inputs = tuple(pin for pin in dependencies if pin.role not in CONTEXT_ROLES)
        briefs = ("a-position-clock-brief", "z-position-clock-brief")
        for brief_id in briefs:
            enroll_synthetic(str(self.owner.pk), self.thesis_id, brief_id, self.approval_id,
                fixture_inputs, clock=lambda: self.at + timedelta(seconds=10), synthetic=True)
        held, attempted, release, clock_called = (Event() for _ in range(4))
        holder_pid, waiter_pid, completed = {}, {}, []
        fake_now = [self.at + timedelta(seconds=11)]
        holder_time = self.at + timedelta(seconds=20)
        tables = {get_user_model()._meta.db_table: "owner", ThesisRecord._meta.db_table: "thesis",
                  PositionRecord._meta.db_table: "position",
                  publication_models.BriefStateRecord._meta.db_table: "briefs"}

        def holder():
            with transaction.atomic():
                row = publication_models.BriefStateRecord.objects.select_for_update().get(pk=briefs[1])
                row.changed_at = holder_time
                row.save(update_fields=("changed_at",))
                holder_pid["pid"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("bound brief protection not released")

        def writer():
            def observe(execute, sql, params, many, context):
                guarded = sql.lstrip().upper().startswith("SELECT") and "FOR UPDATE" in sql
                target = next((label for table, label in tables.items() if table in sql), None) if guarded else None
                if target == "briefs":
                    waiter_pid["pid"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                result = execute(sql, params, many, context)
                if target:
                    completed.append(target)
                return result

            def clock():
                self.assertEqual(completed, ["owner", "thesis", "position", "briefs"])
                clock_called.set()
                return fake_now[0]

            with connection.execute_wrapper(observe):
                return service.revise_position(str(self.owner.pk), initial["id"], str(uuid.uuid4()),
                    initial["revision"], self.approval_id, self.declaration(direction="short"), clock=clock)

        with ThreadPoolExecutor(max_workers=2) as executor:
            protected = executor.submit(isolated_thread, holder)
            try:
                self.assertTrue(held.wait(10))
                changed = executor.submit(isolated_thread, writer)
                self.assertTrue(attempted.wait(10))
                self.server_lock_wait(waiter_pid["pid"], holder_pid["pid"],
                                      publication_models.BriefStateRecord._meta.db_table)
                self.assertFalse(clock_called.is_set())
                self.assertEqual(completed, ["owner", "thesis", "position"])
                fake_now[0] = self.at + timedelta(seconds=30)
            finally:
                release.set()
            protected.result(timeout=15)
            result = changed.result(timeout=15)
        self.assertTrue(clock_called.is_set())
        self.assertEqual(result["command"]["result"]["accepted_at"], fake_now[0].isoformat())
        self.assertGreater(fake_now[0], holder_time)
        self.assertEqual(set(ThesisBriefBinding.objects.values_list("status", flat=True)), {"pending"})
        self.assertEqual(list(publication_models.BriefStateRecord.objects.order_by("brief_id")
                              .values_list("changed_at", flat=True)), [fake_now[0], fake_now[0]])

    def assert_ordered_race(self, first_kind):
        initial = self.create()["position"]
        first_saved, attempted, release = Event(), Event(), Event()
        holder_pid, waiter_pid = {}, {}
        original_save = service._save_command

        def hold_first(thesis, position, command_id, kind, digest, at):
            result = original_save(thesis, position, command_id, kind, digest, at)
            if kind == first_kind:
                holder_pid["pid"] = connection.connection.info.backend_pid
                first_saved.set()
                if not release.wait(10):
                    raise TimeoutError("first exposure command not released")
            return result

        def first():
            return self.revise(initial) if first_kind == "revise" else self.close(initial)

        def second():
            def observe(execute, sql, params, many, context):
                if sql.lstrip().upper().startswith("SELECT") and "FOR UPDATE" in sql:
                    if get_user_model()._meta.db_table in sql:
                        waiter_pid["pid"] = context["connection"].connection.info.backend_pid
                        attempted.set()
                return execute(sql, params, many, context)

            with connection.execute_wrapper(observe):
                return self.close(initial) if first_kind == "revise" else self.revise(initial)

        with patch.object(service, "_save_command", hold_first), ThreadPoolExecutor(max_workers=2) as executor:
            winner = executor.submit(isolated_thread, first)
            try:
                self.assertTrue(first_saved.wait(10))
                loser = executor.submit(isolated_thread, second)
                self.assertTrue(attempted.wait(10))
                self.server_lock_wait(waiter_pid["pid"], holder_pid["pid"], get_user_model()._meta.db_table)
            finally:
                release.set()
            winning = winner.result(timeout=15)["position"]
            with self.assertRaises(service.PositionConflict):
                loser.result(timeout=15)
        self.assertEqual(service.get_position(str(self.owner.pk), initial["id"]), winning)
        self.assertEqual(PositionVersion.objects.count(), 2)
        if first_kind == "revise":
            completed = self.close(winning)["position"]
            self.assertEqual(completed["current_version"]["status"], "closed")
            self.assertEqual(completed["current_version"]["direction"], "short")
        else:
            self.assertEqual(winning["current_version"]["status"], "closed")

    def test_revise_first_requires_close_to_refresh_its_expected_revision(self):
        self.assert_ordered_race("revise")

    def test_close_first_rejects_waiting_revision_without_reopening(self):
        self.assert_ordered_race("close")
