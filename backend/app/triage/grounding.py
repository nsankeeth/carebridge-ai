"""Grounding and safety checks for model output about a symptom thread."""

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


def patient_text_issues(text: str, corpus: str) -> list[str]:
    allowed = {str(i) for i in range(0, 11)} | set(_NUM_RE.findall(corpus))
    return safety_issues(text, "acknowledgement") + number_issues(text, allowed, "acknowledgement")
