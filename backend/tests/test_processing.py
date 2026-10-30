from sqlalchemy import select

from app.agent.documents import extract_pages, parse_rows
from app.agent.validation import reconcile_findings
from app.ai.provider import CallMeta, ModelCallError
from app.ai.schemas import ExtractionResult
from app.db import SessionLocal
from app.models import AISummary, ModelCall, SummaryStatus
from tests.conftest import FakeProvider, report_pdf, upload


def test_upload_rejects_non_pdf(client, auth):
    r = client.post("/api/patient/cases/upload", headers=auth["patient_a"], data={"title": "x"}, files={"file": ("r.pdf", b"hello", "application/pdf")})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_file"


def test_upload_rejects_oversized_file(client, auth):
    big = b"%PDF-" + b"0" * (10 * 1024 * 1024 + 10)
    r = client.post("/api/patient/cases/upload", headers=auth["patient_a"], data={"title": "x"}, files={"file": ("r.pdf", big, "application/pdf")})
    assert r.status_code == 413


def test_upload_processes_report_into_findings_and_summary(client, auth):
    case = upload(client, auth["patient_a"])
    assert case["status"] == "SUMMARY_READY"
    names = {f["test_name"]: f for f in case["findings"]}
    assert names["Hemoglobin"]["value"] == "112"
    assert names["Hemoglobin"]["unit"] == "g/L"
    assert names["Hemoglobin"]["reference_range"] == "120-160"
    assert names["Hemoglobin"]["flag"] == "L"
    assert names["Hemoglobin"]["source_page"] == 1
    assert names["Ferritin"]["report_date"] == "2026-10-28"
    assert all(f["status"] == "VERIFIED" for f in case["findings"])
    assert case["summary"]["status"] == "ACTIVE"
    assert "clinician_summary" not in case["summary"]  # patients get the patient view only
    steps = [s["name"] for s in case["executions"][0]["steps"]]
    assert steps == ["document_processing", "deterministic_parse", "meta_report_understanding", "finding_validation", "meta_patient_explanation", "meta_clinician_summary", "output_validation"]


def test_every_model_call_is_logged(client, auth):
    case = upload(client, auth["patient_a"])
    db = SessionLocal()
    calls = db.scalars(select(ModelCall).where(ModelCall.case_id == case["id"])).all()
    assert {c.task for c in calls} == {"report_understanding", "patient_explanation", "clinician_summary"}
    assert all(c.model_id == "fake-model" and c.status == "ok" for c in calls)


def test_deterministic_parser_preserves_exact_values():
    rows = parse_rows(extract_pages(report_pdf("demo-upload-lipids-thyroid")))
    got = {r.test_name: (r.value, r.unit, r.reference_range, r.flag) for r in rows}
    assert got["Total Cholesterol"] == ("6.4", "mmol/L", "<5.2", "H")
    assert got["HDL Cholesterol"] == ("1.3", "mmol/L", ">1.2", None)
    assert got["Vitamin B12"] == ("245", "pmol/L", "148-616", None)


def test_hallucinated_or_altered_values_are_marked_for_review():
    pages = extract_pages(report_pdf())
    rows = parse_rows(pages)
    ai = ExtractionResult(
        lab_name="Northbridge Medical Laboratories",
        report_date="2026-10-28",
        findings=[
            # altered value: source line says 112
            {"test_name": "Hemoglobin", "value": "121", "unit": "g/L", "reference_range": "120-160", "flag": None, "source_page": 1, "source_quote": "Hemoglobin 121 g/L 120-160"},
            # invented test that is not in the report
            {"test_name": "Vitamin D", "value": "40", "unit": "nmol/L", "reference_range": "75-250", "flag": "L", "source_page": 1, "source_quote": "Vitamin D 40 nmol/L 75-250 L"},
        ],
        ambiguities=[],
    )
    drafts, issues, lab, date = reconcile_findings(ai, rows, pages)
    by_name = {d.test_name: d for d in drafts}
    assert by_name["Hemoglobin"].status == "NEEDS_REVIEW"
    assert by_name["Vitamin D"].status == "NEEDS_REVIEW"
    # Rows the model skipped are recovered from the source text.
    assert by_name["Ferritin"].method == "deterministic" and by_name["Ferritin"].value == "9"
    assert lab == "Northbridge Medical Laboratories" and date == "2026-10-28"


