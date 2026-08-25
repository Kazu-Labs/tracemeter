"""OTLP/HTTP ingest -- the strongest interoperability proof point.

TraceMeter can *receive* standard OTLP GenAI data from other
instrumentation, not just its own SDK. Point any OTel SDK's OTLP/HTTP
exporter at this server (`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8765`)
and it becomes a lightweight local backend: spans land in the same
SQLite store and dashboard as TraceMeter's own SDK, and cost is still
computed automatically from `gen_ai.usage.*` attributes -- no custom
instrumentation required.

Both wire formats are supported, dispatched on Content-Type:
- `application/x-protobuf` -- what every mainstream OTel SDK's OTLP/HTTP
  exporter sends by default. Requires the `opentelemetry-proto` package
  (the `otlp` extra) -- it's just the compiled protobuf message classes,
  not the OTel SDK, so it's a light add. Verified against a real
  `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-http` export
  during development; a JSON-only endpoint does NOT interoperate with
  that exporter, since it always sends protobuf regardless of the
  `OTEL_EXPORTER_OTLP_PROTOCOL` env var.
- `application/json` -- OTLP's JSON encoding, for tooling that emits it
  directly (e.g. hand-rolled exporters, curl, tests).
"""

from __future__ import annotations

import base64
import binascii
from typing import Any, Optional

from tracemeter import semconv
from tracemeter.pricing.engine import compute_cost
from tracemeter.tracer import Span


class MalformedOtlpPayload(ValueError):
    """Raised when an OTLP payload can't be parsed."""


def _maybe_compute_cost(attributes: dict[str, Any]) -> None:
    """If the incoming span already carries gen_ai.usage.* attributes but
    no cost (because it came from a non-TraceMeter OTel SDK), compute it
    the same way the SDK integrations do."""
    if semconv.TRACEMETER_COST_USD in attributes or semconv.TRACEMETER_COST_UNKNOWN in attributes:
        return
    model = attributes.get(semconv.GEN_AI_REQUEST_MODEL) or attributes.get(
        semconv.GEN_AI_RESPONSE_MODEL
    )
    input_tokens = attributes.get(semconv.GEN_AI_USAGE_INPUT_TOKENS)
    output_tokens = attributes.get(semconv.GEN_AI_USAGE_OUTPUT_TOKENS)
    if model is None or (input_tokens is None and output_tokens is None):
        return
    cost = compute_cost(
        model,
        input_tokens=input_tokens or 0,
        output_tokens=output_tokens or 0,
        reasoning_tokens=attributes.get(semconv.GEN_AI_USAGE_REASONING_TOKENS) or 0,
        system=attributes.get(semconv.GEN_AI_SYSTEM),
    )
    if cost is None:
        attributes[semconv.TRACEMETER_COST_UNKNOWN] = True
    else:
        attributes[semconv.TRACEMETER_COST_USD] = cost


