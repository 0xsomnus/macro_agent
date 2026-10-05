"""Paper exposure missingness, exact declarations and lifecycle invariants."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from macro_agent.domain.exposure import (
    PaperPositionVersion, quantity_string, validate_position_transition, version_content,
)
from macro_agent.domain.models import canonical_json, text_digest


AT = datetime(2026, 10, 5, 6, tzinfo=timezone.utc)


def position(**changes):
    values = {
        "version_id": "position-v1", "position_id": "position", "owner_id": "owner",
        "thesis_id": "thesis", "approval_id": "approval-v1", "underlying": "XAU",
        "direction": "long", "accepted_at": AT,
    }
    return PaperPositionVersion(**{**values, **changes})


class PaperExposureTests(unittest.TestCase):
    def test_missing_exposure_is_explicit_and_cannot_claim_verified_mapping(self):
        item = position(underlying="DXY")
        self.assertIsNone(item.product_id)
        self.assertIsNone(item.quantity)
        self.assertEqual(item.mapping_status, "user_declared_unverified")
        self.assertIn("product_id", item.missing_fields)
        self.assertIn("venue", item.missing_fields)
        self.assertNotIn("expiry", item.missing_fields)

    def test_actual_identity_does_not_imply_coverage_or_require_an_allowlist(self):
        item = position(underlying="Global supply disruption", product_id=" User's product ",
                        venue=" User's venue ")
        self.assertEqual(item.product_id, " User's product ")
        self.assertEqual(item.mapping_status, "user_declared_unverified")

    def test_declarations_preserve_exact_unicode_spacing_and_fractional_zeroes(self):
        item = position(product_id="  cafe\u0301\r\ncontract  ", horizon=" months ",
                        quantity="1.00", quantity_unit=" contracts ")
        self.assertEqual(item.product_id.encode("utf-8"), "  cafe\u0301\r\ncontract  ".encode("utf-8"))
        self.assertEqual(item.quantity, "1.00")
        self.assertEqual(item.quantity_unit, " contracts ")
        self.assertNotEqual(item.digest, replace(item, product_id=item.product_id.strip()).digest)
        self.assertNotEqual(item.digest, replace(item, quantity="1").digest)

    def test_version_is_frozen_and_derived_payload_is_detached(self):
        item = position()
        with self.assertRaises(FrozenInstanceError):
            item.direction = "short"
        detached = version_content(item)
        detached["direction"] = "short"
        self.assertEqual(item.direction, "long")
        self.assertEqual(item.digest, text_digest(canonical_json(version_content(item))))

    def test_only_paper_and_explicit_direction_and_state_are_accepted(self):
        for changes in ({"paper": False}, {"paper": 1}, {"direction": "LONG"},
                        {"direction": True}, {"status": "unknown"}, {"status": 1}):
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                position(**changes)

    def test_nullable_strings_reject_blank_nonstring_nul_invalid_unicode_and_limits(self):
        for name in ("underlying", "product_id", "venue", "quote_currency", "horizon"):
            for bad in (" ", 1, True, "bad\x00identity", "\ud800"):
                with self.subTest(name=name, bad=repr(bad)), self.assertRaises((TypeError, ValueError)):
                    position(**{name: bad})
        with self.assertRaises(ValueError):
            position(underlying="x" * 129)
        with self.assertRaises(ValueError):
            position(horizon="x" * 1001)

    def test_expiry_accepts_calendar_date_without_inventing_instrument_type(self):
        self.assertEqual(position(expiry="2028-02-29").expiry, "2028-02-29")
        for bad in ("2026-02-29", "2026-13-01", "2026-10-5", "20261005",
                    "2026-10-05T00:00:00Z", "0000-01-01", 20261005):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                position(expiry=bad)

    def test_quantity_and_explicit_unit_are_optional_as_a_pair(self):
        self.assertIsNone(position().quantity)
        for values in ({"quantity": "1"}, {"quantity_unit": "contracts"},
                       {"quantity": "1", "quantity_unit": " "}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                position(**values)

    def test_quantity_rejects_coercion_nonfinite_signs_exponents_leading_zeroes_and_zero(self):
        for bad in (1, 1.0, True, Decimal("1"), "NaN", "Infinity", "1e2", "+1", "-1",
                    ".1", "1.", "01", "00.1", " 1", "1 ", "0", "0.000", "1\n"):
            with self.subTest(bad=repr(bad)), self.assertRaises((TypeError, ValueError)):
                quantity_string(bad)

    def test_quantity_precision_bounds_are_explicit(self):
        for value in ("1", "1.00", "0.000000000001", "9" * 28,
                      "9" * 16 + "." + "9" * 12):
            self.assertEqual(quantity_string(value), value)
        for value in ("9" * 29, "1.0000000000001", "9" * 17 + "." + "9" * 12):
            with self.subTest(value=value), self.assertRaises(ValueError):
                quantity_string(value)

    def test_effective_acceptance_time_is_aware_and_normalizes_timezone(self):
        local = AT.astimezone(timezone(timedelta(hours=3)))
        self.assertEqual(position(accepted_at=local).accepted_at, AT)
        with self.assertRaises(ValueError):
            position(accepted_at=AT.replace(tzinfo=None))

    def test_digest_binds_reviewed_approval_parent_and_temporal_state(self):
        original = position()
        for change in ({"approval_id": "approval-v2"}, {"accepted_at": AT + timedelta(seconds=1)},
                       {"parent_version_id": "previous"}, {"status": "closed"}):
            with self.subTest(change=change):
                self.assertNotEqual(original.digest, replace(original, **change).digest)


class PaperPositionLifecycleTests(unittest.TestCase):
    def next(self, previous, **changes):
        return replace(previous, version_id="position-v2", parent_version_id=previous.version_id,
                       **changes)

    def test_revision_can_update_exposure_and_review_a_new_approval(self):
        previous = position()
        changed = self.next(previous, direction="short", approval_id="approval-v2")
        validate_position_transition(previous, changed)
        self.assertEqual(previous.direction, "long")
        self.assertEqual(previous.approval_id, "approval-v1")

    def test_closed_position_cannot_reopen_or_append_another_close(self):
        previous = position()
        closed = self.next(previous, status="closed")
        validate_position_transition(previous, closed)
        for status in ("open", "closed"):
            following = replace(closed, version_id="position-v3", parent_version_id=closed.version_id,
                                status=status)
            with self.subTest(status=status), self.assertRaises(ValueError):
                validate_position_transition(closed, following)

    def test_close_preserves_exposure_even_if_reviewed_approval_changed(self):
        previous = position(quantity="1.00", quantity_unit="contracts")
        validate_position_transition(previous, self.next(previous, status="closed", approval_id="new"))
        for change in ({"direction": "short"}, {"quantity": "2"}, {"horizon": "years"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_position_transition(previous, self.next(previous, status="closed", **change))

    def test_transition_requires_new_identity_scope_parent_and_monotonic_clock(self):
        previous = position()
        valid = self.next(previous)
        for changes in ({"version_id": previous.version_id}, {"parent_version_id": None},
                        {"owner_id": "other"}, {"thesis_id": "other"}, {"position_id": "other"},
                        {"accepted_at": AT - timedelta(seconds=1)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_position_transition(previous, replace(valid, **changes))


if __name__ == "__main__":
    unittest.main()
