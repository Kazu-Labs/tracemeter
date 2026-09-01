from tracemeter import semconv
from tracemeter.demo import populate_demo_data
from tracemeter.storage.sqlite_store import SqliteStore


def test_populate_demo_data_seeds_plausible_traces(tmp_path):
    store = SqliteStore(tmp_path / "demo.db")
    summary = populate_demo_data(store)

    assert summary.trace_count > 20
    assert summary.span_count > summary.trace_count  # most traces have nested spans
    assert summary.total_cost_usd > 0

    traces = store.list_traces(limit=1000)
    assert len(traces) == summary.trace_count


def test_populate_demo_data_is_deterministic(tmp_path):
    store_a = SqliteStore(tmp_path / "a.db")
    store_b = SqliteStore(tmp_path / "b.db")
    summary_a = populate_demo_data(store_a, seed=7)
    summary_b = populate_demo_data(store_b, seed=7)
    assert summary_a == summary_b


def test_populate_demo_data_covers_error_unknown_cost_and_ttft(tmp_path):
    store = SqliteStore(tmp_path / "demo.db")
    populate_demo_data(store)

    all_spans = store.export_spans()
    assert any(s["status"] == "error" for s in all_spans)
    assert any(s["attributes"].get(semconv.TRACEMETER_COST_UNKNOWN) for s in all_spans)
    assert any(semconv.TRACEMETER_TTFT_MS in s["attributes"] for s in all_spans)
    assert any(s["attributes"].get("gen_ai.system") == "langchain" for s in all_spans)


def test_run_comparison_has_something_to_compare(tmp_path):
    """rag_pipeline should span both the gpt-4o and gpt-4o-mini eras, so
    the run-comparison feature has a real before/after to show."""
    store = SqliteStore(tmp_path / "demo.db")
    populate_demo_data(store)

    rag_traces = [t for t in store.list_traces(limit=1000) if t["name"] == "rag_pipeline"]
    models = set()
    for t in rag_traces:
        for s in store.get_trace_spans(t["trace_id"]):
            model = s["attributes"].get("gen_ai.request.model")
            if model:
                models.add(model)
    assert {"gpt-4o", "gpt-4o-mini"} <= models
