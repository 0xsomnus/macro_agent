"""Approval binds labelled review content without promoting its hypotheses."""

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from macro_agent.domain.compilation import SECTIONS, build_review_card
from macro_agent.domain.models import CompiledThesisVersion, UserThesisVersion, canonical_json
from macro_agent.domain.thesis import ApprovalRequest, approve_thesis


AT = datetime(2026, 10, 9, tzinfo=timezone.utc)
EXACT = "  I am investigating gold.\r\nΔ"


def review(exact_text=EXACT):
    return build_review_card({
        "interpretation": {"drivers": [], "horizon": None, "invalidation_signposts": []},
        "grounding": [], "refinement_issues": [], "agent_hypotheses": [],
        "counter_case": "Unverified: other forces could dominate.",
        "review_card": {section: {"extracted": [],
            "proposed": ["Unverified proposal: investigate real yields."],
            "gap": "No supporting evidence or trader commitment."} for section in SECTIONS},
    }, exact_text)


class ReviewApprovalTests(unittest.TestCase):
    def setUp(self):
        self.thesis = UserThesisVersion("text", "thesis", "owner", EXACT, AT)
        self.meaning = CompiledThesisVersion("meaning", "text", (), None, (), AT,
                                             canonical_json(review()))
        self.request = ApprovalRequest("approval", "owner", "user", "text",
            self.thesis.text_digest, "meaning", self.meaning.digest, AT)

    def test_review_approval_preserves_proposals_and_missing_intent(self):
        approved = approve_thesis(self.thesis, self.meaning, self.request, now=AT)
        self.assertEqual(approved.interpretation_digest, self.meaning.digest)
        self.assertEqual(self.meaning.drivers, ())
        self.assertIsNone(self.meaning.horizon)
        self.assertEqual(self.meaning.invalidation_signposts, ())
        card = json.loads(self.meaning.review_card_json)
        self.assertEqual(card["document"]["review_card"]["causal_path"]["extracted"], [])
        self.assertEqual(card["evidence"], {"status": "unavailable", "references": []})
        self.assertEqual(self.thesis.exact_text, EXACT)

    def test_card_quote_source_must_match_exact_selected_thesis_even_with_valid_hash(self):
        different = replace(self.meaning, review_card_json=canonical_json(review(EXACT.strip())))
        request = replace(self.request, interpretation_digest=different.digest)
        with self.assertRaisesRegex(ValueError, "exact thesis text"):
            approve_thesis(self.thesis, different, request, now=AT)

    def test_changed_counter_case_requires_new_exact_review_approval(self):
        card = json.loads(self.meaning.review_card_json)
        card["document"]["counter_case"] = "A different unverified counter-case."
        different = replace(self.meaning, review_card_json=canonical_json(card))
        with self.assertRaisesRegex(ValueError, "exact displayed"):
            approve_thesis(self.thesis, different, self.request, now=AT)
        approved = approve_thesis(self.thesis, different,
            replace(self.request, interpretation_digest=different.digest), now=AT)
        self.assertEqual(approved.interpretation_digest, different.digest)
        self.assertEqual(different.drivers, ())


if __name__ == "__main__":
    unittest.main()
