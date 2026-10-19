"""Retained investigation trace, without factual or execution authority.

The application proves record ownership and immutable membership. This module
checks the supplied projection's exact shape and relation to selected reports.
Search questions and empty results remain workflow context, never source claims.
"""

import json
import re
from uuid import UUID

from .models import canonical_json
from .research_plan import SCHEMA_VERSION as PLAN_SCHEMA_VERSION, parse_plan
from .source_evidence import _array, _object, _text, _uuid


SCHEMA_VERSION = "question-research-context-v1"
CONTEXT_FIELDS = frozenset((
    "schema_version", "run_id", "run_request_digest", "exact_question_digest",
    "plan_attempt_id", "plan_prompt_digest", "plan_result_id", "plan_result_digest",
    "evidence_depth", "coverage_complete", "questions",
))
QUESTION_FIELDS = frozenset((
    "question_index", "planned_question", "source_id", "contract_version_id",
    "contract_digest", "discovery_attempt_id",
    "receipt_id", "receipt_digest", "result_id", "result_digest", "capture_id",
    "status", "returned_candidate_count", "selected_count", "excluded_count",
    "exclusion_counts", "candidate_cap_reached", "revision_ids",
))
EXCLUSION_REASONS = frozenset((
    "duplicate_url_identity", "unsafe_or_non_https_attribution_url",
    "explicit_selection_limit",
))


def _digest(value, name):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} requires lowercase SHA256")


def _count(value, name, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} requires a bounded integer")
    return value


def validate_question_research_context(value, reports):
    """Return detached exact trace data, without asserting ownership or truth.

    Every selected report must belong to exactly one completed question search.
    A completed empty search is retained explicitly; it is not evidence against
    the proposed mechanism or proof of complete counter-evidence coverage.
    """
    _object(value, CONTEXT_FIELDS, "question research context")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported question research context schema")
    run_id = _uuid(value["run_id"], "research run")
    for field in ("plan_attempt_id", "plan_result_id"):
        _uuid(value[field], field)
    if value["plan_attempt_id"] != value["plan_result_id"]:
        raise ValueError("research plan result must identify its admitted attempt")
    for field in ("run_request_digest", "exact_question_digest", "plan_prompt_digest",
                  "plan_result_digest"):
        _digest(value[field], field)
    if value["evidence_depth"] != "headline_metadata_only":
        raise ValueError("question research evidence depth must remain headline metadata only")
    if value["coverage_complete"] is not False:
        raise ValueError("question research cannot assert complete coverage")

    questions = _array(value["questions"], "research questions", 3)
    if not questions:
        raise ValueError("question research requires one to three questions")
    source_for_revision = {}
    for report in _array(reports, "question research reports", 16):
        if (type(report) is not dict or not
                {"revision_id", "source_id", "contract_version_id", "contract_digest"} <= set(report)):
            raise ValueError("question research reports require revision, source and contract identities")
        revision = _uuid(report["revision_id"], "research report revision")
        source = _text(report["source_id"], "research report source", 128)
        contract = _uuid(report["contract_version_id"], "research report contract version")
        _digest(report["contract_digest"], "research report contract digest")
        if revision in source_for_revision:
            raise ValueError("question research report revisions cannot repeat")
        source_for_revision[revision] = (source, contract, report["contract_digest"])

    attempts, captures, selected_revisions, planned = set(), set(), set(), []
    for index, item in enumerate(questions):
        _object(item, QUESTION_FIELDS, "retained research question")
        if type(item["question_index"]) is not int or item["question_index"] != index:
            raise ValueError("retained research question indexes must be contiguous and ordered")
        planned.append(item["planned_question"])
        expected_source = f"research-gdelt-{UUID(run_id).hex}-{index}"
        if item["source_id"] != expected_source:
            raise ValueError("retained research source must identify its exact run and question")
        contract = _uuid(item["contract_version_id"], "question source contract version")
        _digest(item["contract_digest"], "question source contract digest")
        expected_membership = (expected_source, contract, item["contract_digest"])
        for field in ("discovery_attempt_id", "receipt_id", "result_id", "capture_id"):
            _uuid(item[field], field)
        attempt = item["discovery_attempt_id"]
        if item["receipt_id"] != attempt or item["result_id"] != attempt:
            raise ValueError("research receipt and result must identify their admitted attempt")
        if attempt in attempts or item["capture_id"] in captures:
            raise ValueError("question searches cannot reuse attempt or capture identities")
        attempts.add(attempt)
        captures.add(item["capture_id"])
        for field in ("receipt_digest", "result_digest"):
            _digest(item[field], field)
        if item["status"] != "captured":
            raise ValueError("question research requires a retained capture for every question")
        returned = _count(item["returned_candidate_count"], "returned candidates", 5)
        selected = _count(item["selected_count"], "selected candidates", 4)
        excluded = _count(item["excluded_count"], "excluded candidates", 5)
        exclusions = item["exclusion_counts"]
        if type(exclusions) is not dict or not set(exclusions) <= EXCLUSION_REASONS:
            raise ValueError("question search exclusions require documented reasons")
        for count in exclusions.values():
            if type(count) is not int or not 1 <= count <= 5:
                raise ValueError("question search exclusion counts require positive bounded integers")
        if returned - selected != excluded or excluded != sum(exclusions.values()):
            raise ValueError("question search candidate counts must account for every exclusion")
        if (type(item["candidate_cap_reached"]) is not bool
                or item["candidate_cap_reached"] != (returned == 5)):
            raise ValueError("question search cap state must match the returned candidate count")
        revisions = _array(item["revision_ids"], "question selected revisions", 4)
        for revision in revisions:
            _uuid(revision, "question selected revision")
        if revisions != sorted(set(revisions)) or selected != len(revisions):
            raise ValueError("question selected revisions must be sorted unique and match the count")
        for revision in revisions:
            if (revision in selected_revisions
                    or source_for_revision.get(revision) != expected_membership):
                raise ValueError("question selected revisions must match their exact source and contract reports")
            selected_revisions.add(revision)
    if selected_revisions != set(source_for_revision):
        raise ValueError("question selected revisions must exactly cover the source reports")
    try:
        # Validate the complete plan together, including unique IDs and queries.
        # The original question is separately bound by its retained exact digest.
        parse_plan(canonical_json({"schema_version": PLAN_SCHEMA_VERSION,
                                   "questions": planned}), "Retained research question")
        return json.loads(canonical_json(value))
    except (TypeError, UnicodeError, RecursionError, OverflowError):
        raise ValueError("question research context requires bounded finite JSON data") from None
