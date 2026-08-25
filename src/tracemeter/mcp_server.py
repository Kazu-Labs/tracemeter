"""MCP server exposing TraceMeter's trace/cost data as tools for AI agents.

Lets an MCP-aware agent (Claude Code, Claude Desktop, etc.) query cost and
latency data directly -- "how much did the last hour of calls cost", "which
model is most expensive", "compare these two runs" -- instead of only
finding the package via search. Runs over stdio by default: an agent
launches it as a local subprocess, the same way any other local MCP server
is configured. No network exposure, no separate account.

Requires the `mcp` extra (Python 3.10+): pip install "tracemeter[mcp]"
"""

from __future__ import annotations

from typing import Any, Optional

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError as exc:
    raise ImportError(
        "The MCP server requires the 'mcp' extra (Python 3.10+): "
        "pip install 'tracemeter[mcp]'"
    ) from exc

from tracemeter.compare import compare_traces
from tracemeter.pricing.engine import compute_cost
from tracemeter.storage.sqlite_store import SqliteStore


def create_mcp_server(store: Optional[SqliteStore] = None) -> MCPServer:
    """Builds the MCPServer with a store closed over each tool, so tests
    can inject an isolated store instead of touching ~/.tracemeter/traces.db."""
    store = store or SqliteStore.default()
    server = MCPServer(
        name="tracemeter",
        instructions=(
            "Query local LLM cost and latency trace data recorded by the "
            "tracemeter Python SDK (tracemeter.span(), instrument_openai(), "
            "etc.) into a local SQLite store. No cloud account or collector "
            "involved -- all data is on this machine. Costs are computed "
            "from a community-maintained pricing table; a null cost_usd "
            "means the model isn't in that table, not that it's free."
        ),
    )

    @server.tool()
    def list_traces(
        name: Optional[str] = None,
        model: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List recent traces, most recent first. Optionally filter by a
        substring of the trace name or by model (matches any span in the
        trace). Each result has trace_id, name, start_time/end_time (unix
        seconds), span_count, error_count, and total_cost_usd."""
        return store.list_traces(name_contains=name, model=model, limit=limit)

    @server.tool()
    def get_trace(trace_id: str) -> dict[str, Any]:
        """Get every span in one trace by trace_id (from list_traces),
        including gen_ai.* and tracemeter.* attributes: model, token
        usage, cost, latency, and any error message."""
        return {"trace_id": trace_id, "spans": store.get_trace_spans(trace_id)}

    @server.tool()
    def cost_summary(group_by: str = "model", limit: int = 20) -> list[dict[str, Any]]:
        """Aggregate cost and latency across all recorded traces. group_by
        is 'model', 'day', or 'name' (span/step name). Sorted by total
        cost descending."""
        if group_by not in ("model", "day", "name"):
            # ToolError (not a bare ValueError) so the agent gets a normal
            # is_error tool result with this message, instead of the call
            # surfacing as an unhandled protocol-level crash.
            raise ToolError("group_by must be one of: model, day, name")
        return store.cost_summary(group_by=group_by)[:limit]

    @server.tool()
    def compare_two_traces(trace_id_a: str, trace_id_b: str) -> dict[str, Any]:
        """Compare cost and latency between two traces (e.g. a prompt v2
        run vs a v1 run), matching steps by span name within each trace.
        Returns per-trace totals, the delta, and a per-step breakdown."""
        return compare_traces(store, trace_id_a, trace_id_b)

    @server.tool()
    def lookup_model_price(
        model: str,
        input_tokens: int = 1_000_000,
        output_tokens: int = 1_000_000,
        system: Optional[str] = None,
    ) -> dict[str, Any]:
        """Look up TraceMeter's pricing-table cost for `model` at a given
        token count (defaults to 1,000,000 of each -- i.e. the raw
        per-million-token rate). cost_usd is null, not a guess, if the
        model isn't in the pricing table."""
        cost = compute_cost(
            model, input_tokens=input_tokens, output_tokens=output_tokens, system=system
        )
        return {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
        }

    return server


def main() -> None:
    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
