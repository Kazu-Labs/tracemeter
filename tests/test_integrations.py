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


# AsyncOpenAI/AsyncAnthropic use the same wrapper against `async def` client
# methods -- covered separately since a coroutine function is instrumented
# through a different branch of instrument_create_method than a sync one.


async def test_instrument_openai_async_records_span_and_cost(tmp_path):
    tracer, store = make_tracer(tmp_path)

    class AsyncFakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                model="gpt-4o-mini",
                usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=AsyncFakeCompletions()))
    instrument_openai(client, tracer=tracer)

    response = await client.chat.completions.create(model="gpt-4o-mini", messages=[])
    assert response.usage.prompt_tokens == 100

    traces = store.list_traces()
    assert len(traces) == 1
    attrs = store.get_trace_spans(traces[0]["trace_id"])[0]["attributes"]
    expected_cost = (100 / 1_000_000) * 0.15 + (50 / 1_000_000) * 0.60
    assert attrs["tracemeter.cost.usd"] == round(expected_cost, 8)


async def test_instrument_openai_async_records_error(tmp_path):
    tracer, store = make_tracer(tmp_path)

    class FailingAsyncCompletions:
        async def create(self, **kwargs):
            raise RuntimeError("rate limited")

    client = SimpleNamespace(chat=SimpleNamespace(completions=FailingAsyncCompletions()))
    instrument_openai(client, tracer=tracer)

    try:
        await client.chat.completions.create(model="gpt-4o-mini", messages=[])
    except RuntimeError:
        pass

    spans = store.get_trace_spans(store.list_traces()[0]["trace_id"])
    assert spans[0]["status"] == "error"
    assert "rate limited" in spans[0]["error_message"]


async def test_instrument_openai_async_streaming(tmp_path):
    """Regression test: AsyncOpenAI-style streaming returns an async
    iterator (`__anext__`/`StopAsyncIteration`), not a sync one -- the
    wrapper needs its own async iteration protocol rather than reusing the
    sync wrapper's `__next__`, which would raise TypeError against it."""
    tracer, store = make_tracer(tmp_path)

    class AsyncStreamCompletions:
        async def create(self, **kwargs):
            async def gen():
                yield SimpleNamespace(choices=[], usage=None)
                yield SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                )

            return gen()

    client = SimpleNamespace(chat=SimpleNamespace(completions=AsyncStreamCompletions()))
    instrument_openai(client, tracer=tracer)

    stream = await client.chat.completions.create(model="gpt-4o-mini", messages=[], stream=True)
    chunks = [chunk async for chunk in stream]
    assert len(chunks) == 2

    traces = store.list_traces()
    attrs = store.get_trace_spans(traces[0]["trace_id"])[0]["attributes"]
    assert attrs["gen_ai.usage.input_tokens"] == 10
    assert attrs["gen_ai.usage.output_tokens"] == 5
    assert "tracemeter.ttft_ms" in attrs


async def test_instrument_anthropic_async_records_span_and_cost(tmp_path):
    tracer, store = make_tracer(tmp_path)

    class AsyncFakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(
                model=kwargs.get("model"),
                usage=SimpleNamespace(input_tokens=200, output_tokens=80),
            )

    client = SimpleNamespace(messages=AsyncFakeMessages())
    instrument_anthropic(client, tracer=tracer)

    await client.messages.create(model="claude-3-5-sonnet-20241022", messages=[])

    attrs = store.get_trace_spans(store.list_traces()[0]["trace_id"])[0]["attributes"]
    assert attrs["gen_ai.usage.input_tokens"] == 200
    assert attrs["gen_ai.usage.output_tokens"] == 80


async def test_instrument_litellm_async_records_span_and_cost(tmp_path):
    tracer, store = make_tracer(tmp_path)

    async def acompletion(**kwargs):
        return SimpleNamespace(
            model=kwargs.get("model"),
            usage={"prompt_tokens": 300, "completion_tokens": 120},
        )

    fake_litellm = SimpleNamespace(
        completion=lambda **kwargs: None,
        acompletion=acompletion,
    )
    instrument_litellm(fake_litellm, tracer=tracer)

    await fake_litellm.acompletion(model="gpt-4o-mini", messages=[])

    attrs = store.get_trace_spans(store.list_traces()[0]["trace_id"])[0]["attributes"]
    assert attrs["gen_ai.system"] == "litellm"
    assert attrs["gen_ai.usage.input_tokens"] == 300
    assert attrs["gen_ai.usage.output_tokens"] == 120
