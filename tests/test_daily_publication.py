"""Daily authority rules preserve the retained review instead of rewriting it."""

from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import sys
import unittest
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from macro_agent.domain.daily_publication import (
    DailyPublicationCandidate, DailyPublicationState, decide_daily_publication,
)
from macro_agent.domain.models import canonical_json, text_digest
from test_daily_review import CUTOFF, PREPARED, SCOPE, analysis, build, report


def identity(number):
    return str(UUID(int=number))


OWNER, THESIS, APPROVAL, REVIEW, CONTEXT, COMMAND = (identity(i) for i in range(1, 7))
SCOPE = replace(SCOPE, owner_id=OWNER, thesis_id=THESIS, approval_id=APPROVAL)


def candidate(*, retained=False):
    if retained:
        source = report()
        prior = analysis(source)
        context = json.loads(prior.context_json)
        context["approved_thesis"]["thesis_id"] = THESIS
        prior = replace(prior, owner_id=OWNER, thesis_id=THESIS,
                        context_json=canonical_json(context))
        content = build(scope=SCOPE, reports=(source,), analyses=(prior,)).content_json
    else:
        content = build(scope=SCOPE).content_json
    return DailyPublicationCandidate(COMMAND, OWNER, THESIS, "daily:" + THESIS, REVIEW,
        CONTEXT, CUTOFF, text_digest(content), APPROVAL, SCOPE.exposure_digest, 0, content)


def state(**changes):
    result = DailyPublicationState(OWNER, THESIS, 0, PREPARED, REVIEW, CUTOFF, None, ())
    return replace(result, **changes)


