"""One internal, metadata-only GDELT investigation lookup, never a watcher.

Official API and dataset terms checked 2026-10-17:
https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
https://gdeltproject.org/about.html#termsofuse

Dataset terms require GDELT attribution. They do not establish processing or
redistribution rights for linked publishers' articles. This adapter retrieves
only the DOC ArtList metadata response and never follows article/image URLs.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from http.client import HTTPException
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.domain.research_plan import validate_query
from macro_agent.transport.http import BoundedOpener, TransportError

from .sources import SourceBatch, SourceError, SourceItem, _utc
from . import research_policy


ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
ADAPTER_VERSION = "gdelt-research-metadata-v1"
POLICY_VERSION = "gdelt-internal-metadata-2026-10-17-v1"
RECOVERY_POLICY_VERSION = "gdelt-internal-metadata-2026-10-20-v2"
RECOVERY_ADAPTER_VERSION = "gdelt-research-metadata-v2"
MAX_CANDIDATES = 5
MAX_SELECTED = 4
MAX_BYTES = 65_536
TIMEOUT_SECONDS = 10
TIMESPAN = "30d"
_FIELDS = frozenset(("url", "url_mobile", "title", "seendate", "socialimage", "domain",
                     "language", "sourcecountry"))
_REQUIRED = frozenset(("url", "title", "seendate", "domain", "language", "sourcecountry"))
LIMITATIONS = (
    "GDELT DOC headline metadata only; linked article bodies were not retrieved.",
    "Search ranking and bounded results do not establish complete or suitable research coverage.",
    "Headlines and automated metadata are attributed claims, not verified facts or causal support.",
    "GDELT seen time is not publisher publication time or first public availability.",
    "Prices, consensus, instrument availability and company-specific exposure remain unverified.",
    "The GDELT Project: https://www.gdeltproject.org/",
)


@dataclass(frozen=True)
class ResearchSearchResult:
    batch: SourceBatch
    metadata: dict


def _now():
    return datetime.now(timezone.utc)


def require_internal_experiment():
    """An explicit local development gate, not production source permission."""
    from django.conf import settings
    if not settings.configured:
        raise PermissionError("Internal research discovery is unavailable")
    name = settings.DATABASES["default"]["NAME"]
    if (getattr(settings, "SETTINGS_MODULE", None) != "macro_agent.web.local_settings"
            or not getattr(settings, "MACRO_ENABLE_RESEARCH_DISCOVERY", False)
            or not (name.endswith("_dev") or name.startswith("test_"))):
        raise PermissionError("Internal research discovery is unavailable")


def _policy(policy_version):
    if type(policy_version) is not str or policy_version not in (POLICY_VERSION, RECOVERY_POLICY_VERSION):
        raise ValueError("unknown GDELT research policy")
    return policy_version


def source_contract(query, *, policy_version=POLICY_VERSION):
    """Pin the query and selection/rights policy before transport admission."""
    validate_query(query)
    _policy(policy_version)
    prefix = "gdelt-research-" if policy_version == POLICY_VERSION else "gdelt-research-v2-"
    identity = prefix + text_digest(query)
    return identity, contract(identity, query, policy_version=policy_version)


def contract(source_id, query, *, policy_version=POLICY_VERSION):
    validate_query(query)
    _policy(policy_version)
    legacy = policy_version == POLICY_VERSION
    expected = ("gdelt-research-" if legacy else "gdelt-research-v2-") + text_digest(query)
    # A durable application run may own a separate capture node even when
    # another private run searches the same query. Ownership is enforced by the
    # application; this adapter recognizes only the bounded node identity form.
    if (type(source_id) is not str or (source_id != expected and
            re.fullmatch(r"research-gdelt-[0-9a-f]{32}-[0-2]", source_id) is None)):
        raise ValueError("research source identity must match a query or durable run node")
    value = {"id": source_id, "label": "GDELT DOC internal research metadata",
        "kind": "gdelt_research_metadata", "url": ENDPOINT, "query": query,
        "adapter_version": ADAPTER_VERSION if legacy else RECOVERY_ADAPTER_VERSION,
        "policy_version": policy_version,
        "coverage": "bounded_snapshot", "mode": "ArtList", "format": "json",
        "timespan": TIMESPAN, "sort": "HybridRel", "max_candidates": MAX_CANDIDATES,
        "max_selected": MAX_SELECTED, "max_bytes": MAX_BYTES,
        "timeout_seconds": TIMEOUT_SECONDS if legacy else research_policy.RECOVERY_POLICY["transport_timeout_seconds"],
        "rights_status": "internal_metadata_experiment_only",
        "rights_note": "GDELT dataset metadata, attributed to The GDELT Project "
            "(https://www.gdeltproject.org/). Dataset terms: "
            "https://gdeltproject.org/about.html#termsofuse. Linked article text and images "
            "are not retrieved; publisher processing or redistribution rights are not established.",
        "selection_policy": "first_four_distinct_safe_https_candidates_in_api_order",
        "publication_time": "unavailable; seendate retained as GDELT observation only",
        "monitoring_authority": False}
    if not legacy:
        value["recovery_policy"] = dict(research_policy.RECOVERY_POLICY)
    return value


def matches_source_contract(row):
    """Recognize a saved exact policy; callers separately enforce permissions."""
    try:
        query = row.contract["query"]
        expected = contract(row.pk, query, policy_version=row.contract["policy_version"])
        return row.contract == expected and row.contract_digest == text_digest(canonical_json(expected))
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def request_url(query, *, policy_version=POLICY_VERSION):
    validate_query(query)
    _policy(policy_version)
    return ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "mode": "ArtList",
        "format": "json", "timespan": TIMESPAN, "sort": "HybridRel",
        "maxrecords": MAX_CANDIDATES})


def _same_request_url(actual, expected):
    """Allow transport percent-encoding normalization, never another target."""
    try:
        first, second = urllib.parse.urlsplit(actual), urllib.parse.urlsplit(expected)
        return (not first.fragment and first._replace(query="", fragment="") ==
            second._replace(query="", fragment="") and
            urllib.parse.parse_qsl(first.query, keep_blank_values=True, strict_parsing=True,
                                  errors="strict") ==
            urllib.parse.parse_qsl(second.query, keep_blank_values=True, strict_parsing=True,
                                  errors="strict"))
    except (TypeError, ValueError, UnicodeError):
        return False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceError("invalid_json")
        result[key] = value
    return result


def _finite(value):
    raise SourceError("invalid_json")


def _text(value, limit, *, blank=False):
    if (type(value) is not str or len(value) > limit or (not blank and not value.strip())
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise SourceError("invalid_research_metadata")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise SourceError("invalid_research_metadata") from None
    return value


def _safe_article_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or len(host) > 253
                or re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", host) is None
                or host.lower().endswith((".localhost", ".local", ".internal"))):
            return False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return True
        return False
    except ValueError:
        return False


def parse_metadata(raw, *, query, received_at, policy_version=POLICY_VERSION):
    """Preserve the entire bounded candidate log and an explicit selected set."""
    validate_query(query)
    _policy(policy_version)
    received_at = _utc(received_at)
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        raise SourceError("byte_limit")
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                           parse_constant=_finite)
    except (UnicodeError, ValueError, RecursionError):
        raise SourceError("invalid_json") from None
    if type(value) is not dict or set(value) != {"articles"} or type(value["articles"]) is not list:
        raise SourceError("invalid_research_metadata")
    articles = value["articles"]
    if len(articles) > MAX_CANDIDATES:
        raise SourceError("item_limit")
    candidates, selected, seen = [], [], set()
    for index, article in enumerate(articles):
        if type(article) is not dict or not _REQUIRED <= set(article) <= _FIELDS:
            raise SourceError("invalid_research_metadata")
        for field in article:
            limit = 2048 if field in ("title", "url", "url_mobile", "socialimage") else 253
            _text(article[field], limit, blank=field not in ("title", "url", "seendate"))
        stamp = article["seendate"]
        if re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", stamp) is None:
            raise SourceError("invalid_time")
        try:
            gdelt_seen_at = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            raise SourceError("invalid_time") from None
        identity = "url-sha256:" + text_digest(article["url"])
        reason = None
        if identity in seen:
            reason = "duplicate_url_identity"
        elif not _safe_article_url(article["url"]):
            reason = "unsafe_or_non_https_attribution_url"
        elif len(selected) >= MAX_SELECTED:
            reason = "explicit_selection_limit"
        seen.add(identity)
        candidates.append({"rank": index + 1, "native_id": identity,
            "selected": reason is None, "exclusion_reason": reason,
            "gdelt_seen_at": gdelt_seen_at.isoformat(), "metadata": dict(article)})
        if reason is None:
            content = canonical_json({"kind": "gdelt_headline_metadata_only",
                "gdelt_seen_at": gdelt_seen_at.isoformat(), "domain": article["domain"],
                "language": article["language"], "sourcecountry": article["sourcecountry"],
                "article_body": "not_retrieved", "publisher_publication_time": "unavailable"})
            selected.append(SourceItem(identity, article["title"], article["url"], None, content))
    # This batch is exactly the logged selection. API cap/scope limits are
    # distinct from a truncated transport payload and remain explicit metadata.
    batch = SourceBatch(tuple(selected), received_at, "bounded_snapshot", False, sha256(raw).hexdigest())
    legacy = policy_version == POLICY_VERSION
    metadata = {"schema_version": "gdelt-research-selection-v1" if legacy else "gdelt-research-selection-v2", "query": query,
        "request_url": request_url(query, policy_version=policy_version), "received_at": received_at.isoformat(),
        "transport_digest": batch.transport_digest, "requested_candidate_limit": MAX_CANDIDATES,
        "selection_limit": MAX_SELECTED, "returned_candidate_count": len(articles),
        "selected_count": len(selected), "candidate_cap_reached": len(articles) == MAX_CANDIDATES,
        "coverage_complete": False, "candidates": candidates, "limitations": list(LIMITATIONS)}
    if not legacy:
        metadata["policy_version"] = policy_version
        metadata["adapter_version"] = RECOVERY_ADAPTER_VERSION
    return ResearchSearchResult(batch=batch, metadata=metadata)


def _retry_after(headers, *, clock):
    """Only a single bounded header is eligible; never expose the raw value."""
    if headers is None:
        return None
    values = (headers.get_all("Retry-After", []) if hasattr(headers, "get_all")
              else [headers.get("Retry-After")])
    if len(values) != 1:
        return None
    return research_policy.parse_retry_after(values[0], now=clock())


def discover(query, *, clock=_now, opener=None, policy_version=POLICY_VERSION):
    """One fixed HTTPS GET; no article fetch, redirect, credential or retry."""
    validate_query(query)
    _policy(policy_version)
    require_internal_experiment()
    url = request_url(query, policy_version=policy_version)
    timeout = TIMEOUT_SECONDS if policy_version == POLICY_VERSION else research_policy.RECOVERY_POLICY["transport_timeout_seconds"]
    request = urllib.request.Request(url, method="GET", headers={
        "Accept": "application/json", "Accept-Encoding": "identity",
        "User-Agent": "MacroAgentInternalResearch/0.1 (+https://github.com/0xsomnus/macro_agent)",
    })
    try:
        with (opener or BoundedOpener()).open(request, timeout=timeout, limit=MAX_BYTES) as response:
            if response.status != 200 or not _same_request_url(response.geturl(), url):
                raise SourceError("invalid_response")
            if response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity"):
                raise SourceError("invalid_response")
            length = response.headers.get("Content-Length")
            if length is not None:
                if re.fullmatch(r"[0-9]{1,20}", length) is None:
                    raise SourceError("invalid_response")
                if int(length) > MAX_BYTES:
                    raise SourceError("byte_limit")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in ("application/json", "text/json"):
                raise SourceError("invalid_response")
            raw = response.read(MAX_BYTES + 1)
            received_at = clock()
            if len(raw) > MAX_BYTES:
                raise SourceError("byte_limit")
            if length is not None and int(length) != len(raw):
                raise SourceError("incomplete_response")
    except TransportError as error:
        code = error.code if error.code in ("timeout", "unavailable", "byte_limit",
            "invalid_response", "incomplete_response") else "transport_error"
        raise SourceError(code) from None
    except urllib.error.HTTPError as error:
        status = error.code
        try:
            retry_after = _retry_after(error.headers, clock=clock) if status == 429 or 500 <= status <= 599 else None
        finally:
            error.close()
        code = "rate_limited" if status == 429 else "unavailable" if 500 <= status <= 599 else "http_error"
        raise SourceError(code, retry_after_seconds=retry_after) from None
    except TimeoutError:
        raise SourceError("timeout") from None
    except (urllib.error.URLError, OSError, HTTPException):
        raise SourceError("transport_error") from None
    return parse_metadata(raw, query=query, received_at=received_at, policy_version=policy_version)


fetch_research = discover
