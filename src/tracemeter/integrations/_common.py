"""Shared plumbing for provider auto-instrumentation.

Wrapping strategy: patch the bound `create` method on a *client instance*
(not the class globally) so instrumenting one client never affects
another, and tests can instrument a fake client with no monkeypatching
of real SDK internals.
"""

from __future__ import annotations

import inspect
import time
from typing import Any, Callable, Optional

from tracemeter import semconv
from tracemeter.pricing.engine import compute_cost
from tracemeter.tracer import Tracer, get_default_tracer


class _StreamState:
    """Shared bookkeeping between the sync and async stream wrappers below --
    first-chunk TTFT capture and the "close exactly once" span teardown are
    identical either way; only how chunks are pulled off the iterator
    differs between `__next__` and `__anext__`."""

    def __init__(self, span_ctx: Any, span: Any, on_chunk: Callable, on_done: Callable):
        self._span_ctx = span_ctx
        self._span = span
        self._on_chunk = on_chunk
        self._on_done = on_done
        self._first_chunk_seen = False
        self._closed = False

    def handle_chunk(self, chunk: Any) -> None:
        if not self._first_chunk_seen:
            self._first_chunk_seen = True
            self._span.set_attribute(
                semconv.TRACEMETER_TTFT_MS, (time.time() - self._span.start_time) * 1000.0
            )
        self._on_chunk(chunk)

    def close(self, exc: Optional[BaseException] = None) -> None:
        if self._closed:
            return
        self._closed = True
        self._on_done()
        self._span_ctx.__exit__(type(exc) if exc else None, exc, None)


class _StreamSpanWrapper:
    """Wraps a sync streaming response iterator so the span stays open
    across iteration and closes (with usage/cost attrs, if available) once
    the stream is exhausted or errors."""

    def __init__(self, iterator: Any, span_ctx: Any, span: Any, on_chunk: Callable, on_done: Callable):
        self._iterator = iterator
        self._state = _StreamState(span_ctx, span, on_chunk, on_done)

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = next(self._iterator)
        except StopIteration:
            self._state.close()
            raise
        except BaseException as exc:
            self._state.close(exc)
            raise
        self._state.handle_chunk(chunk)
        return chunk


class _AsyncStreamSpanWrapper:
    """Same as `_StreamSpanWrapper`, but over `__anext__`/`StopAsyncIteration`
    for AsyncOpenAI/AsyncAnthropic-style streaming responses, which are
    async iterators rather than sync ones -- the sync wrapper's `next()`
    call would raise `TypeError` against them instead of iterating."""

    def __init__(self, iterator: Any, span_ctx: Any, span: Any, on_chunk: Callable, on_done: Callable):
        self._iterator = iterator
        self._state = _StreamState(span_ctx, span, on_chunk, on_done)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            chunk = await self._iterator.__anext__()
        except StopAsyncIteration:
            self._state.close()
            raise
        except BaseException as exc:
            self._state.close(exc)
            raise
        self._state.handle_chunk(chunk)
        return chunk


def instrument_create_method(
    client: Any,
    attr_path: str,
    system: str,
    operation: str,
    extract_model: Callable[[dict], Optional[str]],
    extract_usage: Callable[[Any], tuple[int, int, int]],
    is_streaming: Callable[[dict], bool],
    on_stream_chunk_usage: Optional[Callable[[Any], Optional[tuple[int, int, int]]]] = None,
    tracer: Optional[Tracer] = None,
) -> None:
    """Monkeypatch `client.<attr_path>` (e.g. "chat.completions.create") to
    emit an OTel-GenAI-compliant span around every call.

    extract_usage(response) -> (input_tokens, output_tokens, reasoning_tokens)
    on_stream_chunk_usage(chunk) -> usage tuple or None; called per chunk to
        find the final chunk's usage in streaming responses.
    """
    tracer = tracer or get_default_tracer()
    parts = attr_path.split(".")
    parent = client
    for p in parts[:-1]:
        parent = getattr(parent, p)
    method_name = parts[-1]
    original = getattr(parent, method_name)

    if getattr(original, "_tracemeter_wrapped", False):
        return  # already instrumented

    def _start_span(kwargs: dict):
        model = extract_model(kwargs)
        span_ctx = tracer.span(
            f"{system}.{operation}",
            **{
                semconv.GEN_AI_SYSTEM: system,
                semconv.GEN_AI_OPERATION_NAME: operation,
                semconv.GEN_AI_REQUEST_MODEL: model,
            },
        )
        span = span_ctx.__enter__()
        if "max_tokens" in kwargs:
            span.set_attribute(semconv.GEN_AI_REQUEST_MAX_TOKENS, kwargs["max_tokens"])
        if "temperature" in kwargs:
            span.set_attribute(semconv.GEN_AI_REQUEST_TEMPERATURE, kwargs["temperature"])
        return span_ctx, span, model

    def _finish_non_streaming(span_ctx, span, model, response):
        in_tok, out_tok, reason_tok = extract_usage(response)
        response_model = getattr(response, "model", None) or model
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

    def _make_stream_wrapper(span_ctx, span, model, iterator, wrapper_cls=_StreamSpanWrapper):
        usage_holder: dict[str, Any] = {}

        def on_chunk(chunk):
            if on_stream_chunk_usage:
                usage = on_stream_chunk_usage(chunk)
                if usage:
                    usage_holder["usage"] = usage

        def on_done():
            in_tok, out_tok, reason_tok = usage_holder.get("usage", (0, 0, 0))
            span.set_attributes(
                {
                    semconv.GEN_AI_RESPONSE_MODEL: model,
                    semconv.GEN_AI_USAGE_INPUT_TOKENS: in_tok,
                    semconv.GEN_AI_USAGE_OUTPUT_TOKENS: out_tok,
                }
            )
            if reason_tok:
                span.set_attribute(semconv.GEN_AI_USAGE_REASONING_TOKENS, reason_tok)
            _set_cost(span, system, model, in_tok, out_tok, reason_tok)

        return wrapper_cls(iterator, span_ctx, span, on_chunk, on_done)

    if inspect.iscoroutinefunction(original):

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            span_ctx, span, model = _start_span(kwargs)
            try:
                response = await original(*args, **kwargs)
            except BaseException as exc:
                span_ctx.__exit__(type(exc), exc, None)
                raise
            if is_streaming(kwargs):
                return _make_stream_wrapper(span_ctx, span, model, response, wrapper_cls=_AsyncStreamSpanWrapper)
            _finish_non_streaming(span_ctx, span, model, response)
            return response

    else:

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            span_ctx, span, model = _start_span(kwargs)
            try:
                response = original(*args, **kwargs)
            except BaseException as exc:
                span_ctx.__exit__(type(exc), exc, None)
                raise
            if is_streaming(kwargs):
                return _make_stream_wrapper(span_ctx, span, model, response)
            _finish_non_streaming(span_ctx, span, model, response)
            return response

    wrapper._tracemeter_wrapped = True  # type: ignore[attr-defined]
    setattr(parent, method_name, wrapper)


def _set_cost(span, system: str, model: Optional[str], in_tok: int, out_tok: int, reason_tok: int) -> None:
    cost = compute_cost(
        model, input_tokens=in_tok, output_tokens=out_tok, reasoning_tokens=reason_tok, system=system
    )
    if cost is None:
        span.set_attribute(semconv.TRACEMETER_COST_UNKNOWN, True)
    else:
        span.set_attribute(semconv.TRACEMETER_COST_USD, cost)
