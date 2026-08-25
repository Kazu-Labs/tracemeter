"""Auto-instrumentation for the `anthropic` client.

    from anthropic import Anthropic
    from tracemeter.integrations.anthropic_wrap import instrument_anthropic

    client = Anthropic()
    instrument_anthropic(client)

    client.messages.create(...)  # now traced automatically
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
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    return (input_tokens, output_tokens, 0)


def _is_streaming(kwargs: dict) -> bool:
    return bool(kwargs.get("stream"))


def _on_stream_chunk_usage(chunk: Any) -> Optional[tuple[int, int, int]]:
    # Anthropic streams a message_delta event carrying cumulative output
    # usage near the end of the stream; message_start carries input usage.
    usage = getattr(chunk, "usage", None)
    if usage is None:
        message = getattr(chunk, "message", None)
        usage = getattr(message, "usage", None) if message else None
    if usage is None:
        return None
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    if not input_tokens and not output_tokens:
        return None
    return (input_tokens, output_tokens, 0)


def instrument_anthropic(client: Any, tracer: Optional[Tracer] = None) -> Any:
    """Instrument an Anthropic (or AsyncAnthropic) client instance in place.

    Wraps `client.messages.create`. Returns the same client for convenience.
    """
    instrument_create_method(
        client,
        "messages.create",
        system="anthropic",
        operation="chat",
        extract_model=_extract_model,
        extract_usage=_extract_usage,
        is_streaming=_is_streaming,
        on_stream_chunk_usage=_on_stream_chunk_usage,
        tracer=tracer,
    )
    return client
