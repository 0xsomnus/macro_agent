"""A source check cannot start paid research or create persistent records."""

from datetime import datetime, timezone
import io
import json
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from macro_agent.monitoring import gdelt_research
from macro_agent.monitoring.sources import SourceError


@override_settings(SETTINGS_MODULE="macro_agent.web.local_settings",
    MACRO_ENABLE_RESEARCH_DISCOVERY=True, MACRO_MODEL_API_KEY="")
class ResearchSourceCheckTests(SimpleTestCase):
    def invoke(self):
        output = io.StringIO()
        return output, lambda: call_command("research_check_source",
            query="fictional gas supply", stdout=output)

    def test_successful_empty_metadata_is_visible_without_database_or_models(self):
        search = gdelt_research.parse_metadata(b'{"articles":[]}', query="fictional gas supply",
            received_at=datetime(2026, 10, 19, tzinfo=timezone.utc))
        output, invoke = self.invoke()
        with patch.object(gdelt_research, "discover", return_value=search) as discover:
            invoke()
        discover.assert_called_once_with("fictional gas supply")
        value = json.loads(output.getvalue())
        self.assertEqual(value["status"], "parsed")
        self.assertEqual(value["selected_reports"], 0)
        self.assertFalse(value["coverage_complete"])
        self.assertEqual((value["model_calls"], value["database_writes"], value["article_fetches"]), (0, 0, 0))
        self.assertNotIn("fictional gas supply", output.getvalue())

    def test_failure_category_is_visible_without_retry_or_exception_detail(self):
        for failure, code in ((SourceError("timeout"), "timeout"),
                (SourceError("unavailable"), "unavailable"),
                (PermissionError("private setting"), "internal_research_disabled"),
                (ValueError("private question"), "invalid_query")):
            output, invoke = self.invoke()
            with self.subTest(code=code), patch.object(gdelt_research, "discover",
                    side_effect=failure) as discover, self.assertRaises(CommandError):
                invoke()
            discover.assert_called_once_with("fictional gas supply")
            value = json.loads(output.getvalue())
            self.assertEqual(value["code"], code)
            self.assertEqual(value["model_calls"], 0)
            self.assertNotIn("private", output.getvalue())

    @override_settings(MACRO_ENABLE_RESEARCH_DISCOVERY=False)
    def test_disabled_local_gate_prevents_transport_without_a_database_connection(self):
        output, invoke = self.invoke()
        with patch.object(gdelt_research, "BoundedOpener",
                side_effect=AssertionError("No transport when disabled")), self.assertRaises(CommandError):
            invoke()
        self.assertEqual(json.loads(output.getvalue())["code"], "internal_research_disabled")
