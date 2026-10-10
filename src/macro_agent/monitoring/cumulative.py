"""Protected cumulative dependencies, without inference or publication authority."""

from macro_agent.desk.models import EvidenceRevision, EvidenceSource, SourceContractHead

from .models import SourceState
from .news_context import NewsConflict, NewsMissing, allowed_source


def lock_sources(source_ids, *, require_permitted=True):
    """All source writers use source order before owner/thesis protection."""
    rows = list(SourceState.objects.select_for_update().filter(
        pk__in=source_ids).order_by("pk"))
    if [row.pk for row in rows] != list(source_ids):
        raise NewsMissing("Complete context source manifest is unavailable")
    if require_permitted and any(not allowed_source(row) for row in rows):
        raise NewsMissing("Context source unavailable for internal analysis")
    return rows


def _dependencies(attempt):
    evidence_id = attempt.admission_context.evidence_id
    sources = list(EvidenceSource.objects.filter(evidence_id=evidence_id).select_related("source", "contract"))
    eligible = [item["revision_id"] for item in attempt.context["cumulative"]["reports"]]
    revisions = list(EvidenceRevision.objects.filter(evidence_id=evidence_id,
        revision_id__in=eligible).select_related("revision__report__current_revision"))
    return sources, revisions


def cumulative_stale_reasons(attempt):
    """Compare consumed heads against admission, never against source age.

    Write callers protect all manifest sources first. Inspection callers use
    one coherent read-only snapshot. Distinct later reports are irrelevant.
    """
    if attempt.admission_context_id is None:
        return []
    sources, revisions = _dependencies(attempt)
    heads = {row.source_id: row.version_id for row in
        SourceContractHead.objects.filter(source_id__in=[row.source_id for row in sources])}
    reasons = set()
    for row in sources:
        if (row.source.contract_digest != row.contract.digest
                or row.source.contract != row.contract.contract
                or heads.get(row.source_id) != row.contract_id):
            reasons.add("contextual_source_contract_changed")
        if not allowed_source(row.source):
            reasons.add("contextual_source_contract_unavailable")
    for row in revisions:
        if row.revision.report.current_revision_id != row.head_at_preparation_id:
            reasons.add("contextual_source_revision_changed")
    return sorted(reasons)


def check_cumulative_clock(attempt, at):
    """Sample time after protection and reject backdated current observations."""
    sources, revisions = _dependencies(attempt)
    for row in revisions:
        head = row.revision.report.current_revision
        if head is not None and at < head.system_received_at:
            raise NewsConflict("Trusted clock precedes contextual source state")
    permissions = SourceContractHead.objects.filter(
        source_id__in=[row.source_id for row in sources]).select_related("version")
    if any(at < row.version.observed_at for row in permissions):
        raise NewsConflict("Trusted clock precedes contextual source permission observation")
