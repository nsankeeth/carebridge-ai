"""Pydantic schemas for every structured output the Meta model produces.

The same models generate the JSON Schema sent as `response_format` and validate the reply.
"""

import copy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# 1. Report understanding -------------------------------------------------------


class ExtractedItem(_Strict):
    test_name: str = Field(description="Test name exactly as printed in the report")
    value: str = Field(description="Result value exactly as printed, including symbols like < or >")
    unit: str | None = Field(description="Unit exactly as printed, or null if none is printed")
    reference_range: str | None = Field(description="Reference interval exactly as printed, or null")
    flag: str | None = Field(description="Abnormality flag printed by the lab (e.g. H, L), or null. Never infer one.")
    source_page: int = Field(description="1-based page number where the result appears")
    source_quote: str = Field(description="The exact line of report text this result was read from")


class ExtractionResult(_Strict):
    lab_name: str | None
    report_date: str | None = Field(description="Collection or report date as printed, or null")
    findings: list[ExtractedItem]
    ambiguities: list[str] = Field(description="Anything unclear, illegible, or missing. Empty list if none.")


# 2. Patient-friendly explanation ------------------------------------------------


class FindingExplanation(_Strict):
    finding_id: str = Field(description="The id of the finding being explained, copied from the input")
    plain_language: str = Field(description="What this test measures and what the report states, in plain words")


class ReviewItem(_Strict):
    finding_id: str
    reason: str = Field(description="Why a clinician should look at this, without diagnosing")


class PatientExplanation(_Strict):
    overview: str = Field(description="2-4 sentence plain-language overview of what the report contains")
    findings: list[FindingExplanation]
    items_for_clinician_review: list[ReviewItem]
    questions_to_ask: list[str] = Field(description="Questions the patient could bring to their clinician")
    limitations: list[str] = Field(description="What this explanation cannot tell the patient")


# 3. Clinician handoff summary ---------------------------------------------------


class KeyFinding(_Strict):
    finding_id: str
    test_name: str
    value: str
    unit: str | None
    reference_range: str | None
    reported_flag: str | None
    note: str = Field(description="Short factual note, e.g. 'above reported reference interval'. No diagnosis.")


class ClinicianSummary(_Strict):
    headline: str = Field(description="One-line factual summary of the report for a clinician")
    key_findings: list[KeyFinding] = Field(description="Results outside the reported interval or flagged by the lab")
    other_findings_count: int = Field(description="How many other results were reported within range")
    items_requiring_review: list[str]
    data_quality: list[str] = Field(description="Extraction or report-quality caveats. Empty list if none.")
    limitations: list[str]


# 4. Administrative follow-up message (used by the coordinator agent) ------------


class AdminMessage(_Strict):
    title: str
    body: str


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic schema → Meta Model API strict subset (all props required, no extras, no defaults)."""
    schema = copy.deepcopy(model.model_json_schema())

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("title", None)
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"].keys())
                node["additionalProperties"] = False
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema
