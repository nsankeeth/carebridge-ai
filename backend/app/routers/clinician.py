import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, audit, serializers, services, storage
from app.db import get_db
from app.deps import clinician_user
from app.errors import NotFound
from app.models import (
    AgentExecution,
    ClinicalHandoff,
    ConsentStatus,
    FollowUpTask,
    HandoffStatus,
    MedicalCase,
    NextStep,
    PatientConsent,
    SummaryAssessment,
    TaskStatus,
    User,
)

router = APIRouter(prefix="/api/clinician", tags=["clinician"])


def _authorized_case_ids(db: Session, user: User) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(ClinicalHandoff.case_id)
            .join(PatientConsent, PatientConsent.id == ClinicalHandoff.consent_id)
            .where(
                ClinicalHandoff.clinician_id == user.clinician_profile.id,
                ClinicalHandoff.status != HandoffStatus.CANCELLED,
                PatientConsent.status == ConsentStatus.GRANTED,
            )
        )
    )


@router.get("/cases")
def list_cases(user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> list[dict]:
    ids = _authorized_case_ids(db, user)
    cases = db.scalars(select(MedicalCase).where(MedicalCase.id.in_(ids)).order_by(MedicalCase.updated_at.desc())) if ids else []
    return [serializers.case_list_item(c) for c in cases]


@router.get("/cases/{case_id}")
def get_case(case_id: uuid.UUID, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    case, handoff = access.clinician_case(db, user, case_id)
    if handoff.first_accessed_at is None:
        handoff.first_accessed_at = services.now()
    audit.record(db, "clinician.case_viewed", "MedicalCase", case.id, actor=user, details={"handoff_id": str(handoff.id)})
    db.commit()
    executions = list(db.scalars(select(AgentExecution).where(AgentExecution.case_id == case.id).order_by(AgentExecution.started_at.desc()).limit(10)))
    return serializers.clinician_case(case, executions)


@router.get("/cases/{case_id}/document")
def get_document(case_id: uuid.UUID, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> Response:
    case, handoff = access.clinician_case(db, user, case_id)
    if not case.documents:
        raise NotFound("No report uploaded")
    doc = case.documents[-1]
    audit.record(db, "clinician.document_viewed", "MedicalDocument", doc.id, actor=user, details={"case_id": str(case.id)})
    db.commit()
    return Response(storage.load(doc.storage_key), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{doc.filename}"', "Cache-Control": "no-store"})


@router.post("/cases/{case_id}/acknowledge")
def acknowledge(case_id: uuid.UUID, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    case, handoff = access.clinician_case(db, user, case_id)
    services.acknowledge(db, case, handoff, user)
    db.commit()
    return {"status": case.status.value}


@router.post("/cases/{case_id}/review/start")
def start_review(case_id: uuid.UUID, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    case, handoff = access.clinician_case(db, user, case_id)
    services.start_review(db, case, handoff, user)
    db.commit()
    return {"status": case.status.value}


class AssessmentIn(BaseModel):
    assessment: SummaryAssessment
    correction: str | None = Field(default=None, max_length=4000)


@router.post("/cases/{case_id}/summary-assessment")
def assess_summary(case_id: uuid.UUID, body: AssessmentIn, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    case, handoff = access.clinician_case(db, user, case_id)
    services.assess_summary(db, case, handoff, user, body.assessment, body.correction)
    db.commit()
    return {"ok": True}


class CompleteIn(BaseModel):
    next_step: NextStep
    clinical_notes: str | None = Field(default=None, max_length=8000)
    patient_message: str | None = Field(default=None, max_length=2000)


@router.post("/cases/{case_id}/review/complete")
def complete_review(case_id: uuid.UUID, body: CompleteIn, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    case, handoff = access.clinician_case(db, user, case_id)
    services.complete_review(db, case, handoff, user, body.next_step, body.clinical_notes, body.patient_message)
    db.commit()
    return {"status": case.status.value}


@router.get("/tasks")
def list_tasks(user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> list[dict]:
    ids = _authorized_case_ids(db, user)
    if not ids:
        return []
    rows = db.scalars(select(FollowUpTask).where(FollowUpTask.case_id.in_(ids)).order_by(FollowUpTask.created_at.desc()))
    return [serializers.task(t) for t in rows]


class TaskStatusIn(BaseModel):
    status: TaskStatus


@router.patch("/tasks/{task_id}")
def update_task(task_id: uuid.UUID, body: TaskStatusIn, user: User = Depends(clinician_user), db: Session = Depends(get_db)) -> dict:
    task = db.get(FollowUpTask, task_id)
    if not task or task.case_id not in _authorized_case_ids(db, user):
        raise NotFound("Task not found")
    services.set_task_status(db, task, body.status, user)
    db.commit()
    return serializers.task(task)
