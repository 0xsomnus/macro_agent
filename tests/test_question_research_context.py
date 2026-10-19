"""A retained search trace preserves limitations without becoming evidence."""

import copy
import sys
import unittest
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from macro_agent.domain.models import canonical_json
from macro_agent.domain.question_research_context import (
    SCHEMA_VERSION, validate_question_research_context,
)
from macro_agent.domain.source_evidence import (
    MAX_EVIDENCE_BYTES, SOURCE_EVIDENCE_QUESTION_SCHEMA_VERSION,
    source_evidence_digest, validate_source_evidence,
)
from test_source_evidence import evidence


def identity(number):
    return str(UUID(int=number))


def planned_question(index):
    return {"question_id": f"q{index}",
        "question": f"What would establish or undermine mechanism {index}?",
        "why_material": "The proposed idea depends on this mechanism.",
        "evidence_to_seek": "A relevant observation with its stated limitations.",
        "counter_evidence_to_seek": "Competing drivers and offsets, including Δ.\r\n",
        "query": f"mechanism {index} competing evidence"}


def question_packet():
    """One selected report and a separately retained empty counter-case search."""
    packet = evidence()
    packet["schema_version"] = SOURCE_EVIDENCE_QUESTION_SCHEMA_VERSION
    run_id = identity(100)
    packet["reports"][0]["source_id"] = f"research-gdelt-{UUID(run_id).hex}-0"
    questions = []
    for index in range(2):
        attempt_id = identity(300 + index)
        questions.append({"question_index": index, "planned_question": planned_question(index),
            "source_id": f"research-gdelt-{UUID(run_id).hex}-{index}",
            "contract_version_id": packet["reports"][0]["contract_version_id"] if index == 0 else identity(601),
            "contract_digest": packet["reports"][0]["contract_digest"] if index == 0 else "e" * 64,
            "discovery_attempt_id": attempt_id, "receipt_id": attempt_id,
            "receipt_digest": "c" * 64, "result_id": attempt_id, "result_digest": "d" * 64,
            "capture_id": identity(400 + index), "status": "captured",
            "returned_candidate_count": 1 if index == 0 else 0,
            "selected_count": 1 if index == 0 else 0, "excluded_count": 0,
            "exclusion_counts": {}, "candidate_cap_reached": False,
            "revision_ids": [packet["reports"][0]["revision_id"]] if index == 0 else []})
    packet["question_research"] = {"schema_version": SCHEMA_VERSION,
        "run_id": run_id, "run_request_digest": "a" * 64,
        "exact_question_digest": "b" * 64, "plan_attempt_id": identity(200),
        "plan_prompt_digest": "c" * 64, "plan_result_id": identity(200),
        "plan_result_digest": "d" * 64, "evidence_depth": "headline_metadata_only",
        "coverage_complete": False, "questions": questions}
    return packet


def saturated_packet():
    packet = question_packet()
    first = packet["reports"][0]
    for index in range(3):
        report = copy.deepcopy(first)
        report["revision_id"] = report["head_at_admission_id"] = identity(500 + index)
        packet["reports"].append(report)
    packet["question_research"]["questions"][0].update(
        returned_candidate_count=5, selected_count=4, excluded_count=1,
        exclusion_counts={"explicit_selection_limit": 1}, candidate_cap_reached=True,
        revision_ids=sorted(item["revision_id"] for item in packet["reports"]))
    return packet


