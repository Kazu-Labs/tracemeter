import time

from tracemeter.storage.sqlite_store import SqliteStore
from tracemeter.tracer import Tracer


def make_tracer(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    return Tracer(store=store), store


def test_span_records_basic_fields(tmp_path):
    tracer, store = make_tracer(tmp_path)
    with tracer.span("root") as s:
        time.sleep(0.01)
        s.set_attribute("gen_ai.request.model", "gpt-4o")

    row = store.get_span(s.span_id)
    assert row is not None
    assert row["name"] == "root"
    assert row["parent_span_id"] is None
    assert row["attributes"]["gen_ai.request.model"] == "gpt-4o"
    assert row["attributes"]["tracemeter.latency_ms"] >= 10


def test_nested_spans_share_trace_id(tmp_path):
    tracer, store = make_tracer(tmp_path)
    with tracer.span("parent") as parent:
        with tracer.span("child") as child:
            pass

    assert child.trace_id == parent.trace_id
    assert child.parent_span_id == parent.span_id

    spans = store.get_trace_spans(parent.trace_id)
    assert {s["name"] for s in spans} == {"parent", "child"}


def test_span_records_exception(tmp_path):
    tracer, store = make_tracer(tmp_path)
    try:
        with tracer.span("failing") as s:
            raise ValueError("boom")
    except ValueError:
        pass

    row = store.get_span(s.span_id)
    assert row["status"] == "error"
    assert "boom" in row["error_message"]


def test_trace_decorator(tmp_path):
    tracer, store = make_tracer(tmp_path)

    @tracer.trace("my_step")
    def step(x):
        return x + 1

    assert step(1) == 2

    traces = store.list_traces()
    assert len(traces) == 1
    assert traces[0]["name"] == "my_step"
