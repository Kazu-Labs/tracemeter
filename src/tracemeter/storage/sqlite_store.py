"""Local SQLite storage for spans -- the "no collector required" layer.

Traces are written to a local SQLite file by default. No OTel Collector,
no exporter config, no external service is needed to get a working
pipeline: `import tracemeter` -> spans land in `~/.tracemeter/traces.db`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    parent_span_id TEXT,
    name TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL,
    status TEXT NOT NULL DEFAULT 'ok',
    error_message TEXT,
    attributes TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_parent ON spans(parent_span_id);
CREATE INDEX IF NOT EXISTS idx_spans_start_time ON spans(start_time);
CREATE INDEX IF NOT EXISTS idx_spans_name ON spans(name);
"""


def default_db_path() -> Path:
    env_path = os.environ.get("TRACEMETER_DB_PATH")
    if env_path:
        return Path(env_path)
    home = Path.home() / ".tracemeter"
    home.mkdir(parents=True, exist_ok=True)
    return home / "traces.db"


class SqliteStore:
    """Thread-safe wrapper around a single SQLite file."""

    _instances: dict[str, "SqliteStore"] = {}
    _instances_lock = threading.Lock()

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    @classmethod
    def default(cls) -> "SqliteStore":
        path = default_db_path()
        key = str(path)
        with cls._instances_lock:
            if key not in cls._instances:
                cls._instances[key] = cls(path)
            return cls._instances[key]

    def write_span(self, span: Any) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO spans
                    (span_id, trace_id, parent_span_id, name, start_time,
                     end_time, status, error_message, attributes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    span.span_id,
                    span.trace_id,
                    span.parent_span_id,
                    span.name,
                    span.start_time,
                    span.end_time,
                    span.status,
                    span.error_message,
                    json.dumps(span.attributes, default=str),
                ),
            )
            self._conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["attributes"] = json.loads(d["attributes"] or "{}")
        return d

    def get_span(self, span_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM spans WHERE span_id = ?", (span_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_trace_spans(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time ASC",
                (trace_id,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_traces(
        self,
        name_contains: Optional[str] = None,
        model: Optional[str] = None,
        start_after: Optional[float] = None,
        start_before: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List root-span-level summaries, one row per trace_id.

        A "root" span is one with no parent. Filters apply to any span
        within the trace (e.g. model filter matches if any span in the
        trace used that model).
        """
        query = """
            SELECT
                trace_id,
                MIN(start_time) AS start_time,
                MAX(end_time) AS end_time,
                COUNT(*) AS span_count,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count,
                (SELECT name FROM spans s2
                   WHERE s2.trace_id = spans.trace_id AND s2.parent_span_id IS NULL
                   LIMIT 1) AS root_name
            FROM spans
            WHERE 1=1
        """
        params: list[Any] = []
        if name_contains:
            query += " AND trace_id IN (SELECT trace_id FROM spans WHERE name LIKE ?)"
            params.append(f"%{name_contains}%")
        if model:
            query += (
                " AND trace_id IN ("
                "  SELECT trace_id FROM spans"
                "  WHERE json_extract(attributes, '$.\"gen_ai.request.model\"') = ?"
                ")"
            )
            params.append(model)
        if start_after is not None:
            query += " AND start_time >= ?"
            params.append(start_after)
        if start_before is not None:
            query += " AND start_time <= ?"
            params.append(start_before)

        query += " GROUP BY trace_id ORDER BY start_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()

        traces = []
        for row in rows:
            d = dict(row)
            spans = self.get_trace_spans(d["trace_id"])
            cost = sum(
                s["attributes"].get("tracemeter.cost.usd") or 0.0 for s in spans
            )
            d["total_cost_usd"] = cost
            # A trace can mix priced and unpriced spans (e.g. one call to a
            # model that isn't in prices.json); without this flag,
            # total_cost_usd reads as "the whole cost" when it's actually
            # only the known portion -- the fail-open pricing engine's
            # "unknown, never silently wrong" guarantee needs the UI to
            # surface this, not just the backend.
            d["has_unknown_cost"] = any(
                s["attributes"].get("tracemeter.cost.unknown") for s in spans
            )
            d["name"] = d.pop("root_name") or "(unnamed trace)"
            traces.append(d)
        return traces

    def cost_summary(
        self,
        group_by: str = "model",
        start_after: Optional[float] = None,
        start_before: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """Aggregate cost/latency by 'model' or 'day' or 'name'."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM spans WHERE 1=1").fetchall()
        spans = [self._row_to_dict(r) for r in rows]
        if start_after is not None:
            spans = [s for s in spans if s["start_time"] >= start_after]
        if start_before is not None:
            spans = [s for s in spans if s["start_time"] <= start_before]

        buckets: dict[str, dict[str, Any]] = {}
        for s in spans:
            attrs = s["attributes"]
            if group_by == "model":
                key = attrs.get("gen_ai.request.model") or attrs.get(
                    "gen_ai.response.model"
                )
            elif group_by == "day":
                import datetime

                key = datetime.datetime.utcfromtimestamp(s["start_time"]).strftime(
                    "%Y-%m-%d"
                )
            else:
                key = s["name"]
            if key is None:
                continue
            b = buckets.setdefault(
                key,
                {
                    "key": key,
                    "cost_usd": 0.0,
                    "call_count": 0,
                    "total_latency_ms": 0.0,
                    "unknown_cost_count": 0,
                },
            )
            b["cost_usd"] += attrs.get("tracemeter.cost.usd") or 0.0
            b["call_count"] += 1
            b["total_latency_ms"] += attrs.get("tracemeter.latency_ms") or 0.0
            if attrs.get("tracemeter.cost.unknown"):
                b["unknown_cost_count"] += 1

        result = list(buckets.values())
        for b in result:
            b["avg_latency_ms"] = (
                b["total_latency_ms"] / b["call_count"] if b["call_count"] else 0.0
            )
        result.sort(key=lambda b: b["cost_usd"], reverse=True)
        return result

    def stats(
        self,
        name_contains: Optional[str] = None,
        model: Optional[str] = None,
        start_after: Optional[float] = None,
        start_before: Optional[float] = None,
    ) -> dict[str, Any]:
        """Totals for the dashboard's stat-tile header, over every matching
        span rather than just one page of list_traces -- trace count, known
        cost, how many spans priced as "unknown" (so the cost figure can be
        shown as a floor rather than a complete total), error count, and
        average root-span latency."""
        query = "SELECT * FROM spans WHERE 1=1"
        params: list[Any] = []
        if name_contains:
            query += " AND trace_id IN (SELECT trace_id FROM spans WHERE name LIKE ?)"
            params.append(f"%{name_contains}%")
        if model:
            query += (
                " AND trace_id IN ("
                "  SELECT trace_id FROM spans"
                "  WHERE json_extract(attributes, '$.\"gen_ai.request.model\"') = ?"
                ")"
            )
            params.append(model)
        if start_after is not None:
            query += " AND start_time >= ?"
            params.append(start_after)
        if start_before is not None:
            query += " AND start_time <= ?"
            params.append(start_before)

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        spans = [self._row_to_dict(r) for r in rows]

        trace_ids: set[str] = set()
        error_trace_ids: set[str] = set()
        total_cost = 0.0
        unknown_cost_span_count = 0
        root_latencies: list[float] = []
        for s in spans:
            trace_ids.add(s["trace_id"])
            attrs = s["attributes"]
            if s["status"] == "error":
                error_trace_ids.add(s["trace_id"])
            cost = attrs.get("tracemeter.cost.usd")
            if cost is not None:
                total_cost += cost
            elif attrs.get("tracemeter.cost.unknown"):
                unknown_cost_span_count += 1
            if s["parent_span_id"] is None and s["end_time"] is not None:
                root_latencies.append((s["end_time"] - s["start_time"]) * 1000.0)

        return {
            "trace_count": len(trace_ids),
            "span_count": len(spans),
            "total_cost_usd": round(total_cost, 8),
            "unknown_cost_span_count": unknown_cost_span_count,
            "error_trace_count": len(error_trace_ids),
            "avg_trace_latency_ms": (
                sum(root_latencies) / len(root_latencies) if root_latencies else None
            ),
        }

    def export_spans(
        self,
        start_after: Optional[float] = None,
        start_before: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM spans ORDER BY start_time ASC"
            ).fetchall()
        spans = [self._row_to_dict(r) for r in rows]
        if start_after is not None:
            spans = [s for s in spans if s["start_time"] >= start_after]
        if start_before is not None:
            spans = [s for s in spans if s["start_time"] <= start_before]
        return spans

    def close(self) -> None:
        with self._lock:
            self._conn.close()
