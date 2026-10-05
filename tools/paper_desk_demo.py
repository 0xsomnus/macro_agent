"""Sequential synthetic desk trace with real approved thesis and paper records.

No provider, model or external delivery is used. Source and macro inputs remain
fictional. Independent PostgreSQL tests establish concurrent ordering.
"""

import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from uuid import UUID, uuid5


ROOT = Path(__file__).resolve().parents[1]
OWNER_ID = "3d5d64e2-90b6-43af-a25e-158c0f773b85"
USERNAME = "macro-paper-desk-synthetic-demo-v1"
BRIEF_ID = "paper-desk-synthetic-brief-v1"
START = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
MEANING = {"drivers": ["Real yields", "USD"], "horizon": "Several weeks",
           "invalidation_signposts": ["A sustained rise in real yields"]}


def command_id(name):
    return str(uuid5(UUID(OWNER_ID), name))


def clock(seconds):
    return lambda: START + timedelta(seconds=seconds)


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


def approval_request(thesis, name):
    draft = thesis["draft"]
    return {"command_id": command_id(name), "expected_revision": thesis["revision"],
            "thesis_version_id": draft["text_version"]["id"],
            "text_digest": draft["text_version"]["text_digest"],
            "interpretation_version_id": draft["interpretation"]["id"],
            "interpretation_digest": draft["interpretation"]["digest"]}


def stage_snapshot(state):
    """Keep intermediate currentness; complete immutable history is saved once."""
    return {key: state[key] for key in (
        "brief_id", "generation", "changed_at", "current_assessment_id",
        "thesis_binding", "current_dependencies", "notifications",
    )}


def demonstration(*, inspect_only=False):
    from django.conf import settings
    from domain_fixture import fixture_case
    from macro_agent.application.publication import publish
    from macro_agent.domain.exposure import DECLARATION_FIELDS
    from macro_agent.domain.models import ContextSnapshot
    from macro_agent.persistence.context_binding import (
        CONTEXT_ROLES, ContextPending, enroll_synthetic, refresh_context,
    )
    from macro_agent.persistence.models import BriefStateRecord
    from macro_agent.persistence.publication_store import DjangoPublicationStore
    from macro_agent.positions import service as positions
    from macro_agent.positions.models import CommandReceipt as PositionReceipt
    from macro_agent.theses import service as theses
    from macro_agent.theses.models import CommandReceipt as ThesisReceipt

    database = settings.DATABASES["default"]["NAME"]
    if not (database.endswith("_dev") or database.startswith("test_")):
        raise PermissionError("demo requires a development or test database")
    observations, stages = {}, []
    if inspect_only:
        fixture_owner(create=False)
        thesis_id = str(ThesisReceipt.objects.get(owner_id=OWNER_ID,
                        command_id=command_id("create-thesis")).thesis_id)
        position_id = str(PositionReceipt.objects.get(owner_id=OWNER_ID,
                          command_id=command_id("create-position")).position_id)
    else:
        if settings.MACRO_ALLOW_SYNTHETIC_SETUP is not True:
            raise PermissionError("write demo requires MACRO_ALLOW_SYNTHETIC_SETUP=1")
        if (ThesisReceipt.objects.filter(owner_id=OWNER_ID).exists()
                or BriefStateRecord.objects.filter(pk=BRIEF_ID).exists()):
            raise ValueError("demo records already exist; use --inspect-only")
        fixture_owner(create=True)
        created = theses.create_thesis(OWNER_ID, command_id("create-thesis"),
            "  Gold may benefit if real yields fall.\r\n", MEANING, clock=clock(0))
        thesis_id = created["thesis"]["id"]
        first_request = approval_request(created["thesis"], "approve-first")
        approved = theses.approve_thesis(OWNER_ID, thesis_id, **first_request, clock=clock(1))
        approval_id = approved["command"]["result"]["approval_id"]
        declaration = {field: None for field in DECLARATION_FIELDS}
        declaration.update(underlying="XAU", direction="long", quantity="1.00",
                           quantity_unit="declared units", horizon="Several weeks")
        attached = positions.create_position(OWNER_ID, thesis_id, command_id("create-position"),
                                              approval_id, declaration, clock=clock(2))["position"]
        position_id = attached["id"]
        base, dependencies = fixture_case(owner_id=OWNER_ID)
        enroll_synthetic(OWNER_ID, thesis_id, BRIEF_ID, approval_id,
            tuple(pin for pin in dependencies if pin.role not in CONTEXT_ROLES),
            synthetic=True, clock=clock(3))
        store = DjangoPublicationStore(OWNER_ID)

        def candidate(name, seconds):
            with store.transaction(BRIEF_ID) as tx:
                state = tx.state()
            return replace(base, assessment_id=name, run_id="run:" + name, brief_id=BRIEF_ID,
                expected_generation=state.generation,
                snapshot=ContextSnapshot("snapshot:" + name, clock(seconds)(), state.dependencies))

        def publish_current(name, seconds):
            value = candidate(name, seconds)
            decision = publish(store, value, clock(seconds))
            if decision.status != "current":
                raise ValueError("current synthetic notice was not published")
            stages.append({"stage": name, "state": stage_snapshot(store.inspect(BRIEF_ID))})
            return value

        def pending(stage, old, seconds):
            state = store.inspect(BRIEF_ID)
            if (state["thesis_binding"]["status"] != "pending"
                    or state["current_assessment_id"] is not None
                    or any(item["state"] == "pending" for item in state["notifications"])):
                raise ValueError("obsolete brief or notification remained current")
            try:
                publish(store, old, clock(seconds))
            except ContextPending:
                observations[stage + "_publication_blocked"] = True
            else:
                raise ValueError("pending context allowed publication")
            stages.append({"stage": stage, "state": stage_snapshot(state)})

        first = publish_current("paper-desk-initial", 4)
        revised = positions.revise_position(OWNER_ID, position_id, command_id("revise-position"),
            attached["revision"], approval_id, {**declaration, "quantity": "2.00"}, clock=clock(5))["position"]
        pending("position_changed", first, 6)
        refresh_context(OWNER_ID, thesis_id, approval_id, clock=clock(7))
        old_disposition = publish(store, first, clock(8))
        observations["old_assessment_retry_status"] = old_disposition.status
        if old_disposition.status != "superseded":
            raise ValueError("old assessment retry appeared current")
        second = publish_current("paper-desk-resized", 9)
        proposal = theses.propose_thesis(OWNER_ID, thesis_id, command_id("propose"),
            "  Gold may benefit if real yields fall, unless USD strength offsets it.\r\n",
            MEANING, approved["thesis"]["revision"], clock=clock(10))
        observations["proposal_preserved_current_brief"] = (
            store.inspect(BRIEF_ID)["current_assessment_id"] == second.assessment_id)
        updated = theses.approve_thesis(OWNER_ID, thesis_id,
            **approval_request(proposal["thesis"], "approve-second"), clock=clock(11))
        approval_id = updated["command"]["result"]["approval_id"]
        pending("approval_changed", second, 12)
        old_retry = theses.approve_thesis(OWNER_ID, thesis_id, **first_request)
        observations["old_approval_retry_is_current"] = old_retry["command"]["is_current_approval"]
        refresh_context(OWNER_ID, thesis_id, approval_id, clock=clock(13))
        third = publish_current("paper-desk-amended", 14)
        positions.close_position(OWNER_ID, position_id, command_id("close-position"),
            revised["revision"], approval_id, clock=clock(15))
        pending("position_closed", third, 16)
        refresh_context(OWNER_ID, thesis_id, approval_id, clock=clock(17))
        publish_current("paper-desk-closed-history", 18)
        if (not observations["proposal_preserved_current_brief"]
                or observations["old_approval_retry_is_current"]):
            raise ValueError("proposal or old retry changed approved authority")
    store = DjangoPublicationStore(OWNER_ID)
    return {"synthetic": True, "mode": "inspect_only" if inspect_only else "sequential_demonstration",
        "provider_calls": 0, "provider_spend": 0, "owner_id": OWNER_ID,
        "monitoring": "not_configured", "observations": observations, "stages": stages,
        "time_scope": "Committed inputs observed under protection; exact admission commit time is not measured.",
        "thesis_history": theses.thesis_history(OWNER_ID, thesis_id),
        "position_history": positions.position_history(OWNER_ID, position_id),
        "current_brief": store.inspect(BRIEF_ID)}


