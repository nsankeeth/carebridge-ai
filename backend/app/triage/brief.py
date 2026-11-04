"""Clinician-only triage brief, drafted by Meta and grounded in the patient's own words."""

import uuid

from sqlalchemy.orm import Session

from app import audit
from app.ai import prompts
from app.ai.schemas import ClinicianTriageBrief
from app.db import SessionLocal
from app.errors import AppError
from app.models import ClinicianBrief, MedicalCase, MessageAuthor, SummaryAssessment, User
from app.services import now
from app.triage.grounding import patient_corpus, quote_grounded
from app.triage.llm import call_structured


def _subject(case: MedicalCase) -> str:
    dep = case.subject_dependent
    if dep:
        years = (now().date() - dep.date_of_birth).days / 365.25
        return f"{dep.relation} of the account holder, age {years:.1f} years"
    dob = case.patient.date_of_birth
    return f"the account holder, age {int((now().date() - dob).days / 365.25)} years" if dob else "the account holder"


def _prompt(case: MedicalCase) -> str:
    lines = [f"Subject: {_subject(case)}", f"Current urgency: {case.urgency.value if case.urgency else 'not set'}", "", "Patient messages and answers:"]
    for m in case.messages:
        if m.author_type == MessageAuthor.PATIENT:
            p = m.payload or {}
            lines.append(f"- [answer to {p['question_id']}] {p.get('answer')}" if p.get("kind") == "answer" else f"- {m.body}")
    if case.triage_assessments:
        a = case.triage_assessments[-1]
        lines += ["", f"Rule-based red flags: {', '.join(a.rule_flags) or 'none'}"]
    if case.findings:
        lines += ["", "Lab results from an attached report (copy values exactly):"]
        lines += [f"- {f.test_name}: {f.value} {f.unit or ''} (ref {f.reference_range or 'n/a'}) flag={f.flag or 'none'}" for f in case.findings]
    return "\n".join(lines)


def generate(case_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        _generate(db, case_id)
        db.commit()
    finally:
        db.close()


def _generate(db: Session, case_id: uuid.UUID) -> ClinicianBrief | None:
    case = db.get(MedicalCase, case_id)
    if not case:
        return None
    corpus = patient_corpus(case.messages)
    out, calls = call_structured(db, case, "clinician_triage_brief", prompts.BRIEF_SYSTEM, _prompt(case), ClinicianTriageBrief, {"corpus": corpus})
    if out is None:
        return None
    issues: list[str] = []
    data = out.model_dump()
    kept = []
    for f in data["red_flags"]:
        if quote_grounded(f["patient_quote"], corpus):
            kept.append(f)
        else:
            issues.append(f"Dropped red flag '{f['flag']}': quote not found in patient messages")
    data["red_flags"] = kept
    for c in data["possible_causes"]:
        for key in ("supporting_quotes", "against_quotes"):
            good = [q for q in c[key] if quote_grounded(q, corpus)]
            issues += [f"Dropped quote for '{c['cause']}': not found in patient messages" for q in c[key] if q not in good]
            c[key] = good
        both = set(c["supporting_quotes"]) & set(c["against_quotes"])
        if both:
            # A quote can't be evidence both ways; it tells the clinician nothing about this cause.
            c["supporting_quotes"] = [q for q in c["supporting_quotes"] if q not in both]
            c["against_quotes"] = [q for q in c["against_quotes"] if q not in both]
            issues.append(f"Dropped {len(both)} quote(s) used both for and against '{c['cause']}'")
    # Filled from the record, not the model: exactly what the patient was shown.
    data["what_ai_told_patient"] = [m.body for m in case.messages if m.author_type in (MessageAuthor.AI, MessageAuthor.SYSTEM)]
    version = (case.briefs[-1].version if case.briefs else 0) + 1
    b = ClinicianBrief(case_id=case.id, version=version, content=data, validation_issues=issues, model_id=calls[-1].model_id)
    db.add(b)
    db.flush()
    audit.record(db, "ai.brief_generated", "ClinicianBrief", b.id, actor_type="AGENT", org_id=case.org_id, details={"case_id": str(case.id), "version": version, "dropped": len(issues)})
    return b


def assess(db: Session, case: MedicalCase, actor: User, assessment: SummaryAssessment, correction: str | None) -> ClinicianBrief:
    if not case.briefs:
        raise AppError("no_brief", "There is no brief to assess yet")
    if assessment != SummaryAssessment.ACCURATE and not (correction and correction.strip()):
        raise AppError("correction_required", "Describe what is inaccurate when correcting or rejecting the brief")
    b = case.briefs[-1]
    b.assessment, b.correction = assessment, correction
    audit.record(db, "ai.brief_assessed", "ClinicianBrief", b.id, actor=actor, details={"case_id": str(case.id), "assessment": assessment.value})
    return b
