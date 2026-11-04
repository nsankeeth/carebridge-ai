import json
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.agent.validation import admin_message_issues
from app.db import SessionLocal
from app.models import AuditEvent, ClinicalHandoff, ClinicianProfile, Dependent, MedicalCase, Notification, PatientProfile
from tests.conftest import report_pdf
from tests.test_triage_rules import EXAMPLE


def setup_care_team(people, *, dependent: bool = True) -> str | None:
    """Family doctor clin_a, clin_b on call; optionally a 4-year-old dependent for patient_a. Returns its id."""
    db = SessionLocal()
    patient = db.get(PatientProfile, uuid.UUID(people["patient_a"]["profile_id"]))
    patient.primary_clinician_id = uuid.UUID(people["clin_a"]["profile_id"])
    cb = db.get(ClinicianProfile, uuid.UUID(people["clin_b"]["profile_id"]))
    cb.on_call, cb.on_call_priority = True, 1
    dep_id = None
    if dependent:
        dep = Dependent(patient_id=patient.id, name="Ava", date_of_birth=date.today() - timedelta(days=4 * 365 + 30), relation="daughter")
        db.add(dep)
        db.flush()
        dep_id = str(dep.id)
    db.commit()
    db.close()
    return dep_id


def start_thread(client, headers, body, dependent_id=None):
    r = client.post("/api/patient/threads", headers=headers, json={"subject_dependent_id": dependent_id, "body": body, "consent_confirmed": True})
    assert r.status_code == 201, r.text
    return r.json()["thread"]


def test_create_thread_requires_consent_confirmation(client, auth, people):
    setup_care_team(people)
    r = client.post("/api/patient/threads", headers=auth["patient_a"], json={"subject_dependent_id": None, "body": "tummy hurts", "consent_confirmed": False})
    assert r.status_code == 422
    assert SessionLocal().scalars(select(MedicalCase)).all() == []


def test_parent_creates_thread_for_dependent(client, auth, people):
    dep = setup_care_team(people)
    deps = client.get("/api/patient/dependents", headers=auth["patient_a"]).json()
    assert [d["name"] for d in deps] == ["Ava"] and 4 <= deps[0]["age_years"] < 5
    t = start_thread(client, auth["patient_a"], EXAMPLE, dep)
    assert t["urgency"] == "URGENT" and t["subject"]["name"] == "Ava"
    t = client.get(f"/api/patient/threads/{t['id']}", headers=auth["patient_a"]).json()
    assert "wakes_easily" in {q["id"] for q in t["pending_questions"]}
    assert {c["name"] for c in t["care_team"]} == {"Clin A", "Clin B"}
    assert t["emergency"] is False and t["consent_active"] is True
    r = client.post(f"/api/patient/threads/{t['id']}/answers", headers=auth["patient_a"], json={"question_id": "wakes_easily", "option": "No"})
    assert r.status_code == 200
    t = client.get(f"/api/patient/threads/{t['id']}", headers=auth["patient_a"]).json()
    assert t["urgency"] == "EMERGENCY" and t["emergency"] is True
    assert "wakes_easily" not in {q["id"] for q in t["pending_questions"]}
    listed = client.get("/api/patient/threads", headers=auth["patient_a"]).json()
    assert listed[0]["id"] == t["id"] and listed[0]["subject_name"] == "Ava"


def test_patient_view_never_contains_brief_or_causes(client, auth, people):
    dep = setup_care_team(people)
    t = start_thread(client, auth["patient_a"], EXAMPLE, dep)
    raw = json.dumps(client.get(f"/api/patient/threads/{t['id']}", headers=auth["patient_a"]).json())
    for key in ("possible_causes", "draft_treatment_idea", "reasons", "brief", "model_flags"):
        assert key not in raw
    assert SessionLocal().get(MedicalCase, uuid.UUID(t["id"])).briefs, "a brief exists, just not for the patient"


def test_foreign_dependent_and_thread_are_404(client, auth, people):
    dep = setup_care_team(people)
    r = client.post("/api/patient/threads", headers=auth["patient_b"], json={"subject_dependent_id": dep, "body": "tummy hurts", "consent_confirmed": True})
    assert r.status_code == 404
    assert SessionLocal().scalars(select(MedicalCase)).all() == []
    t = start_thread(client, auth["patient_a"], "tummy hurts")
    for method, path in [("get", ""), ("post", "/messages")]:
        r = getattr(client, method)(f"/api/patient/threads/{t['id']}{path}", headers=auth["patient_b"], **({"json": {"body": "hi"}} if method == "post" else {}))
        assert r.status_code == 404


def test_clinician_queue_sorted_by_urgency(client, auth, people):
    dep = setup_care_team(people)
    soon = start_thread(client, auth["patient_a"], "mild sore throat for two days")
    urgent = start_thread(client, auth["patient_a"], EXAMPLE, dep)
    q = client.get("/api/clinician/queue", headers=auth["clin_a"]).json()
    assert [row["id"] for row in q] == [urgent["id"], soon["id"]]
    assert q[0]["urgency"] == "URGENT" and q[0]["ack_due_at"] and q[0]["subject_name"] == "Ava"


def test_unpaged_clinician_gets_403(client, auth, people):
    setup_care_team(people)
    t = start_thread(client, auth["patient_a"], "mild sore throat for two days")
    assert client.get(f"/api/clinician/threads/{t['id']}", headers=auth["clin_a"]).status_code == 200
    assert client.get(f"/api/clinician/threads/{t['id']}", headers=auth["clin_b"]).status_code == 403


