"""Owner-scoped, read-only daily review summaries for the internal desk.

The list is an inspection surface, not a current publication pointer. Counts
describe retained records. They do not establish news coverage or usefulness.
"""

from django.db import connection, transaction
from django.db.models import Func, IntegerField
from django.db.models.fields.json import KeyTransform
from django.utils import timezone

from macro_agent.domain.time import as_utc
from macro_agent.theses import service as theses

from . import service
from .models import DailyReview


def _array_length(*path):
    expression = "content"
    for key in path:
        expression = KeyTransform(key, expression)
    return Func(expression, function="jsonb_array_length", output_field=IntegerField())


def _summaries(query):
    counts = {
        f"{kind}_{section}_count": _array_length(kind, section)
        for kind in ("reports", "analyses")
        for section in ("new", "background", "deferred")
    }
    counts.update(
        issue_count=_array_length("issues"),
        unresolved_analysis_count=_array_length("unresolved_analysis_ids"),
        unknown_reported_cost_analysis_count=_array_length("unknown_reported_cost_analysis_ids"),
    )
    # Lists never retrieve full source content, prior model documents or exact
    # approved inputs. Full retained integrity verification belongs to detail.
    return query.select_related("context__evidence").defer(
        "content", "context__resolved_inputs"
    ).annotate(**counts)


def _summary(row, thesis, at, observation):
    return {
        "id": str(row.pk), "command_id": str(row.command_id),
        "context_id": str(row.context_id), "evidence_set_id": str(row.context.evidence_id),
        "predecessor_id": str(row.context.predecessor_id) if row.context.predecessor_id else None,
        "start": row.start.isoformat(), "cutoff": row.cutoff.isoformat(),
        "prepared_at": row.prepared_at.isoformat(), "original_outcome": row.original_outcome,
        "digest": row.digest, "source_manifest": row.context.evidence.source_manifest,
        "counts": {
            kind: {section: getattr(row, f"{kind}_{section}_count")
                   for section in ("new", "background", "deferred")}
            for kind in ("reports", "analyses")
        } | {
            "issues": row.issue_count,
            "unresolved_analyses": row.unresolved_analysis_count,
            "unknown_reported_cost_analyses": row.unknown_reported_cost_analysis_count,
        },
        "current_disposition": service._present(row, thesis, at, observation=observation),
    }


def list_reviews(actor_id, thesis_id, limit=20, offset=0, *, clock=timezone.now):
    """One coherent private snapshot, with stable newest-cutoff-first ordering.

    A subsequent request gets another snapshot, so offsets are not historical
    cursors. The observation timestamp is not an exact commit or delivery time.
    """
    service.gate()
    service.outermost()
    if (type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int
            or not 0 <= offset <= 1_000_000):
        raise ValueError("Invalid daily review pagination")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        theses._owner(actor_id)
        thesis = theses._record(actor_id, thesis_id)
        query = DailyReview.objects.filter(owner_id=actor_id, thesis=thesis)
        total = query.count()
        rows = list(_summaries(query.order_by("-cutoff", "-id"))[offset:offset + limit])
        source_ids = {reference["source_id"] for row in rows
                      for reference in row.context.evidence.source_manifest}
        observation = service._present_observation(thesis, source_ids) if rows else None
        at = as_utc(clock())
        return {
            "thesis_id": str(thesis.pk),
            "reviews": [_summary(row, thesis, at, observation) for row in rows],
            "limit": limit, "offset": offset, "total": total,
            "has_more": offset + len(rows) < total,
            "observed_at": at.isoformat(), "publication_authority": False,
        }
