"""Auto-instrumentation for the `openai` client (>=1.0 SDK).

    from openai import OpenAI
    from tracemeter.integrations.openai_wrap import instrument_openai

    client = OpenAI()
    instrument_openai(client)

    client.chat.completions.create(...)  # now traced automatically
"""

from __future__ import annotations

from typing import Any, Optional

from tracemeter.integrations._common import instrument_create_method
from tracemeter.tracer import Tracer


def _extract_model(kwargs: dict) -> Optional[str]:
    return kwargs.get("model")


def _extract_usage(response: Any) -> tuple[int, int, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return (0, 0, 0)
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0
    reasoning_tokens = 0
    details = getattr(usage, "completion_tokens_details", None)
    if details is not None:
        reasoning_tokens = getattr(details, "reasoning_tokens", 0) or 0
    return (input_tokens, output_tokens, reasoning_tokens)


def _is_streaming(kwargs: dict) -> bool:
    return bool(kwargs.get("stream"))


def _on_stream_chunk_usage(chunk: Any) -> Optional[tuple[int, int, int]]:
    # Only populated on the final chunk when `stream_options={"include_usage": True}`.
    usage = getattr(chunk, "usage", None)
    if usage is None:
        return None
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0
    return (input_tokens, output_tokens, 0)


def instrument_openai(client: Any, tracer: Optional[Tracer] = None) -> Any:
    """Instrument an OpenAI (or AsyncOpenAI) client instance in place.

    Wraps `client.chat.completions.create` and `client.embeddings.create`.
    Returns the same client for convenience.
    """
    instrument_create_method(
        client,
        "chat.completions.create",
        system="openai",
        operation="chat",
        extract_model=_extract_model,
        extract_usage=_extract_usage,
        is_streaming=_is_streaming,
        on_stream_chunk_usage=_on_stream_chunk_usage,
        tracer=tracer,
    )
    if hasattr(client, "embeddings"):
        instrument_create_method(
            client,
            "embeddings.create",
            system="openai",
            operation="embeddings",
            extract_model=_extract_model,
            extract_usage=_extract_usage,
            is_streaming=lambda kwargs: False,
            tracer=tracer,
        )
    return client
