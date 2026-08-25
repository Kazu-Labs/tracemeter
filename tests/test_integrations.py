"""Tests instrumentation against fake clients shaped like the real SDKs,
so the test suite doesn't need `openai`/`anthropic` installed."""

from types import SimpleNamespace

from tracemeter.integrations.anthropic_wrap import instrument_anthropic
from tracemeter.integrations.litellm_wrap import instrument_litellm
from tracemeter.integrations.openai_wrap import instrument_openai
from tracemeter.storage.sqlite_store import SqliteStore
from tracemeter.tracer import Tracer


class FakeCompletions:
    def create(self, **kwargs):
        return SimpleNamespace(
            model="gpt-4o-mini",
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        )


class FakeOpenAIClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


class FakeMessages:
    def create(self, **kwargs):
        return SimpleNamespace(
            model=kwargs.get("model"),
            usage=SimpleNamespace(input_tokens=200, output_tokens=80),
        )


class FakeAnthropicClient:
    def __init__(self):
        self.messages = FakeMessages()


def make_tracer(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    return Tracer(store=store), store


def test_instrument_openai_records_span_and_cost(tmp_path):
    tracer, store = make_tracer(tmp_path)
    client = FakeOpenAIClient()
    instrument_openai(client, tracer=tracer)

    response = client.chat.completions.create(model="gpt-4o-mini", messages=[])
    assert response.usage.prompt_tokens == 100

    traces = store.list_traces()
    assert len(traces) == 1
    spans = store.get_trace_spans(traces[0]["trace_id"])
    assert len(spans) == 1
    attrs = spans[0]["attributes"]
    assert attrs["gen_ai.system"] == "openai"
    assert attrs["gen_ai.request.model"] == "gpt-4o-mini"
    assert attrs["gen_ai.usage.input_tokens"] == 100
    assert attrs["gen_ai.usage.output_tokens"] == 50
    expected_cost = (100 / 1_000_000) * 0.15 + (50 / 1_000_000) * 0.60
    assert attrs["tracemeter.cost.usd"] == round(expected_cost, 8)


def test_instrument_openai_is_idempotent(tmp_path):
    tracer, store = make_tracer(tmp_path)
    client = FakeOpenAIClient()
    instrument_openai(client, tracer=tracer)
    instrument_openai(client, tracer=tracer)  # should not double-wrap

    client.chat.completions.create(model="gpt-4o-mini", messages=[])
    traces = store.list_traces()
    assert len(traces) == 1  # not double-recorded


def test_instrument_anthropic_records_span_and_cost(tmp_path):
    tracer, store = make_tracer(tmp_path)
    client = FakeAnthropicClient()
    instrument_anthropic(client, tracer=tracer)

    client.messages.create(model="claude-3-5-sonnet-20241022", messages=[])

    traces = store.list_traces()
    spans = store.get_trace_spans(traces[0]["trace_id"])
    attrs = spans[0]["attributes"]
    assert attrs["gen_ai.system"] == "anthropic"
    assert attrs["gen_ai.usage.input_tokens"] == 200
    assert attrs["gen_ai.usage.output_tokens"] == 80
    expected_cost = (200 / 1_000_000) * 3.00 + (80 / 1_000_000) * 15.00
    assert attrs["tracemeter.cost.usd"] == round(expected_cost, 8)


def test_instrument_openai_records_error(tmp_path):
    tracer, store = make_tracer(tmp_path)

    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("rate limited")

    client = SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions()))
    instrument_openai(client, tracer=tracer)

    try:
        client.chat.completions.create(model="gpt-4o-mini", messages=[])
    except RuntimeError:
        pass

    traces = store.list_traces()
    spans = store.get_trace_spans(traces[0]["trace_id"])
    assert spans[0]["status"] == "error"
    assert "rate limited" in spans[0]["error_message"]


def test_instrument_litellm_records_span_and_cost(tmp_path):
    tracer, store = make_tracer(tmp_path)

    fake_litellm = SimpleNamespace(
        completion=lambda **kwargs: SimpleNamespace(
            model=kwargs.get("model"),
            usage={"prompt_tokens": 300, "completion_tokens": 120},
        )
    )
    instrument_litellm(fake_litellm, tracer=tracer)

    fake_litellm.completion(model="gpt-4o-mini", messages=[])

    traces = store.list_traces()
    spans = store.get_trace_spans(traces[0]["trace_id"])
    attrs = spans[0]["attributes"]
    assert attrs["gen_ai.system"] == "litellm"
    assert attrs["gen_ai.usage.input_tokens"] == 300
    assert attrs["gen_ai.usage.output_tokens"] == 120
    expected_cost = (300 / 1_000_000) * 0.15 + (120 / 1_000_000) * 0.60
    assert attrs["tracemeter.cost.usd"] == round(expected_cost, 8)


def test_instrument_openai_streaming(tmp_path):
    tracer, store = make_tracer(tmp_path)

    class StreamCompletions:
        def create(self, **kwargs):
            def gen():
                yield SimpleNamespace(choices=[], usage=None)
                yield SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                )

            return gen()

    client = SimpleNamespace(chat=SimpleNamespace(completions=StreamCompletions()))
    instrument_openai(client, tracer=tracer)

    chunks = list(client.chat.completions.create(model="gpt-4o-mini", messages=[], stream=True))
    assert len(chunks) == 2

    traces = store.list_traces()
    spans = store.get_trace_spans(traces[0]["trace_id"])
    attrs = spans[0]["attributes"]
    assert attrs["gen_ai.usage.input_tokens"] == 10
    assert attrs["gen_ai.usage.output_tokens"] == 5
    assert "tracemeter.ttft_ms" in attrs
