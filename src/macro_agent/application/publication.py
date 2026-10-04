"""One auditable application boundary owns the entire publication operation."""

from datetime import datetime
from typing import Callable

from ..domain.publication import PublicationCandidate, PublicationDecision, decide_publication
from ..ports import PublicationStore
from ..domain.time import as_utc


def publish(store: PublicationStore, candidate: PublicationCandidate,
            at: datetime | Callable[[], datetime]) -> PublicationDecision:
    """A runtime supplies a trusted clock, sampled after the protected read.

    A fixed datetime supports recorded fixtures only. Sampling before acquiring
    the transaction can become obsolete while waiting behind a correction.
    """
    with store.transaction(candidate.brief_id) as transaction:
        current = transaction.state()
        at = as_utc(at() if callable(at) else at)
        if candidate.owner_id != current.owner_id:
            raise PermissionError("publication belongs to a different owner")
        if at < candidate.snapshot.cutoff or at < current.changed_at:
            raise ValueError("publication cannot be backdated behind its inputs or current state")
        existing = transaction.existing(candidate.assessment_id)
        if existing is not None:
            digest, decision = existing
            if digest != candidate.digest:
                raise ValueError("immutable assessment identity reused with different content")
            return decision
        decision = decide_publication(candidate, current, at)
        transaction.save(candidate, decision, at)
        return decision
