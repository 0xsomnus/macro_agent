"""Versioned source-recovery contract shared by admission and context readers."""

from types import MappingProxyType


RECOVERY_POLICY_VERSION = "research-source-recovery-2026-10-20-v1"
RECOVERY_POLICY = MappingProxyType({
    "policy_version": RECOVERY_POLICY_VERSION,
    "max_attempts_per_question": 3,
    "transport_timeout_seconds": 20,
    "minimum_spacing_seconds": 5,
    "base_backoff_seconds": 30,
    "maximum_backoff_seconds": 300,
    "run_deadline_seconds": 1800,
})

# The complete representable datetime interval. Saturating a huge valid hint
# at this bound never permits this 30-minute research graph to retry early.
MAX_RETRY_AFTER_SECONDS = 315_537_897_599

# Only these source outcomes can authorize another bounded source admission.
# Invalid payloads, rights changes and paid-node uncertainty remain ineligible.
RETRY_REASONS = MappingProxyType({
    "timeout": "timeout",
    "transport_error": "unavailable",
    "unavailable": "unavailable",
    "rate_limited": "rate_limited",
    "capture_response_not_recorded": "timeout",
    "capture_admission_expired": "timeout",
    "capture_lease_expired": "timeout",
})


def validate_retry_after(value):
    if value is not None and (type(value) is not int or not 0 <= value <= MAX_RETRY_AFTER_SECONDS):
        raise ValueError("retry delay must be a bounded nonnegative integer")
    return value


def validate_recovery_policy(value):
    """Reject coercion, extra fields and changes under the same identity."""
    if (type(value) is not dict or value != dict(RECOVERY_POLICY)
            or any(type(value[key]) is not type(expected) for key, expected in RECOVERY_POLICY.items())):
        raise ValueError("unknown research source-recovery policy")
    return dict(value)
