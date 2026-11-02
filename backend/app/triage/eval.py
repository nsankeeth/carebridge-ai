"""Live triage evaluation: runs synthetic vignettes through the rules and the Meta model and prints the results.

    python -m app.triage.eval

A report, not a gate: it always exits 0. Record the real output, misses included.
"""

import sys
from datetime import date

from app.ai import prompts
from app.ai.provider import ModelCallError, get_provider
from app.ai.schemas import TriageModelOutput
from app.config import get_settings
from app.models import URGENCY_RANK, Urgency, max_urgency
from app.triage import content, questions, rules
from app.triage.eval_cases import VIGNETTES


def main() -> int:
    s = get_settings()
    if not s.model_api_key:
        print("MODEL_API_KEY is not set; the evaluation needs live Meta inference.")
        return 0
    provider = get_provider()
    system = prompts.triage_system(list(content.CARE_TIPS), list(questions.BANK))
    print(f"model={s.meta_model} endpoint={s.meta_base_url} run={date.today()}\n")
    print(f"{'vignette':45} {'min':9} {'rules':9} {'model':9} {'final':9} result  latency")
    passed = model_alone = 0
    for v in VIGNETTES:
        r = rules.evaluate(v.text, v.answers, v.age_years)
        answers = "".join(f"\n- Patient answered '{questions.BANK[q].text}': {a}" for q, a in v.answers.items())
        who = f"a child aged {v.age_years:.1f} years (the parent is writing)" if v.age_years is not None and v.age_years < 18 else f"the patient, aged {v.age_years:.0f}"
        user = f"About: {who}\nRule-based red flags found so far: {', '.join(f.code for f in r.flags) or 'none'}\n\nMessages:\n- Patient: {v.text}{answers}"
        try:
            out, meta = provider.structured(task="triage_assessment", system=system, user=user, schema=TriageModelOutput, context={})
            model_level, latency = Urgency(out.level), f"{meta.latency_ms / 1000:.1f}s"
        except ModelCallError as e:
            model_level, latency = None, f"error: {e.meta.status}"
        final = max_urgency(r.level, model_level) or Urgency.SOON
        ok = URGENCY_RANK[final] >= URGENCY_RANK[v.min_level]
        passed += ok
        model_alone += bool(model_level) and URGENCY_RANK[model_level] >= URGENCY_RANK[v.min_level]
        lv = lambda x: x.value if x else "-"  # noqa: E731
        print(f"{v.name[:45]:45} {v.min_level.value:9} {lv(r.level):9} {lv(model_level):9} {final.value:9} {'PASS' if ok else 'MISS':6}  {latency}", flush=True)
    n = len(VIGNETTES)
    print(f"\nFinal level at or above the expected minimum: {passed}/{n}. Meta alone: {model_alone}/{n}.")
    print("Synthetic vignettes written for a demo; this is a smoke test, not clinical validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
