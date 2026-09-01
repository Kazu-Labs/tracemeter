"""Synthetic demo data for `tracemeter demo` -- a populated dashboard with
zero API keys, zero real LLM calls, and zero setup, so someone can see
what the product does before wiring up their own instrumentation.

The data tells a small story rather than being pure noise: `rag_pipeline`
runs on the expensive `gpt-4o` for the first half of the seeded history,
then switches to `gpt-4o-mini` -- giving the dashboard's cost-by-day chart
and run-comparison feature something real to show ("cost dropped after
switching models"). A handful of other pipelines cover the rest of the
surface: an agent run that sometimes fails, a streaming call with
time-to-first-token, a LangChain-routed call, and a call to an unpriced
model to demonstrate the pricing engine's fail-open "unknown cost"
behavior rather than a silent wrong number.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from tracemeter import semconv
from tracemeter.pricing.engine import compute_cost
from tracemeter.storage.sqlite_store import SqliteStore
from tracemeter.tracer import Span

_DAYS_OF_HISTORY = 14
_RUNS_PER_DAY = (2, 6)  # inclusive range of rag_pipeline runs seeded per day


@dataclass
class DemoSummary:
    trace_count: int
    span_count: int
    total_cost_usd: float


def _new_id() -> str:
    return uuid.uuid4().hex


def _finish(span: Span) -> Span:
    span.set_attribute(semconv.TRACEMETER_LATENCY_MS, span.latency_ms)
    span.set_attribute(semconv.TRACEMETER_STATUS, span.status)
    if span.error_message:
        span.set_attribute(semconv.TRACEMETER_ERROR_MESSAGE, span.error_message)
    return span


def _span(
    trace_id: str,
    parent_span_id: Optional[str],
    name: str,
    start_time: float,
    duration_s: float,
    attributes: dict,
    status: str = "ok",
    error_message: Optional[str] = None,
    span_id: Optional[str] = None,
) -> Span:
    kwargs = dict(
        name=name,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        start_time=start_time,
        end_time=start_time + duration_s,
        status=status,
        error_message=error_message,
    )
    if span_id is not None:
        kwargs["span_id"] = span_id
    span = Span(**kwargs)
    span.set_attributes(attributes)
    return _finish(span)


def _llm_attrs(
    system: str,
    model: str,
    operation: str,
    input_tokens: int,
    output_tokens: int,
    ttft_ms: Optional[float] = None,
) -> dict:
    attrs = {
        semconv.GEN_AI_SYSTEM: system,
        semconv.GEN_AI_OPERATION_NAME: operation,
        semconv.GEN_AI_REQUEST_MODEL: model,
        semconv.GEN_AI_RESPONSE_MODEL: model,
        semconv.GEN_AI_USAGE_INPUT_TOKENS: input_tokens,
        semconv.GEN_AI_USAGE_OUTPUT_TOKENS: output_tokens,
    }
    cost = compute_cost(model, input_tokens=input_tokens, output_tokens=output_tokens, system=system)
    if cost is None:
        attrs[semconv.TRACEMETER_COST_UNKNOWN] = True
    else:
        attrs[semconv.TRACEMETER_COST_USD] = cost
    if ttft_ms is not None:
        attrs[semconv.TRACEMETER_TTFT_MS] = ttft_ms
    return attrs


def _rag_pipeline(rng: random.Random, trace_id: str, t0: float, model: str) -> list[Span]:
    root_id = _new_id()
    cursor = t0

    d = rng.uniform(0.05, 0.15)
    retrieve = _span(trace_id, root_id, "retrieve_docs", cursor, d, {})
    cursor += d

    d = rng.uniform(0.05, 0.2)
    embed = _span(
        trace_id, root_id, "openai.embeddings", cursor, d,
        _llm_attrs("openai", "text-embedding-3-small", semconv.OPERATION_EMBEDDINGS, rng.randint(20, 60), 0),
    )
    cursor += d

    d = rng.uniform(0.8, 2.4) if model == "gpt-4o" else rng.uniform(0.3, 1.0)
    generate = _span(
        trace_id, root_id, "openai.chat", cursor, d,
        _llm_attrs("openai", model, semconv.OPERATION_CHAT, rng.randint(800, 2200), rng.randint(150, 500)),
    )
    cursor += d

    root = _span(trace_id, None, "rag_pipeline", t0, cursor - t0, {}, span_id=root_id)
    return [root, retrieve, embed, generate]


def _summarize_doc(rng: random.Random, trace_id: str, t0: float) -> list[Span]:
    root_id = _new_id()
    d = rng.uniform(0.4, 1.1)
    child = _span(
        trace_id, root_id, "anthropic.chat", t0, d,
        _llm_attrs("anthropic", "claude-haiku-4-5", semconv.OPERATION_CHAT, rng.randint(500, 1500), rng.randint(40, 120)),
    )
    root = _span(trace_id, None, "summarize_doc", t0, d, {}, span_id=root_id)
    return [root, child]


def _agent_run(rng: random.Random, trace_id: str, t0: float, fail: bool) -> list[Span]:
    root_id = _new_id()
    cursor = t0

    d = rng.uniform(0.4, 1.2)
    plan = _span(
        trace_id, root_id, "anthropic.chat", cursor, d,
        _llm_attrs("anthropic", "claude-sonnet-4-5", semconv.OPERATION_CHAT, rng.randint(300, 900), rng.randint(80, 250)),
    )
    cursor += d

    d = rng.uniform(0.1, 0.5)
    if fail:
        tool_call = _span(
            trace_id, root_id, "call_tool_calculator", cursor, d, {},
            status="error", error_message="RuntimeError: tool timed out after 5s",
        )
        cursor += d
        root = _span(
            trace_id, None, "agent_run", t0, cursor - t0, {}, span_id=root_id,
            status="error", error_message="RuntimeError: tool timed out after 5s",
        )
        return [root, plan, tool_call]

    tool_call = _span(trace_id, root_id, "call_tool_calculator", cursor, d, {})
    cursor += d

    d = rng.uniform(0.3, 0.9)
    synthesize = _span(
        trace_id, root_id, "openai.chat", cursor, d,
        _llm_attrs("openai", "gpt-4o-mini", semconv.OPERATION_CHAT, rng.randint(400, 1000), rng.randint(100, 300)),
    )
    cursor += d

    root = _span(trace_id, None, "agent_run", t0, cursor - t0, {}, span_id=root_id)
    return [root, plan, tool_call, synthesize]


def _chatbot_reply(rng: random.Random, trace_id: str, t0: float) -> list[Span]:
    """Routed through LangChain rather than a direct SDK client -- system
    stays "langchain" (its callback handler's fallback tag) rather than the
    underlying provider, demonstrating that integration alongside the
    direct-SDK ones."""
    root_id = _new_id()
    d = rng.uniform(0.3, 0.9)
    child = _span(
        trace_id, root_id, "langchain.chat", t0, d,
        _llm_attrs("langchain", "gpt-4o-mini", semconv.OPERATION_CHAT, rng.randint(200, 700), rng.randint(60, 200)),
    )
    root = _span(trace_id, None, "chatbot_reply", t0, d, {}, span_id=root_id)
    return [root, child]


def _streaming_summary(rng: random.Random, trace_id: str, t0: float) -> list[Span]:
    root_id = _new_id()
    d = rng.uniform(1.0, 2.5)
    child = _span(
        trace_id, root_id, "openai.chat", t0, d,
        _llm_attrs(
            "openai", "gpt-4o-mini", semconv.OPERATION_CHAT,
            rng.randint(300, 900), rng.randint(150, 500), ttft_ms=rng.uniform(120, 400),
        ),
    )
    root = _span(trace_id, None, "streaming_summary", t0, d, {}, span_id=root_id)
    return [root, child]


def _unknown_model_call(rng: random.Random, trace_id: str, t0: float) -> list[Span]:
    """A locally-hosted model with no entry in prices.json -- shows the
    pricing engine failing open (cost "unknown") instead of guessing."""
    d = rng.uniform(0.3, 0.8)
    span = _span(
        trace_id, None, "local_llama_call", t0, d,
        _llm_attrs("litellm", "llama-3.1-70b-instruct-local", semconv.OPERATION_CHAT, rng.randint(200, 600), rng.randint(50, 200)),
    )
    return [span]


def populate_demo_data(store: SqliteStore, seed: int = 42) -> DemoSummary:
    """Writes ~14 days of synthetic pipeline runs directly to `store` and
    returns a summary. Deterministic for a given seed, so `tracemeter demo`
    (and its README/launch-post screenshots) look the same every run."""
    rng = random.Random(seed)
    now = time.time()
    spans: list[Span] = []

    for day_offset in range(_DAYS_OF_HISTORY, 0, -1):
        day_start = now - day_offset * 86400
        model = "gpt-4o" if day_offset > _DAYS_OF_HISTORY / 2 else "gpt-4o-mini"

        for _ in range(rng.randint(*_RUNS_PER_DAY)):
            spans += _rag_pipeline(rng, _new_id(), day_start + rng.uniform(0, 86400), model)
        if rng.random() < 0.6:
            spans += _summarize_doc(rng, _new_id(), day_start + rng.uniform(0, 86400))
        if rng.random() < 0.65:
            spans += _agent_run(rng, _new_id(), day_start + rng.uniform(0, 86400), fail=rng.random() < 0.25)
        if rng.random() < 0.4:
            spans += _chatbot_reply(rng, _new_id(), day_start + rng.uniform(0, 86400))
        if rng.random() < 0.3:
            spans += _streaming_summary(rng, _new_id(), day_start + rng.uniform(0, 86400))
        if rng.random() < 0.15:
            spans += _unknown_model_call(rng, _new_id(), day_start + rng.uniform(0, 86400))

    for span in spans:
        store.write_span(span)

    trace_ids = {s.trace_id for s in spans}
    total_cost = sum(s.attributes.get(semconv.TRACEMETER_COST_USD) or 0.0 for s in spans)
    return DemoSummary(trace_count=len(trace_ids), span_count=len(spans), total_cost_usd=total_cost)
