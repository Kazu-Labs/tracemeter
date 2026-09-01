"""Auto-instrumentation for LlamaIndex via its callback handler system.

Like LangChain, LlamaIndex has no single client method to monkeypatch --
instead every LLM/embedding call fires `on_event_start`/`on_event_end` on
whatever handlers are registered on its `CallbackManager`, regardless of
which of LlamaIndex's many provider integrations (openai, anthropic,
bedrock, ...) is doing the calling. That's the seam this hooks into.

    from llama_index.core import Settings
    from tracemeter.integrations.llamaindex_wrap import TraceMeterCallbackHandler

    Settings.callback_manager.add_handler(TraceMeterCallbackHandler())
    # or: CallbackManager([TraceMeterCallbackHandler()]) passed to a query engine

Requires the `llamaindex` extra (Python 3.10+, matching llama-index-core's
own floor): pip install "tracemeter[llamaindex]"
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from llama_index.core.callbacks.base_handler import BaseCallbackHandler
    from llama_index.core.callbacks.schema import CBEventType, EventPayload
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The LlamaIndex integration requires the 'llamaindex' extra (Python 3.10+): "
        "pip install 'tracemeter[llamaindex]'"
    ) from exc

from tracemeter import semconv
from tracemeter.integrations._common import _set_cost
from tracemeter.tracer import Tracer, get_default_tracer

# Matched against a call's `class_name()` (e.g. "openai_llm", "anthropic_llm")
# to recover the underlying provider for `gen_ai.system`. Falls back to
# "llamaindex" for integrations not in this list, same fallback style as
# litellm_wrap ("litellm") and langchain_wrap ("langchain").
_KNOWN_SYSTEMS = (
    "openai",
    "anthropic",
    "bedrock",
    "vertex",
    "gemini",
    "azure",
    "cohere",
    "mistral",
    "groq",
    "ollama",
)

_EVENT_OPERATIONS = {
    CBEventType.LLM: semconv.OPERATION_CHAT,
    CBEventType.EMBEDDING: semconv.OPERATION_EMBEDDINGS,
}


def _extract_system(serialized: dict) -> str:
    class_name = str(serialized.get("class_name") or "").lower()
    for known in _KNOWN_SYSTEMS:
        if known in class_name:
            return known
    return "llamaindex"


def _extract_model(serialized: dict) -> Optional[str]:
    return serialized.get("model") or serialized.get("model_name")


def _extract_usage(raw: Any) -> tuple[int, int]:
    """LlamaIndex LLM integrations set `response.raw` to the underlying
    provider SDK's own response object (or, for some integrations, a
    plain dict) -- the same shape openai_wrap/litellm_wrap already know
    how to read token usage from."""
    if raw is None:
        return (0, 0)
    usage = getattr(raw, "usage", None)
    if usage is None and isinstance(raw, dict):
        usage = raw.get("usage")
    if usage is None:
        return (0, 0)
    get = (lambda k: usage.get(k)) if isinstance(usage, dict) else (lambda k: getattr(usage, k, None))
    input_tokens = get("prompt_tokens") or get("input_tokens") or 0
    output_tokens = get("completion_tokens") or get("output_tokens") or 0
    return (input_tokens, output_tokens)


class TraceMeterCallbackHandler(BaseCallbackHandler):
    """LlamaIndex callback handler that emits an OTel-GenAI-compliant
    TraceMeter span (with cost computed from response token usage) for
    every LLM and embedding call it observes.

        from llama_index.core import Settings
        Settings.callback_manager.add_handler(TraceMeterCallbackHandler())
    """

    def __init__(self, tracer: Optional[Tracer] = None):
        super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
        self._tracer = tracer or get_default_tracer()
        self._runs: dict[str, dict[str, Any]] = {}

    def on_event_start(
        self,
        event_type: "CBEventType",
        payload: Optional[dict] = None,
        event_id: str = "",
        parent_id: str = "",
        **kwargs: Any,
    ) -> str:
        operation = _EVENT_OPERATIONS.get(event_type)
        if operation is None:
            return event_id
        serialized = (payload or {}).get(EventPayload.SERIALIZED) or {}
        system = _extract_system(serialized)
        model = _extract_model(serialized)
        span_ctx = self._tracer.span(
            f"{system}.{operation}",
            **{
                semconv.GEN_AI_SYSTEM: system,
                semconv.GEN_AI_OPERATION_NAME: operation,
                semconv.GEN_AI_REQUEST_MODEL: model,
            },
        )
        span = span_ctx.__enter__()
        self._runs[event_id] = {"span_ctx": span_ctx, "span": span, "system": system, "model": model}
        return event_id

    def on_event_end(
        self,
        event_type: "CBEventType",
        payload: Optional[dict] = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        entry = self._runs.pop(event_id, None)
        if entry is None:
            return
        span, span_ctx, system, model = entry["span"], entry["span_ctx"], entry["system"], entry["model"]

        payload = payload or {}
        if EventPayload.EXCEPTION in payload:
            exc = payload[EventPayload.EXCEPTION]
            span_ctx.__exit__(type(exc), exc, None)
            return

        response = payload.get(EventPayload.RESPONSE) or payload.get(EventPayload.COMPLETION)
        raw = getattr(response, "raw", None)
        in_tok, out_tok = _extract_usage(raw)
        span.set_attributes(
            {
                semconv.GEN_AI_RESPONSE_MODEL: model,
                semconv.GEN_AI_USAGE_INPUT_TOKENS: in_tok,
                semconv.GEN_AI_USAGE_OUTPUT_TOKENS: out_tok,
            }
        )
        _set_cost(span, system, model, in_tok, out_tok, 0)
        span_ctx.__exit__(None, None, None)

    def start_trace(self, trace_id: Optional[str] = None) -> None:
        pass

    def end_trace(self, trace_id: Optional[str] = None, trace_map: Optional[dict] = None) -> None:
        pass
