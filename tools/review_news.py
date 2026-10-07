"""Explicitly initiate one automatically selected retained-report analysis.

Uses the existing authenticated HTTP API. This review cannot change approved
meaning, paper declarations, notification intent or unresolved screening work.
"""

import argparse
import getpass
import json
from pathlib import Path
import sys
from uuid import uuid4

from desk_cli import (
    DeskClient, WalkthroughError, _id, local_url, quoted, required, select_model,
)
from evaluate_compilation import ReviewJournal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from macro_agent.domain.news_analysis import validate_news_document


STATUSES = {"analysed", "stale", "failed", "outcome_unknown", "running", "queue_empty"}
REVIEW_QUESTIONS = (
    ("attribution", "Do the quoted source passages support the attributed report claims?"),
    ("independent_routes", "Are thesis relevance and open-trade relevance considered separately?"),
    ("uncertainty", "Are assumptions, competing explanations and missing context visible?"),
    ("usefulness", "Does this explain a useful possible consequence for your view or attached trades?"),
)


def select_source(client, *, requested=None, ask=input, say=print):
    catalog = client.request("GET", "/api/v1/news/sources/")
    sources = catalog["sources"]
    if type(sources) is not list or not sources:
        raise WalkthroughError("No retained source is available. Capture an allowed source first.")
    identities = [source["id"] for source in sources]
    if any(type(identity) is not str or not identity for identity in identities) or len(set(identities)) != len(identities):
        raise WalkthroughError("The source catalogue is invalid. No analysis was requested.")
    for index, source in enumerate(sources, 1):
        say(f"{index}. {quoted(source['id'])}: {quoted(source['label'])}; "
            f"kind {quoted(source['kind'])}; current retained reports {quoted(source['current_reports'])}")
    for limitation in catalog["limitations"]:
        say("Source limitation: " + quoted(limitation))
    if requested is not None:
        if requested not in identities:
            raise WalkthroughError("The requested source is not in the retained-source catalogue.")
        return requested
    while True:
        choice = ask("Choose a source number or ID, or Enter to cancel: ").strip()
        if not choice:
            return None
        if choice in identities:
            return choice
        if choice.isascii() and choice.isdecimal() and 1 <= int(choice) <= len(sources):
            return identities[int(choice) - 1]
        say("Choose a displayed source. The backend selects its next unattempted report automatically.")


def render_context(context, say):
    say("Exact approved thesis, quoted to preserve whitespace:")
    say(quoted(context["approved_exact_text"]))
    say("Approved interpretation: " + quoted(context["approved_interpretation"]))
    say("Current approval: " + quoted(context["approval_id"]))
    say("Attached paper book digest: " + quoted(context["exposure_digest"]))
    say("Complete attached-thesis paper book, including closed declarations:")
    for position in context["positions"]:
        say(quoted(position))
    if not context["positions"]:
        say("No attached declarations.")
    for limitation in context["limitations"]:
        say("Context limitation: " + quoted(limitation))


def _available_result(result, preview, selection, source_id):
    analysis = result["analysis"]
    if (analysis["provider"] != selection["provider_id"] or analysis["model_id"] != selection["model_id"]
            or analysis["status"] not in STATUSES):
        raise WalkthroughError("The analysis does not match the selected provider/model or has an unknown state. No retry was made.")
    if analysis["status"] == "queue_empty":
        if (analysis["id"] is not None or analysis["context"] is not None or analysis["document"] is not None
                or analysis["current_disposition"] != "queue_empty"):
            raise WalkthroughError("The empty-queue response includes unexpected analysis. No retry was made.")
        return "queue_empty"
    _id(analysis["id"])
    context = analysis["context"]
    approved = context["approved_thesis"]
    expected = {"thesis_id": preview["thesis_id"], "approval_id": preview["approval_id"],
        "exact_text": preview["approved_exact_text"], **preview["approved_interpretation"]}
    if (any(approved.get(key) != value for key, value in expected.items())
            or context["positions"] != preview["positions"]
            or context["source"]["source_key"] != source_id
            or context["source"]["revision_id"] != analysis["source_revision_id"]):
        raise WalkthroughError("The retained context differs from the reviewed approval, paper book or report identity. No review was accepted.")
    if analysis["document"] is not None:
        validate_news_document(json.dumps(analysis["document"], ensure_ascii=False, allow_nan=False), context)
    if analysis["status"] == "analysed" and analysis["current_disposition"] == "current":
        if analysis["document"] is None:
            raise WalkthroughError("The completed analysis has no reviewable document.")
        return "analysed"
    return "stale" if analysis["current_disposition"] == "stale" else analysis["status"]


