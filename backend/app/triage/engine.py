"""Triage engine: rules first (synchronous, no model), then Meta (background) to refine, ask and acknowledge.

The level of a thread only ever goes up here. A clinician's change (made through the API) resets the baseline.
"""

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, workflow
from app.ai import prompts
from app.ai.schemas import TriageModelOutput
from app.config import get_settings
from app.db import SessionLocal
from app.errors import Conflict, NotFound
from app.models import CaseKind, CaseStatus, ConsentStatus, Dependent, MedicalCase, PatientConsent, Message, MessageAuthor, TriageAssessment, Urgency, User, max_urgency
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


def _guidance(level: Urgency, flags: list[str], ack: str | None) -> str:
    parts = [ack] if ack else []
    parts.append(content.GUIDANCE[level])
    signs = [content.WORSENING_SIGNS[f] for f in flags if f in content.WORSENING_SIGNS]
    if signs and level != Urgency.EMERGENCY:
        parts.append("Watch for: " + " ".join(dict.fromkeys(signs)))
    return "\n\n".join(parts)


def intake(db: Session, case: MedicalCase, message: Message) -> TriageAssessment:
    """Synchronous rules pass for a new patient message or answer. Never calls a model."""
    case = lock_case(db, case.id)
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
        post_message(db, case, MessageAuthor.AI, _guidance(Urgency.EMERGENCY, [], None), {"kind": "guidance", "level": "EMERGENCY"})
    return a


def _prompt(case: MedicalCase, age: float | None, rule_flags: list[str]) -> str:
    who = f"a child aged {age:.1f} years (the parent is writing)" if case.subject_dependent and age is not None else f"the patient, aged {int(age)}" if age is not None else "the patient"
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


def lock_case(db: Session, case_id: uuid.UUID) -> MedicalCase:
    """Row-lock the case and reload it, so concurrent requests and background runs see each other's commits."""
    db.flush()
    case = db.scalar(select(MedicalCase).where(MedicalCase.id == case_id).with_for_update().execution_options(populate_existing=True))
    for rel in ("messages", "triage_assessments", "handoffs", "consents"):
        db.expire(case, [rel])
    return case


def _patient_flags(case: MedicalCase, age: float | None) -> list[str]:
    text = " ".join(m.body for m in case.messages if m.author_type == MessageAuthor.PATIENT and not m.payload)
    return [f.code for f in rules.evaluate(text, _answers(case), age).flags]


def _run_model_triage(db: Session, assessment_id: uuid.UUID) -> uuid.UUID | None:
    a = db.get(TriageAssessment, assessment_id)
    if not a or a.status != "rules_only":
        return None
    case_id = a.case_id
    case = db.get(MedicalCase, case_id)
    if case.status in (CaseStatus.CONSENT_WITHDRAWN, CaseStatus.CLOSED):
        return None

    # 1. Model calls on a snapshot, holding no lock (they take tens of seconds).
    age = subject_age(case, now().date())
    corpus = patient_corpus(case.messages)
    system = prompts.triage_system(list(questions.BANK))
    user = _prompt(case, age, _patient_flags(case, age))
    ctx = {"corpus": corpus, "rule_level": a.rule_level.value if a.rule_level else None}
    out, calls = call_structured(db, case, "triage_assessment", system, user, TriageModelOutput, ctx)
    ack = out.acknowledgement if out else None
    if ack and patient_text_issues(ack, corpus):
        retry, more = call_structured(db, case, "triage_assessment", system, user + "\n\nThe acknowledgement was rejected for unsafe wording. Rewrite it following the rules.", TriageModelOutput, ctx)
        calls += more
        ack = retry.acknowledgement if retry and not patient_text_issues(retry.acknowledgement, corpus) else None

    # 2. Apply against fresh, locked state: a newer message or a clinician may have changed the case meanwhile.
    case = lock_case(db, case_id)
    a = db.get(TriageAssessment, assessment_id)
    a.model_call_ids = [str(c.id) for c in calls]
    if case.status in (CaseStatus.CONSENT_WITHDRAWN, CaseStatus.CLOSED):
        a.status = "complete" if out else "model_failed"
        return None
    clinician_set = case.urgency_set_by == "clinician"
    model_questions = []
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
        model_questions = out.follow_up_questions
    a.final_level = case.urgency

    level = case.urgency
    all_flags = _patient_flags(case, age)
    if level == Urgency.EMERGENCY and _emergency_guidance_shown(case):
        # The Call 911 wording is already in the thread; add only the acknowledgement.
        if ack:
            post_message(db, case, MessageAuthor.AI, ack, {"kind": "acknowledgement", "level": level.value})
    else:
        post_message(db, case, MessageAuthor.AI, _guidance(level, all_flags, ack), {"kind": "guidance", "level": level.value})
    _ask(db, case, all_flags, age, model_questions, patient_corpus(case.messages))
    return case.id


