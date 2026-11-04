"""Symptom threads: the patient's conversation with CareBridge and their care team."""

import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, audit, serializers, services, storage, workflow
from app.agent import pipeline
from app.ai import voice
from app.db import get_db
from app.deps import clinician_user, patient_user
from app.errors import AppError, Conflict, NotFound
from app.models import (
    CaseKind,
    CaseStatus,
    ClinicalHandoff,
    HandoffStatus,
    MedicalCase,
    MedicalDocument,
    MessageAuthor,
    NextStep,
    SummaryAssessment,
    ThreadOutcome,
    Urgency,
    User,
)
from app.routers.clinician import _authorized_case_ids
from app.routers.patient import _read_pdf
from app.triage import brief, content, engine, routing
from app.triage.messages import post_message

patient_router = APIRouter(prefix="/api/patient", tags=["threads"])
clinician_router = APIRouter(prefix="/api/clinician", tags=["threads"])

Body = Field(min_length=1, max_length=4000)


def _patient_thread(db: Session, user: User, case_id: uuid.UUID) -> MedicalCase:
    case = access.patient_case(db, user, case_id)
    if case.kind != CaseKind.SYMPTOM:
        raise NotFound("Thread not found")
    return case


def _clinician_thread(db: Session, user: User, case_id: uuid.UUID) -> tuple[MedicalCase, ClinicalHandoff]:
    case, handoff = access.clinician_case(db, user, case_id)
    if case.kind != CaseKind.SYMPTOM:
        raise NotFound("Thread not found")
    return case, handoff


# --- Patient -----------------------------------------------------------------------


@patient_router.get("/dependents")
def list_dependents(user: User = Depends(patient_user)) -> list[dict]:
    return [
        {"id": str(d.id), "name": d.name, "date_of_birth": serializers.iso(d.date_of_birth), "relation": d.relation, "age_years": serializers._age(d.date_of_birth)}
        for d in user.patient_profile.dependents
    ]


class ThreadIn(BaseModel):
    subject_dependent_id: uuid.UUID | None = None
    body: str = Body
    consent_confirmed: Literal[True]


