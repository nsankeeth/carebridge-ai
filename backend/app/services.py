"""Workflow services (F/G backends). REST routes and agent tools both call these; they enforce the rules."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit, workflow
from app.access import active_handoff_for
from app.errors import AppError, Conflict, NotFound
from app.models import (
    AISummary,
    CaseStatus,
    ClinicalHandoff,
    ClinicalReview,
    ClinicianProfile,
    ConsentStatus,
    FollowUpTask,
    HandoffStatus,
    MedicalCase,
    NextStep,
    Notification,
    PatientConsent,
    SummaryAssessment,
    SummaryStatus,
    TaskStatus,
    User,
    UserRole,
)

CONSENT_SCOPE = ["original_report", "extracted_findings", "ai_clinician_summary"]
CONSENT_PURPOSE = (
    "So the selected clinician can review your laboratory report and the AI-prepared summary, "
    "and decide on any appropriate next steps."
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def active_summary(case: MedicalCase) -> AISummary | None:
    for s in reversed(case.summaries):
        if s.status in (SummaryStatus.ACTIVE, SummaryStatus.CORRECTED):
            return s
    return None


def active_consent(case: MedicalCase) -> PatientConsent | None:
    for c in reversed(case.consents):
        if c.status == ConsentStatus.GRANTED:
            return c
    return None


def notify(db: Session, user_id: uuid.UUID, case: MedicalCase | None, title: str, body: str, source: str = "system") -> Notification:
    n = Notification(user_id=user_id, case_id=case.id if case else None, title=title, body=body, source=source)
    db.add(n)
    return n


def clinician_in_org(db: Session, org_id: uuid.UUID, clinician_id: uuid.UUID) -> ClinicianProfile:
    c = db.get(ClinicianProfile, clinician_id)
    if not c or c.user.org_id != org_id or not c.user.is_active:
        raise NotFound("Clinician not found")
    return c


# --- Consent -----------------------------------------------------------------------


def request_consent(db: Session, case: MedicalCase, actor: User) -> None:
    if case.status not in (CaseStatus.SUMMARY_READY, CaseStatus.CONSENT_WITHDRAWN, CaseStatus.HANDOFF_CANCELLED):
        raise Conflict("invalid_state", "Sharing can only be set up once a validated summary is ready")
    if not active_summary(case):
        raise Conflict("no_summary", "There is no validated summary to share")
    workflow.transition(db, case, CaseStatus.AWAITING_CONSENT, actor=actor, reason="patient opened sharing")


def grant_consent(db: Session, case: MedicalCase, actor: User, clinician_id: uuid.UUID, confirmed: bool) -> PatientConsent:
    if not confirmed:
        raise AppError("consent_not_confirmed", "Explicit confirmation is required to grant consent")
    if case.status != CaseStatus.AWAITING_CONSENT:
        raise Conflict("invalid_state", "This case is not awaiting consent")
    clinician = clinician_in_org(db, case.org_id, clinician_id)
    consent = PatientConsent(
        case_id=case.id,
        patient_id=case.patient_id,
        clinician_id=clinician.id,
        scope=CONSENT_SCOPE,
        purpose=CONSENT_PURPOSE,
        status=ConsentStatus.GRANTED,
        granted_at=now(),
    )
    db.add(consent)
    db.flush()
    workflow.transition(db, case, CaseStatus.CONSENT_GRANTED, actor=actor)
    audit.record(db, "consent.granted", "PatientConsent", consent.id, actor=actor, details={"case_id": str(case.id), "clinician_id": str(clinician.id), "scope": CONSENT_SCOPE})
    return consent


def withdraw_consent(db: Session, case: MedicalCase, actor: User) -> PatientConsent:
    consent = active_consent(case)
    if not consent:
        raise Conflict("no_consent", "There is no active consent to withdraw")
    consent.status = ConsentStatus.WITHDRAWN
    consent.withdrawn_at = now()
    for h in case.handoffs:
        if h.consent_id == consent.id and h.status in (HandoffStatus.SENT, HandoffStatus.ACKNOWLEDGED):
            h.status = HandoffStatus.CANCELLED
            notify(db, h.clinician.user_id, case, "A shared case is no longer available", "The patient withdrew consent for future access to a case shared with you.")
    for t in case.tasks:
        if t.status == TaskStatus.OPEN:
            t.status = TaskStatus.CANCELLED
    workflow.transition(db, case, CaseStatus.CONSENT_WITHDRAWN, actor=actor, reason="consent withdrawn")
    audit.record(db, "consent.withdrawn", "PatientConsent", consent.id, actor=actor, details={"case_id": str(case.id)})
    return consent


# --- Handoff -----------------------------------------------------------------------


def create_handoff(db: Session, case: MedicalCase, *, actor: User | None, actor_type: str) -> tuple[ClinicalHandoff, bool]:
    """Idempotent: returns (handoff, created). Consent is re-checked here, not trusted from the caller."""
    consent = active_consent(case)
    if not consent:
        raise Conflict("consent_required", "A clinician handoff requires active patient consent")
    existing = db.scalar(select(ClinicalHandoff).where(ClinicalHandoff.consent_id == consent.id))
    if existing:
        return existing, False
    if case.status != CaseStatus.CONSENT_GRANTED:
        raise Conflict("invalid_state", f"A handoff cannot be sent while the case is {case.status.value}")
    summary = active_summary(case)
    if not summary:
        raise Conflict("no_summary", "There is no validated summary to hand off")
    handoff = ClinicalHandoff(
        case_id=case.id,
        consent_id=consent.id,
        clinician_id=consent.clinician_id,
        summary_id=summary.id,
        status=HandoffStatus.SENT,
        sent_at=now(),
    )
    db.add(handoff)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ClinicalHandoff).where(ClinicalHandoff.consent_id == consent.id))
        if existing:
            return existing, False
        raise
    workflow.transition(db, case, CaseStatus.HANDOFF_SENT, actor=actor, actor_type=actor_type)
    audit.record(
        db, "handoff.sent", "ClinicalHandoff", handoff.id, actor=actor, actor_type=actor_type, org_id=case.org_id,
        details={"case_id": str(case.id), "clinician_id": str(consent.clinician_id), "consent_id": str(consent.id), "shared": consent.scope},
    )
    return handoff, True


def acknowledge(db: Session, case: MedicalCase, handoff: ClinicalHandoff, actor: User) -> None:
    if handoff.status != HandoffStatus.SENT:
        raise Conflict("invalid_state", "This handoff has already been acknowledged")
    handoff.status = HandoffStatus.ACKNOWLEDGED
    handoff.acknowledged_at = now()
    workflow.transition(db, case, CaseStatus.ACKNOWLEDGED, actor=actor)
    _complete_tasks(case, "ack_reminder")
    audit.record(db, "handoff.acknowledged", "ClinicalHandoff", handoff.id, actor=actor, details={"case_id": str(case.id)})
    notify(db, case.patient.user_id, case, "Your clinician received your report", f"{actor.full_name} acknowledged the handoff and will review your case.")


def start_review(db: Session, case: MedicalCase, handoff: ClinicalHandoff, actor: User) -> ClinicalReview:
    if case.status != CaseStatus.ACKNOWLEDGED:
        raise Conflict("invalid_state", "Acknowledge the handoff before starting a review")
    review = ClinicalReview(case_id=case.id, handoff_id=handoff.id, clinician_id=handoff.clinician_id)
    db.add(review)
    workflow.transition(db, case, CaseStatus.UNDER_REVIEW, actor=actor)
    audit.record(db, "review.started", "MedicalCase", case.id, actor=actor)
    return review


def review_for(case: MedicalCase, handoff: ClinicalHandoff) -> ClinicalReview | None:
    return next((r for r in case.reviews if r.handoff_id == handoff.id), None)


def assess_summary(db: Session, case: MedicalCase, handoff: ClinicalHandoff, actor: User, assessment: SummaryAssessment, correction: str | None) -> None:
    review = review_for(case, handoff)
    if case.status != CaseStatus.UNDER_REVIEW or not review:
        raise Conflict("invalid_state", "Start the review before assessing the summary")
    if assessment != SummaryAssessment.ACCURATE and not (correction and correction.strip()):
        raise AppError("correction_required", "Describe what is inaccurate when correcting or rejecting a summary")
    review.summary_assessment = assessment
    review.summary_correction = correction
    summary = db.get(AISummary, handoff.summary_id)
    if summary and assessment != SummaryAssessment.ACCURATE:
        summary.status = SummaryStatus.CORRECTED if assessment == SummaryAssessment.CORRECTED else SummaryStatus.REJECTED
        summary.clinician_correction = correction
    audit.record(db, "review.summary_assessed", "AISummary", handoff.summary_id, actor=actor, details={"case_id": str(case.id), "assessment": assessment.value})


def complete_review(db: Session, case: MedicalCase, handoff: ClinicalHandoff, actor: User, next_step: NextStep, clinical_notes: str | None, patient_message: str | None) -> ClinicalReview:
    review = review_for(case, handoff)
    if case.status != CaseStatus.UNDER_REVIEW or not review:
        raise Conflict("invalid_state", "Start the review before completing it")
    if not review.summary_assessment:
        raise AppError("assessment_required", "Mark the AI summary as accurate, corrected or rejected before completing the review")
    review.next_step = next_step
    review.clinical_notes = clinical_notes
    review.patient_message = patient_message
    review.completed_at = now()
    handoff.status = HandoffStatus.COMPLETED
    workflow.transition(db, case, CaseStatus.REVIEW_COMPLETED, actor=actor)
    _complete_tasks(case, "review_reminder")
    audit.record(db, "review.completed", "ClinicalReview", review.id, actor=actor, details={"case_id": str(case.id), "next_step": next_step.value})
    notify(db, case.patient.user_id, case, "Your clinician completed their review", "Open your case to see the clinician's next steps.")
    if next_step != NextStep.NO_FURTHER_ACTION:
        create_task(db, case, kind=f"next_step:{next_step.value}", description=NEXT_STEP_TASKS[next_step], assignee_role=UserRole.ADMIN, created_by=str(actor.id), due_in_hours=72)
    return review


NEXT_STEP_TASKS = {
    NextStep.SCHEDULE_APPOINTMENT: "Book a follow-up appointment for the patient with the reviewing clinician.",
    NextStep.REPEAT_TEST: "Arrange a repeat laboratory requisition as requested by the reviewing clinician.",
    NextStep.REFER_TO_SPECIALIST: "Prepare referral paperwork for clinician signature (referral is not sent automatically).",
    NextStep.CONTACT_PATIENT: "Clinic staff to contact the patient to discuss the review.",
    NextStep.NO_FURTHER_ACTION: "",
}


def close_case(db: Session, case: MedicalCase, actor: User) -> None:
    workflow.transition(db, case, CaseStatus.CLOSED, actor=actor)


# --- Follow-up ---------------------------------------------------------------------


def create_task(db: Session, case: MedicalCase, *, kind: str, description: str, assignee_role: UserRole, created_by: str, due_in_hours: int | None = None) -> tuple[FollowUpTask, bool]:
    key = f"{case.id}:{kind}"
    existing = db.scalar(select(FollowUpTask).where(FollowUpTask.dedupe_key == key))
    if existing:
        return existing, False
    task = FollowUpTask(
        case_id=case.id,
        kind=kind,
        description=description,
        assignee_role=assignee_role,
        created_by=created_by,
        dedupe_key=key,
        due_at=now() + timedelta(hours=due_in_hours) if due_in_hours else None,
    )
    db.add(task)
    db.flush()
    audit.record(db, "followup.created", "FollowUpTask", task.id, actor_type="AGENT" if created_by == "agent" else "USER", org_id=case.org_id, details={"case_id": str(case.id), "kind": kind})
    return task, True


def _complete_tasks(case: MedicalCase, kind: str) -> None:
    for t in case.tasks:
        if t.kind == kind and t.status == TaskStatus.OPEN:
            t.status = TaskStatus.DONE
            t.completed_at = now()


def set_task_status(db: Session, task: FollowUpTask, status: TaskStatus, actor: User) -> None:
    task.status = status
    task.completed_at = now() if status == TaskStatus.DONE else None
    audit.record(db, "followup.status_changed", "FollowUpTask", task.id, actor=actor, details={"case_id": str(task.case_id), "status": status.value})


def clinician_handoff(db: Session, case: MedicalCase, clinician: ClinicianProfile) -> ClinicalHandoff | None:
    return active_handoff_for(db, case.id, clinician.id)
