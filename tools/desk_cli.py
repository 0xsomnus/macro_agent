"""Guided local desk walkthrough using the authenticated HTTP application API.

This client has no database access or trading rules. It preserves manual input,
requires explicit approval, and displays the recorded-news boundary's limits.
"""

import argparse
import getpass
import http.cookiejar
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID, uuid4


MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class WalkthroughError(Exception):
    """An actionable error whose text contains no credentials or tokens."""


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
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            messages = {
                400: "The server rejected these inputs. Check required text, duplicate drivers and quantity/unit format.",
                403: "Authentication or CSRF validation failed. Check the account credentials and restart the walkthrough.",
                404: "This item or the recorded-news endpoint is unavailable. Check the local lab setup and account.",
                409: "The saved state changed. Review the current thesis before approving again. No replacement was approved automatically.",
                415: "The server did not accept the client's JSON request format.",
            }
            if 300 <= status < 400:
                raise WalkthroughError("The server requested a redirect. It was blocked; use the direct loopback server address.") from None
            raise WalkthroughError(messages.get(status, f"The local server returned HTTP {status}. Check its terminal for the cause.")) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise WalkthroughError(f"Cannot reach the local desk at {self.url}. Start the server and check its port.") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise WalkthroughError("The local server returned an unexpectedly large response.")
        try:
            result = json.loads(raw.decode("utf-8"))
            if type(result) is not dict:
                raise ValueError
        except (UnicodeError, ValueError):
            raise WalkthroughError("The local server returned an invalid JSON response. Check its terminal.") from None
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
    say("Model calls: 0. Live monitoring is not configured.")
    for limitation in response.get("limitations", []):
        say(f"  {quoted(limitation)}")
    return brief["context_status"] == "ready" and notice["is_current"] is True


def happy_path(client, *, thesis_file=None, ask=input, secret=getpass.getpass, say=print):
    say("Local recorded-news walkthrough. Your entries are saved in the local desk database.")
    say("No live news, model analysis, broker execution or external notification is used.")
    username = required("Username: ", ask, say)
    password = secret("Password: ")
    client.login(username, password)
    del password
    try:
        return _entered_happy_path(client, thesis_file=thesis_file, ask=ask, say=say)
    finally:
        try:
            client.logout()
        except WalkthroughError:
            say("Session cleanup could not reach the local server. Saved records are unchanged; the server session will expire normally.")


def _entered_happy_path(client, *, thesis_file, ask, say):
    text = read_thesis(thesis_file) if thesis_file else required("Your thesis (one line): ", ask, say)
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
    draft = thesis["draft"]
    say(f"\nDraft saved: {thesis_id}")
    say("Exact thesis text, JSON quoting preserves whitespace and line endings:")
    say(quoted(draft["text_version"]["exact_text"]))
    reviewed_meaning = {name: draft["interpretation"][name]
                        for name in ("drivers", "horizon", "invalidation_signposts")}
    say("Manual interpretation to approve:")
    say(quoted(reviewed_meaning))
    trace = {"mode": "recorded_example", "draft": created}
    if ask("Type approve to approve exactly this text and interpretation, or Enter to leave a draft: ").strip().lower() != "approve":
        say("Draft left unapproved. No paper position or recorded-news notice was created.")
        return trace
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
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.thesis_file:
            read_thesis(args.thesis_file)
        if args.output and (args.output.exists() or not args.output.parent.is_dir()):
            raise WalkthroughError("Choose a new trace filename in an existing directory. Existing files are never overwritten.")
        trace = happy_path(DeskClient(args.url), thesis_file=args.thesis_file)
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
