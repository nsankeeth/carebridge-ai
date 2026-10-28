"""Service-layer authorization for patient records. Every route that touches a case goes through here."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Forbidden, NotFound
from app.models import (
    ClinicalHandoff,
    ConsentStatus,
    HandoffStatus,
    MedicalCase,
    PatientConsent,
    User,
)
from app.workflow import CLINICIAN_VISIBLE


def patient_case(db: Session, user: User, case_id: uuid.UUID) -> MedicalCase:
    """A patient may only ever see their own cases. Other patients' cases look like 404s."""
    case = db.get(MedicalCase, case_id)
    if not case or not user.patient_profile or case.patient_id != user.patient_profile.id:
        raise NotFound("Case not found")
    return case


def active_handoff_for(db: Session, case_id: uuid.UUID, clinician_profile_id: uuid.UUID) -> ClinicalHandoff | None:
    """The handoff that currently authorizes this clinician, backed by consent that is still granted."""
    return db.scalar(
        select(ClinicalHandoff)
        .join(PatientConsent, PatientConsent.id == ClinicalHandoff.consent_id)
        .where(
            ClinicalHandoff.case_id == case_id,
            ClinicalHandoff.clinician_id == clinician_profile_id,
            ClinicalHandoff.status != HandoffStatus.CANCELLED,
            PatientConsent.status == ConsentStatus.GRANTED,
        )
        .order_by(ClinicalHandoff.sent_at.desc())
    )


def clinician_case(db: Session, user: User, case_id: uuid.UUID) -> tuple[MedicalCase, ClinicalHandoff]:
    """A clinician may see a case only through an active, consented handoff addressed to them."""
    case = db.get(MedicalCase, case_id)
    profile = user.clinician_profile
    if not case or not profile or case.org_id != user.org_id:
        raise NotFound("Case not found")
    handoff = active_handoff_for(db, case.id, profile.id)
    if not handoff or case.status not in CLINICIAN_VISIBLE:
        raise Forbidden("This case has not been shared with you")
    return case, handoff
