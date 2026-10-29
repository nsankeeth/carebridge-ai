"""Report-processing workflow: a bounded, persisted sequence of steps (A–E).

Meta model calls: report understanding, patient explanation, clinician summary.
Deterministic code: PDF text, row parsing, grounding checks, safety validation, state transitions.
"""

import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, storage, workflow
from app.agent.documents import DocumentError, extract_pages, pages_to_prompt_text, parse_rows
from app.agent.validation import FindingDraft, outside_range, reconcile_findings, validate_outputs
from app.ai import prompts
from app.ai.provider import CallMeta, LLMProvider, ModelCallError, get_provider
from app.ai.schemas import ClinicianSummary, ExtractionResult, PatientExplanation
from app.db import SessionLocal
from app.models import (
    AgentExecution,
    AISummary,
    CaseStatus,
    ExecutionStatus,
    ExtractedFinding,
    FindingStatus,
    MedicalCase,
    ModelCall,
    SummaryStatus,
    User,
)

log = logging.getLogger("agent.pipeline")
T = TypeVar("T", bound=BaseModel)
MAX_GENERATION_ATTEMPTS = 2


class StepFailed(Exception):
    def __init__(self, message: str, target: CaseStatus = CaseStatus.PROCESSING_FAILED):
        super().__init__(message)
        self.target = target


def record_model_call(db: Session, meta: CallMeta, execution_id: uuid.UUID | None, case_id: uuid.UUID | None) -> ModelCall:
    row = ModelCall(
        execution_id=execution_id,
        case_id=case_id,
        task=meta.task,
        provider=meta.provider,
        model_id=meta.model_id,
        status=meta.status,
        latency_ms=meta.latency_ms,
        input_tokens=meta.input_tokens,
        output_tokens=meta.output_tokens,
        total_tokens=meta.total_tokens,
        response_id=meta.response_id,
        error=meta.error,
    )
    db.add(row)
    return row


def start_processing(db: Session, case: MedicalCase, actor: User | None) -> AgentExecution:
    if not case.documents:
        raise StepFailed("Upload a report before starting processing")
    workflow.transition(db, case, CaseStatus.PROCESSING, actor=actor, reason="processing requested")
    ex = AgentExecution(case_id=case.id, kind="PROCESSING", status=ExecutionStatus.RUNNING, steps=[])
    db.add(ex)
    db.flush()
    audit.record(db, "agent.processing_started", "AgentExecution", ex.id, actor=actor, org_id=case.org_id, details={"case_id": str(case.id)})
    db.commit()
    return ex


class _Run:
    def __init__(self, db: Session, ex: AgentExecution, case: MedicalCase, provider: LLMProvider):
        self.db, self.ex, self.case, self.provider = db, ex, case, provider

    def step(self, name: str, fn: Callable[[], Any], detail: Callable[[Any], dict] | None = None) -> Any:
        started = time.perf_counter()
        self.ex.current_step = name
        self.db.commit()
        entry: dict[str, Any] = {"name": name, "started_at": datetime.now(timezone.utc).isoformat()}
        try:
            result = fn()
        except Exception as e:
            entry.update(status="failed", error=str(e)[:300], duration_ms=round((time.perf_counter() - started) * 1000))
            self.ex.steps = [*self.ex.steps, entry]
            self.db.commit()
            raise
        entry.update(status="succeeded", duration_ms=round((time.perf_counter() - started) * 1000))
        if detail:
            entry["detail"] = detail(result)
        self.ex.steps = [*self.ex.steps, entry]
        self.db.commit()
        return result

    def model(self, task: str, system: str, user: str, schema: type[T], context: dict[str, Any]) -> T:
        """One structured Meta call, re-asked once with the validation error if the output is invalid."""
        last_error = ""
        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            prompt = user if attempt == 1 else f"{user}\n\nYour previous answer was rejected: {last_error}\nReturn corrected JSON."
            try:
                out, meta = self.provider.structured(task=task, system=system, user=prompt, schema=schema, context=context)
                record_model_call(self.db, meta, self.ex.id, self.case.id)
                self.db.commit()
                return out
            except ModelCallError as e:
                record_model_call(self.db, e.meta, self.ex.id, self.case.id)
                self.db.commit()
                last_error = e.meta.error or str(e)
                if e.meta.status != "invalid_output":
                    raise StepFailed(f"Meta model call failed during {task}: {last_error}")
        raise StepFailed(f"Meta model returned invalid output for {task} after {MAX_GENERATION_ATTEMPTS} attempts")


