"""Prepare or recover one selected source packet through the local session API."""

import argparse
import getpass
import json
import sys
from uuid import uuid4
from desk_cli import DeskClient, WalkthroughError, _id, local_url, required, new_command_journal


def review_evidence(client, thesis_id, *, revision_ids=(), command_id=None, recover=False,
                    journal=None, ask=input, secret=getpass.getpass, say=print):
    thesis_id = _id(thesis_id)
    if recover:
        command_id = _id(command_id)
    else:
        revision_ids = [_id(value) for value in revision_ids]
        if not 1 <= len(revision_ids) <= 16 or len(revision_ids) != len(set(revision_ids)):
            raise WalkthroughError("Select one to sixteen unique captured revision IDs.")
        command_id = _id(command_id) if command_id else str(uuid4())
    client.login(required("Username: ", ask, say), secret("Password: "))
    try:
        if recover:
            result = client.request("GET", f"/api/v1/theses/{thesis_id}/evidence-commands/{command_id}/")
        else:
            command = {"command_id": command_id, "revision_ids": revision_ids}
            say("Selected retained revisions: " + json.dumps(command))
            say("This freezes source claims and permission versions. It makes no model request or approval.")
            if ask("Type prepare to save this source packet, or Enter to cancel: ").strip().lower() != "prepare":
                return None
            if journal is None:
                raise WalkthroughError("A private command journal is required before saving evidence.")
            journal.append("evidence_requested", {"thesis_id": thesis_id, "request": command})
            say("Saved evidence command ID: " + command_id)
            result = client.request("POST", f"/api/v1/theses/{thesis_id}/evidence/", command)
            journal.append("evidence_response", result)
        if (_id(result["evidence"]["thesis_id"]) != thesis_id
                or _id(result["evidence"]["command_id"]) != command_id):
            raise WalkthroughError("The evidence receipt belongs to a different request.")
        from macro_agent.domain.source_evidence import validate_source_evidence
        validate_source_evidence(result["evidence"]["content"])
        say(json.dumps(result, indent=2, ensure_ascii=False))
        say("Source claims establish attribution, not independently verified truth or complete macro context.")
        return result
    finally:
        try:
            client.logout()
        except WalkthroughError:
            say("Logout could not be confirmed. No request was retried.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=local_url, default="http://127.0.0.1:8000")
    parser.add_argument("--thesis-id", required=True)
    parser.add_argument("--revision-id", action="append", default=[])
    parser.add_argument("--command-id")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--journal")
    args = parser.parse_args(argv)
    journal = None
    try:
        if args.recover and (args.revision_id or args.journal):
            raise WalkthroughError("Recovery accepts only the saved thesis and command IDs; it cannot prepare a packet.")
        if not args.recover:
            journal = new_command_journal(args.journal)
            print("Private journal: " + str(journal.path))
        review_evidence(DeskClient(args.url), args.thesis_id, revision_ids=args.revision_id,
            command_id=args.command_id, recover=args.recover, journal=journal)
        return 0
    except (WalkthroughError, ValueError, TypeError, KeyError) as error:
        print(str(error) if isinstance(error, WalkthroughError) else "Invalid evidence input or server response.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Stopped. Saved records remain available for read-only recovery.", file=sys.stderr)
        return 130
    finally:
        if journal:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
