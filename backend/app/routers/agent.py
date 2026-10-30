import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, serializers
from app.agent import pipeline
from app.config import get_settings
from app.db import get_db
from app.deps import current_user, patient_user
from app.errors import Conflict, NotFound
from app.models import AgentExecution, CaseStatus, ExecutionStatus, ModelCall, User, UserRole

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/cases/{case_id}/process", status_code=202)
def start_processing(case_id: uuid.UUID, background: BackgroundTasks, user: User = Depends(patient_user), db: Session = Depends(get_db)) -> dict:
    """Start (or retry) the report-processing agent for a patient's own case."""
    case = access.patient_case(db, user, case_id)
    running = db.scalar(select(AgentExecution).where(AgentExecution.case_id == case.id, AgentExecution.kind == "PROCESSING", AgentExecution.status == ExecutionStatus.RUNNING))
    if running:
        return serializers.execution(running)
    if case.status not in (CaseStatus.UPLOADED, CaseStatus.PROCESSING_FAILED, CaseStatus.NEEDS_CORRECTION, CaseStatus.SUMMARY_READY):
        raise Conflict("invalid_state", f"Processing can't be started while the case is {case.status.value}")
    try:
        ex = pipeline.start_processing(db, case, user)
    except pipeline.StepFailed as e:
        raise Conflict("no_document", str(e))
    background.add_task(pipeline.run_processing, ex.id)
    return serializers.execution(ex)


@router.get("/executions/{execution_id}")
def get_execution(execution_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    ex = db.get(AgentExecution, execution_id)
    if not ex:
        raise NotFound("Execution not found")
    # Reuse case-level authorization: you may see a run only if you may see its case.
    if user.role == UserRole.PATIENT:
        access.patient_case(db, user, ex.case_id)
    elif user.role == UserRole.CLINICIAN:
        access.clinician_case(db, user, ex.case_id)
    else:
        raise NotFound("Execution not found")
    out = serializers.execution(ex)
    out["model_calls"] = [serializers.model_call(m) for m in db.scalars(select(ModelCall).where(ModelCall.execution_id == ex.id).order_by(ModelCall.created_at))]
    return out


@router.get("/status")
def ai_status(_: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Which model provider is configured and when it last answered successfully. No secrets."""
    s = get_settings()
    last_ok = db.scalar(select(ModelCall).where(ModelCall.status == "ok").order_by(ModelCall.created_at.desc()))
    return {
        "provider": "meta",
        "model": s.meta_model,
        "base_url": s.meta_base_url,
        "api_key_configured": bool(s.model_api_key),
        "last_successful_meta_call": serializers.model_call(last_ok) if last_ok else None,
    }
