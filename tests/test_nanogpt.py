"""Fake HTTP transport proves bounded explicit dispatch without credentials."""

from email.message import Message
from http.client import IncompleteRead
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from macro_agent.providers import NanoGPT, ProviderError, is_explicit_model_id
from macro_agent.providers import nanogpt


KEY = "test-only-key-never-a-real-credential"
MODEL = "example/research-small"
MESSAGES = [{"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "  Gold thesis.\r\nΔ\r\n"}]


def completion(**changes):
    value = {"model": MODEL, "id": "completion-id-not-a-billing-request-id", "choices": [{
        "index": 0, "message": {"role": "assistant", "content": '{"summary":"example"}'},
        "finish_reason": "stop"}], "usage": {"prompt_tokens": 32, "completion_tokens": 16, "total_tokens": 48}}
    value.update(changes)
    return value


class Response:
    def __init__(self, body, *, url=nanogpt.COMPLETIONS_URL, headers=None, status=200):
        self.body = body if type(body) is bytes else json.dumps(body).encode()
        self.url, self.status = url, status
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value
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
        return self.body[:size]


class FakeOpener:
    def __init__(self, result):
        self.result, self.calls, self.limits = result, [], []

    def open(self, request, *, timeout, limit):
        self.calls.append((request, timeout))
        self.limits.append(limit)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def configured(result, **options):
    fake = FakeOpener(result)
    with patch.object(nanogpt, "BoundedOpener", return_value=fake) as builder:
        provider = NanoGPT(KEY, **options)
    return provider, fake, builder


class NanoGPTTests(unittest.TestCase):
    def test_catalog_is_public_fixed_host_and_preserves_explicit_units(self):
        response = Response({"data": [{"id": MODEL, "name": "Research Small", "context_length": 8192,
            "capabilities": {"structured_output": True, "reasoning": False, "unsupported_shape": []},
            "pricing": {"prompt": 0.25, "completion": "0.75", "unit": "per_million_tokens", "currency": "USD"}},
            {"id": "example/other"}]}, url=nanogpt.MODELS_URL)
        provider, fake, _ = configured(response)
        result = provider.list_models()
        self.assertEqual(result["models"][0], {"id": MODEL, "name": "Research Small", "context_length": 8192,
            "input_price_usd_per_million": "0.25", "output_price_usd_per_million": "0.75",
            "capabilities": {"structured_output": True, "reasoning": False}})
        self.assertEqual(result["models"][1]["name"], "example/other")
        self.assertIsNone(result["models"][1]["input_price_usd_per_million"])
        self.assertTrue(result["fetched_at"].endswith("+00:00"))
        request, timeout = fake.calls[0]
        self.assertEqual((request.full_url, request.method, timeout), (nanogpt.MODELS_URL, "GET", 10))
        self.assertNotIn("Authorization", dict(request.header_items()))
        self.assertEqual(response.read_sizes, [nanogpt.MAX_CATALOG_BYTES + 1])
        self.assertTrue(response.closed)
        self.assertEqual(fake.limits, [nanogpt.MAX_CATALOG_BYTES])

    def test_unknown_or_incompatible_price_units_are_never_guessed(self):
        cases = [{"prompt": 0.1, "completion": 0.2},
                 {"prompt": 0.1, "completion": 0.2, "currency": "USD", "unit": "per_token"},
                 {"prompt": 0.1, "completion": 0.2, "currency": "EUR", "unit": "per_million_tokens"},
                 {"prompt": "NaN", "completion": -1, "currency": "USD", "unit": "per_million_tokens"}]
        for pricing in cases:
            with self.subTest(pricing=pricing):
                provider, _, _ = configured(Response({"data": [{"id": MODEL, "pricing": pricing}]}, url=nanogpt.MODELS_URL))
                model = provider.list_models()["models"][0]
                self.assertIsNone(model["input_price_usd_per_million"])
                self.assertIsNone(model["output_price_usd_per_million"])

    def test_catalog_rejects_duplicates_and_malformed_identity(self):
        for body in ({"data": [{"id": MODEL}, {"id": MODEL}]}, {"data": [{"id": None}]}, {"data": []}, {"data": {}}):
            with self.subTest(body=body):
                provider, _, _ = configured(Response(body, url=nanogpt.MODELS_URL))
                with self.assertRaises(ProviderError) as error:
                    provider.list_models()
                self.assertEqual(error.exception.code, "invalid_response")

    def test_completion_sends_only_bounded_explicit_payload_and_exact_messages(self):
        response = Response(completion(), headers={"X-Request-ID": "request-accounting-id"})
        provider, fake, _ = configured(response, max_output_tokens=777, timeout_seconds=20)
        result = provider.complete(MODEL, MESSAGES)
        request, timeout = fake.calls[0]
        self.assertEqual((request.full_url, request.method, timeout), (nanogpt.COMPLETIONS_URL, "POST", 20))
        self.assertEqual(json.loads(request.data), {"model": MODEL, "messages": MESSAGES, "stream": False, "max_tokens": 777})
        self.assertEqual(request.get_header("Authorization"), "Bearer " + KEY)
        self.assertEqual(result["provider_request_id"], "request-accounting-id")
        self.assertEqual(result["reported_model"], MODEL)
        self.assertEqual(result["usage"], {"prompt_tokens": 32, "completion_tokens": 16, "total_tokens": 48})
        self.assertIsNone(result["reported_cost_usd"])
        self.assertEqual(result["finish_reason"], "stop")
        self.assertGreaterEqual(result["latency_ms"], 0)
        self.assertEqual(len(fake.calls), 1)

    def test_reported_model_is_retained_separately_from_chosen_request_id(self):
        provider, fake, _ = configured(Response(completion(model="example/research-small-2026")))
        result = provider.complete(MODEL, MESSAGES)
        self.assertEqual(json.loads(fake.calls[0][0].data)["model"], MODEL)
        self.assertEqual(result["reported_model"], "example/research-small-2026")
        self.assertIsNone(result["provider_request_id"])

    def test_missing_and_malformed_accounting_stays_unknown(self):
        provider, _, _ = configured(Response(completion(usage={"prompt_tokens": True, "completion_tokens": -1,
                "total_tokens": "48"}, cost_usd="0.0001")))
        result = provider.complete(MODEL, MESSAGES)
        self.assertEqual(result["usage"], {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None})
        self.assertIsNone(result["reported_cost_usd"])

    def test_length_failure_preserves_usage_but_never_partial_output_or_retry(self):
        body = completion()
        body["choices"][0]["finish_reason"] = "length"
        body["choices"][0]["message"]["content"] = '{"private partial'
        provider, fake, _ = configured(Response(body, headers={"X-Request-ID": "billed-request"}))
        with self.assertRaises(ProviderError) as raised:
            provider.complete(MODEL, MESSAGES)
        error = raised.exception
        self.assertEqual(error.code, "truncated_response")
        self.assertEqual(error.metadata["usage"]["total_tokens"], 48)
        self.assertEqual(error.metadata["provider_request_id"], "billed-request")
        self.assertEqual(error.metadata["finish_reason"], "length")
        self.assertNotIn("content", error.metadata)
        self.assertNotIn("private partial", str(error))
        self.assertEqual(len(fake.calls), 1)

    def test_missing_or_other_finish_reason_is_not_accepted_as_completion(self):
        for reason in (None, "tool_calls", "content_filter", "unexpected", ["stop"]):
            with self.subTest(reason=reason):
                body = completion()
                body["choices"][0]["finish_reason"] = reason
                provider, _, _ = configured(Response(body))
                with self.assertRaises(ProviderError) as error:
                    provider.complete(MODEL, MESSAGES)
                self.assertEqual(error.exception.code, "invalid_response")

    def test_malformed_choices_tool_calls_refusal_and_empty_content_are_rejected(self):
        responses = [completion(choices=[]), completion(choices=[{}, {}])]
        for fields in ({"tool_calls": [{"id": "tool"}]}, {"refusal": "blocked"}, {"content": []},
                       {"content": "   "}, {"content": "\ud800"}, {"role": "user"}):
            body = completion()
            body["choices"][0]["message"].update(fields)
            responses.append(body)
        for body in responses:
            with self.subTest(body=body):
                provider, _, _ = configured(Response(body))
                with self.assertRaises(ProviderError):
                    provider.complete(MODEL, MESSAGES)

    def test_model_suffixes_and_auto_routing_cannot_enable_optional_services(self):
        for model in ("auto", "openrouter/auto", "auto-fast", MODEL + ":online", MODEL + ":cheap",
                      MODEL + ":cerebras", MODEL + ":memory", MODEL + ":tools", MODEL + ":thinking:online",
                      MODEL + "?search=true", "https://other.example/model", "example//model"):
            with self.subTest(model=model):
                self.assertFalse(is_explicit_model_id(model))
                provider, fake, _ = configured(Response(completion()))
                with self.assertRaises(ProviderError) as error:
                    provider.complete(model, MESSAGES)
                self.assertEqual(error.exception.code, "invalid_request")
                self.assertEqual(fake.calls, [])
        self.assertTrue(is_explicit_model_id(MODEL + ":thinking"))

    def test_provider_uses_shared_bounded_transport(self):
        provider, fake, builder = configured(Response(completion()))
        provider.complete(MODEL, MESSAGES)
        builder.assert_called_once_with()
        self.assertEqual(fake.limits, [nanogpt.MAX_RESPONSE_BYTES])

    def test_redirect_or_wrong_origin_response_is_rejected_once(self):
        for result in (Response(completion(), url="https://other.example"),
                       urllib.error.HTTPError(nanogpt.COMPLETIONS_URL, 302, KEY, {}, io.BytesIO(KEY.encode()))):
            with self.subTest(result=type(result).__name__):
                provider, fake, _ = configured(result)
                with self.assertRaises(ProviderError) as error:
                    provider.complete(MODEL, MESSAGES)
                self.assertEqual(error.exception.code, "invalid_response")
                self.assertNotIn(KEY, str(error.exception))
                self.assertEqual(len(fake.calls), 1)

    def test_http_errors_are_safe_categories_and_never_read_body_or_retry(self):
        for status, code in ((400, "invalid_request"), (401, "authentication"), (402, "payment_required"),
                             (403, "authentication"), (429, "rate_limited"), (500, "unavailable"), (503, "unavailable")):
            with self.subTest(status=status):
                body = io.BytesIO((KEY + " private thesis body").encode())
                headers = Message()
                headers["X-Request-ID"] = KEY
                remote = urllib.error.HTTPError(nanogpt.COMPLETIONS_URL, status, KEY, headers, body)
                provider, fake, _ = configured(remote)
                with self.assertRaises(ProviderError) as raised:
                    provider.complete(MODEL, MESSAGES)
                error = raised.exception
                self.assertEqual(error.code, code)
                self.assertNotIn(KEY, str(error))
                self.assertIsNone(error.metadata["provider_request_id"])
                self.assertTrue(body.closed)
                self.assertEqual(len(fake.calls), 1)

    def test_post_disconnect_or_timeout_is_ambiguous_without_retry(self):
        for remote in (TimeoutError(KEY), urllib.error.URLError(TimeoutError(KEY)),
                       OSError(KEY), IncompleteRead(KEY.encode(), 200)):
            with self.subTest(remote=type(remote).__name__):
                provider, fake, _ = configured(remote)
                with self.assertRaises(ProviderError) as raised:
                    provider.complete(MODEL, MESSAGES)
                self.assertEqual(raised.exception.code, "outcome_unknown")
                self.assertNotIn(KEY, str(raised.exception))
                self.assertEqual(len(fake.calls), 1)

    def test_catalog_timeout_has_no_inference_outcome_ambiguity(self):
        provider, _, _ = configured(TimeoutError(KEY))
        with self.assertRaises(ProviderError) as raised:
            provider.list_models()
        self.assertEqual(raised.exception.code, "timeout")

    def test_response_bound_header_and_read_limit_reject_oversize_or_bad_length(self):
        for response in (Response(completion(), headers={"Content-Length": str(nanogpt.MAX_RESPONSE_BYTES + 1)}),
                         Response(b"x" * (nanogpt.MAX_RESPONSE_BYTES + 1)),
                         Response(completion(), headers={"Content-Length": "-1"}),
                         Response(completion(), headers={"Content-Length": "1"}),
                         Response(completion(), headers={"Content-Encoding": "gzip"})):
            with self.subTest(headers=list(response.headers.items())):
                provider, _, _ = configured(response)
                with self.assertRaises(ProviderError):
                    provider.complete(MODEL, MESSAGES)
                self.assertTrue(response.closed)
                self.assertTrue(all(size <= nanogpt.MAX_RESPONSE_BYTES + 1 for size in response.read_sizes))

    def test_invalid_json_duplicates_non_finite_and_invalid_utf8_are_rejected(self):
        for body in (b'{"choices":[],"choices":[]}', b'{"usage": NaN}', b'{', b'[]', b'\xff'):
            with self.subTest(body=body):
                provider, _, _ = configured(Response(body, headers={"X-Request-ID": "known-request"}))
                with self.assertRaises(ProviderError) as error:
                    provider.complete(MODEL, MESSAGES)
                self.assertEqual(error.exception.code, "invalid_response")
                self.assertEqual(error.exception.metadata["provider_request_id"], "known-request")

    def test_provider_key_echo_is_rejected_without_secret_metadata(self):
        body = completion(model=KEY)
        body["choices"][0]["message"]["content"] = "echo " + KEY
        provider, _, _ = configured(Response(body, headers={"X-Request-ID": KEY}))
        with self.assertRaises(ProviderError) as raised:
            provider.complete(MODEL, MESSAGES)
        self.assertNotIn(KEY, repr(raised.exception.metadata))
        self.assertNotIn(KEY, str(raised.exception))

    def test_invalid_messages_are_rejected_before_http(self):
        cases = [[], "messages", [{"role": "user", "content": "x", "tools": []}],
                 [{"role": "tool", "content": "x"}], [{"role": "user", "content": ""}],
                 [{"role": "user", "content": ["x"]}], [{"role": "user", "content": "\ud800"}],
                 [{"role": "user", "content": "x" * (nanogpt.MAX_MESSAGE_BYTES + 1)}],
                 [{"role": "user", "content": "x"}] * (nanogpt.MAX_MESSAGES + 1),
                 [{"role": "user", "content": "x" * nanogpt.MAX_MESSAGE_BYTES}] * 5]
        for messages in cases:
            with self.subTest(kind=type(messages).__name__):
                provider, fake, _ = configured(Response(completion()))
                with self.assertRaises(ProviderError) as raised:
                    provider.complete(MODEL, messages)
                self.assertEqual(raised.exception.code, "invalid_request")
                self.assertEqual(fake.calls, [])

    def test_empty_key_allows_public_catalog_but_never_inference(self):
        response = Response({"data": [{"id": MODEL}]}, url=nanogpt.MODELS_URL)
        with patch.object(nanogpt, "BoundedOpener", return_value=FakeOpener(response)):
            provider = NanoGPT("")
        self.assertEqual(provider.list_models()["models"][0]["id"], MODEL)
        with self.assertRaises(ProviderError) as raised:
            provider.complete(MODEL, MESSAGES)
        self.assertEqual(raised.exception.code, "authentication")

    def test_configuration_bounds_reject_ambiguous_key_and_limits(self):
        for key, options in (("contains\nnewline", {}), (" contains-space", {}), ("contains\0control", {}),
                             (KEY, {"timeout_seconds": True}),
                             (KEY, {"timeout_seconds": float("inf")}), (KEY, {"timeout_seconds": 121}),
                             (KEY, {"max_output_tokens": True}), (KEY, {"max_output_tokens": 0}),
                             (KEY, {"max_output_tokens": nanogpt.MAX_OUTPUT_TOKENS + 1})):
            with self.subTest(options=options), self.assertRaises(ProviderError):
                NanoGPT(key, **options)


if __name__ == "__main__":
    unittest.main()
