"""Structured Meta calls for symptom threads, with telemetry and one re-ask on invalid output."""

from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.pipeline import record_model_call
from app.ai.provider import ModelCallError, get_provider
from app.models import MedicalCase, ModelCall

T = TypeVar("T", bound=BaseModel)


def call_structured(db: Session, case: MedicalCase, task: str, system: str, user: str, schema: type[T], context: dict[str, Any]) -> tuple[T | None, list[ModelCall]]:
    """Returns (output, calls). Output is None when Meta is unavailable or keeps returning invalid output."""
    calls: list[ModelCall] = []
    try:
        provider = get_provider()
    except RuntimeError:
        return None, calls
    last_error = ""
    for attempt in (1, 2):
        prompt = user if attempt == 1 else f"{user}\n\nYour previous answer was rejected: {last_error}\nReturn corrected JSON."
        try:
            out, meta = provider.structured(task=task, system=system, user=prompt, schema=schema, context={**context, "prompt": prompt})
            calls.append(record_model_call(db, meta, None, case.id))
            db.flush()
            return out, calls
        except ModelCallError as e:
            calls.append(record_model_call(db, e.meta, None, case.id))
            db.flush()
            last_error = e.meta.error or str(e)
            if e.meta.status != "invalid_output":
                break
    return None, calls
