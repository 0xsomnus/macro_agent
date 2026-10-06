"""Guided local desk walkthrough using the authenticated HTTP application API.

This client has no database access or trading rules. It preserves manual input,
requires explicit approval, and displays the recorded-news boundary's limits.
"""

import argparse
import getpass
from http.client import HTTPException
import http.cookiejar
import json
import os
from pathlib import Path
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID, uuid4
import warnings


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MODEL_PAGE_SIZE = 20
ROOT = Path(__file__).resolve().parents[1]
PROVIDER_LABELS = {"nanogpt": "NanoGPT", "openrouter": "OpenRouter", "cheaperinference": "CheaperInference"}


class WalkthroughError(Exception):
    """An actionable error whose text contains no credentials or tokens."""


def _response_error(path, message):
    if path.endswith("/compile/"):
        return WalkthroughError("The compilation response was not received. Its outcome and cost are unknown. The saved draft remains unapproved; check its history before another provider request. No retry was made.")
    return WalkthroughError(message)


def local_url(value):
    """Use an explicit loopback target without proxies or ambiguous URL parts."""
    if any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
        raise argparse.ArgumentTypeError("Use a plain loopback HTTP URL, such as http://127.0.0.1:8000.")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or port == 0):
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError("Use a loopback HTTP origin without credentials, a path or a query.") from None
    # Avoid resolving localhost through a potentially modified resolver.
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    return "http://" + host + (f":{port}" if port is not None else "")


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class DeskClient:
    def __init__(self, url, *, timeout=10):
        self.url = local_url(url)
        self.timeout = timeout
        self.csrf_token = None
        self.authenticated = False
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirects(),
            urllib.request.HTTPCookieProcessor(self.cookies),
        )

    def request(self, method, path, body=None):
        if (not path.startswith("/api/v1/") or "?" in path or "#" in path
                or "\\" in path or any(ord(character) < 32 for character in path)):
            raise WalkthroughError("The server returned an invalid application path.")
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            if not self.csrf_token:
                raise WalkthroughError("Start a session before sending a write.")
            headers["Content-Type"] = "application/json; charset=utf-8"
            headers["X-CSRFToken"] = self.csrf_token
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            timeout = 90 if path.endswith("/compile/") else self.timeout
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            messages = {
                400: "The server rejected these inputs. Check required text, duplicate drivers and quantity/unit format.",
                403: "Authentication or CSRF validation failed. Check the account credentials and restart the walkthrough.",
                404: "This item or endpoint is unavailable. Check the account, local lab gate and model-compilation configuration.",
                409: "The saved state changed. Review the current thesis before approving again. No replacement was approved automatically.",
                415: "The server did not accept the client's JSON request format.",
                503: "Model compilation is unavailable. Configure the provider key, load its environment file and restart the backend.",
            }
            if 300 <= status < 400:
                raise WalkthroughError("The server requested a redirect. It was blocked; use the direct loopback server address.") from None
            raise WalkthroughError(messages.get(status, f"The local server returned HTTP {status}. Check its terminal for the cause.")) from None
        except (urllib.error.URLError, TimeoutError, OSError, HTTPException):
            raise _response_error(path, f"Cannot reach the local desk at {self.url}. Start the server and check its port.") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise _response_error(path, "The local server returned an unexpectedly large response.")
        try:
            result = json.loads(raw.decode("utf-8"))
            if type(result) is not dict:
                raise ValueError
        except (UnicodeError, ValueError, RecursionError):
            raise _response_error(path, "The local server returned an invalid JSON response. Check its terminal.") from None
        return result

    def login(self, username, password):
        identity = self.request("GET", "/api/v1/session/")
        self.csrf_token = _token(identity)
        identity = self.request("POST", "/api/v1/session/login/", {"username": username, "password": password})
        if identity.get("authenticated") is not True:
            raise WalkthroughError("The local server did not establish an authenticated session.")
        # Django rotates the CSRF secret on login. Never reuse the bootstrap token.
        self.csrf_token = _token(identity)
        self.authenticated = True

    def logout(self):
        if self.authenticated:
            try:
                self.request("POST", "/api/v1/session/logout/", {})
            finally:
                self.authenticated = False
                self.csrf_token = None


def _token(response):
    value = response.get("csrf_token")
    if not isinstance(value, str) or not value or len(value) > 256:
        raise WalkthroughError("The local server did not supply a valid session token.")
    return value


def _id(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError):
        raise WalkthroughError("The local server returned an invalid record identifier.") from None
    return value


