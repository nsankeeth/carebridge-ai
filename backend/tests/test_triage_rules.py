import pytest

from app.agent.validation import UNSAFE_PATTERNS
from app.models import Urgency
from app.triage import content, questions, rules

EXAMPLE = (
    "My 4-year-old daughter started vomiting unexpectedly about four hours ago. She has thrown up three times since "
    "then and is refusing to drink any water or apple juice because she says her tummy hurts. She is very lethargic "
    "and just wants to sleep. I checked her temperature and she has a mild fever of 100.4°F."
)


def codes(result: rules.RuleResult) -> set[str]:
    return {f.code for f in result.flags}


def test_example_message_is_at_least_urgent():
    r = rules.evaluate(EXAMPLE, {}, 4)
    assert r.level == Urgency.URGENT
    assert {"child_lethargy", "child_refusing_fluids"} <= codes(r)


def test_example_with_hard_to_wake_answer_is_emergency():
    r = rules.evaluate(EXAMPLE, {"wakes_easily": "No"}, 4)
    assert r.level == Urgency.EMERGENCY
    assert "hard_to_wake" in codes(r)


@pytest.mark.parametrize(
    "text,age,expected",
    [
        ("I have crushing chest pain", 55, Urgency.EMERGENCY),
        ("my 2 month old has a fever of 38.2", 0.15, Urgency.EMERGENCY),
        ("mild sore throat for two days", 30, None),
        ("I took a whole bottle of pills", 20, Urgency.EMERGENCY),
        ("He can't breathe properly and his lips look blue", 6, Urgency.EMERGENCY),
        ("She had a seizure ten minutes ago", 3, Urgency.EMERGENCY),
        ("My face is drooping on one side and my speech is slurred", 70, Urgency.EMERGENCY),
        ("I want to kill myself", 25, Urgency.EMERGENCY),
        ("fever and a stiff neck, light hurts my eyes", 19, Urgency.EMERGENCY),
        ("He threw up green stuff twice", 2, Urgency.EMERGENCY),
        ("I have had a runny nose and a cough", 40, None),
        ("she hasn't peed since this morning and has no tears when crying", 1, Urgency.EMERGENCY),
        ("my toddler won't drink anything", 2, Urgency.URGENT),
        # Found by the live eval: rules missed these phrasings (Meta caught them).
        ("I have crushing pressure in my chest spreading to my left arm", 58, Urgency.EMERGENCY),
        ("his puffer isn't helping and he's struggling to breathe", 9, Urgency.EMERGENCY),
        ("she can't catch her breath", 30, Urgency.EMERGENCY),
    ],
)
def test_vignettes(text, age, expected):
    assert rules.evaluate(text, {}, age).level == expected


def test_negated_flags_do_not_fire():
    r = rules.evaluate("no trouble breathing and she is not hard to wake", {}, 4)
    assert "breathing_difficulty" not in codes(r)
    assert "hard_to_wake" not in codes(r)


def test_lethargy_is_not_urgent_for_adults():
    assert "child_lethargy" not in codes(rules.evaluate("very lethargic", {}, 35))


def test_age_bands():
    assert rules.age_band(0.1) == "infant_lt_3m"
    assert rules.age_band(4) == "under_5"
    assert rules.age_band(9) == "child"
    assert rules.age_band(None) == "adult"


def test_next_questions_limits():
    flags = sorted(codes(rules.evaluate(EXAMPLE, {}, 4)))
    first = questions.next_questions(flags, "under_5", set(), 1)
    assert 0 < len(first) <= 3
    assert "wakes_easily" in {q.id for q in first}
    again = questions.next_questions(flags, "under_5", {"wakes_easily"}, 2)
    assert "wakes_easily" not in {q.id for q in again}
    assert questions.next_questions(flags, "under_5", set(), 3) == []


def test_answer_flags_reference_bank_options():
    for (qid, option), flag in questions.ANSWER_FLAGS.items():
        assert option in questions.BANK[qid].options
        assert flag in rules.RULE_CODES


def test_every_level_has_guidance_and_every_flag_has_worsening_sign():
    for level in Urgency:
        assert content.GUIDANCE[level]
    assert "Call 911" in content.GUIDANCE[Urgency.EMERGENCY]
    for code in rules.RULE_CODES:
        assert content.WORSENING_SIGNS[code]
    assert content.GUIDANCE_FALLBACK and content.EMERGENCY_STEPS


def test_fixed_content_has_no_diagnosis_or_medication_advice():
    texts = list(content.GUIDANCE.values()) + list(content.WORSENING_SIGNS.values())
    texts += content.EMERGENCY_STEPS + [content.GUIDANCE_FALLBACK]
    for t in texts:
        bad = [label for label, rx in UNSAFE_PATTERNS if label != "triage decision" and rx.search(t)]
        assert not bad, (t, bad)


def test_negation_stops_at_clause_boundaries():
    # Review C2: a negator in an earlier sentence or clause must not cancel a later red flag.
    assert rules.evaluate("No fever. Can't breathe.", {}, 30).level == Urgency.EMERGENCY
    assert "chest_pain" in codes(rules.evaluate("He has no appetite and chest pain", {}, 60))
    assert "breathing_difficulty" in codes(rules.evaluate("not eating, struggling to breathe", {}, 8))
