"""Inspect a deterministic daily review using entirely fictional retained data."""

import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from macro_agent.domain.daily_review import (
    DailyReviewLimits, DailyReviewPeriod, DailyReviewScope, RetainedNewsAnalysis,
    RetainedReport, ReviewIssue, SourceContractReference, build_daily_review,
)
from macro_agent.domain.models import canonical_json, text_digest


def demonstration():
    start = datetime(2026, 10, 8, tzinfo=timezone.utc)
    cutoff = start + timedelta(days=1)
    period = DailyReviewPeriod(start, cutoff, cutoff + timedelta(hours=1))
    contract = SourceContractReference("fixture-divergence", "fictional-contract-v1",
        text_digest(canonical_json({"synthetic": True, "permission": "fictional fixture only"})))
    positions = [{"position_id": "fixture-position", "version_id": "position-version-current",
                  "status": "open", "underlying": "NQ", "direction": "long"}]
    scope = DailyReviewScope("fictional-owner", "fixture-thesis", "approval-current",
        "meaning-current", text_digest(canonical_json({"positions": positions})),
        ("position-version-current",), (contract,), "fictional-predecessor-context")
    payload = json.loads((ROOT / "fixtures/news_analysis_case.json").read_text(encoding="utf-8"))["items"][0]
    def report(identity, received, witness):
        content = canonical_json({**payload, "id": identity,
            "title": payload["title"] + " (" + identity + ")"})
        return RetainedReport(identity, identity + "-report", contract.source_id,
            contract.version_id, contract.digest, content, text_digest(content), received, witness)

    old = report("old-report", start - timedelta(days=2), start - timedelta(days=1))
    new = report("new-report", start + timedelta(hours=6), start + timedelta(hours=6, seconds=1))
    unproven = report("unproven-report", start + timedelta(hours=9), None)

    def analysis(identity, source, admitted, finished, witness, *, current=False):
        retained_payload = json.loads(source.payload_json)
        context = {"source": {"source_key": source.source_id, "revision_id": source.revision_id,
                       "digest": source.payload_digest,
                       **{key: retained_payload[key] for key in ("title", "content", "url", "published_at")}},
            "approved_thesis": {"thesis_id": scope.thesis_id,
                "approval_id": scope.approval_id if current else "approval-original",
                "interpretation_id": scope.interpretation_id if current else "meaning-original",
                "exact_text": "Policy easing may support equities.", "drivers": ["Policy easing"],
                "horizon": "six months", "invalidation_signposts": []},
            "positions": positions}
        document = json.loads((ROOT / "fixtures/news_analysis_response.json").read_text(encoding="utf-8"))
        for fact in document["attributed_facts"]:
            fact["source_revision_id"] = source.revision_id
        return RetainedNewsAnalysis(identity, scope.owner_id, scope.thesis_id, source.revision_id,
            admitted, finished, witness, "analysed", (), "current" if current else "stale",
            () if current else ("approved_meaning_changed",), canonical_json(context),
            canonical_json(document), canonical_json({"reported_cost_usd": None, "estimated_cost_usd": "0.0002"}))

    late = analysis("late-analysis-of-old-report", old, start - timedelta(hours=1),
                    start + timedelta(hours=2), start + timedelta(hours=3))
    current = analysis("current-analysis", new, start + timedelta(hours=7),
                       start + timedelta(hours=8), start + timedelta(hours=8, seconds=1), current=True)
    pending = replace(analysis("unresolved-admission", unproven, start + timedelta(hours=10),
        start + timedelta(hours=11), None), original_status=None, finished_at=None,
        document_json=None, current_disposition="unresolved", current_stale_reasons=(),
        costs_json=canonical_json({"reported_cost_usd": None, "estimated_cost_usd": None}),
        stop_reason="Fictional crash after admission; remote outcome remains unknown.")
    later = analysis("postcutoff-analysis", old, cutoff - timedelta(minutes=10),
                     cutoff + timedelta(minutes=10), cutoff + timedelta(minutes=11))
    issue = ReviewIssue("fictional-coverage-gap", "coverage_gap",
        canonical_json({"detail": "Only this synthetic source was selected; broad market coverage is absent."}),
        source_id=contract.source_id)
    limits = DailyReviewLimits(reports=10, analyses=10, exposure_versions=200,
        issues=10, source_contracts=10, encoded_bytes=262_144)
    candidate = build_daily_review(period=period, scope=scope, reports=(old, new, unproven),
        analyses=(late, current, pending, later), issues=(issue,), limits=limits)
    return {"synthetic": True, "scope": "pure domain assembly, no persistence or provider calls",
        "time_limit": "All timestamps and availability witnesses are invented fixture inputs.",
        "candidate_digest": candidate.digest, "candidate": candidate.to_dict()}


def readable_report(result):
    review = result["candidate"]
    lines = ["# Deterministic daily review demonstration", "",
        "Entirely fictional retained inputs. No database, network, scheduler or model is invoked.",
        "Fixture timestamps illustrate caller-supplied availability witnesses; they are not measured commits.", "",
        "The reporting interval is (2026-10-08 00:00 UTC, 2026-10-09 00:00 UTC]. Preparation is at 01:00 UTC.", "",
        "| Record | Classification | Preserved distinction |", "| --- | --- | --- |",
        "| Old report | Background | Publication and receipt do not decide new availability. |",
        "| Late analysis of old report | New analysis | Original approval and result remain; current meaning has changed. |",
        "| New report and current analysis | New | Complete selected exposure references agree. |",
        "| Report without witness | Deferred | Receipt alone cannot establish durable availability. |",
        "| Unresolved admission | Deferred and unresolved | No invented completion, billed cost or paid retry. |",
        "| Analysis first available after cutoff | Deferred | It belongs to a later reporting interval. |", "",
        f"New eligible reports: {review['new_eligible_report_count']}. Assembly inference calls: {review['assembly_inference_calls']}.",
        f"Candidate digest: `{result['candidate_digest']}`.", "",
        "The full JSON retains exact attributed source text, original model documents, source-contract references,",
        "predecessor reference, full exposure pins, unresolved work, coverage gaps and unknown reported costs.", "",
        "## Limits", "",
        "The builder validates supplied data and rejects overflow without truncation. It does not prove completeness,",
        "source rights, currentness, owner authorization, persistence, context lineage or correction/publication ordering.",
        "It grants no thesis approval, notification or retry authority. A scheduled daily briefing and continuous runner",
        "remain to be implemented. Zero assembly inference cost does not estimate prior model, compute or storage costs.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = demonstration()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(readable_report(result), encoding="utf-8")
