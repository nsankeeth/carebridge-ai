"""Verify real Meta Model API inference end to end. Run: python -m app.verify_meta

Makes two live calls with the configured key and model:
  1. structured output (report understanding schema) on a sample report
  2. function tool calling (coordinator toolset)
Prints model id, latency and token usage for each. Exits non-zero on any failure.
"""

import sys

from app.agent.coordinator import MODE_TOOLS, TOOL_DEFS
from app.agent.documents import extract_pages, pages_to_prompt_text
from app.ai import prompts
from app.ai.provider import MetaProvider, ModelCallError
from app.ai.schemas import ExtractionResult
from app.config import get_settings
from app.fixtures import REPORTS, build_pdf


def main() -> int:
    s = get_settings()
    print(f"endpoint={s.meta_base_url} model={s.meta_model} key_configured={bool(s.model_api_key)}")
    try:
        provider = MetaProvider(s.model_api_key, s.meta_base_url, s.meta_model, s.ai_timeout_seconds, 0)
    except RuntimeError as e:
        print(f"BLOCKED: {e}")
        return 2

    report = next(r for r in REPORTS if r.slug == "cbc-iron-maya")
    text = pages_to_prompt_text(extract_pages(build_pdf(report)))
    try:
        out, meta = provider.structured(
            task="verify_structured_output",
            system=prompts.EXTRACTION_SYSTEM,
            user=f"Extract all laboratory results from this report.\n\n{text}",
            schema=ExtractionResult,
        )
    except ModelCallError as e:
        print(f"FAILED structured output: {e.meta.error}")
        return 1
    print(f"[structured] ok model={meta.model_id} latency={meta.latency_ms:.0f}ms tokens={meta.input_tokens}/{meta.output_tokens}/{meta.total_tokens} id={meta.response_id}")
    for f in out.findings:
        print(f"   - {f.test_name}: {f.value} {f.unit or ''} (ref {f.reference_range}) flag={f.flag} p{f.source_page}")

    tools = [TOOL_DEFS[n] for n in MODE_TOOLS["FOLLOW_UP"]]
    messages = [
        {"role": "system", "content": prompts.COORDINATOR_SYSTEM},
        {"role": "user", "content": "Case 00000000-0000-0000-0000-000000000000. Goal: run a follow-up check on this case."},
    ]
    try:
        turn, meta = provider.tool_step(task="verify_tool_calling", messages=messages, tools=tools)
    except ModelCallError as e:
        print(f"FAILED tool calling: {e.meta.error}")
        return 1
    calls = [c.name for c in turn.tool_calls]
    print(f"[tools] ok model={meta.model_id} latency={meta.latency_ms:.0f}ms tokens={meta.total_tokens} tool_calls={calls}")
    if "get_case_snapshot" not in calls:
        print("WARNING: model did not call get_case_snapshot first")
    print("Meta inference verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
