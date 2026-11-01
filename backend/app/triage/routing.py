"""Deterministic paging and escalation for symptom threads. No model is involved in who gets paged or when."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, services, workflow
from app.config import get_settings
from app.models import (
    CaseKind,
    CaseStatus,
    ClinicalHandoff,
    ClinicianProfile,
    HandoffStatus,
    MedicalCase,
    MessageAuthor,
    Urgency,
    User,
)
from app.triage import content
from app.triage.messages import post_message

HIGH = (Urgency.URGENT, Urgency.EMERGENCY)


def ack_window(level: Urgency) -> timedelta:
    s = get_settings()
    minutes = {
        Urgency.EMERGENCY: s.urgent_ack_minutes,
        Urgency.URGENT: s.urgent_ack_minutes,
        Urgency.SOON: s.soon_ack_minutes,
        Urgency.ROUTINE: s.routine_ack_minutes,
    }[level]
    return timedelta(minutes=minutes)


def _family_doctor(db: Session, case: MedicalCase) -> ClinicianProfile | None:
    fd_id = case.patient.primary_clinician_id
    fd = db.get(ClinicianProfile, fd_id) if fd_id else None
    return fd if fd and fd.user.is_active and fd.user.org_id == case.org_id else None


def _on_call(db: Session, case: MedicalCase) -> list[ClinicianProfile]:
    rows = db.scalars(
        select(ClinicianProfile)
        .join(User, User.id == ClinicianProfile.user_id)
        .where(ClinicianProfile.on_call.is_(True), User.org_id == case.org_id, User.is_active.is_(True))
        .order_by(ClinicianProfile.on_call_priority, ClinicianProfile.id)
    )
    return list(rows)


def care_team(db: Session, case: MedicalCase) -> list[ClinicianProfile]:
    """Family doctor first, then on-call clinicians by priority, each once."""
    fd = _family_doctor(db, case)
    team = [fd] if fd else []
    return team + [c for c in _on_call(db, case) if not fd or c.id != fd.id]


def _required(db: Session, case: MedicalCase, level: Urgency) -> list[ClinicianProfile]:
    team = care_team(db, case)
    fd = _family_doctor(db, case)
    if level in HIGH:
        return team[:2] if fd else team[:1]
    return team[:1]


def _handoffs(db: Session, case: MedicalCase) -> list[ClinicalHandoff]:
    return list(db.scalars(select(ClinicalHandoff).where(ClinicalHandoff.case_id == case.id, ClinicalHandoff.status != HandoffStatus.CANCELLED)))


def _page(db: Session, case: MedicalCase, clinician: ClinicianProfile, level: Urgency, due: datetime, now: datetime) -> ClinicalHandoff:
    consent = services.active_consent(case)
    assert consent is not None
    latest = case.triage_assessments[-1].id if case.triage_assessments else None
    h = ClinicalHandoff(case_id=case.id, consent_id=consent.id, clinician_id=clinician.id, triage_id=latest, status=HandoffStatus.SENT, sent_at=now, ack_due_at=due)
    db.add(h)
    db.flush()
    title = "Urgent case waiting for you" if level in HIGH else "New case waiting for you"
    services.notify(db, clinician.user_id, case, title, "Open CareBridge to review.")
    audit.record(db, "triage.paged", "ClinicalHandoff", h.id, actor_type="SYSTEM", org_id=case.org_id, details={"case_id": str(case.id), "clinician_id": str(clinician.id), "level": level.value})
    if case.status == CaseStatus.TRIAGED:
        workflow.transition(db, case, CaseStatus.HANDOFF_SENT, actor_type="SYSTEM", reason=f"paged at {level.value}")
    return h


def _advise_fallback(db: Session, case: MedicalCase, now: datetime) -> None:
    case.fallback_advised_at = now
    post_message(db, case, MessageAuthor.SYSTEM, content.GUIDANCE_FALLBACK, {"kind": "fallback"})
    services.notify(db, case.patient.user_id, case, "Update on your message", "Open CareBridge for an update.")
    audit.record(db, "triage.fallback_advised", "MedicalCase", case.id, actor_type="SYSTEM", org_id=case.org_id)


def apply_level(db: Session, case: MedicalCase, level: Urgency, now: datetime) -> list[ClinicalHandoff]:
    """Page whoever this level requires and tighten open deadlines. Safe to call repeatedly."""
    if not services.active_consent(case):
        return []
    existing = _handoffs(db, case)
    paged_ids = {h.clinician_id for h in existing}
    due = now + ack_window(level)
    for h in existing:
        if h.status == HandoffStatus.SENT and (h.ack_due_at is None or h.ack_due_at > due):
            h.ack_due_at = due
    created = [_page(db, case, c, level, due, now) for c in _required(db, case, level) if c.id not in paged_ids]
    if not existing and not created and level in HIGH and case.fallback_advised_at is None:
        _advise_fallback(db, case, now)
    return created


def acknowledge(db: Session, case: MedicalCase, handoff: ClinicalHandoff, actor: User) -> None:
    if handoff.status != HandoffStatus.SENT:
        return
    handoff.status = HandoffStatus.ACKNOWLEDGED
    handoff.acknowledged_at = services.now()
    first = case.status == CaseStatus.HANDOFF_SENT
    if first:
        workflow.transition(db, case, CaseStatus.ACKNOWLEDGED, actor=actor)
    audit.record(db, "handoff.acknowledged", "ClinicalHandoff", handoff.id, actor=actor, details={"case_id": str(case.id)})
    if first:
        post_message(db, case, MessageAuthor.SYSTEM, f"{actor.full_name} has seen your message.", {"kind": "acknowledged"})
        services.notify(db, case.patient.user_id, case, "A clinician has seen your message", "Open CareBridge for details.")


def sweep(db: Session, now: datetime) -> dict[str, int]:
    """Escalate overdue pages and advise urgent care when nobody has responded. Run by the scheduler."""
    counts = {"escalated": 0, "fallback": 0}
    ids = db.scalars(select(MedicalCase.id).where(MedicalCase.kind == CaseKind.SYMPTOM, MedicalCase.status == CaseStatus.HANDOFF_SENT)).all()
    for case_id in ids:
        # Lock and re-read: an acknowledgement committed since the query above wins.
        case = db.scalar(select(MedicalCase).where(MedicalCase.id == case_id).with_for_update())
        if not case or case.status != CaseStatus.HANDOFF_SENT or not case.urgency:
            continue
        handoffs = _handoffs(db, case)
        overdue = [h for h in handoffs if h.status == HandoffStatus.SENT and h.ack_due_at and h.ack_due_at <= now and h.escalated_at is None]
        exhausted = False
        if overdue:
            for h in overdue:
                h.escalated_at = now
            paged = {h.clinician_id for h in handoffs}
            nxt = next((c for c in care_team(db, case) if c.id not in paged), None)
            if nxt:
                _page(db, case, nxt, case.urgency, now + ack_window(case.urgency), now)
                post_message(db, case, MessageAuthor.SYSTEM, "We're contacting another clinician.", {"kind": "escalated"})
                counts["escalated"] += 1
            else:
                exhausted = True
        first_sent = min((h.sent_at for h in handoffs), default=None)
        waited_too_long = first_sent is not None and now - first_sent >= timedelta(minutes=get_settings().urgent_fallback_minutes)
        if case.urgency == Urgency.URGENT and case.fallback_advised_at is None and (exhausted or waited_too_long):
            _advise_fallback(db, case, now)
            counts["fallback"] += 1
    return counts
