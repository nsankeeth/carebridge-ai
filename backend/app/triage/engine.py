"""Triage engine: rules first (synchronous, no model), then Meta (background) to refine, ask and acknowledge.

The level of a thread only ever goes up here. A clinician's change (made through the API) resets the baseline.
"""

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app import audit, workflow
from app.ai import prompts
from app.ai.schemas import TriageModelOutput
from app.db import SessionLocal
from app.errors import Conflict
from app.models import CaseStatus, MedicalCase, Message, MessageAuthor, TriageAssessment, Urgency, User, max_urgency
from app.services import now
from app.triage import brief, content, questions, routing, rules
from app.triage.grounding import patient_corpus, patient_text_issues, split_grounded
from app.triage.llm import call_structured
from app.triage.messages import post_message


def subject_age(case: MedicalCase, today: date) -> float | None:
    dob = case.subject_dependent.date_of_birth if case.subject_dependent else case.patient.date_of_birth
    return (today - dob).days / 365.25 if dob else None


def _answers(case: MedicalCase) -> dict[str, str]:
    return {m.payload["question_id"]: m.payload["answer"] for m in case.messages if m.author_type == MessageAuthor.PATIENT and (m.payload or {}).get("kind") == "answer"}


def _question_messages(case: MedicalCase) -> list[Message]:
    return [m for m in case.messages if (m.payload or {}).get("kind") == "questions"]


def _raise_level(db: Session, case: MedicalCase, level: Urgency | None, source: str) -> bool:
    """Raise the thread's urgency (never lower it), move it out of intake and page. Returns True if it changed."""
    if level is None:
        return False
    new = max_urgency(case.urgency, level)
    changed = new != case.urgency
    if changed:
        audit.record(db, "triage.level_set", "MedicalCase", case.id, actor_type="SYSTEM", org_id=case.org_id, details={"from": case.urgency.value if case.urgency else None, "to": new.value, "source": source})
        case.urgency, case.urgency_set_by = new, source
    if case.status == CaseStatus.INTAKE:
        workflow.transition(db, case, CaseStatus.TRIAGED, actor_type="SYSTEM", reason=f"triaged by {source}")
    routing.apply_level(db, case, case.urgency, now())
    return changed


def _guidance(level: Urgency, flags: list[str], tips: list[str], ack: str | None) -> str:
    parts = [ack] if ack else []
    parts.append(content.GUIDANCE[level])
    signs = [content.WORSENING_SIGNS[f] for f in flags if f in content.WORSENING_SIGNS]
    if signs and level != Urgency.EMERGENCY:
        parts.append("Watch for: " + " ".join(dict.fromkeys(signs)))
    if tips and level != Urgency.EMERGENCY:
        parts.append("Until then: " + " ".join(content.CARE_TIPS[t] for t in tips))
    return "\n\n".join(parts)


def intake(db: Session, case: MedicalCase, message: Message) -> TriageAssessment:
    """Synchronous rules pass for a new patient message or answer. Never calls a model."""
    is_answer = (message.payload or {}).get("kind") == "answer"
    result = rules.evaluate("" if is_answer else message.body, _answers(case), subject_age(case, now().date()))
    baseline = set(case.urgency_baseline_flags or [])
    new_flags = [f for f in result.flags if f.code not in baseline]
    rule_level = max_urgency(*(f.level for f in new_flags))
    a = TriageAssessment(case_id=case.id, message_id=message.id, rule_level=rule_level, rule_flags=[f.code for f in new_flags], final_level=rule_level, status="rules_only")
    db.add(a)
    db.flush()
    if a not in case.triage_assessments:
        case.triage_assessments.append(a)
    was_emergency = case.urgency == Urgency.EMERGENCY
    _raise_level(db, case, rule_level, "rules")
    if case.urgency == Urgency.EMERGENCY and not was_emergency:
        post_message(db, case, MessageAuthor.AI, _guidance(Urgency.EMERGENCY, [], [], None), {"kind": "guidance", "level": "EMERGENCY"})
    return a


def _prompt(case: MedicalCase, age: float | None, rule_flags: list[str]) -> str:
    who = f"a child aged {age:.1f} years (the parent is writing)" if case.subject_dependent and age is not None else f"the patient, aged {age:.0f}" if age is not None else "the patient"
    lines = [f"About: {who}", f"Rule-based red flags found so far: {', '.join(rule_flags) or 'none'}", "", "Messages:"]
    for m in case.messages:
        if m.author_type == MessageAuthor.PATIENT:
            p = m.payload or {}
            q = questions.BANK.get(p.get("question_id", "")) if p.get("kind") == "answer" else None
            lines.append(f"- Patient answered '{q.text if q else p.get('question_id')}': {p.get('answer')}" if p.get("kind") == "answer" else f"- Patient: {m.body}")
        elif m.author_type == MessageAuthor.CLINICIAN:
            lines.append(f"- Clinician: {m.body}")
    return "\n".join(lines)


