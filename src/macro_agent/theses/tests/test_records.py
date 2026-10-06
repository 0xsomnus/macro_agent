"""Independent PostgreSQL evidence for durable thesis scope and authority."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
import uuid

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, connections, transaction
from django.db.models.query import QuerySet
from django.test import RequestFactory, TransactionTestCase

from macro_agent.theses import service
from macro_agent.theses.models import (
    ApprovalRecord, AuditTransition, CommandReceipt, InterpretationRecord,
    TextVersionRecord, ThesisRecord,
)


TABLE_MODELS = (
    ThesisRecord, TextVersionRecord, InterpretationRecord, ApprovalRecord,
    CommandReceipt, AuditTransition,
)
def isolated_thread(function, *args):
    """Each worker uses its own PostgreSQL connection and closes it on exit."""
    connections.close_all()
    try:
        return function(*args)
    finally:
        connections.close_all()


class PostgreSQLThesisTestCase(TransactionTestCase):
    """Shared fixtures and direct SQL assertions, without service internals."""

    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("Thesis persistence tests require PostgreSQL")
        self.owner = get_user_model().objects.create_user(username="thesis-owner")
        self.other = get_user_model().objects.create_user(username="thesis-other")
        self.at = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)

    @contextmanager
    def assert_database_guard(self, sqlstate, message=None):
        with self.assertRaises(DatabaseError) as raised:
            with transaction.atomic():
                yield
        self.assertEqual(getattr(raised.exception.__cause__, "sqlstate", None), sqlstate)
        if message:
            self.assertIn(message, str(raised.exception))

    def raw_mutation(self, record, *, delete=False, assignments=None, params=()):
        quote = connection.ops.quote_name
        table = quote(record._meta.db_table)
        pk = quote(record._meta.pk.column)
        if delete:
            sql = f"DELETE FROM {table} WHERE {pk} = %s"
        else:
            assignments = assignments or f"{pk} = {pk}"
            sql = f"UPDATE {table} SET {assignments} WHERE {pk} = %s"
        with connection.cursor() as cursor:
            cursor.execute(sql, [*params, record.pk])

    def draft(self, owner=None, *, approved=False):
        owner = owner or self.owner
        thesis = ThesisRecord.objects.create(
            owner=owner, revision=1, created_at=self.at,
            changed_at=self.at + timedelta(seconds=1),
        )
        text = TextVersionRecord.objects.create(
            thesis=thesis, exact_text="  Exact user belief.\n",
            text_digest=sha256(b"  Exact user belief.\n").hexdigest(), created_at=self.at,
        )
        interpretation = InterpretationRecord.objects.create(
            thesis=thesis, text_version=text, drivers=["Real yields"], horizon=None,
            invalidation_signposts=["Real yields rise"], known_at=self.at, digest="a" * 64,
        )
        thesis.latest_text, thesis.latest_interpretation = text, interpretation
        thesis.save(update_fields=["latest_text", "latest_interpretation"])
        if approved:
            approval = ApprovalRecord.objects.create(
                thesis=thesis, text_version=text, interpretation=interpretation,
                actor=owner, approved_at=self.at + timedelta(seconds=1), digest="b" * 64,
                revision=2,
            )
            thesis.current_approval, thesis.revision = approval, 2
            thesis.save(update_fields=["current_approval", "revision"])
        return thesis

    def state(self):
        return {
            model.__name__: list(model.objects.order_by(model._meta.pk.name).values())
            for model in TABLE_MODELS
        }

    def assert_server_lock_wait(self, waiter_pid, blocker_pid, table, timeout=5):
        deadline = monotonic() + timeout
        observed = None
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT state, wait_event_type, query, pg_blocking_pids(pid) "
                    "FROM pg_stat_activity WHERE pid = %s", [waiter_pid],
                )
                observed = cursor.fetchone()
            if (observed and observed[0] == "active" and observed[1] == "Lock"
                    and "FOR UPDATE" in observed[2] and table in observed[2]
                    and blocker_pid in observed[3]):
                return
            sleep(0.01)
        self.fail(f"Expected a guarded PostgreSQL wait on {table}: {observed!r}")


class PostgreSQLThesisSchemaTests(PostgreSQLThesisTestCase):
    def test_raw_sql_cannot_update_or_delete_any_history_table(self):
        thesis = self.draft(approved=True)
        receipt = CommandReceipt.objects.create(
            command_id=uuid.uuid4(), owner=self.owner, thesis=thesis, kind="approve",
            request_digest="c" * 64, result={"revision": 2}, saved_at=self.at,
        )
        audit = AuditTransition.objects.create(thesis=thesis, kind="approved", at=self.at, detail={})
        records = (thesis.latest_text, thesis.latest_interpretation, thesis.current_approval,
                   receipt, audit)
        before = self.state()
        for record in records:
            for delete in (False, True):
                with self.subTest(model=record.__class__.__name__, delete=delete):
                    with self.assert_database_guard("23514", "immutable thesis history"):
                        self.raw_mutation(record, delete=delete)
        self.assertEqual(self.state(), before)

    def test_thesis_identity_and_monotonic_progress_are_sql_guarded(self):
        thesis = self.draft()
        mutations = (
            ("id = %s", [uuid.uuid4()], "identity"),
            ("owner_id = %s", [self.other.pk], "identity"),
            ("created_at = %s", [self.at - timedelta(seconds=1)], "creation time"),
            ("revision = %s", [0], "revision cannot move backwards"),
            ("changed_at = %s", [self.at], "changed_at cannot move backwards"),
        )
        before = self.state()
        for assignments, params, message in mutations:
            with self.subTest(field=assignments):
                with self.assert_database_guard("23514", message):
                    self.raw_mutation(thesis, assignments=assignments, params=params)
        with self.assert_database_guard("23514", "cannot be deleted"):
            self.raw_mutation(thesis, delete=True)
        self.assertEqual(self.state(), before)

    def test_partial_draft_pointers_and_approval_without_draft_are_rejected(self):
        thesis = self.draft(approved=True)
        for fields in (
            {"latest_text_id": None}, {"latest_interpretation_id": None},
            {"latest_text_id": None, "latest_interpretation_id": None},
        ):
            with self.subTest(fields=fields):
                with self.assert_database_guard("23514", "macro_thesis_draft_pair"):
                    ThesisRecord.objects.filter(pk=thesis.pk).update(**fields)
        empty = ThesisRecord.objects.create(owner=self.owner, created_at=self.at, changed_at=self.at)
        self.assertIsNone(empty.current_approval_id)

    def test_current_draft_matches_its_exact_text_even_within_same_thesis(self):
        thesis = self.draft()
        second_text = TextVersionRecord.objects.create(
            thesis=thesis, parent=thesis.latest_text, exact_text="A different belief.",
            text_digest="d" * 64, created_at=self.at,
        )
        second_interpretation = InterpretationRecord.objects.create(
            thesis=thesis, text_version=second_text, drivers=[], horizon=None,
            invalidation_signposts=[], known_at=self.at, digest="e" * 64,
        )
        with self.assert_database_guard("23503", "macro_latest_draft_text_interp_fk"):
            ThesisRecord.objects.filter(pk=thesis.pk).update(latest_interpretation=second_interpretation)
        with self.assert_database_guard("23503", "macro_approval_interp_text_fk"):
            ApprovalRecord.objects.create(
                thesis=thesis, text_version=thesis.latest_text, interpretation=second_interpretation,
                actor=self.owner, approved_at=self.at, digest="f" * 64, revision=2,
            )

    def test_cross_thesis_versions_parent_and_current_pointers_are_rejected(self):
        thesis, foreign = self.draft(approved=True), self.draft(self.other, approved=True)
        with self.assert_database_guard("23503", "macro_text_parent_scope_fk"):
            TextVersionRecord.objects.create(
                thesis=thesis, parent=foreign.latest_text, exact_text="Proposed child.",
                text_digest="a" * 64, created_at=self.at,
            )
        with self.assert_database_guard("23503", "macro_interp_text_scope_fk"):
            InterpretationRecord.objects.create(
                thesis=thesis, text_version=foreign.latest_text, drivers=[], horizon=None,
                invalidation_signposts=[], known_at=self.at, digest="a" * 64,
            )
        for fields in (
            {"latest_text": foreign.latest_text, "latest_interpretation": foreign.latest_interpretation},
            {"current_approval": foreign.current_approval},
        ):
            with self.subTest(fields=tuple(fields)):
                with self.assert_database_guard("23503"):
                    ThesisRecord.objects.filter(pk=thesis.pk).update(**fields)

    def test_approval_actor_and_command_owner_must_own_the_thesis(self):
        thesis = self.draft()
        with self.assert_database_guard("23503", "macro_approval_owner_scope_fk"):
            ApprovalRecord.objects.create(
                thesis=thesis, text_version=thesis.latest_text, interpretation=thesis.latest_interpretation,
                actor=self.other, approved_at=self.at, digest="a" * 64, revision=2,
            )
        with self.assert_database_guard("23503", "macro_command_owner_scope_fk"):
            CommandReceipt.objects.create(
                thesis=thesis, owner=self.other, command_id=uuid.uuid4(), kind="create",
                request_digest="a" * 64, result={}, saved_at=self.at,
            )

    def test_interpretation_string_arrays_and_origin_provenance_are_enforced(self):
        thesis = self.draft()
        base = {
            "thesis": thesis, "text_version": thesis.latest_text,
            "drivers": [], "horizon": None, "invalidation_signposts": [],
            "known_at": self.at, "digest": "a" * 64,
        }
        for field in ("drivers", "invalidation_signposts"):
            for value in ({"key": "value"}, [1], ["valid", None], False, "driver"):
                with self.subTest(field=field, value=value):
                    with self.assert_database_guard("23514"):
                        InterpretationRecord.objects.create(**{**base, field: value})
        with self.assert_database_guard("23514", "macro_interp_origin_provenance"):
            InterpretationRecord.objects.create(**base, origin="agent_compiled")

    def test_command_and_audit_payloads_require_objects(self):
        thesis = self.draft()
        with self.assert_database_guard("23514", "macro_command_result_object"):
            CommandReceipt.objects.create(
                thesis=thesis, owner=self.owner, command_id=uuid.uuid4(), kind="create",
                request_digest="a" * 64, result=[], saved_at=self.at,
            )
        with self.assert_database_guard("23514", "macro_thesis_audit_detail_object"):
            AuditTransition.objects.create(thesis=thesis, kind="created", at=self.at, detail=[])


class PostgreSQLThesisServiceTests(PostgreSQLThesisTestCase):
    def meaning(self):
        return {
            "drivers": ["Real yields", "Policy uncertainty"], "horizon": None,
            "invalidation_signposts": ["Real yields rise"],
        }

    def create(self, *, command_id=None, text="  Gold can rise.\n", actor=None, at=None):
        return service.create_thesis(
            str((actor or self.owner).pk), command_id or str(uuid.uuid4()),
            text, self.meaning(), clock=lambda: at or self.at,
        )

    def approval_arguments(self, detail, *, command_id=None):
        draft = detail["draft"]
        return {
            "command_id": command_id or str(uuid.uuid4()),
            "thesis_version_id": draft["text_version"]["id"],
            "text_digest": draft["text_version"]["text_digest"],
            "interpretation_version_id": draft["interpretation"]["id"],
            "interpretation_digest": draft["interpretation"]["digest"],
            "expected_revision": detail["revision"],
        }

    def approve(self, detail, *, at=None, arguments=None):
        return service.approve_thesis(
            str(self.owner.pk), detail["id"],
            **(arguments or self.approval_arguments(detail)),
            clock=lambda: at or self.at + timedelta(seconds=1),
        )

    def propose(self, detail, *, text="A proposed new belief.", at=None, command_id=None):
        return service.propose_thesis(
            str(self.owner.pk), detail["id"], command_id or str(uuid.uuid4()), text,
            self.meaning(), detail["revision"],
            clock=lambda: at or self.at + timedelta(seconds=2),
        )

    def test_exact_text_and_manual_preview_wait_for_explicit_approval(self):
        exact = " \nGold may rise if real yields fall. €\n "
        created = self.create(text=exact)
        detail = created["thesis"]
        self.assertEqual(detail["draft"]["text_version"]["exact_text"], exact)
        self.assertEqual(detail["draft"]["text_version"]["text_digest"],
                         sha256(exact.encode("utf-8")).hexdigest())
        self.assertEqual(detail["draft"]["interpretation"]["origin"], "user_supplied")
        self.assertIsNone(detail["approved"])
        self.assertEqual(detail["monitoring"], "not_configured")
        approved = self.approve(detail)["thesis"]
        self.assertEqual(approved["approved"]["text_version"], detail["draft"]["text_version"])
        self.assertEqual(approved["approved"]["interpretation"], detail["draft"]["interpretation"])
        proposed = self.propose(approved)["thesis"]
        self.assertEqual(proposed["approved"], approved["approved"])
        self.assertNotEqual(proposed["draft"]["text_version"]["id"],
                            approved["approved"]["text_version"]["id"])
        self.assertEqual(proposed["draft"]["text_version"]["parent_version_id"],
                         detail["draft"]["text_version"]["id"])

    def test_stale_revision_and_wrong_displayed_digests_cannot_activate(self):
        detail = self.create()["thesis"]
        for field, value in (("text_digest", "0" * 64), ("interpretation_digest", "0" * 64),
                             ("thesis_version_id", str(uuid.uuid4())),
                             ("interpretation_version_id", str(uuid.uuid4()))):
            arguments = self.approval_arguments(detail)
            arguments[field] = value
            before = self.state()
            with self.subTest(field=field), self.assertRaises(service.ThesisConflict):
                self.approve(detail, arguments=arguments)
            self.assertEqual(self.state(), before)
        self.propose(detail)
        before = self.state()
        with self.assertRaises(service.ThesisConflict):
            self.approve(detail, at=self.at + timedelta(seconds=3))
        with self.assertRaises(service.ThesisConflict):
            self.propose(detail, at=self.at + timedelta(seconds=3))
        self.assertEqual(self.state(), before)

    def test_late_command_retry_preserves_original_result_and_current_disposition(self):
        command_id = str(uuid.uuid4())
        original = self.create(command_id=command_id)
        first_arguments = self.approval_arguments(original["thesis"])
        first = self.approve(original["thesis"], arguments=first_arguments)
        proposed = self.propose(first["thesis"])
        latest = self.approve(proposed["thesis"], at=self.at + timedelta(seconds=3))
        before = self.state()
        retried = self.approve(original["thesis"], arguments=first_arguments,
                               at=self.at + timedelta(days=1))
        self.assertTrue(retried["command"]["replayed"])
        self.assertEqual(retried["command"]["result"], first["command"]["result"])
        self.assertFalse(retried["command"]["is_current_approval"])
        self.assertEqual(retried["thesis"], latest["thesis"])
        replayed_create = self.create(command_id=command_id, at=self.at + timedelta(days=1))
        self.assertTrue(replayed_create["command"]["replayed"])
        self.assertEqual(replayed_create["command"]["result"], original["command"]["result"])
        self.assertEqual(replayed_create["thesis"], latest["thesis"])
        self.assertEqual(self.state(), before)

    def test_command_identity_is_scoped_to_owner_and_rejects_changed_payload(self):
        command_id = str(uuid.uuid4())
        original = self.create(command_id=command_id)
        before = self.state()
        with self.assertRaises(service.ThesisConflict):
            self.create(command_id=command_id, text="Changed request.")
        with self.assertRaises(service.ThesisConflict):
            self.propose(original["thesis"], command_id=command_id)
        self.assertEqual(self.state(), before)
        other = self.create(command_id=command_id, actor=self.other)
        self.assertNotEqual(other["thesis"]["id"], original["thesis"]["id"])
        self.assertEqual(CommandReceipt.objects.filter(command_id=command_id).count(), 2)

    def test_foreign_and_inactive_actors_cannot_read_or_approve_private_theses(self):
        detail = self.create()["thesis"]
        before = self.state()
        foreign_calls = (
            lambda: service.get_thesis(str(self.other.pk), detail["id"]),
            lambda: service.thesis_history(str(self.other.pk), detail["id"]),
            lambda: service.propose_thesis(str(self.other.pk), detail["id"], str(uuid.uuid4()),
                                          "Changed.", self.meaning(), detail["revision"]),
            lambda: service.approve_thesis(str(self.other.pk), detail["id"],
                                          **self.approval_arguments(detail)),
        )
        for call in foreign_calls:
            with self.assertRaises(service.ThesisUnavailable):
                call()
        self.assertEqual(service.list_theses(str(self.other.pk))["theses"], [])
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        with self.assertRaises(service.ThesisUnavailable):
            service.get_thesis(str(self.owner.pk), detail["id"])
        with self.assertRaises(service.ThesisUnavailable):
            self.approve(detail)
        self.assertEqual(self.state(), before)

    def test_receipt_failure_rolls_back_create_proposal_and_approval(self):
        original_create = QuerySet.create

        def fail_receipt(queryset, **values):
            if queryset.model is CommandReceipt:
                raise RuntimeError("injected command receipt failure")
            return original_create(queryset, **values)

        before = self.state()
        with patch.object(QuerySet, "create", fail_receipt):
            with self.assertRaisesRegex(RuntimeError, "receipt failure"):
                self.create()
        self.assertEqual(self.state(), before)
        detail = self.approve(self.create()["thesis"])["thesis"]
        before = self.state()
        with patch.object(QuerySet, "create", fail_receipt):
            with self.assertRaisesRegex(RuntimeError, "receipt failure"):
                self.propose(detail)
        self.assertEqual(self.state(), before)
        proposed = self.propose(detail)["thesis"]
        before = self.state()
        with patch.object(QuerySet, "create", fail_receipt):
            with self.assertRaisesRegex(RuntimeError, "receipt failure"):
                self.approve(proposed, at=self.at + timedelta(seconds=3))
        self.assertEqual(self.state(), before)

    def test_history_is_a_read_only_effective_time_snapshot(self):
        detail = self.approve(self.create()["thesis"])["thesis"]
        before, queries = self.state(), []

        def observe(execute, sql, params, many, context):
            queries.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(observe):
            history = service.thesis_history(str(self.owner.pk), detail["id"])
        self.assertEqual(history["thesis"], detail)
        self.assertEqual([row["kind"] for row in history["audit"]], ["create", "approve"])
        self.assertEqual(history["replay_scope"], "approval_effective_time_history")
        self.assertFalse(history["truncated"])
        self.assertTrue(any("REPEATABLE READ, READ ONLY" in sql for sql in queries))
        self.assertFalse(any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                             for sql in queries))
        self.assertEqual(self.state(), before)

    def test_history_remains_consistent_when_proposal_and_approval_commit_mid_read(self):
        detail = self.approve(self.create()["thesis"])["thesis"]
        before = service.thesis_history(str(self.owner.pk), detail["id"])
        snapshot_started, release = Event(), Event()
        root_queries = []

        def reader():
            def observe(execute, sql, params, many, context):
                result = execute(sql, params, many, context)
                if (sql.lstrip().upper().startswith("SELECT") and 'FROM "macro_theses"' in sql
                        and not snapshot_started.is_set()):
                    root_queries.append(sql)
                    snapshot_started.set()
                    if not release.wait(10):
                        raise TimeoutError("history snapshot was not released")
                return result

            with connection.execute_wrapper(observe):
                return service.thesis_history(str(self.owner.pk), detail["id"])

        def writer():
            proposed = self.propose(detail)["thesis"]
            return self.approve(proposed, at=self.at + timedelta(seconds=3))["thesis"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            history_read = executor.submit(isolated_thread, reader)
            try:
                self.assertTrue(snapshot_started.wait(10))
                changed = executor.submit(isolated_thread, writer).result(timeout=10)
                self.assertEqual(ApprovalRecord.objects.count(), 2)
                self.assertEqual(ThesisRecord.objects.get(pk=detail["id"]).revision, changed["revision"])
            finally:
                release.set()
            during = history_read.result(timeout=15)
        self.assertIn("LEFT OUTER JOIN", root_queries[0])
        self.assertIn("macro_thesis_approvals", root_queries[0])
        self.assertEqual(during, before)
        self.assertEqual(len(during["text_versions"]), 1)
        self.assertEqual(len(during["interpretations"]), 1)
        self.assertEqual(len(during["approvals"]), 1)
        after = service.thesis_history(str(self.owner.pk), detail["id"])
        self.assertEqual(after["thesis"], changed)
        self.assertNotEqual(after["thesis"]["approved"]["approval"]["id"],
                            before["thesis"]["approved"]["approval"]["id"])
        self.assertEqual(len(after["text_versions"]), 2)
        self.assertEqual(len(after["interpretations"]), 2)
        self.assertEqual(len(after["approvals"]), 2)
        self.assertEqual([event["kind"] for event in after["audit"]],
                         ["create", "approve", "propose", "approve"])

    def test_thesis_admin_is_owner_scoped_and_http_edits_are_denied_even_for_superuser(self):
        detail = self.approve(self.create()["thesis"])["thesis"]
        foreign = self.create(actor=self.other)["thesis"]
        service.approve_thesis(
            str(self.other.pk), foreign["id"], **self.approval_arguments(foreign),
            clock=lambda: self.at + timedelta(seconds=1),
        )
        own_url = f'/admin/macro_theses/thesisrecord/{detail["id"]}/change/'
        self.assertEqual(self.client.get(own_url).status_code, 302)
        self.owner.is_staff = self.owner.is_superuser = True
        self.owner.save(update_fields=["is_staff", "is_superuser"])
        request = RequestFactory().get("/admin/")
        request.user = self.owner
        self.client.force_login(self.owner)
        before = self.state()
        for model in TABLE_MODELS:
            owner_field = "owner" if model in (ThesisRecord, CommandReceipt) else "thesis__owner"
            own_rows = model.objects.filter(**{owner_field: self.owner})
            foreign_row = model.objects.filter(**{owner_field: self.other}).first()
            own_row = own_rows.first()
            model_admin = admin.site._registry[model]
            with self.subTest(model=model.__name__):
                self.assertEqual(set(model_admin.get_queryset(request).values_list("pk", flat=True)),
                                 set(own_rows.values_list("pk", flat=True)))
                self.assertTrue(model_admin.has_view_permission(request, own_row))
                self.assertFalse(model_admin.has_view_permission(request, foreign_row))
                self.assertFalse(model_admin.has_add_permission(request))
                self.assertFalse(model_admin.has_change_permission(request, own_row))
                self.assertFalse(model_admin.has_delete_permission(request, own_row))
                path = f"/admin/{model._meta.app_label}/{model._meta.model_name}"
                self.assertEqual(self.client.get(f"{path}/{own_row.pk}/change/").status_code, 200)
                self.assertEqual(self.client.get(f"{path}/{foreign_row.pk}/change/").status_code, 302)
                self.assertEqual(self.client.post(f"{path}/{own_row.pk}/change/",
                                                  {"revision": 999}).status_code, 403)
        self.assertEqual(self.state(), before)

    def assert_command_wait(self, lock_model):
        detail = self.create()["thesis"]
        held, attempted, release, clock_called = (Event() for _ in range(4))
        holder_pid, waiter_pid, completed_locks = {}, {}, []
        owner_table = get_user_model()._meta.db_table
        thesis_table = ThesisRecord._meta.db_table
        lock_table = lock_model._meta.db_table
        at = self.at + timedelta(seconds=5)

        def holder():
            with transaction.atomic():
                pk = self.owner.pk if lock_model is get_user_model() else detail["id"]
                lock_model.objects.select_for_update().get(pk=pk)
                holder_pid["pid"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("protected record was not released")

        def waiter():
            def observe(execute, sql, params, many, context):
                guarded = sql.lstrip().upper().startswith("SELECT") and "FOR UPDATE" in sql
                target = None
                if guarded:
                    target = "owner" if owner_table in sql else "thesis" if thesis_table in sql else None
                    if lock_table in sql:
                        waiter_pid["pid"] = context["connection"].connection.info.backend_pid
                        attempted.set()
                result = execute(sql, params, many, context)
                if target:
                    completed_locks.append(target)
                return result

            def clock():
                self.assertEqual(completed_locks, ["owner", "thesis"])
                clock_called.set()
                return at

            with connection.execute_wrapper(observe):
                return service.propose_thesis(
                    str(self.owner.pk), detail["id"], str(uuid.uuid4()), "A waiting proposal.",
                    self.meaning(), detail["revision"], clock=clock,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            protected = executor.submit(isolated_thread, holder)
            try:
                self.assertTrue(held.wait(10))
                command = executor.submit(isolated_thread, waiter)
                self.assertTrue(attempted.wait(10))
                self.assert_server_lock_wait(waiter_pid["pid"], holder_pid["pid"], lock_table)
                self.assertFalse(clock_called.is_set())
            finally:
                release.set()
            protected.result(timeout=15)
            result = command.result(timeout=15)
        self.assertEqual(result["command"]["result"]["accepted_at"], at.isoformat())
        self.assertEqual(result["thesis"]["changed_at"], at.isoformat())

    def test_owner_lock_wait_precedes_thesis_read_and_clock(self):
        self.assert_command_wait(get_user_model())

    def test_thesis_lock_wait_precedes_clock(self):
        self.assert_command_wait(ThesisRecord)

    def assert_competing_review_commands(self, first_kind):
        created = self.create()
        detail = created["thesis"]
        first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
        approval_arguments = self.approval_arguments(detail)
        held, release, attempted, loser_clock_called = (Event() for _ in range(4))
        holder_pid, waiter_pid, first_locks = {}, {}, []
        owner_table = get_user_model()._meta.db_table
        second_kind = "propose" if first_kind == "approve" else "approve"

        def command(kind, command_id, clock):
            if kind == "approve":
                return service.approve_thesis(
                    str(self.owner.pk), detail["id"],
                    **{**approval_arguments, "command_id": command_id}, clock=clock,
                )
            return service.propose_thesis(
                str(self.owner.pk), detail["id"], command_id, "Revised after review.",
                self.meaning(), detail["revision"], clock=clock,
            )

        def first():
            def observe(execute, sql, params, many, context):
                result = execute(sql, params, many, context)
                if sql.lstrip().upper().startswith("SELECT") and "FOR UPDATE" in sql:
                    if owner_table in sql:
                        first_locks.append("owner")
                    elif "macro_theses" in sql:
                        first_locks.append("thesis")
                return result

            def clock():
                self.assertEqual(first_locks, ["owner", "thesis"])
                holder_pid["pid"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("first review command was not released")
                return self.at + timedelta(seconds=1)

            with connection.execute_wrapper(observe):
                return command(first_kind, first_id, clock)

        def second():
            def observe(execute, sql, params, many, context):
                if (sql.lstrip().upper().startswith("SELECT") and "FOR UPDATE" in sql
                        and owner_table in sql):
                    waiter_pid["pid"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                return execute(sql, params, many, context)

            def clock():
                loser_clock_called.set()
                raise AssertionError("a stale competing command must not sample its clock")

            with connection.execute_wrapper(observe):
                return command(second_kind, second_id, clock)

        with ThreadPoolExecutor(max_workers=2) as executor:
            winning_command = executor.submit(isolated_thread, first)
            try:
                self.assertTrue(held.wait(10))
                losing_command = executor.submit(isolated_thread, second)
                self.assertTrue(attempted.wait(10))
                self.assert_server_lock_wait(waiter_pid["pid"], holder_pid["pid"], owner_table)
                self.assertFalse(loser_clock_called.is_set())
            finally:
                release.set()
            winner = winning_command.result(timeout=15)
            with self.assertRaises(service.ThesisConflict):
                losing_command.result(timeout=15)
        self.assertFalse(loser_clock_called.is_set())
        self.assertEqual(winner["thesis"]["revision"], 2)
        self.assertEqual(service.get_thesis(str(self.owner.pk), detail["id"]), winner["thesis"])
        self.assertEqual(set(CommandReceipt.objects.values_list("command_id", flat=True)),
                         {uuid.UUID(created["command"]["command_id"]), uuid.UUID(first_id)})
        history = service.thesis_history(str(self.owner.pk), detail["id"])
        self.assertEqual([event["kind"] for event in history["audit"]], ["create", first_kind])
        self.assertFalse(any(event["detail"]["command_id"] == second_id for event in history["audit"]))
        if first_kind == "approve":
            self.assertEqual(history["thesis"]["draft"], detail["draft"])
            self.assertEqual(len(history["text_versions"]), 1)
            self.assertEqual(len(history["interpretations"]), 1)
            self.assertEqual(len(history["approvals"]), 1)
            self.assertEqual(history["thesis"]["approved"]["approval"]["id"],
                             winner["command"]["result"]["approval_id"])
        else:
            self.assertNotEqual(history["thesis"]["draft"]["text_version"]["id"],
                                detail["draft"]["text_version"]["id"])
            self.assertEqual(history["thesis"]["draft"]["text_version"]["exact_text"],
                             "Revised after review.")
            self.assertEqual(len(history["text_versions"]), 2)
            self.assertEqual(len(history["interpretations"]), 2)
            self.assertEqual(history["approvals"], [])
            self.assertIsNone(history["thesis"]["approved"])

    def test_approval_first_rejects_waiting_proposal_reviewed_at_same_revision(self):
        self.assert_competing_review_commands("approve")

    def test_proposal_first_rejects_waiting_approval_of_old_displayed_versions(self):
        self.assert_competing_review_commands("propose")

    def test_concurrent_identical_creates_commit_one_aggregate_and_receipt(self):
        command_id = str(uuid.uuid4())
        held, release, attempted = Event(), Event(), Event()
        holder_pid, waiter_pid = {}, {}
        owner_table = get_user_model()._meta.db_table

        def first():
            def clock():
                holder_pid["pid"] = connection.connection.info.backend_pid
                held.set()
                if not release.wait(10):
                    raise TimeoutError("first create was not released")
                return self.at

            return service.create_thesis(str(self.owner.pk), command_id, "Exact create.",
                                         self.meaning(), clock=clock)

        def second():
            def observe(execute, sql, params, many, context):
                if (sql.lstrip().upper().startswith("SELECT") and "FOR UPDATE" in sql
                        and owner_table in sql):
                    waiter_pid["pid"] = context["connection"].connection.info.backend_pid
                    attempted.set()
                return execute(sql, params, many, context)

            def unexpected_clock():
                raise AssertionError("receipt replay must not resample its accepted time")

            with connection.execute_wrapper(observe):
                return service.create_thesis(str(self.owner.pk), command_id, "Exact create.",
                                             self.meaning(), clock=unexpected_clock)

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_create = executor.submit(isolated_thread, first)
            try:
                self.assertTrue(held.wait(10))
                second_create = executor.submit(isolated_thread, second)
                self.assertTrue(attempted.wait(10))
                self.assert_server_lock_wait(waiter_pid["pid"], holder_pid["pid"], owner_table)
            finally:
                release.set()
            original, replay = first_create.result(timeout=15), second_create.result(timeout=15)
        self.assertFalse(original["command"]["replayed"])
        self.assertTrue(replay["command"]["replayed"])
        self.assertEqual(original["command"]["result"], replay["command"]["result"])
        self.assertEqual(original["thesis"], replay["thesis"])
        self.assertEqual(ThesisRecord.objects.count(), 1)
        self.assertEqual(TextVersionRecord.objects.count(), 1)
        self.assertEqual(InterpretationRecord.objects.count(), 1)
        self.assertEqual(CommandReceipt.objects.count(), 1)
        self.assertEqual(AuditTransition.objects.count(), 1)
