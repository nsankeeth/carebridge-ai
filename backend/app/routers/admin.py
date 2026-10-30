"""Administration. Admins see workflow metadata, audit and model telemetry, never report contents."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, serializers, services
from app.agent import coordinator
from app.db import get_db
from app.deps import admin_user
from app.errors import Conflict, NotFound
from app.models import (
    AgentExecution,
    AuditEvent,
    ClinicianProfile,
    FollowUpTask,
    MedicalCase,
    ModelCall,
    PatientProfile,
    TaskStatus,
    User,
    UserRole,
)
from app.security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/overview")
def overview(user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    by_status = dict(db.execute(select(MedicalCase.status, func.count()).where(MedicalCase.org_id == user.org_id).group_by(MedicalCase.status)).all())
    cases = db.scalars(select(MedicalCase).where(MedicalCase.org_id == user.org_id).order_by(MedicalCase.updated_at.desc()).limit(50))
    calls = db.execute(
        select(ModelCall.provider, ModelCall.model_id, ModelCall.status, func.count(), func.avg(ModelCall.latency_ms), func.sum(ModelCall.total_tokens))
        .join(MedicalCase, MedicalCase.id == ModelCall.case_id)
        .where(MedicalCase.org_id == user.org_id)
        .group_by(ModelCall.provider, ModelCall.model_id, ModelCall.status)
    ).all()
    return {
        "cases_by_status": {k.value: v for k, v in by_status.items()},
        "cases": [
            {"id": str(c.id), "status": c.status.value, "patient_name": c.patient.user.full_name, "created_at": serializers.iso(c.created_at), "updated_at": serializers.iso(c.updated_at), "open_tasks": sum(t.status == TaskStatus.OPEN for t in c.tasks)}
            for c in cases
        ],
        "model_usage": [
            {"provider": p, "model_id": m, "status": st, "calls": n, "avg_latency_ms": round(lat or 0), "total_tokens": int(tok or 0)}
            for p, m, st, n, lat, tok in calls
        ],
    }


@router.get("/users")
def list_users(user: User = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    return [serializers.user(u) for u in db.scalars(select(User).where(User.org_id == user.org_id).order_by(User.role, User.full_name))]


class UserIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: UserRole
    password: str = Field(min_length=8, max_length=200)
    specialty: str | None = Field(default=None, max_length=100)


@router.post("/users", status_code=201)
def create_user(body: UserIn, user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise Conflict("email_taken", "A user with that email already exists")
    new = User(org_id=user.org_id, email=body.email.lower(), full_name=body.full_name, role=body.role, password_hash=hash_password(body.password))
    db.add(new)
    db.flush()
    if body.role == UserRole.PATIENT:
        db.add(PatientProfile(user_id=new.id, province="ON", synthetic_health_ref=f"SYN-{uuid.uuid4().hex[:8].upper()}"))
    elif body.role == UserRole.CLINICIAN:
        db.add(ClinicianProfile(user_id=new.id, specialty=body.specialty or "Family Medicine", clinic_name="Demo Clinic"))
    audit.record(db, "admin.user_created", "User", new.id, actor=user, details={"role": body.role.value})
    db.commit()
    db.refresh(new)
    return serializers.user(new)


class UserPatch(BaseModel):
    is_active: bool


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserPatch, user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    target = db.get(User, user_id)
    if not target or target.org_id != user.org_id:
        raise NotFound("User not found")
    if target.id == user.id:
        raise Conflict("self_update", "You cannot deactivate yourself")
    target.is_active = body.is_active
    target.token_version += 1
    audit.record(db, "admin.user_updated", "User", target.id, actor=user, details={"is_active": body.is_active})
    db.commit()
    return serializers.user(target)


@router.get("/audit")
def audit_log(
    action: str | None = None,
    resource_id: str | None = None,
    limit: int = Query(default=100, le=500),
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = select(AuditEvent, User.full_name).outerjoin(User, User.id == AuditEvent.actor_user_id).where(AuditEvent.org_id == user.org_id)
    if action:
        q = q.where(AuditEvent.action.like(f"{action}%"))
    if resource_id:
        q = q.where(AuditEvent.resource_id == resource_id)
    rows = db.execute(q.order_by(AuditEvent.created_at.desc()).limit(limit)).all()
    return [
        {"id": str(e.id), "action": e.action, "actor_type": e.actor_type, "actor_name": name, "resource_type": e.resource_type, "resource_id": e.resource_id, "details": e.details, "created_at": serializers.iso(e.created_at)}
        for e, name in rows
    ]


@router.get("/tasks")
def list_tasks(user: User = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(FollowUpTask).join(MedicalCase).where(MedicalCase.org_id == user.org_id).order_by(FollowUpTask.created_at.desc()))
    return [serializers.task(t) for t in rows]


class TaskStatusIn(BaseModel):
    status: TaskStatus


@router.patch("/tasks/{task_id}")
def update_task(task_id: uuid.UUID, body: TaskStatusIn, user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    task = db.get(FollowUpTask, task_id)
    if not task or task.case.org_id != user.org_id or task.assignee_role != UserRole.ADMIN:
        raise NotFound("Task not found")
    services.set_task_status(db, task, body.status, user)
    db.commit()
    return serializers.task(task)


@router.post("/follow-up/run", status_code=202)
def run_follow_up(background: BackgroundTasks, user: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    """Run the follow-up coordinator agent over every case that might need administrative action."""
    started = []
    for case in coordinator.follow_up_candidates(db, user.org_id):
        ex = coordinator.start(db, case, "FOLLOW_UP", user)
        background.add_task(coordinator.run, ex.id, user.id)
        started.append({"case_id": str(case.id), "execution_id": str(ex.id)})
    return {"started": started}


@router.get("/executions")
def executions(limit: int = Query(default=50, le=200), user: User = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(AgentExecution).join(MedicalCase).where(MedicalCase.org_id == user.org_id).order_by(AgentExecution.started_at.desc()).limit(limit))
    out = []
    for e in rows:
        d = serializers.execution(e)
        d["case_id"] = str(e.case_id)
        # Steps can echo tool results; admins get names and outcomes only.
        d["steps"] = [{k: s.get(k) for k in ("name", "type", "tool", "status", "ok", "turn", "model", "duration_ms")} for s in e.steps]
        out.append(d)
    return out


@router.get("/model-calls")
def model_calls(limit: int = Query(default=100, le=500), user: User = Depends(admin_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(ModelCall).join(MedicalCase, MedicalCase.id == ModelCall.case_id).where(MedicalCase.org_id == user.org_id).order_by(ModelCall.created_at.desc()).limit(limit))
    return [serializers.model_call(m) for m in rows]