def _findings_payload(findings: list[FindingDraft]) -> list[dict[str, Any]]:
    return [
        {
            "id": f.id,
            "test_name": f.test_name,
            "value": f.value,
            "unit": f.unit,
            "reference_range": f.reference_range,
            "lab_flag": f.flag,
            "outside_reference_range": outside_range(f.value, f.reference_range),
            "extraction_status": f.status,
        }
        for f in findings
    ]


def run_processing(execution_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        _run_processing(db, execution_id)
    finally:
        db.close()


def _run_processing(db: Session, execution_id: uuid.UUID) -> None:
    ex = db.get(AgentExecution, execution_id)
    if not ex or ex.status != ExecutionStatus.RUNNING:
        return
    case = db.get(MedicalCase, ex.case_id)
    assert case is not None
    try:
        provider = get_provider()
    except RuntimeError as e:
        _fail(db, ex, case, StepFailed(str(e)))
        return
    run = _Run(db, ex, case, provider)
    doc = case.documents[-1]

    try:
        pages = run.step(
            "document_processing",
            lambda: extract_pages(storage.load(doc.storage_key)),
            lambda p: {"pages": len(p)},
        )
        doc.extracted_text = pages_to_prompt_text(pages)
        doc.page_count = len(pages)
        rows = run.step("deterministic_parse", lambda: parse_rows(pages), lambda r: {"rows": len(r)})

        extraction: ExtractionResult = run.step(
            "meta_report_understanding",
            lambda: run.model(
                "report_understanding",
                prompts.EXTRACTION_SYSTEM,
                f"Extract all laboratory results from this report.\n\n{doc.extracted_text}",
                ExtractionResult,
                {"rows": rows, "pages": pages},
            ),
            lambda r: {"findings": len(r.findings), "ambiguities": len(r.ambiguities)},
        )
        findings, data_issues, lab_name, report_date = run.step(
            "finding_validation",
            lambda: reconcile_findings(extraction, rows, pages),
            lambda r: {"findings": len(r[0]), "needs_review": sum(f.status == "NEEDS_REVIEW" for f in r[0])},
        )
        if not findings:
            raise StepFailed("No laboratory results could be extracted from the report", CaseStatus.NEEDS_CORRECTION)
        _persist_findings(db, case, doc.id, findings, lab_name, report_date)

        payload = json.dumps(
            {"lab_name": lab_name, "report_date": report_date, "data_quality_notes": data_issues, "findings": _findings_payload(findings)},
            indent=1,
        )
        context = {"findings": findings, "report_date": report_date, "data_issues": data_issues}
        explanation, summary, issues = None, None, []
        feedback = ""
        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            extra = f"\n\nA previous draft failed validation. Fix these problems:\n- " + "\n- ".join(issues) if issues else ""
            explanation = run.step(
                "meta_patient_explanation",
                lambda: run.model("patient_explanation", prompts.EXPLANATION_SYSTEM, f"Report data:\n{payload}{extra}", PatientExplanation, context),
                lambda r: {"attempt": attempt, "explained": len(r.findings), "for_review": len(r.items_for_clinician_review)},
            )
            summary = run.step(
                "meta_clinician_summary",
                lambda: run.model("clinician_summary", prompts.CLINICIAN_SYSTEM, f"Report data:\n{payload}{extra}", ClinicianSummary, context),
                lambda r: {"attempt": attempt, "key_findings": len(r.key_findings)},
            )
            issues = run.step(
                "output_validation",
                lambda: validate_outputs(findings, explanation, summary, report_date),
                lambda r: {"attempt": attempt, "issues": len(r)},
            )
            if not issues:
                break
            feedback = "; ".join(issues)
        assert explanation and summary

        summary_dump = summary.model_dump()
        summary_dump["data_quality"] = list(dict.fromkeys([*summary_dump["data_quality"], *data_issues]))
        version = (db.scalar(select(func.max(AISummary.version)).where(AISummary.case_id == case.id)) or 0) + 1
        ai_summary = AISummary(
            case_id=case.id,
            version=version,
            status=SummaryStatus.ACTIVE if not issues else SummaryStatus.FAILED_VALIDATION,
            patient_explanation=explanation.model_dump(),
            clinician_summary=summary_dump,
            validation_issues=issues,
            provider=provider.name,
            model_id=provider.model_id,
        )
        db.add(ai_summary)
        db.flush()
        audit.record(
            db, "ai.summary_generated", "AISummary", ai_summary.id, actor_type="AGENT", org_id=case.org_id,
            details={"case_id": str(case.id), "model_id": provider.model_id, "validation_issues": len(issues)},
        )
        if issues:
            raise StepFailed(f"Generated summary failed validation: {feedback}", CaseStatus.NEEDS_CORRECTION)
        workflow.transition(db, case, CaseStatus.SUMMARY_READY, actor_type="AGENT", reason="processing succeeded")
        ex.status = ExecutionStatus.SUCCEEDED
        ex.current_step = None
        ex.finished_at = datetime.now(timezone.utc)
        db.commit()
    except StepFailed as e:
        _fail(db, ex, case, e)
    except DocumentError as e:
        _fail(db, ex, case, StepFailed(str(e)))
    except Exception as e:  # noqa: BLE001 - never leave a case stuck in PROCESSING
        log.exception("processing crashed")
        db.rollback()
        _fail(db, db.get(AgentExecution, execution_id), db.get(MedicalCase, case.id), StepFailed(f"Unexpected error: {type(e).__name__}"))


def _persist_findings(db: Session, case: MedicalCase, document_id: uuid.UUID, findings: list[FindingDraft], lab_name: str | None, report_date: str | None) -> None:
    for old in list(case.findings):
        db.delete(old)
    db.flush()
    for i, f in enumerate(findings):
        db.add(
            ExtractedFinding(
                id=uuid.UUID(f.id),
                case_id=case.id,
                document_id=document_id,
                position=i,
                test_name=f.test_name[:200],
                value=f.value[:100],
                unit=f.unit,
                reference_range=f.reference_range,
                flag=f.flag,
                report_date=report_date,
                lab_name=lab_name,
                source_page=f.source_page,
                source_text=f.source_text,
                status=FindingStatus(f.status),
                validation_notes=f.notes,
                extraction_method=f.method,
            )
        )
    audit.record(db, "ai.findings_extracted", "MedicalCase", case.id, actor_type="AGENT", org_id=case.org_id, details={"count": len(findings)})
    db.commit()


def _fail(db: Session, ex: AgentExecution | None, case: MedicalCase | None, err: StepFailed) -> None:
    if ex is None or case is None:
        return
    ex.status = ExecutionStatus.FAILED
    ex.error = str(err)[:1000]
    ex.finished_at = datetime.now(timezone.utc)
    if case.status == CaseStatus.PROCESSING:
        workflow.transition(db, case, err.target, actor_type="AGENT", reason=str(err)[:200])
    audit.record(db, "agent.processing_failed", "AgentExecution", ex.id, actor_type="AGENT", org_id=case.org_id, details={"case_id": str(case.id), "target": err.target.value})
    db.commit()
