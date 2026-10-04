"""Publication persistence contract; each adapter must prove its own ordering."""

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from .domain.publication import BriefState, PublicationCandidate, PublicationDecision


class PublicationTransaction(Protocol):
    def state(self) -> BriefState: ...

    def existing(self, assessment_id: str) -> tuple[str, PublicationDecision] | None:
        """Return immutable input digest and current disposition of a saved ID.
        Keep the original decision in history. A superseded publication retry
        must not report itself as current or restore its pointer/notification.
        """
        ...

    def save(self, candidate: PublicationCandidate, decision: PublicationDecision,
             at: datetime) -> None:
        """Atomically append assessment/history/audit, update current state, save
        intent or reassessment work. Save superseded results without notification.
        A material update cancels pending previous intents; a non-material update
        retains valid pending material intents. A retry must not re-publish an ID.
        """
        ...


class PublicationStore(Protocol):
    def transaction(self, brief_id: str) -> AbstractContextManager[PublicationTransaction]:
        """Protect fresh reads and writes from every governing-state writer.
        Never perform model/network calls within this short transaction.
        """
        ...
