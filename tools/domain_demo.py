"""Record two fictional correction orderings for read-only inspection."""

import argparse
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from domain_fixture import correction_pin, fixture_case
from lab_sqlite_store import SQLitePublicationStore
from macro_agent.application.publication import publish


def demonstration():
    candidate, dependencies = fixture_case()
    correction = correction_pin()
    with TemporaryDirectory(prefix="macro-publication-") as directory:
        reports = {}
        for scenario in ("correction_first", "publication_first"):
            store = SQLitePublicationStore(Path(directory) / (scenario + ".sqlite"))
            store.bootstrap(candidate.brief_id, candidate.owner_id, dependencies,
                            candidate.snapshot.cutoff)
            if scenario == "publication_first":
                publish(store, candidate, candidate.snapshot.cutoff)
            store.advance_dependency(candidate.brief_id, correction, correction.known_at)
            decision = publish(store, candidate, correction.known_at + timedelta(seconds=1))
            before = store.inspect(candidate.brief_id)
            fresh, _ = fixture_case("analysis-r2", expected_generation=before["generation"], revision=2)
            publish(store, fresh, correction.known_at + timedelta(seconds=2))
            reports[scenario] = {"old_analysis_current_disposition": decision.status,
                "before_reassessment": before, "after_reassessment": store.inspect(candidate.brief_id)}
    return {"synthetic": True, "provider_calls": 0, "provider_spend": 0,
        "scope": "independent domain core and local SQLite adapter mechanics",
        "race_proof": "Separate-connection tests prove ordering; this report is sequential.",
        "scenarios": reports}


def readable_report(report):
    lines = ["# Publication audit demonstration", "",
        "Fictional inputs, no provider calls or spend. Separate-connection tests prove",
        "the local SQLite ordering behavior. This report illustrates recorded results.", ""]
    for scenario, details in report["scenarios"].items():
        before, after = details["before_reassessment"], details["after_reassessment"]
        lines += ["## " + scenario.replace("_", " ").capitalize(), "",
            "| Assessment | Original decision | Current before reassessment |",
            "| --- | --- | --- |"]
        for item in before["assessments"]:
            lines.append(f"| {item['assessment_id']} | {item['decision']['status']} | {item['is_current']} |")
        lines += ["", "Retry/late-completion result: " + details["old_analysis_current_disposition"] + ".",
            "Current after fresh evidence: " + after["current_assessment_id"] + ".", "",
            "| Recorded transition | Result |", "| --- | --- |"]
        for item in after["audit"]:
            detail = item["detail"]
            result = detail.get("status", detail.get("current", {}).get("version_id", "fixture setup"))
            lines.append(f"| {item['kind']} | {result} |")
        lines += ["", "| Notification assessment | Final local state |", "| --- | --- |"]
        for item in after["notifications"]:
            lines.append(f"| {item['assessment_id']} | {item['state']} |")
        lines.append("")
    lines += ["## Limits", "",
        "No live feed, model analysis, authenticated service, global correction fan-out,",
        "durable worker leasing, or external notification channel is exercised.",
        "These results do not establish the behavior of another database adapter.", ""]
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
