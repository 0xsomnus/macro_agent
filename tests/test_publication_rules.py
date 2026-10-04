"""Publication rules independently executable without a database or model."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from domain_fixture import correction_pin, fixture_case
from macro_agent.domain.models import ContextSnapshot, canonical_json
from macro_agent.domain.publication import BriefState, FactClaim, decide_publication


class PublicationRuleTests(unittest.TestCase):
    def setUp(self):
        self.candidate, dependencies = fixture_case()
        self.current = BriefState(self.candidate.owner_id, 0, dependencies,
                                  self.candidate.snapshot.cutoff)

    def test_exact_current_inputs_can_publish(self):
        decision = decide_publication(self.candidate, self.current, self.current.changed_at)
        self.assertEqual(decision.status, "current")
        self.assertFalse(decision.reassessment_required)

    def test_old_source_revision_is_history_and_requests_reassessment(self):
        correction = correction_pin()
        heads = tuple(correction if pin.role == correction.role else pin
                      for pin in self.current.dependencies)
        decision = decide_publication(self.candidate, replace(self.current,
            dependencies=heads, changed_at=correction.known_at), correction.known_at)
        self.assertEqual(decision.status, "superseded")
        self.assertEqual(decision.reasons, ("changed:event_revision",))
        self.assertTrue(decision.reassessment_required)

    def test_older_run_with_identical_inputs_cannot_replace_newer_publication(self):
        decision = decide_publication(self.candidate, replace(self.current, generation=1),
                                      self.current.changed_at)
        self.assertEqual(decision.reasons, ("newer_publication",))
        self.assertFalse(decision.reassessment_required)

    def test_future_publication_generation_is_invalid_input(self):
        with self.assertRaises(ValueError):
            decide_publication(replace(self.candidate, expected_generation=1),
                               self.current, self.current.changed_at)

    def test_every_governing_role_can_invalidate_inflight_analysis(self):
        for role in ("activation", "exposure", "source_contract", "coverage", "macro_context",
                     "rules", "entitlements", "model", "prompt"):
            with self.subTest(role=role):
                heads = tuple(replace(pin, version_id="new:" + pin.version_id)
                              if pin.role == role else pin for pin in self.current.dependencies)
                decision = decide_publication(self.candidate,
                    replace(self.current, dependencies=heads), self.current.changed_at)
                self.assertEqual(decision.reasons, ("changed:" + role,))

    def test_cross_owner_publication_fails(self):
        with self.assertRaises(PermissionError):
            decide_publication(self.candidate, replace(self.current, owner_id="another-owner"),
                               self.current.changed_at)

    def test_backdating_cannot_hide_current_state(self):
        with self.assertRaises(ValueError):
            decide_publication(self.candidate, self.current,
                               self.current.changed_at - timedelta(seconds=1))

    def test_missing_pin_cannot_bypass_currentness_check(self):
        snapshot = ContextSnapshot("incomplete", self.candidate.snapshot.cutoff,
                                   self.candidate.snapshot.dependencies[:-1])
        with self.assertRaises(ValueError):
            replace(self.candidate, snapshot=snapshot)

    def test_factual_notice_requires_exact_source_field(self):
        with self.assertRaises(ValueError):
            replace(self.candidate, fact_claims=(FactClaim("reported_measure", "9.9"),))
        with self.assertRaises(ValueError):
            replace(self.candidate, fact_claims=())

    def test_json_fact_values_reject_duplicate_keys_and_nonfinite_numbers(self):
        for value in ('{"value":1,"value":2}', "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FactClaim("reported_measure", value)

    def test_source_permission_is_exact_membership_not_substring(self):
        contract = replace(self.candidate.source_contract,
                           content_json=canonical_json({"permitted_uses": "not_display"}))
        dependencies = tuple(replace(pin, digest=contract.digest)
            if pin.role == "source_contract" else pin for pin in self.candidate.snapshot.dependencies)
        snapshot = replace(self.candidate.snapshot, dependencies=dependencies)
        with self.assertRaises(ValueError):
            replace(self.candidate, source_contract=contract, snapshot=snapshot)

    def test_revoked_display_and_low_screening_block_notice(self):
        contract = replace(self.candidate.source_contract,
                           content_json=canonical_json({"permitted_uses": ["capture"]}))
        dependencies = tuple(replace(pin, digest=contract.digest)
            if pin.role == "source_contract" else pin for pin in self.candidate.snapshot.dependencies)
        with self.assertRaises(PermissionError):
            replace(self.candidate, source_contract=contract,
                    snapshot=replace(self.candidate.snapshot, dependencies=dependencies))
        with self.assertRaises(ValueError):
            replace(self.candidate, screening=replace(self.candidate.screening,
                                                      thesis_impact=False, potential_severity="low"))

    def test_retry_identity_is_stable_and_nonmaterial_update_has_no_intent(self):
        self.assertEqual(self.candidate.intent_id, fixture_case()[0].intent_id)
        self.assertIsNone(replace(self.candidate, material_change=False).intent_id)
        self.assertNotEqual(self.candidate.intent_id,
                            replace(self.candidate, assessment_id="next-version").intent_id)

    def test_equivalent_pin_order_cannot_change_immutable_retry_content(self):
        reordered = replace(self.candidate, snapshot=replace(self.candidate.snapshot,
                            dependencies=tuple(reversed(self.candidate.snapshot.dependencies))))
        self.assertEqual(self.candidate.digest, reordered.digest)
        self.assertEqual(self.candidate.intent_id, reordered.intent_id)


if __name__ == "__main__":
    unittest.main()
