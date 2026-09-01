"""Auto-instrumentation for LangChain via its callback handler system.

Unlike the openai/anthropic/litellm integrations, there's no single
`create` method to monkeypatch here -- LangChain's chat model integrations
are numerous and provider-specific, but they all funnel through the same
callback handler API, so that's the one seam that works across all of them.

    from langchain_openai import ChatOpenAI
    from tracemeter.integrations.langchain_wrap import TraceMeterCallbackHandler

    llm = ChatOpenAI(model="gpt-4o-mini", callbacks=[TraceMeterCallbackHandler()])
    llm.invoke("hello")  # traced

Requires the `langchain` extra: pip install "tracemeter[langchain]"
"""

from __future__ import annotations

import time
from typing import Any, Optional
from uuid import UUID

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The LangChain integration requires the 'langchain' extra: "
        "pip install 'tracemeter[langchain]'"
    ) from exc

from tracemeter import semconv
from tracemeter.integrations._common import _set_cost
from tracemeter.tracer import Tracer, get_default_tracer

# Substrings matched (in order) against a call's `serialized["id"]` module
# path (e.g. ["langchain_openai", "chat_models", "base", "ChatOpenAI"]) to
# recover the underlying provider for `gen_ai.system`. Falls back to
# "langchain" for integrations not in this list, same as litellm_wrap
# falling back to "litellm" -- the model string still identifies it.
_KNOWN_SYSTEMS = (
    "openai",
    "anthropic",
    "bedrock",
    "vertexai",
    "google",
    "azure",
    "cohere",
    "mistralai",
    "groq",
    "ollama",
)


def _extract_system(serialized: Optional[dict]) -> str:
    if serialized:
        path = ".".join(str(p) for p in serialized.get("id") or []).lower()
        for known in _KNOWN_SYSTEMS:
            if known in path:
                return known
    return "langchain"


def _extract_model(serialized: Optional[dict], kwargs: dict) -> Optional[str]:
    invocation_params = kwargs.get("invocation_params") or {}
    model = invocation_params.get("model") or invocation_params.get("model_name")
    if model:
        return model
    serialized_kwargs = (serialized or {}).get("kwargs") or {}
    return serialized_kwargs.get("model") or serialized_kwargs.get("model_name")


def _extract_usage(response: Any) -> tuple[int, int, int]:
    """Prefers each generation's `usage_metadata` (langchain-core's
    provider-normalized token accounting, present since ~0.2), falling back
    to the older provider-specific `llm_output["token_usage"]` shape."""
    for generation_list in getattr(response, "generations", None) or []:
        for generation in generation_list:
            message = getattr(generation, "message", None)
            usage = getattr(message, "usage_metadata", None) if message else None
            if usage:
                details = usage.get("output_token_details") or {}
                return (
                    usage.get("input_tokens") or 0,
                    usage.get("output_tokens") or 0,
                    details.get("reasoning") or 0,
                )
    llm_output = getattr(response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    return (
        token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0,
        token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0,
        0,
    )


class TraceMeterCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that emits an OTel-GenAI-compliant
    TraceMeter span (with cost computed from response token usage) for
    every chat/LLM call it observes.

    Attach it globally to a model, or pass it per-call:

        llm = ChatOpenAI(callbacks=[TraceMeterCallbackHandler()])
        # or: llm.invoke("hello", config={"callbacks": [TraceMeterCallbackHandler()]})
    """

    def __init__(self, tracer: Optional[Tracer] = None):
        self._tracer = tracer or get_default_tracer()
        # Runs can execute concurrently (batches, async, sub-chains), so
        # each is tracked independently by the run_id LangChain assigns it
        # rather than assuming call/return happen back-to-back.
        self._runs: dict[UUID, dict[str, Any]] = {}

    def _start(self, run_id: UUID, serialized: Optional[dict], kwargs: dict) -> None:
        system = _extract_system(serialized)
        model = _extract_model(serialized, kwargs)
        span_ctx = self._tracer.span(
            f"{system}.{semconv.OPERATION_CHAT}",
            **{
                semconv.GEN_AI_SYSTEM: system,
                semconv.GEN_AI_OPERATION_NAME: semconv.OPERATION_CHAT,
                semconv.GEN_AI_REQUEST_MODEL: model,
            },
        )
        span = span_ctx.__enter__()
        self._runs[run_id] = {
            "span_ctx": span_ctx,
            "span": span,
            "system": system,
            "model": model,
            "first_token_seen": False,
        }

    def on_llm_start(self, serialized: dict, prompts: list, *, run_id: UUID, **kwargs: Any) -> Any:
        self._start(run_id, serialized, kwargs)

    def on_chat_model_start(self, serialized: dict, messages: list, *, run_id: UUID, **kwargs: Any) -> Any:
        self._start(run_id, serialized, kwargs)

    def on_llm_new_token(self, token: str, *, run_id: UUID, **kwargs: Any) -> Any:
        entry = self._runs.get(run_id)
        if entry is not None and not entry["first_token_seen"]:
            entry["first_token_seen"] = True
            entry["span"].set_attribute(
                semconv.TRACEMETER_TTFT_MS, (time.time() - entry["span"].start_time) * 1000.0
            )

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> Any:
        entry = self._runs.pop(run_id, None)
        if entry is None:
            return
        span, span_ctx, system, model = entry["span"], entry["span_ctx"], entry["system"], entry["model"]
        in_tok, out_tok, reason_tok = _extract_usage(response)
        response_model = (getattr(response, "llm_output", None) or {}).get("model_name") or model
        span.set_attributes(
            {
                semconv.GEN_AI_RESPONSE_MODEL: response_model,
                semconv.GEN_AI_USAGE_INPUT_TOKENS: in_tok,
                semconv.GEN_AI_USAGE_OUTPUT_TOKENS: out_tok,
            }
        )
        if reason_tok:
            span.set_attribute(semconv.GEN_AI_USAGE_REASONING_TOKENS, reason_tok)
        _set_cost(span, system, response_model or model, in_tok, out_tok, reason_tok)
        span_ctx.__exit__(None, None, None)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> Any:
        entry = self._runs.pop(run_id, None)
        if entry is None:
            return
        entry["span_ctx"].__exit__(type(error), error, None)