def _emergency_guidance_shown(case: MedicalCase) -> bool:
    return any((m.payload or {}).get("kind") == "guidance" and m.payload.get("level") == Urgency.EMERGENCY.value for m in case.messages)


def recover_stale_intake(db: Session, at: datetime) -> int:
    """Give a level to threads whose background triage never finished (lost task, restart). Run by the scheduler."""
    cutoff = at - timedelta(seconds=get_settings().stale_intake_seconds)
    ids = db.scalars(select(MedicalCase.id).where(MedicalCase.kind == CaseKind.SYMPTOM, MedicalCase.status == CaseStatus.INTAKE, MedicalCase.created_at <= cutoff)).all()
    recovered = 0
    for case_id in ids:
        case = lock_case(db, case_id)
        if case.status != CaseStatus.INTAKE:
            continue
        _raise_level(db, case, Urgency.SOON, "fallback")
        post_message(db, case, MessageAuthor.AI, _guidance(Urgency.SOON, _patient_flags(case, subject_age(case, at.date())), None), {"kind": "guidance", "level": "SOON"})
        audit.record(db, "triage.intake_recovered", "MedicalCase", case.id, actor_type="SYSTEM", org_id=case.org_id)
        recovered += 1
    return recovered


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
        if q.id in asked or q.id in questions.BANK or not (2 <= len(q.options) <= 3) or len(q.id) > 60 or any(len(o) > 60 for o in q.options):
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


CARE_TEAM_SCOPE = ["symptom_thread", "attachments"]
CARE_TEAM_PURPOSE = "So your family doctor and on-call clinicians can see this conversation and anything you attach, and respond."


def start_thread(db: Session, user: User, text: str, dependent_id: uuid.UUID | None) -> tuple[MedicalCase, TriageAssessment]:
    """Create a symptom thread with care-team consent and run the synchronous rules pass. Caller commits."""
    profile = user.patient_profile
    if dependent_id:
        dep = db.get(Dependent, dependent_id)
        if not dep or dep.patient_id != profile.id:
            raise NotFound("Dependent not found")
    text = text.strip()
    case = MedicalCase(org_id=user.org_id, patient_id=profile.id, title=text[:60], kind=CaseKind.SYMPTOM, status=CaseStatus.INTAKE, subject_dependent_id=dependent_id)
    db.add(case)
    db.flush()
    audit.record(db, "case.created", "MedicalCase", case.id, actor=user, details={"kind": "SYMPTOM"})
    consent = PatientConsent(case_id=case.id, patient_id=profile.id, clinician_id=None, audience="CARE_TEAM", scope=CARE_TEAM_SCOPE, purpose=CARE_TEAM_PURPOSE, status=ConsentStatus.GRANTED)
    db.add(consent)
    db.flush()
    audit.record(db, "consent.granted", "PatientConsent", consent.id, actor=user, details={"case_id": str(case.id), "audience": "CARE_TEAM", "scope": CARE_TEAM_SCOPE})
    db.refresh(case)
    msg = post_message(db, case, MessageAuthor.PATIENT, text, author=user)
    return case, intake(db, case, msg)
