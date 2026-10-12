"""Request or recover one fresh morning interpretation through the session API."""

import argparse
import getpass
import json
import sys
from uuid import uuid4

from desk_cli import (
    DeskClient, WalkthroughError, _id, local_url, new_command_journal,
    required, select_model,
)


def render_synthesis(result, say=print):
    from macro_agent.domain.daily_synthesis import build_synthesis_prompt, validate_synthesis_document
    from macro_agent.domain.models import canonical_json, text_digest
    saved = result["synthesis"]
    context = saved["context"]
    build_synthesis_prompt(context)
    if (saved["context_digest"] != text_digest(canonical_json(context))
            or saved["review_id"] != context["review_id"]
            or saved["review_digest"] != context["review_digest"]):
        raise WalkthroughError("The saved synthesis and exact review context disagree.")
    document = saved["document"]
    if document is not None:
        validate_synthesis_document(canonical_json(document), context)
    say("Saved morning synthesis: " + saved["id"])
    say("Original outcome: " + saved["status"])
    say("Present disposition: " + json.dumps(result["current_disposition"], ensure_ascii=False))
    say("Model: " + saved["provider"] + "/" + saved["model_id"])
    for field in ("reported_cost_usd", "estimated_cost_usd"):
        say(field + ": " + (str(saved.get(field)) if saved.get(field) is not None else "unknown"))
    if document is None:
        say("No usable model document was retained. The original digest remains independently available.")
    else:
        for field, label in (("attributed_claims", "Exact source quotations"),
                             ("overview", "Fresh overview, model interpretation"),
                             ("thesis_effect", "Effect on the approved thesis"),
                             ("trade_effects", "Effects on the complete open paper book"),
                             ("counter_case", "Counter-case"),
                             ("watch_questions", "Questions to watch"), ("gaps", "Gaps")):
            say(label + ": " + json.dumps(document[field], ensure_ascii=False, indent=2))
    say("Retained digest: " + saved["review_id"] + ", digest " + saved["review_digest"])
    say("This is unverified model interpretation. It does not edit your thesis or create a publication or notification.")


def review_morning(client, review_id, *, command_id=None, recover=False, requested_model=None,
                   journal=None, ask=input, secret=getpass.getpass, say=print):
    review_id = _id(review_id)
    command_id = _id(command_id) if command_id else (None if recover else str(uuid4()))
    if recover and command_id is None:
        raise WalkthroughError("Recovery requires the saved review and command IDs.")
    client.login(required("Username: ", ask, say), secret("Password: "))
    try:
        if recover:
            result = client.request("GET", f"/api/v1/daily-reviews/{review_id}/synthesis-commands/{command_id}/")
        else:
            review = client.request("GET", f"/api/v1/daily-reviews/{review_id}/")
            if _id(review["review"]["id"]) != review_id:
                raise WalkthroughError("The server returned a different retained review.")
            say("Exact retained daily review: " + json.dumps(review, ensure_ascii=False, indent=2))
            if review["current_disposition"]["status"] != "prepared":
                raise WalkthroughError("This review is stale. Prepare a later review before requesting fresh synthesis.")
            selection = select_model(client, requested=requested_model, ask=ask, say=say)
            if selection is None:
                return None
            command = {"command_id": command_id, "expected_review_digest": review["review"]["digest"],
                       "provider_id": selection["provider_id"], "model_id": selection["model_id"]}
            say("This sends the exact review, approved thesis and complete paper book to the selected provider. A charge may apply.")
            if ask("Type synthesise to make one fresh model request, or Enter to cancel: ").strip().lower() != "synthesise":
                return None
            if journal is None:
                raise WalkthroughError("A private command journal is required before requesting synthesis.")
            journal.append("synthesis_requested", {"review_id": review_id, "request": command})
            say("Saved synthesis command ID: " + command_id)
            try:
                result = client.request("POST", f"/api/v1/daily-reviews/{review_id}/synthesise/", command)
            except WalkthroughError:
                journal.append("synthesis_response_unavailable", {"review_id": review_id,
                               "command_id": command_id, "automatic_retries": 0})
                raise WalkthroughError("The model response was not received. Recover review " + review_id
                    + " and command " + command_id + " with --recover. No retry was made; cost is unknown.") from None
            journal.append("synthesis_response", result)
            if (result["synthesis"]["provider"] != selection["provider_id"]
                    or result["synthesis"]["model_id"] != selection["model_id"]
                    or result["synthesis"]["review_digest"] != command["expected_review_digest"]):
                raise WalkthroughError("The synthesis receipt changed the selected provider, model or exact review.")
        if (_id(result["synthesis"]["command_id"]) != command_id
                or _id(result["synthesis"]["review_id"]) != review_id):
            raise WalkthroughError("The synthesis receipt belongs to a different request.")
        render_synthesis(result, say)
        return result
    finally:
        try:
            client.logout()
        except WalkthroughError:
            say("Logout could not be confirmed. No model request was retried.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=local_url, default="http://127.0.0.1:8000")
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--command-id")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--journal")
    args = parser.parse_args(argv)
    journal = None
    try:
        if args.recover and (args.model or args.journal):
            raise WalkthroughError("Recovery accepts saved IDs only; it cannot select a model or send a new request.")
        if not args.recover:
            journal = new_command_journal(args.journal)
            print("Private journal: " + str(journal.path))
        review_morning(DeskClient(args.url), args.review_id, command_id=args.command_id,
            recover=args.recover, requested_model=args.model, journal=journal)
        return 0
    except (WalkthroughError, ValueError, TypeError, KeyError) as error:
        print(str(error) if isinstance(error, WalkthroughError) else "Invalid synthesis input or server response.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Stopped. Saved commands remain available for read-only recovery.", file=sys.stderr)
        return 130
    finally:
        if journal:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
