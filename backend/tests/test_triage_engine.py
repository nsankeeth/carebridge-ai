import uuid

import pytest

from app.ai.provider import CallMeta, ModelCallError, set_provider_override
from app.db import SessionLocal
from app.errors import Conflict
from app.models import CaseStatus, MedicalCase, MessageAuthor, Urgency, User
from app.triage import content, engine
from app.triage.messages import post_message
from tests import fake_outputs
from tests.conftest import FakeProvider, symptom_case
from tests.test_triage_rules import EXAMPLE


def _triage_override(**changes):
    def make(ctx):
        out = fake_outputs.structured("triage_assessment", ctx)
        out.update(changes)
        return out

    return make


def _open(cid):
    db = SessionLocal()
    return db, db.get(MedicalCase, cid)


def _intake_and_model(cid):
    db, case = _open(cid)
    a = engine.intake(db, case, case.messages[-1])
    db.commit()
    aid = a.id
    db.close()
    engine.run_model_triage(aid)
    return _open(cid)


def _new_message(cid, text):
    db, case = _open(cid)
    m = post_message(db, case, MessageAuthor.PATIENT, text)
    a = engine.intake(db, case, m)
    db.commit()
    aid = a.id
    db.close()
    engine.run_model_triage(aid)


def _bodies(case, author):
    return [m.body for m in case.messages if m.author_type == author]


def _guidance(case):
    return [m.body for m in case.messages if (m.payload or {}).get("kind") == "guidance"]


def _questions(case):
    return [q for m in case.messages if (m.payload or {}).get("kind") == "questions" for q in m.payload["questions"]]


class _NoModel:
    name, model_id = "none", "none"

    def structured(self, **_):
        raise AssertionError("model must not be called during intake")

    tool_step = structured


def test_emergency_intake_makes_no_model_call(people):
    cid = symptom_case(people, text="I have crushing chest pain")
    set_provider_override(_NoModel)
    db, case = _open(cid)
    a = engine.intake(db, case, case.messages[-1])
    db.commit()
    assert a.final_level == Urgency.EMERGENCY and case.urgency == Urgency.EMERGENCY
    assert any("Call 911" in b for b in _bodies(case, MessageAuthor.AI))
    assert case.status == CaseStatus.HANDOFF_SENT


def test_example_thread_end_to_end_with_fake_model(people):
    cid = symptom_case(people, text=EXAMPLE, dependent_age_years=4)
    db, case = _intake_and_model(cid)
    assert case.urgency == Urgency.URGENT
    assert "wakes_easily" in {q["id"] for q in _questions(case)}
    assert any(content.GUIDANCE[Urgency.URGENT] in b for b in _bodies(case, MessageAuthor.AI))
    assert case.triage_assessments[-1].status == "complete"
    assert case.briefs, "brief generated after triage"


def test_model_cannot_lower_rule_level(people):
    cid = symptom_case(people, text=EXAMPLE, dependent_age_years=4)
    FakeProvider.overrides = {"triage_assessment": _triage_override(level="ROUTINE")}
    db, case = _intake_and_model(cid)
    assert case.urgency == Urgency.URGENT
    assert case.triage_assessments[-1].final_level == Urgency.URGENT


def test_model_can_raise_level(people):
    cid = symptom_case(people, text="My stomach has been hurting since last night")
    FakeProvider.overrides = {"triage_assessment": _triage_override(level="URGENT", red_flags=[{"flag": "pain", "patient_quote": "stomach has been hurting"}])}
    db, case = _intake_and_model(cid)
    assert case.urgency == Urgency.URGENT and case.urgency_set_by == "model"
    assert case.status == CaseStatus.HANDOFF_SENT


def test_ungrounded_model_flag_is_dropped(people):
    cid = symptom_case(people, text="My stomach has been hurting since last night")
    FakeProvider.overrides = {"triage_assessment": _triage_override(red_flags=[{"flag": "seizure", "patient_quote": "had a seizure"}])}
    db, case = _intake_and_model(cid)
    a = case.triage_assessments[-1]
    assert [f["flag"] for f in a.dropped_flags] == ["seizure"]
    assert a.model_flags == []


def test_model_failure_falls_back_to_soon_and_pages(people):
    cid = symptom_case(people, text="My stomach has been hurting since last night")
    FakeProvider.overrides = {"triage_assessment": lambda _: ModelCallError(CallMeta(task="triage_assessment", provider="fake", model_id="fake-model", status="error", error="timeout"), "timeout")}
    db, case = _intake_and_model(cid)
    assert case.urgency == Urgency.SOON and case.urgency_set_by == "fallback"
    assert case.triage_assessments[-1].status == "model_failed"
    assert case.status == CaseStatus.HANDOFF_SENT and case.handoffs
    assert _guidance(case)[-1].startswith(content.GUIDANCE[Urgency.SOON])


def test_unsafe_acknowledgement_is_replaced_by_template(people):
    cid = symptom_case(people, text="My stomach has been hurting since last night")
    FakeProvider.overrides = {"triage_assessment": _triage_override(acknowledgement="You likely have an infection.")}
    db, case = _intake_and_model(cid)
    last = _guidance(case)[-1]
    assert "infection" not in last and last.startswith(content.GUIDANCE[Urgency.SOON])


def test_answer_no_to_wakes_easily_escalates_to_emergency(people):
    cid = symptom_case(people, text=EXAMPLE, dependent_age_years=4)
    db, case = _intake_and_model(cid)
    actor = db.get(User, uuid.UUID(people["patient_a"]["user_id"]))
    engine.answer(db, case, "wakes_easily", "No", actor)
    db.commit()
    assert case.urgency == Urgency.EMERGENCY
    assert any("Call 911" in b for b in _bodies(case, MessageAuthor.AI))


