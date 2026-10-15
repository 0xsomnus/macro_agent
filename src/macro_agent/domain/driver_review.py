"""Evidence-qualified driver review, without thesis or publication authority.

The enclosing application pins the approved interpretation and eligible evidence.
This module validates references and shape. It cannot verify semantic fidelity,
causation, source truth, materiality or market-price observations.
"""

MAX_DRIVERS = 32
MAX_ITEMS = 16
MAX_TEXT = 2_000
SUPPORT = frozenset(("supports", "challenges", "mixed", "unresolved"))
RELATIONSHIPS = frozenset(("competing", "amplifying", "offsetting", "additional"))


def _object(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError(f"{label} requires exactly its documented fields")


def _text(value, label):
    if type(value) is not str or not value.strip() or len(value) > MAX_TEXT or "\x00" in value:
        raise ValueError(f"{label} requires bounded nonblank text")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError(f"{label} requires valid Unicode") from None
    return value


def _array(value, label, limit=MAX_ITEMS):
    if type(value) is not list or len(value) > limit:
        raise ValueError(f"{label} requires a bounded array")
    return value


def _strings(value, label, *, required=False):
    result = [_text(item, label) for item in _array(value, label)]
    if len(result) != len(set(result)) or required and not result:
        raise ValueError(f"{label} requires unique text and any required entries")
    return result


def _references(value, allowed, label):
    result = _strings(value, label)
    if any(item not in allowed for item in result):
        raise ValueError(f"{label} must reference supplied eligible identities")
    return result


def _indices(value, drivers, label):
    result = _array(value, label, MAX_DRIVERS)
    if any(type(index) is not int or not 0 <= index < len(drivers) for index in result):
        raise ValueError(f"{label} must reference exact approved driver indices")
    if len(result) != len(set(result)):
        raise ValueError(f"{label} must be unique")
    return result


def _assessment(value, statuses, claim_ids, prior_ids, label):
    _object(value, ("status", "claim_ids", "prior_analysis_ids", "reasoning", "uncertainty"), label)
    if type(value["status"]) is not str or value["status"] not in statuses:
        raise ValueError(f"{label} status is unsupported")
    claims = _references(value["claim_ids"], claim_ids, f"{label} claims")
    priors = _references(value["prior_analysis_ids"], prior_ids, f"{label} prior analyses")
    if value["status"] != "unresolved" and not (claims or priors):
        raise ValueError(f"{label} conclusions require eligible evidence references")
    _text(value["reasoning"], f"{label} reasoning")
    _text(value["uncertainty"], f"{label} uncertainty")


def validate_driver_assessment(value, *, drivers, claim_ids, prior_analysis_ids):
    """Validate a complete review of the exact supplied approved drivers.

    ``claim_ids`` can identify source-attributed news facts or morning claims.
    Prior references identify eligible model interpretations, never factual proof.
    Nothing here installs new drivers or authorizes notifications.
    """
    if type(drivers) is not list or len(drivers) > MAX_DRIVERS or any(type(item) is not str for item in drivers):
        raise ValueError("approved drivers require their bounded exact string list")
    _object(value, ("approved_drivers", "other_drivers", "progression", "price_observation",
                    "entry_assessment", "attention"), "driver assessment")
    reviews = _array(value["approved_drivers"], "approved driver reviews", MAX_DRIVERS)
    seen = set()
    for review in reviews:
        _object(review, ("driver_index", "exact_driver", "premise", "mechanism", "discriminating_questions"),
                "approved driver review")
        index = review["driver_index"]
        _indices([index], drivers, "approved driver review index")
        if index in seen or type(review["exact_driver"]) is not str or review["exact_driver"] != drivers[index]:
            raise ValueError("each review must preserve one exact approved driver")
        seen.add(index)
        for name in ("premise", "mechanism"):
            _assessment(review[name], SUPPORT, claim_ids, prior_analysis_ids, name)
        _strings(review["discriminating_questions"], "driver discriminating questions")
    if seen != set(range(len(drivers))):
        raise ValueError("driver assessment must cover every exact approved driver once")
    hypotheses = set()
    for other in _array(value["other_drivers"], "other drivers"):
        _object(other, ("hypothesis_id", "relationship", "driver_indices", "claim_ids", "counter_claim_ids",
                        "prior_analysis_ids", "explanation", "transmission", "assumptions", "uncertainty",
                        "discriminating_questions"), "other driver")
        identity = _text(other["hypothesis_id"], "other driver identity")
        if identity in hypotheses:
            raise ValueError("other driver identities must be unique")
        hypotheses.add(identity)
        if type(other["relationship"]) is not str or other["relationship"] not in RELATIONSHIPS:
            raise ValueError("other driver relationship is unsupported")
        _indices(other["driver_indices"], drivers, "other driver approved references")
        if other["relationship"] != "additional" and not other["driver_indices"]:
            raise ValueError("a related competing, amplifying or offsetting hypothesis requires an approved driver")
        if not _references(other["claim_ids"], claim_ids, "other driver claims"):
            raise ValueError("new driver hypotheses require current attributed source claims")
        _references(other["counter_claim_ids"], claim_ids, "other driver counter claims")
        _references(other["prior_analysis_ids"], prior_analysis_ids, "other driver prior analyses")
        for name in ("explanation", "transmission", "uncertainty"):
            _text(other[name], f"other driver {name}")
        _strings(other["assumptions"], "other driver assumptions")
        _strings(other["discriminating_questions"], "other driver discriminating questions")
    _assessment(value["progression"], frozenset(("progressing", "not_progressing", "mixed", "unresolved")),
                claim_ids, prior_analysis_ids, "thesis progression")
    for name, expected in (("price_observation", "unavailable"), ("entry_assessment", "not_assessed")):
        _object(value[name], ("status", "gaps"), name)
        if value[name]["status"] != expected or type(value[name]["status"]) is not str:
            raise ValueError(f"{name} remains {expected} without verified market data")
        _strings(value[name]["gaps"], f"{name} gaps", required=True)
    attention = value["attention"]
    _object(attention, ("status", "driver_indices", "claim_ids", "prior_analysis_ids", "reasoning", "uncertainty"),
            "driver attention recommendation")
    if type(attention["status"]) is not str or attention["status"] not in ("review_recommended", "not_identified"):
        raise ValueError("driver attention recommendation status is unsupported")
    _indices(attention["driver_indices"], drivers, "attention driver indices")
    claims = _references(attention["claim_ids"], claim_ids, "attention claims")
    priors = _references(attention["prior_analysis_ids"], prior_analysis_ids, "attention prior analyses")
    if attention["status"] == "review_recommended" and not claims:
        raise ValueError("a material-review recommendation requires current attributed evidence")
    _text(attention["reasoning"], "attention reasoning")
    _text(attention["uncertainty"], "attention uncertainty")
    return value


def driver_assessment_example(drivers):
    def unresolved():
        return {"status": "unresolved", "claim_ids": [], "prior_analysis_ids": [],
                "reasoning": "The supplied evidence does not settle this question.",
                "uncertainty": "Attribution and coverage remain limited."}
    return {
        "approved_drivers": [{"driver_index": index, "exact_driver": driver,
            "premise": unresolved(), "mechanism": unresolved(), "discriminating_questions": []}
            for index, driver in enumerate(drivers)],
        "other_drivers": [], "progression": unresolved(),
        "price_observation": {"status": "unavailable", "gaps": ["No verified instrument-price history is supplied."]},
        "entry_assessment": {"status": "not_assessed", "gaps": ["Verified prices and a prospective entry plan are unavailable."]},
        "attention": {"status": "not_identified", "driver_indices": [], "claim_ids": [], "prior_analysis_ids": [],
            "reasoning": "No material driver change is established from this limited input.",
            "uncertainty": "This recommendation cannot establish non-materiality or suppress monitoring."},
    }


def driver_assessment_instructions():
    return """
driver_assessment is a separate evidence-qualified review, never approved intent.
Use exactly the fields in its example. approved_drivers covers every supplied
approved driver exactly once using its zero-based driver_index and exact_driver
text. Assess premise (whether the event or condition occurred) separately from
mechanism (whether its proposed transmission is supported). Both use status
supports, challenges, mixed or unresolved, claim_ids, prior_analysis_ids,
reasoning and uncertainty. Event confirmation does not verify a price effect.
Non-unresolved conclusions require eligible claim or prior-analysis references.
The claim_ids in this section reference this output's attributed source claims
(fact_id for news, claim_id for morning synthesis), never trader quotations.
Prior analyses remain model interpretations and cannot verify source truth.
Each driver also has discriminating_questions, a bounded array of questions
that distinguish explanations. Preserve approved driver text and uncertainty.

other_drivers contains proposed agent hypotheses only. Each has hypothesis_id,
relationship (competing, amplifying, offsetting or additional), driver_indices,
claim_ids, counter_claim_ids, prior_analysis_ids, explanation, transmission,
assumptions, uncertainty and discriminating_questions. Its claim_ids must be
nonempty references to attributed claims in this output. Counter-evidence may
be absent only when unavailable; state that gap. All references must be unique.
Except additional, a relationship requires approved driver_indices. Never infer
independent corroboration from repeated reports or promote a new driver into
approved belief. Explain alternatives before asking consequential intent questions.

progression independently assesses status progressing, not_progressing, mixed
or unresolved with claim_ids, prior_analysis_ids, reasoning and uncertainty.
Progression does not establish original causal attribution or entry quality.
price_observation stays {status: unavailable, gaps: [nonblank explanations]}.
entry_assessment stays {status: not_assessed, gaps: [nonblank explanations]}.
There is no verified price history or entry plan. Trader-observed prices remain
unverified. Do not manufacture direction, deadlines, targets, stops or R:R.

attention has status review_recommended or not_identified, driver_indices,
claim_ids, prior_analysis_ids, reasoning and uncertainty. A review recommendation
requires current attributed claim_ids and explains a consequential change to
premise, mechanism, horizon or invalidation, including when no trade exists.
It is an analytical recommendation with no publication or notification authority.
Novelty or wording alone is insufficient. Distinguish what new evidence changes
from what remains intact using eligible predecessor references when present.
Do not claim a historical change without an eligible prior assessment. No prior
assessment is a visible gap, not permission to invent one. All arrays have at
most 16 entries except complete approved_drivers and driver_indices (at most 32).
All text is nonblank, at most 2000 characters; exact_driver preserves input text.
"""
