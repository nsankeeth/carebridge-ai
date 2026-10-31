"""E. Validation. Deterministic checks that every model output is grounded in the source report and safe."""

import re
import uuid
from dataclasses import dataclass, field

from app.agent.documents import PageText, ParsedRow, norm, norm_name
from app.ai.schemas import ClinicianSummary, ExtractionResult, PatientExplanation


@dataclass
class FindingDraft:
    test_name: str
    value: str
    unit: str | None
    reference_range: str | None
    flag: str | None
    source_page: int | None
    source_text: str | None
    method: str
    status: str = "VERIFIED"
    notes: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def needs_review(self, note: str) -> None:
        self.status = "NEEDS_REVIEW"
        self.notes.append(note)


_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _to_float(s: str | None) -> float | None:
    m = _NUM_RE.search(s or "")
    return float(m.group()) if m else None


def outside_range(value: str, reference_range: str | None) -> bool | None:
    """True/False when the printed value and interval are comparable, None when they are not."""
    if not reference_range:
        return None
    v = _to_float(value)
    if v is None or value.strip()[:1] in "<>":
        return None
    r = reference_range.replace(" ", "")
    if m := re.fullmatch(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", r):
        return not (float(m[1]) <= v <= float(m[2]))
    if m := re.fullmatch(r"[<≤](\d+(?:\.\d+)?)", r):
        return v >= float(m[1]) if r[0] == "<" else v > float(m[1])
    if m := re.fullmatch(r"[>≥](\d+(?:\.\d+)?)", r):
        return v <= float(m[1]) if r[0] == ">" else v < float(m[1])
    return None


def needs_clinician_attention(f: FindingDraft) -> bool:
    return bool(f.flag) or outside_range(f.value, f.reference_range) is True or f.status == "NEEDS_REVIEW"


def reconcile_findings(
    ai: ExtractionResult, rows: list[ParsedRow], pages: list[PageText]
) -> tuple[list[FindingDraft], list[str], str | None, str | None]:
    """Cross-check model extraction against the source text and the deterministic parser."""
    page_text = {p.page: norm(p.text) for p in pages}
    all_text = " ".join(page_text.values())
    rows_by_name = {norm_name(r.test_name): r for r in rows}
    issues: list[str] = list(ai.ambiguities)
    drafts: list[FindingDraft] = []
    seen: set[str] = set()

    for item in ai.findings:
        d = FindingDraft(
            test_name=item.test_name.strip(),
            value=item.value.strip(),
            unit=item.unit,
            reference_range=item.reference_range,
            flag=item.flag,
            source_page=item.source_page,
            source_text=item.source_quote,
            method="meta+deterministic",
        )
        quote = norm(item.source_quote)
        page = page_text.get(item.source_page)
        if page is None:
            d.needs_review(f"Cited page {item.source_page} does not exist")
        elif not quote or quote not in page:
            d.needs_review("Cited source text was not found on the cited page")
        for label, val in (("value", d.value), ("unit", d.unit), ("reference range", d.reference_range), ("flag", d.flag)):
            if val and norm(val) not in quote:
                d.needs_review(f"Extracted {label} '{val}' does not appear in the source line")
        key = norm_name(d.test_name)
        row = rows_by_name.get(key)
        if row:
            for label, ai_val, det_val in (
                ("value", d.value, row.value),
                ("unit", d.unit, row.unit),
                ("reference range", d.reference_range, row.reference_range),
                ("flag", d.flag, row.flag),
            ):
                if norm(ai_val).replace(" ", "") != norm(det_val).replace(" ", ""):
                    d.needs_review(f"Model {label} '{ai_val}' differs from parsed {label} '{det_val}'")
        else:
            d.method = "meta"
        if key in seen:
            d.needs_review("Duplicate test name in report")
        seen.add(key)
        drafts.append(d)

    # Rows the parser found but the model missed: the source line itself is the evidence.
    for key, row in rows_by_name.items():
        if key not in seen:
            drafts.append(
                FindingDraft(
                    test_name=row.test_name,
                    value=row.value,
                    unit=row.unit,
                    reference_range=row.reference_range,
                    flag=row.flag,
                    source_page=row.page,
                    source_text=row.line,
                    method="deterministic",
                    notes=["Parsed from source text; not returned by model extraction"],
                )
            )

    lab_name = ai.lab_name if ai.lab_name and norm(ai.lab_name) in all_text else None
    report_date = ai.report_date if ai.report_date and norm(ai.report_date) in all_text else None
    if ai.lab_name and not lab_name:
        issues.append("Laboratory name returned by the model was not found in the report")
    if ai.report_date and not report_date:
        issues.append("Report date returned by the model was not found in the report")
    if not report_date:
        issues.append("Report date could not be confirmed")
    return drafts, issues, lab_name, report_date


# --- Output validation -------------------------------------------------------------

UNSAFE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("diagnostic claim", re.compile(r"\byou (?:likely |probably |may |might )?(?:have|are suffering from) (?:an? )?(?:\w+ ){0,2}(?:disease|condition|disorder|diabetes|anemia|anaemia|infection|failure|deficiency|cancer)\b", re.I)),
    ("diagnostic language", re.compile(r"\b(?:consistent with|suggestive of|indicative of|diagnostic of|confirms? (?:a|an|that you))\b", re.I)),
    ("diagnosis", re.compile(r"\b(?<!not a )(?<!no )diagnosed with\b", re.I)),
    ("medication advice", re.compile(r"\b(?:start|stop|begin|increase|decrease|reduce|double|adjust) (?:taking |your )?(?:\w+ )?(?:medication|medicine|dose|dosage|pills?|insulin|statins?|supplements?)\b", re.I)),
    ("dosage", re.compile(r"\b\d+(?:\.\d+)?\s?(?:mg|mcg|µg|iu|units?) (?:daily|per day|twice|once)\b", re.I)),
    ("health reassurance", re.compile(r"\b(?:you are|you're) (?:healthy|unhealthy|fine|perfectly normal)\b|\bnothing to worry about\b|\bno need to (?:see|consult|worry)\b", re.I)),
    ("triage decision", re.compile(r"\b(?:go to|visit) (?:the )?(?:emergency|er\b|hospital)|\bcall 911\b|\bthis is (?:an )?emergency\b", re.I)),
]


