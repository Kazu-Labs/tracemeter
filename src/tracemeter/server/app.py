"""Local dashboard server -- the part OTel doesn't ship.

Serves a REST API over the local SQLite store plus a static single-page
dashboard (timeline/waterfall view, cost & latency breakdowns, run
comparison, filtering, CSV/JSON export). No account, no external
service: `tracemeter serve` and it's on localhost.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, Query
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The dashboard server requires the 'server' extra: pip install 'tracemeter[server]'"
    ) from exc

from tracemeter.storage.sqlite_store import SqliteStore

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(store: Optional[SqliteStore] = None) -> "FastAPI":
    app = FastAPI(title="TraceMeter", docs_url="/api/docs")
    app.state.store = store or SqliteStore.default()

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (_STATIC_DIR / "index.html").read_text()

    @app.get("/api/traces")
    def list_traces(
        name: Optional[str] = None,
        model: Optional[str] = None,
        start_after: Optional[float] = None,
        start_before: Optional[float] = None,
        limit: int = Query(default=100, le=1000),
        offset: int = 0,
    ):
        return app.state.store.list_traces(
            name_contains=name,
            model=model,
            start_after=start_after,
            start_before=start_before,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/traces/{trace_id}")
    def get_trace(trace_id: str):
        spans = app.state.store.get_trace_spans(trace_id)
        if not spans:
            return JSONResponse({"error": "trace not found"}, status_code=404)
        return {"trace_id": trace_id, "spans": spans}

    @app.get("/api/cost_summary")
    def cost_summary(
        group_by: str = Query(default="model", pattern="^(model|day|name)$"),
        start_after: Optional[float] = None,
        start_before: Optional[float] = None,
    ):
        return app.state.store.cost_summary(
            group_by=group_by, start_after=start_after, start_before=start_before
        )

    @app.get("/api/export")
    def export(
        format: str = Query(default="json", pattern="^(json|csv)$"),
        start_after: Optional[float] = None,
        start_before: Optional[float] = None,
    ):
        spans = app.state.store.export_spans(
            start_after=start_after, start_before=start_before
        )
        if format == "json":
            return JSONResponse(spans)

        buf = io.StringIO()
        fieldnames = [
            "span_id",
            "trace_id",
            "parent_span_id",
            "name",
            "start_time",
            "end_time",
            "status",
            "error_message",
            "attributes",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for s in spans:
            row = dict(s)
            row["attributes"] = json.dumps(row["attributes"])
            writer.writerow(row)
        return PlainTextResponse(buf.getvalue(), media_type="text/csv")

    return app
