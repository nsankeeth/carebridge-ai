import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import services
from app.agent.validation import admin_message_issues
from app.db import SessionLocal
from app.models import CaseStatus, ClinicalHandoff, ClinicianProfile, HandoffStatus, MedicalCase, MessageAuthor, Notification, Urgency, User
from app.triage import content, routing
from tests.conftest import make_clinician, symptom_case

T0 = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)


def _pid(people, key):
    return uuid.UUID(people[key]["profile_id"])


def _open(case_id):
    db = SessionLocal()
    return db, db.get(MedicalCase, case_id)


def _paged(db, case_id):
    return {h.clinician_id: h for h in db.scalars(select(ClinicalHandoff).where(ClinicalHandoff.case_id == case_id))}


def _system_bodies(case):
    return [m.body for m in case.messages if m.author_type == MessageAuthor.SYSTEM]


def test_urgent_pages_family_doctor_and_first_on_call(people):
    cid = symptom_case(people, status=CaseStatus.TRIAGED)
    db, case = _open(cid)
    routing.apply_level(db, case, Urgency.URGENT, T0)
    db.commit()
    paged = _paged(db, cid)
    assert set(paged) == {_pid(people, "clin_a"), _pid(people, "clin_b")}
    assert all(h.ack_due_at == T0 + timedelta(minutes=15) for h in paged.values())
    assert case.status == CaseStatus.HANDOFF_SENT
    notes = db.scalars(select(Notification)).all()
    assert {n.title for n in notes} == {"Urgent case waiting for you"}
    assert all(admin_message_issues(n.title + " " + n.body) == [] for n in notes)


def test_routine_pages_family_doctor_only(people):
    cid = symptom_case(people, status=CaseStatus.TRIAGED)
    db, case = _open(cid)
    routing.apply_level(db, case, Urgency.ROUTINE, T0)
    db.commit()
    assert set(_paged(db, cid)) == {_pid(people, "clin_a")}


def test_no_family_doctor_pages_on_call(people):
    cid = symptom_case(people, family_doctor=None, status=CaseStatus.TRIAGED)
    db, case = _open(cid)
    routing.apply_level(db, case, Urgency.SOON, T0)
    db.commit()
    assert set(_paged(db, cid)) == {_pid(people, "clin_b")}


def test_family_doctor_who_is_on_call_paged_once(people):
    cid = symptom_case(people, family_doctor="clin_a", on_call=("clin_a", "clin_b"), status=CaseStatus.TRIAGED)
    db, case = _open(cid)
    routing.apply_level(db, case, Urgency.URGENT, T0)
    db.commit()
    # Family doctor counts once; the first *other* on-call clinician is paged alongside.
    assert set(_paged(db, cid)) == {_pid(people, "clin_a"), _pid(people, "clin_b")}


def test_apply_level_is_idempotent(people):
    cid = symptom_case(people, status=CaseStatus.TRIAGED)
    db, case = _open(cid)
    routing.apply_level(db, case, Urgency.URGENT, T0)
    routing.apply_level(db, case, Urgency.URGENT, T0 + timedelta(minutes=1))
    db.commit()
    paged = _paged(db, cid)
    assert len(paged) == 2
    assert all(h.ack_due_at == T0 + timedelta(minutes=15) for h in paged.values())


def test_level_rise_pages_more_and_tightens_deadlines(people):
    cid = symptom_case(people, status=CaseStatus.TRIAGED)
    db, case = _open(cid)
    routing.apply_level(db, case, Urgency.SOON, T0)
    routing.apply_level(db, case, Urgency.URGENT, T0 + timedelta(minutes=10))
    db.commit()
    paged = _paged(db, cid)
    assert set(paged) == {_pid(people, "clin_a"), _pid(people, "clin_b")}
    assert paged[_pid(people, "clin_a")].ack_due_at == T0 + timedelta(minutes=25)


def test_sweep_escalates_after_15_minutes(people):
    cid = symptom_case(people, status=CaseStatus.TRIAGED)
    db, case = _open(cid)
    case.urgency = Urgency.URGENT
    third = make_clinician("Dr Third", case.org_id, on_call=True, priority=5)
    routing.apply_level(db, case, Urgency.URGENT, T0)
    db.commit()
    db.close()
    for _ in range(2):
        db = SessionLocal()
        routing.sweep(db, T0 + timedelta(minutes=16))
        db.commit()
        db.close()
    db, case = _open(cid)
    paged = _paged(db, cid)
    assert third in paged and paged[third].ack_due_at == T0 + timedelta(minutes=31)
    assert len(paged) == 3
    assert sum("another clinician" in b for b in _system_bodies(case)) == 1


def test_sweep_posts_fallback_after_30_minutes_once(people):
    cid = symptom_case(people, status=CaseStatus.TRIAGED)
    db, case = _open(cid)
    case.urgency = Urgency.URGENT
    routing.apply_level(db, case, Urgency.URGENT, T0)
    db.commit()
    db.close()
    for minutes in (31, 32):
        db = SessionLocal()
        routing.sweep(db, T0 + timedelta(minutes=minutes))
        db.commit()
        db.close()
    db, case = _open(cid)
    assert _system_bodies(case).count(content.GUIDANCE_FALLBACK) == 1
    assert case.fallback_advised_at is not None


def test_sweep_skips_acknowledged_case_even_if_deadline_passed(people):
    cid = symptom_case(people, status=CaseStatus.TRIAGED)
    db, case = _open(cid)
    case.urgency = Urgency.URGENT
    routing.apply_level(db, case, Urgency.URGENT, T0)
    db.commit()
    handoff = _paged(db, cid)[_pid(people, "clin_a")]
    actor = db.get(ClinicianProfile, _pid(people, "clin_a")).user
    routing.acknowledge(db, case, handoff, actor)
    db.commit()
    assert case.status == CaseStatus.ACKNOWLEDGED
    assert any("has seen your message" in b for b in _system_bodies(case))
    db.close()
    db = SessionLocal()
    assert routing.sweep(db, T0 + timedelta(hours=2)) == {"escalated": 0, "fallback": 0}
    db.commit()
    db, case = _open(cid)
    assert case.fallback_advised_at is None and len(_paged(db, cid)) == 2


def test_empty_care_team_advises_urgent_care_immediately(people):
    cid = symptom_case(people, family_doctor=None, on_call=(), status=CaseStatus.TRIAGED)
    db, case = _open(cid)
    routing.apply_level(db, case, Urgency.URGENT, T0)
    db.commit()
    assert _paged(db, cid) == {}
    assert content.GUIDANCE_FALLBACK in _system_bodies(case)


def test_withdraw_consent_stops_paging_but_keeps_patient_guidance(people):
    cid = symptom_case(people, status=CaseStatus.TRIAGED)
    db, case = _open(cid)
    case.urgency = Urgency.URGENT
    routing.apply_level(db, case, Urgency.URGENT, T0)
    db.commit()
    patient_user = db.get(User, uuid.UUID(people["patient_a"]["user_id"]))
    services.withdraw_consent(db, case, patient_user)
    db.commit()
    assert all(h.status == HandoffStatus.CANCELLED for h in _paged(db, cid).values())
    assert case.status == CaseStatus.CONSENT_WITHDRAWN and case.urgency == Urgency.URGENT
    assert any("no longer has access" in b for b in _system_bodies(case))
    db.close()
    db = SessionLocal()
    assert routing.sweep(db, T0 + timedelta(hours=1)) == {"escalated": 0, "fallback": 0}
