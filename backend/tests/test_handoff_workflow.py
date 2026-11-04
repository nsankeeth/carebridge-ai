import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import workflow
from app.agent import coordinator
from app.ai.provider import AssistantTurn, ToolCall
from app.agent.validation import admin_message_issues
from app.db import SessionLocal
from app.errors import Conflict
from app.models import AgentExecution, AuditEvent, CaseStatus, ClinicalHandoff, FollowUpTask, MedicalCase, Notification
from app.services import now
from tests.conftest import FakeProvider, share, upload


def test_handoff_requires_consent(client, auth):
    case = upload(client, auth["patient_a"])
    r = client.post(f"/api/patient/cases/{case['id']}/handoff", headers=auth["patient_a"])
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "consent_required"
    db = SessionLocal()
    assert db.scalars(select(ClinicalHandoff)).all() == []


def test_consent_requires_explicit_confirmation(client, auth, people):
    case = upload(client, auth["patient_a"])
    client.post(f"/api/patient/cases/{case['id']}/consent/request", headers=auth["patient_a"])
    r = client.post(f"/api/patient/cases/{case['id']}/consent", headers=auth["patient_a"], json={"clinician_id": people["clin_a"]["profile_id"], "confirmed": False})
    assert r.status_code == 400


def test_agent_tool_cannot_bypass_consent(client, auth):
    """Even if the model calls create_clinician_handoff, the backend refuses without consent."""
    case = upload(client, auth["patient_a"])
    db = SessionLocal()
    c = db.get(MedicalCase, case["id"])
    runner = coordinator.ToolRunner(db, c, "HANDOFF", None)
    result = runner.run(ToolCall(id="1", name="create_clinician_handoff", arguments="{}"))
    assert result["ok"] is False and result["code"] == "consent_required"
    # And tools outside the allow-list are refused outright.
    result = runner.run(ToolCall(id="2", name="set_case_status", arguments='{"status": "CLOSED"}'))
    assert result["ok"] is False
    db.refresh(c)
    assert c.status == CaseStatus.SUMMARY_READY


