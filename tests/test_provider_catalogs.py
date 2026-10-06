"""The same selection contract with different router units and auth policies."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from macro_agent.providers import create_provider, ProviderError, is_explicit_model_id
from test_nanogpt import Response, completion, KEY, MODEL, MESSAGES


class Opener:
    def __init__(self, body, url, headers=None):
        self.response = Response(body, url=url, headers=headers)
        self.requests = []

    def open(self, request, **kwargs):
        self.requests.append(request)
        return self.response


class RouterCatalogTests(unittest.TestCase):
    def catalog(self, provider_id, entry):
        adapter = create_provider(provider_id, KEY)
        opener = Opener({"data": [entry]}, adapter.models_url)
        adapter._opener = opener
        result = adapter.list_models()
        return result["models"][0], opener.requests[0]

    def test_openrouter_rates_convert_per_token_and_catalog_has_no_key(self):
        model, request = self.catalog("openrouter", {"id": MODEL, "name": "Example",
            "pricing": {"prompt": "0.0000001", "completion": "0.0000002"},
            "architecture": {"output_modalities": ["text"]},
            "supported_parameters": ["response_format"]})
        self.assertEqual(model["input_price_usd_per_million"], "0.1000000")
        self.assertEqual(model["output_price_usd_per_million"], "0.2000000")
        self.assertTrue(model["capabilities"]["chat_completions"])
        self.assertIsNone(request.get_header("Authorization"))

    def test_cheaper_rates_already_per_million_with_matching_key(self):
        model, request = self.catalog("cheaperinference", {"id": MODEL,
            "pricing": {"currency": "USD", "input_per_million": "0.1", "output_per_million": "0.2"},
            "endpoint": "/v1/responses", "supported_endpoints": ["/v1/chat/completions", "/v1/responses"]})
        self.assertEqual(model["input_price_usd_per_million"], "0.1")
        self.assertTrue(model["capabilities"]["chat_completions"])
        self.assertEqual(request.get_header("Authorization"), "Bearer " + KEY)

    def test_unknown_rates_and_media_are_not_invented_as_free_chat(self):
        for provider in ("nanogpt", "openrouter", "cheaperinference"):
            with self.subTest(provider=provider):
                model, _ = self.catalog(provider, {"id": MODEL, "type": "image",
                    "endpoint": "/v1/images/generations", "architecture": {"output_modalities": ["image"]},
                    "pricing": {"prompt": "NaN", "completion": True}})
                self.assertIsNone(model["input_price_usd_per_million"])
                self.assertIsNone(model["output_price_usd_per_million"])
                if provider != "nanogpt":
                    self.assertFalse(model["capabilities"]["chat_completions"])

    def test_completion_pins_each_router_and_normalizes_reported_charge(self):
        for provider in ("nanogpt", "openrouter", "cheaperinference"):
            with self.subTest(provider=provider):
                adapter = create_provider(provider, KEY)
                response = completion()
                response["usage"]["cost"] = 0.001
                response["cheaper_inference"] = {"billing": {"status": "settled",
                    "currency": "USD", "billed_cost_usd": "0.0009"}}
                opener = Opener(response, adapter.completions_url,
                    headers={"x-ci-request-id": "ci-request", "X-Request-ID": "request"})
                adapter._opener = opener
                result = adapter.complete(MODEL, MESSAGES)
                payload = json.loads(opener.requests[0].data)
                self.assertEqual(payload["model"], MODEL)
                self.assertEqual(payload["messages"], MESSAGES)
                self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer " + KEY)
                self.assertEqual(len(opener.requests), 1)
                self.assertEqual(result["reported_cost_usd"], {"nanogpt": None,
                    "openrouter": "0.001", "cheaperinference": "0.0009"}[provider])

    def test_unsettled_cheaper_charge_remains_unknown(self):
        adapter = create_provider("cheaperinference", KEY)
        value = completion(cheaper_inference={"billing": {"status": "pending",
            "currency": "USD", "billed_cost_usd": "0.002"}})
        adapter._opener = Opener(value, adapter.completions_url)
        self.assertIsNone(adapter.complete(MODEL, MESSAGES)["reported_cost_usd"])

    def test_missing_cheaper_key_and_unknown_provider_fail_before_dispatch(self):
        with self.assertRaises(ProviderError):
            create_provider("cheaperinference", "").list_models()
        with self.assertRaises(ProviderError):
            create_provider("unreviewed-host", KEY)
        self.assertTrue(is_explicit_model_id("qwen/example:free"))
        for model in ("openrouter/auto", "openrouter/fusion", "openrouter/free", "qwen/example:online"):
            self.assertFalse(is_explicit_model_id(model))


if __name__ == "__main__":
    unittest.main()