@patient_router.post("/threads", status_code=201)
def create_thread(body: ThreadIn, background: BackgroundTasks, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    case, a = engine.start_thread(db, user, body.body, body.subject_dependent_id)
    db.commit()
    background.add_task(engine.run_model_triage, a.id)
    return {"thread": serializers.patient_thread(case)}


@patient_router.get("/threads")
def list_threads(user: User = Depends(patient_user), db: Session = Depends(get_db)) -> list[dict]:
    cases = db.scalars(select(MedicalCase).where(MedicalCase.patient_id == user.patient_profile.id))
    rows = [serializers.thread_list_item(c) for c in cases]
    return sorted(rows, key=lambda r: r["last_message_at"] or "", reverse=True)


@patient_router.get("/threads/{case_id}")
def get_thread(case_id: uuid.UUID, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    return serializers.patient_thread(_patient_thread(db, user, case_id))


class MessageIn(BaseModel):
    body: str = Body


@patient_router.post("/threads/{case_id}/messages")
def patient_message(case_id: uuid.UUID, body: MessageIn, background: BackgroundTasks, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    case = _patient_thread(db, user, case_id)
    if case.status == CaseStatus.CLOSED:
        raise Conflict("closed", "This conversation is closed. Start a new one.")
    msg = post_message(db, case, MessageAuthor.PATIENT, body.body.strip(), author=user)
    a = engine.intake(db, case, msg)
    for h in case.handoffs:
        if h.status != HandoffStatus.CANCELLED and case.status != CaseStatus.CONSENT_WITHDRAWN:
            services.notify(db, h.clinician.user_id, case, "New message from a patient", "Open CareBridge to read it.")
    db.commit()
    background.add_task(engine.run_model_triage, a.id)
    return serializers.patient_thread(case)


class AnswerIn(BaseModel):
    question_id: str = Field(min_length=1, max_length=60)
    option: str = Field(min_length=1, max_length=60)


@patient_router.post("/threads/{case_id}/answers")
def answer(case_id: uuid.UUID, body: AnswerIn, background: BackgroundTasks, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    case = _patient_thread(db, user, case_id)
    a = engine.answer(db, case, body.question_id, body.option, user)
    db.commit()
    # Re-run the model once the round is fully answered, not after every tap.
    if not serializers.pending_questions(case):
        background.add_task(engine.run_model_triage, a.id)
    return serializers.patient_thread(case)


@patient_router.post("/threads/{case_id}/attachments", status_code=201)
async def attach(case_id: uuid.UUID, background: BackgroundTasks, file: UploadFile = File(...), user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    case = _patient_thread(db, user, case_id)
    if case.status == CaseStatus.CLOSED:
        raise Conflict("closed", "This conversation is closed")
    data = await _read_pdf(file)
    key, digest = storage.save(case.id, data)
    doc = MedicalDocument(case_id=case.id, filename=(file.filename or "report.pdf")[:255], storage_key=key, content_type="application/pdf", size_bytes=len(data), sha256=digest)
    db.add(doc)
    db.flush()
    audit.record(db, "document.uploaded", "MedicalDocument", doc.id, actor=user, details={"case_id": str(case.id), "size_bytes": len(data)})
    post_message(db, case, MessageAuthor.PATIENT, f"Attached {doc.filename}", {"kind": "report", "document_id": str(doc.id)}, author=user)
    ex = pipeline.start_document_processing(db, case, doc, user)
    background.add_task(pipeline.run_processing, ex.id)
    return {"document_id": str(doc.id)}


@patient_router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    """Turn a spoken message into text with Muse Voice Transcribe. The patient reviews it before sending."""
    data = await audio.read(voice.MAX_BYTES + 1)
    problem = voice.check_wav(data)
    if problem:
        raise AppError("unsupported_audio", problem)
    try:
        text = voice.transcribe(db, data, user.org_id)
    except voice.VoiceError:
        db.commit()  # keep the failed call in the model log
        raise AppError("transcription_failed", "We couldn't transcribe that recording. Please try again or type your message.", 502)
    audit.record(db, "voice.transcribed", "User", user.id, actor=user, details={"model_id": voice.MODEL_ID})
    db.commit()
    if not text:
        raise AppError("no_speech", "We didn't catch any speech. Please try again.", 422)
    return {"transcript": text}


# --- Clinician ---------------------------------------------------------------------


@clinician_router.get("/queue")
def queue(user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> list[dict]:
    ids = _authorized_case_ids(db, user)
    if not ids:
        return []
    cases = db.scalars(select(MedicalCase).where(MedicalCase.id.in_(ids), MedicalCase.status != CaseStatus.CLOSED))
    rows = []
    for c in cases:
        h = next((h for h in c.handoffs if h.clinician_id == user.clinician_profile.id and h.status != HandoffStatus.CANCELLED), None)
        rows.append(serializers.queue_row(c, h))
    rows.sort(key=lambda r: (-r["_rank"], r["ack_due_at"] or "9999", r["first_message_at"] or ""))
    for r in rows:
        r.pop("_rank")
    return rows


@clinician_router.get("/threads/{case_id}")
def clinician_get_thread(case_id: uuid.UUID, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    case, handoff = _clinician_thread(db, user, case_id)
    if handoff.first_accessed_at is None:
        handoff.first_accessed_at = services.now()
    audit.record(db, "clinician.case_viewed", "MedicalCase", case.id, actor=user, details={"handoff_id": str(handoff.id)})
    db.commit()
    return serializers.clinician_thread(case, handoff)


@clinician_router.post("/threads/{case_id}/acknowledge")
def clinician_acknowledge(case_id: uuid.UUID, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    case, handoff = _clinician_thread(db, user, case_id)
    routing.acknowledge(db, case, handoff, user)
    db.commit()
    return {"status": case.status.value}


@clinician_router.post("/threads/{case_id}/messages")
def clinician_message(case_id: uuid.UUID, body: MessageIn, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    case, handoff = _clinician_thread(db, user, case_id)
    if case.status == CaseStatus.CLOSED:
        raise Conflict("closed", "This conversation is closed")
    routing.acknowledge(db, case, handoff, user)  # replying implies you've seen it
    post_message(db, case, MessageAuthor.CLINICIAN, body.body.strip(), {"kind": "clinician_reply"}, author=user)
    if case.status == CaseStatus.ACKNOWLEDGED:
        workflow.transition(db, case, CaseStatus.IN_CONVERSATION, actor=user)
    services.notify(db, case.patient.user_id, case, "Your clinician replied", "Open CareBridge to read it.")
    audit.record(db, "thread.clinician_replied", "MedicalCase", case.id, actor=user)
    db.commit()
    return {"status": case.status.value}


class UrgencyIn(BaseModel):
    level: Urgency
    reason: str = Field(min_length=1, max_length=500)


@clinician_router.post("/threads/{case_id}/urgency")
def change_urgency(case_id: uuid.UUID, body: UrgencyIn, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    case, _ = _clinician_thread(db, user, case_id)
    case = engine.lock_case(db, case.id)
    previous = case.urgency
    if body.level == previous:
        raise Conflict("same_urgency", "The thread is already at that urgency")
    case.urgency, case.urgency_set_by = body.level, "clinician"
    case.urgency_baseline_flags = list(dict.fromkeys(code for a in case.triage_assessments for code in a.rule_flags))
    audit.record(db, "triage.urgency_changed", "MedicalCase", case.id, actor=user, details={"from": previous.value if previous else None, "to": body.level.value, "reason": body.reason})
    post_message(db, case, MessageAuthor.SYSTEM, f"{user.full_name} updated how urgent this is.\n\n{content.GUIDANCE[body.level]}", {"kind": "guidance", "level": body.level.value, "set_by": "clinician"})
    routing.apply_level(db, case, body.level, services.now())
    db.commit()
    return {"urgency": case.urgency.value}


class BriefAssessmentIn(BaseModel):
    assessment: SummaryAssessment
    correction: str | None = Field(default=None, max_length=4000)


@clinician_router.post("/threads/{case_id}/brief-assessment")
def assess_brief(case_id: uuid.UUID, body: BriefAssessmentIn, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    case, _ = _clinician_thread(db, user, case_id)
    b = brief.assess(db, case, user, body.assessment, body.correction)
    db.commit()
    return {"assessment": b.assessment.value}


OUTCOMES = {o.value for o in ThreadOutcome} | {n.value for n in NextStep}


class OutcomeIn(BaseModel):
    outcome: str
    note: str | None = Field(default=None, max_length=4000)


@clinician_router.post("/threads/{case_id}/outcome")
def record_outcome(case_id: uuid.UUID, body: OutcomeIn, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    if body.outcome not in OUTCOMES:
        raise AppError("invalid_outcome", f"Outcome must be one of: {', '.join(sorted(OUTCOMES))}")
    case, _ = _clinician_thread(db, user, case_id)
    case.outcome, case.outcome_note = body.outcome, body.note
    audit.record(db, "thread.outcome_recorded", "MedicalCase", case.id, actor=user, details={"outcome": body.outcome})
    db.commit()
    return {"outcome": case.outcome}


@clinician_router.post("/threads/{case_id}/close")
def close_thread(case_id: uuid.UUID, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    case, _ = _clinician_thread(db, user, case_id)
    if case.status not in (CaseStatus.ACKNOWLEDGED, CaseStatus.IN_CONVERSATION):
        raise Conflict("invalid_state", "Acknowledge the conversation before closing it")
    for h in case.handoffs:
        if h.status in (HandoffStatus.SENT, HandoffStatus.ACKNOWLEDGED):
            h.status = HandoffStatus.COMPLETED
    workflow.transition(db, case, CaseStatus.CLOSED, actor=user)
    post_message(db, case, MessageAuthor.SYSTEM, f"{user.full_name} closed this conversation. Start a new one any time.", {"kind": "closed"})
    services.notify(db, case.patient.user_id, case, "Your conversation was closed", "Open CareBridge for details.")
    db.commit()
    return {"status": case.status.value}
