import pytest

from tracemeter.compare import compare_traces
from tracemeter.storage.sqlite_store import SqliteStore
from tracemeter.tracer import Tracer


@pytest.fixture
def two_traces(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    tracer = Tracer(store=store)

    with tracer.span("prompt_v1") as a:
        with tracer.span("retrieve") as s:
            s.set_attribute("tracemeter.cost.usd", 0.0)
        with tracer.span("call_model") as s:
            s.set_attribute("tracemeter.cost.usd", 0.01)

    with tracer.span("prompt_v2") as b:
        with tracer.span("retrieve") as s:
            s.set_attribute("tracemeter.cost.usd", 0.0)
        with tracer.span("call_model") as s:
            s.set_attribute("tracemeter.cost.usd", 0.02)
        with tracer.span("extra_validation_step") as s:
            s.set_attribute("tracemeter.cost.usd", 0.005)

    return store, a.trace_id, b.trace_id


def test_compare_totals(two_traces):
    store, trace_a, trace_b = two_traces
    result = compare_traces(store, trace_a, trace_b)

    assert result["a"]["trace_id"] == trace_a
    assert result["b"]["trace_id"] == trace_b
    assert round(result["a"]["cost_usd"], 4) == 0.01
    assert round(result["b"]["cost_usd"], 4) == 0.025
    assert round(result["delta"]["cost_usd"], 4) == 0.015


def test_compare_steps_matched_by_name(two_traces):
    store, trace_a, trace_b = two_traces
    result = compare_traces(store, trace_a, trace_b)
    steps = {s["name"]: s for s in result["steps"]}

    assert round(steps["call_model"]["cost_delta_usd"], 4) == 0.01
    assert steps["call_model"]["only_in"] is None


def test_compare_step_only_in_one_trace(two_traces):
    store, trace_a, trace_b = two_traces
    result = compare_traces(store, trace_a, trace_b)
    steps = {s["name"]: s for s in result["steps"]}

    assert steps["extra_validation_step"]["only_in"] == "b"
    assert steps["extra_validation_step"]["a_cost_usd"] == 0.0
