"""Deterministic stand-ins for model output, used only by the test double in conftest.py."""

import json
import re
import uuid
from typing import Any

from app.ai.provider import AssistantTurn, ToolCall


def _lab_and_date(pages: list[Any]) -> tuple[str | None, str | None]:
    text = "\n".join(p.text for p in pages)
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), None)
    m = re.search(r"(?:Collected|Report date|Date)[:\s]+([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
    return first, m.group(1) if m else None


def structured(task: str, ctx: dict[str, Any]) -> dict[str, Any]:
    from app.agent.validation import needs_clinician_attention, outside_range

    if task == "report_understanding":
        lab, date = _lab_and_date(ctx.get("pages", []))
        return {
            "lab_name": lab,
            "report_date": date,
            "findings": [
                {"test_name": r.test_name, "value": r.value, "unit": r.unit, "reference_range": r.reference_range, "flag": r.flag, "source_page": r.page, "source_quote": r.line}
                for r in ctx.get("rows", [])
            ],
            "ambiguities": [],
        }
    if task == "triage_assessment":
        quote = " ".join(ctx["corpus"].split()[:5])
        return {
            "level": ctx.get("rule_level") or "SOON",
            "red_flags": [{"flag": "reported_symptoms", "patient_quote": quote}] if quote else [],
            "reasons": ["Test double reasoning."],
            "follow_up_questions": [{"id": "pain_location", "question": "Where does it hurt most?", "options": ["Middle", "Lower right", "All over"]}],
            "care_tip_ids": ["rest", "stay_with_them"],
            "acknowledgement": "Thank you for telling us what is happening. Your care team is being contacted.",
        }
    if task == "clinician_triage_brief":
        quote = " ".join(ctx["corpus"].split()[:5])
        return {
            "headline": "Test double brief",
            "timeline": ["Symptoms as reported."],
            "red_flags": [{"flag": "reported_symptoms", "patient_quote": quote}],
            "possible_causes": [{"cause": "Cause A", "supporting_quotes": [quote], "against_quotes": [], "likelihood": "higher"}],
            "suggested_questions": ["When did it start?"],
            "suggested_next_steps": ["Call the patient."],
            "draft_treatment_idea": "Draft for clinician review.",
        }
    findings = ctx["findings"]
    attention = [f for f in findings if needs_clinician_attention(f)]
    if task == "patient_explanation":
        def describe(f: Any) -> str:
            pos = outside_range(f.value, f.reference_range)
            where = "outside" if pos else "within" if pos is False else "compared against"
            return f"Your report lists {f.test_name} as {f.value} {f.unit or ''}".strip() + f". This is {where} the reference range printed by the lab ({f.reference_range})."
        return {
            "overview": f"Your report lists {len(findings)} laboratory results. {len(attention)} of them are marked for your clinician to look at. Only a clinician can interpret these results in the context of your health.",
            "findings": [{"finding_id": f.id, "plain_language": describe(f)} for f in findings],
            "items_for_clinician_review": [{"finding_id": f.id, "reason": "Outside the lab's printed reference range or flagged by the lab."} for f in attention],
            "questions_to_ask": ["What do these results mean for me?", "Do I need any follow-up testing?"],
            "limitations": ["Test double output.", "It cannot interpret results in the context of your health history."],
        }
    if task == "clinician_summary":
        return {
            "headline": f"Laboratory report with {len(findings)} results; {len(attention)} flagged or outside the printed interval.",
            "key_findings": [
                {"finding_id": f.id, "test_name": f.test_name, "value": f.value, "unit": f.unit, "reference_range": f.reference_range, "reported_flag": f.flag, "note": "flagged or outside reported reference interval"}
                for f in findings if f.flag or outside_range(f.value, f.reference_range)
            ],
            "other_findings_count": len(findings) - len(attention),
            "items_requiring_review": [f.test_name for f in attention],
            "data_quality": [],
            "limitations": ["Simulated demo output. Draft for clinician review only."],
        }
    raise ValueError(f"No demo output for task {task}")


def _call(name: str, args: dict[str, Any] | None = None) -> AssistantTurn:
    return AssistantTurn(content=None, tool_calls=[ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=name, arguments=json.dumps(args or {}))])


def tool_step(messages: list[dict[str, Any]], ctx: dict[str, Any]) -> AssistantTurn:
    done = [m["tool_calls"][0]["function"]["name"] for m in messages if m.get("role") == "assistant" and m.get("tool_calls")]
    snap = ctx["snapshot"]
    if "get_case_snapshot" not in done:
        return _call("get_case_snapshot")
    if ctx["mode"] == "HANDOFF":
        if "create_clinician_handoff" not in done and snap["status"] == "CONSENT_GRANTED":
            return _call("create_clinician_handoff")
        if "notify_patient" not in done:
            return _call("notify_patient", {"title": "Your report was shared", "body": "Your report and summary were sent to your clinician. We will let you know when they respond."})
        return AssistantTurn(content="[Simulated] Handoff created and patient notified.")
    h = snap.get("handoff")
    if h and snap["status"] == "HANDOFF_SENT" and (h["hours_since_sent"] or 0) > h["acknowledgment_window_hours"] and "ack_reminder" not in snap["open_follow_up_tasks"] and "create_follow_up_task" not in done:
        return _call("create_follow_up_task", {"kind": "ack_reminder", "description": "A shared case has not been acknowledged within the expected window. Please acknowledge it.", "due_in_hours": 24})
    return AssistantTurn(content="[Simulated] Follow-up check complete.")
