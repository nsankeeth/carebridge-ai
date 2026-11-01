"""Role-specific projections. Admin views never include clinical content; patients never see clinician notes."""

from typing import Any

from app import services
from app.triage import content as _content
from app.models import (
    URGENCY_RANK,
    HandoffStatus,
    Message,
    MessageAuthor,
    AgentExecution,
    AISummary,
    ExtractedFinding,
    FollowUpTask,
    MedicalCase,
    ModelCall,
    Notification,
    User,
)


def iso(dt: Any) -> str | None:
    return dt.isoformat() if dt else None


def user(u: User) -> dict[str, Any]:
    out = {"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role.value, "is_active": u.is_active}
    if u.clinician_profile:
        cp = u.clinician_profile
        out["clinician"] = {"id": str(cp.id), "specialty": cp.specialty, "clinic_name": cp.clinic_name, "on_call": cp.on_call, "on_call_priority": cp.on_call_priority}
    if u.patient_profile:
        out["patient"] = {"id": str(u.patient_profile.id), "province": u.patient_profile.province}
    return out


def finding(f: ExtractedFinding) -> dict[str, Any]:
    from app.agent.validation import outside_range

    return {
        "id": str(f.id),
        "test_name": f.test_name,
        "value": f.value,
        "unit": f.unit,
        "reference_range": f.reference_range,
        "flag": f.flag,
        "outside_reference_range": outside_range(f.value, f.reference_range),
        "report_date": f.report_date,
        "lab_name": f.lab_name,
        "source_page": f.source_page,
        "source_text": f.source_text,
        "status": f.status.value,
        "validation_notes": f.validation_notes,
        "extraction_method": f.extraction_method,
    }


def summary(s: AISummary | None, *, clinician: bool) -> dict[str, Any] | None:
    if not s:
        return None
    out = {
        "id": str(s.id),
        "version": s.version,
        "status": s.status.value,
        "provider": s.provider,
        "model_id": s.model_id,
        "created_at": iso(s.created_at),
        "patient_explanation": s.patient_explanation,
        "validation_issues": s.validation_issues,
    }
    if clinician:
        out["clinician_summary"] = s.clinician_summary
        out["clinician_correction"] = s.clinician_correction
    return out


def execution(e: AgentExecution | None) -> dict[str, Any] | None:
    if not e:
        return None
    return {
        "id": str(e.id),
        "kind": e.kind,
        "status": e.status.value,
        "current_step": e.current_step,
        "steps": e.steps,
        "error": e.error,
        "started_at": iso(e.started_at),
        "finished_at": iso(e.finished_at),
    }


def model_call(m: ModelCall) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "task": m.task,
        "provider": m.provider,
        "model_id": m.model_id,
        "status": m.status,
        "latency_ms": round(m.latency_ms),
        "input_tokens": m.input_tokens,
        "output_tokens": m.output_tokens,
        "total_tokens": m.total_tokens,
        "response_id": m.response_id,
        "error": m.error,
        "created_at": iso(m.created_at),
    }


def task(t: FollowUpTask) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "case_id": str(t.case_id),
        "kind": t.kind,
        "description": t.description,
        "assignee_role": t.assignee_role.value,
        "status": t.status.value,
        "created_by": t.created_by,
        "due_at": iso(t.due_at),
        "created_at": iso(t.created_at),
    }


def notification(n: Notification) -> dict[str, Any]:
    return {"id": str(n.id), "case_id": str(n.case_id) if n.case_id else None, "title": n.title, "body": n.body, "source": n.source, "read": n.read_at is not None, "created_at": iso(n.created_at)}


def _handoff_status(case: MedicalCase) -> dict[str, Any] | None:
    h = case.handoffs[-1] if case.handoffs else None
    if not h:
        return None
    return {
        "id": str(h.id),
        "status": h.status.value,
        "clinician_name": h.clinician.user.full_name,
        "clinic_name": h.clinician.clinic_name,
        "sent_at": iso(h.sent_at),
        "acknowledged_at": iso(h.acknowledged_at),
    }


