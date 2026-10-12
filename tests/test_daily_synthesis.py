"""Fresh synthesis keeps evidence attribution and independent paper effects."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from macro_agent.domain.daily_synthesis import (
    MAX_CONTEXT_BYTES, SCHEMA_VERSION, build_synthesis_prompt, validate_synthesis_document,
)
from macro_agent.domain.models import canonical_json, text_digest
from test_daily_review import SCOPE, START, analysis, build, report


def context(*, deferred=False, prior=False, quiet=False):
    source = report(witness=None if deferred else START)
    value = build(reports=() if quiet else (source,),
        analyses=(analysis(source),) if prior else ()).to_dict()
    return {"review_id": "review", "review_digest": text_digest(canonical_json(value)), "review": value,
        "original_inputs": {"approved_user": {"thesis_id": SCOPE.thesis_id,
            "approval": {"version_id": SCOPE.approval_id},
            "interpretation": {"version_id": SCOPE.interpretation_id},
            "exposure": {"positions": [{"position_id": "position", "version_id": "position-version-current",
                "payload": {"status": "open"}}]}}},
        "report_heads": {} if quiet else {source.report_id: source.revision_id}}


def document(value):
    reports = [item for section in ("new", "background") for item in value["review"]["reports"][section]]
    claims = [{"claim_id": "claim",
        "source_revision_id": reports[0]["revision_id"], "source_field": "title",
        "quote": reports[0]["payload"]["title"]}] if reports else []
    refs = ["claim"] if claims else []
    section = {"text": "Interpretation remains conditional.", "claim_ids": refs,
        "prior_analysis_ids": [], "uncertainty": "Transmission and timing remain uncertain."}
    return {"schema_version": SCHEMA_VERSION, "attributed_claims": claims,
        "overview": section, "thesis_effect": {"effect": "supports" if claims else "unresolved", "reasoning": "Potential policy support.",
            **{key: section[key] for key in ("claim_ids", "prior_analysis_ids", "uncertainty")}},
        "trade_effects": [{"position_id": "position", "effect": "potential_risk" if claims else "unresolved",
            "reasoning": "Funding stress can hurt the open trade before the thesis plays out.",
            **{key: section[key] for key in ("claim_ids", "prior_analysis_ids", "uncertainty")}}],
        "counter_case": deepcopy(section), "watch_questions": ["Does transmission improve?"],
        "gaps": ["Pricing and starting macro context are unavailable."]}


class DailySynthesisContractTests(unittest.TestCase):
    def test_supportive_thesis_and_separate_trade_risk_are_valid_interpretations(self):
        value = context()
        result = validate_synthesis_document(canonical_json(document(value)), value)
        self.assertEqual(result["thesis_effect"]["effect"], "supports")
        self.assertEqual(result["trade_effects"][0]["effect"], "potential_risk")

    def test_prompt_retains_exact_digest_and_original_labels_as_untrusted_data(self):
        value = context(prior=True)
        messages = build_synthesis_prompt(value)
        self.assertEqual(json.loads(messages[1]["content"]), value)
        self.assertIn("never verified evidence", messages[0]["content"])
        self.assertEqual(value["review"]["analyses"]["new"][0]["current_disposition"], "stale")

    def test_quiet_digest_can_be_synthesised_without_invented_source_claims(self):
        value = context(quiet=True)
        self.assertEqual(validate_synthesis_document(canonical_json(document(value)), value)["attributed_claims"], [])
        self.assertIn("Do not infer market calm", build_synthesis_prompt(value)[0]["content"])

    def test_unknown_revision_or_changed_quote_is_rejected(self):
        value = context()
        for field, changed in (("source_revision_id", "invented"), ("quote", "Invented quote"),
                               ("source_field", "url")):
            output = document(value)
            output["attributed_claims"][0][field] = changed
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "exact eligible"):
                validate_synthesis_document(canonical_json(output), value)

    def test_deferred_report_cannot_become_citable_evidence(self):
        value = context(deferred=True)
        output = document(context())
        with self.assertRaisesRegex(ValueError, "exact eligible"):
            validate_synthesis_document(canonical_json(output), value)

    def test_only_eligible_completed_prior_interpretations_can_be_referenced(self):
        value = context(prior=True)
        output = document(value)
        output["overview"]["prior_analysis_ids"] = ["analysis"]
        validate_synthesis_document(canonical_json(output), value)
        output["overview"]["prior_analysis_ids"] = ["invented"]
        with self.assertRaisesRegex(ValueError, "supplied identities"):
            validate_synthesis_document(canonical_json(output), value)

    def test_open_positions_cannot_be_dropped_duplicated_or_invented(self):
        value = context()
        for kind in ("missing", "duplicate", "invented"):
            output = document(value)
            if kind == "missing":
                output["trade_effects"] = []
            elif kind == "duplicate":
                output["trade_effects"] *= 2
            else:
                output["trade_effects"][0]["position_id"] = "other"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate_synthesis_document(canonical_json(output), value)

    def test_closed_positions_remain_context_but_cannot_receive_open_trade_effects(self):
        value = context()
        value["original_inputs"]["approved_user"]["exposure"]["positions"][0]["payload"]["status"] = "closed"
        output = document(value)
        with self.assertRaisesRegex(ValueError, "open positions"):
            validate_synthesis_document(canonical_json(output), value)
        output["trade_effects"] = []
        validate_synthesis_document(canonical_json(output), value)

    def test_unknown_fields_duplicate_json_and_missing_uncertainty_reject(self):
        value = context()
        output = document(value)
        output["approve_thesis"] = True
        with self.assertRaisesRegex(ValueError, "documented fields"):
            validate_synthesis_document(canonical_json(output), value)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_synthesis_document('{"schema_version":1,"schema_version":2}', value)
        output = document(value)
        output["overview"]["uncertainty"] = ""
        with self.assertRaisesRegex(ValueError, "uncertainty"):
            validate_synthesis_document(canonical_json(output), value)

    def test_context_requires_exact_digest_complete_book_and_report_head_labels(self):
        for kind in ("digest", "book", "heads"):
            value = context()
            if kind == "digest":
                value["review_digest"] = "0" * 64
            elif kind == "book":
                value["original_inputs"]["approved_user"]["exposure"]["positions"] = []
            else:
                value["report_heads"] = {}
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                build_synthesis_prompt(value)

    def test_complete_context_overflow_rejects_without_truncation(self):
        value = context()
        value["original_inputs"]["retained_extra"] = "x" * MAX_CONTEXT_BYTES
        with self.assertRaisesRegex(ValueError, "do not truncate"):
            build_synthesis_prompt(value)

    def test_directional_effect_cannot_be_asserted_without_evidence_references(self):
        value = context()
        output = document(value)
        output["thesis_effect"]["claim_ids"] = []
        with self.assertRaisesRegex(ValueError, "requires supplied evidence"):
            validate_synthesis_document(canonical_json(output), value)