def read_thesis(path):
    try:
        # Path.read_text would translate CRLF. Decode bytes to preserve exact text.
        return Path(path).read_bytes().decode("utf-8", errors="strict")
    except (OSError, UnicodeError):
        raise WalkthroughError("Cannot read the thesis file as UTF-8. Check its path and encoding.") from None


def required(prompt, ask, say):
    while True:
        value = ask(prompt)
        if value.strip():
            return value
        say("Enter a nonblank value.")


def string_list(label, ask, say):
    say(f"{label}: enter one per line; a blank line finishes. Leave empty if unknown.")
    values = []
    while True:
        value = ask("> ")
        if value == "":
            return values
        values.append(value)


def quoted(value):
    # Escape terminal control sequences while keeping Unicode legible.
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def model_catalog(client):
    result = client.request("GET", "/api/v1/models/")
    if result.get("provider") not in PROVIDER_LABELS:
        raise WalkthroughError("The backend did not return a supported model-provider catalog.")
    if result.get("compilation_enabled") is not True or result.get("credentials_configured") is not True:
        raise WalkthroughError("Model compilation is not configured. Run configure-models, load .local/models.env in the backend terminal and restart the server.")
    models = result.get("models")
    if (type(models) is not list or not models
            or any(type(model) is not dict or type(model.get("id")) is not str or not model["id"]
                   for model in models)
            or len({model["id"] for model in models}) != len(models)):
        raise WalkthroughError("No usable model catalog was returned. Check the provider setup and backend terminal.")
    return result


def select_model(client, *, requested=None, ask=input, say=print):
    catalog = model_catalog(client)
    models = catalog["models"]
    provider = catalog["provider"]
    provider_name = PROVIDER_LABELS[provider]
    if requested is not None:
        if not any(model["id"] == requested for model in models):
            raise WalkthroughError("The requested model is not in the currently eligible provider catalog. Select an available model explicitly.")
        say(f"Selected {provider_name} model: " + quoted(requested))
        return {"provider_id": provider, "model_id": requested}
    filtered = models
    page = 0
    while True:
        start = page * MODEL_PAGE_SIZE
        shown = filtered[start:start + MODEL_PAGE_SIZE]
        say(f"\nAvailable {provider_name} models, fetched from the backend:")
        for index, model in enumerate(shown, start=start + 1):
            name = model.get("name") or model["id"]
            input_price = model.get("input_price_usd_per_million")
            output_price = model.get("output_price_usd_per_million")
            say(f"  {index}. {quoted(name)} [{quoted(model['id'])}]")
            say(f"     Context: {quoted(model.get('context_length'))}; input/output USD per million tokens: "
                f"{quoted(input_price) if input_price is not None else 'unknown'} / "
                f"{quoted(output_price) if output_price is not None else 'unknown'}")
        say(f"Showing {len(shown)} of {len(filtered)} matching models. No model is selected by default.")
        choice = ask("Choose a displayed number or model ID, /search text, next, back, or cancel: ").strip()
        if choice == "cancel" or choice == "":
            return None
        if choice.startswith("/"):
            query = (choice[len("/search "):] if choice.startswith("/search ") else choice[1:]).strip().casefold()
            filtered = [model for model in models if query in model["id"].casefold()
                        or query in str(model.get("name") or "").casefold()]
            page = 0
            continue
        if choice == "next":
            if start + MODEL_PAGE_SIZE < len(filtered):
                page += 1
            continue
        if choice == "back":
            page = max(0, page - 1)
            continue
        if any(model["id"] == choice for model in models):
            return {"provider_id": provider, "model_id": choice}
        if choice.isascii() and choice.isdecimal() and start < int(choice) <= start + len(shown):
            return {"provider_id": provider, "model_id": filtered[int(choice) - 1]["id"]}
        say("Choose an available model explicitly. Use / followed by part of its name to filter.")


def render_draft(thesis, *, model_generated, say):
    draft = thesis["draft"]
    say("Exact thesis text, JSON quoting preserves whitespace and line endings:")
    say(quoted(draft["text_version"]["exact_text"]))
    meaning = {name: draft["interpretation"][name]
               for name in ("drivers", "horizon", "invalidation_signposts")}
    say("Model interpretation preview, unverified:" if model_generated else "Manual interpretation to approve:")
    say(quoted(meaning))
    say("Text digest: " + quoted(draft["text_version"]["text_digest"]))
    say("Interpretation digest: " + quoted(draft["interpretation"]["digest"]))


