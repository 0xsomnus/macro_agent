"""Read-only synthetic compilation cases and a deliberately literal baseline.

This module does not call models, approve theses, verify market facts or learn
from outcomes. A case describes a review exercise, not a correct market view.
The baseline recognizes explicit line labels only. An unrecognized field is
unknown to this parser, not necessarily absent from the trader's reasoning.
"""

import json
from pathlib import Path
import re

from .compilation import MAX_THESIS_CHARS


PACK_SCHEMA_VERSION = "text-compilation-review-pack-v1"
BASELINE_VERSION = "literal-labelled-thesis-baseline-v1"
MAX_PACK_BYTES = 524_288
MAX_CASES = 10
INSTRUMENTS = frozenset(("ES", "NQ", "XAU", "DXY", "EURUSD", "USDJPY", "USDCNH"))
CASE_TAGS = frozenset((
    "incomplete", "contrarian", "ambiguous", "conditional", "checkable_premise",
    "unsupported_mechanism", "injection", "labelled_control",
))
REVIEW_DIMENSIONS = (
    "intent_fidelity", "invented_facts_or_assumptions", "consequential_questions",
    "counter_case", "usefulness",
)
QUALITY_STATUSES = ("good", "poor", "uncertain")
ATTEMPT_STATUSES = frozenset(("compiled", "stale", "failed", "running", "outcome_unknown"))
REVIEW_RUBRIC = (
    ("intent_fidelity", "Does the interpretation preserve the trader's actual meaning, qualifiers and missing intent?"),
    ("invented_facts_or_assumptions", "Does the output avoid invented facts, verified-condition claims and assumptions presented as trader intent?"),
    ("consequential_questions", "Do the questions expose gaps that could change reasoning, timing or invalidation rather than add generic detail?"),
    ("counter_case", "Is the counter-case relevant and explicitly unverified, with disagreement kept separate from factual error?"),
    ("usefulness", "Compared with exact prose and the literal baseline, did this response make review easier or reasoning more explicit, even if conviction fell?"),
)


def _text(value, field: str, limit: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{field} must be a nonblank bounded string without NUL")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError(f"{field} requires valid Unicode") from None
    return value


def _object(value, fields: tuple[str, ...], field: str) -> dict:
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError(f"{field} requires exactly its documented fields")
    return value


def _array(value, field: str, minimum: int, maximum: int) -> list:
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field} must be a bounded array")
    return value


def _strings(value, field: str, minimum: int, maximum: int, limit: int) -> list[str]:
    items = [_text(item, field, limit) for item in _array(value, field, minimum, maximum)]
    if len(set(items)) != len(items):
        raise ValueError(f"{field} must not contain duplicates")
    return items


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON keys are ambiguous")
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError("non-finite JSON numbers are unsupported")


