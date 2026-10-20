"""Investigate one rough question, or recover its saved research without new calls."""

import argparse
from datetime import datetime, timezone
import getpass
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

from desk_cli import (DeskClient, WalkthroughError, _id, local_url, new_command_journal,
    quoted, render_compilation, required, select_model)


def render_research(result, say=print):
    from macro_agent.domain.research_plan import parse_plan
    from macro_agent.domain.research_compilation import parse_compilation
    run = result["research"]
    _id(run["id"])
    _id(run["command_id"])
    _id(run["thesis_id"])
    if run["authority"] != {"monitoring_started": False, "thesis_approved": False, "positions_created": False}:
        raise WalkthroughError("Unexpected authority in a research result.")
    say("Research ID: " + run["id"])
    say("Saved command ID: " + run["command_id"])
    say("Exact research question: " + quoted(run["exact_question"]))
    say("Research state: " + quoted(run["status"]))
    say("Pinned model: " + quoted(run["provider"] + "/" + run["model_id"]))
    say("Costs, unknown values stay unknown: " + quoted(run["costs"]))
    if run.get("execution_policy"):
        say("Source-only recovery policy: " + quoted(run["execution_policy"]))
        say("Source recovery deadline: " + quoted(run["source_deadline_at"]))
        if run.get("source_next_attempt_at"):
            say("Next source attempt is eligible at: " + quoted(run["source_next_attempt_at"]))
        if run.get("source_stop_reason"):
            say("Source recovery outcome: " + quoted(run["source_stop_reason"]))
        if run["status"] == "waiting_source":
            say("Progress is saved. Use --continue-run with this research ID, or --wait to follow eligible source recovery.")
    plan = run["plan"]
    if plan:
        say("Planning state: " + quoted(plan["status"]))
        say("Planning outcome: " + quoted(plan["stop_reason"]))
        if plan["document"] is not None:
            parse_plan(quoted(plan["document"]), run["exact_question"])
            say("Named questions, counter-evidence and searches: " + quoted(plan["document"]))
    for discovery in run["discoveries"]:
        say("Source discovery, including selection limits and exclusions: " + quoted(discovery))
    compiled = run["compilation"]
    if compiled is not None:
        value = compiled["compilation"]
        if value["input_text_version"]["exact_text"] != run["exact_question"]:
            raise WalkthroughError("The research result changed its original question.")
        if value["document"] is not None:
            parse_compilation(quoted(value["document"]), run["exact_question"],
                value["evidence_context"]["content"], refinement_inputs=value.get("refinement_inputs", []))
        render_compilation(value, say)
    for gap in run["gaps"]:
        say("Research limit: " + quoted(gap))
    say("Research starts no monitoring, approval or position. Any later adoption is separate.")


def follow_sources(client, result, journal, *, wait_seconds=300, say=print,
                   sleep=time.sleep, monotonic=time.monotonic,
                   now=lambda: datetime.now(timezone.utc)):
    """Follow only saved source waits; a lost HTTP response stops this client."""
    if type(wait_seconds) is not int or not 1 <= wait_seconds <= 1800:
        raise WalkthroughError("Wait budget must be between 1 and 1800 seconds.")
    if journal is None:
        raise WalkthroughError("A private journal is required before following source recovery.")
    original = result["research"]
    identity = {key: original[key] for key in ("id", "command_id", "exact_question", "provider", "model_id")}
    run_id = _id(original["id"])
    expires = monotonic() + wait_seconds
    steps = 0
    while result["research"]["status"] == "waiting_source":
        if steps >= 12 or monotonic() >= expires:
            say("Local wait budget ended. Saved research can be resumed with --continue-run " + run_id)
            break
        run = result["research"]
        if not run.get("execution_policy") or not run.get("source_next_attempt_at"):
            raise WalkthroughError("Waiting research lacks its pinned recovery policy or next due time.")
        try:
            due = datetime.fromisoformat(run["source_next_attempt_at"])
            if due.tzinfo is None or due.utcoffset() is None:
                raise ValueError
            delay = max(1.0, (due - now()).total_seconds())
        except (TypeError, ValueError, OverflowError):
            raise WalkthroughError("Invalid source recovery due time.") from None
        say("Waiting for the source. Saved planning and completed searches will be reused.")
        remaining_delay = delay
        while remaining_delay > 0 and monotonic() < expires:
            pause = min(30.0, remaining_delay, max(0, expires - monotonic()))
            if pause <= 0:
                break
            sleep(pause)
            remaining_delay -= pause
        if monotonic() >= expires:
            say("Local wait budget ended. Saved research can be resumed with --continue-run " + run_id)
            break
        journal.append("research_continuation_requested", {"run_id": run_id, "request": {}})
        try:
            result = client.request("POST", f"/api/v1/research/{run_id}/continue/", {})
        except WalkthroughError:
            raise WalkthroughError("Continuation response unavailable. Use --show-run " + run_id
                + " for read-only recovery. No request was retried; cost may be unknown.") from None
        journal.append("research_response", result)
        if any(result["research"][key] != value for key, value in identity.items()):
            raise WalkthroughError("Source recovery changed its saved research identity.")
        steps += 1
        say("Research state: " + quoted(result["research"]["status"]))
    return result


