"""Source capture tests use bounded fake transport and fictional text only."""

from dataclasses import replace
from datetime import datetime, timezone
from email.message import Message
from hashlib import sha256
from http.client import IncompleteRead
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from macro_agent.monitoring import sources
from macro_agent.monitoring.sources import (
    SourceBatch, SourceError, SourceItem, fetch_source, load_recorded, parse_rss, source_specs,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC = source_specs["fed-press"]
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
ITEM = {"id": "fictional-001", "title": " Fictional Δ title ",
        "url": "https://example.invalid/fictional-001", "published_at": "2026-10-01T12:00:00Z",
        "content": " Exact fictional text.\r\nSecond line.\r\n"}


def rss_item(*, identity="fictional-001", date="Thu, 1 Oct 2026 12:00:00 GMT", extra="",
             title="Fictional Δ title", description="Exact fictional feed text."):
    pubdate = f"<pubDate>{date}</pubDate>" if date is not None else ""
    return (f"<item><guid>{identity}</guid><title><![CDATA[{title}]]></title>"
            f"<link>https://example.invalid/{identity}</link>"
            f"<description><![CDATA[{description}]]></description>{pubdate}{extra}</item>")


def rss(*items):
    return ('<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
            '<title>Fictional test feed</title>' + "".join(items) + '</channel></rss>').encode()


class Response:
    def __init__(self, body, *, url=SPEC.url, status=200, headers=None, read_error=None):
        self.body, self.url, self.status = body, url, status
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self.read_error = read_error
        self.read_sizes = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def geturl(self):
        return self.url

    def read(self, size):
        self.read_sizes.append(size)
        if self.read_error:
            raise self.read_error
        return self.body[:size]


class Opener:
    def __init__(self, response):
        self.response, self.calls, self.limits = response, [], []

    def open(self, request, *, timeout, limit):
        self.calls.append((request, timeout))
        self.limits.append(limit)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class SourceCaptureTests(unittest.TestCase):
    def assert_code(self, code, callback):
        with self.assertRaises(SourceError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def fixture(self, raw):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            path.write_bytes(raw if type(raw) is bytes else json.dumps(raw).encode())
            return load_recorded(path)

    def parse(self, raw):
        return parse_rss(raw, received_at=NOW, spec=SPEC)

    def fetch(self, response):
        opener = Opener(response)
        with patch.object(sources, "BoundedOpener", return_value=opener):
            result = fetch_source("fed-press")
        return result, opener

    def test_recorded_capture_preserves_exact_unicode_and_line_endings(self):
        batch = self.fixture({"items": [ITEM]})
        self.assertEqual(batch.items[0].title, ITEM["title"])
        self.assertEqual(batch.items[0].content, ITEM["content"])
        self.assertEqual(batch.items[0].published_at, datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(batch.received_at.utcoffset().total_seconds(), 0)
        self.assertEqual((batch.coverage, batch.truncated), ("bounded_snapshot", False))

    def test_digest_normalizes_offset_only_and_tracks_each_source_field(self):
        first = self.fixture({"items": [ITEM]}).items[0]
        offset = dict(ITEM, published_at="2026-10-01T15:00:00+03:00")
        self.assertEqual(first.digest, self.fixture({"items": [offset]}).items[0].digest)
        for field, value in (("id", "different"), ("title", "Changed title"),
                             ("url", "https://example.invalid/changed"),
                             ("published_at", None), ("content", "Changed fictional text")):
            with self.subTest(field=field):
                self.assertNotEqual(first.digest, self.fixture({"items": [dict(ITEM, **{field: value})]}).items[0].digest)
        self.assertNotEqual(first.digest, replace(first, content=first.content.replace("\r\n", "\n")).digest)

    def test_transport_digest_tracks_bytes_separately_from_item_meaning(self):
        compact = json.dumps({"items": [ITEM]}, separators=(",", ":")).encode()
        pretty = json.dumps({"items": [ITEM]}, indent=2).encode()
        first, second = self.fixture(compact), self.fixture(pretty)
        self.assertEqual(first.items[0].digest, second.items[0].digest)
        self.assertEqual(first.transport_digest, sha256(compact).hexdigest())
        self.assertNotEqual(first.transport_digest, second.transport_digest)

    def test_fictional_correction_keeps_identity_changes_only_first_item(self):
        first = load_recorded(ROOT / "fixtures/monitoring_feed.json")
        corrected = load_recorded(ROOT / "fixtures/monitoring_feed_correction.json")
        self.assertEqual(first.items[0].native_id, corrected.items[0].native_id)
        self.assertNotEqual(first.items[0].digest, corrected.items[0].digest)
        self.assertEqual(first.items[1].digest, corrected.items[1].digest)
        self.assertIsNone(first.items[1].published_at)
        self.assertIn("FICTIONAL", first.items[0].title)

    def test_fixture_rejects_duplicate_keys_nonfinite_and_extra_fields(self):
        for raw in (b'{"items":[],"items":[]}', b'{"items":[],"other":1}',
                    b'{"items":NaN}', b'{"items":{}}', b'[]', b'\xff'):
            with self.subTest(raw=raw):
                self.assert_code("invalid_json", lambda: self.fixture(raw))
        repeated = json.dumps({"items": [ITEM]}).replace('"id": "fictional-001"', '"id":"one","id":"two"').encode()
        self.assert_code("invalid_json", lambda: self.fixture(repeated))
        self.assert_code("invalid_item", lambda: self.fixture({"items": [dict(ITEM, extra=1)]}))

    def test_fixture_rejects_duplicate_ids_even_if_reports_are_identical(self):
        for second in (ITEM, dict(ITEM, content="conflicting content")):
            with self.subTest(second=second["content"]):
                self.assert_code("duplicate_identity", lambda: self.fixture({"items": [ITEM, second]}))

    def test_fixture_limits_reject_entire_batch_and_missing_file_is_safe(self):
        self.assert_code("byte_limit", lambda: self.fixture(b" " * (sources.MAX_BATCH_BYTES + 1)))
        items = [dict(ITEM, id=f"test-{index}") for index in range(sources.MAX_ITEMS + 1)]
        self.assert_code("item_limit", lambda: self.fixture({"items": items}))
        error = self.assert_code("fixture_unavailable", lambda: load_recorded("/nonexistent/private-test-path"))
        self.assertNotIn("private-test-path", str(error))

    def test_missing_publication_is_explicit_invalid_or_naive_dates_are_rejected(self):
        self.assertIsNone(self.fixture({"items": [dict(ITEM, published_at=None)]}).items[0].published_at)
        for value in ("2026-10-01", "2026-10-01T12:00:00", "2026-13-01T12:00:00Z", "yesterday", 1, True):
            with self.subTest(value=value):
                self.assert_code("invalid_time", lambda: self.fixture({"items": [dict(ITEM, published_at=value)]}))

    def test_source_item_bounds_types_urls_and_naive_time_are_enforced(self):
        values = (("id", "x" * 513), ("id", "bad\nidentity"), ("title", "x" * 4097),
                  ("content", "x" * 16385), ("title", True), ("content", "\ud800"),
                  ("url", "http://example.invalid/a"), ("url", "https://name:password@example.invalid/a"),
                  ("url", "https://example.invalid:8443/a"), ("url", "https://example.invalid/a\n"))
        for field, value in values:
            with self.subTest(field=field, value=repr(value[:20]) if type(value) is str else value):
                self.assert_code("invalid_item", lambda: self.fixture({"items": [dict(ITEM, **{field: value})]}))
        self.assert_code("invalid_time", lambda: SourceItem("id", "title", ITEM["url"], datetime(2026, 1, 1), ""))

    def test_batch_rejects_malformed_metadata_and_direct_duplicate_items(self):
        item = self.fixture({"items": [ITEM]}).items[0]
        self.assert_code("invalid_batch", lambda: SourceBatch((item,), NOW, "complete", False, "a" * 64))
        self.assert_code("invalid_batch", lambda: SourceBatch((item,), NOW, "bounded_snapshot", False, 42))
        self.assert_code("invalid_time", lambda: SourceBatch((item,), NOW.replace(tzinfo=None), "bounded_snapshot", False, "a" * 64))
        self.assert_code("duplicate_identity", lambda: SourceBatch((item, item), NOW, "bounded_snapshot", False, "a" * 64))

    def test_rss_preserves_native_identity_and_claimed_time_and_strips_markup(self):
        batch = self.parse(rss(rss_item(description="<p>First &amp; second</p><p>Next</p><script>bad()</script>")))
        self.assertEqual(batch.items[0].native_id, "fictional-001")
        self.assertEqual(batch.items[0].content, "First & second\nNext")
        self.assertEqual(batch.items[0].published_at, datetime(2026, 10, 1, 12, tzinfo=timezone.utc))
        self.assertEqual(batch.received_at, NOW)
        self.assertEqual(batch.transport_digest, sha256(rss(rss_item(description="<p>First &amp; second</p><p>Next</p><script>bad()</script>"))).hexdigest())

    def test_rss_accepts_utf8_bom_and_unknown_publication_and_empty_snapshot(self):
        self.assertIsNone(self.parse(b"\xef\xbb\xbf" + rss(rss_item(date=None))).items[0].published_at)
        self.assertEqual(self.parse(rss()).items, ())

    def test_rss_rejects_dtd_entity_definitions_and_alternate_encodings(self):
        declarations = ('<!DOCTYPE rss [<!ENTITY secret "expanded">]>', '<!ENTITY secret SYSTEM "file:///private">')
        for declaration in declarations:
            with self.subTest(declaration=declaration):
                self.assert_code("unsafe_xml", lambda: self.parse((declaration + rss().decode()).encode()))
        utf16 = ('<?xml version="1.0" encoding="utf-16"?>'
                 '<!DOCTYPE rss [<!ENTITY attack "text">]><rss version="2.0"><channel/></rss>').encode("utf-16")
        self.assert_code("invalid_feed", lambda: self.parse(utf16))
        other = rss().replace(b'encoding="utf-8"', b'encoding="iso-8859-1"')
        self.assert_code("invalid_feed", lambda: self.parse(other))

    def test_rss_rejects_malformed_shape_duplicate_fields_missing_identity_and_nested_item(self):
        samples = (b"not XML", b"<rss version='2.0'><channel>",
                   b"<rss version='2.0'><channel/><channel/></rss>",
                   b"<rss version='1.0'><channel/></rss>",
                   rss(rss_item(extra="<title>ambiguous</title>")),
                   rss(rss_item()).replace(b"<guid>fictional-001</guid>", b""),
                   rss(rss_item()).replace(b"<guid>fictional-001</guid>", b"<guid><nested>bad</nested></guid>"),
                   rss("<wrapper>" + rss_item() + "</wrapper>"))
        for raw in samples:
            with self.subTest(raw=raw[:80]):
                self.assert_code("invalid_feed", lambda: self.parse(raw))

    def test_rss_rejects_naive_bad_dates_duplicates_and_limits_without_partial_success(self):
        for date in ("not a date", "Thu, 1 Oct 2026 12:00:00", "Thu, 32 Oct 2026 12:00:00 GMT"):
            with self.subTest(date=date):
                self.assert_code("invalid_time", lambda: self.parse(rss(rss_item(date=date))))
        self.assert_code("duplicate_identity", lambda: self.parse(rss(rss_item(), rss_item(description="Changed"))))
        self.assert_code("item_limit", lambda: self.parse(rss(*(rss_item(identity=f"id-{index}") for index in range(101)))))
        self.assert_code("byte_limit", lambda: self.parse(b" " * (sources.MAX_BATCH_BYTES + 1)))

    def test_fetch_is_one_fixed_get_and_uses_bounded_read_without_model_or_article_requests(self):
        response = Response(rss(rss_item()))
        batch, opener = self.fetch(response)
        request, timeout = opener.calls[0]
        self.assertEqual((request.full_url, request.method, timeout), (SPEC.url, "GET", 10))
        self.assertEqual(request.get_header("Accept-encoding"), "identity")
        self.assertEqual(response.read_sizes, [sources.MAX_BATCH_BYTES + 1])
        self.assertTrue(response.closed)
        self.assertEqual(len(batch.items), 1)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(opener.limits, [sources.MAX_BATCH_BYTES])

    def test_shared_bounded_transport_and_unknown_source_never_dispatches(self):
        opener = Opener(Response(rss()))
        with patch.object(sources, "BoundedOpener", return_value=opener) as builder:
            fetch_source("fed-press")
            self.assert_code("unknown_source", lambda: fetch_source("https://attacker.invalid/feed"))
        builder.assert_called_once_with()
        self.assertEqual(len(opener.calls), 1)

    def test_transport_bounds_and_unexpected_compression_are_rejected_before_parse(self):
        samples = (("byte_limit", Response(b"x", headers={"Content-Length": str(sources.MAX_BATCH_BYTES + 1)})),
                   ("byte_limit", Response(b"x" * (sources.MAX_BATCH_BYTES + 1))),
                   ("invalid_response", Response(rss(), headers={"Content-Length": "unknown"})),
                   ("invalid_response", Response(rss(), headers={"Content-Encoding": "gzip"})),
                   ("incomplete_response", Response(rss(), headers={"Content-Length": "999"})))
        for code, response in samples:
            with self.subTest(code=code):
                self.assert_code(code, lambda: self.fetch(response))
                self.assertTrue(response.closed)

    def test_wrong_final_url_and_status_are_rejected_once(self):
        for response in (Response(rss(), url="https://other.invalid/feed"), Response(rss(), status=206)):
            with self.subTest(url=response.url, status=response.status):
                self.assert_code("invalid_response", lambda: self.fetch(response))
                self.assertEqual(response.read_sizes, [])

    def test_http_error_bodies_are_not_read_or_exposed_or_retried(self):
        for status, code in ((302, "http_error"), (403, "http_error"), (429, "rate_limited"), (503, "unavailable")):
            with self.subTest(status=status):
                body = io.BytesIO(b"remote private error detail")
                remote = urllib.error.HTTPError(SPEC.url, status, "remote private error detail", {}, body)
                opener = Opener(remote)
                with patch.object(sources, "BoundedOpener", return_value=opener):
                    error = self.assert_code(code, lambda: fetch_source("fed-press"))
                self.assertNotIn("remote private", str(error))
                self.assertTrue(body.closed)
                self.assertEqual(len(opener.calls), 1)

    def test_timeout_partial_read_and_network_failures_are_safe_and_not_retried(self):
        samples = (TimeoutError("private timeout detail"), urllib.error.URLError("private network detail"),
                   Response(rss(), read_error=IncompleteRead(b"private partial", 20)))
        for response in samples:
            with self.subTest(response=type(response).__name__):
                opener = Opener(response)
                with patch.object(sources, "BoundedOpener", return_value=opener):
                    error = self.assert_code("transport_error", lambda: fetch_source("fed-press"))
                self.assertNotIn("private", str(error))
                self.assertEqual(len(opener.calls), 1)


if __name__ == "__main__":
    unittest.main()