def _consent(case: MedicalCase) -> list[dict[str, Any]]:
    return [
        {
            "id": str(c.id),
            "status": c.status.value,
            "clinician_name": c.clinician.user.full_name if c.clinician else "Your care team",
            "scope": c.scope,
            "purpose": c.purpose,
            "granted_at": iso(c.granted_at),
            "withdrawn_at": iso(c.withdrawn_at),
        }
        for c in case.consents
    ]


def case_list_item(case: MedicalCase) -> dict[str, Any]:
    doc = case.documents[-1] if case.documents else None
    return {
        "id": str(case.id),
        "title": case.title,
        "status": case.status.value,
        "patient_name": case.patient.user.full_name,
        "document_name": doc.filename if doc else None,
        "created_at": iso(case.created_at),
        "updated_at": iso(case.updated_at),
        "handoff": _handoff_status(case),
    }


def _executions(case: MedicalCase, db_executions: list[AgentExecution]) -> list[dict[str, Any]]:
    return [execution(e) for e in db_executions]  # type: ignore[misc]


def patient_case(case: MedicalCase, executions: list[AgentExecution]) -> dict[str, Any]:
    review = case.reviews[-1] if case.reviews else None
    doc = case.documents[-1] if case.documents else None
    return {
        **case_list_item(case),
        "document": {"id": str(doc.id), "filename": doc.filename, "page_count": doc.page_count, "uploaded_at": iso(doc.uploaded_at)} if doc else None,
        "findings": [finding(f) for f in case.findings],
        "summary": summary(services.active_summary(case) or (case.summaries[-1] if case.summaries else None), clinician=False),
        "consents": _consent(case),
        "review": {
            "next_step": review.next_step.value if review.next_step else None,
            "patient_message": review.patient_message,
            "completed_at": iso(review.completed_at),
        } if review else None,
        "executions": _executions(case, executions),
    }


def clinician_case(case: MedicalCase, executions: list[AgentExecution]) -> dict[str, Any]:
    review = case.reviews[-1] if case.reviews else None
    doc = case.documents[-1] if case.documents else None
    p = case.patient
    return {
        **case_list_item(case),
        "patient": {"name": p.user.full_name, "date_of_birth": iso(p.date_of_birth), "province": p.province, "synthetic_health_ref": p.synthetic_health_ref},
        "document": {"id": str(doc.id), "filename": doc.filename, "page_count": doc.page_count} if doc else None,
        "findings": [finding(f) for f in case.findings],
        "summary": summary(next((s for s in case.summaries if case.handoffs and s.id == case.handoffs[-1].summary_id), None), clinician=True),
        "consents": _consent(case),
        "review": {
            "summary_assessment": review.summary_assessment.value if review.summary_assessment else None,
            "summary_correction": review.summary_correction,
            "clinical_notes": review.clinical_notes,
            "next_step": review.next_step.value if review.next_step else None,
            "patient_message": review.patient_message,
            "started_at": iso(review.started_at),
            "completed_at": iso(review.completed_at),
        } if review else None,
        "tasks": [task(t) for t in case.tasks],
        "executions": _executions(case, executions),
    }


# --- Symptom threads ---------------------------------------------------------------

def _age(dob: Any) -> float | None:
    return round((services.now().date() - dob).days / 365.25, 1) if dob else None


def thread_subject(case: MedicalCase) -> dict[str, Any]:
    d = case.subject_dependent
    if d:
        return {"name": d.name, "relation": d.relation, "age_years": _age(d.date_of_birth), "dependent_id": str(d.id)}
    p = case.patient
    return {"name": p.user.full_name, "relation": "self", "age_years": _age(p.date_of_birth), "dependent_id": None}


def message(m: Message) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "author_type": m.author_type.value,
        "author_name": m.author.full_name if m.author and m.author_type == MessageAuthor.CLINICIAN else None,
        "body": m.body,
        "payload": m.payload,
        "created_at": iso(m.created_at),
    }


def pending_questions(case: MedicalCase) -> list[dict[str, Any]]:
    answered = {(m.payload or {}).get("question_id") for m in case.messages if (m.payload or {}).get("kind") == "answer"}
    rounds = [m for m in case.messages if (m.payload or {}).get("kind") == "questions"]
    if not rounds or case.urgency and case.urgency.value == "EMERGENCY":
        return []
    return [q for q in rounds[-1].payload["questions"] if q["id"] not in answered]