def test_clinician_reply_visible_to_patient_and_moves_to_in_conversation(client, auth, people):
    dep = setup_care_team(people)
    t = start_thread(client, auth["patient_a"], EXAMPLE, dep)
    ca = auth["clin_a"]
    detail = client.get(f"/api/clinician/threads/{t['id']}", headers=ca).json()
    assert detail["brief"]["content"]["possible_causes"] and detail["patient_phone"] is None
    assert client.post(f"/api/clinician/threads/{t['id']}/acknowledge", headers=ca).json()["status"] == "ACKNOWLEDGED"
    r = client.post(f"/api/clinician/threads/{t['id']}/messages", headers=ca, json={"body": "I'll call you in 5 minutes."})
    assert r.json()["status"] == "IN_CONVERSATION"
    pt = client.get(f"/api/patient/threads/{t['id']}", headers=auth["patient_a"]).json()
    assert pt["messages"][-1]["author_type"] == "CLINICIAN" and pt["messages"][-1]["author_name"] == "Clin A"
    titles = [n["title"] for n in client.get("/api/notifications", headers=auth["patient_a"]).json()]
    assert "Your clinician replied" in titles
    assert client.post(f"/api/clinician/threads/{t['id']}/outcome", headers=ca, json={"outcome": "ADVICE_GIVEN", "note": "Fluids plan"}).status_code == 200
    assert client.post(f"/api/clinician/threads/{t['id']}/brief-assessment", headers=ca, json={"assessment": "ACCURATE"}).status_code == 200
    assert client.post(f"/api/clinician/threads/{t['id']}/close", headers=ca).json()["status"] == "CLOSED"


def test_clinician_lowers_urgency_with_reason_and_audit(client, auth, people):
    dep = setup_care_team(people)
    t = start_thread(client, auth["patient_a"], EXAMPLE, dep)
    ca = auth["clin_a"]
    assert client.post(f"/api/clinician/threads/{t['id']}/urgency", headers=ca, json={"level": "SOON"}).status_code == 422
    r = client.post(f"/api/clinician/threads/{t['id']}/urgency", headers=ca, json={"level": "SOON", "reason": "Spoke to parent; drinking now"})
    assert r.status_code == 200
    db = SessionLocal()
    case = db.get(MedicalCase, uuid.UUID(t["id"]))
    assert case.urgency.value == "SOON" and case.urgency_set_by == "clinician"
    assert "child_lethargy" in case.urgency_baseline_flags
    assert db.scalars(select(AuditEvent).where(AuditEvent.action == "triage.urgency_changed")).one()


def test_attachment_processed_without_changing_thread_status(client, auth, people):
    setup_care_team(people)
    t = start_thread(client, auth["patient_a"], "I feel very tired lately")
    before = client.get(f"/api/patient/threads/{t['id']}", headers=auth["patient_a"]).json()["status"]
    r = client.post(f"/api/patient/threads/{t['id']}/attachments", headers=auth["patient_a"], files={"file": ("cbc.pdf", report_pdf(), "application/pdf")})
    assert r.status_code == 201, r.text
    pt = client.get(f"/api/patient/threads/{t['id']}", headers=auth["patient_a"]).json()
    assert pt["status"] == before
    assert pt["attachments"][0]["processing_status"] == "READY"
    kinds = [(m["payload"] or {}).get("kind") for m in pt["messages"]]
    assert "report" in kinds and "report_ready" in kinds
    ct = client.get(f"/api/clinician/threads/{t['id']}", headers=auth["clin_a"]).json()
    assert {f["test_name"] for f in ct["findings"]} >= {"Hemoglobin", "Ferritin"}
    assert client.post(f"/api/patient/threads/{t['id']}/attachments", headers=auth["patient_a"], files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 400


def test_all_feature_notifications_have_no_medical_detail(client, auth, people):
    dep = setup_care_team(people)
    t = start_thread(client, auth["patient_a"], EXAMPLE, dep)
    client.post(f"/api/patient/threads/{t['id']}/answers", headers=auth["patient_a"], json={"question_id": "wakes_easily", "option": "No"})
    client.post(f"/api/clinician/threads/{t['id']}/acknowledge", headers=auth["clin_a"])
    client.post(f"/api/clinician/threads/{t['id']}/messages", headers=auth["clin_a"], json={"body": "Calling 911 for her is right; I'm calling you now."})
    notes = SessionLocal().scalars(select(Notification)).all()
    assert notes
    for n in notes:
        assert admin_message_issues(f"{n.title} {n.body}") == [], n.title


def test_handoffs_exist_per_paged_clinician(client, auth, people):
    dep = setup_care_team(people)
    t = start_thread(client, auth["patient_a"], EXAMPLE, dep)
    hs = SessionLocal().scalars(select(ClinicalHandoff).where(ClinicalHandoff.case_id == uuid.UUID(t["id"]))).all()
    assert len(hs) == 2 and all(h.triage_id for h in hs)


def test_urgency_change_to_the_same_level_is_rejected(client, auth, people):
    dep = setup_care_team(people)
    t = start_thread(client, auth["patient_a"], EXAMPLE, dep)
    r = client.post(f"/api/clinician/threads/{t['id']}/urgency", headers=auth["clin_a"], json={"level": "URGENT", "reason": "Checked"})
    assert r.status_code == 409
    assert SessionLocal().scalars(select(AuditEvent).where(AuditEvent.action == "triage.urgency_changed")).all() == []


def test_putting_a_clinician_on_call_gives_the_next_position(client, auth, people):
    setup_care_team(people, dependent=False)  # clin_b is on call at #1
    r = client.patch(f"/api/admin/users/{people['clin_a']['user_id']}", headers=auth["admin"], json={"on_call": True})
    assert r.status_code == 200
    assert SessionLocal().get(ClinicianProfile, uuid.UUID(people["clin_a"]["profile_id"])).on_call_priority == 2