def test_invalid_answer_rejected(people):
    cid = symptom_case(people, text=EXAMPLE, dependent_age_years=4)
    db, case = _intake_and_model(cid)
    actor = db.get(User, uuid.UUID(people["patient_a"]["user_id"]))
    with pytest.raises(Conflict):
        engine.answer(db, case, "never_asked", "Yes", actor)
    with pytest.raises(Conflict):
        engine.answer(db, case, "wakes_easily", "Maybe", actor)
    engine.answer(db, case, "wakes_easily", "Yes", actor)
    with pytest.raises(Conflict):
        engine.answer(db, case, "wakes_easily", "No", actor)


def test_level_never_drops_across_messages(people):
    cid = symptom_case(people, text=EXAMPLE, dependent_age_years=4)
    _intake_and_model(cid)
    FakeProvider.overrides = {"triage_assessment": _triage_override(level="ROUTINE")}
    _new_message(cid, "She drank a little now")
    db, case = _open(cid)
    assert case.urgency == Urgency.URGENT


def test_clinician_baseline_ignores_repeated_flags(people):
    cid = symptom_case(people, text=EXAMPLE, dependent_age_years=4)
    _intake_and_model(cid)
    db, case = _open(cid)
    case.urgency, case.urgency_set_by = Urgency.SOON, "clinician"
    case.urgency_baseline_flags = ["child_lethargy", "child_refusing_fluids"]
    db.commit()
    db.close()
    FakeProvider.overrides = {"triage_assessment": _triage_override(level="URGENT")}
    _new_message(cid, "ok thanks, she is still very lethargic")
    db, case = _open(cid)
    assert case.urgency == Urgency.SOON
    db.close()
    _new_message(cid, "she won't wake up")
    db, case = _open(cid)
    assert case.urgency == Urgency.EMERGENCY


def test_no_questions_after_two_rounds_or_at_emergency(people):
    cid = symptom_case(people, text=EXAMPLE, dependent_age_years=4)
    _intake_and_model(cid)
    _new_message(cid, "still the same")
    _new_message(cid, "still the same again")
    db, case = _open(cid)
    rounds = [m.payload["round"] for m in case.messages if (m.payload or {}).get("kind") == "questions"]
    assert rounds == [1, 2]
    cid2 = symptom_case(people, text="I have crushing chest pain")
    db, case = _intake_and_model(cid2)
    assert _questions(case) == []


def test_model_question_with_overlong_option_is_not_asked(people):
    # Review M2: options the answer API rejects (>60 chars) must never be rendered as buttons.
    long_opt = "Yes, and it has been getting steadily worse over the last several hours"
    cid = symptom_case(people, text="My stomach has been hurting since last night")
    FakeProvider.overrides = {"triage_assessment": _triage_override(follow_up_questions=[
        {"id": "pain_change", "question": "Is the pain changing?", "options": [long_opt, "No"]},
        {"id": "pain_where", "question": "Where is the pain?", "options": ["Upper", "Lower"]},
    ])}
    db, case = _intake_and_model(cid)
    assert {q["id"] for q in _questions(case)} == {"pain_where"}


def test_model_run_does_not_overwrite_a_concurrent_emergency(people):
    # Review C1: while Meta is thinking about message 1, message 2 ("turning blue") commits EMERGENCY.
    # The background run must re-read the case, not write its stale level/status over it.
    cid = symptom_case(people, text="My stomach has been hurting since last night")
    db, case = _open(cid)
    a = engine.intake(db, case, case.messages[-1])
    db.commit()
    aid = a.id
    db.close()

    def concurrent_request(ctx):
        other, c2 = _open(cid)
        m = post_message(other, c2, MessageAuthor.PATIENT, "Now her lips are turning blue")
        engine.intake(other, c2, m)
        other.commit()
        other.close()
        return fake_outputs.structured("triage_assessment", ctx) | {"level": "URGENT"}

    FakeProvider.overrides = {"triage_assessment": concurrent_request}
    engine.run_model_triage(aid)
    db, case = _open(cid)
    assert case.urgency == Urgency.EMERGENCY
    assert case.status == CaseStatus.HANDOFF_SENT


def test_stale_intake_is_recovered_by_the_sweep(people):
    # Review I1: if the background Meta run is lost (restart, crash), the thread must not sit in INTAKE unpaged.
    from datetime import timedelta

    from app.services import now

    stale = symptom_case(people, text="My stomach has been hurting since last night")
    fresh = symptom_case(people, text="My knee is a bit sore")
    for cid in (stale, fresh):
        db, case = _open(cid)
        engine.intake(db, case, case.messages[-1])
        db.commit()
        db.close()
    db = SessionLocal()
    assert engine.recover_stale_intake(db, now() + timedelta(seconds=5)) == 0
    db.get(MedicalCase, stale).created_at = now() - timedelta(minutes=5)
    db.commit()
    assert engine.recover_stale_intake(db, now()) == 1
    db.commit()
    db, case = _open(stale)
    assert case.urgency == Urgency.SOON and case.urgency_set_by == "fallback"
    assert case.status == CaseStatus.HANDOFF_SENT and case.handoffs
    assert _guidance(case)[-1].startswith(content.GUIDANCE[Urgency.SOON])
    assert SessionLocal().get(MedicalCase, fresh).status == CaseStatus.INTAKE
