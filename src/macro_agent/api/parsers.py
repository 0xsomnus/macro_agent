"""Bounded, unambiguous JSON requests without text normalization."""

import json
import math

from django.utils.http import parse_header_parameters
from rest_framework.exceptions import ParseError, UnsupportedMediaType
from rest_framework.parsers import BaseParser


MAX_BODY_BYTES = 128 * 1024
MAX_JSON_DEPTH = 16
MAX_JSON_VALUES = 2048


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not accepted.")
        result[key] = value
    return result


def _finite_constant(value):
    raise ValueError("Nonfinite JSON numbers are not accepted.")


def _validate_strings(value, depth=0, budget=None):
    if budget is None:
        budget = [MAX_JSON_VALUES]
    budget[0] -= 1
    if budget[0] < 0 or depth > MAX_JSON_DEPTH:
        raise ValueError("JSON structure exceeds the request limit.")
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("NUL is not accepted in JSON strings.")
        value.encode("utf-8", errors="strict")
    elif isinstance(value, dict):
        for key, child in value.items():
            _validate_strings(key, depth + 1, budget)
            _validate_strings(child, depth + 1, budget)
    elif isinstance(value, list):
        for child in value:
            _validate_strings(child, depth + 1, budget)
    elif type(value) is float and not math.isfinite(value):
        raise ValueError("Nonfinite JSON numbers are not accepted.")


def decode_json_body(body):
    """Shared decoder for DRF requests and ordinary Django session views."""
    if len(body) > MAX_BODY_BYTES:
        raise ParseError("JSON body exceeds the 128 KiB limit.")
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_finite_constant,
        )
        _validate_strings(value)
        if type(value) is not dict:
            raise ValueError("The request must be a JSON object.")
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        # Do not include decoded request text, credentials, or parser excerpts.
        raise ParseError("Invalid JSON object.") from None
    return value


def require_json_content_type(request):
    content_type, parameters = parse_header_parameters(request.META.get("CONTENT_TYPE", ""))
    charset = parameters.get("charset", "utf-8")
    if content_type.lower() != "application/json" or charset.lower() not in ("utf-8", "utf8"):
        raise UnsupportedMediaType("application/json", detail="Only UTF-8 application/json is accepted.")


class StrictJSONParser(BaseParser):
    media_type = "application/json"

    def parse(self, stream, media_type=None, parser_context=None):
        request = (parser_context or {}).get("request")
        if request is not None:
            require_json_content_type(request)
        return decode_json_body(stream.read(MAX_BODY_BYTES + 1))
