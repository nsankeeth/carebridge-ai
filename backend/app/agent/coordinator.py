"""F/G. Handoff and follow-up coordinator: Meta-model tool calling over a narrow, allow-listed toolset.

The model decides which tools to call from the case snapshot. Each tool is a thin wrapper over
`app.services`, which enforces consent, permissions and valid state transitions. The model can't
change case status directly, and it never sees result values.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, services
from app.agent.pipeline import record_model_call
from app.agent.validation import admin_message_issues
from app.ai import prompts
from app.ai.provider import ModelCallError, ToolCall, get_provider, tool_args
from app.config import get_settings
from app.db import SessionLocal
from app.errors import AppError
from app.models import (
    AgentExecution,
    CaseStatus,
    ClinicalHandoff,
    ExecutionStatus,
    FindingStatus,
    HandoffStatus,
    MedicalCase,
    TaskStatus,
    User,
    UserRole,
)

log = logging.getLogger("agent.coordinator")
MAX_TURNS = 6

TASK_KINDS = {
    # kind -> (statuses in which it is allowed, default assignee)
    "ack_reminder": ({CaseStatus.HANDOFF_SENT}, UserRole.CLINICIAN),
    "review_reminder": ({CaseStatus.ACKNOWLEDGED, CaseStatus.UNDER_REVIEW}, UserRole.CLINICIAN),
    "patient_update": ({CaseStatus.REVIEW_COMPLETED}, UserRole.ADMIN),
    "consent_reminder": ({CaseStatus.SUMMARY_READY, CaseStatus.AWAITING_CONSENT}, UserRole.PATIENT),
    "data_correction": ({CaseStatus.NEEDS_CORRECTION, CaseStatus.PROCESSING_FAILED}, UserRole.ADMIN),
}


def _fn(name: str, description: str, properties: dict[str, Any] | None = None) -> dict[str, Any]:
    properties = properties or {}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False},
            "strict": True,
        },
    }


_MSG = {"title": {"type": "string", "description": "Short administrative title"}, "body": {"type": "string", "description": "Administrative message. No test names, values or medical details."}}

TOOL_DEFS = {
    "get_case_snapshot": _fn("get_case_snapshot", "Read the current workflow state of the case: status, consent, handoff, review and open follow-up tasks. Contains no medical values."),
    "create_clinician_handoff": _fn("create_clinician_handoff", "Send the report and validated AI summary to the clinician the patient consented to share with. Fails if consent is missing or withdrawn. Safe to call once."),
    "create_follow_up_task": _fn(
        "create_follow_up_task",
        "Open an administrative follow-up task for this case. Duplicate kinds are ignored.",
        {
            "kind": {"type": "string", "enum": list(TASK_KINDS)},
            "description": {"type": "string", "description": "What needs to happen, administrative only"},
            "due_in_hours": {"type": "integer", "description": "1 to 168"},
        },
    ),
    "notify_patient": _fn("notify_patient", "Send the patient an in-app administrative update about their case workflow.", _MSG),
    "notify_clinician": _fn("notify_clinician", "Send the assigned clinician an in-app administrative message about this case.", _MSG),
}

MODE_TOOLS = {
    "HANDOFF": ["get_case_snapshot", "create_clinician_handoff", "notify_patient", "notify_clinician", "create_follow_up_task"],
    "FOLLOW_UP": ["get_case_snapshot", "create_follow_up_task", "notify_patient", "notify_clinician"],
}

MODE_GOALS = {
    "HANDOFF": "The patient has granted consent and asked to send their case to their clinician. Complete the handoff and keep both parties informed.",
    "FOLLOW_UP": "Run a follow-up check on this case. Identify outstanding workflow tasks (for example an unacknowledged handoff past its acknowledgment window, a review in progress, or a patient awaiting an update) and take only the administrative actions needed. If nothing is needed, do nothing.",
}


def _hours_since(ts: datetime | None) -> float | None:
    return round((datetime.now(timezone.utc) - ts).total_seconds() / 3600, 1) if ts else None


def case_snapshot(db: Session, case: MedicalCase) -> dict[str, Any]:
    consent = services.active_consent(case)
    handoff = case.handoffs[-1] if case.handoffs else None
    review = case.reviews[-1] if case.reviews else None
    summary = services.active_summary(case)
    return {
        "case_id": str(case.id),
        "status": case.status.value,
        "hours_since_last_update": _hours_since(case.updated_at),
        "summary_ready": summary is not None,
        "items_flagged_for_clinician_review": len(summary.patient_explanation.get("items_for_clinician_review", [])) if summary else 0,
        "findings_needing_data_review": sum(f.status == FindingStatus.NEEDS_REVIEW for f in case.findings),
        "consent": {"granted": True, "recipient": consent.clinician.user.full_name, "hours_since_granted": _hours_since(consent.granted_at)} if consent else {"granted": False},
        "handoff": {
            "status": handoff.status.value,
            "hours_since_sent": _hours_since(handoff.sent_at),
            "acknowledged": handoff.acknowledged_at is not None,
            "acknowledgment_window_hours": get_settings().ack_sla_hours,
        } if handoff else None,
        "review": {"started": True, "completed": review.completed_at is not None, "next_step": review.next_step.value if review.next_step else None} if review else None,
        "open_follow_up_tasks": [t.kind for t in case.tasks if t.status == TaskStatus.OPEN],
    }


class ToolRunner:
    def __init__(self, db: Session, case: MedicalCase, mode: str, triggered_by: User | None):
        self.db, self.case, self.mode, self.triggered_by = db, case, mode, triggered_by
        self.sent: set[str] = set()

    def run(self, call: ToolCall) -> dict[str, Any]:
        if call.name not in MODE_TOOLS[self.mode]:
            return {"ok": False, "error": f"Tool {call.name} is not available in this workflow"}
        handler: Callable[[dict[str, Any]], dict[str, Any]] = getattr(self, f"_t_{call.name}")
        try:
            result = handler(tool_args(call))
            self.db.commit()
            return result
        except AppError as e:
            self.db.rollback()
            return {"ok": False, "error": e.message, "code": e.code}

    def _current_handoff(self) -> ClinicalHandoff | None:
        # Query rather than read case.handoffs: a handoff created earlier in this run isn't in the cached relationship.
        return self.db.scalar(
            select(ClinicalHandoff)
            .where(ClinicalHandoff.case_id == self.case.id, ClinicalHandoff.status != HandoffStatus.CANCELLED)
            .order_by(ClinicalHandoff.sent_at.desc())
        )

    def _t_get_case_snapshot(self, _: dict[str, Any]) -> dict[str, Any]:
        self.db.refresh(self.case)
        return {"ok": True, "snapshot": case_snapshot(self.db, self.case)}

    def _t_create_clinician_handoff(self, _: dict[str, Any]) -> dict[str, Any]:
        handoff, created = services.create_handoff(self.db, self.case, actor=None, actor_type="AGENT")
        return {"ok": True, "created": created, "handoff_status": handoff.status.value, "recipient": handoff.clinician.user.full_name}

    def _t_create_follow_up_task(self, a: dict[str, Any]) -> dict[str, Any]:
        kind = a.get("kind")
        if kind not in TASK_KINDS:
            return {"ok": False, "error": "Unknown task kind"}
        allowed, assignee = TASK_KINDS[kind]
        if self.case.status not in allowed:
            return {"ok": False, "error": f"A {kind} task does not apply while the case is {self.case.status.value}"}
        description = str(a.get("description", "")).strip()[:500]
        if not description or (issues := admin_message_issues(description)):
            return {"ok": False, "error": "Description must be administrative only: " + "; ".join(issues or ["empty"])}
        due = a.get("due_in_hours")
        due = min(max(int(due), 1), 168) if isinstance(due, int) else 24
        task, created = services.create_task(self.db, self.case, kind=kind, description=description, assignee_role=assignee, created_by="agent", due_in_hours=due)
        if created and kind in ("ack_reminder", "review_reminder"):
            handoff = self._current_handoff()
            if handoff and services.active_consent(self.case):
                services.notify(self.db, handoff.clinician.user_id, self.case, "Follow-up: case awaiting your action", description, source="agent")
        return {"ok": True, "created": created, "task_id": str(task.id), "kind": kind}

    def _message(self, a: dict[str, Any], recipient: str) -> tuple[str, str] | dict[str, Any]:
        if recipient in self.sent:
            return {"ok": False, "error": f"A {recipient} message was already sent in this run"}
        title, body = str(a.get("title", "")).strip()[:120], str(a.get("body", "")).strip()[:600]
        if not title or not body:
            return {"ok": False, "error": "title and body are required"}
        if issues := admin_message_issues(f"{title}\n{body}"):
            return {"ok": False, "error": "Rejected: " + "; ".join(issues)}
        return title, body

    def _t_notify_patient(self, a: dict[str, Any]) -> dict[str, Any]:
        msg = self._message(a, "patient")
        if isinstance(msg, dict):
            return msg
        services.notify(self.db, self.case.patient.user_id, self.case, *msg, source="agent")
        self.sent.add("patient")
        audit.record(self.db, "notification.sent", "MedicalCase", self.case.id, actor_type="AGENT", org_id=self.case.org_id, details={"recipient": "patient"})
        return {"ok": True}

    def _t_notify_clinician(self, a: dict[str, Any]) -> dict[str, Any]:
        handoff = self._current_handoff()
        if not handoff or not services.active_consent(self.case):
            return {"ok": False, "error": "No clinician is currently authorized on this case"}
        msg = self._message(a, "clinician")
        if isinstance(msg, dict):
            return msg
        services.notify(self.db, handoff.clinician.user_id, self.case, *msg, source="agent")
        self.sent.add("clinician")
        audit.record(self.db, "notification.sent", "MedicalCase", self.case.id, actor_type="AGENT", org_id=self.case.org_id, details={"recipient": "clinician"})
        return {"ok": True}


def start(db: Session, case: MedicalCase, mode: str, triggered_by: User | None) -> AgentExecution:
    ex = AgentExecution(case_id=case.id, kind=mode, status=ExecutionStatus.RUNNING, steps=[])
    db.add(ex)
    db.flush()
    audit.record(db, f"agent.{mode.lower()}_started", "AgentExecution", ex.id, actor=triggered_by, org_id=case.org_id, details={"case_id": str(case.id)})
    db.commit()
    return ex


def run(execution_id: uuid.UUID, triggered_by_id: uuid.UUID | None = None) -> None:
    db = SessionLocal()
    try:
        _run(db, execution_id, triggered_by_id)
    finally:
        db.close()


def _step(db: Session, ex: AgentExecution, entry: dict[str, Any]) -> None:
    ex.steps = [*ex.steps, {"at": datetime.now(timezone.utc).isoformat(), **entry}]
    db.commit()


def _run(db: Session, execution_id: uuid.UUID, triggered_by_id: uuid.UUID | None) -> None:
    ex = db.get(AgentExecution, execution_id)
    if not ex or ex.status != ExecutionStatus.RUNNING:
        return
    case = db.get(MedicalCase, ex.case_id)
    assert case is not None
    mode = ex.kind
    triggered_by = db.get(User, triggered_by_id) if triggered_by_id else None
    runner = ToolRunner(db, case, mode, triggered_by)
    tools = [TOOL_DEFS[n] for n in MODE_TOOLS[mode]]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompts.COORDINATOR_SYSTEM},
        {"role": "user", "content": f"Case {case.id}. Goal: {MODE_GOALS[mode]}"},
    ]
    try:
        provider = get_provider()
        final = None
        for turn in range(1, MAX_TURNS + 1):
            ex.current_step = f"reasoning (turn {turn})"
            db.commit()
            try:
                reply, meta = provider.tool_step(task=f"coordinator_{mode.lower()}", messages=messages, tools=tools, context={"mode": mode, "snapshot": case_snapshot(db, case)})
            except ModelCallError as e:
                record_model_call(db, e.meta, ex.id, case.id)
                db.commit()
                raise RuntimeError(f"Meta model call failed: {e.meta.error}")
            record_model_call(db, meta, ex.id, case.id)
            if not reply.tool_calls:
                final = (reply.content or "").strip()
                _step(db, ex, {"type": "final", "turn": turn, "model": meta.model_id, "message": final[:1000]})
                break
            messages.append({
                "role": "assistant",
                "content": reply.content or "",
                "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in reply.tool_calls],
            })
            for call in reply.tool_calls:
                result = runner.run(call)
                _step(db, ex, {"type": "tool_call", "turn": turn, "tool": call.name, "arguments": tool_args(call), "ok": result.get("ok", False), "result": result, "model": meta.model_id})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)})
        else:
            _step(db, ex, {"type": "limit", "message": f"Stopped after {MAX_TURNS} reasoning turns"})

        db.refresh(case)
        if mode == "HANDOFF" and case.status == CaseStatus.CONSENT_GRANTED:
            raise RuntimeError("The agent finished without completing the handoff; it can be retried")
        ex.status = ExecutionStatus.SUCCEEDED
    except Exception as e:  # noqa: BLE001 - persist the failure, never crash the worker
        log.exception("coordinator failed")
        db.rollback()
        ex = db.get(AgentExecution, execution_id)
        ex.status = ExecutionStatus.FAILED
        ex.error = str(e)[:1000]
    ex.current_step = None
    ex.finished_at = datetime.now(timezone.utc)
    audit.record(db, f"agent.{mode.lower()}_finished", "AgentExecution", ex.id, actor_type="AGENT", org_id=case.org_id, details={"case_id": str(case.id), "status": ex.status.value})
    db.commit()


def follow_up_candidates(db: Session, org_id: uuid.UUID) -> list[MedicalCase]:
    """Deterministic selection of cases worth a follow-up check; the agent decides what (if anything) to do."""
    statuses = [CaseStatus.HANDOFF_SENT, CaseStatus.ACKNOWLEDGED, CaseStatus.UNDER_REVIEW, CaseStatus.REVIEW_COMPLETED, CaseStatus.SUMMARY_READY, CaseStatus.AWAITING_CONSENT, CaseStatus.NEEDS_CORRECTION]
    return list(db.scalars(select(MedicalCase).where(MedicalCase.org_id == org_id, MedicalCase.status.in_(statuses))))
