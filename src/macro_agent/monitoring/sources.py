"""Bounded source capture without model calls, article fetching or retries.

The official feed is a rolling snapshot, not a completeness contract. Published
dates are publisher claims; received_at is the local read observation, not a
durable commit time or proof of first public availability. RSS markup is reduced
to plain text; the transport digest retains the identity of the original bytes.
Rejected response bytes are not retained for operational replay. The transport
applies a total elapsed request deadline, including response reads. Persistence
still fences capture results against the current admission.

Verified on 2026-10-07 against the Board's source directory and reuse policy:
https://www.federalreserve.gov/feeds/feeds.htm
https://www.federalreserve.gov/disclaimer.htm
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
from http.client import HTTPException
import json
from pathlib import Path
import re
from types import MappingProxyType
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from macro_agent.transport.http import BoundedOpener, TransportError


MAX_BATCH_BYTES = 1024 * 1024
MAX_ITEMS = 100
_FIELDS = frozenset({"id", "title", "url", "published_at", "content"})
_ISO_DATE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)


class SourceError(RuntimeError):
    """Stable safe failure category, without remote bodies or local paths."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"Source capture failed ({code}).")


def _text(value, limit, *, blank=False):
    if type(value) is not str or len(value) > limit or (not blank and not value.strip()):
        raise SourceError("invalid_item")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise SourceError("invalid_item") from None
    return value


def _utc(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise SourceError("invalid_time")
    try:
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise SourceError("invalid_time") from None


def _url(value):
    _text(value, 2048)
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value):
        raise SourceError("invalid_item")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        raise SourceError("invalid_item") from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or port not in (None, 443)):
        raise SourceError("invalid_item")
    return value


@dataclass(frozen=True)
class SourceItem:
    native_id: str
    title: str
    url: str
    published_at: datetime | None
    content: str

    def __post_init__(self):
        _text(self.native_id, 512)
        if any(ord(character) < 32 or ord(character) == 127 for character in self.native_id):
            raise SourceError("invalid_item")
        _text(self.title, 4096)
        _url(self.url)
        _text(self.content, 16384, blank=True)
        if self.published_at is not None:
            object.__setattr__(self, "published_at", _utc(self.published_at))

    def payload(self):
        """Normalized identity payload; source strings are otherwise preserved."""
        return {"id": self.native_id, "title": self.title, "url": self.url,
                "published_at": self.published_at.isoformat() if self.published_at else None,
                "content": self.content}

    @property
    def digest(self):
        encoded = json.dumps(self.payload(), sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SourceBatch:
    items: tuple[SourceItem, ...]
    received_at: datetime
    coverage: str
    truncated: bool
    transport_digest: str

    def __post_init__(self):
        if (type(self.items) is not tuple or len(self.items) > MAX_ITEMS
                or any(type(item) is not SourceItem for item in self.items)):
            raise SourceError("item_limit")
        _unique_items(self.items)
        object.__setattr__(self, "received_at", _utc(self.received_at))
        if (self.coverage != "bounded_snapshot" or type(self.truncated) is not bool
                or type(self.transport_digest) is not str
                or re.fullmatch(r"[a-f0-9]{64}", self.transport_digest) is None):
            raise SourceError("invalid_batch")


@dataclass(frozen=True)
class SourceSpec:
    id: str
    label: str
    url: str
    rights_note: str
    kind: str
    max_items: int = MAX_ITEMS
    max_bytes: int = MAX_BATCH_BYTES
    # Total transport deadline; local cancellation does not prove remote state.
    timeout_seconds: int = 10


source_specs = MappingProxyType({
    "fed-press": SourceSpec(
        id="fed-press", label="Federal Reserve Board press-release RSS",
        url="https://www.federalreserve.gov/feeds/press_all.xml", kind="rss",
        rights_note=("Board feed text and metadata only, attributed to the Board. Its website "
                     "policy permits reuse unless otherwise indicated; third-party materials "
                     "and protected logos are excluded. No linked pages are fetched. "
                     "Policy checked 2026-10-07: https://www.federalreserve.gov/disclaimer.htm"),
    ),
})


def _unique_items(items):
    seen = set()
    for item in items:
        if item.native_id in seen:
            raise SourceError("duplicate_identity")
        seen.add(item.native_id)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceError("invalid_json")
        result[key] = value
    return result


def _reject_constant(value):
    raise SourceError("invalid_json")


def _recorded_time(value):
    if value is None:
        return None
    if type(value) is not str or _ISO_DATE.fullmatch(value) is None:
        raise SourceError("invalid_time")
    try:
        return _utc(datetime.fromisoformat(value))
    except (ValueError, OverflowError):
        raise SourceError("invalid_time") from None


def load_recorded(path) -> SourceBatch:
    """Read one strict fictional fixture, preserving its exact string values."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_BATCH_BYTES + 1)
    except OSError:
        raise SourceError("fixture_unavailable") from None
    received_at = datetime.now(timezone.utc)
    if len(raw) > MAX_BATCH_BYTES:
        raise SourceError("byte_limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise SourceError("invalid_json") from None
    if type(value) is not dict or set(value) != {"items"} or type(value["items"]) is not list:
        raise SourceError("invalid_json")
    if len(value["items"]) > MAX_ITEMS:
        raise SourceError("item_limit")
    items = []
    for item in value["items"]:
        if type(item) is not dict or set(item) != _FIELDS:
            raise SourceError("invalid_item")
        items.append(SourceItem(item["id"], item["title"], item["url"],
                                _recorded_time(item["published_at"]), item["content"]))
    return SourceBatch(tuple(items), received_at, "bounded_snapshot", False, sha256(raw).hexdigest())


class _PlainText(HTMLParser):
    """Plain text representation of feed HTML, never a renderer or fetcher."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif not self.hidden and tag in {"br", "p", "div", "li"} and self.parts:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _plain_text(value):
    if "<" not in value and "&" not in value:
        return value
    parser = _PlainText()
    try:
        parser.feed(value)
        parser.close()
    except (ValueError, AssertionError):
        raise SourceError("invalid_feed") from None
    return "".join(parser.parts)


def _field(item, name, *, required=False):
    fields = item.findall(name)
    if len(fields) > 1 or (required and not fields) or (fields and len(fields[0])):
        raise SourceError("invalid_feed")
    return (fields[0].text or "") if fields else ""


def parse_rss(raw: bytes, *, received_at: datetime, spec: SourceSpec) -> SourceBatch:
    """Parse a complete bounded RSS2 snapshot, rejecting DTDs and entities."""
    if type(raw) is not bytes or len(raw) > spec.max_bytes:
        raise SourceError("byte_limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise SourceError("invalid_feed") from None
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, flags=re.IGNORECASE):
        raise SourceError("unsafe_xml")
    encoding = re.search(r"^\s*<\?xml\s+[^?]*encoding\s*=\s*['\"]([^'\"]+)['\"]", text)
    if encoding and encoding.group(1).lower() not in {"utf-8", "utf8"}:
        raise SourceError("invalid_feed")
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError, RecursionError):
        raise SourceError("invalid_feed") from None
    if (root.tag != "rss" or root.get("version") != "2.0"
            or len(root.findall("channel")) != 1 or len(list(root.iter())) > 10000):
        raise SourceError("invalid_feed")
    entries = root.find("channel").findall("item")
    if len(list(root.iter("item"))) != len(entries):
        raise SourceError("invalid_feed")
    if len(entries) > spec.max_items:
        raise SourceError("item_limit")
    items = []
    for entry in entries:
        date = _field(entry, "pubDate")
        published_at = None
        if date:
            try:
                published_at = _utc(parsedate_to_datetime(date))
            except (ValueError, TypeError, OverflowError):
                raise SourceError("invalid_time") from None
        items.append(SourceItem(
            _field(entry, "guid", required=True),
            _plain_text(_field(entry, "title", required=True)),
            _field(entry, "link", required=True), published_at,
            _plain_text(_field(entry, "description")),
        ))
    return SourceBatch(tuple(items), received_at, "bounded_snapshot", False, sha256(raw).hexdigest())


