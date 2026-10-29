"""A. Document processing and the deterministic half of finding extraction."""

import io
import re
from dataclasses import dataclass

import pdfplumber


@dataclass
class PageText:
    page: int  # 1-based
    text: str


class DocumentError(Exception):
    pass


def extract_pages(pdf_bytes: bytes) -> list[PageText]:
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [PageText(i + 1, p.extract_text() or "") for i, p in enumerate(pdf.pages)]
    except Exception as e:  # pdfplumber raises a variety of parser errors
        raise DocumentError(f"Could not read PDF: {type(e).__name__}") from e
    if not any(p.text.strip() for p in pages):
        raise DocumentError("No machine-readable text found (scanned PDFs are not supported yet)")
    return pages


def pages_to_prompt_text(pages: list[PageText]) -> str:
    return "\n\n".join(f"=== PAGE {p.page} ===\n{p.text}" for p in pages)


_NUM = r"\d+(?:\.\d+)?"
ROW = re.compile(
    rf"^(?P<name>[A-Za-z][A-Za-z0-9 ,()/%'\-\.]*?[A-Za-z0-9)])\s+"
    rf"(?P<value>[<>]?\s?{_NUM})\s+"
    rf"(?P<unit>[^\s\d][^\s]*|%)\s+"
    rf"(?P<range>[<>≤≥]\s?{_NUM}|{_NUM}\s?-\s?{_NUM})"
    rf"(?:\s+(?P<flag>HH|LL|H|L|A))?\s*$"
)


@dataclass
class ParsedRow:
    test_name: str
    value: str
    unit: str
    reference_range: str
    flag: str | None
    page: int
    line: str


def parse_rows(pages: list[PageText]) -> list[ParsedRow]:
    """Tabular lab rows: <test> <value> <unit> <range> [flag]. Lines that don't match are left to the model."""
    rows: list[ParsedRow] = []
    for p in pages:
        for line in p.text.splitlines():
            m = ROW.match(line.strip())
            if m:
                rows.append(
                    ParsedRow(
                        test_name=m["name"].strip(),
                        value=m["value"].replace(" ", ""),
                        unit=m["unit"],
                        reference_range=m["range"].strip(),
                        flag=m["flag"],
                        page=p.page,
                        line=line.strip(),
                    )
                )
    return rows


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())