def readable_report(result):
    brief = result["current_brief"]
    lines = ["# Paper desk audit", "", "Real persisted manual approvals and paper declarations with fictional news inputs.",
        "Zero model/provider calls or spend. Monitoring and external delivery are not configured.",
        "This sequential trace illustrates state changes; independent PostgreSQL tests prove concurrency.", "",
        "| Recorded stage | Binding | Current assessment | Pending notices |", "| --- | --- | --- | --- |"]
    for item in result["stages"]:
        state = item["state"]
        count = sum(notice["state"] == "pending" for notice in state["notifications"])
        lines.append(f"| {item['stage']} | {state['thesis_binding']['status']} | {state['current_assessment_id'] or 'none'} | {count} |")
    if not result["stages"]:
        lines += ["", "Read-only current inspection; earlier intermediate states are not reconstructed."]
    lines += ["", "The approved thesis text and interpretation remain separate from source facts and agent assessments.",
        "A draft proposal preserves the approval. Position changes, closure and explicit thesis approval clear",
        "obsolete current briefs and cancel pending notices atomically. Fresh committed inputs must be admitted",
        "before publication resumes. Historical retries cannot restore an obsolete approval or assessment.", "",
        "| Paper transition | Revision | Quantity | Status |", "| --- | --- | --- | --- |"]
    for audit, version in zip(result["position_history"]["audit"], result["position_history"]["versions"], strict=True):
        lines.append(f"| {audit['kind']} | {audit['detail']['revision']} | {version['quantity']} | {version['status']} |")
    lines += ["", "Current brief: " + brief["current_assessment_id"] + ".",
        "Input admissions: " + str(len(brief["context_admissions"])) + ".", "",
        "Input-observed timestamps conservatively witness already committed user context. Approval/preparation",
        "times and admission effective times do not measure exact durable admission commit time.",
        "The twelve source/macro/runtime roles remain synthetic. Instrument mapping is user-declared and unverified;",
        "missing venue, product and quote currency remain explicit. Quantity is not exposure arithmetic or P&L.",
        "Closed positions remain in history. Portfolio consequences remain unresolved; this is a factual-notice",
        "mechanics trace, not continuous coverage, investment analysis or a complete operational replay.", ""]
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
        parser.exit(2, "Paper desk demonstration failed (" + type(error).__name__ + ").\n")


if __name__ == "__main__":
    main()