def safety_issues(text: str, where: str) -> list[str]:
    return [f"{where}: contains {label} (\"{m.group(0)}\")" for label, rx in UNSAFE_PATTERNS if (m := rx.search(text))]


def _allowed_numbers(findings: list[FindingDraft], report_date: str | None) -> set[str]:
    allowed = {str(i) for i in range(0, 11)}
    for f in findings:
        for s in (f.value, f.reference_range, f.unit, f.test_name):
            allowed.update(_NUM_RE.findall(s or ""))
    allowed.update(_NUM_RE.findall(report_date or ""))
    return allowed


def number_issues(text: str, allowed: set[str], where: str) -> list[str]:
    bad = sorted({n for n in _NUM_RE.findall(text) if n not in allowed})
    return [f"{where}: mentions number(s) not found in the report: {', '.join(bad)}"] if bad else []


def validate_outputs(
    findings: list[FindingDraft],
    explanation: PatientExplanation,
    summary: ClinicianSummary,
    report_date: str | None,
) -> list[str]:
    by_id = {f.id: f for f in findings}
    attention = {f.id for f in findings if needs_clinician_attention(f)}
    allowed = _allowed_numbers(findings, report_date)
    issues: list[str] = []

    # Patient explanation
    explained = {e.finding_id for e in explanation.findings}
    for e in explanation.findings:
        if e.finding_id not in by_id:
            issues.append(f"Explanation references unknown finding id {e.finding_id}")
    if missing := [by_id[i].test_name for i in by_id.keys() - explained]:
        issues.append(f"Explanation omits findings: {', '.join(sorted(missing))}")
    review_ids = {r.finding_id for r in explanation.items_for_clinician_review}
    if unknown := review_ids - by_id.keys():
        issues.append(f"Review list references unknown finding ids: {', '.join(sorted(unknown))}")
    if missed := [by_id[i].test_name for i in attention - review_ids]:
        issues.append(f"Explanation does not flag for clinician review: {', '.join(sorted(missed))}")
    patient_texts = [("overview", explanation.overview)]
    patient_texts += [(f"explanation of {by_id[e.finding_id].test_name}", e.plain_language) for e in explanation.findings if e.finding_id in by_id]
    patient_texts += [("review reason", r.reason) for r in explanation.items_for_clinician_review]
    patient_texts += [("question", q) for q in explanation.questions_to_ask]
    for where, text in patient_texts:
        issues += safety_issues(text, where) + number_issues(text, allowed, where)

    # Clinician summary
    key_ids = set()
    for k in summary.key_findings:
        f = by_id.get(k.finding_id)
        if not f:
            issues.append(f"Clinician summary references unknown finding id {k.finding_id}")
            continue
        key_ids.add(k.finding_id)
        for label, got, want in (
            ("value", k.value, f.value),
            ("unit", k.unit, f.unit),
            ("reference range", k.reference_range, f.reference_range),
            ("flag", k.reported_flag, f.flag),
        ):
            if norm(got) != norm(want):
                issues.append(f"Clinician summary {label} for {f.test_name} ('{got}') contradicts the report ('{want}')")
        issues += safety_issues(k.note, f"note on {f.test_name}") + number_issues(k.note, allowed, f"note on {f.test_name}")
    flagged_or_out = {f.id for f in findings if f.flag or outside_range(f.value, f.reference_range)}
    if omitted := [by_id[i].test_name for i in flagged_or_out - key_ids]:
        issues.append(f"Clinician summary omits flagged/out-of-range results: {', '.join(sorted(omitted))}")
    for where, text in [("headline", summary.headline)] + [("review item", t) for t in summary.items_requiring_review]:
        issues += safety_issues(text, where) + number_issues(text, allowed, where)

    # Cross-output consistency: anything the clinician summary calls out must also be surfaced to the patient.
    if inconsistent := [by_id[i].test_name for i in key_ids - review_ids]:
        issues.append(f"Patient explanation and clinician summary disagree on: {', '.join(sorted(inconsistent))}")
    return issues


MEDICAL_DETAIL = re.compile(
    r"\b(?:mmol|umol|g/l|mg|hba1c|a1c|hemoglobin|haemoglobin|hematocrit|glucose|cholesterol|ldl|hdl|triglycerides?|creatinine|"
    r"tsh|ferritin|potassium|sodium|platelets?|egfr|alt|ast|bilirubin|b12|mcv)\b"
    # Any number except a duration ("24 hours", "3 business days"); lab values are numbers.
    r"|(?<![\d.])\d+(?:\.\d+)?(?![\d.])(?!\s?(?:hours?|hrs?|h\b|days?|business days?|weeks?|minutes?|mins?)\b)",
    re.I,
)


def admin_message_issues(text: str) -> list[str]:
    """Notifications travel outside the clinical record, so they must carry no medical details."""
    issues = safety_issues(text, "message")
    if m := MEDICAL_DETAIL.search(text):
        issues.append(f"message contains medical detail or numbers (\"{m.group(0)}\")")
    return issues
