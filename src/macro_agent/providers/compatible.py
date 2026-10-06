"""Fixed router adapters behind the same catalog and completion contract.

Rates are normalized only using documented units. These adapters do not select
another model, rewrite prompts or opt into experiments, search or tools.
"""

from decimal import Decimal

from .nanogpt import ChatProvider, _decimal


class OpenRouter(ChatProvider):
    models_url = "https://openrouter.ai/api/v1/models"
    completions_url = "https://openrouter.ai/api/v1/chat/completions"

    def _prices(self, entry):
        pricing = entry.get("pricing")
        if type(pricing) is not dict:
            return None, None
        # https://openrouter.ai/docs/api/api-reference/models/get-models
        return tuple(str(Decimal(rate) * 1_000_000) if rate is not None else None
                     for rate in (_decimal(pricing.get("prompt")), _decimal(pricing.get("completion"))))

    def _capabilities(self, entry):
        architecture = entry.get("architecture")
        outputs = architecture.get("output_modalities") if type(architecture) is dict else None
        parameters = entry.get("supported_parameters")
        result = {"chat_completions": "text" in outputs} if type(outputs) is list else {}
        if type(parameters) is list:
            result.update({"tools": "tools" in parameters,
                           "structured_output": "response_format" in parameters})
        return result

    def _reported_cost(self, response):
        usage = response.get("usage")
        return _decimal(usage.get("cost")) if type(usage) is dict else None


class CheaperInference(ChatProvider):
    models_url = "https://api.cheaperinference.com/v1/models"
    completions_url = "https://api.cheaperinference.com/v1/chat/completions"
    catalog_requires_key = True
    request_id_headers = ("x-ci-request-id", "X-Cheaper-Inference-Request-Id")

    def _prices(self, entry):
        pricing = entry.get("pricing")
        if type(pricing) is dict and pricing.get("currency") == "USD":
            return (_decimal(pricing.get("input_per_million")),
                    _decimal(pricing.get("output_per_million")))
        return None, None

    def _capabilities(self, entry):
        result = super()._capabilities(entry)
        endpoints = entry.get("supported_endpoints")
        endpoint = entry.get("endpoint")
        if type(endpoints) is list:
            result["chat_completions"] = any(value in endpoints
                for value in ("/v1/chat/completions", "/chat/completions"))
        elif type(endpoint) is str:
            result["chat_completions"] = endpoint in ("/v1/chat/completions", "/chat/completions")
        elif entry.get("type") in ("image", "video", "audio", "embedding"):
            result["chat_completions"] = False
        return result

    def _reported_cost(self, response):
        ledger = response.get("cheaper_inference")
        billing = ledger.get("billing") if type(ledger) is dict else None
        if (type(billing) is dict and billing.get("status") == "settled"
                and billing.get("currency") == "USD"):
            return _decimal(billing.get("billed_cost_usd"))
        return None