def test_consented_handoff_via_agent_and_clinician_review(client, auth, people):
    pa, ca = auth["patient_a"], auth["clin_a"]
    case = upload(client, pa)
    share(client, auth, people, case["id"])
    detail = client.get(f"/api/patient/cases/{case['id']}", headers=pa).json()
    assert detail["status"] == "HANDOFF_SENT"
    run = next(e for e in detail["executions"] if e["kind"] == "HANDOFF")
    assert run["status"] == "SUCCEEDED"
    assert [s["tool"] for s in run["steps"] if s["type"] == "tool_call"] == ["get_case_snapshot", "create_clinician_handoff", "notify_patient"]

    assert [c["id"] for c in client.get("/api/clinician/cases", headers=ca).json()] == [case["id"]]
    cd = client.get(f"/api/clinician/cases/{case['id']}", headers=ca).json()
    assert cd["summary"]["clinician_summary"]["key_findings"]
    assert client.get(f"/api/clinician/cases/{case['id']}/document", headers=ca).headers["content-type"] == "application/pdf"

    # Review can't start before acknowledgement; completion needs a summary assessment.
    assert client.post(f"/api/clinician/cases/{case['id']}/review/start", headers=ca).status_code == 409
    assert client.post(f"/api/clinician/cases/{case['id']}/acknowledge", headers=ca).json()["status"] == "ACKNOWLEDGED"
    assert client.post(f"/api/clinician/cases/{case['id']}/review/start", headers=ca).json()["status"] == "UNDER_REVIEW"
    r = client.post(f"/api/clinician/cases/{case['id']}/review/complete", headers=ca, json={"next_step": "REPEAT_TEST"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "assessment_required"
    r = client.post(f"/api/clinician/cases/{case['id']}/summary-assessment", headers=ca, json={"assessment": "CORRECTED"})
    assert r.status_code == 400  # correction text required
    assert client.post(f"/api/clinician/cases/{case['id']}/summary-assessment", headers=ca, json={"assessment": "CORRECTED", "correction": "MCV is borderline, not markedly low."}).status_code == 200
    r = client.post(f"/api/clinician/cases/{case['id']}/review/complete", headers=ca, json={"next_step": "REPEAT_TEST", "clinical_notes": "Repeat CBC in 6 weeks.", "patient_message": "Please book a repeat blood test."})
    assert r.json()["status"] == "REVIEW_COMPLETED"

    detail = client.get(f"/api/patient/cases/{case['id']}", headers=pa).json()
    assert detail["status"] == "REVIEW_COMPLETED"
    assert detail["review"]["next_step"] == "REPEAT_TEST"
    assert "clinical_notes" not in detail["review"]
    titles = [n["title"] for n in client.get("/api/notifications", headers=pa).json()]
    assert "Your clinician completed their review" in titles and "Your clinician received your report" in titles
    tasks = client.get("/api/admin/tasks", headers=auth["admin"]).json()
    assert [t["kind"] for t in tasks] == ["next_step:REPEAT_TEST"]
    assert client.post(f"/api/patient/cases/{case['id']}/close", headers=pa).json()["status"] == "CLOSED"

    actions = {e.action for e in SessionLocal().scalars(select(AuditEvent))}
    for a in ("document.uploaded", "ai.summary_generated", "consent.granted", "handoff.sent", "clinician.case_viewed", "handoff.acknowledged", "review.completed", "followup.created"):
        assert a in actions, a


def test_duplicate_handoff_requests_create_one_referral(client, auth, people):
    case = upload(client, auth["patient_a"])
    share(client, auth, people, case["id"])
    for _ in range(3):
        r = client.post(f"/api/patient/cases/{case['id']}/handoff", headers=auth["patient_a"])
        assert r.status_code == 202
    db = SessionLocal()
    assert len(db.scalars(select(ClinicalHandoff).where(ClinicalHandoff.case_id == case["id"])).all()) == 1
    # Direct service call is idempotent too.
    from app import services

    c = db.get(MedicalCase, case["id"])
    _, created = services.create_handoff(db, c, actor=None, actor_type="AGENT")
    assert created is False


def test_withdrawing_consent_revokes_future_clinician_access(client, auth, people):
    case = upload(client, auth["patient_a"])
    share(client, auth, people, case["id"])
    assert client.get(f"/api/clinician/cases/{case['id']}", headers=auth["clin_a"]).status_code == 200
    assert client.post(f"/api/patient/cases/{case['id']}/consent/withdraw", headers=auth["patient_a"]).json()["status"] == "CONSENT_WITHDRAWN"
    assert client.get(f"/api/clinician/cases/{case['id']}", headers=auth["clin_a"]).status_code == 403
    assert client.get("/api/clinician/cases", headers=auth["clin_a"]).json() == []
    # Withdrawn consent can't be used for a new handoff.
    assert client.post(f"/api/patient/cases/{case['id']}/handoff", headers=auth["patient_a"]).status_code == 409


def test_state_machine_rejects_invalid_transitions():
    db = SessionLocal()
    c = MedicalCase(status=CaseStatus.UPLOADED)
    with pytest.raises(Conflict):
        workflow.transition(db, c, CaseStatus.HANDOFF_SENT)
    assert workflow.can_transition(CaseStatus.PROCESSING, CaseStatus.SUMMARY_READY)
    assert not workflow.can_transition(CaseStatus.SUMMARY_READY, CaseStatus.HANDOFF_SENT)
    assert not workflow.can_transition(CaseStatus.CLOSED, CaseStatus.PROCESSING)
    for s in CaseStatus:
        assert s in workflow.TRANSITIONS


def test_follow_up_agent_creates_reminder_for_overdue_handoff_once(client, auth, people):
    case = upload(client, auth["patient_a"])
    share(client, auth, people, case["id"])
    db = SessionLocal()
    h = db.scalars(select(ClinicalHandoff)).one()
    h.sent_at = now() - timedelta(hours=30)
    db.commit()

    for _ in range(2):
        r = client.post("/api/admin/follow-up/run", headers=auth["admin"])
        assert r.status_code == 202
    db = SessionLocal()
    tasks = db.scalars(select(FollowUpTask).where(FollowUpTask.case_id == case["id"])).all()
    assert [t.kind for t in tasks] == ["ack_reminder"]
    assert tasks[0].created_by == "agent"
    assert any(n.title.startswith("Follow-up") for n in db.scalars(select(Notification).where(Notification.user_id == people["clin_a"]["user_id"])))
    runs = db.scalars(select(AgentExecution).where(AgentExecution.kind == "FOLLOW_UP")).all()
    assert len(runs) == 2 and all(r.status.value == "SUCCEEDED" for r in runs)

    # Acknowledging closes the reminder.
    client.post(f"/api/clinician/cases/{case['id']}/acknowledge", headers=auth["clin_a"])
    db = SessionLocal()
    assert db.scalars(select(FollowUpTask).where(FollowUpTask.case_id == case["id"])).one().status.value == "DONE"


def test_agent_messages_with_medical_details_are_blocked(client, auth, people):
    assert admin_message_issues("Your ferritin is 9 ug/L") != []
    assert admin_message_issues("Your case was shared with your clinician.") == []

    case = upload(client, auth["patient_a"])
    db = SessionLocal()
    c = db.get(MedicalCase, case["id"])
    runner = coordinator.ToolRunner(db, c, "HANDOFF", None)
    r = runner.run(ToolCall(id="1", name="notify_patient", arguments=json.dumps({"title": "Update", "body": "Your hemoglobin of 112 is low."})))
    assert r["ok"] is False
    assert db.scalars(select(Notification)).all() == []


def test_handoff_run_fails_honestly_if_agent_does_not_hand_off(client, auth, people, monkeypatch):
    monkeypatch.setattr(FakeProvider, "tool_step", lambda self, **kw: (AssistantTurn(content="Nothing to do."), self._meta("coordinator_handoff")))
    case = upload(client, auth["patient_a"])
    share(client, auth, people, case["id"])
    detail = client.get(f"/api/patient/cases/{case['id']}", headers=auth["patient_a"]).json()
    assert detail["status"] == "CONSENT_GRANTED"
    run = next(e for e in detail["executions"] if e["kind"] == "HANDOFF")
    assert run["status"] == "FAILED" and "retried" in run["error"]


def test_agent_can_notify_clinician_right_after_creating_handoff(client, auth, people):
    """Regression: the clinician check must see a handoff created earlier in the same agent run."""
    case = upload(client, auth["patient_a"])
    h = auth["patient_a"]
    client.post(f"/api/patient/cases/{case['id']}/consent/request", headers=h)
    client.post(f"/api/patient/cases/{case['id']}/consent", headers=h, json={"clinician_id": people["clin_a"]["profile_id"], "confirmed": True})
    db = SessionLocal()
    c = db.get(MedicalCase, case["id"])
    runner = coordinator.ToolRunner(db, c, "HANDOFF", None)
    # Same order as the live Meta run: the snapshot loads case.handoffs before the handoff exists.
    assert runner.run(ToolCall(id="0", name="get_case_snapshot", arguments="{}"))["ok"] is True
    assert runner.run(ToolCall(id="1", name="create_clinician_handoff", arguments="{}"))["ok"] is True
    msg ={"title": "New case shared for review", "body": "A patient case has been shared with you for review."}
    assert runner.run(ToolCall(id="2", name="notify_clinician", arguments=json.dumps(msg))) == {"ok": True}
    assert db.scalars(select(Notification).where(Notification.user_id == people["clin_a"]["user_id"])).one().title == msg["title"]


@pytest.mark.parametrize(
    "text,blocked",
    [
        ("Handoff sent over 24 hours ago remains unacknowledged", False),
        ("Handoff remains unacknowledged past acknowledgement window", False),
        ("Please respond within 3 business days.", False),
        ("Your ALT is 62 U/L", True),
        ("Your ferritin result needs review", True),
        ("LDL came back at 4.3", True),
        ("The value was 7.1", True),
    ],
)
def test_admin_message_filter(text, blocked):
    assert bool(admin_message_issues(text)) is blocked


def test_follow_up_agent_leaves_symptom_threads_to_the_escalation_sweep(people):
    # Symptom threads escalate on their own clock (routing.sweep); their care-team consent names no single clinician.
    from app.agent.coordinator import follow_up_candidates
    from app.models import CaseStatus, MedicalCase
    from tests.conftest import symptom_case

    cid = symptom_case(people, status=CaseStatus.HANDOFF_SENT)
    db = SessionLocal()
    org_id = db.get(MedicalCase, cid).org_id
    assert cid not in {c.id for c in follow_up_candidates(db, org_id)}
    db.close()
