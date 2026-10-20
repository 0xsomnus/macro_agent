"""Safe server hints and bounded recovery calculations without live requests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from macro_agent.domain.research_recovery_policy import validate_recovery_policy
from macro_agent.monitoring import research_policy as policy
from macro_agent.monitoring.sources import SourceError


NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


class ResearchRecoveryPolicyTests(unittest.TestCase):
    def test_policy_is_exact_typed_and_cannot_be_mutated(self):
        exact = dict(policy.RECOVERY_POLICY)
        self.assertEqual(validate_recovery_policy(exact), exact)
        with self.assertRaises(TypeError):
            policy.RECOVERY_POLICY["run_deadline_seconds"] = 10
        for value in (None, [], dict(exact, max_attempts_per_question=3.0),
                      dict(exact, max_attempts_per_question=True), dict(exact, extra=1),
                      dict(exact, run_deadline_seconds=2000)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_recovery_policy(value)

    def test_delta_seconds_and_aware_http_dates_are_relative_to_response_clock(self):
        parse = lambda value: policy.parse_retry_after(value, now=NOW)
        for value, expected in (("0", 0), ("120", 120), ("  00060\t", 60),
                                ("Tue, 20 Oct 2026 12:01:30 GMT", 90),
                                ("Tue, 20 Oct 2026 14:01:30 +0200", 90),
                                ("Tue, 20 Oct 2026 11:00:00 GMT", 0)):
            with self.subTest(value=value):
                self.assertEqual(parse(value), expected)
        self.assertEqual(policy.parse_retry_after("Tue, 20 Oct 2026 12:01:30 GMT",
                         now=NOW + timedelta(microseconds=1)), 90)

    def test_bad_unbounded_or_naive_hints_cannot_enter_safe_metadata(self):
        for value in (None, True, 2, "", "-10", "+10", "1.5", "1e9", "٣٠", "∞",
                      "Tue, 20 Oct 2026 12:01:30", "Tue, 20 Oct 12026 12:01:30 GMT",
                      "120\r\nsecret", "120, 130", "9" * 8191):
            with self.subTest(value=value):
                self.assertIsNone(policy.parse_retry_after(value, now=NOW))
        with self.assertRaises(ValueError):
            policy.parse_retry_after("120", now=NOW.replace(tzinfo=None))

    def test_long_valid_hints_block_the_run_instead_of_being_capped_to_early_retry(self):
        for value in ("1801", "86400", "99999999999999999999999999999999", "9" * 129,
                      "Fri, 31 Dec 9999 23:59:59 GMT"):
            with self.subTest(value=value):
                delay = policy.parse_retry_after(value, now=NOW)
                self.assertGreater(delay, 1800)
                self.assertLessEqual(delay, policy.MAX_RETRY_AFTER_SECONDS)
                self.assertIsNone(policy.retry_due_at(finished_at=NOW, attempt_number=1,
                    deadline_at=NOW + timedelta(seconds=1800), retry_after_seconds=delay))
                self.assertGreater(policy.cooldown_until(finished_at=NOW, attempt_number=1,
                    retry_after_seconds=delay), NOW + timedelta(seconds=1800))

    def test_server_hints_never_reduce_backoff_and_deadline_is_exclusive(self):
        self.assertEqual(policy.retry_delay_seconds(1), 30)
        self.assertEqual(policy.retry_delay_seconds(2), 60)
        self.assertEqual(policy.retry_delay_seconds(1, 2), 30)
        self.assertEqual(policy.retry_delay_seconds(2, 150), 150)
        self.assertEqual(policy.retry_due_at(finished_at=NOW, attempt_number=2,
            deadline_at=NOW + timedelta(seconds=61)), NOW + timedelta(seconds=60))
        self.assertIsNone(policy.retry_due_at(finished_at=NOW, attempt_number=2,
            deadline_at=NOW + timedelta(seconds=60)))
        self.assertIsNone(policy.retry_due_at(finished_at=NOW, attempt_number=1,
            deadline_at=NOW - timedelta(seconds=1)))
        for number in (0, 4, True, 1.0, 1_000_000):
            with self.subTest(number=number), self.assertRaises(ValueError):
                policy.retry_delay_seconds(number)

    def test_safe_delay_is_an_optional_bounded_integer_without_header_text(self):
        self.assertIsNone(SourceError("timeout").retry_after_seconds)
        error = SourceError("rate_limited", retry_after_seconds=86400)
        self.assertEqual(error.retry_after_seconds, 86400)
        self.assertEqual(str(error), "Source capture failed (rate_limited).")
        for delay in (-1, True, 1.5, "1", policy.MAX_RETRY_AFTER_SECONDS + 1):
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                SourceError("rate_limited", retry_after_seconds=delay)

    def test_cooldown_saturates_only_at_representable_datetime_maximum(self):
        maximum = datetime.max.replace(tzinfo=timezone.utc)
        self.assertEqual(policy.cooldown_until(finished_at=NOW, attempt_number=1,
            retry_after_seconds=policy.MAX_RETRY_AFTER_SECONDS), maximum)
        self.assertEqual(policy.cooldown_until(finished_at=maximum - timedelta(seconds=1),
            attempt_number=1), maximum)


if __name__ == "__main__":
    unittest.main()