def _care_team(case: MedicalCase) -> list[dict[str, Any]]:
    return [
        {"name": h.clinician.user.full_name, "status": h.status.value, "notified_at": iso(h.sent_at), "acknowledged_at": iso(h.acknowledged_at)}
        for h in case.handoffs
        if h.status != HandoffStatus.CANCELLED
    ]


def _attachments(case: MedicalCase, *, clinician: bool) -> list[dict[str, Any]]:
    out = []
    for d in case.documents:
        out.append({"id": str(d.id), "filename": d.filename, "processing_status": d.processing_status.value if d.processing_status else None, "uploaded_at": iso(d.uploaded_at)})
    if out and case.findings:
        s = services.active_summary(case)
        out[-1]["findings"] = [finding(f) for f in case.findings]
        out[-1]["explanation"] = summary(s, clinician=False)["patient_explanation"] if s and not clinician else None
    return out


def thread_list_item(case: MedicalCase) -> dict[str, Any]:
    last = case.messages[-1].created_at if case.messages else case.updated_at
    return {
        "id": str(case.id),
        "kind": case.kind.value,
        "title": case.title,
        "subject_name": thread_subject(case)["name"],
        "urgency": case.urgency.value if case.urgency else None,
        "status": case.status.value,
        "last_message_at": iso(last),
        "created_at": iso(case.created_at),
    }


def patient_thread(case: MedicalCase) -> dict[str, Any]:
    """Patient view. Never includes the clinician brief, model reasons, or possible causes."""
    flags = list(dict.fromkeys(code for a in case.triage_assessments for code in a.rule_flags))
    level = case.urgency
    return {
        **thread_list_item(case),
        "subject": thread_subject(case),
        "emergency": level is not None and level.value == "EMERGENCY",
        "guidance": _content.GUIDANCE[level] if level else None,
        "emergency_steps": _content.EMERGENCY_STEPS if level and level.value == "EMERGENCY" else [],
        "worsening_signs": [_content.WORSENING_SIGNS[f] for f in flags if f in _content.WORSENING_SIGNS],
        "care_team": _care_team(case),
        "messages": [message(m) for m in case.messages],
        "pending_questions": pending_questions(case),
        "consent_active": services.active_consent(case) is not None,
        "fallback_advised": case.fallback_advised_at is not None,
        "attachments": _attachments(case, clinician=False),
        "outcome": case.outcome,
    }


def clinician_thread(case: MedicalCase, handoff: Any) -> dict[str, Any]:
    b = case.briefs[-1] if case.briefs else None
    return {
        **patient_thread(case),
        "urgency_set_by": case.urgency_set_by,
        "patient_name": case.patient.user.full_name,
        "patient_phone": case.patient.user.phone,
        "my_handoff": {"status": handoff.status.value, "ack_due_at": iso(handoff.ack_due_at), "sent_at": iso(handoff.sent_at)},
        "brief": {
            "version": b.version, "content": b.content, "validation_issues": b.validation_issues, "assessment": b.assessment.value if b.assessment else None,
            "correction": b.correction, "model_id": b.model_id, "created_at": iso(b.created_at),
        } if b else None,
        "assessments": [
            {"rule_level": a.rule_level.value if a.rule_level else None, "rule_flags": a.rule_flags, "model_level": a.model_level.value if a.model_level else None,
             "model_flags": a.model_flags, "dropped_flags": a.dropped_flags, "reasons": a.reasons, "final_level": a.final_level.value if a.final_level else None,
             "status": a.status, "created_at": iso(a.created_at)}
            for a in case.triage_assessments
        ],
        "findings": [finding(f) for f in case.findings],
        "outcome_note": case.outcome_note,
    }


def queue_row(case: MedicalCase, handoff: Any) -> dict[str, Any]:
    subject = thread_subject(case)
    first = case.messages[0].created_at if case.messages else case.created_at
    return {
        **thread_list_item(case),
        "subject_age_years": subject["age_years"],
        "patient_name": case.patient.user.full_name,
        "ack_due_at": iso(handoff.ack_due_at) if handoff and handoff.status == HandoffStatus.SENT else None,
        "first_message_at": iso(first),
        "_rank": URGENCY_RANK[case.urgency] if case.urgency else -1,
    }
