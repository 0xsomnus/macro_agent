"""Sequential fictional thesis approvals, with immutable history inspection.

No model or source call occurs. Integration tests separately establish HTTP
authority and concurrency. This command only operates in the gated local lab.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from uuid import UUID, uuid5


ROOT = Path(__file__).resolve().parents[1]
OWNER_ID = "d54e3108-120c-4856-867a-34bdc1159e1a"
USERNAME = "macro-thesis-synthetic-demo"
START = datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc)
MEANING = {"drivers": ["Real yields", "USD"], "horizon": "Several weeks",
           "invalidation_signposts": ["A sustained rise in real yields"]}


def command_id(name):
    return str(uuid5(UUID(OWNER_ID), name))


def configure():
    sys.path.insert(0, str(ROOT / "src"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "macro_agent.web.local_settings")
    if os.environ["DJANGO_SETTINGS_MODULE"] != "macro_agent.web.local_settings":
        raise ValueError("demo requires explicit local settings")
    import django
    django.setup()


def fixture_owner(*, create):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.hashers import make_password

    users = get_user_model().objects
    if create:
        owner, _ = users.get_or_create(pk=OWNER_ID, defaults={
            "username": USERNAME, "password": make_password(None),
        })
    else:
        owner = users.get(pk=OWNER_ID)
    if (owner.username != USERNAME or owner.has_usable_password() or not owner.is_active
            or owner.is_staff or owner.is_superuser):
        raise ValueError("existing account is not the restricted fixture owner")
    return owner


def approval_request(detail, name):
    draft = detail["draft"]
    return {
        "command_id": command_id(name), "expected_revision": detail["revision"],
        "thesis_version_id": draft["text_version"]["id"],
        "text_digest": draft["text_version"]["text_digest"],
        "interpretation_version_id": draft["interpretation"]["id"],
        "interpretation_digest": draft["interpretation"]["digest"],
    }


def demonstration(*, inspect_only=False):
    from django.conf import settings
    from django.db import transaction
    from macro_agent.theses import service
    from macro_agent.theses.models import CommandReceipt

    database = settings.DATABASES["default"]["NAME"]
    if not (database.endswith("_dev") or database.startswith("test_")):
        raise PermissionError("demo requires an explicitly named development or test database")
    observations = {}
    if inspect_only:
        fixture_owner(create=False)
        receipt = CommandReceipt.objects.get(owner_id=OWNER_ID, command_id=command_id("create"))
        thesis_id = str(receipt.thesis_id)
    else:
        if settings.MACRO_ALLOW_SYNTHETIC_SETUP is not True:
            raise PermissionError("write demo requires MACRO_ALLOW_SYNTHETIC_SETUP=1")
        with transaction.atomic():
            fixture_owner(create=True)
            if CommandReceipt.objects.filter(owner_id=OWNER_ID).exists():
                raise ValueError("demo records already exist; use --inspect-only")
            created = service.create_thesis(
                OWNER_ID, command_id("create"), "  Gold may benefit if real yields fall.\r\n",
                MEANING, clock=lambda: START,
            )
        thesis_id = created["thesis"]["id"]
        first_request = approval_request(created["thesis"], "approve-first")
        approved = service.approve_thesis(OWNER_ID, thesis_id, **first_request,
                                          clock=lambda: START + timedelta(seconds=1))
        proposed = service.propose_thesis(
            OWNER_ID, thesis_id, command_id("propose"),
            "  Gold may benefit if real yields fall, unless USD strength offsets it.\r\n",
            MEANING, approved["thesis"]["revision"],
            clock=lambda: START + timedelta(seconds=2),
        )
        observations["proposal_preserved_approved_text"] = (
            proposed["thesis"]["approved"] == approved["thesis"]["approved"])
        stale = {**first_request, "command_id": command_id("stale-approval")}
        try:
            service.approve_thesis(OWNER_ID, thesis_id, **stale,
                                   clock=lambda: START + timedelta(seconds=3))
        except service.ThesisConflict:
            observations["stale_approval_rejected"] = True
        else:
            raise ValueError("stale approval unexpectedly accepted")
        service.approve_thesis(
            OWNER_ID, thesis_id, **approval_request(proposed["thesis"], "approve-second"),
            clock=lambda: START + timedelta(seconds=4),
        )
        retried = service.approve_thesis(OWNER_ID, thesis_id, **first_request)
        observations["older_approval_retry"] = retried["command"]
        if (not retried["command"]["replayed"] or retried["command"]["is_current_approval"]
                or not observations["proposal_preserved_approved_text"]):
            raise ValueError("demo violated approval or retry invariants")
    return {
        "synthetic": True, "mode": "inspect_only" if inspect_only else "sequential_demonstration",
        "provider_calls": 0, "provider_spend": 0, "owner_id": OWNER_ID,
        "monitoring": "not_configured", "observations": observations,
        "time_scope": "Protected command effective times, not measured durable commit times.",
        "history": service.thesis_history(OWNER_ID, thesis_id),
    }


def readable_report(result):
    history, observations = result["history"], result["observations"]
    lines = ["# Thesis approval audit", "",
             "Fictional manual interpretation, zero provider calls or spend. Monitoring is not configured.",
             "This sequential service trace does not prove HTTP authentication or concurrency.",
             "The integration tests establish those boundaries separately.", "",
             "| Transition | Revision | Text version | New approval |", "| --- | --- | --- | --- |"]
    for item in history["audit"]:
        detail = item["detail"]
        lines.append(f"| {item['kind']} | {detail['revision']} | {detail['thesis_version_id']} | {detail['approval_id'] or 'none'} |")
    lines += ["", "Current approval: " + history["thesis"]["approved"]["approval"]["id"] + ".", ""]
    if observations:
        lines += ["The revised draft preserved the first approval. An attempted stale approval was rejected.",
                  "Retrying the first approval returned its original receipt with `is_current_approval: false`.", ""]
    else:
        lines += ["Read-only inspection of current persisted history; earlier attempted commands are not reconstructed.", ""]
    lines += ["Times record protected acceptance and manual preparation. They are not measured durable commit times.",
              "History is capped per category, with truncation visible. No source coverage, attached trades,",
              "model compilation, publication-pin integration, UI, or external delivery is exercised.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args()
    try:
        configure()
        result = demonstration(inspect_only=args.inspect_only)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(readable_report(result), encoding="utf-8")
    except Exception as error:
        # Avoid printing connection details, settings, credential values or SQL.
        parser.exit(2, "Thesis demonstration failed (" + type(error).__name__ + ").\n")


if __name__ == "__main__":
    main()
