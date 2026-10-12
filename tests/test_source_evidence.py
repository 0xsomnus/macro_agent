"""Source projections establish attribution and availability, never fact truth."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from macro_agent.domain.source_evidence import (
    SOURCE_EVIDENCE_SCHEMA_VERSION, source_evidence_digest,
    validate_attributed_claims, validate_source_evidence,
)


REVISION = "00000000-0000-4000-8000-000000000001"
CONTRACT = "00000000-0000-4000-8000-000000000002"


def evidence():
    return {"schema_version": SOURCE_EVIDENCE_SCHEMA_VERSION,
        "cutoff": "2026-10-12T09:00:00+00:00", "reports": [{
            "revision_id": REVISION, "source_id": "fixture-research",
            "title": "  Policy rate remains unchanged. Δ\r\n",
            "content": "The committee left the rate at 4%.\r\nOutlook uncertain.",
            "source_url": "https://example.invalid/research",
            "source_claimed_published_at": None,
            "system_received_at": "2026-10-12T08:30:00+00:00",
            "availability_witness_at": "2026-10-12T08:31:00+00:00",
            "contract_version_id": CONTRACT, "contract_digest": "a" * 64,
            "head_at_admission_id": REVISION,
        }], "gaps": ["A current macro regime has not been established."]}


def claim():
    return {"claim_id": "rate", "revision_id": REVISION, "field": "content",
            "exact_quote": "The committee left the rate at 4%."}


class SourceEvidenceTests(unittest.TestCase):
    def test_exact_unicode_and_whitespace_are_retained_in_detached_data(self):
        original = evidence()
        retained = validate_source_evidence(original)
        self.assertEqual(retained, original)
        original["reports"][0]["title"] = "Changed"
        self.assertEqual(retained["reports"][0]["title"], "  Policy rate remains unchanged. Δ\r\n")

    def test_public_timestamp_does_not_replace_a_conservative_witness(self):
        value = evidence()
        value["reports"][0]["source_claimed_published_at"] = "2026-10-01T00:00:00+00:00"
        value["reports"][0]["availability_witness_at"] = None
        with self.assertRaises(ValueError):
            validate_source_evidence(value)

    def test_all_receipt_witness_and_cutoff_orderings_are_checked(self):
        for field, value in (
                ("system_received_at", "2026-10-12T08:32:00+00:00"),
                ("availability_witness_at", "2026-10-12T09:01:00+00:00"),
                ("availability_witness_at", "2026-10-12T08:31:00")):
            with self.subTest(field=field, value=value):
                item = evidence()
                item["reports"][0][field] = value
                with self.assertRaises(ValueError):
                    validate_source_evidence(item)

    def test_timezone_offsets_are_compared_as_instants(self):
        value = evidence()
        value["reports"][0]["availability_witness_at"] = "2026-10-12T11:31:00+03:00"
        self.assertEqual(validate_source_evidence(value), value)

    def test_source_claimed_publication_can_be_unknown_or_future(self):
        for public in (None, "2026-10-13T09:00:00+00:00"):
            value = evidence()
            value["reports"][0]["source_claimed_published_at"] = public
            self.assertEqual(validate_source_evidence(value), value)

    def test_noncurrent_and_duplicate_selected_revisions_are_rejected(self):
        value = evidence()
        value["reports"][0]["head_at_admission_id"] = CONTRACT
        with self.assertRaises(ValueError):
            validate_source_evidence(value)
        value = evidence()
        value["reports"].append(copy.deepcopy(value["reports"][0]))
        with self.assertRaises(ValueError):
            validate_source_evidence(value)

    def test_one_source_cannot_smuggle_different_contract_versions(self):
        value = evidence()
        other = copy.deepcopy(value["reports"][0])
        other["revision_id"] = other["head_at_admission_id"] = CONTRACT
        other["contract_digest"] = "b" * 64
        value["reports"].append(other)
        with self.assertRaises(ValueError):
            validate_source_evidence(value)

    def test_empty_and_overflow_inputs_reject_without_selection_or_compaction(self):
        for reports in ([], evidence()["reports"] * 17):
            value = evidence()
            value["reports"] = reports
            with self.assertRaises(ValueError):
                validate_source_evidence(value)
        value = evidence()
        value["reports"] = []
        for index in range(5):
            report = copy.deepcopy(evidence()["reports"][0])
            report["revision_id"] = report["head_at_admission_id"] = f"00000000-0000-4000-8000-{index:012d}"
            report["content"] = "x" * 16_384
            value["reports"].append(report)
        with self.assertRaisesRegex(ValueError, "complete source evidence"):
            validate_source_evidence(value)

    def test_unknown_missing_fields_and_coercion_are_rejected(self):
        cases = []
        for target in ("envelope", "report"):
            for mutation in ("add", "remove"):
                value = evidence()
                item = value if target == "envelope" else value["reports"][0]
                if mutation == "add":
                    item["extra"] = "unauthorised"
                else:
                    del item[next(iter(item))]
                cases.append(value)
        for field, value in (("title", True), ("content", None),
                             ("contract_digest", "A" * 64), ("revision_id", "not-a-uuid"),
                             ("title", "bad\x00"), ("title", "bad\ud800")):
            item = evidence()
            item["reports"][0][field] = value
            cases.append(item)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_source_evidence(value)

    def test_digest_binds_passages_permissions_cutoff_and_visible_gaps(self):
        original = source_evidence_digest(evidence())
        changes = (lambda x: x["reports"][0].update(content="Changed passage"),
                   lambda x: x["reports"][0].update(contract_version_id=REVISION),
                   lambda x: x.update(cutoff="2026-10-12T09:01:00+00:00"),
                   lambda x: x["gaps"].append("No expectation data."))
        for change in changes:
            value = evidence()
            change(value)
            self.assertNotEqual(source_evidence_digest(value), original)

    def test_attribution_requires_exact_named_source_field(self):
        self.assertEqual(validate_attributed_claims([claim()], evidence()), [claim()])
        for field, value in (("revision_id", CONTRACT), ("field", "source_url"),
                             ("exact_quote", "the committee left the rate at 4%."),
                             ("exact_quote", "Outlook uncertain.\n")):
            item = claim()
            item[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_attributed_claims([item], evidence())

    def test_claim_ids_are_unique_and_no_claim_can_add_truth_authority(self):
        for claims in ([claim(), claim()], [{**claim(), "verified": True}]):
            with self.assertRaises(ValueError):
                validate_attributed_claims(claims, evidence())
        self.assertEqual(validate_attributed_claims([], evidence()), [])


if __name__ == "__main__":
    unittest.main()
