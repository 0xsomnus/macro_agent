"""Bounded source fanout under the common publication ordering protocol.

The caller owns the source lock. All affected owners, theses and brief rows
are protected before its trusted clock is sampled. Invalidation preserves the
original assessment and publication receipt, and never invokes a model.
"""

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Q

from macro_agent.domain.models import require_text
from macro_agent.domain.time import as_utc
from macro_agent.persistence.models import (
    AuditTransition, BriefStateRecord, CurrentAssessment, NotificationIntent,
    ReassessmentWork,
)
from macro_agent.theses.models import ThesisRecord


MAX_FANOUT = 1000


def _active_publications():
    from .models import DailyPublication
    current = CurrentAssessment.objects.values_list("assessment_id", flat=True)
    pending = NotificationIntent.objects.filter(state="pending").values_list("assessment_id", flat=True)
    return DailyPublication.objects.filter(Q(assessment_id__in=current) | Q(assessment_id__in=pending))


def check_publication_capacity(*, source_ids, brief_id, fanout_limit):
    """Keep newly activated current output within every source's reviewed cap.

    The caller holds all selected source locks. Every new publication uses the
    same source-first protection, so another admission cannot grow this set.
    Concurrent removals only make this observation conservative. No other
    owner locks or model calls are needed for the bounded admission check.
    """
    from .models import DailyBrief
    from macro_agent.domain.daily_review import ReviewCapacityExceeded

    if connection.vendor != "postgresql" or not connection.in_atomic_block:
        raise RuntimeError("Daily capacity admission requires protected PostgreSQL sources")
    if type(fanout_limit) is not int or not 1 <= fanout_limit <= MAX_FANOUT:
        raise ValueError("Daily capacity admission requires an explicit reviewed fanout limit")
    require_text(brief_id, "brief_id")
    if type(source_ids) not in (list, tuple) or not 1 <= len(source_ids) <= 16 or len(set(source_ids)) != len(source_ids):
        raise ValueError("Daily capacity admission requires an explicit unique source manifest")
    for source_id in sorted(source_ids):
        publications = _active_publications().filter(review__context__evidence__sources__source_id=source_id)
        bindings = list(DailyBrief.objects.filter(brief_id__in=publications.values("brief_id"))
            .order_by("brief_id").values("brief_id", "fanout_limit")[:MAX_FANOUT + 1])
        count = len(bindings) + int(brief_id not in {row["brief_id"] for row in bindings})
        bound = min(MAX_FANOUT, fanout_limit, *(row["fanout_limit"] for row in bindings))
        if count > bound:
            raise ReviewCapacityExceeded("Daily publication would exceed a source's reviewed complete fanout bound; no output was activated")


def lock_source_dependents(*, source_id, report_ids=None, actor_id=None):
    """Protect the complete affected set, never an arbitrary truncated prefix.

    ``None`` selects permission dependents for the source. A report-id list
    selects only corrections to those reports. Current pointers and pending
    intents both count, so clearing a pointer alone cannot hide a stale notice.
    Immutable source membership and source-first publication admission keep
    this discovery stable while the caller holds its source protection.
    """
    from .models import DailyBrief
    from macro_agent.domain.daily_review import ReviewCapacityExceeded

    if connection.vendor != "postgresql" or not connection.in_atomic_block:
        raise RuntimeError("Source fanout requires a protected PostgreSQL transaction")
    publications = _active_publications()
    if report_ids is None:
        publications = publications.filter(review__context__evidence__sources__source_id=source_id)
    else:
        publications = publications.filter(
            review__context__evidence__revisions__revision__report_id__in=report_ids,
            review__context__evidence__revisions__revision__report__source_id=source_id)
    # Deduplicate bindings before the N+1 bound, independently of how many
    # revisions and historical assessments refer to the same brief.
    bindings = list(DailyBrief.objects.filter(brief_id__in=publications.values("brief_id"))
        .order_by("brief_id").values("brief_id", "owner_id", "thesis_id", "fanout_limit")[:MAX_FANOUT + 1])
    if bindings and len(bindings) > min(MAX_FANOUT, *(row["fanout_limit"] for row in bindings)):
        raise ReviewCapacityExceeded("Complete daily publication fanout exceeds its reviewed bound; no records were discarded")

    owner_ids = {row["owner_id"] for row in bindings}
    if actor_id is not None:
        owner_ids.add(actor_id)
    # Inactive owners can still have retained current state or pending intents.
    list(get_user_model().objects.select_for_update().filter(pk__in=owner_ids).order_by("pk"))
    list(ThesisRecord.objects.select_for_update().filter(
        pk__in={row["thesis_id"] for row in bindings}).order_by("pk"))
    return list(BriefStateRecord.objects.select_for_update().filter(
        pk__in=[row["brief_id"] for row in bindings]).order_by("pk"))


def invalidate_daily_briefs(briefs, at, reason):
    """Atomically clear protected daily authority and cancel pending notices."""
    if connection.vendor != "postgresql" or not connection.in_atomic_block:
        raise RuntimeError("Daily invalidation requires a protected PostgreSQL transaction")
    require_text(reason, "reason")
    at = as_utc(at)
    if any(at < brief.changed_at for brief in briefs):
        raise ValueError("Daily invalidation cannot precede protected publication state")
    for brief in briefs:
        CurrentAssessment.objects.filter(brief=brief).delete()
        canceled = list(NotificationIntent.objects.filter(brief=brief, state="pending")
            .order_by("intent_id").values_list("intent_id", flat=True))
        NotificationIntent.objects.filter(brief=brief, state="pending").update(state="canceled", updated_at=at)
        ReassessmentWork.objects.filter(brief=brief, state="pending").update(state="superseded", completed_at=at)
        brief.changed_at = at
        brief.save(update_fields=("changed_at",))
        AuditTransition.objects.create(brief=brief, kind="daily_publication_invalidated", happened_at=at,
            detail={"actor_id": str(brief.owner_id), "reason": reason, "canceled_intents": canceled,
                    "original_decisions_preserved": True})
    return [brief.pk for brief in briefs]
