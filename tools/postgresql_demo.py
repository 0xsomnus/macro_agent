"""Record fictional correction orderings through the real PostgreSQL adapter.

This is a sequential illustration. Actual concurrency is proved by separate
integration tests, rather than by the order of calls in this demonstration.
"""

import argparse
from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
OWNER_ID = "f87df2c4-3bf1-4f49-b81d-186864056a02"
OWNER_USERNAME = "macro-postgresql-synthetic-demo"
BRIEF_IDS = {
    "correction_first": "postgres-demo-correction-first",
    "publication_first": "postgres-demo-publication-first",
}


def _configure_django():
    sys.path.insert(0, str(ROOT / "src"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "macro_agent.web.local_settings")
    if os.environ["DJANGO_SETTINGS_MODULE"] != "macro_agent.web.local_settings":
        raise ValueError("demonstration requires the explicit local settings module")
    import django
    django.setup()


def _fixture_owner(*, create):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.hashers import make_password

    users = get_user_model().objects
    if create:
        owner, _ = users.get_or_create(pk=OWNER_ID, defaults={
            "username": OWNER_USERNAME, "password": make_password(None),
            "is_active": True, "is_staff": False, "is_superuser": False,
        })
    else:
        owner = users.filter(pk=OWNER_ID).first()
    if owner is None:
        raise ValueError("synthetic demonstration owner does not exist")
    if (owner.username != OWNER_USERNAME or owner.has_usable_password()
            or not owner.is_active or owner.is_staff or owner.is_superuser):
        raise ValueError("existing account does not match the restricted synthetic fixture owner")
    return owner


def demonstration(*, inspect_only=False):
    from django.conf import settings
    from django.db import transaction
    from domain_fixture import correction_pin, fixture_case
    from macro_agent.application.publication import publish
    from macro_agent.persistence.models import BriefStateRecord
    from macro_agent.persistence.publication_store import DjangoPublicationStore

    candidate, dependencies = fixture_case(owner_id=OWNER_ID)
    correction = correction_pin()
    if inspect_only:
        _fixture_owner(create=False)
        store = DjangoPublicationStore(OWNER_ID)
        scenarios = {name: {"current_state": store.inspect(brief_id)}
                     for name, brief_id in BRIEF_IDS.items()}
    else:
        if settings.MACRO_ALLOW_SYNTHETIC_SETUP is not True:
            raise PermissionError("write demonstration requires MACRO_ALLOW_SYNTHETIC_SETUP=1")
        # All setup commits together. An existing brief is never reinitialized.
        with transaction.atomic():
            if BriefStateRecord.objects.filter(brief_id__in=BRIEF_IDS.values()).exists():
                raise ValueError("demonstration briefs already exist; use --inspect-only")
            _fixture_owner(create=True)
            store = DjangoPublicationStore(OWNER_ID)
            for brief_id in BRIEF_IDS.values():
                store.bootstrap_synthetic(brief_id, dependencies, candidate.snapshot.cutoff, synthetic=True)
        scenarios = {}
        for name, brief_id in BRIEF_IDS.items():
            original = replace(candidate, brief_id=brief_id)
            if name == "publication_first":
                publish(store, original, original.snapshot.cutoff)
            store.register_synthetic_dependency(brief_id, correction, synthetic=True)
            store.advance_evidence(brief_id, correction, original.snapshot.dependency("event_revision"),
                                   correction.known_at)
            disposition = publish(store, original, correction.known_at + timedelta(seconds=1))
            before = store.inspect(brief_id)
            fresh, _ = fixture_case("analysis-r2", expected_generation=before["generation"],
                                    revision=2, owner_id=OWNER_ID)
            publish(store, replace(fresh, brief_id=brief_id), correction.known_at + timedelta(seconds=2))
            scenarios[name] = {
                "old_analysis_current_disposition": disposition.status,
                "before_reassessment": before,
                "after_reassessment": store.inspect(brief_id),
            }
    return {
        "synthetic": True, "mode": "inspect_only" if inspect_only else "sequential_demonstration",
        "provider_calls": 0, "provider_spend": 0, "owner_id": OWNER_ID,
        "scope": "Django/PostgreSQL publication mechanics with a restricted synthetic owner",
        "race_proof": "Separate-connection integration tests prove ordering; this report is sequential.",
        "scenarios": scenarios,
    }


def readable_report(report):
    lines = ["# PostgreSQL publication audit demonstration", "",
             "Fictional recorded inputs, zero provider calls and spend. These snapshots",
             "illustrate the Django/PostgreSQL adapter's persisted results. Separate",
             "integration tests prove concurrency; this report is sequential.", ""]
    if report["mode"] == "inspect_only":
        lines += ["Read-only inspection of existing demonstration state. Earlier snapshots",
                  "are not reconstructed or claimed here.", ""]
    for name, scenario in report["scenarios"].items():
        before = scenario.get("before_reassessment")
        after = scenario.get("after_reassessment", scenario.get("current_state"))
        lines += ["## " + name.replace("_", " ").capitalize(), "",
                  "Brief: " + after["brief_id"] + ".", ""]
        if before is not None:
            lines += ["| Assessment | Initial decision | Current before reassessment |",
                      "| --- | --- | --- |"]
            for record in before["assessments"]:
                lines.append(f"| {record['assessment_id']} | {record['decision']['status']} | {record['is_current']} |")
            lines += ["", "Old-analysis disposition: " + scenario["old_analysis_current_disposition"] + ".", ""]
        lines += ["Current persisted assessment: " + (after["current_assessment_id"] or "none") + ".",
                  "Generation: " + str(after["generation"]) + ".", "",
                  "| Recorded transition | Result |", "| --- | --- |"]
        for entry in after["audit"]:
            detail = entry["detail"]
            result = detail.get("status", detail.get("current", {}).get("version_id",
                                detail.get("dependency", {}).get("version_id", "fixture setup")))
            lines.append(f"| {entry['kind']} | {result} |")
        lines += ["", "| Notification assessment | Persisted local state |", "| --- | --- |"]
        for intent in after["notifications"]:
            lines.append(f"| {intent['assessment_id']} | {intent['state']} |")
        work_states = ", ".join(work["state"] for work in after["reassessment"]) or "none"
        lines += ["", "Reassessment work: " + work_states + ".", ""]
    lines += ["## Limits", "",
              "No live feed, model analysis, trader onboarding, global correction fan-out,",
              "durable worker leasing, or external notification channel is exercised.",
              "The fixture owner's unusable password prevents interactive login. Synthetic",
              "bootstrap is not durable approval of a real trader's thesis.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--inspect-only", action="store_true",
                        help="read existing demo briefs without initializing or changing database state")
    args = parser.parse_args()
    try:
        _configure_django()
        result = demonstration(inspect_only=args.inspect_only)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(readable_report(result), encoding="utf-8")
    except (ValueError, PermissionError) as error:
        parser.exit(2, str(error) + "\n")
    except Exception as error:
        # Avoid printing credentials, settings, SQL parameters or connection DSNs.
        parser.exit(2, "PostgreSQL demonstration failed (" + type(error).__name__ + ").\n")


if __name__ == "__main__":
    main()
