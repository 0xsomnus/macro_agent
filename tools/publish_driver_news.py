"""Publish or inspect a qualified internal driver brief, with no external send."""

import argparse
import getpass
import sys
from urllib.parse import urlencode
from uuid import uuid4

from desk_cli import DeskClient, WalkthroughError, _id, local_url, new_command_journal, quoted, required
from review_news import render_analysis

POLICY = "evidence-linked-driver-review-v1"


def render_publication(result, say=print):
    value = result["publication"]
    _id(value["id"])
    _id(value["command_id"])
    if value["analysis_id"] != result["analysis"]["id"]:
        raise WalkthroughError("The publication and retained analysis disagree.")
    say("Publication ID: " + value["id"])
    say("Original publication decision: " + quoted(value["original_decision"]))
    say("Present disposition: " + quoted(result["current_disposition"]))
    say("Qualified-review decision: " + quoted(value["attention_decision"]))
    say("Internal notification intent: " + quoted(result["notification_intent"]))
    say("Original analytical review, separate from the publication decision above:")
    render_analysis(result["analysis"], say)
    say("An internal intent is not a delivered alert. No external delivery or thesis amendment occurs.")


def publish(client, *, analysis_id=None, fanout_limit=None, thesis_id=None,
            recover_command=None, current=False, journal=None,
            ask=input, secret=getpass.getpass, say=print):
    if recover_command is not None or current:
        thesis_id = _id(thesis_id)
        if analysis_id is not None or fanout_limit is not None:
            raise WalkthroughError("Inspection accepts saved thesis/command IDs only.")
    else:
        analysis_id = _id(analysis_id)
        if type(fanout_limit) is not int or not 1 <= fanout_limit <= 1000:
            raise WalkthroughError("An explicit fanout limit from 1 to 1000 is required.")
    client.login(required("Username: ", ask, say), secret("Password: "))
    try:
        if recover_command is not None:
            command_id = _id(recover_command)
            result = client.request("GET", f"/api/v1/theses/{thesis_id}/news-publication-commands/{command_id}/")
            if result["publication"]["command_id"] != command_id or result["analysis"]["context"]["approved_thesis"]["thesis_id"] != thesis_id:
                raise WalkthroughError("The saved publication belongs to another request.")
        elif current:
            result = client.request("GET", f"/api/v1/theses/{thesis_id}/news-brief/")
            if result["thesis_id"] != thesis_id:
                raise WalkthroughError("The current driver brief belongs to another thesis.")
            if result["current_publication"] is None:
                say("No current driver brief. Historical output is not substituted.")
                return result
            render_publication(result["current_publication"], say)
            return result
        else:
            query = urlencode({"fanout_limit": fanout_limit, "policy_version": POLICY})
            preview = client.request("GET", f"/api/v1/news-analyses/{analysis_id}/publication-preview/?{query}")
            if preview["analysis_id"] != analysis_id or preview["policy_version"] != POLICY or preview["fanout_limit"] != fanout_limit:
                raise WalkthroughError("The preview changed the requested analysis or policy.")
            say("Exact publication preview: " + quoted(preview))
            say("Policy requests qualified internal review for a first or changed typed approved-driver assessment with linked evidence; duplicates and unchanged assessments are suppressed.")
            if ask("Type publish to save this internal brief and policy decision, or Enter to cancel: ").strip().lower() != "publish":
                return None
            if journal is None:
                raise WalkthroughError("A private command journal is required before publication.")
            command = {"command_id": str(uuid4()), "expected_analysis_digest": preview["analysis_digest"],
                "expected_generation": preview["expected_generation"], "fanout_limit": fanout_limit, "policy_version": POLICY}
            journal.append("news_publication_requested", {"analysis_id": analysis_id,
                "thesis_id": preview["thesis_id"], "request": command})
            say("Saved publication command ID: " + command["command_id"])
            result = client.request("POST", f"/api/v1/news-analyses/{analysis_id}/publish/", command)
            journal.append("news_publication_response", result)
            if (result["publication"]["command_id"] != command["command_id"]
                    or result["publication"]["analysis_id"] != analysis_id
                    or result["publication"]["analysis_digest"] != command["expected_analysis_digest"]):
                raise WalkthroughError("The publication receipt changed its exact requested analysis.")
        render_publication(result, say)
        return result
    finally:
        try:
            client.logout()
        except WalkthroughError:
            say("Logout could not be confirmed. No publication was retried.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=local_url, default="http://127.0.0.1:8000")
    parser.add_argument("--analysis-id")
    parser.add_argument("--fanout-limit", type=int)
    parser.add_argument("--thesis-id")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--recover-command")
    group.add_argument("--current", action="store_true")
    parser.add_argument("--journal")
    args = parser.parse_args(argv)
    journal = None
    try:
        if args.recover_command or args.current:
            if args.journal:
                raise WalkthroughError("Inspection does not create a publication journal.")
        else:
            journal = new_command_journal(args.journal)
            print("Private journal: " + str(journal.path))
        publish(DeskClient(args.url), analysis_id=args.analysis_id, fanout_limit=args.fanout_limit,
            thesis_id=args.thesis_id, recover_command=args.recover_command,
            current=args.current, journal=journal)
        return 0
    except (WalkthroughError, ValueError, TypeError, KeyError, OSError) as error:
        print(str(error) if isinstance(error, WalkthroughError) else "Invalid driver publication input or response.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Stopped. Saved publication commands remain available for read-only recovery.", file=sys.stderr)
        return 130
    finally:
        if journal:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
