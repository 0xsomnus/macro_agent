"""Configuration cannot disable database wait limits or inject libpq options."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from django.core.exceptions import ImproperlyConfigured
from macro_agent.web.db_settings import postgres_options


class DatabaseOptionTests(unittest.TestCase):
    def test_defaults_bound_connect_lock_and_statement_waits(self):
        options = postgres_options({})
        self.assertEqual(options["connect_timeout"], 5)
        self.assertIn("lock_timeout=5000ms", options["options"])
        self.assertIn("statement_timeout=15000ms", options["options"])

    def test_explicit_limits_remain_separate(self):
        options = postgres_options({"MACRO_DB_LOCK_TIMEOUT_MS": "120",
                                    "MACRO_DB_STATEMENT_TIMEOUT_MS": "800"})
        self.assertIn("lock_timeout=120ms", options["options"])
        self.assertIn("statement_timeout=800ms", options["options"])

    def test_invalid_or_disabled_limits_reject_without_echoing_values(self):
        for name in ("MACRO_DB_LOCK_TIMEOUT_MS", "MACRO_DB_STATEMENT_TIMEOUT_MS"):
            for value in ("0", "-1", "300001", "NaN", "1.5", "١٢", "100 -c search_path=private", None, True):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ImproperlyConfigured) as raised:
                        postgres_options({name: value})
                    self.assertIn(name, str(raised.exception))
                    self.assertNotIn("search_path", str(raised.exception))

    def test_lock_limit_cannot_be_hidden_by_shorter_statement_limit(self):
        for value in ("5000", "4000"):
            with self.assertRaises(ImproperlyConfigured):
                postgres_options({"MACRO_DB_STATEMENT_TIMEOUT_MS": value})