def _finalize_span(
    name: str,
    trace_id: str,
    span_id: str,
    parent_span_id: Optional[str],
    start_time: float,
    end_time: Optional[float],
    attributes: dict[str, Any],
    is_error: bool,
    error_message: Optional[str],
) -> Span:
    if end_time is not None:
        attributes.setdefault(semconv.TRACEMETER_LATENCY_MS, (end_time - start_time) * 1000.0)
    if error_message:
        attributes.setdefault(semconv.TRACEMETER_ERROR_MESSAGE, error_message)
    _maybe_compute_cost(attributes)
    return Span(
        name=name or "(unnamed span)",
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        start_time=start_time,
        end_time=end_time,
        attributes=attributes,
        status="error" if is_error else "ok",
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# JSON encoding
# ---------------------------------------------------------------------------


def _any_value_to_python(value: dict) -> Any:
    if "stringValue" in value:
        return value["stringValue"]
    if "boolValue" in value:
        return value["boolValue"]
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return value["doubleValue"]
    if "arrayValue" in value:
        return [_any_value_to_python(v) for v in value["arrayValue"].get("values", [])]
    if "kvlistValue" in value:
        return _attrs_list_to_dict(value["kvlistValue"].get("values", []))
    if "bytesValue" in value:
        return value["bytesValue"]
    return None


def _attrs_list_to_dict(attrs: list) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for attr in attrs:
        key = attr.get("key")
        val = attr.get("value")
        if key is None or val is None:
            continue
        out[key] = _any_value_to_python(val)
    return out


def _normalize_id(raw: Optional[str], expected_hex_len: int) -> Optional[str]:
    """The OTLP spec calls for hex-string trace_id/span_id in the JSON
    encoding (not the canonical protobuf-JSON base64 mapping other
    `bytes` fields would get), and that's what real exporters emit.
    Accept either, to be safe."""
    if not raw:
        return None
    candidate = raw.lower()
    if len(candidate) == expected_hex_len and all(
        c in "0123456789abcdef" for c in candidate
    ):
        return candidate
    try:
        return base64.b64decode(raw).hex()
    except (binascii.Error, ValueError):
        return candidate


def _ns_to_seconds(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    return int(raw) / 1_000_000_000.0


def parse_export_request_json(body: dict) -> list[Span]:
    """Parses an OTLP ExportTraceServiceRequest (JSON encoding) into
    TraceMeter Span objects."""
    spans: list[Span] = []
    try:
        for resource_spans in body.get("resourceSpans", []):
            for scope_spans in resource_spans.get("scopeSpans", []):
                for raw_span in scope_spans.get("spans", []):
                    trace_id = _normalize_id(raw_span.get("traceId"), 32)
                    span_id = _normalize_id(raw_span.get("spanId"), 16)
                    parent_span_id = _normalize_id(raw_span.get("parentSpanId"), 16)
                    if not trace_id or not span_id:
                        continue

                    attributes = _attrs_list_to_dict(raw_span.get("attributes", []))
                    status = raw_span.get("status", {})
                    is_error = status.get("code") == 2  # STATUS_CODE_ERROR
                    error_message = status.get("message") if is_error else None
                    start_time = _ns_to_seconds(raw_span.get("startTimeUnixNano")) or 0.0
                    end_time = _ns_to_seconds(raw_span.get("endTimeUnixNano"))

                    spans.append(
                        _finalize_span(
                            raw_span.get("name"),
                            trace_id,
                            span_id,
                            parent_span_id,
                            start_time,
                            end_time,
                            attributes,
                            is_error,
                            error_message,
                        )
                    )
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise MalformedOtlpPayload(str(exc)) from exc
    return spans


# ---------------------------------------------------------------------------
# Protobuf encoding (the default wire format of every mainstream OTLP/HTTP
# exporter, including opentelemetry-exporter-otlp-proto-http)
# ---------------------------------------------------------------------------


def _proto_any_value_to_python(value: Any) -> Any:
    kind = value.WhichOneof("value")
    if kind == "string_value":
        return value.string_value
    if kind == "bool_value":
        return value.bool_value
    if kind == "int_value":
        return value.int_value
    if kind == "double_value":
        return value.double_value
    if kind == "array_value":
        return [_proto_any_value_to_python(v) for v in value.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: _proto_any_value_to_python(kv.value) for kv in value.kvlist_value.values}
    if kind == "bytes_value":
        return value.bytes_value
    return None


def parse_export_request_protobuf(raw_body: bytes) -> list[Span]:
    """Parses an OTLP ExportTraceServiceRequest (protobuf encoding) into
    TraceMeter Span objects. Requires `pip install 'tracemeter[otlp]'`."""
    try:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Receiving protobuf-encoded OTLP requires the 'otlp' extra: "
            "pip install 'tracemeter[otlp]'"
        ) from exc

    request = ExportTraceServiceRequest()
    try:
        request.ParseFromString(raw_body)
    except Exception as exc:  # protobuf raises its own DecodeError subclasses
        raise MalformedOtlpPayload(str(exc)) from exc

    spans: list[Span] = []
    for resource_spans in request.resource_spans:
        for scope_spans in resource_spans.scope_spans:
            for raw_span in scope_spans.spans:
                trace_id = raw_span.trace_id.hex()
                span_id = raw_span.span_id.hex()
                if not trace_id or not span_id:
                    continue
                parent_span_id = raw_span.parent_span_id.hex() if raw_span.parent_span_id else None

                attributes = {
                    kv.key: _proto_any_value_to_python(kv.value) for kv in raw_span.attributes
                }
                is_error = raw_span.status.code == 2  # STATUS_CODE_ERROR
                error_message = raw_span.status.message if is_error else None
                start_time = raw_span.start_time_unix_nano / 1_000_000_000.0
                end_time = (
                    raw_span.end_time_unix_nano / 1_000_000_000.0
                    if raw_span.end_time_unix_nano
                    else None
                )

                spans.append(
                    _finalize_span(
                        raw_span.name,
                        trace_id,
                        span_id,
                        parent_span_id,
                        start_time,
                        end_time,
                        attributes,
                        is_error,
                        error_message,
                    )
                )
    return spans
