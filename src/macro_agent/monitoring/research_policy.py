"""Pinned source-only recovery bounds, without transport or persistence work.

The transport makes one exchange. Application admission owns pacing, attempts
and deadline enforcement. A server delay can extend a provider cooldown beyond
the research run's deadline; it is never shortened to permit an earlier retry.
"""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import math
import re
from macro_agent.domain.research_recovery_policy import (
    MAX_RETRY_AFTER_SECONDS, RECOVERY_POLICY, RECOVERY_POLICY_VERSION, RETRY_REASONS,
    validate_recovery_policy, validate_retry_after,
)
_MAX_RETRY_TEXT = str(MAX_RETRY_AFTER_SECONDS)
# Match the underlying aiohttp field-size bound. Large legal delta-seconds
# within that transport bound still become a blocking delay, not a short retry.
_MAX_HEADER_LENGTH = 8190


def _utc(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("recovery clock must be an aware datetime")
    try:
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise ValueError("recovery clock must be representable in UTC") from None


def parse_retry_after(value, *, now):
    """Return bounded seconds from delta-seconds or an aware HTTP date.

    Do not retain untrusted header text. Invalid, ambiguous and oversized
    headers are absent hints, never remote exception messages. Numeric values
    are compared as strings before conversion to avoid unbounded integers.
    """
    now = _utc(now)
    if (type(value) is not str or len(value) > _MAX_HEADER_LENGTH
            or any(ord(char) < 32 and char != "\t" or ord(char) > 126 for char in value)):
        return None
    value = value.strip(" \t")
    if re.fullmatch(r"[0-9]+", value):
        normalized = value.lstrip("0") or "0"
        if (len(normalized) > len(_MAX_RETRY_TEXT)
                or len(normalized) == len(_MAX_RETRY_TEXT) and normalized > _MAX_RETRY_TEXT):
            return MAX_RETRY_AFTER_SECONDS
        return int(normalized)
    try:
        stamp = parsedate_to_datetime(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        seconds = math.ceil((_utc(stamp) - now).total_seconds())
    except (TypeError, ValueError, OverflowError, IndexError):
        return None
    return max(0, min(seconds, MAX_RETRY_AFTER_SECONDS))


def retry_delay_seconds(attempt_number, retry_after_seconds=None):
    """Use a conservative bounded backoff without shortening server hints."""
    if type(attempt_number) is not int or not 1 <= attempt_number <= RECOVERY_POLICY["max_attempts_per_question"]:
        raise ValueError("attempt number is outside the recovery policy")
    validate_retry_after(retry_after_seconds)
    backoff = min(RECOVERY_POLICY["maximum_backoff_seconds"],
                  RECOVERY_POLICY["base_backoff_seconds"] * 2 ** (attempt_number - 1))
    return max(backoff, retry_after_seconds or 0, RECOVERY_POLICY["minimum_spacing_seconds"])


def cooldown_until(*, finished_at, attempt_number, retry_after_seconds=None):
    """Provider cooldown can outlast a run, with safe datetime saturation."""
    finished_at = _utc(finished_at)
    delay = retry_delay_seconds(attempt_number, retry_after_seconds)
    maximum = datetime.max.replace(tzinfo=timezone.utc)
    if delay > (maximum - finished_at).total_seconds():
        return maximum
    try:
        return finished_at + timedelta(seconds=delay)
    except OverflowError:
        return maximum


def retry_due_at(*, finished_at, attempt_number, deadline_at, retry_after_seconds=None):
    """None means the required cooldown cannot fit inside this run's budget."""
    finished_at, deadline_at = _utc(finished_at), _utc(deadline_at)
    delay = retry_delay_seconds(attempt_number, retry_after_seconds)
    if delay >= (deadline_at - finished_at).total_seconds():
        return None
    return finished_at + timedelta(seconds=delay)
