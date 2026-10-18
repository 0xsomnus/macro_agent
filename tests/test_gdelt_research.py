"""Fictional GDELT metadata fixtures, without live API or article requests."""

from datetime import datetime, timezone
from email.message import Message
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.monitoring import gdelt_research as gdelt
from macro_agent.monitoring.sources import SourceError
from macro_agent.transport.http import TransportError


NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
QUERY = '"industrial gas" supply substitutes'


def article(index=1, **updates):
    return {"url": f"https://example.invalid/story-{index}", "url_mobile": "",
        "title": f"Fictional gas supply report {index}", "seendate": "20261017T110000Z",
        "socialimage": "https://images.example.invalid/image.jpg", "domain": "example.invalid",
        "language": "English", "sourcecountry": "Uganda", **updates}


def raw(*articles):
    return json.dumps({"articles": list(articles)}).encode()


class Response(io.BytesIO):
    def __init__(self, body, *, url=None, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.url = gdelt.request_url(QUERY) if url is None else url
        self.headers = Message()
        self.headers["Content-Type"] = "application/json; charset=utf-8"
        for key, value in (headers or {}).items():
            if key in self.headers:
                del self.headers[key]
            self.headers[key] = value

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, response):
        self.response, self.calls = response, []

    def open(self, request, *, timeout, limit):
        self.calls.append((request, timeout, limit))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class GdeltResearchTests(unittest.TestCase):
    def parse(self, body):
        return gdelt.parse_metadata(body, query=QUERY, received_at=NOW)

    def assert_code(self, code, callback):
        with self.assertRaises(SourceError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def fetch(self, response):
        opener = Opener(response)
        with patch.object(gdelt, "require_internal_experiment"):
            result = gdelt.discover(QUERY, clock=lambda: NOW, opener=opener)
        return result, opener

    def test_exact_query_pinned_source_contract_has_no_monitoring_authority(self):
        source_id, contract = gdelt.source_contract(QUERY)
        self.assertEqual(source_id, "gdelt-research-" + text_digest(QUERY))
        self.assertEqual(contract, gdelt.contract(source_id, QUERY))
        self.assertFalse(contract["monitoring_authority"])
        self.assertEqual(contract["rights_status"], "internal_metadata_experiment_only")
        row = SimpleNamespace(pk=source_id, contract=contract, contract_digest=text_digest(canonical_json(contract)))
        self.assertTrue(gdelt.matches_source_contract(row))
        for key, value in (("url", "https://private.invalid"), ("max_selected", 50),
                           ("monitoring_authority", True), ("policy_version", "future")):
            changed = dict(contract, **{key: value})
            invalid = SimpleNamespace(pk=source_id, contract=changed, contract_digest=text_digest(canonical_json(changed)))
            self.assertFalse(gdelt.matches_source_contract(invalid))
        with self.assertRaises(ValueError):
            gdelt.contract(source_id, "another query")
        node_id = "research-gdelt-" + "a" * 32 + "-2"
        node_contract = gdelt.contract(node_id, QUERY)
        self.assertEqual(node_contract["id"], node_id)
        self.assertEqual(node_contract["query"], QUERY)
        row = SimpleNamespace(pk=node_id, contract=node_contract,
            contract_digest=text_digest(canonical_json(node_contract)))
        self.assertTrue(gdelt.matches_source_contract(row))
        for node_id in ("arbitrary", "research-gdelt-" + "a" * 32 + "-3",
                        "research-gdelt-" + "a" * 31 + "-0"):
            with self.subTest(node_id=node_id), self.assertRaises(ValueError):
                gdelt.contract(node_id, QUERY)

    def test_metadata_attribution_receipt_and_seen_time_are_distinct(self):
        body = raw(article())
        result = self.parse(body)
        item = result.batch.items[0]
        self.assertEqual(item.title, article()["title"])
        self.assertEqual(item.url, article()["url"])
        self.assertIsNone(item.published_at)
        self.assertEqual(result.batch.received_at, NOW)
        self.assertEqual(result.batch.transport_digest, sha256(body).hexdigest())
        self.assertEqual(json.loads(item.content)["gdelt_seen_at"], "2026-10-17T11:00:00+00:00")
        self.assertEqual(json.loads(item.content)["article_body"], "not_retrieved")
        self.assertFalse(result.metadata["coverage_complete"])
        self.assertIn("GDELT Project", " ".join(result.metadata["limitations"]))

    def test_stable_url_identity_is_distinct_from_changed_payload_and_query(self):
        first = self.parse(raw(article()))
        corrected = self.parse(raw(article(title="Fictional changed headline")))
        other_query = gdelt.parse_metadata(raw(article()), query="a distinct topic", received_at=NOW)
        self.assertEqual(first.batch.items[0].native_id, corrected.batch.items[0].native_id)
        self.assertNotEqual(first.batch.items[0].digest, corrected.batch.items[0].digest)
        self.assertEqual(first.batch.items[0].native_id, other_query.batch.items[0].native_id)
        self.assertNotEqual(gdelt.source_contract(QUERY)[0], gdelt.source_contract("a distinct topic")[0])

    def test_saturation_preserves_all_candidates_and_explicit_fifth_exclusion(self):
        result = self.parse(raw(*(article(index) for index in range(1, 6))))
        self.assertEqual(len(result.batch.items), 4)
        self.assertFalse(result.batch.truncated)
        self.assertTrue(result.metadata["candidate_cap_reached"])
        self.assertEqual(len(result.metadata["candidates"]), 5)
        excluded = result.metadata["candidates"][4]
        self.assertFalse(excluded["selected"])
        self.assertEqual(excluded["exclusion_reason"], "explicit_selection_limit")
        self.assertEqual(excluded["metadata"], article(5))

    def test_empty_result_is_visible_limited_evidence_not_a_negative_finding(self):
        result = self.parse(raw())
        self.assertEqual(result.batch.items, ())
        self.assertEqual(result.metadata["selected_count"], 0)
        self.assertFalse(result.metadata["coverage_complete"])
        self.assertFalse(result.metadata["candidate_cap_reached"])
        self.assertEqual(result.metadata["candidates"], [])

    def test_unsafe_attribution_urls_and_duplicates_are_explicitly_excluded(self):
        for url in ("http://example.invalid/story", "https://127.0.0.1/story", "https://localhost/story",
                    "https://private.internal/story", "https://user:secret@example.invalid/story",
                    "https://example.invalid:8443/story"):
            with self.subTest(url=url):
                result = self.parse(raw(article(url=url)))
                self.assertEqual(result.batch.items, ())
                self.assertEqual(result.metadata["candidates"][0]["exclusion_reason"],
                                 "unsafe_or_non_https_attribution_url")
        duplicate = self.parse(raw(article(), article()))
        self.assertEqual(len(duplicate.batch.items), 1)
        self.assertEqual(duplicate.metadata["candidates"][1]["exclusion_reason"], "duplicate_url_identity")

    def test_no_silent_acceptance_of_malformed_metadata_or_additional_payload(self):
        missing = article()
        del missing["title"]
        for body in (raw(missing), raw(article(extra="uncontracted")), b'{"articles":{}}',
                     b'{"articles":[],"next":"url"}', b'{}', b'[]', raw(article(title=True)),
                     raw(article(title="")), raw(article(title="\ud800")), raw(article(title="x" * 2049))):
            with self.subTest(body=body[:80]):
                self.assert_code("invalid_research_metadata", lambda: self.parse(body))
        for body in (b'{"articles":[],"articles":[]}', b'{"articles":NaN}', b'\xff', b'not json'):
            with self.subTest(body=body[:80]):
                self.assert_code("invalid_json", lambda: self.parse(body))

    def test_invalid_seen_time_and_overlimits_reject_entire_response(self):
        for stamp in ("yesterday", "20261317T110000Z", "20261017", "20261017T110000"):
            with self.subTest(stamp=stamp):
                self.assert_code("invalid_time", lambda: self.parse(raw(article(seendate=stamp))))
        self.assert_code("item_limit", lambda: self.parse(raw(*(article(index) for index in range(6)))))
        self.assert_code("byte_limit", lambda: self.parse(b" " * (gdelt.MAX_BYTES + 1)))

    def test_fixed_request_encodes_query_instead_of_allowing_parameter_injection(self):
        result, opener = self.fetch(Response(raw(article())))
        self.assertEqual(len(opener.calls), 1)
        request, timeout, limit = opener.calls[0]
        self.assertEqual((request.get_method(), timeout, limit), ("GET", 10, gdelt.MAX_BYTES))
        self.assertEqual(request.get_header("Accept-encoding"), "identity")
        self.assertIsNone(request.get_header("Authorization"))
        parsed = urllib.parse.urlsplit(request.full_url)
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path), ("https", "api.gdeltproject.org", "/api/v2/doc/doc"))
        self.assertEqual(urllib.parse.parse_qs(parsed.query), {"query": [QUERY], "mode": ["ArtList"],
            "format": ["json"], "timespan": ["30d"], "sort": ["HybridRel"], "maxrecords": ["5"]})
        injected = urllib.parse.parse_qs(urllib.parse.urlsplit(gdelt.request_url("gas&maxrecords=250")).query)
        self.assertEqual(injected["maxrecords"], ["5"])
        self.assertEqual(injected["query"], ["gas&maxrecords=250"])

    def test_local_experiment_gate_precedes_any_transport(self):
        opener = Opener(Response(raw()))
        with patch.object(gdelt, "require_internal_experiment", side_effect=PermissionError("disabled")):
            with self.assertRaises(PermissionError):
                gdelt.discover(QUERY, opener=opener)
        self.assertEqual(opener.calls, [])

    def test_transport_normalized_query_encoding_retains_same_fixed_target(self):
        from yarl import URL
        query = "(helium OR gas) supply"
        expected = gdelt.request_url(query)
        canonical = str(URL(expected))
        self.assertNotEqual(expected, canonical)
        self.assertTrue(gdelt._same_request_url(canonical, expected))
        for altered in (canonical + "&maxrecords=250", canonical + "#fragment",
                        canonical.replace("api.gdeltproject.org", "private.invalid"),
                        canonical.replace("maxrecords=5", "maxrecords=4")):
            self.assertFalse(gdelt._same_request_url(altered, expected))
        opener = Opener(Response(raw(), url=canonical))
        with patch.object(gdelt, "require_internal_experiment"):
            self.assertEqual(gdelt.discover(query, clock=lambda: NOW, opener=opener).batch.items, ())

    def test_no_redirect_wrong_type_oversize_or_incomplete_response_is_accepted(self):
        cases = ((Response(raw(), url="https://other.invalid"), "invalid_response"),
                 (Response(raw(), status=302), "invalid_response"),
                 (Response(raw(), headers={"Content-Type": "text/html"}), "invalid_response"),
                 (Response(raw(), headers={"Content-Encoding": "gzip"}), "invalid_response"),
                 (Response(raw(), headers={"Content-Length": "-1"}), "invalid_response"),
                 (Response(raw(), headers={"Content-Length": str(gdelt.MAX_BYTES + 1)}), "byte_limit"),
                 (Response(raw(), headers={"Content-Length": "400"}), "incomplete_response"))
        for response, code in cases:
            with self.subTest(code=code):
                self.assert_code(code, lambda: self.fetch(response))

    def test_remote_failures_are_safe_visible_and_never_retried(self):
        cases = [(urllib.error.HTTPError(gdelt.ENDPOINT, status, "secret remote detail", Message(), None), code)
                 for status, code in ((429, "rate_limited"), (503, "unavailable"), (403, "http_error"), (302, "http_error"))]
        cases.extend(((TransportError("timeout"), "transport_error"), (OSError("private path"), "transport_error")))
        for error, code in cases:
            opener = Opener(error)
            with self.subTest(code=code), patch.object(gdelt, "require_internal_experiment"):
                self.assert_code(code, lambda: gdelt.discover(QUERY, opener=opener))
            self.assertEqual(len(opener.calls), 1)


if __name__ == "__main__":
    unittest.main()
