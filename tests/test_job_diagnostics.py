"""Saved job summaries cannot invent causes, billing or retry authority."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from macro_agent.scheduling.diagnostics import render_brief, summarize_watch


CONFIG = {"provider": "nanogpt", "model_id": "example/cheap", "approval_id": "approved-one",
    "exposure_digest": "e" * 64, "model_configuration": {"max_output_tokens": 512},
    "sources": [{"source_id": "source-one", "contract_digest": "c" * 64}],
    "context_bounds": {"reports": 100}, "allowances": {"analysis_dispatches": 4}}


def slot(identity, kind="analysis", state="blocked", *, day="2026-10-09", payload=None, status="blocked"):
    return {"slot_id": identity, "kind": kind, "state": state, "local_date": day if kind == "daily_review" else None,
        "intended_at": day + "T08:00:00+00:00", "period_start": day + "T00:00:00+00:00",
        "cutoff": day + "T08:00:00+00:00", "configuration": deepcopy(CONFIG), "analysis_request": None,
        "leases": [{"sequence": 1, "outcome": {"status": status, "payload": payload or {}}}]}


def watch(*slots):
    return {"watch_id": "watch-one", "configuration": deepcopy(CONFIG), "slots": list(slots)}


class JobDiagnosticsTests(unittest.TestCase):
    def test_counts_and_oldest_unfinished_daily_preserve_saved_state(self):
        pending = slot("pending", "daily_review", "pending", day="2026-10-07")
        pending["leases"] = []
        value = watch(slot("done", "daily_review", "completed", day="2026-10-06", status="completed"),
            slot("blocked", "daily_review", day="2026-10-08", payload={"code": "context_overflow"}),
            slot("captured", "capture", "completed", status="completed"), pending)
        original = deepcopy(value)
        summary = summarize_watch(value)
        self.assertEqual(value, original)
        self.assertEqual(summary["counts_by_kind_state"]["daily_review"],
                         {"pending": 1, "running": 0, "completed": 1, "blocked": 1})
        self.assertEqual(summary["oldest_blocking_daily_slot"]["slot_id"], "pending")
        self.assertEqual(summary["saved_failure_codes"], [{"code": "context_overflow", "count": 1}])
        self.assertTrue(summary["read_only"])
        self.assertFalse(summary["paid_retry_authorized"])

    def test_provider_approval_exposure_source_and_config_codes_have_concrete_safe_actions(self):
        codes = ("selected_provider_not_configured", "reviewed_approval_or_exposure_changed",
            "model_configuration_changed", "source_contract_or_permission_changed", "source_unavailable")
        summary = summarize_watch(watch(*(slot(str(index), payload={"code": code, "model_calls": 0})
                                        for index, code in enumerate(codes))))
        self.assertEqual({item["saved_code"] for item in summary["diagnostics"]}, set(codes))
        for item in summary["diagnostics"]:
            self.assertTrue(item["diagnostics_complete"])
            self.assertTrue(item["suggested_action"])
            self.assertEqual(item["billing"]["model_calls"], 0)
            self.assertIsNone(item["billing"]["reported_cost_usd"])

    def test_legacy_value_error_is_incomplete_and_does_not_imply_limits_or_zero_cost(self):
        item = summarize_watch(watch(slot("legacy", payload={"code": "ValueError"}))) ["diagnostics"][0]
        self.assertEqual(item["saved_code"], "ValueError")
        self.assertFalse(item["diagnostics_complete"])
        self.assertIn("specific cause is unavailable", item["description"])
        self.assertNotIn("bound", item["description"])
        self.assertIsNone(item["billing"]["model_calls"])
        self.assertIsNone(item["billing"]["reported_cost_usd"])
        self.assertIsNone(item["billing"]["estimated_cost_usd"])

    def test_missing_or_unrecognized_codes_stay_incomplete(self):
        summary = summarize_watch(watch(slot("missing"), slot("new", payload={"code": "future_failure"})))
        self.assertEqual(summary["incomplete_diagnostics_count"], 2)
        self.assertEqual(summary["saved_failure_codes"], [{"code": "future_failure", "count": 1}])

    def test_limits_are_attributed_only_when_saved_code_says_so(self):
        summary = summarize_watch(watch(slot("old", payload={"reason": "context_overflow"}),
            slot("budget", payload={"code": "NewsBudgetExhausted"})))
        self.assertIn("bound", summary["diagnostics"][0]["description"])
        self.assertIn("allowance", summary["diagnostics"][1]["description"])
        self.assertTrue(all(item["diagnostics_complete"] for item in summary["diagnostics"]))

    def test_typed_review_capacity_and_watch_allowance_codes_have_specific_actions(self):
        summary = summarize_watch(watch(slot("review", payload={"code": "ReviewCapacityExceeded"}),
            slot("allowance", payload={"code": "AnalysisAllowanceExhausted"})))
        self.assertTrue(all(item["diagnostics_complete"] for item in summary["diagnostics"]))
        self.assertIn("without discarding evidence", summary["diagnostics"][0]["suggested_action"])
        self.assertIn("admissions", summary["diagnostics"][1]["suggested_action"])
        self.assertTrue(all(item["billing"]["model_calls"] is None for item in summary["diagnostics"]))

    def test_recovery_metadata_preserves_audit_links_and_does_not_rewrite_old_failure(self):
        value = slot("recovered", state="completed", payload={"code": "ValueError"})
        value["recoveries"] = [{"recovery_id": "recovery-one", "action": "retry", "prior_token": "lease-one",
            "initial_lease_token": "lease-two", "watch_version_id": "version-two", "created_at": "2026-10-09T09:00:00+00:00"}]
        value["leases"].append({"sequence": 2, "recovery_id": "recovery-one", "effective_watch_version_id": "version-two",
            "outcome": {"status": "completed", "payload": {}}})
        summary = summarize_watch(watch(value))
        self.assertEqual(summary["recoveries"][0]["prior_token"], "lease-one")
        self.assertEqual(summary["diagnostics"][0]["saved_outcome"], "blocked")
        self.assertEqual(summary["diagnostics"][0]["slot_state"], "completed")
        self.assertIn("saved blocked, current completed", render_brief(summary))
        self.assertIn("Recovery recovery-one: retry", render_brief(summary))

    def test_uncertain_model_results_retain_unknown_costs_and_never_authorize_paid_retry(self):
        for reason in ("timeout", "response_not_recorded", "completion_deadline_exceeded", "outcome_unknown"):
            with self.subTest(reason=reason):
                value = slot("uncertain", payload={"analysis": {"id": "attempt-one", "status": "outcome_unknown",
                    "stop_reason": reason, "reported_cost_usd": None, "estimated_cost_usd": "0.0002"}}, status="unresolved")
                value["analysis_request"] = {"provider": "nanogpt"}
                item = summarize_watch(watch(value))["diagnostics"][0]
                self.assertEqual(item["analysis_id"], "attempt-one")
                self.assertTrue(item["billing"]["dispatch_recorded"])
                self.assertIsNone(item["billing"]["reported_cost_usd"])
                self.assertEqual(item["billing"]["estimated_cost_usd"], "0.0002")
                self.assertFalse(item["billing"]["paid_retry_authorized"])
                self.assertIn("no repeated paid request", item["suggested_action"])

    def test_failed_model_output_can_have_reported_cost_without_becoming_success(self):
        value = slot("failed", payload={"analysis": {"status": "failed", "stop_reason": "invalid_model_output",
            "reported_cost_usd": "0.01", "estimated_cost_usd": None}}, status="failed")
        item = summarize_watch(watch(value))["diagnostics"][0]
        self.assertEqual(item["saved_outcome"], "failed")
        self.assertEqual(item["billing"]["reported_cost_usd"], "0.01")
        self.assertFalse(item["billing"]["paid_retry_authorized"])

    def test_old_expired_outcome_remains_visible_after_slot_completed(self):
        value = slot("recovered", state="completed", payload={"reason": "lease_expired"}, status="expired")
        value["leases"].append({"sequence": 2, "outcome": {"status": "completed", "payload": {}}})
        summary = summarize_watch(watch(value))
        self.assertEqual(summary["counts_by_kind_state"]["analysis"]["completed"], 1)
        self.assertEqual(summary["diagnostics"][0]["slot_state"], "completed")
        self.assertEqual(summary["diagnostics"][0]["saved_outcome"], "expired")
        self.assertEqual(summary["diagnostics"][0]["lease_sequence"], 1)

    def test_capture_failures_are_attributed_to_the_source(self):
        value = slot("capture", "capture", payload={"model_calls": 0, "captures": [
            {"source_id": "good", "status": "captured", "code": "snapshot_captured"},
            {"source_id": "bad", "status": "failed", "code": "source_unavailable"}]}, status="failed")
        summary = summarize_watch(watch(value))
        self.assertEqual(len(summary["diagnostics"]), 1)
        self.assertEqual(summary["diagnostics"][0]["source_id"], "bad")
        self.assertEqual(summary["diagnostics"][0]["billing"]["model_calls"], 0)

    def test_current_watch_differences_are_separate_from_saved_failure_cause(self):
        value = watch(slot("older", payload={"code": "ValueError"}))
        for field in ("provider", "approval_id", "exposure_digest", "model_configuration", "sources"):
            value["configuration"][field] = "changed"
        summary = summarize_watch(value)
        self.assertEqual(summary["configuration_changes"][0]["fields"],
                         ["provider", "approval_id", "exposure_digest", "model_configuration", "sources"])
        self.assertFalse(summary["diagnostics"][0]["diagnostics_complete"])
        self.assertIn("does not establish the failure cause", summary["configuration_changes"][0]["description"])

    def test_brief_does_not_echo_untrusted_error_text_or_control_characters(self):
        value = slot("safe", payload={"code": "ValueError\nsecret-key", "message": "Do not echo this credential"})
        summary = summarize_watch(watch(value))
        rendered = render_brief(summary)
        self.assertNotIn("secret-key", rendered)
        self.assertNotIn("credential", rendered)
        self.assertIn("specific cause is unavailable", rendered)
        self.assertIn("Unreported costs remain unknown", rendered)

    def test_invalid_accounting_never_coerces_to_free_or_trusted_amount(self):
        value = slot("bad", payload={"model_calls": False, "analysis": {"status": "failed",
            "reported_cost_usd": "NaN", "estimated_cost_usd": "-1"}}, status="failed")
        billing = summarize_watch(watch(value))["diagnostics"][0]["billing"]
        self.assertIsNone(billing["model_calls"])
        self.assertIsNone(billing["reported_cost_usd"])
        self.assertIsNone(billing["estimated_cost_usd"])

    def test_unsupported_slot_state_fails_visibly_instead_of_disappearing_from_counts(self):
        with self.assertRaises(ValueError):
            summarize_watch(watch(slot("bad", state="unrecognized")))


if __name__ == "__main__":
    unittest.main()
