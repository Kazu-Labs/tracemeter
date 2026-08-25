"""Auto-instrumentation for `litellm`.

Unlike the openai/anthropic SDKs, litellm's primary interface is a
module-level function (`litellm.completion`, `litellm.acompletion`)
rather than a client instance, so this patches the module directly
rather than a per-instance bound method.

    import litellm
    from tracemeter.integrations.litellm_wrap import instrument_litellm

    instrument_litellm(litellm)

    litellm.completion(model="gpt-4o-mini", messages=[...])  # traced
"""

from __future__ import annotations

from typing import Any, Optional

from tracemeter.integrations._common import instrument_create_method
from tracemeter.tracer import Tracer


def _extract_model(kwargs: dict) -> Optional[str]:
    return kwargs.get("model")


def _extract_usage(response: Any) -> tuple[int, int, int]:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return (0, 0, 0)
    get = (lambda k: usage.get(k)) if isinstance(usage, dict) else (lambda k: getattr(usage, k, None))
    return (get("prompt_tokens") or 0, get("completion_tokens") or 0, 0)


def _is_streaming(kwargs: dict) -> bool:
    return bool(kwargs.get("stream"))


def instrument_litellm(litellm_module: Any, tracer: Optional[Tracer] = None) -> Any:
    """Instrument the `litellm` module's `completion` (and `acompletion`,
    if present) in place. litellm normalizes providers internally, so
    `gen_ai.system` is reported as "litellm" -- the underlying provider is
    still visible via the model string."""
    instrument_create_method(
        litellm_module,
        "completion",
        system="litellm",
        operation="chat",
        extract_model=_extract_model,
        extract_usage=_extract_usage,
        is_streaming=_is_streaming,
        tracer=tracer,
    )
    if hasattr(litellm_module, "acompletion"):
        instrument_create_method(
            litellm_module,
            "acompletion",
            system="litellm",
            operation="chat",
            extract_model=_extract_model,
            extract_usage=_extract_usage,
            is_streaming=_is_streaming,
            tracer=tracer,
        )
    return litellm_module
