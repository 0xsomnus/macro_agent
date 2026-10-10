"""Daily evidence boundaries and retained history, without model or DB calls."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from macro_agent.domain.daily_review import (
    DailyReviewCandidate, DailyReviewLimits, DailyReviewPeriod, DailyReviewScope,
    RetainedNewsAnalysis, RetainedReport, ReviewIssue, SourceContractReference,
    build_daily_review,
)
from macro_agent.domain.models import canonical_json, text_digest


START = datetime(2026, 10, 8, tzinfo=timezone.utc)
CUTOFF = START + timedelta(days=1)
PREPARED = CUTOFF + timedelta(hours=1)
PERIOD = DailyReviewPeriod(START, CUTOFF, PREPARED)
LIMITS = DailyReviewLimits(reports=10, analyses=10, exposure_versions=200, issues=10,
                          source_contracts=10, encoded_bytes=262_144)
CONTRACT = SourceContractReference("fixture-divergence", "contract-v1", "c" * 64)
SCOPE = DailyReviewScope("owner", "fixture-thesis", "approval-current", "meaning-current",
                        "e" * 64, ("position-version-current",), (CONTRACT,), "context-previous")


def report(*, witness=START + timedelta(hours=1), identity="fixture-revision"):
    payload = json.loads((ROOT / "fixtures/news_analysis_case.json").read_text())["items"][0]
    content = canonical_json(payload)
    return RetainedReport(identity, "report", CONTRACT.source_id, CONTRACT.version_id,
        CONTRACT.digest, content, text_digest(content), START - timedelta(days=2), witness)


def analysis(source=None, *, witness=START + timedelta(hours=2), identity="analysis"):
    source = source or report()
    payload = json.loads(source.payload_json)
    context = {"source": {"source_key": source.source_id, "revision_id": source.revision_id,
            "digest": source.payload_digest, **{key: payload[key] for key in ("title", "content", "url", "published_at")}},
        "approved_thesis": {"thesis_id": "fixture-thesis", "approval_id": "approval-original",
            "interpretation_id": "meaning-original", "exact_text": "Policy easing may support equities.",
            "drivers": ["Policy easing"], "horizon": "six months", "invalidation_signposts": []},
        "positions": [{"position_id": "fixture-position", "status": "open", "underlying": "NQ", "direction": "long"}]}
    document = json.loads((ROOT / "fixtures/news_analysis_response.json").read_text())
    for fact in document["attributed_facts"]:
        fact["source_revision_id"] = source.revision_id
    return RetainedNewsAnalysis(identity, "owner", "fixture-thesis", source.revision_id,
        START - timedelta(hours=1), START + timedelta(hours=1), witness,
        "analysed", (), "stale", ("approved_meaning_changed",),
        canonical_json(context), canonical_json(document),
        canonical_json({"reported_cost_usd": None, "estimated_cost_usd": "0.0002"}))


def build(*, reports=(), analyses=(), issues=(), scope=SCOPE, limits=LIMITS, period=PERIOD):
    return build_daily_review(period=period, scope=scope, reports=reports, analyses=analyses,
                              issues=issues, limits=limits)


class DailyReviewTests(unittest.TestCase):
    def test_cumulative_projection_omits_nested_context_after_full_binding_checks(self):
        source = report()
        retained = analysis(source)
        full = build(reports=(source,), analyses=(retained,)).to_dict()
        projected = build_daily_review(period=PERIOD, scope=SCOPE, reports=(source,),
            analyses=(retained,), issues=(), limits=LIMITS, include_original_context=False).to_dict()
        expected = full["analyses"]["new"][0]
        self.assertEqual(expected.pop("original_context"), json.loads(retained.context_json))
        self.assertEqual(projected, full)
        altered = json.loads(retained.context_json)
        altered["approved_thesis"]["thesis_id"] = "another-private-thesis"
        wrong_scope = replace(retained, context_json=canonical_json(altered))
        with self.assertRaisesRegex(ValueError, "bind the exact"):
            build_daily_review(period=PERIOD, scope=SCOPE, reports=(source,),
                analyses=(wrong_scope,), issues=(), limits=LIMITS, include_original_context=False)

    def test_original_context_projection_rejects_boolean_coercion(self):
        for value in (None, 0, 1, "false"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "explicit boolean"):
                build_daily_review(period=PERIOD, scope=SCOPE, reports=(), analyses=(),
                    issues=(), limits=LIMITS, include_original_context=value)

    def test_explicit_period_boundaries_and_no_publication_timestamp_selection(self):
        earlier = report(witness=START, identity="earlier")
        current = report(witness=CUTOFF, identity="current")
        later = report(witness=CUTOFF + timedelta(microseconds=1), identity="later")
        result = build(reports=(later, earlier, current)).to_dict()
        self.assertEqual([item["revision_id"] for item in result["reports"]["background"]], ["earlier"])
        self.assertEqual([item["revision_id"] for item in result["reports"]["new"]], ["current"])
        self.assertEqual(result["reports"]["deferred"][0]["deferred_reason"], "available_after_cutoff")
        self.assertEqual(result["new_eligible_report_count"], 1)
        self.assertEqual(result["reports"]["new"][0]["payload"]["published_at"], "2026-10-01T12:00:00Z")

    def test_late_analysis_of_older_report_enters_analysis_period_without_fresh_report(self):
        source = report(witness=START - timedelta(days=1))
        retained = analysis(source)
        result = build(reports=(source,), analyses=(retained,)).to_dict()
        self.assertEqual(result["new_eligible_report_count"], 0)
        self.assertEqual(result["analyses"]["new"][0]["analysis_id"], "analysis")
        self.assertIn("does not establish", result["limitations"][0])

    def test_retained_original_outcome_is_not_rewritten_by_current_disposition(self):
        source = report()
        result = build(reports=(source,), analyses=(analysis(source),)).to_dict()
        retained = result["analyses"]["new"][0]
        self.assertEqual(retained["original_status"], "analysed")
        self.assertEqual(retained["original_stale_reasons"], [])
        self.assertEqual(retained["current_disposition"], "stale")
        self.assertEqual(retained["current_stale_reasons"], ["approved_meaning_changed"])
        self.assertEqual(retained["disposition_observed_at"], PREPARED.isoformat())
        self.assertEqual(retained["original_context"]["approved_thesis"]["approval_id"], "approval-original")
        self.assertEqual(result["scope"]["approval_id"], "approval-current")
        self.assertEqual(retained["document"], json.loads(analysis(source).document_json))
        self.assertEqual(retained["document"]["thesis_route"]["status"], "potential")

    def test_missing_report_witness_is_visible_and_cannot_enter_by_publication_or_receipt(self):
        source = report(witness=None)
        retained = analysis(source)
        result = build(reports=(source,), analyses=(retained,)).to_dict()
        self.assertEqual(result["reports"]["deferred"][0]["deferred_reason"], "availability_unproven")
        self.assertEqual(result["analyses"]["deferred"][0]["deferred_reason"], "source_availability_unproven")
        self.assertEqual(result["reports"]["new"], [])
        self.assertEqual(result["analyses"]["new"], [])

    def test_finished_analysis_without_postcommit_witness_is_deferred(self):
        source = report()
        result = build(reports=(source,), analyses=(analysis(source, witness=None),)).to_dict()
        self.assertEqual(result["analyses"]["deferred"][0]["deferred_reason"], "availability_unproven")
        self.assertEqual(result["analyses"]["new"], [])

    def test_postcutoff_analysis_of_eligible_source_is_explicitly_deferred(self):
        source = report()
        result = build(reports=(source,), analyses=(analysis(source, witness=PREPARED),)).to_dict()
        self.assertEqual(result["analyses"]["deferred"][0]["deferred_reason"], "available_after_cutoff")
        self.assertEqual(result["analyses"]["new"], [])

    def test_unresolved_admission_coverage_and_unknown_cost_survive(self):
        source = report()
        pending = replace(analysis(source), original_status=None, finished_at=None,
            availability_witness_at=None, document_json=None, current_disposition="unresolved", current_stale_reasons=())
        issue = ReviewIssue("coverage", "coverage_gap", '{"code":"feed_failed","coverage":"bounded_snapshot"}', source_id=source.source_id)
        result = build(reports=(source,), analyses=(pending,), issues=(issue,)).to_dict()
        self.assertEqual(result["unresolved_analysis_ids"], ["analysis"])
        self.assertEqual(result["unknown_reported_cost_analysis_ids"], ["analysis"])
        self.assertEqual(result["issues"][0]["detail"]["code"], "feed_failed")
        self.assertIsNone(result["analyses"]["deferred"][0]["costs"]["reported_cost_usd"])
        self.assertEqual(result["analyses"]["deferred"][0]["costs"]["estimated_cost_usd"], "0.0002")

    def test_originally_stale_result_cannot_be_reactivated(self):
        retained = replace(analysis(), original_status="stale", original_stale_reasons=("source_changed",))
        with self.assertRaises(ValueError):
            replace(retained, original_status="stale", current_disposition="current", current_stale_reasons=())
        result = build(reports=(report(),), analyses=(retained,)).to_dict()
        self.assertEqual(result["analyses"]["new"][0]["original_stale_reasons"], ["source_changed"])

    def test_complete_exposure_references_are_kept_and_overflow_rejects(self):
        versions = tuple(f"position-version-{index}" for index in range(200))
        scope = replace(SCOPE, exposure_version_ids=versions)
        result = build(scope=scope).to_dict()
        self.assertEqual(result["scope"]["exposure_version_ids"], list(versions))
        with self.assertRaisesRegex(ValueError, "do not truncate"):
            build(scope=scope, limits=replace(LIMITS, exposure_versions=199))

    def test_encoded_and_record_bounds_reject_without_hidden_selection(self):
        with self.assertRaisesRegex(ValueError, "do not truncate"):
            build(reports=(report(identity="a"), report(identity="b")), limits=replace(LIMITS, reports=1))
        with self.assertRaisesRegex(ValueError, "do not truncate"):
            build(reports=(report(),), limits=replace(LIMITS, encoded_bytes=100))
        with self.assertRaises(ValueError):
            DailyReviewLimits(True, 1, 1, 1, 1, 1)

    def test_mutating_display_copy_or_input_lists_cannot_change_candidate(self):
        supplied = [report()]
        candidate = build(reports=supplied)
        before = candidate.content_json, candidate.digest
        view = candidate.to_dict()
        view["reports"]["new"][0]["payload"]["title"] = "Changed"
        view["scope"]["exposure_version_ids"].clear()
        supplied.clear()
        self.assertEqual((candidate.content_json, candidate.digest), before)
        self.assertTrue(candidate.to_dict()["scope"]["exposure_version_ids"])
        with self.assertRaises(FrozenInstanceError):
            candidate.content_json = "{}"

    def test_order_is_deterministic_but_no_semantic_deduplication_is_invented(self):
        first, second = report(identity="a"), report(identity="b")
        self.assertEqual(build(reports=(first, second)).digest, build(reports=(second, first)).digest)
        self.assertEqual(len(build(reports=(first, second)).to_dict()["reports"]["new"]), 2)
        with self.assertRaises(ValueError):
            build(reports=(first, first))

    def test_forged_revision_digest_owner_and_diagnostic_references_reject(self):
        source, retained = report(), analysis()
        for changes in ({"source_revision_id": "missing"}, {"owner_id": "other"}, {"thesis_id": "other"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build(reports=(source,), analyses=(replace(retained, **changes),))
        with self.assertRaises(ValueError):
            replace(source, payload_digest="f" * 64)
        with self.assertRaises(ValueError):
            build(reports=(replace(source, source_contract_digest="f" * 64),))
        with self.assertRaises(ValueError):
            build(issues=(ReviewIssue("bad", "unresolved_work", "{}", analysis_id="missing"),))

    def test_historical_contract_versions_coexist_without_conflicting_identity(self):
        newer_contract = replace(CONTRACT, version_id="contract-v2", digest="d" * 64)
        old = report(identity="old")
        new = replace(report(identity="new"), source_contract_version_id=newer_contract.version_id,
                      source_contract_digest=newer_contract.digest)
        scope = replace(SCOPE, source_contracts=(newer_contract, CONTRACT))
        result = build(reports=(old, new), scope=scope).to_dict()
        self.assertEqual([item["version_id"] for item in result["scope"]["source_contracts"]],
                         ["contract-v1", "contract-v2"])
        self.assertEqual({item["source_contract_version_id"] for item in result["reports"]["new"]},
                         {"contract-v1", "contract-v2"})
        for duplicate in (CONTRACT, replace(CONTRACT, digest="f" * 64)):
            with self.subTest(duplicate=duplicate), self.assertRaises(ValueError):
                replace(SCOPE, source_contracts=(CONTRACT, duplicate))

    def test_original_context_cannot_swap_payload_or_quote(self):
        source, retained = report(), analysis()
        context = json.loads(retained.context_json)
        context["source"]["url"] = "https://example.invalid/other"
        with self.assertRaises(ValueError):
            build(reports=(source,), analyses=(replace(retained, context_json=canonical_json(context)),))
        document = json.loads(retained.document_json)
        document["attributed_facts"][0]["exact_quote"] = "A fact that was never retained."
        with self.assertRaises(ValueError):
            replace(retained, document_json=canonical_json(document))
        document = json.loads(retained.document_json)
        document["hypotheses"][0]["position_ids"] = ["invented-position"]
        with self.assertRaises(ValueError):
            replace(retained, document_json=canonical_json(document))

    def test_witness_order_and_unambiguous_json_are_required(self):
        with self.assertRaises(ValueError):
            replace(report(), availability_witness_at=START - timedelta(days=3))
        with self.assertRaises(ValueError):
            replace(analysis(), availability_witness_at=START)
        with self.assertRaises(ValueError):
            DailyReviewPeriod(START, CUTOFF, START)
        with self.assertRaises(ValueError):
            DailyReviewPeriod(START.replace(tzinfo=None), CUTOFF, PREPARED)
        for content in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":"\\ud800"}', '{"a":"\\u0000"}'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                DailyReviewCandidate(content)

    def test_future_observations_cannot_be_invented_at_preparation(self):
        future = PREPARED + timedelta(microseconds=1)
        source = report()
        for changed in (replace(source, received_at=future, availability_witness_at=None),
                        replace(source, availability_witness_at=future)):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "preparation"):
                build(reports=(changed,))
        retained = analysis(source)
        future_analyses = (
            replace(retained, created_at=future, finished_at=future, availability_witness_at=future),
            replace(retained, finished_at=future, availability_witness_at=None),
            replace(retained, availability_witness_at=future),
        )
        for changed in future_analyses:
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "preparation"):
                build(reports=(source,), analyses=(changed,))

    def test_admission_cannot_precede_receipt_but_may_precede_late_witness(self):
        source = replace(report(), received_at=START, availability_witness_at=START + timedelta(hours=3))
        with self.assertRaisesRegex(ValueError, "precede receipt"):
            build(reports=(source,), analyses=(analysis(source),))
        retained = replace(analysis(source), created_at=START + timedelta(minutes=1))
        result = build(reports=(source,), analyses=(retained,)).to_dict()
        self.assertEqual(result["analyses"]["new"][0]["analysis_id"], "analysis")

    def current_analysis(self):
        retained = analysis()
        context = json.loads(retained.context_json)
        context["approved_thesis"].update(approval_id=SCOPE.approval_id, interpretation_id=SCOPE.interpretation_id)
        context["positions"][0]["version_id"] = SCOPE.exposure_version_ids[0]
        return replace(retained, current_disposition="current", current_stale_reasons=(),
                       context_json=canonical_json(context))

    def test_current_analysis_preserves_matching_governing_references(self):
        retained = self.current_analysis()
        result = build(reports=(report(),), analyses=(retained,)).to_dict()
        self.assertEqual(result["analyses"]["new"][0]["current_disposition"], "current")

    def test_current_label_cannot_contradict_explicit_approval_or_interpretation(self):
        retained = self.current_analysis()
        for name in ("approval_id", "interpretation_id"):
            context = json.loads(retained.context_json)
            context["approved_thesis"][name] = "different-original"
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "cannot contradict"):
                build(reports=(report(),), analyses=(replace(retained, context_json=canonical_json(context)),))
            # Historical inputs remain inspectable under a stale label.
            stale = replace(retained, context_json=canonical_json(context), current_disposition="stale",
                            current_stale_reasons=("approved_meaning_changed",))
            self.assertEqual(build(reports=(report(),), analyses=(stale,)).to_dict()["analyses"]["new"][0]
                             ["original_context"]["approved_thesis"][name], "different-original")

    def test_current_label_requires_all_original_exposure_versions_without_duplicates(self):
        retained = self.current_analysis()
        for version in (None, "other-version"):
            context = json.loads(retained.context_json)
            context["positions"][0]["version_id"] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                build(reports=(report(),), analyses=(replace(retained, context_json=canonical_json(context)),))
        context = json.loads(retained.context_json)
        context["positions"].append({**context["positions"][0], "position_id": "other-position"})
        with self.assertRaisesRegex(ValueError, "must be unique"):
            build(reports=(report(),), analyses=(replace(retained, context_json=canonical_json(context)),))
        with self.assertRaisesRegex(ValueError, "complete selected"):
            build(reports=(report(),), analyses=(retained,),
                  scope=replace(SCOPE, exposure_version_ids=(*SCOPE.exposure_version_ids, "missing-from-context")))

    def test_assembly_never_obtains_clock_network_model_or_database_authority(self):
        with patch("socket.socket", side_effect=AssertionError("No network")), patch(
                "time.time", side_effect=AssertionError("No implicit clock")):
            result = build().to_dict()
        self.assertEqual(result["assembly_inference_calls"], 0)
        self.assertEqual(result["assembly_inference_cost_usd"], "0")
        self.assertNotIn("publish", result)
        self.assertNotIn("notification_intent", result)


if __name__ == "__main__":
    unittest.main()
