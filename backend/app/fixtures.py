"""Synthetic laboratory reports. Every name, identifier and value here is fabricated."""

import io
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

LAB = "Northbridge Medical Laboratories"


@dataclass
class Report:
    slug: str
    title: str
    patient: str
    health_ref: str
    collected: str
    rows: list[tuple[str, str, str, str, str]]  # test, value, unit, range, flag
    footnote: str | None = None


REPORTS: list[Report] = [
    Report("cbc-iron-maya", "Complete blood count and iron studies", "Maya Thompson", "SYN-ON-4471-0092", "2026-10-28", [
        ("Hemoglobin", "112", "g/L", "120-160", "L"),
        ("Hematocrit", "0.35", "L/L", "0.36-0.46", "L"),
        ("MCV", "76", "fL", "80-100", "L"),
        ("White Blood Cells", "6.4", "x10^9/L", "4.0-11.0", ""),
        ("Platelets", "288", "x10^9/L", "150-400", ""),
        ("Ferritin", "9", "ug/L", "15-150", "L"),
    ]),
    Report("lipids-maya", "Lipid panel", "Maya Thompson", "SYN-ON-4471-0092", "2026-09-14", [
        ("Total Cholesterol", "5.1", "mmol/L", "<5.2", ""),
        ("LDL Cholesterol", "3.2", "mmol/L", "<3.5", ""),
        ("HDL Cholesterol", "1.6", "mmol/L", ">1.2", ""),
        ("Triglycerides", "1.1", "mmol/L", "<1.7", ""),
    ]),
    Report("metabolic-daniel", "Diabetes screening and kidney function", "Daniel Okafor", "SYN-ON-8820-1157", "2026-10-21", [
        ("Glucose Fasting", "7.4", "mmol/L", "3.6-6.0", "H"),
        ("Hemoglobin A1c", "7.1", "%", "4.0-5.9", "H"),
        ("Creatinine", "88", "umol/L", "60-110", ""),
        ("eGFR", "84", "mL/min/1.73m2", ">60", ""),
        ("Potassium", "4.3", "mmol/L", "3.5-5.0", ""),
    ]),
    Report("thyroid-daniel", "Thyroid function", "Daniel Okafor", "SYN-ON-8820-1157", "2026-08-02", [
        ("TSH", "2.1", "mIU/L", "0.32-4.00", ""),
    ]),
    Report("liver-daniel", "Liver enzymes", "Daniel Okafor", "SYN-ON-8820-1157", "2026-07-19", [
        ("ALT", "62", "U/L", "<40", "H"),
        ("AST", "38", "U/L", "<40", ""),
        ("Alkaline Phosphatase", "96", "U/L", "40-129", ""),
        ("Total Bilirubin", "14", "umol/L", "<21", ""),
    ]),
    # The file a presenter uploads live in the demo.
    Report("demo-upload-lipids-thyroid", "Lipid panel and thyroid follow-up", "Maya Thompson", "SYN-ON-4471-0092", "2026-10-30", [
        ("Total Cholesterol", "6.4", "mmol/L", "<5.2", "H"),
        ("LDL Cholesterol", "4.3", "mmol/L", "<3.5", "H"),
        ("HDL Cholesterol", "1.3", "mmol/L", ">1.2", ""),
        ("Triglycerides", "1.9", "mmol/L", "<1.7", "H"),
        ("TSH", "3.6", "mIU/L", "0.32-4.00", ""),
        ("Vitamin B12", "245", "pmol/L", "148-616", ""),
    ], footnote="Specimen received fasting 12 hours."),
]


def build_pdf(r: Report) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.setTitle(f"{LAB} - {r.title}")
    y = 740
    c.setFont("Helvetica-Bold", 15)
    c.drawString(60, y, LAB)
    c.setFont("Helvetica", 9)
    c.drawString(60, y - 14, "SYNTHETIC REPORT FOR DEMONSTRATION - NOT REAL PATIENT DATA")
    c.setFont("Helvetica", 10)
    for i, line in enumerate([f"Patient: {r.patient}", f"Health Ref: {r.health_ref}", f"Collected: {r.collected}", f"Report: {r.title}"]):
        c.drawString(60, y - 40 - i * 14, line)
    y -= 120
    cols = [60, 250, 320, 420, 520]
    c.setFont("Helvetica-Bold", 10)
    for x, h in zip(cols, ["Test", "Result", "Units", "Reference Range", "Flag"]):
        c.drawString(x, y, h)
    c.line(60, y - 4, 550, y - 4)
    c.setFont("Helvetica", 10)
    for row in r.rows:
        y -= 18
        for x, v in zip(cols, row):
            if v:
                c.drawString(x, y, v)
    y -= 40
    if r.footnote:
        c.drawString(60, y, r.footnote)
        y -= 14
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(60, y, "Flags: H = above reference range, L = below reference range. Interpretation requires a clinician.")
    c.showPage()
    c.save()
    return buf.getvalue()


def write_all(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for r in REPORTS:
        p = out_dir / f"{r.slug}.pdf"
        p.write_bytes(build_pdf(r))
        paths.append(p)
    return paths


if __name__ == "__main__":
    for p in write_all(Path(__file__).resolve().parents[2] / "fixtures" / "reports"):
        print(p)
