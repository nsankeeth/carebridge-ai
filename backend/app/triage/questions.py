"""Fixed follow-up questions asked as tap answers. Answers feed straight back into the rules."""

from dataclasses import dataclass

MAX_PER_ROUND = 3
MAX_ROUNDS = 2


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    options: list[str]


BANK: dict[str, Question] = {
    q.id: q
    for q in [
        Question("wakes_easily", "Can they be woken easily, and do they respond to you?", ["Yes", "No", "Not sure"]),
        Question("urine_last_8h", "Have they peed (or had a wet diaper) in the last 8 hours?", ["Yes", "No", "Not sure"]),
        Question("green_or_bloody_vomit", "Is there any green or bloody vomit?", ["Yes", "No"]),
        Question("constant_severe_belly_pain", "Is the belly pain severe or constant?", ["Yes", "No"]),
        Question("breathing_ok", "Are they breathing normally?", ["Yes", "No"]),
    ]
}

# (question, option) → red-flag code it confirms.
ANSWER_FLAGS: dict[tuple[str, str], str] = {
    ("wakes_easily", "No"): "hard_to_wake",
    ("urine_last_8h", "No"): "severe_dehydration",
    ("green_or_bloody_vomit", "Yes"): "green_or_bloody_vomit",
    ("constant_severe_belly_pain", "Yes"): "severe_abdominal_pain",
    ("breathing_ok", "No"): "breathing_difficulty",
}

# Flags that make each question worth asking, and the order questions are asked in.
_TRIGGERS: dict[str, set[str]] = {
    "wakes_easily": {"child_lethargy"},
    "urine_last_8h": {"child_refusing_fluids", "severe_dehydration"},
    "green_or_bloody_vomit": {"child_refusing_fluids", "child_lethargy"},
    "constant_severe_belly_pain": {"child_refusing_fluids"},
    "breathing_ok": {"child_lethargy", "infant_fever"},
}


def next_questions(flags: list[str], age_band: str, asked: set[str], round_no: int) -> list[Question]:
    if round_no > MAX_ROUNDS:
        return []
    present = set(flags)
    due = [BANK[qid] for qid, triggers in _TRIGGERS.items() if qid not in asked and triggers & present]
    return due[:MAX_PER_ROUND]
