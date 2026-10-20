"""Evidence-linked research proposals, separate from exact approved intent.

This opt-in profile adds no source discovery, instrument availability or causal
verification. It preserves the existing source-backed validator and encodings.
"""

import json

from . import compilation as text_compilation
from . import sourced_compilation
from .models import canonical_json, normalize_json_object
from .source_evidence import validate_source_evidence


SOURCED_SCHEMA_VERSION = "source-backed-thesis-compilation-v2"
PROMPT_VERSION = "source-backed-thesis-prompt-v2"
CARD_SCHEMA_VERSION = "thesis-review-card-v3"
ADDED_FIELDS = frozenset(("proposed_drivers", "exposure_candidates"))
DOCUMENT_FIELDS = sourced_compilation.DOCUMENT_FIELDS | ADDED_FIELDS
DRIVER_FIELDS = frozenset(("driver_id", "explanation", "transmission",
    "supporting_claim_ids", "counter_claim_ids", "assumptions", "uncertainty", "why_material"))
EXPOSURE_FIELDS = frozenset(("candidate_id", "asset", "expression", "relationship",
    "claim_ids", "basis_risks", "verification_questions", "uncertainty", "availability"))


def prompt_version(evidence):
    return sourced_compilation.prompt_version(evidence).replace(
        sourced_compilation.PROMPT_VERSION, PROMPT_VERSION, 1)


def _identity(value, field, seen):
    identity = text_compilation._text(value, field, 128)
    if identity in seen:
        raise ValueError(f"{field} must be unique")
    seen.add(identity)


def _example():
    return {
        "interpretation": {"drivers": [], "horizon": None, "invalidation_signposts": []},
        "grounding": [], "refinement_issues": [], "agent_hypotheses": [],
        "counter_case": None,
        "review_card": {section: {"extracted": [], "proposed": [],
                                   "gap": "Not supplied or established."}
                        for section in text_compilation.SECTIONS},
        "attributed_claims": [], "factual_conflicts": [], "evidence_assessment": {
            "summary": "The bounded evidence does not establish the thesis.",
            "supporting_claim_ids": [], "counter_claim_ids": [], "gaps": []},
    }


def build_messages(exact_text, evidence, *, refinement_inputs=()):
    """Propose qualified drivers before asking questions that change the thesis."""
    messages = sourced_compilation.build_messages(
        exact_text, evidence, refinement_inputs=refinement_inputs)
    instructions = messages[0]["content"].replace(
        sourced_compilation.PROMPT_VERSION, PROMPT_VERSION).replace(
        sourced_compilation.SOURCED_SCHEMA_VERSION, SOURCED_SCHEMA_VERSION)
    example = _example()
    old_example = canonical_json(example)
    example.update(proposed_drivers=[], exposure_candidates=[])
    if old_example not in instructions:
        raise ValueError("research compilation requires the expected sourced output example")
    instructions = instructions.replace(old_example, canonical_json(example))
    instructions = instructions.replace(
        "Proposed additions stay in proposed fields or\nagent_hypotheses, never extracted intent.",
        "Proposed additions stay in proposed fields or\nproposed_drivers, never extracted intent.")
    instructions = instructions.replace(
        "agent_hypotheses entries have exactly explanation,introduced_assumptions;\n"
        "explanation at most 2000, assumptions a bounded string array.",
        "agent_hypotheses must be an empty array in this research profile.")
    instructions += """

This research profile additionally requires exactly proposed_drivers and
exposure_candidates. Both arrays contain agent hypotheses, never trader intent,
verified facts, approved drivers or a recommendation to transact. The existing
agent_hypotheses array must be empty: place new driver hypotheses in the typed,
evidence-linked proposed_drivers array. Review-card proposed prose can summarize
these labelled proposals but does not establish an additional driver.

Accept rough observations, questions and unfamiliar assets. Research has no
pilot-instrument allowlist and does not start monitoring onboarding. Use the
bounded supplied evidence to propose and explain potentially important omitted
drivers before asking consequential clarification questions. Do not ask the
trader to complete the research framework. Empty proposal arrays are valid if
the packet does not support a useful qualified proposal; show the evidence gap.

proposed_drivers contains at most 32 entries, each exactly driver_id,explanation,
transmission,supporting_claim_ids,counter_claim_ids,assumptions,uncertainty,
why_material. driver_id is unique nonblank text at most 128 characters.
explanation, transmission, uncertainty and why_material are nonblank text at
most 2000 characters each. References are unique arrays of supplied attributed
claim IDs, at most 32 per array. At least one supporting or counter reference
is required. Counter evidence alone can motivate a qualified alternative,
without being described as positive support. assumptions is a bounded array of
nonblank strings, at most 1000 characters each. Explain the hypothesized
transmission, uncertainty, competing evidence and materiality. An exact quote
proves attribution only; it does not prove relevance, truth or causation.

exposure_candidates contains at most 32 entries, each exactly candidate_id,
asset,expression,relationship,claim_ids,basis_risks,verification_questions,
uncertainty,availability. candidate_id is unique nonblank text at most 128
characters. asset and expression are nonblank text at most 1000 characters;
expression is unrestricted research prose, not a fixed instrument catalogue.
relationship and uncertainty are nonblank text at most 2000 characters.
claim_ids is a nonempty unique array of attributed claim IDs. basis_risks and
verification_questions are nonempty arrays of nonblank strings, each at most
1000 characters, at most 32 entries. availability is always unverified.
Distinguish a commodity from an equity, derivative or other indirect expression.
Explain potential benefit, adverse input costs, offsets and basis risk where
relevant: an importer does not necessarily benefit from higher commodity prices.
Instrument, broker, jurisdiction, contract and data availability remain open
verification questions; do not claim an instrument is listed or accessible.
These research candidates neither configure monitoring nor certify coverage.

Keep explanation validity, thesis progression and prospective entry appeal
separate. Do not invent an entry, target, stop, time deadline, price, sizing,
R:R or verified market data. No proposal alters extracted interpretation or
approves an amendment. Only exact trader input and saved answers ground intent.
"""
    return [{"role": "system", "content": instructions}, messages[1]]


