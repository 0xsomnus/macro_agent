"""Exact-text and interpretation approval rules with explicit user authority."""

from dataclasses import dataclass
from datetime import datetime
import json

from .models import (
    CompiledThesisVersion, ThesisApproval, UserThesisVersion, require_digest,
    require_text,
)
from .time import as_utc


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """Internal command, with actor identity supplied by a trusted boundary.

    actor_id and actor_role are not authentication. An eventual API must derive
    them from authenticated context, never from client-selected request fields.
    """

    approval_id: str
    actor_id: str
    actor_role: str
    thesis_version_id: str
    text_digest: str
    interpretation_version_id: str
    interpretation_digest: str
    approved_at: datetime

    def __post_init__(self) -> None:
        for name in ("approval_id", "actor_id", "actor_role", "thesis_version_id", "interpretation_version_id"):
            require_text(getattr(self, name), name)
        require_digest(self.text_digest, "text_digest")
        require_digest(self.interpretation_digest, "interpretation_digest")
        object.__setattr__(self, "approved_at", as_utc(self.approved_at))


def approve_thesis(
    thesis: UserThesisVersion,
    interpretation: CompiledThesisVersion,
    request: ApprovalRequest,
    *,
    now: datetime,
) -> ThesisApproval:
    """Bind approval to exact displayed versions without changing either one.

    The application supplies its trusted instant for this synchronous command.
    Persistence later decides current activation atomically; this pure function
    emits authority evidence without claiming to update durable current state.
    """
    if not isinstance(thesis, UserThesisVersion) or not isinstance(interpretation, CompiledThesisVersion):
        raise TypeError("approval requires validated thesis and interpretation versions")
    if not isinstance(request, ApprovalRequest):
        raise TypeError("approval requires a validated internal command")
    at = as_utc(now)
    if request.actor_role != "user" or request.actor_id != thesis.owner_id:
        raise PermissionError("only the thesis owner acting as a user can approve")
    if interpretation.thesis_version_id != thesis.version_id:
        raise ValueError("interpretation is not linked to the selected thesis version")
    if (interpretation.review_card_json is not None
            and json.loads(interpretation.review_card_json)["inputs"][0]["exact_text"] != thesis.exact_text):
        raise ValueError("review card must preserve the selected exact thesis text")
    if interpretation.known_at < thesis.created_at:
        raise ValueError("compiled interpretation cannot precede its linked thesis version")
    if request.thesis_version_id != thesis.version_id or request.interpretation_version_id != interpretation.version_id:
        raise ValueError("approval must bind the selected immutable versions")
    if request.text_digest != thesis.text_digest or request.interpretation_digest != interpretation.digest:
        raise ValueError("approval must bind exact displayed text and interpretation")
    if request.approved_at != at:
        raise ValueError("approval cannot be backdated or future-dated behind the trusted clock")
    if at < max(thesis.created_at, interpretation.known_at):
        raise ValueError("approval cannot precede availability of its input versions")
    return ThesisApproval(
        approval_id=request.approval_id,
        actor_id=request.actor_id,
        thesis_version_id=thesis.version_id,
        text_digest=thesis.text_digest,
        interpretation_version_id=interpretation.version_id,
        interpretation_digest=interpretation.digest,
        approved_at=at,
    )
