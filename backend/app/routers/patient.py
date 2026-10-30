import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, audit, serializers, services, storage
from app.agent import coordinator, pipeline
from app.config import get_settings
from app.db import get_db
from app.deps import patient_user
from app.errors import AppError, Conflict
from app.models import (
    AgentExecution,
    CaseStatus,
    ClinicianProfile,
    ExecutionStatus,
    MedicalCase,
    MedicalDocument,
    User,
    UserRole,
)

router = APIRouter(prefix="/api/patient", tags=["patient"])


def _executions(db: Session, case_id: uuid.UUID) -> list[AgentExecution]:
    return list(db.scalars(select(AgentExecution).where(AgentExecution.case_id == case_id).order_by(AgentExecution.started_at.desc()).limit(10)))


@router.get("/cases")
def list_cases(user: User = Depends(patient_user), db: Session = Depends(get_db)) -> list[dict]:
    cases = db.scalars(select(MedicalCase).where(MedicalCase.patient_id == user.patient_profile.id).order_by(MedicalCase.created_at.desc()))
    return [serializers.case_list_item(c) for c in cases]


class CaseIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.post("/cases", status_code=201)
def create_case(body: CaseIn, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    case = MedicalCase(org_id=user.org_id, patient_id=user.patient_profile.id, title=body.title.strip(), status=CaseStatus.UPLOADED)
    db.add(case)
    db.flush()
    audit.record(db, "case.created", "MedicalCase", case.id, actor=user)
    db.commit()
    return serializers.case_list_item(case)


async def _read_pdf(file: UploadFile) -> bytes:
    data = await file.read(get_settings().max_upload_bytes + 1)
    if len(data) > get_settings().max_upload_bytes:
        raise AppError("file_too_large", "Reports must be 10 MB or smaller", 413)
    if not data.startswith(b"%PDF-"):
        raise AppError("invalid_file", "Only PDF reports are supported")
    return data


def _attach(db: Session, case: MedicalCase, user: User, file: UploadFile, data: bytes) -> MedicalDocument:
    if case.status not in (CaseStatus.UPLOADED, CaseStatus.PROCESSING_FAILED, CaseStatus.NEEDS_CORRECTION):
        raise Conflict("invalid_state", "A report can't be uploaded to this case in its current state")
    key, digest = storage.save(case.id, data)
    doc = MedicalDocument(case_id=case.id, filename=(file.filename or "report.pdf")[:255], storage_key=key, content_type="application/pdf", size_bytes=len(data), sha256=digest)
    db.add(doc)
    db.flush()
    db.refresh(case)
    audit.record(db, "document.uploaded", "MedicalDocument", doc.id, actor=user, details={"case_id": str(case.id), "size_bytes": len(data)})
    return doc


@router.post("/cases/upload", status_code=201)
async def create_case_with_report(
    background: BackgroundTasks,
    title: str = Form(min_length=1, max_length=200),
    file: UploadFile = File(...),
    user: User = Depends(patient_user),
    db: Session = Depends(get_db),
) -> dict:
    """Create a case, upload the PDF, and start the processing agent in one step."""
    data = await _read_pdf(file)
    case = MedicalCase(org_id=user.org_id, patient_id=user.patient_profile.id, title=title.strip(), status=CaseStatus.UPLOADED)
    db.add(case)
    db.flush()
    audit.record(db, "case.created", "MedicalCase", case.id, actor=user)
    _attach(db, case, user, file, data)
    ex = pipeline.start_processing(db, case, user)
    background.add_task(pipeline.run_processing, ex.id)
    return {"case": serializers.case_list_item(case), "execution": serializers.execution(ex)}


@router.post("/cases/{case_id}/documents", status_code=201)
async def upload_report(
    case_id: uuid.UUID,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    process: bool = True,
    user: User = Depends(patient_user),
    db: Session = Depends(get_db),
) -> dict:
    case = access.patient_case(db, user, case_id)
    data = await _read_pdf(file)
    doc = _attach(db, case, user, file, data)
    ex = None
    if process:
        ex = pipeline.start_processing(db, case, user)
        background.add_task(pipeline.run_processing, ex.id)
    else:
        db.commit()
    return {"document_id": str(doc.id), "execution": serializers.execution(ex)}


@router.get("/cases/{case_id}")
def get_case(case_id: uuid.UUID, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    case = access.patient_case(db, user, case_id)
    return serializers.patient_case(case, _executions(db, case.id))


@router.get("/cases/{case_id}/findings")
def get_findings(case_id: uuid.UUID, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> list[dict]:
    case = access.patient_case(db, user, case_id)
    return [serializers.finding(f) for f in case.findings]


@router.get("/cases/{case_id}/explanation")
def get_explanation(case_id: uuid.UUID, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict | None:
    case = access.patient_case(db, user, case_id)
    return serializers.summary(services.active_summary(case), clinician=False)


@router.get("/cases/{case_id}/document")
def get_document(case_id: uuid.UUID, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> Response:
    case = access.patient_case(db, user, case_id)
    if not case.documents:
        raise AppError("no_document", "No report uploaded", 404)
    doc = case.documents[-1]
    return Response(storage.load(doc.storage_key), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{doc.filename}"', "Cache-Control": "no-store"})


@router.get("/cases/{case_id}/sharing")
def sharing_preview(case_id: uuid.UUID, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    """Everything the patient needs to see before consenting: what, to whom, and why."""
    case = access.patient_case(db, user, case_id)
    clinicians = db.scalars(select(ClinicianProfile).join(User).where(User.org_id == user.org_id, User.role == UserRole.CLINICIAN, User.is_active.is_(True)))
    summary = services.active_summary(case)
    return {
        "status": case.status.value,
        "scope": [
            {"key": "original_report", "label": "Your original report (PDF)"},
            {"key": "extracted_findings", "label": f"{len(case.findings)} extracted results"},
            {"key": "ai_clinician_summary", "label": "The AI-prepared summary for clinician review"},
        ],
        "purpose": services.CONSENT_PURPOSE,
        "clinicians": [{"id": str(c.id), "name": c.user.full_name, "specialty": c.specialty, "clinic_name": c.clinic_name} for c in clinicians],
        "summary_available": summary is not None,
        "notes": [
            "You can withdraw consent at any time to stop future access.",
            "Withdrawing does not undo access that has already happened.",
            "Sharing does not guarantee a response time. In an emergency, contact emergency services.",
        ],
    }


@router.post("/cases/{case_id}/consent/request")
def request_consent(case_id: uuid.UUID, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    case = access.patient_case(db, user, case_id)
    services.request_consent(db, case, user)
    db.commit()
    return {"status": case.status.value}


class ConsentIn(BaseModel):
    clinician_id: uuid.UUID
    confirmed: bool


@router.post("/cases/{case_id}/consent")
def grant_consent(case_id: uuid.UUID, body: ConsentIn, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    case = access.patient_case(db, user, case_id)
    with db.begin_nested():
        consent = services.grant_consent(db, case, user, body.clinician_id, body.confirmed)
    db.commit()
    return {"consent_id": str(consent.id), "status": case.status.value}


@router.post("/cases/{case_id}/consent/withdraw")
def withdraw_consent(case_id: uuid.UUID, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    case = access.patient_case(db, user, case_id)
    services.withdraw_consent(db, case, user)
    db.commit()
    return {"status": case.status.value}


@router.post("/cases/{case_id}/handoff", status_code=202)
def submit_handoff(case_id: uuid.UUID, background: BackgroundTasks, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    """Ask the coordinator agent to hand the case off. Idempotent: repeats return the same run or handoff."""
    case = access.patient_case(db, user, case_id)
    consent = services.active_consent(case)
    if not consent:
        raise Conflict("consent_required", "Grant consent before sending your case to a clinician")
    running = db.scalar(select(AgentExecution).where(AgentExecution.case_id == case.id, AgentExecution.kind == "HANDOFF", AgentExecution.status == ExecutionStatus.RUNNING))
    if running:
        return {"execution": serializers.execution(running), "status": case.status.value}
    if case.status != CaseStatus.CONSENT_GRANTED:
        return {"execution": None, "status": case.status.value}
    ex = coordinator.start(db, case, "HANDOFF", user)
    background.add_task(coordinator.run, ex.id, user.id)
    return {"execution": serializers.execution(ex), "status": case.status.value}


@router.get("/cases/{case_id}/handoff")
def handoff_status(case_id: uuid.UUID, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    case = access.patient_case(db, user, case_id)
    item = serializers.case_list_item(case)
    return {"status": case.status.value, "handoff": item["handoff"]}


@router.post("/cases/{case_id}/close")
def close_case(case_id: uuid.UUID, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    case = access.patient_case(db, user, case_id)
    services.close_case(db, case, user)
    db.commit()
    return {"status": case.status.value}
