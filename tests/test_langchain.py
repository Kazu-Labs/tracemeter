"""Tests the LangChain callback handler against real langchain_core message/
result types, so the shapes match what a real chat model integration would
pass in. Requires the `langchain` extra; skipped otherwise."""

import pytest

pytest.importorskip("langchain_core")

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from tracemeter.integrations.langchain_wrap import TraceMeterCallbackHandler
from tracemeter.storage.sqlite_store import SqliteStore
from tracemeter.tracer import Tracer

OPENAI_SERIALIZED = {"id": ["langchain_openai", "chat_models", "base", "ChatOpenAI"], "kwargs": {}}
ANTHROPIC_SERIALIZED = {"id": ["langchain_anthropic", "chat_models", "ChatAnthropic"], "kwargs": {}}


def make_handler(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    tracer = Tracer(store=store)
    return TraceMeterCallbackHandler(tracer=tracer), store


def test_chat_model_records_span_and_cost(tmp_path):
    handler, store = make_handler(tmp_path)
    run_id = "11111111-1111-1111-1111-111111111111"

    handler.on_chat_model_start(
        OPENAI_SERIALIZED,
        [[]],
        run_id=run_id,
        invocation_params={"model": "gpt-4o-mini"},
    )
    message = AIMessage(content="hi", usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150})
    result = LLMResult(generations=[[ChatGeneration(message=message)]])
    handler.on_llm_end(result, run_id=run_id)

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


def test_extracts_system_from_serialized_id(tmp_path):
    handler, store = make_handler(tmp_path)
    run_id = "22222222-2222-2222-2222-222222222222"

    handler.on_chat_model_start(
        ANTHROPIC_SERIALIZED,
        [[]],
        run_id=run_id,
        invocation_params={"model": "claude-3-5-sonnet-20241022"},
    )
    message = AIMessage(content="hi", usage_metadata={"input_tokens": 200, "output_tokens": 80, "total_tokens": 280})
    result = LLMResult(generations=[[ChatGeneration(message=message)]])
    handler.on_llm_end(result, run_id=run_id)

    spans = store.get_trace_spans(store.list_traces()[0]["trace_id"])
    assert spans[0]["attributes"]["gen_ai.system"] == "anthropic"


def test_falls_back_to_token_usage_llm_output(tmp_path):
    handler, store = make_handler(tmp_path)
    run_id = "33333333-3333-3333-3333-333333333333"

    handler.on_llm_start(
        {"id": ["some", "other", "provider"], "kwargs": {}},
        ["prompt"],
        run_id=run_id,
        invocation_params={"model": "some-model"},
    )
    result = LLMResult(
        generations=[[]],
        llm_output={"token_usage": {"prompt_tokens": 30, "completion_tokens": 10}},
    )
    handler.on_llm_end(result, run_id=run_id)

    spans = store.get_trace_spans(store.list_traces()[0]["trace_id"])
    attrs = spans[0]["attributes"]
    assert attrs["gen_ai.system"] == "langchain"
    assert attrs["gen_ai.usage.input_tokens"] == 30
    assert attrs["gen_ai.usage.output_tokens"] == 10


def test_records_error(tmp_path):
    handler, store = make_handler(tmp_path)
    run_id = "44444444-4444-4444-4444-444444444444"

    handler.on_chat_model_start(
        OPENAI_SERIALIZED, [[]], run_id=run_id, invocation_params={"model": "gpt-4o-mini"}
    )
    handler.on_llm_error(RuntimeError("rate limited"), run_id=run_id)

    spans = store.get_trace_spans(store.list_traces()[0]["trace_id"])
    assert spans[0]["status"] == "error"
    assert "rate limited" in spans[0]["error_message"]


def test_new_token_sets_ttft(tmp_path):
    handler, store = make_handler(tmp_path)
    run_id = "55555555-5555-5555-5555-555555555555"

    handler.on_chat_model_start(
        OPENAI_SERIALIZED, [[]], run_id=run_id, invocation_params={"model": "gpt-4o-mini"}
    )
    handler.on_llm_new_token("hel", run_id=run_id)
    handler.on_llm_new_token("lo", run_id=run_id)  # second call must not overwrite TTFT
    message = AIMessage(content="hello", usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7})
    handler.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=run_id)

    spans = store.get_trace_spans(store.list_traces()[0]["trace_id"])
    assert "tracemeter.ttft_ms" in spans[0]["attributes"]
