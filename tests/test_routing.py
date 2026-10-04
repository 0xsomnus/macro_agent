"""Behavioral regressions for conservative routing and fixture accumulation."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from macro_agent.domain.routing import (
    EvidenceContribution,
    Route,
    RoutingState,
    Screening,
    Severity,
    accumulate_evidence,
    route_event,
)


def screen(**changes):
    fields = dict(
        resolved=True, credible=True, urgent=False, potential_severity="low",
        thesis_impact=False, trade_impact=False, plausible_transmission=False,
        broad_disruption=False, novel=False, classifier_available=True,
    )
    fields.update(changes)
    return Screening(**fields)


class RoutingTests(unittest.TestCase):
    def test_novelty_alone_changes_neither_route_nor_interruption(self):
        ordinary = route_event(screen())
        novel = route_event(screen(novel=True, urgent=True))
        self.assertEqual(ordinary, novel)
        self.assertEqual(novel.route, Route.AUDIT_ONLY)
        self.assertEqual(novel.state, RoutingState.RESOLVED_LOW)

    def test_classifier_failure_and_uncertainty_never_resolve_low(self):
        for changes in ({"classifier_available": False}, {"resolved": False}):
            with self.subTest(changes=changes):
                decision = route_event(screen(**changes))
                self.assertEqual(decision.route, Route.UNRESOLVED_QUEUE)
                self.assertEqual(decision.state, RoutingState.POTENTIAL_OR_UNRESOLVED)
                self.assertFalse(decision.early_notice)

    def test_trade_impact_can_investigate_without_thesis_impact(self):
        decision = route_event(screen(trade_impact=True, classifier_available=False))
        self.assertEqual(decision.route, Route.INVESTIGATE)
        self.assertTrue(decision.analysis_required)
        self.assertIn("trade_impact_candidate", decision.reasons)
        self.assertIn("classifier_unavailable", decision.reasons)

    def test_credible_severe_surprise_can_bypass_mapped_impacts(self):
        for severity in (Severity.HIGH, Severity.EXTREME):
            for path in ("plausible_transmission", "broad_disruption"):
                with self.subTest(severity=severity, path=path):
                    decision = route_event(screen(
                        potential_severity=severity, resolved=False, **{path: True},
                    ))
                    self.assertEqual(decision.route, Route.INVESTIGATE)
                    self.assertIn("credible_severe_surprise", decision.reasons)
                    self.assertFalse(decision.early_notice)

    def test_severity_without_credible_significance_path_does_not_bypass(self):
        for changes in (
            {"potential_severity": "extreme"},
            {"potential_severity": "extreme", "credible": False, "broad_disruption": True},
            {"potential_severity": "low", "plausible_transmission": True, "novel": True},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(route_event(screen(**changes)).route, Route.AUDIT_ONLY)

    def test_credible_urgent_unresolved_significance_can_qualify_early_notice(self):
        decision = route_event(screen(
            resolved=False, classifier_available=False, urgent=True,
            potential_severity="high", broad_disruption=True,
        ))
        self.assertEqual(decision.route, Route.INVESTIGATE)
        self.assertTrue(decision.early_notice)
        self.assertEqual(decision.state, RoutingState.POTENTIAL_OR_UNRESOLVED)

    def test_urgency_without_significance_cannot_interrupt(self):
        self.assertFalse(route_event(screen(urgent=True, resolved=False)).early_notice)
        self.assertFalse(route_event(screen(urgent=True, trade_impact=True, credible=False)).early_notice)

    def test_screening_rejects_truthy_non_booleans_and_unknown_severity(self):
        for field in (
            "resolved", "credible", "urgent", "thesis_impact", "trade_impact",
            "plausible_transmission", "broad_disruption", "novel", "classifier_available",
        ):
            with self.subTest(field=field), self.assertRaises(TypeError):
                screen(**{field: 1})
        with self.assertRaises(ValueError):
            screen(potential_severity="catastrophic")
        with self.assertRaises(TypeError):
            screen(potential_severity=1)

    def test_screening_and_decision_are_immutable_typed_records(self):
        screening = screen()
        with self.assertRaises(FrozenInstanceError):
            screening.credible = False
        with self.assertRaises(FrozenInstanceError):
            route_event(screening).early_notice = True
        with self.assertRaises(TypeError):
            route_event({"resolved": True})


class AccumulationTests(unittest.TestCase):
    def setUp(self):
        self.cutoff = datetime(2026, 10, 3, 9, tzinfo=timezone.utc)

    def contribution(self, event_id, weight, **changes):
        fields = dict(
            event_id=event_id, driver_id="real_yields",
            known_at=self.cutoff, signed_fixture_weight=weight,
        )
        fields.update(changes)
        return EvidenceContribution(**fields)

    def accumulate(self, contributions, **changes):
        fields = dict(driver_id="real_yields", cutoff=self.cutoff, window_seconds=3600, threshold=1.0)
        fields.update(changes)
        return accumulate_evidence(contributions, **fields)

    def test_distinct_developments_accumulate_and_offsets_reduce_score(self):
        first = self.contribution("policy-a", 0.6)
        second = self.contribution("policy-b", 0.6)
        offset = self.contribution("offset-c", -0.7)
        self.assertFalse(self.accumulate([first]).material)
        self.assertTrue(self.accumulate([first, second]).material)
        result = self.accumulate([first, second, offset])
        self.assertFalse(result.material)
        self.assertAlmostEqual(result.signed_fixture_score, 0.5)

    def test_duplicate_story_cannot_reinforce_evidence(self):
        contribution = self.contribution("same-event", 0.6)
        result = self.accumulate([contribution, replace(contribution)])
        self.assertEqual(result.event_ids, ("same-event",))
        self.assertFalse(result.material)
        self.assertEqual(result.signed_fixture_score, 0.6)

    def test_conflicting_duplicate_requires_explicit_revision_resolution(self):
        contribution = self.contribution("same-event", 0.6)
        with self.assertRaisesRegex(ValueError, "explicit event revision"):
            self.accumulate([contribution, replace(contribution, signed_fixture_weight=0.8)])

    def test_window_boundaries_are_inclusive_and_future_knowledge_excluded(self):
        contributions = [
            self.contribution("lower", 0.5, known_at=self.cutoff - timedelta(hours=1)),
            self.contribution("upper", 0.5),
            self.contribution("old", 100, known_at=self.cutoff - timedelta(hours=1, microseconds=1)),
            self.contribution("future", 100, known_at=self.cutoff + timedelta(microseconds=1)),
            self.contribution("other-driver", 100, driver_id="growth"),
        ]
        result = self.accumulate(contributions)
        self.assertEqual(result.event_ids, ("lower", "upper"))
        self.assertEqual(result.signed_fixture_score, 1.0)
        self.assertTrue(result.material)

    def test_replay_ignores_future_conflicting_observation(self):
        original = self.contribution("event", 0.6)
        future = replace(original, signed_fixture_weight=0.8, known_at=self.cutoff + timedelta(seconds=1))
        self.assertEqual(self.accumulate([original, future]).signed_fixture_score, 0.6)

    def test_offset_direction_and_input_order_are_preserved(self):
        contributions = [self.contribution("z", -0.6), self.contribution("a", -0.6)]
        result = self.accumulate(contributions)
        self.assertTrue(result.material)
        self.assertEqual(result.signed_fixture_score, -1.2)
        self.assertEqual(result, self.accumulate(reversed(contributions)))

    def test_aware_instants_normalize_before_duplicate_comparison(self):
        original = self.contribution("event", 0.6)
        east_africa = replace(original, known_at=self.cutoff.astimezone(timezone(timedelta(hours=3))))
        self.assertEqual(original, east_africa)
        self.assertEqual(self.accumulate([original, east_africa]).signed_fixture_score, 0.6)

    def test_naive_datetime_and_nonfinite_or_boolean_weights_are_rejected(self):
        with self.assertRaises(ValueError):
            self.contribution("event", 0.6, known_at=datetime(2026, 10, 3, 9))
        with self.assertRaises(ValueError):
            self.accumulate([], cutoff=datetime(2026, 10, 3, 9))
        for weight in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                self.contribution("event", weight)
        with self.assertRaises(TypeError):
            self.contribution("event", True)

    def test_invalid_configuration_and_overflow_cannot_create_materiality(self):
        for changes in (
            {"window_seconds": 0}, {"window_seconds": -1},
            {"threshold": 0}, {"threshold": -1}, {"threshold": float("nan")},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.accumulate([], **changes)
        for changes in ({"window_seconds": True}, {"threshold": True}):
            with self.subTest(changes=changes), self.assertRaises(TypeError):
                self.accumulate([], **changes)
        with self.assertRaises(ValueError):
            self.accumulate([self.contribution("a", 1e308), self.contribution("b", 1e308)])

    def test_contributions_and_result_are_immutable_and_empty_window_is_low(self):
        contribution = self.contribution("event", 0.6)
        with self.assertRaises(FrozenInstanceError):
            contribution.signed_fixture_weight = 5
        result = self.accumulate([])
        self.assertEqual(result.event_ids, ())
        self.assertEqual(result.signed_fixture_score, 0)
        self.assertFalse(result.material)
        with self.assertRaises(FrozenInstanceError):
            result.material = True
        with self.assertRaises(TypeError):
            self.accumulate([{"event_id": "event"}])


if __name__ == "__main__":
    unittest.main()
