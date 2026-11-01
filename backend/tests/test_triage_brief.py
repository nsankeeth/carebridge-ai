import uuid

import pytest

from app.db import SessionLocal
from app.errors import AppError
from app.models import ClinicianProfile, DocumentStatus, ExtractedFinding, MedicalDocument, FindingStatus, MedicalCase, MessageAuthor, SummaryAssessment
from app.triage import brief
from app.triage.messages import post_message
from tests.conftest import FakeProvider, symptom_case

TEXT = "She is very lethargic and refusing to drink anything"


def _brief_override(**changes):
    def make(ctx):
        quote = "very lethargic"
        out = {
            "headline": "4-year-old, vomiting, lethargic",
            "timeline": ["Vomiting for four hours"],
            "red_flags": [{"flag": "child_lethargy", "patient_quote": quote}],
            "possible_causes": [{"cause": "Gastroenteritis", "supporting_quotes": [quote], "against_quotes": [], "likelihood": "higher"}],
            "suggested_questions": ["Last wet diaper?"],
            "suggested_next_steps": ["Call parent now"],
            "draft_treatment_idea": "Oral rehydration trial.",
        }
        out.update(changes)
        return out

    return make


def test_brief_quotes_are_grounded(people):
    cid = symptom_case(people, text=TEXT)
    FakeProvider.overrides = {"clinician_triage_brief": _brief_override(
        red_flags=[{"flag": "child_lethargy", "patient_quote": "very lethargic"}, {"flag": "seizure", "patient_quote": "she had a seizure"}],
        possible_causes=[{"cause": "X", "supporting_quotes": ["refusing to drink", "invented words"], "against_quotes": ["also invented"], "likelihood": "higher"}],
    )}
    brief.generate(cid)
    b = SessionLocal().get(MedicalCase, cid).briefs[-1]
    assert [f["flag"] for f in b.content["red_flags"]] == ["child_lethargy"]
    assert b.content["possible_causes"][0]["supporting_quotes"] == ["refusing to drink"]
    assert b.content["possible_causes"][0]["against_quotes"] == []
    assert len(b.validation_issues) == 3


def test_what_ai_told_patient_comes_from_messages(people):
    cid = symptom_case(people, text=TEXT)
    db = SessionLocal()
    case = db.get(MedicalCase, cid)
    post_message(db, case, MessageAuthor.AI, "Thanks for telling us. A clinician is being contacted.")
    post_message(db, case, MessageAuthor.SYSTEM, "We're contacting another clinician.")
    db.commit()
    brief.generate(cid)
    b = SessionLocal().get(MedicalCase, cid).briefs[-1]
    assert b.content["what_ai_told_patient"] == ["Thanks for telling us. A clinician is being contacted.", "We're contacting another clinician."]


def test_brief_versions_increment(people):
    cid = symptom_case(people, text=TEXT)
    brief.generate(cid)
    brief.generate(cid)
    assert [b.version for b in SessionLocal().get(MedicalCase, cid).briefs] == [1, 2]


def test_brief_includes_attached_report_findings_in_prompt(people):
    cid = symptom_case(people, text=TEXT)
    db = SessionLocal()
    doc = MedicalDocument(case_id=cid, filename="r.pdf", storage_key="k", content_type="application/pdf", size_bytes=1, sha256="0" * 64, processing_status=DocumentStatus.READY)
    db.add(doc)
    db.flush()
    db.add(ExtractedFinding(case_id=cid, document_id=doc.id, test_name="Ferritin", value="9", unit="ug/L", reference_range="15-150", flag="L", status=FindingStatus.VERIFIED, position=0, extraction_method="meta"))
    db.commit()
    seen = {}

    def capture(ctx):
        seen["prompt"] = ctx["prompt"]
        return _brief_override()(ctx)

    FakeProvider.overrides = {"clinician_triage_brief": capture}
    brief.generate(cid)
    assert "Ferritin" in seen["prompt"] and "9 ug/L" in seen["prompt"]


def test_model_failure_creates_no_brief(people):
    from app.ai.provider import CallMeta, ModelCallError

    cid = symptom_case(people, text=TEXT)
    FakeProvider.overrides = {"clinician_triage_brief": lambda _: ModelCallError(CallMeta(task="clinician_triage_brief", provider="fake", model_id="fake-model", status="error", error="timeout"), "timeout")}
    brief.generate(cid)
    assert SessionLocal().get(MedicalCase, cid).briefs == []


def test_assess_requires_correction(people):
    cid = symptom_case(people, text=TEXT)
    brief.generate(cid)
    db = SessionLocal()
    case = db.get(MedicalCase, cid)
    actor = db.get(ClinicianProfile, uuid.UUID(people["clin_a"]["profile_id"])).user
    with pytest.raises(AppError):
        brief.assess(db, case, actor, SummaryAssessment.CORRECTED, " ")
    b = brief.assess(db, case, actor, SummaryAssessment.CORRECTED, "Lethargy is mild")
    assert b.assessment == SummaryAssessment.CORRECTED and b.correction == "Lethargy is mild"