def parse_compilation(content, exact_text, evidence, *, refinement_inputs=()):
    """Require exact retained references without promoting semantic claims."""
    envelope = validate_source_evidence(evidence)
    text_compilation._text(content, "content", text_compilation.MAX_CONTENT_BYTES)
    if len(content.encode("utf-8")) > text_compilation.MAX_CONTENT_BYTES:
        raise ValueError("content exceeds its encoded limit")
    try:
        document = json.loads(normalize_json_object(content))
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise ValueError("content must be one unambiguous finite JSON object") from None
    text_compilation._object(document, DOCUMENT_FIELDS, "research compilation")
    base = {field: document[field] for field in sourced_compilation.DOCUMENT_FIELDS}
    sourced_compilation.parse_compilation(canonical_json(base), exact_text, envelope,
                                          refinement_inputs=refinement_inputs)
    if document["agent_hypotheses"]:
        raise ValueError("research driver hypotheses require evidence-linked proposed_drivers")
    identities = {item["claim_id"] for item in document["attributed_claims"]}
    seen = set()
    for driver in text_compilation._array(document["proposed_drivers"], "proposed drivers"):
        text_compilation._object(driver, DRIVER_FIELDS, "proposed driver")
        _identity(driver["driver_id"], "driver_id", seen)
        for field in ("explanation", "transmission", "uncertainty", "why_material"):
            text_compilation._text(driver[field], field, 2_000)
        for field in ("supporting_claim_ids", "counter_claim_ids"):
            sourced_compilation._references(driver[field], identities, field)
        if not driver["supporting_claim_ids"] and not driver["counter_claim_ids"]:
            raise ValueError("a proposed driver requires supporting or counter claim IDs")
        text_compilation._strings(driver["assumptions"], "driver assumptions")
    seen = set()
    for candidate in text_compilation._array(document["exposure_candidates"], "exposure candidates"):
        text_compilation._object(candidate, EXPOSURE_FIELDS, "exposure candidate")
        _identity(candidate["candidate_id"], "candidate_id", seen)
        for field in ("asset", "expression"):
            text_compilation._text(candidate[field], field, 1_000)
        for field in ("relationship", "uncertainty"):
            text_compilation._text(candidate[field], field, 2_000)
        sourced_compilation._references(candidate["claim_ids"], identities,
                                        "candidate claim IDs", required=True)
        for field in ("basis_risks", "verification_questions"):
            if not text_compilation._strings(candidate[field], field):
                raise ValueError(f"{field} requires an explicit unresolved research question or risk")
        if candidate["availability"] != "unverified":
            raise ValueError("exposure candidate availability must remain unverified")
    return json.loads(canonical_json(document))


def build_review_card(document, exact_text, evidence, *, refinement_inputs=()):
    """Bind exact inputs, linked research proposals and retained evidence."""
    envelope = validate_source_evidence(evidence)
    answers = text_compilation.validate_refinement_inputs(refinement_inputs)
    parsed = parse_compilation(canonical_json(document), exact_text, envelope,
                               refinement_inputs=answers)
    return {"schema_version": CARD_SCHEMA_VERSION,
            "inputs": [{"input_id": "thesis", "exact_text": exact_text}, *answers],
            "document": parsed,
            "evidence": {"status": "retained_sources", "context": envelope}}


def validate_review_card_json(content):
    """Validate the new profile without re-encoding historical source cards."""
    text_compilation._text(content, "review_card_json", text_compilation.MAX_REVIEW_CARD_BYTES)
    if len(content.encode("utf-8")) > text_compilation.MAX_REVIEW_CARD_BYTES:
        raise ValueError("review card exceeds its encoded limit")
    try:
        card = json.loads(normalize_json_object(content))
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise ValueError("review card requires unambiguous finite JSON") from None
    text_compilation._object(card, frozenset(("schema_version", "inputs", "document", "evidence")),
                             "research review card")
    if card["schema_version"] != CARD_SCHEMA_VERSION:
        raise ValueError("unsupported research review card schema version")
    inputs = text_compilation._array(card["inputs"], "review inputs",
                                     text_compilation.MAX_REFINEMENT_INPUTS + 1)
    if not inputs:
        raise ValueError("review card requires its exact original thesis input")
    first = text_compilation._object(inputs[0], frozenset(("input_id", "exact_text")),
                                     "original thesis input")
    if first["input_id"] != "thesis":
        raise ValueError("original thesis input must be named thesis")
    evidence = text_compilation._object(card["evidence"], frozenset(("status", "context")),
                                        "retained source evidence")
    if evidence["status"] != "retained_sources":
        raise ValueError("research review requires retained_sources evidence")
    return canonical_json(build_review_card(card["document"], first["exact_text"],
                                            evidence["context"], refinement_inputs=inputs[1:]))