def render_analysis(analysis, say):
    say("Analysis outcome: " + quoted(analysis["status"]))
    say("Current dependency disposition: " + quoted(analysis["current_disposition"]))
    say("Attempt ID: " + quoted(analysis["id"]))
    say("Prior unresolved attempts: " + quoted(analysis["unresolved_attempt_count"]))
    say("Token usage: " + quoted(analysis["usage"]))
    for field, label in (("reported_cost_usd", "Provider-reported cost USD"),
                         ("estimated_cost_usd", "Estimated cost USD")):
        value = analysis[field]
        say(label + ": " + (quoted(value) if value is not None else "unknown"))
    for reason in analysis["stale_reasons"]:
        say("Stale dependency: " + quoted(reason))
    for limitation in analysis["limitations"]:
        say("Analysis limitation: " + quoted(limitation))
    context = analysis["context"]
    if context is not None:
        say("Retained source snapshot: " + quoted(context["source"]))
    document = analysis["document"]
    if document is None:
        return
    say("Attributed report claims, exact quotations establish attribution only:")
    for fact in document["attributed_facts"]:
        say(quoted(fact))
    say("Thesis relevance, model hypothesis: " + quoted(document["thesis_route"]))
    say("Open-trade relevance, independent model hypothesis: " + quoted(document["trade_route"]))
    say("Possible consequences, assumptions, counter-cases and signposts:")
    for hypothesis in document["hypotheses"]:
        say(quoted(hypothesis))
    for question in document["trader_questions"]:
        say("Trader question: " + quoted(question))
    say("A scoped not_identified result leaves monitoring unresolved. This review does not publish an alert.")


def _available_recovery_result(result, thesis_id):
    """Historical context is checked against its retained report, not new intent."""
    analysis = result["analysis"]
    if (analysis["status"] not in STATUSES
            or analysis["current_disposition"] not in {"current", "stale", "unresolved", "queue_empty"}
            or analysis["provider"] not in {"nanogpt", "openrouter", "cheaperinference"}
            or type(analysis["model_id"]) is not str or not analysis["model_id"]):
        raise WalkthroughError("The saved command receipt has an invalid analysis disposition. No retry was made.")
    if analysis["status"] == "queue_empty":
        if (analysis["id"] is not None or analysis["context"] is not None or analysis["document"] is not None
                or analysis["current_disposition"] != "queue_empty"):
            raise WalkthroughError("The saved empty-queue receipt includes unexpected analysis. No retry was made.")
        return
    _id(analysis["id"])
    context = analysis["context"]
    if (context["approved_thesis"]["thesis_id"] != thesis_id
            or context["source"]["revision_id"] != analysis["source_revision_id"]):
        raise WalkthroughError("The saved command receipt belongs to another thesis or report. No retry was made.")
    if analysis["document"] is not None:
        validate_news_document(json.dumps(analysis["document"], ensure_ascii=False, allow_nan=False), context)
    elif analysis["status"] == "analysed":
        raise WalkthroughError("The saved completed analysis has no document. No retry was made.")


def recover_one(client, thesis_id, command_id, journal, *, ask=input,
                secret=getpass.getpass, say=print):
    thesis_id, command_id = _id(thesis_id), _id(command_id)
    username = required("Username: ", ask, say)
    password = secret("Password: ")
    client.login(username, password)
    del password
    try:
        path = f"/api/v1/theses/{thesis_id}/news-commands/{command_id}/"
        journal.append("recovery_requested", {"thesis_id": thesis_id, "command_id": command_id,
            "path": path, "method": "GET", "provider_calls": 0})
        try:
            result = client.request("GET", path)
        except WalkthroughError as error:
            journal.append("recovery_unavailable", {"command_id": command_id,
                "receipt": "unavailable_to_client", "provider_calls": 0, "automatic_retries": 0})
            raise WalkthroughError("Saved command receipt unavailable: " + quoted(str(error))
                + ". No model request or POST fallback was made. An absent receipt does not establish "
                "whether an earlier request incurred a charge.") from None
        journal.append("recovery_response", result)
        _available_recovery_result(result, thesis_id)
        render_analysis(result["analysis"], say)
        say("Saved command inspected. Its retained context is historical; current dependency disposition is shown separately. No model request was made.")
        return result
    finally:
        client.logout()


