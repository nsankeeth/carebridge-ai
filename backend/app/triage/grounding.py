"""Grounding and safety checks for model output about a symptom thread."""

import re

from app.agent.documents import norm
from app.agent.validation import _NUM_RE, number_issues, safety_issues
from app.ai.schemas import TriageFlag
from app.models import Message, MessageAuthor
from app.triage.questions import BANK


def patient_corpus(messages: list[Message]) -> str:
    """Everything the patient said, including tap answers as 'question answer' text. AI and clinician text excluded."""
    parts = []
    for m in messages:
        if m.author_type != MessageAuthor.PATIENT:
            continue
        p = m.payload or {}
        if p.get("kind") == "answer" and p.get("question_id") in BANK:
            parts.append(f"{BANK[p['question_id']].text} {p.get('answer', '')}")
        else:
            parts.append(m.body)
    return norm(" \n ".join(parts))


def split_grounded(flags: list[TriageFlag], corpus: str) -> tuple[list[TriageFlag], list[TriageFlag]]:
    kept, dropped = [], []
    for f in flags:
        (kept if norm(f.patient_quote) and norm(f.patient_quote) in corpus else dropped).append(f)
    return kept, dropped


def quote_grounded(quote: str, corpus: str) -> bool:
    return bool(norm(quote)) and norm(quote) in corpus


# Model text shown to a patient about symptoms may not suggest a cause or tell them where to seek care:
# causes belong to the clinician brief and care-level wording comes only from fixed templates.
TRIAGE_PATIENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("suggested cause", re.compile(r"\b(?:sounds|looks|seems) like\b|\b(?:probably|likely|could be|might be|may be|possibly)\b(?: just)?(?: an?\b)?", re.I)),
    ("named condition", re.compile(r"\b(?:virus|viral|flu|influenza|infection|bug|gastro\w*|croup|appendicitis|covid|strep|pneumonia|meningitis|sepsis|migraine|allerg\w+|asthma attack|food poisoning)\b", re.I)),
    ("care instruction", re.compile(r"\b(?:urgent care|walk-?in|emergency|\bER\b|hospital|see (?:a|your) (?:doctor|clinician|gp)|at home|stay home|monitor (?:him|her|them|it)|wait (?:and see|until)|no need)\b", re.I)),
]


def patient_text_issues(text: str, corpus: str) -> list[str]:
    allowed = {str(i) for i in range(0, 11)} | set(_NUM_RE.findall(corpus))
    issues = safety_issues(text, "acknowledgement") + number_issues(text, allowed, "acknowledgement")
    issues += [f"acknowledgement: contains {label} (\"{m.group(0)}\")" for label, rx in TRIAGE_PATIENT_PATTERNS if (m := rx.search(text))]
    return issues
