"""Review, opt into or stop background work for one saved investigation."""

import argparse
import getpass
import sys
from uuid import uuid4

from desk_cli import (DeskClient, WalkthroughError, _id, local_url,
    new_command_journal, quoted, required)
from research_question import render_research


def render_job(result, say=print):
    job = result["job"]
    _id(job["id"])
    _id(job["run_id"])
    say("Research ID: " + job["run_id"])
    say("Owner ID for the internal worker: " + job["owner_id"])
    say("Background state: " + quoted(job["status"]))
    say("Selected model: " + quoted(job["provider"] + "/" + job["model_id"]))
    say("Next eligible work: " + quoted(job["next_due_at"]))
    say("Last background outcome: " + quoted(job["last_stop_reason"]))
    say("Background policy: " + quoted(job["policy"]))
    say("Pinned model limits: " + quoted(job["model_configuration"]))
    if job["status"] in {"pending", "running"}:
        say("Operator worker: .venv/bin/python manage.py research_run --owner " + job["owner_id"]
            + " --run-id " + job["run_id"] + " --idle-seconds 5")
    say("Research creates no monitoring, approval, position or external alert.")


def background(client, run_id, operation, *, journal=None, ask=input,
               secret=getpass.getpass, say=print):
    run_id = _id(run_id)
    if operation not in {"status", "enroll", "revoke"}:
        raise WalkthroughError("Choose status, enroll or revoke.")
    if operation != "status" and journal is None:
        raise WalkthroughError("A private journal is required before changing background work.")
    client.login(required("Username: ", ask, say), secret("Password: "))
    base = f"/api/v1/research/{run_id}/background/"
    try:
        if operation == "status":
            result = client.request("GET", base)
        else:
            command = {"command_id": str(uuid4())}
            if operation == "enroll":
                research = client.request("GET", f"/api/v1/research/{run_id}/")
                if research["research"]["id"] != run_id:
                    raise WalkthroughError("The saved research belongs to another request.")
                render_research(research, say)
                command["expected_request_digest"] = research["research"]["request_digest"]
                say("Background work reuses this plan and selected model. It can make the remaining compilation call, which may incur a charge.")
                say("Source attempts and deadlines stay fixed. Admitted uncertain model calls will not be resent.")
                if ask("Type background to enroll this saved investigation, or Enter to stop: ").strip().lower() != "background":
                    return None
            path = base if operation == "enroll" else base + "revoke/"
            journal.append("research_background_requested", {
                "run_id": run_id, "operation": operation, "request": command})
            say("Saved background command ID: " + command["command_id"])
            try:
                result = client.request("POST", path, command)
            except WalkthroughError:
                raise WalkthroughError("Background response unavailable. Use --status for read-only inspection. "
                    "No request was retried. The original command is saved in the private journal.") from None
            journal.append("research_background_response", result)
        if result["job"]["run_id"] != run_id:
            raise WalkthroughError("Background work changed its saved research identity.")
        render_job(result, say)
        return result
    finally:
        try:
            client.logout()
        except WalkthroughError:
            say("Logout could not be confirmed. No background request was retried.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=local_url, default="http://127.0.0.1:8000")
    parser.add_argument("--run-id", required=True)
    operations = parser.add_mutually_exclusive_group(required=True)
    operations.add_argument("--status", action="store_true")
    operations.add_argument("--enroll", action="store_true")
    operations.add_argument("--revoke", action="store_true")
    parser.add_argument("--journal")
    options = parser.parse_args(argv)
    journal = None
    try:
        if options.status and options.journal:
            raise WalkthroughError("Read-only status needs no journal.")
        if not options.status:
            journal = new_command_journal(options.journal)
            print("Private journal: " + str(journal.path))
        operation = "status" if options.status else "enroll" if options.enroll else "revoke"
        background(DeskClient(options.url), options.run_id, operation, journal=journal)
        return 0
    except (WalkthroughError, ValueError, TypeError, KeyError, OSError) as error:
        print(str(error) if isinstance(error, WalkthroughError) else "Invalid background input or saved response.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Stopped. Saved commands and research remain available for inspection.", file=sys.stderr)
        return 130
    finally:
        if journal:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
