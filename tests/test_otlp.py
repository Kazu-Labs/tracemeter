import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from tracemeter.server.app import create_app
from tracemeter.server.otlp import parse_export_request_json
from tracemeter.storage.sqlite_store import SqliteStore

TRACE_ID_HEX = "4bf92f3577b34da6a3ce929d0e0e4736"
ROOT_SPAN_ID_HEX = "00f067aa0ba902b7"
CHILD_SPAN_ID_HEX = "00f067aa0ba902b8"


def _sample_payload():
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [
                    {
                        "scope": {"name": "some-otel-instrumented-app"},
                        "spans": [
                            {
                                "traceId": TRACE_ID_HEX,
                                "spanId": ROOT_SPAN_ID_HEX,
                                "name": "pipeline_run",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000500000000",
                                "attributes": [],
                                "status": {"code": 0},
                            },
                            {
                                "traceId": TRACE_ID_HEX,
                                "spanId": CHILD_SPAN_ID_HEX,
                                "parentSpanId": ROOT_SPAN_ID_HEX,
                                "name": "chat gpt-4o-mini",
                                "startTimeUnixNano": "1700000000100000000",
                                "endTimeUnixNano": "1700000000400000000",
                                "attributes": [
                                    {"key": "gen_ai.system", "value": {"stringValue": "openai"}},
                                    {
                                        "key": "gen_ai.request.model",
                                        "value": {"stringValue": "gpt-4o-mini"},
                                    },
                                    {
                                        "key": "gen_ai.usage.input_tokens",
                                        "value": {"intValue": "1000"},
                                    },
                                    {
                                        "key": "gen_ai.usage.output_tokens",
                                        "value": {"intValue": "500"},
                                    },
                                ],
                                "status": {"code": 0},
                            },
                        ],
                    }
                ],
            }
        ]
    }


def test_parse_export_request_extracts_spans_and_hierarchy():
    spans = parse_export_request_json(_sample_payload())
    assert len(spans) == 2

    root = next(s for s in spans if s.name == "pipeline_run")
    child = next(s for s in spans if s.name == "chat gpt-4o-mini")

    assert root.trace_id == TRACE_ID_HEX
    assert root.parent_span_id is None
    assert child.trace_id == TRACE_ID_HEX
    assert child.parent_span_id == ROOT_SPAN_ID_HEX
    assert abs(root.start_time - 1700000000.0) < 1e-6
    assert abs(root.end_time - 1700000000.5) < 1e-6


def test_parse_export_request_computes_cost_from_usage_attrs():
    spans = parse_export_request_json(_sample_payload())
    child = next(s for s in spans if s.name == "chat gpt-4o-mini")
    expected_cost = (1000 / 1_000_000) * 0.15 + (500 / 1_000_000) * 0.60
    assert child.attributes["tracemeter.cost.usd"] == round(expected_cost, 8)


def test_ingest_endpoint_writes_to_store(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    app = create_app(store=store)
    client = TestClient(app)

    res = client.post("/v1/traces", json=_sample_payload())
    assert res.status_code == 200
    assert res.json()["spans_written"] == 2

    traces = store.list_traces()
    assert len(traces) == 1
    assert traces[0]["trace_id"] == TRACE_ID_HEX
    assert traces[0]["span_count"] == 2
    assert traces[0]["total_cost_usd"] > 0


def test_ingest_endpoint_rejects_malformed_payload(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    app = create_app(store=store)
    client = TestClient(app)

    res = client.post("/v1/traces", json={"resourceSpans": [{"scopeSpans": "not-a-list"}]})
    assert res.status_code == 400


otel_proto = pytest.importorskip("opentelemetry.proto.collector.trace.v1.trace_service_pb2")


def _sample_payload_protobuf():
    """Builds the protobuf-encoded equivalent of _sample_payload() using
    opentelemetry-proto directly, so this test exercises the actual wire
    format mainstream OTel exporters send (verified against a real
    opentelemetry-sdk export during development -- JSON alone does not
    interoperate with the default Python OTLP/HTTP exporter)."""
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )
    from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
    from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, Status

    request = ExportTraceServiceRequest()
    resource_spans = request.resource_spans.add()
    scope_spans = resource_spans.scope_spans.add()

    root = scope_spans.spans.add()
    root.trace_id = bytes.fromhex(TRACE_ID_HEX)
    root.span_id = bytes.fromhex(ROOT_SPAN_ID_HEX)
    root.name = "pipeline_run"
    root.start_time_unix_nano = 1700000000000000000
    root.end_time_unix_nano = 1700000000500000000
    root.status.code = Status.STATUS_CODE_OK

    child = scope_spans.spans.add()
    child.trace_id = bytes.fromhex(TRACE_ID_HEX)
    child.span_id = bytes.fromhex(CHILD_SPAN_ID_HEX)
    child.parent_span_id = bytes.fromhex(ROOT_SPAN_ID_HEX)
    child.name = "chat gpt-4o-mini"
    child.start_time_unix_nano = 1700000000100000000
    child.end_time_unix_nano = 1700000000400000000
    child.status.code = Status.STATUS_CODE_OK
    child.attributes.extend(
        [
            KeyValue(key="gen_ai.system", value=AnyValue(string_value="openai")),
            KeyValue(key="gen_ai.request.model", value=AnyValue(string_value="gpt-4o-mini")),
            KeyValue(key="gen_ai.usage.input_tokens", value=AnyValue(int_value=1000)),
            KeyValue(key="gen_ai.usage.output_tokens", value=AnyValue(int_value=500)),
        ]
    )

    return request.SerializeToString()


def test_ingest_endpoint_accepts_real_otlp_protobuf(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    app = create_app(store=store)
    client = TestClient(app)

    res = client.post(
        "/v1/traces",
        content=_sample_payload_protobuf(),
        headers={"content-type": "application/x-protobuf"},
    )
    assert res.status_code == 200
    assert res.json()["spans_written"] == 2

    traces = store.list_traces()
    assert len(traces) == 1
    assert traces[0]["trace_id"] == TRACE_ID_HEX
    assert traces[0]["span_count"] == 2
    assert traces[0]["total_cost_usd"] > 0


def test_error_status_span_recorded(tmp_path):
    payload = _sample_payload()
    payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["status"] = {
        "code": 2,
        "message": "upstream timeout",
    }
    store = SqliteStore(tmp_path / "test.db")
    app = create_app(store=store)
    client = TestClient(app)
    client.post("/v1/traces", json=payload)

    spans = store.get_trace_spans(TRACE_ID_HEX)
    root = next(s for s in spans if s["name"] == "pipeline_run")
    assert root["status"] == "error"
    assert root["error_message"] == "upstream timeout"