def render_compilation(compilation, say):
    say("\nModel compilation: " + quoted(compilation["status"]))
    say("Provider: " + quoted(compilation["provider"]))
    say("Model: " + quoted(compilation["model_id"]))
    for key, label in (("reported_cost_usd", "Provider-reported cost USD"),
                       ("estimated_cost_usd", "Estimated cost USD")):
        value = compilation.get(key)
        say(label + ": " + (quoted(value) if value is not None else "unknown"))
    say("Token usage: " + quoted(compilation.get("usage")))
    say("This model output is unverified. Current macro context and factual verification are unavailable.")
    document = compilation.get("document")
    if type(document) is not dict:
        return
    say("Grounding in your supplied text, without independent verification:")
    grounding = document.get("grounding", [])
    if not grounding:
        say("  None supplied.")
    for item in grounding:
        say(f"  {quoted(item['field'])} at index {quoted(item['index'])}: {quoted(item['exact_quote'])}")
    say("Gaps, assumptions and questions for your review:")
    issues = document.get("refinement_issues", [])
    if not issues:
        say("  No questions were supplied. This does not establish that the thesis is sound.")
    for issue in issues:
        say("  Kind: " + quoted(issue["kind"]))
        say("  Your quoted words: " + quoted(issue["exact_quote"]))
        say("  Explanation: " + quoted(issue["explanation"]))
        say("  Question: " + quoted(issue["question"]))
    say("Agent hypotheses, separate from your approved meaning:")
    hypotheses = document.get("agent_hypotheses", [])
    if not hypotheses:
        say("  None supplied.")
    for hypothesis in hypotheses:
        say("  Explanation: " + quoted(hypothesis["explanation"]))
        say("  Introduced assumptions: " + quoted(hypothesis["introduced_assumptions"]))
    say("Counter-case, a model hypothesis:")
    say(quoted(document.get("counter_case")))


def compiled_review(client, thesis, *, selection, trace, ask, say):
    thesis_id = _id(thesis["id"])
    exact_text = thesis["draft"]["text_version"]["exact_text"]
    trace["compilations"] = []
    while True:
        model_id, provider_id = selection["model_id"], selection["provider_id"]
        say(f"Your exact thesis will be sent to {PROVIDER_LABELS[provider_id]} using " + quoted(model_id) + ". This model request may incur a charge.")
        result = client.request("POST", f"/api/v1/theses/{thesis_id}/compile/", {
            "command_id": str(uuid4()), "expected_revision": thesis["revision"],
            "provider_id": provider_id, "model_id": model_id,
        })
        trace["compilations"].append(result)
        compilation = result["compilation"]
        render_compilation(compilation, say)
        thesis = result["thesis"]
        if (_id(thesis["id"]) != thesis_id or thesis["draft"]["text_version"]["exact_text"] != exact_text
                or compilation.get("model_id") != model_id or compilation.get("provider") != provider_id):
            raise WalkthroughError("The compilation response no longer matches your exact draft, provider or selected model. No approval was made.")
        if (compilation["status"] != "compiled" or compilation.get("is_current_draft") is not True
                or compilation.get("interpretation_version_id") != thesis["draft"]["interpretation"]["id"]
                or type(compilation.get("document")) is not dict):
            say("The result is unavailable or does not belong to the current draft. Your draft remains unapproved; no automatic retry, position or notice was created.")
            return None
        render_draft(thesis, model_generated=True, say=say)
        choice = ask("Type approve to approve exactly this text and interpretation, switch to choose another model, or Enter to leave a draft: ").strip().lower()
        if choice == "approve":
            return thesis
        if choice != "switch":
            say("Draft left unapproved. No paper position or recorded-news notice was created.")
            return None
        selection = select_model(client, ask=ask, say=say)
        if selection is None:
            say("Draft left unapproved. No further model request was made.")
            return None