def parse_evaluation_pack(content: str) -> dict:
    """Validate an entire bounded pack without repairing or normalizing inputs."""
    _text(content, "pack content", MAX_PACK_BYTES)
    if len(content.encode("utf-8")) > MAX_PACK_BYTES:
        raise ValueError("pack exceeds its encoded limit")
    try:
        pack = json.loads(content, object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (ValueError, RecursionError, OverflowError):
        raise ValueError("pack must be one unambiguous finite JSON object") from None
    _object(pack, ("schema_version", "scope_limits", "rubric", "cases"), "pack")
    if type(pack["schema_version"]) is not str or pack["schema_version"] != PACK_SCHEMA_VERSION:
        raise ValueError("unsupported evaluation pack version")
    _strings(pack["scope_limits"], "scope_limits", 1, 12, 1_000)

    rubric_ids = []
    for item in _array(pack["rubric"], "rubric", len(REVIEW_DIMENSIONS), len(REVIEW_DIMENSIONS)):
        _object(item, ("id", "question"), "rubric dimension")
        rubric_ids.append(_text(item["id"], "rubric id", 64))
        _text(item["question"], "rubric question", 1_000)
    if len(set(rubric_ids)) != len(rubric_ids) or set(rubric_ids) != set(REVIEW_DIMENSIONS):
        raise ValueError("rubric must include each independent review dimension once")

    case_ids = set()
    for case in _array(pack["cases"], "cases", 1, MAX_CASES):
        _object(case, ("id", "title", "instrument", "tags", "exact_text", "review_questions"), "case")
        case_id = _text(case["id"], "case id", 64)
        if re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", case_id) is None or case_id in case_ids:
            raise ValueError("case IDs must be unique bounded lowercase slugs")
        case_ids.add(case_id)
        _text(case["title"], "case title", 160)
        instrument = _text(case["instrument"], "case instrument", 16)
        if instrument not in INSTRUMENTS:
            raise ValueError("case instrument is outside this synthetic pack's scope")
        tags = _strings(case["tags"], "case tags", 1, len(CASE_TAGS), 64)
        if not set(tags) <= CASE_TAGS:
            raise ValueError("unsupported case tag")
        _text(case["exact_text"], "exact_text", MAX_THESIS_CHARS)
        _strings(case["review_questions"], "review_questions", 1, 6, 1_000)
    return pack


def load_evaluation_pack(path: str | Path) -> dict:
    """Read a bounded UTF-8 fixture without universal-newline translation."""
    with Path(path).open("rb") as stream:
        content = stream.read(MAX_PACK_BYTES + 1)
    if len(content) > MAX_PACK_BYTES:
        raise ValueError("pack exceeds its encoded limit")
    try:
        decoded = content.decode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError("pack requires UTF-8") from None
    return parse_evaluation_pack(decoded)


def review_outcome(attempt_status: str, ratings: dict | None = None) -> dict:
    """Separate operational disposition from explicit manual quality review."""
    if type(attempt_status) is not str or attempt_status not in ATTEMPT_STATUSES:
        raise ValueError("unsupported compilation attempt status")
    if attempt_status != "compiled":
        if ratings is not None:
            raise ValueError("noncompiled attempts cannot receive quality ratings")
        return {"status": "not_reviewable", "attempt_status": attempt_status, "ratings": None}
    if ratings is None:
        return {"status": "not_reviewed", "attempt_status": attempt_status, "ratings": None}
    _object(ratings, REVIEW_DIMENSIONS, "manual quality ratings")
    for value in ratings.values():
        if type(value) is not str or value not in QUALITY_STATUSES:
            raise ValueError("manual quality ratings require good, poor or uncertain")
    return {"status": "reviewed", "attempt_status": attempt_status,
            "ratings": {dimension: ratings[dimension] for dimension in REVIEW_DIMENSIONS}}


def deterministic_baseline(exact_text: str) -> dict:
    """Echo prose and quote explicit labels without interpreting causal meaning.

Only Driver:, Horizon: and Invalidation: at the start of a line are recognized.
Repeated horizons remain ambiguous; no horizon is selected silently. Labels
are untrusted user declarations, never verified facts or operational commands.
"""
    _text(exact_text, "exact_text", MAX_THESIS_CHARS)
    labels = {"Driver:": "drivers", "Horizon:": "horizon", "Invalidation:": "invalidation_signposts"}
    values = {field: [] for field in labels.values()}
    unparsed = []
    for original_line in exact_text.splitlines(keepends=True):
        line = original_line.removesuffix("\n").removesuffix("\r")
        for label, field in labels.items():
            if line.startswith(label) and line[len(label):].strip():
                values[field].append(line[len(label):])
                break
        else:
            unparsed.append(original_line)

    horizon = values["horizon"][0] if len(values["horizon"]) == 1 else None
    unknown = []
    questions = []
    if not values["drivers"]:
        unknown.append("drivers")
        questions.append("No labelled driver was extracted. What mechanism or association do you intend to monitor?")
    if horizon is None:
        unknown.append("horizon")
        questions.append("Multiple labelled horizons were supplied. Which horizon governs this thesis?" if values["horizon"] else
                         "No labelled horizon was extracted. What horizon, if any, should this thesis use?")
    if not values["invalidation_signposts"]:
        unknown.append("invalidation_signposts")
        questions.append("No labelled invalidation signpost was extracted. What observation, if any, would change your view?")
    return {
        "baseline_version": BASELINE_VERSION,
        "exact_text": exact_text,
        "literal_fields": {"drivers": values["drivers"], "horizon": horizon,
                           "invalidation_signposts": values["invalidation_signposts"]},
        "unknown_fields": unknown,
        "unparsed_lines": unparsed,
        "questions": questions,
        "limitations": [
            "Literal labels are untrusted declarations, not verified facts or supported causal mechanisms.",
            "Unknown means this label-only parser did not resolve a field; prose may already express it.",
            "No macro context, fact verification, investment judgment, counter-case or approval is supplied.",
            "Human review is required; this deliberately limited baseline does not establish model superiority.",
        ],
    }