def run_model_triage(assessment_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        case_id = _run_model_triage(db, assessment_id)
        db.commit()
    finally:
        db.close()
    if case_id:
        brief.generate(case_id)


def _run_model_triage(db: Session, assessment_id: uuid.UUID) -> uuid.UUID | None:
    a = db.get(TriageAssessment, assessment_id)
    if not a or a.status != "rules_only":
        return None
    case = db.get(MedicalCase, a.case_id)
    if case.status in (CaseStatus.CONSENT_WITHDRAWN, CaseStatus.CLOSED):
        return None
    age = subject_age(case, now().date())
    corpus = patient_corpus(case.messages)
    all_flags = [f.code for f in rules.evaluate(" ".join(m.body for m in case.messages if m.author_type == MessageAuthor.PATIENT and not m.payload), _answers(case), age).flags]
    system = prompts.triage_system(list(content.CARE_TIPS), list(questions.BANK))
    user = _prompt(case, age, all_flags)
    ctx = {"corpus": corpus, "rule_level": a.rule_level.value if a.rule_level else None}
    out, calls = call_structured(db, case, "triage_assessment", system, user, TriageModelOutput, ctx)
    a.model_call_ids = [str(c.id) for c in calls]
    clinician_set = case.urgency_set_by == "clinician"

    ack, tips, model_questions = None, [], []
    if out is None:
        a.status = "model_failed"
        if case.urgency is None and a.rule_level is None:
            _raise_level(db, case, Urgency.SOON, "fallback")
        else:
            _raise_level(db, case, case.urgency or a.rule_level, case.urgency_set_by or "rules")
    else:
        kept, dropped = split_grounded(out.red_flags, corpus)
        a.model_flags = [f.model_dump() for f in kept]
        a.dropped_flags = [f.model_dump() for f in dropped]
        a.reasons = out.reasons
        a.model_level = Urgency(out.level)
        a.status = "complete"
        # After a clinician sets the level, only new rule flags may move it; the model's view is recorded only.
        if clinician_set:
            level, source = a.rule_level, "rules"
        else:
            level = max_urgency(a.rule_level, a.model_level)
            source = "rules" if level == a.rule_level else "model"
        if level is None:
            level, source = case.urgency or Urgency.SOON, case.urgency_set_by or "fallback"
        _raise_level(db, case, level, source)
        ack = out.acknowledgement
        if patient_text_issues(ack, corpus):
            retry, more = call_structured(db, case, "triage_assessment", system, user + "\n\nThe acknowledgement was rejected for unsafe wording. Rewrite it following the rules.", TriageModelOutput, ctx)
            a.model_call_ids += [str(c.id) for c in more]
            ack = retry.acknowledgement if retry and not patient_text_issues(retry.acknowledgement, corpus) else None
        tips = [t for t in out.care_tip_ids if t in content.CARE_TIPS]
        model_questions = out.follow_up_questions
    a.final_level = case.urgency

    level = case.urgency
    if level != Urgency.EMERGENCY or ack:
        post_message(db, case, MessageAuthor.AI, _guidance(level, all_flags, tips, ack), {"kind": "guidance", "level": level.value, "care_tip_ids": tips})
    _ask(db, case, all_flags, age, model_questions, corpus)
    return case.id


def _ask(db: Session, case: MedicalCase, flags: list[str], age: float | None, model_questions: list, corpus: str) -> None:
    if case.urgency == Urgency.EMERGENCY:
        return
    previous = _question_messages(case)
    round_no = len(previous) + 1
    if round_no > questions.MAX_ROUNDS:
        return
    asked = {q["id"] for m in previous for q in m.payload["questions"]}
    chosen = [{"id": q.id, "question": q.text, "options": q.options} for q in questions.next_questions(flags, rules.age_band(age), asked, round_no)]
    for q in model_questions:
        if len(chosen) >= questions.MAX_PER_ROUND:
            break
        if q.id in asked or q.id in questions.BANK or not (2 <= len(q.options) <= 3):
            continue
        if any(patient_text_issues(t, corpus) for t in [q.question, *q.options]):
            continue
        chosen.append({"id": q.id, "question": q.question, "options": q.options})
    if chosen:
        post_message(db, case, MessageAuthor.AI, "A few quick questions to help us:", {"kind": "questions", "round": round_no, "questions": chosen})


def answer(db: Session, case: MedicalCase, question_id: str, option: str, actor: User) -> TriageAssessment:
    asked = {q["id"]: q for m in _question_messages(case) for q in m.payload["questions"]}
    q = asked.get(question_id)
    if not q or option not in q["options"]:
        raise Conflict("invalid_answer", "That answer doesn't match a question in this conversation")
    if question_id in _answers(case):
        raise Conflict("already_answered", "This question has already been answered")
    m = post_message(db, case, MessageAuthor.PATIENT, option, {"kind": "answer", "question_id": question_id, "answer": option}, author=actor)
    return intake(db, case, m)