def fetch_source(source_id: str) -> SourceBatch:
    """One allowlisted HTTPS GET, outside persistence and without retries."""
    if type(source_id) is not str or source_id not in source_specs:
        raise SourceError("unknown_source")
    spec = source_specs[source_id]
    opener = BoundedOpener()
    request = urllib.request.Request(spec.url, method="GET", headers={
        "Accept": "application/rss+xml, application/xml, text/xml",
        "Accept-Encoding": "identity",
        "User-Agent": "MacroAgentInternalProof/0.1 (+https://github.com/0xsomnus/macro_agent)",
    })
    try:
        with opener.open(request, timeout=spec.timeout_seconds, limit=spec.max_bytes) as response:
            if response.status != 200 or response.geturl() != spec.url:
                raise SourceError("invalid_response")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise SourceError("invalid_response")
            length = response.headers.get("Content-Length")
            if length is not None:
                if not re.fullmatch(r"[0-9]{1,20}", length):
                    raise SourceError("invalid_response")
                if int(length) > spec.max_bytes:
                    raise SourceError("byte_limit")
            raw = response.read(spec.max_bytes + 1)
            received_at = datetime.now(timezone.utc)
            if len(raw) > spec.max_bytes:
                raise SourceError("byte_limit")
            if length is not None and len(raw) != int(length):
                raise SourceError("incomplete_response")
    except TransportError as error:
        code = error.code if error.code in ("byte_limit", "invalid_response", "incomplete_response") else "transport_error"
        raise SourceError(code) from None
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        if status == 429:
            raise SourceError("rate_limited") from None
        if 500 <= status <= 599:
            raise SourceError("unavailable") from None
        raise SourceError("http_error") from None
    except (TimeoutError, urllib.error.URLError, OSError, HTTPException):
        raise SourceError("transport_error") from None
    return parse_rss(raw, received_at=received_at, spec=spec)