class QuestionResearchContextTests(unittest.TestCase):
    def test_empty_counter_evidence_search_and_exact_plan_are_retained_detached(self):
        packet = question_packet()
        retained = validate_source_evidence(packet)
        self.assertEqual(retained, packet)
        context = retained["question_research"]
        self.assertEqual(context["questions"][1]["returned_candidate_count"], 0)
        self.assertEqual(context["questions"][1]["revision_ids"], [])
        packet["question_research"]["questions"][1]["planned_question"]["query"] = "Changed"
        self.assertEqual(context["questions"][1]["planned_question"]["query"],
                         "mechanism 1 competing evidence")
        self.assertTrue(context["questions"][1]["planned_question"]["counter_evidence_to_seek"]
                        .endswith("Δ.\r\n"))

    def test_saturated_candidate_log_accounts_for_selected_and_excluded(self):
        packet = saturated_packet()
        self.assertEqual(validate_source_evidence(packet), packet)
        for field, replacement in (("returned_candidate_count", 4), ("selected_count", 3),
                                   ("excluded_count", 0), ("candidate_cap_reached", False),
                                   ("exclusion_counts", {"explicit_selection_limit": 2})):
            value = saturated_packet()
            value["question_research"]["questions"][0][field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_source_evidence(value)

    def test_all_supported_exclusion_reasons_remain_explicit(self):
        packet = question_packet()
        packet["question_research"]["questions"][0].update(
            returned_candidate_count=3, excluded_count=2,
            exclusion_counts={"duplicate_url_identity": 1,
                              "unsafe_or_non_https_attribution_url": 1})
        self.assertEqual(validate_source_evidence(packet), packet)

    def test_foreign_run_source_or_unmapped_report_cannot_enter_context(self):
        cases = []
        value = question_packet()
        value["question_research"]["run_id"] = identity(999)
        cases.append(value)
        value = question_packet()
        value["reports"][0]["source_id"] = "research-gdelt-" + "f" * 32 + "-0"
        cases.append(value)
        value = question_packet()
        value["question_research"]["questions"][0]["revision_ids"] = [identity(999)]
        cases.append(value)
        value = saturated_packet()
        value["question_research"]["questions"][0].update(
            selected_count=3, excluded_count=2,
            exclusion_counts={"explicit_selection_limit": 2},
            revision_ids=value["question_research"]["questions"][0]["revision_ids"][:-1])
        cases.append(value)
        value = question_packet()
        value["question_research"]["questions"][1].update(
            returned_candidate_count=1, selected_count=1,
            revision_ids=value["question_research"]["questions"][0]["revision_ids"][:])
        cases.append(value)
        for index, value in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_source_evidence(value)

    def test_revision_lists_must_be_sorted_unique_and_match_selected_counts(self):
        for change in ("duplicate", "unsorted", "count"):
            value = saturated_packet()
            question = value["question_research"]["questions"][0]
            if change == "duplicate":
                question["revision_ids"][1] = question["revision_ids"][0]
            elif change == "unsorted":
                question["revision_ids"].reverse()
            else:
                question["revision_ids"].pop()
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_source_evidence(value)

    def test_query_reports_must_match_the_exact_pinned_contract(self):
        for field, replacement in (("contract_version_id", identity(999)),
                                   ("contract_digest", "f" * 64)):
            value = question_packet()
            value["reports"][0][field] = replacement
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "source and contract"):
                validate_source_evidence(value)

    def test_empty_query_requires_its_own_valid_pinned_contract(self):
        for field, replacement in (("contract_version_id", "not-a-uuid"),
                                   ("contract_digest", "E" * 64)):
            value = question_packet()
            value["question_research"]["questions"][1][field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_source_evidence(value)
        for field in ("contract_version_id", "contract_digest"):
            value = question_packet()
            del value["question_research"]["questions"][1][field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                validate_source_evidence(value)

    def test_missing_capture_failed_or_uncertain_node_cannot_claim_complete_trace(self):
        for field, replacement in (("capture_id", None), ("status", "failed"),
                                   ("status", "outcome_unknown"), ("receipt_id", identity(999)),
                                   ("result_id", identity(999))):
            value = question_packet()
            value["question_research"]["questions"][1][field] = replacement
            with self.subTest(field=field, replacement=replacement), self.assertRaises(ValueError):
                validate_source_evidence(value)
        value = question_packet()
        value["question_research"]["plan_result_id"] = identity(999)
        with self.assertRaises(ValueError):
            validate_source_evidence(value)

    def test_attempt_capture_question_ids_and_search_queries_cannot_repeat(self):
        for change in ("attempt", "capture", "question_id", "query", "query_case"):
            value = question_packet()
            first, second = value["question_research"]["questions"]
            if change == "attempt":
                for field in ("discovery_attempt_id", "receipt_id", "result_id"):
                    second[field] = first[field]
            elif change == "capture":
                second["capture_id"] = first["capture_id"]
            else:
                field = "query" if change == "query_case" else change
                text = first["planned_question"][field]
                second["planned_question"][field] = f"  {text.upper()}  " if change == "query_case" else text
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_source_evidence(value)

    def test_indexes_are_contiguous_and_question_count_is_bounded(self):
        for replacement in ([], question_packet()["question_research"]["questions"] * 2):
            value = question_packet()
            value["question_research"]["questions"] = replacement
            with self.assertRaises(ValueError):
                validate_source_evidence(value)
        for index in (-1, 1, True, "0"):
            value = question_packet()
            value["question_research"]["questions"][0]["question_index"] = index
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_source_evidence(value)

    def test_unknown_missing_fields_and_asserted_authority_are_rejected(self):
        for target in ("packet", "context", "question", "planned_question"):
            for change in ("add", "remove"):
                value = question_packet()
                items = {"packet": value, "context": value["question_research"],
                         "question": value["question_research"]["questions"][0],
                         "planned_question": value["question_research"]["questions"][0]["planned_question"]}
                item = items[target]
                if change == "add":
                    item["verified"] = True
                else:
                    del item[next(iter(item))]
                with self.subTest(target=target, change=change), self.assertRaises(ValueError):
                    validate_source_evidence(value)
        for field, replacement in (("coverage_complete", True), ("coverage_complete", 0),
                                   ("evidence_depth", "article_text")):
            value = question_packet()
            value["question_research"][field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_source_evidence(value)

    def test_count_coercion_nonfinite_unknown_exclusions_and_noncanonical_ids_reject(self):
        changes = (("returned_candidate_count", True), ("selected_count", 1.0),
                   ("excluded_count", "0"), ("returned_candidate_count", 6),
                   ("candidate_cap_reached", 0), ("exclusion_counts", {"other": 1}),
                   ("exclusion_counts", {"duplicate_url_identity": 0}),
                   ("exclusion_counts", {"duplicate_url_identity": True}),
                   ("exclusion_counts", {"duplicate_url_identity": float("nan")}),
                   ("receipt_digest", "A" * 64), ("result_digest", "d" * 63),
                   ("capture_id", identity(400).replace("-", "")),
                   ("revision_ids", [UUID(evidence()["reports"][0]["revision_id"])]))
        for field, replacement in changes:
            value = question_packet()
            value["question_research"]["questions"][0][field] = replacement
            with self.subTest(field=field, replacement=replacement), self.assertRaises(ValueError):
                validate_source_evidence(value)

    def test_legacy_exact_fields_and_digest_are_unchanged(self):
        legacy = evidence()
        self.assertEqual(source_evidence_digest(legacy),
                         "59ced54969a9776be68b86f38ed344e15a00ca950700b879e188cdc5fda7dd0a")
        legacy["question_research"] = question_packet()["question_research"]
        with self.assertRaises(ValueError):
            validate_source_evidence(legacy)
        value = question_packet()
        del value["question_research"]
        with self.assertRaises(ValueError):
            validate_source_evidence(value)

    def test_digest_binds_empty_counter_search_rationale_and_trace_identities(self):
        original = source_evidence_digest(question_packet())
        for field in ("counter_evidence_to_seek", "query"):
            packet = question_packet()
            packet["question_research"]["questions"][1]["planned_question"][field] += " distinct"
            self.assertNotEqual(source_evidence_digest(packet), original)
        packet = question_packet()
        packet["question_research"]["questions"][1]["receipt_digest"] = "e" * 64
        self.assertNotEqual(source_evidence_digest(packet), original)

    def test_complete_packet_byte_bound_includes_context_without_truncation(self):
        packet = saturated_packet()
        for report in packet["reports"]:
            report["content"] = "x" * 15_000
        legacy = {key: value for key, value in packet.items() if key != "question_research"}
        legacy["schema_version"] = "retained-source-evidence-v1"
        # Pad only within existing field bounds so the legacy packet fits but
        # the same retained reports plus research context exceed the total cap.
        legacy_size = len(canonical_json(legacy).encode("utf-8"))
        target_size = MAX_EVIDENCE_BYTES - 100
        padding = target_size - legacy_size
        while padding > 0:
            gap = "x" * min(2_000, padding - 3 if padding >= 4 else padding)
            legacy["gaps"].append(gap)
            packet["gaps"] = legacy["gaps"]
            padding = target_size - len(canonical_json(legacy).encode("utf-8"))
        self.assertLessEqual(len(canonical_json(legacy).encode("utf-8")), MAX_EVIDENCE_BYTES)
        self.assertEqual(validate_source_evidence(legacy), legacy)
        with self.assertRaisesRegex(ValueError, "complete source evidence"):
            validate_source_evidence(packet)

    def test_standalone_context_can_retain_an_all_empty_completed_search(self):
        context = question_packet()["question_research"]
        context["questions"][0].update(returned_candidate_count=0, selected_count=0, revision_ids=[])
        self.assertEqual(validate_question_research_context(context, []), context)


if __name__ == "__main__":
    unittest.main()
