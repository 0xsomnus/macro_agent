"""Independent PostgreSQL connections enforce configured lock/query bounds."""

from time import monotonic
from uuid import uuid4

from django.conf import settings
from django.db import connection, transaction
from django.test import TransactionTestCase
import psycopg

from macro_agent.web.db_settings import postgres_options


class DatabaseDeadlineTests(TransactionTestCase):
    def connect(self):
        params = connection.get_connection_params().copy()
        params.update(postgres_options({"MACRO_DB_LOCK_TIMEOUT_MS": "120",
                                        "MACRO_DB_STATEMENT_TIMEOUT_MS": "800"}))
        return psycopg.connect(**params)

    def test_django_connections_receive_the_declared_project_options(self):
        options = settings.DATABASES["default"]["OPTIONS"]["options"]
        with connection.cursor() as cursor:
            for name in ("lock_timeout", "statement_timeout"):
                cursor.execute(f"SELECT EXTRACT(epoch FROM current_setting('{name}')::interval) * 1000")
                value = int(cursor.fetchone()[0])
                self.assertGreater(value, 0)
                self.assertIn(f"{name}={value}ms", options)

    def test_blocked_connection_times_out_and_rollback_keeps_it_usable(self):
        identity = uuid4().int % (2**63 - 1)
        with transaction.atomic(), connection.cursor() as holder:
            holder.execute("SELECT pg_advisory_xact_lock(%s)", [identity])
            with self.connect() as waiter:
                start = monotonic()
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    waiter.execute("SELECT pg_advisory_xact_lock(%s)", [identity])
                self.assertLess(monotonic() - start, 2)
                waiter.rollback()
                self.assertEqual(waiter.execute("SELECT 1").fetchone(), (1,))

    def test_running_query_times_out_and_leaves_no_recovery_action(self):
        with self.connect() as client:
            start = monotonic()
            with self.assertRaises(psycopg.errors.QueryCanceled):
                client.execute("SELECT pg_sleep(5)")
            self.assertLess(monotonic() - start, 2)
            client.rollback()
            self.assertEqual(client.execute("SELECT 1").fetchone(), (1,))
