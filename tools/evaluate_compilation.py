"""Review one text-grounded compilation against a literal baseline.

Uses the existing session/CSRF API. No automatic approval, model retry, batch,
paper position, news call or outcome learning is performed.
"""

import argparse
import getpass
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import uuid4

from desk_cli import (
    DeskClient, WalkthroughError, _id, local_url, quoted, read_thesis,
    render_compilation, render_draft, required, select_model,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from macro_agent.domain.compilation import parse_compilation
from macro_agent.domain.compilation_evaluation import (
    QUALITY_STATUSES, deterministic_baseline,
    load_evaluation_pack, review_outcome,
)

DEFAULT_PACK = ROOT / "fixtures" / "compilation_cases.json"
EMPTY_MEANING = {"drivers": [], "horizon": None, "invalidation_signposts": []}


# Retain the public name used by one-report reviews.
from desk_cli import CommandJournal as ReviewJournal


def _rating(question, ask, say):
    say(quoted(question))
    while True:
        value = ask("Review (good/poor/uncertain): ").strip().lower()
        if value in QUALITY_STATUSES:
            return value
        say("Choose good, poor or uncertain. These are your judgments, not a model score.")


def _available_result(result, thesis_id, exact_text, selection):
    thesis, output = result["thesis"], result["compilation"]
    if (_id(thesis["id"]) != thesis_id
            or output["provider"] != selection["provider_id"]
            or output["model_id"] != selection["model_id"]):
        raise WalkthroughError("The compilation response does not match the requested thesis or selected provider/model. No review or approval was accepted.")
    if output["status"] not in {"compiled", "stale", "failed", "running", "outcome_unknown"}:
        raise WalkthroughError("The backend returned an unknown compilation state. No retry was made.")
    if output["status"] != "compiled":
        return output["status"]
    if (output.get("is_current_draft") is not True
            or output.get("interpretation_version_id") != thesis["draft"]["interpretation"]["id"]):
        return "stale"
    if thesis["draft"]["text_version"]["exact_text"] != exact_text:
        raise WalkthroughError("The current compilation response differs from the requested exact input. No review or approval was accepted.")
    from macro_agent.domain.compilation import build_review_card
    inputs = output.get("refinement_inputs", [])
    document = parse_compilation(json.dumps(output["document"], ensure_ascii=False, allow_nan=False), exact_text, refinement_inputs=inputs)
    meaning = thesis["draft"]["interpretation"]
    if (meaning.get("review_card") != build_review_card(document, exact_text, refinement_inputs=inputs)
            or meaning["origin"] != "model_compilation" or any(
            meaning[field] != document["interpretation"][field] for field in EMPTY_MEANING)):
        raise WalkthroughError("The suggested draft and compilation document disagree. No review or approval was accepted.")
    return "compiled"


def evaluate_one(client, case, rubric, journal, *, requested_model=None,
                 ask=input, secret=getpass.getpass, say=print):
    """Exactly one explicitly initiated compiler request; journal precedes it."""
    baseline = deterministic_baseline(case["exact_text"])
    journal.append("case", {"case": case, "baseline": baseline, "rubric": rubric,
        "scope": "text_only_compilation_review", "maximum_compile_requests": 1,
        "automatic_retries": 0, "automatic_approvals": 0})
    say("One-thesis compilation review. Output is unverified and has no current macro context.")
    say("Exact input: " + quoted(case["exact_text"]))
    say("Deterministic baseline, literal labels only: " + quoted(baseline))
    for question in case["review_questions"]:
        say("Case review question: " + quoted(question))
    username = required("Username: ", ask, say)
    password = secret("Password: ")
    client.login(username, password)
    del password
    try:
        selection = select_model(client, requested=requested_model, ask=ask, say=say)
        if selection is None:
            journal.append("cancelled", {"reason": "no_model_selected", "compile_requests": 0})
            return None
        say("This sends your exact thesis to the selected provider and may incur a charge. No dollar cap is guaranteed.")
        if ask("Type run to initiate one model request, or Enter to cancel: ").strip().lower() != "run":
            journal.append("cancelled", {"reason": "not_initiated", "compile_requests": 0})
            return None
        created = client.request("POST", "/api/v1/theses/", {
            "command_id": str(uuid4()), "text": case["exact_text"], "interpretation": EMPTY_MEANING})
        thesis = created["thesis"]
        thesis_id = _id(thesis["id"])
        if thesis["draft"]["text_version"]["exact_text"] != case["exact_text"]:
            raise WalkthroughError("The saved draft differs from your exact input. No model request was made.")
        journal.append("draft", created)
        command = {"command_id": str(uuid4()), "expected_revision": thesis["revision"], **selection}
        # Persist the request identity before transmission. An absent response
        # is recoverable through backend inspection, never implicit resubmission.
        journal.append("compile_requested", {"thesis_id": thesis_id, "request": command})
        try:
            result = client.request("POST", f"/api/v1/theses/{thesis_id}/compile/", command)
        except WalkthroughError:
            journal.append("response_unavailable", {"outcome": "not_established",
                "review": review_outcome("outcome_unknown"), "automatic_retries": 0})
            raise
        journal.append("compile_response", result)
        review_state = _available_result(result, thesis_id, case["exact_text"], selection)
        render_compilation(result["compilation"], say)
        if review_state != "compiled":
            outcome = review_outcome(review_state)
            journal.append("review", outcome)
            say("This result is not reviewable as current output. Failure or uncertainty is not a poor reasoning grade. No retry was made.")
            return outcome
        render_draft(result["thesis"], model_generated=True, say=say)
        if ask("Type review to record your feedback, or Enter to leave it unreviewed: ").strip().lower() != "review":
            journal.append("review_deferred", {"ratings": None})
            say("Result saved for later inspection. The thesis remains unapproved.")
            return None
        ratings = {}
        for item in rubric:
            ratings[item["id"]] = _rating(item["question"], ask, say)
            journal.append("review_dimension", {"id": item["id"], "rating": ratings[item["id"]]})
        while True:
            preference = ask("Which was more useful (model/baseline/uncertain): ").strip().lower()
            if preference in {"model", "baseline", "uncertain"}:
                break
            say("Choose model, baseline or uncertain; there is no assumed model advantage.")
        notes = ask("Reason or failure example (optional, up to 2000 characters): ")
        while len(notes) > 2000 or "\x00" in notes:
            notes = ask("Use at most 2000 characters without NUL: ")
        outcome = {**review_outcome("compiled", ratings), "comparison": preference, "notes": notes}
        journal.append("review", outcome)
        say("Review saved. This single case does not establish model superiority or investment skill. The thesis remains unapproved.")
        return outcome
    finally:
        try:
            client.logout()
        except WalkthroughError:
            say("Session cleanup could not reach the backend. Saved records remain unchanged.")


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    inputs = result.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--list", action="store_true", help="List synthetic cases without login or inference")
    inputs.add_argument("--case", help="Review one synthetic pack case")
    inputs.add_argument("--thesis-file", type=Path, help="Review your exact UTF-8 thesis file")
    result.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    result.add_argument("--url", type=local_url, default="http://127.0.0.1:8000")
    result.add_argument("--model", help="Explicit ID from the fetched catalogue; otherwise select interactively")
    result.add_argument("--output", type=Path, help="New private JSONL journal; defaults to an ignored .local/ file")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    journal = None
    try:
        pack = load_evaluation_pack(args.pack)
        if args.list:
            for case in pack["cases"]:
                print(quoted(case["id"]) + ": " + quoted(case["title"]))
            return 0
        if args.thesis_file:
            case = {"id": "user-input", "title": "User supplied exact input", "instrument": "unverified",
                    "tags": ["user_supplied"], "exact_text": read_thesis(args.thesis_file), "review_questions": []}
        else:
            case = next((case for case in pack["cases"] if case["id"] == args.case), None)
            if case is None:
                raise WalkthroughError("Unknown case. Use --list to inspect available case IDs.")
        path = args.output
        if path is None:
            (ROOT / ".local").mkdir(mode=0o700, exist_ok=True)
            path = ROOT / ".local" / ("compilation-review-" + uuid4().hex + ".jsonl")
        journal = ReviewJournal(path)
        journal.append("protocol", {"schema_version": pack["schema_version"],
            "canonical_pack_sha256": sha256(json.dumps(pack, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest(), "scope_limits": pack["scope_limits"],
            "comparison": "unblinded_literal_baseline", "quality_thresholds": "not_selected",
            "automatic_learning": False})
        print("Private review journal: " + str(path))
        evaluate_one(DeskClient(args.url), case, pack["rubric"], journal, requested_model=args.model)
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nStopped. The journal retains completed steps; no automatic approval or retry was made.", file=sys.stderr)
        return 130
    except (WalkthroughError, ValueError, TypeError, KeyError, OSError) as error:
        message = str(error) if isinstance(error, WalkthroughError) else "Review input or response could not be validated. No automatic retry was made."
        print("Review stopped: " + message, file=sys.stderr)
        return 1
    finally:
        if journal is not None:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
