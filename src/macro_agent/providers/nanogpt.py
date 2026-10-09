"""Bounded NanoGPT transport for explicit internal research calls.

The public catalog and completion endpoints deliberately use the same host.
No search, tools, provider overrides, streaming or automatic retries are used.
Catalog prices are hints, not charges; the ordinary completion contract does
not document a final USD charge, so reported_cost_usd remains unknown.

Verified against the official models, chat-completion and model-suffix docs:
https://docs.nano-gpt.com/api-reference/endpoint/models
https://docs.nano-gpt.com/api-reference/endpoint/chat-completion
https://docs.nano-gpt.com/api-reference/miscellaneous/model-suffixes
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
import json
import math
import re
from time import perf_counter
import urllib.error
import urllib.request

from macro_agent.transport.http import BoundedOpener, TransportError


MODELS_URL = "https://nano-gpt.com/api/v1/models?detailed=true"
COMPLETIONS_URL = "https://nano-gpt.com/api/v1/chat/completions"
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = 256 * 1024
MAX_MESSAGE_BYTES = 64 * 1024
MAX_MODELS = 5000
MAX_MESSAGES = 32
MAX_OUTPUT_TOKENS = 8192
MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*(?::(?:thinking|free))?\Z")
FINISH_REASONS = frozenset({"stop", "length", "tool_calls", "function_call", "content_filter"})


class ProviderError(RuntimeError):
    """Safe category and normalized accounting, never provider body or content.

For a failed POST, outcome_unknown means completion or billing may have
occurred. The caller must not silently retry. metadata may preserve reported
usage for rejected/truncated output, but never includes partial model text.
"""

    def __init__(self, code: str, *, metadata: dict | None = None):
        self.code = code
        self.metadata = dict(metadata or {})
        super().__init__(f"Model provider request failed ({code}).")


def is_explicit_model_id(value) -> bool:
    """Allow plain IDs and documented thinking/free identity variants.

