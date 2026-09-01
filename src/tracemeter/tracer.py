"""Core tracing primitives: Span, Tracer, @trace decorator, span() context manager.

Spans nest via a contextvar stack so a full pipeline (agent -> steps ->
model calls) shows up as a tree, matching OTel's model rather than
inventing a parallel one.
"""

from __future__ import annotations

import contextvars
import functools
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from tracemeter import semconv
from tracemeter.storage.sqlite_store import SqliteStore

_current_span: contextvars.ContextVar[Optional["Span"]] = contextvars.ContextVar(
    "tracemeter_current_span", default=None
)
_current_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "tracemeter_current_trace_id", default=None
)


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str = field(default_factory=_new_id)
    parent_span_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error_message: Optional[str] = None

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def set_attributes(self, attrs: dict[str, Any]) -> None:
        self.attributes.update(attrs)

    def record_exception(self, exc: BaseException) -> None:
        self.status = "error"
        self.error_message = f"{type(exc).__name__}: {exc}"

    @property
    def latency_ms(self) -> Optional[float]:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000.0


class _SpanContext:
    """Context manager returned by Tracer.span()."""

    def __init__(self, tracer: "Tracer", name: str, attributes: Optional[dict[str, Any]] = None):
        self._tracer = tracer
        self._name = name
        self._initial_attrs = attributes or {}
        self._span: Optional[Span] = None
        self._parent_token = None
        self._trace_token = None

    def __enter__(self) -> Span:
        parent = _current_span.get()
        trace_id = _current_trace_id.get()
        if trace_id is None:
            trace_id = _new_id()
            self._trace_token = _current_trace_id.set(trace_id)

        span = Span(
            name=self._name,
            trace_id=trace_id,
            parent_span_id=parent.span_id if parent else None,
        )
        span.set_attributes(self._initial_attrs)
        self._span = span
        self._parent_token = _current_span.set(span)
        return span

    def __exit__(self, exc_type, exc, tb) -> bool:
        span = self._span
        assert span is not None
        span.end_time = time.time()
        span.set_attribute(semconv.TRACEMETER_LATENCY_MS, span.latency_ms)
        if exc is not None:
            span.record_exception(exc)
        span.set_attribute(semconv.TRACEMETER_STATUS, span.status)
        if span.error_message:
            span.set_attribute(semconv.TRACEMETER_ERROR_MESSAGE, span.error_message)

        self._tracer.store.write_span(span)

        _current_span.reset(self._parent_token)
        if self._trace_token is not None:
            _current_trace_id.reset(self._trace_token)

        return False  # never suppress exceptions

    # `async with tracemeter.span(...)` for async pipelines -- opening and
    # closing a span is pure in-memory bookkeeping plus a local SQLite
    # write, no actual `await`s needed, so these just delegate to the sync
    # versions rather than duplicating them.
    async def __aenter__(self) -> Span:
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return self.__exit__(exc_type, exc, tb)


class Tracer:
    """Entry point for creating spans. Backed by a local SQLite store."""

    def __init__(self, store: Optional[SqliteStore] = None):
        self.store = store or SqliteStore.default()

    def span(self, name: str, **attributes: Any) -> _SpanContext:
        return _SpanContext(self, name, attributes)

    def current_span(self) -> Optional[Span]:
        return _current_span.get()

    def trace(self, name: Optional[str] = None) -> Callable:
        """Decorator form of span(): @tracer.trace("step_name")."""

        def decorator(fn: Callable) -> Callable:
            span_name = name or fn.__name__

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.span(span_name):
                    return fn(*args, **kwargs)

            return wrapper

        return decorator


_default_tracer: Optional[Tracer] = None


def get_default_tracer() -> Tracer:
    global _default_tracer
    if _default_tracer is None:
        _default_tracer = Tracer()
    return _default_tracer


def trace(name: Optional[str] = None) -> Callable:
    """Module-level @trace decorator, using the default tracer."""

    def decorator(fn: Callable) -> Callable:
        span_name = name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with get_default_tracer().span(span_name):
                return fn(*args, **kwargs)

        return wrapper

    return decorator