def review_one(client, thesis_id, journal, *, requested_source=None, requested_model=None,
               ask=input, secret=getpass.getpass, say=print):
    thesis_id = _id(thesis_id)
    username = required("Username: ", ask, say)
    password = secret("Password: ")
    client.login(username, password)
    del password
    try:
        preview = client.request("GET", f"/api/v1/theses/{thesis_id}/news-context/")
        if _id(preview["thesis_id"]) != thesis_id:
            raise WalkthroughError("The context response belongs to another thesis. No analysis was requested.")
        _id(preview["approval_id"])
        journal.append("context_preview", preview)
        render_context(preview, say)
        source_id = select_source(client, requested=requested_source, ask=ask, say=say)
        if source_id is None:
            journal.append("cancelled", {"reason": "no_source_selected"})
            return None
        selection = select_model(client, requested=requested_model, ask=ask, say=say)
        if selection is None:
            journal.append("cancelled", {"reason": "no_model_selected"})
            return None
        say("The backend will select one unattempted retained report automatically. The model will receive that report, your approved thesis and attached paper book. The request may incur a charge; no dollar cap is guaranteed.")
        if ask("Type run to initiate one analysis request, or Enter to cancel: ").strip().lower() != "run":
            journal.append("cancelled", {"reason": "not_initiated"})
            return None
        command = {"command_id": str(uuid4()), "expected_approval_id": preview["approval_id"],
            "expected_exposure_digest": preview["exposure_digest"], "source_id": source_id, **selection}
        path = f"/api/v1/theses/{thesis_id}/analyse-next/"
        journal.append("analysis_requested", {"thesis_id": thesis_id, "path": path, "request": command})
        try:
            result = client.request("POST", path, command)
        except WalkthroughError as error:
            journal.append("response_unavailable", {"command_id": command["command_id"],
                "outcome": "unknown_to_client", "cost": "unknown", "automatic_retries": 0})
            raise WalkthroughError("Analysis request stopped: " + quoted(str(error))
                + ". The request identity is saved in your journal; its outcome and cost may be unknown. "
                "Inspect backend history before another request. No retry was made.") from None
        journal.append("analysis_response", result)
        state = _available_result(result, preview, selection, source_id)
        render_analysis(result["analysis"], say)
        if state != "analysed":
            outcome = {"status": "not_reviewable", "attempt_status": state, "ratings": None}
            journal.append("review", outcome)
            if state == "queue_empty":
                say("No unattempted report is available for these inputs. Prior unresolved attempts and source coverage gaps remain unresolved.")
            else:
                say("This result is unresolved or stale. No quality grade or automatic retry was made.")
            return outcome
        if ask("Type review to record your assessment, or Enter to finish: ").strip().lower() != "review":
            outcome = {"status": "not_reviewed", "attempt_status": state, "ratings": None}
            journal.append("review", outcome)
            return outcome
        ratings = {}
        for key, question in REVIEW_QUESTIONS:
            say(quoted(question))
            while True:
                value = ask("Review (good/poor/uncertain): ").strip().lower()
                if value in {"good", "poor", "uncertain"}:
                    break
                say("Choose good, poor or uncertain. These are your judgments.")
            ratings[key] = value
            journal.append("review_dimension", {"id": key, "rating": value})
        outcome = {"status": "reviewed", "attempt_status": state, "ratings": ratings,
                   "notes": ask("Optional review notes: ")}
        journal.append("review", outcome)
        return outcome
    finally:
        client.logout()


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--thesis-id", required=True, help="Existing approved thesis UUID")
    result.add_argument("--source", help="Retained source ID; otherwise select interactively")
    result.add_argument("--model", help="Explicit model ID from the fetched catalogue")
    result.add_argument("--url", type=local_url, default="http://127.0.0.1:8000")
    result.add_argument("--output", type=Path, help="New private JSONL journal; defaults to ignored .local/")
    result.add_argument("--recover-command", help="Read a saved command UUID without another model request")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    journal = None
    try:
        thesis_id = _id(args.thesis_id)
        command_id = _id(args.recover_command) if args.recover_command else None
        if command_id is not None and (args.source is not None or args.model is not None):
            raise WalkthroughError("Recovery reads the saved command only; omit --source and --model.")
        path = args.output
        if path is None:
            (ROOT / ".local").mkdir(mode=0o700, exist_ok=True)
            path = ROOT / ".local" / ("news-review-" + uuid4().hex + ".jsonl")
        journal = ReviewJournal(path)
        journal.append("protocol", {"schema_version": "retained-news-review-v1",
            "maximum_analysis_requests": 0 if command_id else 1, "automatic_retries": 0,
            "automatic_approvals": 0, "automatic_alerts": 0, "automatic_learning": False})
        print("Private review journal: " + quoted(str(path)))
        if command_id is not None:
            recover_one(DeskClient(args.url), thesis_id, command_id, journal)
        else:
            review_one(DeskClient(args.url, timeout=90), thesis_id, journal,
                       requested_source=args.source, requested_model=args.model)
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nStopped. Completed journal steps remain saved; no automatic retry was made.", file=sys.stderr)
        return 130
    except (WalkthroughError, ValueError, TypeError, KeyError, OSError) as error:
        message = str(error) if isinstance(error, WalkthroughError) else "The input or response could not be validated. No automatic retry was made."
        print("Review stopped: " + message, file=sys.stderr)
        return 1
    finally:
        if journal is not None:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