class DailyPublicationTests(unittest.TestCase):
    def test_quiet_review_can_publish_without_inventing_urgent_event_or_market_calm(self):
        value = candidate()
        decision = decide_daily_publication(value, state(), PREPARED)
        self.assertEqual(decision.status, "current")
        payload = json.loads(value.payload)
        self.assertEqual(payload["kind"], "daily_evidence_review")
        self.assertEqual(payload["content"]["new_eligible_report_count"], 0)
        self.assertIn("does not establish", payload["content"]["limitations"][0])
        self.assertNotIn("screening", payload)

    def test_original_model_labels_source_payloads_and_uncertainty_are_preserved(self):
        value = candidate(retained=True)
        content = json.loads(value.content_json)
        self.assertEqual(json.loads(value.payload)["content"], content)
        prior = content["analyses"]["new"][0]
        self.assertEqual(prior["original_status"], "analysed")
        self.assertEqual(prior["current_disposition"], "stale")
        self.assertEqual(prior["current_stale_reasons"], ["approved_meaning_changed"])
        self.assertIsNone(prior["costs"]["reported_cost_usd"])
        self.assertTrue(prior["document"]["hypotheses"][0]["uncertainty"])
        self.assertEqual(content["reports"]["new"][0]["payload"], json.loads(report().payload_json))

    def test_candidate_rejects_changed_source_fact_even_with_recomputed_review_digest(self):
        value = candidate(retained=True)
        body = json.loads(value.content_json)
        body["reports"]["new"][0]["payload"]["title"] = "Manufactured claim"
        changed = canonical_json(body)
        with self.assertRaisesRegex(ValueError, "digest"):
            replace(value, content_json=changed, review_digest=text_digest(changed))

    def test_candidate_rejects_reclassified_deferred_evidence(self):
        value = candidate(retained=True)
        body = json.loads(value.content_json)
        body["reports"]["deferred"] = body["reports"]["new"]
        body["reports"]["new"] = []
        changed = canonical_json(body)
        with self.assertRaisesRegex(ValueError, "classifications"):
            replace(value, content_json=changed, review_digest=text_digest(changed))

    def test_candidate_rejects_omitted_original_context_and_added_generated_claim(self):
        value = candidate(retained=True)
        body = json.loads(value.content_json)
        del body["analyses"]["new"][0]["original_context"]
        changed = canonical_json(body)
        with self.assertRaisesRegex(ValueError, "complete retained"):
            replace(value, content_json=changed, review_digest=text_digest(changed))
        body = json.loads(value.content_json)
        body["generated_recommendation"] = "Buy now"
        changed = canonical_json(body)
        with self.assertRaisesRegex(ValueError, "retained fields"):
            replace(value, content_json=changed, review_digest=text_digest(changed))

    def test_candidate_rejects_false_current_label_on_original_stale_analysis(self):
        value = candidate(retained=True)
        body = json.loads(value.content_json)
        body["analyses"]["new"][0]["current_disposition"] = "current"
        changed = canonical_json(body)
        with self.assertRaises(ValueError):
            replace(value, content_json=changed, review_digest=text_digest(changed))

    def test_complete_body_and_scope_must_match_digest_and_exact_identity(self):
        value = candidate()
        for changes in ({"review_digest": "0" * 64}, {"approval_id": identity(99)},
                        {"owner_id": identity(99)}, {"cutoff": CUTOFF + timedelta(seconds=1)}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "exact retained"):
                replace(value, **changes)

    def test_duplicate_json_keys_and_generation_coercion_are_rejected(self):
        value = candidate()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            replace(value, content_json='{"scope":{},"scope":{}}')
        for wrong in (True, False, "0", -1, 0.0):
            with self.subTest(wrong=wrong), self.assertRaisesRegex(ValueError, "generation"):
                replace(value, expected_generation=wrong)

    def test_dependency_change_takes_priority_over_newer_review_and_generation(self):
        current = state(generation=1, latest_review_id=identity(88),
            latest_review_cutoff=CUTOFF + timedelta(minutes=1),
            stale_reasons=("source_permission_changed", "approved_meaning_changed"))
        decision = decide_daily_publication(candidate(), current, PREPARED)
        self.assertEqual(decision.reasons, ("approved_meaning_changed", "source_permission_changed"))
        self.assertTrue(decision.reassessment_required)

    def test_late_older_review_cannot_replace_latest_retained_review(self):
        current = state(latest_review_id=identity(88), latest_review_cutoff=CUTOFF + timedelta(minutes=1))
        decision = decide_daily_publication(candidate(), current, PREPARED)
        self.assertEqual(decision.reasons, ("newer_retained_review",))

    def test_watermark_survives_missing_current_pointer_and_bars_reactivation(self):
        for watermark in (CUTOFF, CUTOFF + timedelta(minutes=1)):
            with self.subTest(watermark=watermark):
                decision = decide_daily_publication(candidate(), state(latest_published_cutoff=watermark), PREPARED)
                self.assertEqual(decision.reasons, ("already_published_cutoff",))

    def test_same_context_late_generation_cannot_replace_newer_publication(self):
        decision = decide_daily_publication(candidate(), state(generation=1), PREPARED)
        self.assertEqual(decision.reasons, ("newer_publication",))
        self.assertFalse(decision.reassessment_required)

    def test_owner_scope_future_generation_and_preparation_clock_are_strict(self):
        with self.assertRaises(PermissionError):
            decide_daily_publication(candidate(), state(owner_id=identity(88)), PREPARED)
        with self.assertRaisesRegex(ValueError, "unobserved"):
            decide_daily_publication(replace(candidate(), expected_generation=1), state(), PREPARED)
        with self.assertRaisesRegex(ValueError, "protected input"):
            decide_daily_publication(candidate(), state(), PREPARED - timedelta(microseconds=1))

    def test_identity_replay_is_stable_but_changed_command_changes_candidate_digest(self):
        value = candidate()
        self.assertEqual(value.digest, candidate().digest)
        self.assertEqual(value.intent_id, candidate().intent_id)
        changed = replace(value, command_id=identity(88))
        self.assertNotEqual(value.digest, changed.digest)
        self.assertEqual(value.intent_id, changed.intent_id)
        self.assertEqual(value.assessment_id, "daily:" + REVIEW)


if __name__ == "__main__":
    unittest.main()
