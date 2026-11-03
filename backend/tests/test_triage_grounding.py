from app.ai.schemas import ClinicianTriageBrief, TriageFlag, TriageModelOutput, json_schema_for
from app.models import Message, MessageAuthor
from app.triage import grounding


def corpus_of(*texts: str) -> str:
    return grounding.patient_corpus([Message(author_type=MessageAuthor.PATIENT, body=t) for t in texts])


def test_invented_quote_is_dropped():
    corpus = corpus_of("She is very lethargic and just wants to sleep.")
    kept, dropped = grounding.split_grounded(
        [TriageFlag(flag="child_lethargy", patient_quote="very lethargic"), TriageFlag(flag="seizure", patient_quote="she had a seizure")], corpus
    )
    assert [f.flag for f in kept] == ["child_lethargy"]
    assert [f.flag for f in dropped] == ["seizure"]


def test_quote_matching_ignores_case_and_spacing():
    corpus = corpus_of("She is   VERY lethargic")
    kept, dropped = grounding.split_grounded([TriageFlag(flag="x", patient_quote="very  Lethargic")], corpus)
    assert kept and not dropped


def test_corpus_includes_answers_but_not_ai_or_clinician_text():
    msgs = [
        Message(author_type=MessageAuthor.PATIENT, body="tummy hurts"),
        Message(author_type=MessageAuthor.PATIENT, body="No", payload={"kind": "answer", "question_id": "wakes_easily", "answer": "No"}),
        Message(author_type=MessageAuthor.AI, body="this came from the AI"),
        Message(author_type=MessageAuthor.CLINICIAN, body="clinician words"),
    ]
    corpus = grounding.patient_corpus(msgs)
    assert "tummy hurts" in corpus and "can they be woken easily" in corpus
    assert "from the ai" not in corpus and "clinician words" not in corpus


def test_acknowledgement_with_diagnosis_is_flagged():
    assert grounding.patient_text_issues("It sounds like you likely have an infection.", corpus_of("tummy hurts"))


def test_acknowledgement_numbers_must_come_from_patient():
    corpus = corpus_of("she has a mild fever of 100.4°F")
    assert grounding.patient_text_issues("Thanks for telling us about the fever of 100.4.", corpus) == []
    assert grounding.patient_text_issues("Give her 15 ml now.", corpus)


def test_schemas_are_strict():
    for schema in (TriageModelOutput, ClinicianTriageBrief):
        js = json_schema_for(schema)
        assert js["additionalProperties"] is False
        assert set(js["required"]) == set(js["properties"])


import pytest  # noqa: E402


@pytest.mark.parametrize(
    "text",
    [
        "This sounds like croup.",
        "It's probably just a virus.",
        "It could be a stomach bug.",
        "You can manage this at home.",
        "See a doctor tomorrow if it continues.",
        "Go to urgent care.",
        "Take her to a walk-in clinic.",
        "Just monitor her at home for now.",
        "It may be appendicitis.",
    ],
)
def test_patient_text_blocks_causes_and_care_instructions(text):
    # Review I2: causes and care-level instructions must never come from model text.
    assert grounding.patient_text_issues(text, corpus_of("tummy hurts")), text


def test_patient_text_allows_a_plain_acknowledgement():
    ack = "It is understandable to feel worried when she is this sleepy and not drinking. Your care team is being contacted now."
    assert grounding.patient_text_issues(ack, corpus_of("she is sleepy and not drinking")) == []