def configure_models(path, *, ask=input, secret=getpass.getpass, say=print):
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise WalkthroughError("Model configuration already exists. Existing credential files are never overwritten.")
    say("Configure a model provider for this local backend. The key is stored only in the ignored environment file.")
    provider = ask("Provider (nanogpt/openrouter/cheaperinference): ").strip().lower()
    while provider not in PROVIDER_LABELS:
        say("Choose nanogpt, openrouter or cheaperinference explicitly. There is no default.")
        provider = ask("Provider (nanogpt/openrouter/cheaperinference): ").strip().lower()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = secret(PROVIDER_LABELS[provider] + " API key (hidden): ")
    except getpass.GetPassWarning:
        raise WalkthroughError("Secure terminal input is unavailable. Run configure-models from an interactive terminal.") from None
    if (type(key) is not str or not key or len(key) > 4096
            or any(character.isspace() or not 32 <= ord(character) <= 126 for character in key)):
        raise WalkthroughError("A nonblank API key without whitespace or control characters is required.")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("MACRO_MODEL_PROVIDER=" + shlex.quote(provider) + "\nMACRO_MODEL_API_KEY="
                         + shlex.quote(key) + "\nMACRO_ENABLE_MODEL_COMPILATION=1\n")
    except OSError:
        raise WalkthroughError("Cannot save model credentials. Choose a new filename in a writable local directory.") from None
    del key
    say("Model configuration saved with owner-only permissions. No provider request was made.")
    say("In the backend terminal, load it and restart the server:")
    say("set -a\nsource " + shlex.quote(str(path)) + "\nset +a")
    say("Then run: .venv/bin/python tools/desk_cli.py happy-path --compile")


def render_notice(response, say):
    if (response.get("mode") != "recorded_example" or response.get("synthetic") is not True
            or response.get("model") != "not_used"):
        raise WalkthroughError("The server response is outside the recorded-example walkthrough contract.")
    notice = response["notice"]
    brief = response["brief"]
    source = response["source"]
    say("\nRecorded example news, fictional source")
    for fact in notice["facts"]:
        say(f"  {quoted(fact['field'])}: {quoted(fact['value'])}")
    say(f"Source: {quoted(source['source_id'])}, revision {quoted(source['revision'])}")
    say(f"Portfolio impact: {quoted(notice['portfolio_impact'])}")
    say("This example did not analyse whether the news is relevant to your thesis or trade.")
    if "screening" in response:
        say("Relevance screening: recorded fixture; personalised relevance remains unresolved.")
    say(f"Brief context: {quoted(brief['context_status'])}; current notice: {quoted(notice['is_current'])}")
    notification = notice["notification"]
    say(f"Notice intent: {quoted(notification['state'])}; external delivery: {quoted(notification['external_delivery'])}")
    say("Model calls: 0 for this recorded-news step. Live monitoring is not configured.")
    for limitation in response.get("limitations", []):
        say(f"  {quoted(limitation)}")
    return brief["context_status"] == "ready" and notice["is_current"] is True


def happy_path(client, *, thesis_file=None, compile=False, model_id=None,
               ask=input, secret=getpass.getpass, say=print):
    if model_id is not None and not compile:
        raise WalkthroughError("Use --compile when selecting a model.")
    say("Local recorded-news walkthrough. Your entries are saved in the local desk database.")
    say("Your selected model will propose an interpretation for review. Recorded news remains fictional and unanalysed."
        if compile else "No live news, model analysis, broker execution or external notification is used.")
    username = required("Username: ", ask, say)
    password = secret("Password: ")
    client.login(username, password)
    del password
    try:
        return _entered_happy_path(client, thesis_file=thesis_file, compile=compile,
                                  model_id=model_id, ask=ask, say=say)
    finally:
        try:
            client.logout()
        except WalkthroughError:
            say("Session cleanup could not reach the local server. Saved records are unchanged; the server session will expire normally.")


