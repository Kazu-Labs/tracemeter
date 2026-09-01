"""Tests the LlamaIndex callback handler against real llama_index.core
event/payload types. Requires the `llamaindex` extra (Python 3.10+,
matching llama-index-core's own floor); skipped otherwise."""

import sys
from types import SimpleNamespace

import pytest

if sys.version_info < (3, 10):
    pytest.skip("llama-index-core requires Python 3.10+", allow_module_level=True)

pytest.importorskip("llama_index.core")

from llama_index.core.base.llms.types import ChatMessage, ChatResponse
from llama_index.core.callbacks.schema import CBEventType, EventPayload

from tracemeter.integrations.llamaindex_wrap import TraceMeterCallbackHandler
from tracemeter.storage.sqlite_store import SqliteStore
from tracemeter.tracer import Tracer

OPENAI_SERIALIZED = {"class_name": "openai_llm", "model": "gpt-4o-mini"}
ANTHROPIC_SERIALIZED = {"class_name": "anthropic_llm", "model": "claude-3-5-sonnet-20241022"}


def make_handler(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    tracer = Tracer(store=store)
    return TraceMeterCallbackHandler(tracer=tracer), store


def test_llm_event_records_span_and_cost(tmp_path):
    handler, store = make_handler(tmp_path)

    event_id = handler.on_event_start(CBEventType.LLM, {EventPayload.SERIALIZED: OPENAI_SERIALIZED})
    raw = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50))
    response = ChatResponse(message=ChatMessage(role="assistant", content="hi"), raw=raw)
    handler.on_event_end(CBEventType.LLM, {EventPayload.RESPONSE: response}, event_id=event_id)

    traces = store.list_traces()
    assert len(traces) == 1
    spans = store.get_trace_spans(traces[0]["trace_id"])
    attrs = spans[0]["attributes"]
    assert attrs["gen_ai.system"] == "openai"
    assert attrs["gen_ai.request.model"] == "gpt-4o-mini"
    assert attrs["gen_ai.usage.input_tokens"] == 100
    assert attrs["gen_ai.usage.output_tokens"] == 50
    expected_cost = (100 / 1_000_000) * 0.15 + (50 / 1_000_000) * 0.60
    assert attrs["tracemeter.cost.usd"] == round(expected_cost, 8)


def test_extracts_system_from_class_name(tmp_path):
    handler, store = make_handler(tmp_path)

    event_id = handler.on_event_start(CBEventType.LLM, {EventPayload.SERIALIZED: ANTHROPIC_SERIALIZED})
    raw = SimpleNamespace(usage=SimpleNamespace(input_tokens=200, output_tokens=80))
    response = ChatResponse(message=ChatMessage(role="assistant", content="hi"), raw=raw)
    handler.on_event_end(CBEventType.LLM, {EventPayload.RESPONSE: response}, event_id=event_id)

    spans = store.get_trace_spans(store.list_traces()[0]["trace_id"])
    assert spans[0]["attributes"]["gen_ai.system"] == "anthropic"


def test_ignores_non_llm_embedding_events(tmp_path):
    handler, store = make_handler(tmp_path)

    event_id = handler.on_event_start(CBEventType.RETRIEVE, {})
    handler.on_event_end(CBEventType.RETRIEVE, {}, event_id=event_id)

    assert store.list_traces() == []


def test_records_error(tmp_path):
    handler, store = make_handler(tmp_path)

    event_id = handler.on_event_start(CBEventType.LLM, {EventPayload.SERIALIZED: OPENAI_SERIALIZED})
    handler.on_event_end(
        CBEventType.LLM, {EventPayload.EXCEPTION: RuntimeError("rate limited")}, event_id=event_id
    )

    spans = store.get_trace_spans(store.list_traces()[0]["trace_id"])
    assert spans[0]["status"] == "error"
    assert "rate limited" in spans[0]["error_message"]


def test_unknown_model_reports_cost_unknown(tmp_path):
    handler, store = make_handler(tmp_path)

    event_id = handler.on_event_start(
        CBEventType.LLM, {EventPayload.SERIALIZED: {"class_name": "some_other_llm", "model": "mystery-model"}}
    )
    raw = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))
    response = ChatResponse(message=ChatMessage(role="assistant", content="hi"), raw=raw)
    handler.on_event_end(CBEventType.LLM, {EventPayload.RESPONSE: response}, event_id=event_id)

    spans = store.get_trace_spans(store.list_traces()[0]["trace_id"])
    attrs = spans[0]["attributes"]
    assert attrs["gen_ai.system"] == "llamaindex"
    assert attrs["tracemeter.cost.unknown"] is True
