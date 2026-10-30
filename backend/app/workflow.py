"""Case state machine. The only place case status changes; the LLM never calls this directly."""

from sqlalchemy.orm import Session

from app import audit
from app.errors import Conflict
from app.models import CaseStatus as S
from app.models import MedicalCase, User

TRANSITIONS: dict[S, set[S]] = {
    S.UPLOADED: {S.PROCESSING},
    S.PROCESSING: {S.SUMMARY_READY, S.PROCESSING_FAILED, S.NEEDS_CORRECTION},
    S.PROCESSING_FAILED: {S.PROCESSING},
    S.NEEDS_CORRECTION: {S.PROCESSING},
    S.SUMMARY_READY: {S.AWAITING_CONSENT, S.PROCESSING},
    S.AWAITING_CONSENT: {S.CONSENT_GRANTED, S.SUMMARY_READY},
    S.CONSENT_GRANTED: {S.HANDOFF_SENT, S.CONSENT_WITHDRAWN},
    S.HANDOFF_SENT: {S.ACKNOWLEDGED, S.HANDOFF_CANCELLED, S.CONSENT_WITHDRAWN},
    S.ACKNOWLEDGED: {S.UNDER_REVIEW, S.CONSENT_WITHDRAWN},
    S.UNDER_REVIEW: {S.REVIEW_COMPLETED, S.CONSENT_WITHDRAWN},
    S.REVIEW_COMPLETED: {S.CLOSED},
    S.CONSENT_WITHDRAWN: {S.AWAITING_CONSENT},
    S.HANDOFF_CANCELLED: {S.AWAITING_CONSENT},
    S.CLOSED: set(),
}

# Statuses in which an assigned clinician may view the case (consent is checked separately).
CLINICIAN_VISIBLE = {S.HANDOFF_SENT, S.ACKNOWLEDGED, S.UNDER_REVIEW, S.REVIEW_COMPLETED, S.CLOSED}


def can_transition(current: S, target: S) -> bool:
    return target in TRANSITIONS[current]


def transition(
    db: Session,
    case: MedicalCase,
    target: S,
    *,
    actor: User | None = None,
    actor_type: str | None = None,
    reason: str | None = None,
) -> None:
    current = case.status
    if not can_transition(current, target):
        raise Conflict("invalid_transition", f"Case cannot move from {current.value} to {target.value}")
    case.status = target
    audit.record(
        db,
        "case.status_changed",
        "MedicalCase",
        case.id,
        actor=actor,
        actor_type=actor_type,
        org_id=case.org_id,
        details={"from": current.value, "to": target.value, **({"reason": reason} if reason else {})},
    )