def _entered_happy_path(client, *, thesis_file, compile, model_id, ask, say):
    text = read_thesis(thesis_file) if thesis_file else required("Your thesis (one line): ", ask, say)
    if compile:
        selection = select_model(client, requested=model_id, ask=ask, say=say)
        if selection is None:
            say("No model selected. No draft or provider request was created.")
            return {"mode": "recorded_example", "model_selected": False}
        say("First saving your exact text with an empty preliminary manual preview. The model result will be separate.")
        meaning = {"drivers": [], "horizon": None, "invalidation_signposts": []}
    else:
        say("Enter your own concise interpretation. No agent is compiling or validating it yet.")
        meaning = {
            "drivers": string_list("Drivers", ask, say),
            "horizon": ask("Thesis horizon (optional): ") or None,
            "invalidation_signposts": string_list("Invalidation signposts", ask, say),
        }
    created = client.request("POST", "/api/v1/theses/", {
        "command_id": str(uuid4()), "text": text, "interpretation": meaning,
    })
    thesis = created["thesis"]
    thesis_id = _id(thesis["id"])
    say(f"\nDraft saved: {thesis_id}")
    trace = {"mode": "recorded_example", "draft": created}
    if compile:
        thesis = compiled_review(client, thesis, selection=selection, trace=trace, ask=ask, say=say)
        if thesis is None:
            return trace
    else:
        render_draft(thesis, model_generated=False, say=say)
        if ask("Type approve to approve exactly this text and interpretation, or Enter to leave a draft: ").strip().lower() != "approve":
            say("Draft left unapproved. No paper position or recorded-news notice was created.")
            return trace
    draft = thesis["draft"]
    approved = client.request("POST", f"/api/v1/theses/{thesis_id}/approvals/", {
        "command_id": str(uuid4()), "expected_revision": thesis["revision"],
        "thesis_version_id": _id(draft["text_version"]["id"]),
        "text_digest": draft["text_version"]["text_digest"],
        "interpretation_version_id": _id(draft["interpretation"]["id"]),
        "interpretation_digest": draft["interpretation"]["digest"],
    })
    approval_id = _id(approved["thesis"]["approved"]["approval"]["id"])
    trace["approval"] = approved
    say("Approved. Now attach a paper position using your own declaration.")
    underlying = required("Instrument (for example XAU or EUR/USD): ", ask, say)
    direction = ask("Direction (long/short): ")
    while direction not in {"long", "short"}:
        say("Enter long or short.")
        direction = ask("Direction (long/short): ")
    quantity = ask("Quantity (optional, fixed decimal such as 1.00): ") or None
    unit = required("Quantity unit (for example contracts or ounces): ", ask, say) if quantity else None
    horizon = ask("Position horizon (optional): ") or None
    position = client.request("POST", f"/api/v1/theses/{thesis_id}/positions/", {
        "command_id": str(uuid4()), "expected_approval_id": approval_id,
        "position": {"underlying": underlying, "direction": direction, "quantity": quantity,
                     "quantity_unit": unit, "horizon": horizon, "product_id": None, "venue": None,
                     "expiry": None, "quote_currency": None},
    })
    trace["position"] = position
    say(f"Paper position saved: {_id(position['position']['id'])}")
    say("Instrument mapping is user declared and unverified.")
    say("Missing fields: " + quoted(position["position"]["current_version"]["missing_fields"]))
    news = client.request("POST", f"/api/v1/lab/theses/{thesis_id}/recorded-news/", {
        "expected_approval_id": approval_id,
    })
    trace["recorded_news"] = news
    current = render_notice(news, say)
    if current:
        say(f"\nWalkthrough complete. Thesis {thesis_id} and its paper position remain available in the local API.")
    else:
        say("\nYour inputs were saved, but this recorded notice is not current. Fresh context admission is required.")
    return trace


def write_trace(path, trace):
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(trace, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
    except OSError:
        raise WalkthroughError("Cannot save the trace. Choose an existing directory and a new filename; existing files are never overwritten.") from None


def parser():
    result = argparse.ArgumentParser(description="Try your own thesis and paper trade against fictional recorded example news.")
    commands = result.add_subparsers(dest="command", required=True)
    happy = commands.add_parser("happy-path", help="Guided login, draft review, explicit approval, paper entry and recorded notice")
    happy.add_argument("--url", type=local_url, default="http://127.0.0.1:8000", help="Direct loopback HTTP server origin")
    happy.add_argument("--thesis-file", type=Path, help="Read exact UTF-8 thesis text, including original line endings")
    happy.add_argument("--output", type=Path, help="Optionally save your private trace to a new file, preferably under .local/")
    happy.add_argument("--compile", action="store_true", help="Ask an explicitly selected provider model for an interpretation and review questions")
    happy.add_argument("--model", help="Select an exact model ID from the current fetched catalog; requires --compile")
    commands.add_parser("configure-models", help="Choose a provider, prompt for its hidden key and create ignored .local/models.env")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "configure-models":
            configure_models(ROOT / ".local" / "models.env")
            return 0
        if args.model is not None and not args.compile:
            raise WalkthroughError("Use --compile when selecting a model.")
        if args.thesis_file:
            read_thesis(args.thesis_file)
        if args.output and (args.output.exists() or not args.output.parent.is_dir()):
            raise WalkthroughError("Choose a new trace filename in an existing directory. Existing files are never overwritten.")
        trace = happy_path(DeskClient(args.url), thesis_file=args.thesis_file,
                          compile=args.compile, model_id=args.model)
        if args.output:
            write_trace(args.output, trace)
            print(f"Private trace saved to {args.output}. It contains your exact thesis and paper declaration.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nStopped. Already saved records remain in the local desk; no automatic approval or retry was made.", file=sys.stderr)
        return 130
    except (WalkthroughError, KeyError, TypeError, ValueError) as exc:
        message = str(exc) if isinstance(exc, WalkthroughError) else "The local server returned an unexpected response. Check its terminal."
        print(f"Walkthrough stopped: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
