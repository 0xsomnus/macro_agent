"""Translate fictional recorded inputs into the independent Python contracts.

This is a laboratory adapter, not HTTP validation or a live source adapter.
"""

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from macro_agent.domain.models import (CompiledThesisVersion, ContextSnapshot,
    EventRevision, PinnedDependency, UserThesisVersion, VersionedContent, canonical_json)
from macro_agent.domain.publication import FactClaim, PublicationCandidate
from macro_agent.domain.routing import Screening
from macro_agent.domain.thesis import ApprovalRequest, approve_thesis
from macro_agent.domain.time import SourceTimes, parse_instant


def fixture_case(assessment_id="analysis-r1", expected_generation=0, revision=1, *, owner_id=None):
    fixture = json.loads((ROOT / "fixtures/pilot.json").read_text())
    if fixture.get("synthetic") is not True:
        raise ValueError("laboratory only accepts fictional fixtures")
    source = fixture["thesis"]
    approved_at = parse_instant(source["approved_at"])
    thesis = UserThesisVersion(source["id"], "fixture-gold-thesis", owner_id or source["owner_id"],
                              source["text"], approved_at)
    meaning = fixture["interpretation"]
    compiled = CompiledThesisVersion(meaning["id"], thesis.version_id,
        tuple(meaning["drivers"]), meaning["horizon"],
        tuple(meaning["invalidation_signposts"]), approved_at)
    approval = approve_thesis(thesis, compiled, ApprovalRequest(
        "fixture-approval-v1", thesis.owner_id, "user", thesis.version_id,
        thesis.text_digest, compiled.version_id, compiled.digest, approved_at), now=approved_at)
    event_data = next(e for e in fixture["events"]
                      if e["event_id"] == "fictional-release" and e["revision"] == revision)
    event = EventRevision(event_data["event_id"], revision, event_data["source_id"],
        event_data["source_contract_version"], SourceTimes(
            parse_instant(event_data["public_available_at"]),
            parse_instant(event_data["system_received_at"]),
            parse_instant(event_data["known_at"])), canonical_json(event_data["facts"]))
    records = {record["id"]: VersionedContent(record["id"], record["kind"],
        parse_instant(record["known_at"]), canonical_json(record["content"]))
        for record in fixture["context_versions"]}
    contract = records[event.source_contract_version_id]
    pins = [
        PinnedDependency("user_thesis", thesis.version_id, thesis.text_digest, approved_at),
        PinnedDependency("compiled_thesis", compiled.version_id, compiled.digest, approved_at),
        PinnedDependency("activation", approval.approval_id, approval.digest, approved_at),
        PinnedDependency("event_revision", event.version_id, event.digest, event.times.known_at),
        PinnedDependency("source_contract", contract.version_id, contract.digest, contract.known_at),
    ]
    roles = {"source_manifest_version": "source_manifest",
             "coverage_contract_version": "coverage", "exposure_version": "exposure",
             "macro_context_version": "macro_context", "knowledge_version": "knowledge",
             "rule_version": "rules"}
    for binding, role in roles.items():
        record = records[fixture["context_bindings"][binding]]
        pins.append(PinnedDependency(role, record.version_id, record.digest, record.known_at))
    # Explicit no-model inputs avoid a missing-version loophole in the snapshot.
    for role, content in {
        "execution_graph": {"scope": "publication-only synthetic mechanics"},
        "entitlements": {"scope": "fictional-owner synthetic display"},
        "budget": {"provider_calls": 0, "provider_spend": 0},
        "model": {"state": "not_used"}, "prompt": {"state": "not_used"},
    }.items():
        record = VersionedContent("fixture-" + role + "-v1", role, approved_at,
                                  canonical_json(content))
        pins.append(PinnedDependency(role, record.version_id, record.digest, record.known_at))
    dependencies = tuple(sorted(pins, key=lambda pin: pin.role))
    candidate = PublicationCandidate(assessment_id, "run:" + assessment_id,
        "fixture-gold-release-brief", thesis.owner_id,
        ContextSnapshot("snapshot:" + assessment_id, event.times.known_at, dependencies),
        expected_generation, event, contract, Screening(**event_data["screening"]),
        (FactClaim("reported_measure", canonical_json(event_data["facts"]["reported_measure"])),))
    return candidate, dependencies


def correction_pin():
    _, dependencies = fixture_case(revision=2)
    return next(pin for pin in dependencies if pin.role == "event_revision")
