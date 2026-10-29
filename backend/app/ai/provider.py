"""LLM provider adapter.

`MetaProvider` is the production path: real inference against the Meta Model API
(https://api.meta.ai/v1, OpenAI-SDK compatible, verified against dev.meta.ai/docs).
It is the only provider; tests swap in a test double via `set_provider_override`.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeVar

from openai import APIError, APITimeoutError, OpenAI
from pydantic import BaseModel, ValidationError

from app.ai.schemas import json_schema_for
from app.config import get_settings

log = logging.getLogger("ai")
T = TypeVar("T", bound=BaseModel)


@dataclass
class CallMeta:
    task: str
    provider: str
    model_id: str
    status: str = "ok"
    latency_ms: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    response_id: str | None = None
    error: str | None = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string from the model; validated by the tool layer


@dataclass
class AssistantTurn:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ModelCallError(Exception):
    def __init__(self, meta: CallMeta, message: str):
        super().__init__(message)
        self.meta = meta


class LLMProvider(Protocol):
    name: str
    model_id: str

    def structured(
        self, *, task: str, system: str, user: str, schema: type[T], context: dict[str, Any] | None = None
    ) -> tuple[T, CallMeta]: ...

    def tool_step(
        self,
        *,
        task: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> tuple[AssistantTurn, CallMeta]: ...


class MetaProvider:
    name = "meta"

    def __init__(self, api_key: str, base_url: str, model_id: str, timeout: float, max_retries: int):
        if not api_key:
            raise RuntimeError("MODEL_API_KEY is not set; real Meta inference is unavailable")
        self.model_id = model_id
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries)

    def _meta(self, task: str) -> CallMeta:
        return CallMeta(task=task, provider=self.name, model_id=self.model_id)

    @staticmethod
    def _fill_usage(meta: CallMeta, resp: Any) -> None:
        usage = getattr(resp, "usage", None)
        if usage is not None:
            meta.input_tokens = getattr(usage, "prompt_tokens", None)
            meta.output_tokens = getattr(usage, "completion_tokens", None)
            meta.total_tokens = getattr(usage, "total_tokens", None)
        meta.response_id = getattr(resp, "id", None)
        # Record the model the API says actually served the request.
        meta.model_id = getattr(resp, "model", None) or meta.model_id

    def _create(self, meta: CallMeta, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(model=self.model_id, **kwargs)
        except (APITimeoutError, APIError) as e:
            meta.status = "error"
            meta.latency_ms = (time.perf_counter() - start) * 1000
            meta.error = f"{type(e).__name__}: {getattr(e, 'message', str(e))}"[:500]
            raise ModelCallError(meta, meta.error) from e
        meta.latency_ms = (time.perf_counter() - start) * 1000
        self._fill_usage(meta, resp)
        log.info(
            "meta inference task=%s model=%s latency_ms=%.0f tokens=%s",
            meta.task, meta.model_id, meta.latency_ms, meta.total_tokens,
        )
        return resp

    def structured(self, *, task, system, user, schema, context=None):
        meta = self._meta(task)
        resp = self._create(
            meta,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": json_schema_for(schema), "strict": True},
            },
        )
        raw = resp.choices[0].message.content or ""
        try:
            return schema.model_validate_json(raw), meta
        except ValidationError as e:
            meta.status = "invalid_output"
            meta.error = str(e)[:500]
            raise ModelCallError(meta, "Model output failed schema validation") from e

    def tool_step(self, *, task, messages, tools, context=None):
        meta = self._meta(task)
        resp = self._create(meta, messages=messages, tools=tools, parallel_tool_calls=False)
        msg = resp.choices[0].message
        calls = [ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments) for tc in msg.tool_calls or []]
        return AssistantTurn(content=msg.content, tool_calls=calls), meta


_override: Callable[[], LLMProvider] | None = None


def set_provider_override(factory: Callable[[], LLMProvider] | None) -> None:
    """Tests inject a fake provider here so they never hit the network."""
    global _override
    _override = factory


def get_provider() -> LLMProvider:
    if _override:
        return _override()
    s = get_settings()
    return MetaProvider(s.model_api_key, s.meta_base_url, s.meta_model, s.ai_timeout_seconds, s.ai_max_retries)


def tool_args(call: ToolCall) -> dict[str, Any]:
    try:
        args = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        return {}
    return args if isinstance(args, dict) else {}
