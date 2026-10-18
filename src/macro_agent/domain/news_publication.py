"""Typed publication of retained driver analysis, with qualified internal attention.

The model proposes attention. This admission separately checks exact retained
inputs, source quotations, approved driver references and deterministic change.
It establishes neither semantic materiality nor causal truth or delivery.
"""

from dataclasses import dataclass
from datetime import datetime
import json
from uuid import UUID

from .models import canonical_json, normalize_json_object, require_digest, text_digest
from .news_analysis import DRIVER_SCHEMA_VERSION, validate_news_document
from .publication import PublicationDecision
from .time import as_utc

KIND = "retained_driver_news_analysis"
POLICY_VERSION = "evidence-linked-driver-review-v1"


def _uuid(value, name):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError(f"{name} requires a canonical UUID")


def validate_analysis_content(content_json):
    normalized = normalize_json_object(content_json)
    value = json.loads(normalized)
    fields = {"analysis_id", "owner_id", "thesis_id", "approval_id", "exposure_digest",
              "created_at", "finished_at", "original_status", "original_stale_reasons",
              "context_id", "context_digest", "context", "document", "model"}
    if set(value) != fields:
        raise ValueError("News publication requires the complete exact analysis contract")
    for name in ("analysis_id", "owner_id", "thesis_id", "approval_id", "context_id"):
        _uuid(value[name], name)
    for name in ("exposure_digest", "context_digest"):
        require_digest(value[name], name)
    if (value["original_status"] not in ("analysed", "stale")
            or type(value["original_stale_reasons"]) is not list
            or value["context"].get("driver_review") is not True
            or value["context"].get("cumulative", {}).get("context_id") != value["context_id"]
            or text_digest(canonical_json(value["context"])) != value["context_digest"]
            or value["document"].get("schema_version") != DRIVER_SCHEMA_VERSION):
        raise ValueError("News publication requires a retained cumulative driver-review result")
    validate_news_document(canonical_json(value["document"]), value["context"])
    start = as_utc(datetime.fromisoformat(value["created_at"]))
    finish = as_utc(datetime.fromisoformat(value["finished_at"]))
    if finish < start:
        raise ValueError("Analysis completion cannot precede admission")
    return normalized


@dataclass(frozen=True, slots=True)
class NewsPublicationCandidate:
    command_id: str
    owner_id: str
    thesis_id: str
    brief_id: str
    analysis_id: str
    analysis_digest: str
    expected_generation: int
    policy_version: str
    content_json: str

    def __post_init__(self):
        for name in ("command_id", "owner_id", "thesis_id", "analysis_id"):
            _uuid(getattr(self, name), name)
        require_digest(self.analysis_digest, "analysis_digest")
        if self.brief_id != "news:" + self.thesis_id or self.policy_version != POLICY_VERSION:
            raise ValueError("News publication requires its separate stable stream and explicit policy")
        if type(self.expected_generation) is not int or not 0 <= self.expected_generation <= 2**63-1:
            raise ValueError("News publication generation requires a nonnegative database integer")
        normalized = validate_analysis_content(self.content_json)
        object.__setattr__(self, "content_json", normalized)
        value = json.loads(normalized)
        if (text_digest(normalized) != self.analysis_digest
                or any(value[name] != getattr(self, name) for name in ("owner_id", "thesis_id", "analysis_id"))):
            raise ValueError("News publication must bind the exact retained analysis and private scope")

    @property
    def assessment_id(self):
        return "news:" + self.analysis_id

    @property
    def payload(self):
        return canonical_json({"kind": KIND, "command_id": self.command_id,
            "assessment_id": self.assessment_id, "owner_id": self.owner_id,
            "thesis_id": self.thesis_id, "brief_id": self.brief_id,
            "analysis_id": self.analysis_id, "analysis_digest": self.analysis_digest,
            "expected_generation": self.expected_generation, "policy_version": self.policy_version,
            "content": json.loads(self.content_json)})

    @property
    def digest(self):
        return text_digest(self.payload)

    @property
    def intent_id(self):
        return "notice:" + text_digest(canonical_json([self.owner_id, self.brief_id, self.assessment_id]))