def research(client, *, exact_question=None, requested_model=None, recover_command=None,
             show_run=None, continue_run=None, journal=None, source_recovery=True,
             follow=False, wait_seconds=300,
             ask=input, secret=getpass.getpass, say=print):
    if follow and (type(wait_seconds) is not int or not 1 <= wait_seconds <= 1800):
        raise WalkthroughError("Wait budget must be between 1 and 1800 seconds.")
    if sum(item is not None for item in (recover_command, show_run, continue_run)) > 1:
        raise WalkthroughError("Choose one research operation.")
    reading = recover_command is not None or show_run is not None
    if reading and follow:
        raise WalkthroughError("Read-only recovery cannot follow or advance saved research.")
    if (reading or continue_run is not None) and (exact_question is not None or requested_model is not None):
        raise WalkthroughError("Saved research uses its exact original question and pinned model.")
    client.login(required("Username: ", ask, say), secret("Password: "))
    try:
        if recover_command is not None:
            result = client.request("GET", f"/api/v1/research-commands/{_id(recover_command)}/")
            if _id(result["research"]["command_id"]) != recover_command:
                raise WalkthroughError("The saved research command does not match.")
        elif show_run is not None or continue_run is not None:
            run_id = _id(show_run or continue_run)
            result = client.request("GET", f"/api/v1/research/{run_id}/")
            if _id(result["research"]["id"]) != run_id:
                raise WalkthroughError("The saved research belongs to another request.")
            render_research(result, say)
            if continue_run is not None:
                say("Continuation may run unadmitted nodes. An admitted uncertain model request will not be resent.")
                if ask("Type continue to advance this saved research, or Enter to stop: ").strip().lower() != "continue":
                    return result
                if journal is None:
                    raise WalkthroughError("A private journal is required before continuation.")
                journal.append("research_continuation_requested", {"run_id": run_id, "request": {}})
                result = client.request("POST", f"/api/v1/research/{run_id}/continue/", {})
                journal.append("research_response", result)
        else:
            if exact_question is None:
                exact_question = required("Your research question or rough idea: ", ask, say)
            selection = select_model(client, requested=requested_model, ask=ask, say=say)
            if selection is None:
                return None
            command = {"command_id": str(uuid4()), "exact_question": exact_question, **selection,
                       "source_recovery": source_recovery}
            say("Exact question: " + quoted(exact_question))
            say("Up to two selected-model calls and three named headline/metadata questions. A charge may apply. No monitoring is enrolled.")
            if source_recovery:
                say("Each source question permits at most three GET attempts with shared cooldown and a 30-minute source deadline. Paid model calls are not automatically repeated.")
            if ask("Type research to begin, or Enter to cancel: ").strip().lower() != "research":
                return None
            if journal is None:
                raise WalkthroughError("A private journal is required before starting research.")
            journal.append("research_requested", {"request": command})
            say("Saved research command ID: " + command["command_id"])
            try:
                result = client.request("POST", "/api/v1/research/", command)
            except WalkthroughError:
                raise WalkthroughError("Research response unavailable. Recover command " + command["command_id"]
                    + " with --recover-command. No request was retried; cost may be unknown.") from None
            journal.append("research_response", result)
            run = result["research"]
            if (run["command_id"] != command["command_id"] or run["exact_question"] != exact_question
                    or run["provider"] != selection["provider_id"] or run["model_id"] != selection["model_id"]):
                raise WalkthroughError("The research response changed its request, question or selected model.")
        if follow:
            result = follow_sources(client, result, journal, wait_seconds=wait_seconds, say=say)
        render_research(result, say)
        return result
    finally:
        try:
            client.logout()
        except WalkthroughError:
            say("Logout could not be confirmed. No research request was retried.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=local_url, default="http://127.0.0.1:8000")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--question")
    group.add_argument("--question-file", type=Path)
    group.add_argument("--recover-command")
    group.add_argument("--show-run")
    group.add_argument("--continue-run")
    parser.add_argument("--model")
    parser.add_argument("--journal")
    parser.add_argument("--one-shot-sources", action="store_true", help="Use the legacy one-shot source contract for a new run")
    parser.add_argument("--wait", action="store_true", help="Follow saved source waits within a bounded local time budget")
    parser.add_argument("--wait-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    journal = None
    try:
        exact = args.question
        if args.question_file:
            with args.question_file.open(encoding="utf-8", newline="") as stream:
                exact = stream.read()
        if args.recover_command or args.show_run:
            if args.model or args.journal or args.wait or args.one_shot_sources:
                raise WalkthroughError("Read-only recovery accepts saved IDs only.")
        elif args.continue_run and args.one_shot_sources:
            raise WalkthroughError("Continuation preserves the saved source policy.")
        else:
            journal = new_command_journal(args.journal)
            print("Private journal: " + str(journal.path))
        research(DeskClient(args.url, timeout=180), exact_question=exact, requested_model=args.model,
            recover_command=args.recover_command, show_run=args.show_run,
            continue_run=args.continue_run, journal=journal, source_recovery=not args.one_shot_sources,
            follow=args.wait, wait_seconds=args.wait_seconds)
        return 0
    except (WalkthroughError, ValueError, TypeError, KeyError, OSError) as error:
        print(str(error) if isinstance(error, WalkthroughError) else "Invalid research input or saved response.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Stopped. Saved command IDs remain available for read-only recovery.", file=sys.stderr)
        return 130
    finally:
        if journal:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
