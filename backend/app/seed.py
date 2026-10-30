"""Reset the database and load synthetic demo data.

    python -m app.seed            # runs the real processing agent (Meta model) on every seeded report

Demo accounts share the password in DEMO_PASSWORD (default below).
"""

import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from app import services, storage
from app.agent import pipeline
from app.config import get_settings
from app.db import Base, SessionLocal
from app.fixtures import REPORTS, build_pdf
from app.models import (
    AgentExecution,
    CaseStatus,
    ClinicianProfile,
    MedicalCase,
    MedicalDocument,
    NextStep,
    Organization,
    PatientProfile,
    SummaryAssessment,
    User,
    UserRole,
)
from app.security import hash_password

DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "CareBridge-Demo-2026")

USERS = [
    ("maya.thompson@patient.demo", "Maya Thompson", UserRole.PATIENT, {"dob": date(1988, 4, 12), "ref": "SYN-ON-4471-0092"}),
    ("daniel.okafor@patient.demo", "Daniel Okafor", UserRole.PATIENT, {"dob": date(1971, 11, 3), "ref": "SYN-ON-8820-1157"}),
    ("dr.raman@clinic.demo", "Dr. Priya Raman", UserRole.CLINICIAN, {"specialty": "Family Medicine", "clinic": "Lakeshore Family Health Team"}),
    ("dr.tremblay@clinic.demo", "Dr. Marc Tremblay", UserRole.CLINICIAN, {"specialty": "Internal Medicine", "clinic": "Riverside Internal Medicine"}),
    ("admin@carebridge.demo", "Jordan Lee", UserRole.ADMIN, {}),
]

# (report slug, clinician email for handoff, target state)
CASE_PLAN = [
    ("cbc-iron-maya", "dr.raman@clinic.demo", "HANDOFF_SENT_OVERDUE"),
    ("lipids-maya", "dr.raman@clinic.demo", "CLOSED"),
    ("metabolic-daniel", "dr.tremblay@clinic.demo", "UNDER_REVIEW"),
    ("thyroid-daniel", None, "SUMMARY_READY"),
    ("liver-daniel", None, "AWAITING_CONSENT"),
]


def reset(db) -> None:
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    db.commit()
    shutil.rmtree(Path(get_settings().storage_dir) / "cases", ignore_errors=True)


def main() -> int:
    if not get_settings().model_api_key:
        print("MODEL_API_KEY is not set. Add it to .env; seeding runs every report through the Meta model.")
        return 1

    db = SessionLocal()
    reset(db)
    org = Organization(name="CareBridge Health Network")
    db.add(org)
    db.flush()
    users: dict[str, User] = {}
    for email, name, role, extra in USERS:
        u = User(org_id=org.id, email=email, full_name=name, role=role, password_hash=hash_password(DEMO_PASSWORD))
        db.add(u)
        db.flush()
        if role == UserRole.PATIENT:
            db.add(PatientProfile(user_id=u.id, date_of_birth=extra["dob"], province="ON", synthetic_health_ref=extra["ref"]))
        elif role == UserRole.CLINICIAN:
            db.add(ClinicianProfile(user_id=u.id, specialty=extra["specialty"], clinic_name=extra["clinic"], synthetic_license_ref=f"SYN-CPSO-{len(users):04d}"))
        users[email] = u
    db.commit()
    for u in users.values():
        db.refresh(u)

    reports = {r.slug: r for r in REPORTS}
    patient_by_name = {u.full_name: u for u in users.values() if u.role == UserRole.PATIENT}
    for slug, clinician_email, target in CASE_PLAN:
        r = reports[slug]
        patient = patient_by_name[r.patient]
        case = MedicalCase(org_id=org.id, patient_id=patient.patient_profile.id, title=r.title, status=CaseStatus.UPLOADED)
        db.add(case)
        db.flush()
        data = build_pdf(r)
        key, digest = storage.save(case.id, data)
        db.add(MedicalDocument(case_id=case.id, filename=f"{slug}.pdf", storage_key=key, content_type="application/pdf", size_bytes=len(data), sha256=digest))
        db.commit()
        db.refresh(case)
        ex = pipeline.start_processing(db, case, patient)
        print(f"processing {slug} …", flush=True)
        pipeline.run_processing(ex.id)
        db.expire_all()
        ex = db.get(AgentExecution, ex.id)
        if case.status != CaseStatus.SUMMARY_READY:
            print(f"  ! {slug} ended in {case.status.value}: {ex.error}")
            continue
        _advance(db, case, patient, users.get(clinician_email) if clinician_email else None, target)
        print(f"  {slug}: {case.status.value}")
    db.close()
    print(f"\nSeeded. Demo password for all accounts: see DEMO_PASSWORD in app/seed.py")
    return 0


def _advance(db, case: MedicalCase, patient: User, clinician: User | None, target: str) -> None:
    if target == "SUMMARY_READY":
        return
    services.request_consent(db, case, patient)
    db.commit()
    if target == "AWAITING_CONSENT":
        return
    services.grant_consent(db, case, patient, clinician.clinician_profile.id, True)
    handoff, _ = services.create_handoff(db, case, actor=None, actor_type="AGENT")
    db.commit()
    if target == "HANDOFF_SENT_OVERDUE":
        handoff.sent_at = services.now() - timedelta(hours=30)
        case.consents[-1].granted_at = services.now() - timedelta(hours=30)
        db.commit()
        return
    services.acknowledge(db, case, handoff, clinician)
    services.start_review(db, case, handoff, clinician)
    db.commit()
    if target == "UNDER_REVIEW":
        return
    services.assess_summary(db, case, handoff, clinician, SummaryAssessment.ACCURATE, None)
    services.complete_review(db, case, handoff, clinician, NextStep.NO_FURTHER_ACTION, "Results reviewed. No action needed at this time.", "I reviewed your lipid results. No changes are needed; we'll recheck at your annual visit.")
    services.close_case(db, case, patient)
    db.commit()


if __name__ == "__main__":
    sys.exit(main())
