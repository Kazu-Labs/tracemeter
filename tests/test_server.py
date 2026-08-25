import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from tracemeter.pricing.engine import compute_cost
from tracemeter.server.app import create_app
from tracemeter.storage.sqlite_store import SqliteStore
from tracemeter.tracer import Tracer


@pytest.fixture
def client(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    tracer = Tracer(store=store)
    with tracer.span("pipeline") as root:
        with tracer.span("call_model") as child:
            child.set_attribute("gen_ai.request.model", "gpt-4o-mini")
            child.set_attribute("gen_ai.usage.input_tokens", 1000)
            child.set_attribute("gen_ai.usage.output_tokens", 500)
            cost = compute_cost("gpt-4o-mini", input_tokens=1000, output_tokens=500)
            child.set_attribute("tracemeter.cost.usd", cost)

    app = create_app(store=store)
    return TestClient(app), root.trace_id


def test_index_serves_html(client):
    c, _ = client
    res = c.get("/")
    assert res.status_code == 200
    assert "TraceMeter" in res.text


def test_list_traces(client):
    c, trace_id = client
    res = c.get("/api/traces")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["trace_id"] == trace_id
    assert data[0]["span_count"] == 2
    assert data[0]["total_cost_usd"] > 0


def test_get_trace_detail(client):
    c, trace_id = client
    res = c.get(f"/api/traces/{trace_id}")
    assert res.status_code == 200
    data = res.json()
    assert len(data["spans"]) == 2


def test_get_trace_not_found(client):
    c, _ = client
    res = c.get("/api/traces/does-not-exist")
    assert res.status_code == 404


def test_cost_summary(client):
    c, _ = client
    res = c.get("/api/cost_summary?group_by=model")
    assert res.status_code == 200
    data = res.json()
    assert data[0]["key"] == "gpt-4o-mini"
    assert data[0]["call_count"] == 1


def test_export_json(client):
    c, _ = client
    res = c.get("/api/export?format=json")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_export_csv(client):
    c, _ = client
    res = c.get("/api/export?format=csv")
    assert res.status_code == 200
    assert "span_id" in res.text.splitlines()[0]


def test_compare_endpoint(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    tracer = Tracer(store=store)
    with tracer.span("run_a") as a:
        with tracer.span("step") as s:
            s.set_attribute("tracemeter.cost.usd", 0.01)
    with tracer.span("run_b") as b:
        with tracer.span("step") as s:
            s.set_attribute("tracemeter.cost.usd", 0.02)

    app = create_app(store=store)
    c = TestClient(app)
    res = c.get(f"/api/compare?trace_a={a.trace_id}&trace_b={b.trace_id}")
    assert res.status_code == 200
    data = res.json()
    assert round(data["delta"]["cost_usd"], 4) == 0.01


def test_compare_endpoint_missing_trace(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    app = create_app(store=store)
    c = TestClient(app)
    res = c.get("/api/compare?trace_a=doesnotexist&trace_b=alsomissing")
    assert res.status_code == 404