def test_invalid_model_output_fails_processing_without_a_summary(client, auth):
    def bad(_ctx):
        return ModelCallError(CallMeta(task="report_understanding", provider="fake", model_id="fake-model", status="invalid_output", error="not json"), "invalid")

    FakeProvider.overrides = {"report_understanding": bad}
    case = upload(client, auth["patient_a"])
    assert case["status"] == "PROCESSING_FAILED"
    assert case["summary"] is None
    assert case["executions"][0]["status"] == "FAILED"
    db = SessionLocal()
    assert db.scalars(select(AISummary).where(AISummary.case_id == case["id"])).all() == []
    statuses = [c.status for c in db.scalars(select(ModelCall).where(ModelCall.case_id == case["id"]))]
    assert statuses == ["invalid_output", "invalid_output"]  # retried once, then gave up


def test_model_api_error_fails_processing(client, auth):
    FakeProvider.overrides = {"patient_explanation": lambda _: ModelCallError(CallMeta(task="patient_explanation", provider="fake", model_id="fake-model", status="error", error="timeout"), "timeout")}
    case = upload(client, auth["patient_a"])
    assert case["status"] == "PROCESSING_FAILED"
    assert case["summary"] is None
    # Retry is allowed from the failed state.
    FakeProvider.overrides = {}
    r = client.post(f"/api/agent/cases/{case['id']}/process", headers=auth["patient_a"])
    assert r.status_code == 202
    assert client.get(f"/api/patient/cases/{case['id']}", headers=auth["patient_a"]).json()["status"] == "SUMMARY_READY"


def test_unsafe_generated_text_is_caught_and_case_needs_correction(client, auth):
    def unsafe_explanation(ctx):
        f = ctx["findings"]
        return {
            "overview": "Your results are consistent with iron deficiency anemia. You should start taking iron supplements.",
            "findings": [{"finding_id": x.id, "plain_language": "Measured."} for x in f],
            "items_for_clinician_review": [{"finding_id": x.id, "reason": "flagged"} for x in f if x.flag],
            "questions_to_ask": [],
            "limitations": [],
        }

    FakeProvider.overrides = {"patient_explanation": unsafe_explanation}
    case = upload(client, auth["patient_a"])
    assert case["status"] == "NEEDS_CORRECTION"
    db = SessionLocal()
    s = db.scalars(select(AISummary).where(AISummary.case_id == case["id"])).one()
    assert s.status == SummaryStatus.FAILED_VALIDATION
    joined = " ".join(s.validation_issues)
    assert "diagnostic language" in joined and "medication advice" in joined
    # A failed summary can never be shared.
    r = client.post(f"/api/patient/cases/{case['id']}/consent/request", headers=auth["patient_a"])
    assert r.status_code == 409


def test_contradiction_between_summary_and_report_is_caught(client, auth):
    def wrong_value(ctx):
        f = ctx["findings"]
        return {
            "headline": "Report reviewed.",
            "key_findings": [
                {"finding_id": x.id, "test_name": x.test_name, "value": "999" if x.test_name == "Ferritin" else x.value, "unit": x.unit, "reference_range": x.reference_range, "reported_flag": x.flag, "note": "flagged"}
                for x in f if x.flag
            ],
            "other_findings_count": 2,
            "items_requiring_review": [],
            "data_quality": [],
            "limitations": [],
        }

    FakeProvider.overrides = {"clinician_summary": wrong_value}
    case = upload(client, auth["patient_a"])
    assert case["status"] == "NEEDS_CORRECTION"
    db = SessionLocal()
    s = db.scalars(select(AISummary).where(AISummary.case_id == case["id"])).one()
    assert any("contradicts the report" in i for i in s.validation_issues)
    assert any("not found in the report: 999" in i for i in s.validation_issues) or any("999" in i for i in s.validation_issues)