Other colon suffixes can trigger search, memory, provider routing or other
optional behavior. Catalog presence is enforced separately by the caller.
"""
    if type(value) is not str or not (1 <= len(value) <= 255):
        return False
    if MODEL_PATTERN.fullmatch(value) is None or "//" in value:
        return False
    base = value.split(":")[0].lower()
    return (base.split("/")[-1] not in ("auto", "fusion", "free")
            and not base.startswith("auto-") and not base.startswith("openrouter/auto"))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous JSON")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON")


def _load_json(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_float=Decimal, parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ProviderError("invalid_response") from None
    if type(value) is not dict:
        raise ProviderError("invalid_response")
    return value


def _integer(value):
    return value if type(value) is int and 0 <= value <= 10**12 else None


def _decimal(value):
    if isinstance(value, bool) or type(value) not in (str, int, Decimal):
        return None
    if type(value) is str and (not value or len(value) > 128):
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number < 0 or number > Decimal("1e10"):
        return None
    # Avoid allocating an enormous fixed-point string from an extreme exponent.
    if number.as_tuple().exponent < -24:
        return None
    return format(number, "f")


def _elapsed(start):
    return max(0, int((perf_counter() - start) * 1000))


class ChatProvider:
    """Shared bounded HTTP and chat parsing; adapters normalize catalog/accounting."""

    models_url = MODELS_URL
    completions_url = COMPLETIONS_URL
    catalog_requires_key = False
    request_id_headers = ("X-Request-ID",)
    extra_headers = {}

    def __init__(self, api_key: str, *, timeout_seconds=45, max_output_tokens=3000):
        if type(api_key) is not str or len(api_key) > 4096 or any(
                character.isspace() or not 32 <= ord(character) <= 126 for character in api_key):
            raise ProviderError("invalid_configuration")
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not (
                1 <= timeout_seconds <= 120):
            raise ProviderError("invalid_configuration")
        if type(max_output_tokens) is not int or not (1 <= max_output_tokens <= MAX_OUTPUT_TOKENS):
            raise ProviderError("invalid_configuration")
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self._opener = BoundedOpener()

    def _identifier(self, value, limit=512):
        if (type(value) is not str or not value or len(value) > limit
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
                or (self._api_key and self._api_key in value)):
            return None
        try:
            value.encode("utf-8")
        except UnicodeError:
            return None
        return value

    def _request(self, url, *, body=None, limit, timeout_seconds=None):
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        method = "GET" if body is None else "POST"
        if body is not None:
            headers.update({"Content-Type": "application/json", "Authorization": "Bearer " + self._api_key})
        elif self.catalog_requires_key:
            if not self._api_key:
                raise ProviderError("authentication")
            headers["Authorization"] = "Bearer " + self._api_key
        headers.update(self.extra_headers)
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        metadata = {}
        try:
            with self._opener.open(request,
                    timeout=self.timeout_seconds if timeout_seconds is None else timeout_seconds,
                    limit=limit) as response:
                metadata["provider_request_id"] = next((self._identifier(response.headers.get(name))
                    for name in self.request_id_headers if response.headers.get(name)), None)
                if response.geturl() != url or response.status != 200:
                    raise ProviderError("invalid_response", metadata=metadata)
                encoding = response.headers.get("Content-Encoding", "identity")
                if encoding.lower() not in ("", "identity"):
                    raise ProviderError("invalid_response", metadata=metadata)
                length = response.headers.get("Content-Length")
                if length is not None:
                    try:
                        expected = int(length)
                    except (ValueError, TypeError):
                        raise ProviderError("invalid_response", metadata=metadata) from None
                    if not 0 <= expected <= limit:
                        raise ProviderError("invalid_response", metadata=metadata)
                raw = response.read(limit + 1)
                if len(raw) > limit or (length is not None and len(raw) != expected):
                    raise ProviderError("invalid_response", metadata=metadata)
                try:
                    parsed = _load_json(raw)
                except ProviderError as error:
                    raise ProviderError(error.code, metadata=metadata) from None
                return parsed, metadata
        except TransportError as error:
            metadata["provider_request_id"] = next((self._identifier(error.headers.get(name))
                for name in self.request_id_headers if error.headers.get(name)), None)
            if error.code in ("timeout", "unavailable", "incomplete_response"):
                code = "outcome_unknown" if body is not None else (
                    "timeout" if error.code == "timeout" else "unavailable")
            else:
                code = "invalid_response"
            raise ProviderError(code, metadata=metadata) from None
        except urllib.error.HTTPError as error:
            # Do not read or surface an error body: it may echo credentials,
            # thesis text, provider internals or arbitrary remote instructions.
            code = {400: "invalid_request", 401: "authentication", 402: "payment_required",
                    403: "authentication", 429: "rate_limited"}.get(error.code)
            code = code or ("invalid_response" if 300 <= error.code < 400 else "unavailable")
            request_id = next((self._identifier(error.headers.get(name))
                for name in self.request_id_headers if error.headers.get(name)), None) if error.headers else None
            error.close()
            raise ProviderError(code, metadata={"provider_request_id": request_id}) from None
        except TimeoutError:
            code = "outcome_unknown" if body is not None else "timeout"
            raise ProviderError(code, metadata=metadata) from None
        except urllib.error.URLError as error:
            code = "outcome_unknown" if body is not None else (
                "timeout" if isinstance(error.reason, TimeoutError) else "unavailable")
            raise ProviderError(code, metadata=metadata) from None
        except (OSError, HTTPException):
            code = "outcome_unknown" if body is not None else "unavailable"
            raise ProviderError(code, metadata=metadata) from None

    def list_models(self) -> dict:
        """Fetch advertised metadata; only authenticated catalogs receive a key."""
        value, _ = self._request(self.models_url, limit=MAX_CATALOG_BYTES,
                                 timeout_seconds=min(self.timeout_seconds, 10))
        entries = value.get("data")
        if type(entries) is not list or not (1 <= len(entries) <= MAX_MODELS):
            raise ProviderError("invalid_response")
        models, seen = [], set()
        for entry in entries:
            if type(entry) is not dict:
                raise ProviderError("invalid_response")
            model_id = self._identifier(entry.get("id"), 255)
            if model_id is None or model_id in seen:
                raise ProviderError("invalid_response")
            seen.add(model_id)
            name = self._identifier(entry.get("name"), 512) or model_id
            prompt_price, completion_price = self._prices(entry)
            capabilities = self._capabilities(entry)
            context = _integer(entry.get("context_length"))
            models.append({"id": model_id, "name": name, "context_length": context if context else None,
                           "input_price_usd_per_million": prompt_price,
                           "output_price_usd_per_million": completion_price, "capabilities": capabilities})
        return {"models": models, "fetched_at": datetime.now(timezone.utc).isoformat()}

    def _prices(self, entry):
        return None, None

    def _capabilities(self, entry):
        raw = entry.get("capabilities")
        return {key: flag for key, flag in raw.items()
                if type(key) is str and len(key) <= 128 and type(flag) is bool} if type(raw) is dict else {}

    def _reported_cost(self, response):
        return None

    def complete(self, model_id: str, messages: list[dict]) -> dict:
        """Make one bounded call; reject incomplete output without a retry."""
        if not self._api_key:
            raise ProviderError("authentication")
        if not is_explicit_model_id(model_id) or type(messages) is not list or not (1 <= len(messages) <= MAX_MESSAGES):
            raise ProviderError("invalid_request")
        for message in messages:
            if (type(message) is not dict or set(message) != {"role", "content"}
                    or type(message["role"]) is not str or message["role"] not in ("system", "user", "assistant")
                    or type(message["content"]) is not str or not message["content"]):
                raise ProviderError("invalid_request")
            try:
                if len(message["content"].encode("utf-8")) > MAX_MESSAGE_BYTES:
                    raise ProviderError("invalid_request")
            except UnicodeError:
                raise ProviderError("invalid_request") from None
        body = json.dumps({"model": model_id, "messages": messages, "stream": False,
                           "max_tokens": self.max_output_tokens}, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            raise ProviderError("invalid_request")
        start = perf_counter()
        try:
            response, metadata = self._request(self.completions_url, body=body, limit=MAX_RESPONSE_BYTES)
        except ProviderError as error:
            metadata = {**error.metadata, "latency_ms": _elapsed(start)}
            raise ProviderError(error.code, metadata=metadata) from None
        raw_usage = response.get("usage")
        usage = {name: _integer(raw_usage.get(name)) if type(raw_usage) is dict else None
                 for name in ("prompt_tokens", "completion_tokens", "total_tokens")}
        metadata.update({"reported_model": self._identifier(response.get("model"), 255),
                         "usage": usage, "reported_cost_usd": self._reported_cost(response), "finish_reason": None,
                         "latency_ms": _elapsed(start)})
        choices = response.get("choices")
        if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
            raise ProviderError("invalid_response", metadata=metadata)
        choice = choices[0]
        reason = choice.get("finish_reason")
        metadata["finish_reason"] = reason if type(reason) is str and reason in FINISH_REASONS else None
        if reason != "stop":
            raise ProviderError("truncated_response" if reason == "length" else "invalid_response", metadata=metadata)
        message = choice.get("message")
        if (type(message) is not dict or message.get("role") != "assistant"
                or message.get("tool_calls") or message.get("function_call") or message.get("refusal")):
            raise ProviderError("invalid_response", metadata=metadata)
        content = message.get("content")
        if (type(content) is not str or not content.strip()
                or self._api_key in content):
            raise ProviderError("invalid_response", metadata=metadata)
        try:
            content.encode("utf-8")
        except UnicodeError:
            raise ProviderError("invalid_response", metadata=metadata) from None
        return {"content": content, **metadata}


class NanoGPT(ChatProvider):
    def _prices(self, entry):
        pricing = entry.get("pricing")
        if (type(pricing) is dict and pricing.get("currency") == "USD"
                and pricing.get("unit") == "per_million_tokens"):
            return _decimal(pricing.get("prompt")), _decimal(pricing.get("completion"))
        return None, None
