"""Run comparison: cost/latency diff between two traces (e.g. prompt v2
vs v1), matching steps by span name within each trace."""

from __future__ import annotations

from typing import Any

from tracemeter.storage.sqlite_store import SqliteStore


def _trace_totals(spans: list[dict[str, Any]]) -> dict[str, Any]:
    cost = sum(s["attributes"].get("tracemeter.cost.usd") or 0.0 for s in spans)
    if spans:
        start = min(s["start_time"] for s in spans)
        end = max(s["end_time"] or s["start_time"] for s in spans)
        latency_ms = (end - start) * 1000.0
    else:
        latency_ms = 0.0
    return {"cost_usd": cost, "latency_ms": latency_ms, "span_count": len(spans)}


def _steps_by_name(spans: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Groups non-root spans by name. The root span represents the whole
    run and is already reflected in the totals, so including it here
    would just add a noisy "only in A/B" row for every comparison."""
    steps: dict[str, dict[str, Any]] = {}
    for s in spans:
        if s["parent_span_id"] is None:
            continue
        step = steps.setdefault(s["name"], {"cost_usd": 0.0, "latency_ms": 0.0, "count": 0})
        step["cost_usd"] += s["attributes"].get("tracemeter.cost.usd") or 0.0
        step["latency_ms"] += s["attributes"].get("tracemeter.latency_ms") or 0.0
        step["count"] += 1
    return steps


def compare_traces(store: SqliteStore, trace_id_a: str, trace_id_b: str) -> dict[str, Any]:
    spans_a = store.get_trace_spans(trace_id_a)
    spans_b = store.get_trace_spans(trace_id_b)

    totals_a = _trace_totals(spans_a)
    totals_b = _trace_totals(spans_b)

    steps_a = _steps_by_name(spans_a)
    steps_b = _steps_by_name(spans_b)

    step_rows = []
    for name in sorted(set(steps_a) | set(steps_b)):
        a = steps_a.get(name, {"cost_usd": 0.0, "latency_ms": 0.0, "count": 0})
        b = steps_b.get(name, {"cost_usd": 0.0, "latency_ms": 0.0, "count": 0})
        step_rows.append(
            {
                "name": name,
                "a_cost_usd": a["cost_usd"],
                "b_cost_usd": b["cost_usd"],
                "cost_delta_usd": b["cost_usd"] - a["cost_usd"],
                "a_latency_ms": a["latency_ms"],
                "b_latency_ms": b["latency_ms"],
                "latency_delta_ms": b["latency_ms"] - a["latency_ms"],
                "only_in": "b" if a["count"] == 0 else ("a" if b["count"] == 0 else None),
            }
        )

    return {
        "a": {"trace_id": trace_id_a, **totals_a},
        "b": {"trace_id": trace_id_b, **totals_b},
        "delta": {
            "cost_usd": totals_b["cost_usd"] - totals_a["cost_usd"],
            "latency_ms": totals_b["latency_ms"] - totals_a["latency_ms"],
        },
        "steps": step_rows,
    }
