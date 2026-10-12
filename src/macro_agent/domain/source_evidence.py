"""Exact retained source inputs, without claims of truth or access authority.

The application resolves permissions, immutable revisions and current heads
under protection. This validator checks the supplied data and attribution only.
"""

import json
import re
from uuid import UUID

from .models import canonical_json, text_digest
from .time import parse_instant


SOURCE_EVIDENCE_SCHEMA_VERSION = "retained-source-evidence-v1"
MAX_EVIDENCE_BYTES = 65_536
MAX_REPORTS = 16
MAX_CLAIMS = 32
MAX_QUOTE_CHARS = 2_000
REPORT_FIELDS = frozenset((
    "revision_id", "source_id", "title", "content", "source_url",
    "source_claimed_published_at", "system_received_at", "availability_witness_at",
    "contract_version_id", "contract_digest", "head_at_admission_id",
))


def _text(value, name, limit, *, blank=False):
    if (type(value) is not str or len(value) > limit or "\x00" in value
            or (not blank and not value.strip())):
        raise ValueError(f"{name} requires bounded text without NUL")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError(f"{name} requires valid Unicode") from None
    return value


def _object(value, fields, name):
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"{name} requires exactly its documented fields")
    return value


def _array(value, name, limit):
    if type(value) is not list or len(value) > limit:
        raise ValueError(f"{name} requires a bounded array")
    return value


def _uuid(value, name):
    _text(value, name, 36)
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError):
        raise ValueError(f"{name} requires a canonical UUID") from None
    return value


def _instant(value, name):
    _text(value, name, 64)
    try:
        return parse_instant(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} requires an aware timestamp") from None


def validate_source_evidence(envelope):
    """Return detached exact data; checks neither source truth nor permission.

    A conservative witness must be no later than the selected cutoff. Public
    timestamps remain source claims and cannot substitute for that witness.
    This first contract deliberately admits only current selected revisions.
    """
    _object(envelope, frozenset(("schema_version", "cutoff", "reports", "gaps")),
            "source evidence")
    if envelope["schema_version"] != SOURCE_EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported source evidence schema version")
    cutoff = _instant(envelope["cutoff"], "source evidence cutoff")
    reports = _array(envelope["reports"], "source reports", MAX_REPORTS)
    if not reports:
        raise ValueError("source evidence requires at least one report")
    revisions, contracts = set(), {}
    for report in reports:
        _object(report, REPORT_FIELDS, "source report")
        revision = _uuid(report["revision_id"], "source revision")
        if revision in revisions:
            raise ValueError("source revisions cannot repeat")
        revisions.add(revision)
        source = _text(report["source_id"], "source identity", 128)
        _uuid(report["head_at_admission_id"], "admission source head")
        if report["head_at_admission_id"] != revision:
            raise ValueError("selected revision must be the pinned admission head")
        contract = _uuid(report["contract_version_id"], "source contract version")
        digest = report["contract_digest"]
        if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("source contract digest requires lowercase SHA256")
        if source in contracts and contracts[source] != (contract, digest):
            raise ValueError("one source must use one pinned contract version")
        contracts[source] = (contract, digest)
        _text(report["title"], "source title", 4_096)
        _text(report["content"], "source content", 16_384, blank=True)
        _text(report["source_url"], "source URL", 4_096)
        received = _instant(report["system_received_at"], "source receipt")
        witness = _instant(report["availability_witness_at"], "availability witness")
        if not received <= witness <= cutoff:
            raise ValueError("source receipt and witness must precede the cutoff in order")
        if report["source_claimed_published_at"] is not None:
            _instant(report["source_claimed_published_at"], "source claimed publication")
    for gap in _array(envelope["gaps"], "source evidence gaps", 32):
        _text(gap, "source evidence gap", 2_000)
    try:
        encoded = canonical_json(envelope)
        if len(encoded.encode("utf-8")) > MAX_EVIDENCE_BYTES:
            raise ValueError("complete source evidence exceeds its encoded bound; do not truncate")
        return json.loads(encoded)
    except (TypeError, UnicodeError, RecursionError, OverflowError):
        raise ValueError("source evidence requires bounded finite JSON data") from None


def validate_attributed_claims(claims, envelope):
    """Check exact source quotations, never their truth or inferred meaning."""
    evidence = validate_source_evidence(envelope)
    reports = {item["revision_id"]: item for item in evidence["reports"]}
    identities = set()
    for claim in _array(claims, "attributed claims", MAX_CLAIMS):
        _object(claim, frozenset(("claim_id", "revision_id", "field", "exact_quote")),
                "attributed claim")
        identity = _text(claim["claim_id"], "attributed claim identity", 128)
        if identity in identities:
            raise ValueError("attributed claim identities cannot repeat")
        identities.add(identity)
        revision = claim["revision_id"]
        if type(revision) is not str or revision not in reports:
            raise ValueError("attributed claim requires a supplied source revision")
        field = claim["field"]
        if type(field) is not str or field not in ("title", "content"):
            raise ValueError("attributed claim requires a retained title or content field")
        quote = _text(claim["exact_quote"], "source quotation", MAX_QUOTE_CHARS)
        if quote not in reports[revision][field]:
            raise ValueError("source quotation must match its named retained field exactly")
    return json.loads(canonical_json(claims))


def source_evidence_digest(envelope):
    """Hash the complete validated projection without normalizing exact text."""
    return text_digest(canonical_json(validate_source_evidence(envelope)))