def decide_news_publication(candidate, *, owner_id, thesis_id, generation, changed_at,
                            latest_analysis_id, stale_reasons, at):
    if type(candidate) is not NewsPublicationCandidate:
        raise TypeError("News publication requires a typed retained-analysis candidate")
    if (owner_id, thesis_id) != (candidate.owner_id, candidate.thesis_id):
        raise PermissionError("News publication belongs to another private stream")
    content = json.loads(candidate.content_json)
    if as_utc(at) < max(as_utc(changed_at), as_utc(datetime.fromisoformat(content["finished_at"]))):
        raise ValueError("News publication cannot precede protected state or analysis completion")
    if candidate.expected_generation > generation:
        raise ValueError("News publication cannot claim an unobserved generation")
    if stale_reasons or content["original_status"] != "analysed":
        reasons = tuple(sorted(set(stale_reasons or ("original_analysis_stale",))))
        return PublicationDecision("superseded", reasons, True)
    if candidate.analysis_id != latest_analysis_id:
        return PublicationDecision("superseded", ("newer_retained_analysis",), False)
    if candidate.expected_generation != generation:
        return PublicationDecision("superseded", ("newer_publication",), False)
    return PublicationDecision("current", ("all_dependencies_current",), False)


def _driver_signal(document):
    review = document["driver_assessment"]
    indices = review["attention"]["driver_indices"]
    by_index = {item["driver_index"]: item for item in review["approved_drivers"]}
    return [{"driver_index": index, "exact_driver": by_index[index]["exact_driver"],
        "premise": by_index[index]["premise"]["status"],
        "mechanism": by_index[index]["mechanism"]["status"],
        "other_relationships": sorted({item["relationship"] for item in review["other_drivers"]
            if index in item["driver_indices"]})} for index in sorted(indices)]


def decide_attention(content, *, previous_document=None, prior_signatures=()):
    """Conservative categorical review policy, not calibrated market materiality.

    Repeated prose, facts with unchanged driver states, and unlinked alternatives
    cannot interrupt. A first evidence-linked review can request internal human
    attention. Later review requires changed typed driver support/relationship.
    Semantic duplicates across rewritten source passages are not established.
    """
    document = content["document"]
    attention = document["driver_assessment"]["attention"]
    def result(status, reason, signature=None):
        return {"policy_version": POLICY_VERSION, "status": status, "reason": reason,
                "signal_digest": signature, "kind": "qualified_driver_review"}
    if attention["status"] != "review_recommended":
        return result("not_requested", "The analytical output did not request driver review; this is not proof of non-materiality.")
    if not attention["driver_indices"]:
        return result("unmapped", "The proposed review does not identify an exact approved driver; investigation remains unresolved.")
    selected = set(attention["driver_indices"])
    attached_claims = {claim for item in document["driver_assessment"]["approved_drivers"]
        if item["driver_index"] in selected for name in ("premise", "mechanism") for claim in item[name]["claim_ids"]}
    attached_claims.update(claim for item in document["driver_assessment"]["other_drivers"]
        if selected.intersection(item["driver_indices"]) for claim in item["claim_ids"])
    if not attached_claims.intersection(attention["claim_ids"]):
        return result("unlinked", "Current attention quotations are not linked to the selected approved-driver assessment; investigation remains unresolved.")
    signal = _driver_signal(document)
    facts = {item["fact_id"]: item for item in document["attributed_facts"]}
    quotes = sorted({" ".join(facts[key]["exact_quote"].split()).casefold() for key in attention["claim_ids"]})
    signature = text_digest(canonical_json({"drivers": signal, "quoted_evidence": quotes}))
    if signature in prior_signatures:
        return result("duplicate", "This exact evidence and typed driver signal already requested review.", signature)
    if previous_document is not None:
        old = {item["driver_index"]: item for item in previous_document["driver_assessment"]["approved_drivers"]}
        old_other = previous_document["driver_assessment"]["other_drivers"]
        changed = any(index not in old or item["exact_driver"] != old[index]["exact_driver"]
            or item["premise"] != old[index]["premise"]["status"]
            or item["mechanism"] != old[index]["mechanism"]["status"]
            or item["other_relationships"] != sorted({other["relationship"] for other in old_other if index in other["driver_indices"]})
            for item in signal for index in (item["driver_index"],))
        if not changed:
            return result("unchanged", "New wording or evidence without a changed typed approved-driver assessment updates the brief without another interruption.", signature)
    return result("review_requested", "Current attributed evidence and a first or changed typed approved-driver assessment qualify for internal review; materiality and causation remain unverified.", signature)
