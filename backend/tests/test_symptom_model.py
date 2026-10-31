import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app import workflow
from app.db import SessionLocal
from app.models import (
    CaseKind,
    CaseStatus,
    ClinicalHandoff,
    ClinicianProfile,
    ConsentStatus,
    HandoffStatus,
    MedicalCase,
    PatientConsent,
    Urgency,
    max_urgency,
)


def test_max_urgency_orders_levels():
    assert max_urgency(Urgency.SOON, None, Urgency.URGENT) == Urgency.URGENT
    assert max_urgency(Urgency.EMERGENCY, Urgency.ROUTINE) == Urgency.EMERGENCY
    assert max_urgency(None) is None


def test_symptom_transitions():
    assert workflow.can_transition(CaseStatus.INTAKE, CaseStatus.TRIAGED)
    assert workflow.can_transition(CaseStatus.ACKNOWLEDGED, CaseStatus.IN_CONVERSATION)
    assert workflow.can_transition(CaseStatus.IN_CONVERSATION, CaseStatus.CLOSED)
    assert not workflow.can_transition(CaseStatus.INTAKE, CaseStatus.HANDOFF_SENT)
    assert CaseStatus.IN_CONVERSATION in workflow.CLINICIAN_VISIBLE
    for s in CaseStatus:
        assert s in workflow.TRANSITIONS


def test_one_consent_can_back_handoffs_to_several_clinicians(people):
    db = SessionLocal()
    patient = uuid.UUID(people["patient_a"]["profile_id"])
    org_id = db.get(ClinicianProfile, uuid.UUID(people["clin_a"]["profile_id"])).user.org_id
    case = MedicalCase(org_id=org_id, patient_id=patient, title="Vomiting", kind=CaseKind.SYMPTOM, status=CaseStatus.INTAKE)
    db.add(case)
    db.flush()
    consent = PatientConsent(case_id=case.id, patient_id=patient, clinician_id=None, audience="CARE_TEAM", scope=["symptom_thread"], purpose="care", status=ConsentStatus.GRANTED)
    db.add(consent)
    db.flush()
    for key in ("clin_a", "clin_b"):
        db.add(ClinicalHandoff(case_id=case.id, consent_id=consent.id, clinician_id=uuid.UUID(people[key]["profile_id"]), status=HandoffStatus.SENT))
    db.commit()
    db.add(ClinicalHandoff(case_id=case.id, consent_id=consent.id, clinician_id=uuid.UUID(people["clin_a"]["profile_id"]), status=HandoffStatus.SENT))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()
