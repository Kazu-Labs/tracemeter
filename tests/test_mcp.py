"""Tests the MCP server's tools the way a real agent calls them: through
server.call_tool(name, args), not by reaching into the undecorated
functions. Requires Python 3.10+ (skipped below that, same as the mcp
extra itself)."""

import sys

import pytest

if sys.version_info < (3, 10):
    pytest.skip("mcp requires Python 3.10+", allow_module_level=True)

pytest.importorskip("mcp")

from mcp.server.mcpserver.exceptions import ToolError

from tracemeter.mcp_server import create_mcp_server
from tracemeter.storage.sqlite_store import SqliteStore
from tracemeter.tracer import Tracer


@pytest.fixture
def populated_store(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    tracer = Tracer(store=store)
    with tracer.span("prompt_v1") as a:
        with tracer.span("call_model") as s:
            s.set_attribute("gen_ai.request.model", "gpt-4o-mini")
            s.set_attribute("gen_ai.usage.input_tokens", 1000)
            s.set_attribute("gen_ai.usage.output_tokens", 500)
            s.set_attribute("tracemeter.cost.usd", 0.000375)
    with tracer.span("prompt_v2") as b:
        with tracer.span("call_model") as s:
            s.set_attribute("gen_ai.request.model", "gpt-4o-mini")
            s.set_attribute("gen_ai.usage.input_tokens", 1000)
            s.set_attribute("gen_ai.usage.output_tokens", 800)
            s.set_attribute("tracemeter.cost.usd", 0.00063)
    return store, a.trace_id, b.trace_id


async def _call(server, name, args):
    """Calls a tool the way a real agent does and returns its data.

    List-returning tools serialize as one TextContent block per item plus
    a `structured_content = {"result": [...]}` wrapper; dict-returning
    tools put the dict directly in `structured_content`. Reading
    structured_content (and unwrapping the list case) is the
    version-correct way to get the data back, not concatenating text
    blocks."""
    result = await server.call_tool(name, args)
    assert not result.is_error, result
    sc = result.structured_content
    if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
        return sc["result"]
    return sc


async def test_list_traces(populated_store):
    store, trace_a, _ = populated_store
    server = create_mcp_server(store=store)
    traces = await _call(server, "list_traces", {})
    assert len(traces) == 2
    assert any(t["trace_id"] == trace_a for t in traces)


async def test_list_traces_filter_by_name(populated_store):
    store, trace_a, _ = populated_store
    server = create_mcp_server(store=store)
    traces = await _call(server, "list_traces", {"name": "prompt_v1"})
    assert len(traces) == 1
    assert traces[0]["trace_id"] == trace_a


async def test_get_trace(populated_store):
    store, trace_a, _ = populated_store
    server = create_mcp_server(store=store)
    result = await _call(server, "get_trace", {"trace_id": trace_a})
    assert result["trace_id"] == trace_a
    assert len(result["spans"]) == 2


async def test_cost_summary(populated_store):
    store, _, _ = populated_store
    server = create_mcp_server(store=store)
    result = await _call(server, "cost_summary", {"group_by": "model"})
    assert result[0]["key"] == "gpt-4o-mini"
    assert round(result[0]["cost_usd"], 6) == round(0.000375 + 0.00063, 6)


async def test_cost_summary_rejects_bad_group_by(populated_store):
    # server.call_tool() -- the direct in-process API used here -- propagates
    # ToolError as a raised exception rather than an is_error CallToolResult;
    # that wrapping only happens in the full request-handling pipeline a real
    # agent talks to over stdio. Verified against this SDK version directly
    # rather than assumed.
    store, _, _ = populated_store
    server = create_mcp_server(store=store)
    with pytest.raises(ToolError, match="group_by must be one of"):
        await server.call_tool("cost_summary", {"group_by": "not_a_real_option"})


async def test_compare_two_traces(populated_store):
    store, trace_a, trace_b = populated_store
    server = create_mcp_server(store=store)
    result = await _call(server, "compare_two_traces", {"trace_id_a": trace_a, "trace_id_b": trace_b})
    assert round(result["delta"]["cost_usd"], 6) == round(0.00063 - 0.000375, 6)


async def test_lookup_model_price_known_model(populated_store):
    store, _, _ = populated_store
    server = create_mcp_server(store=store)
    result = await _call(
        server,
        "lookup_model_price",
        {"model": "gpt-4o-mini", "input_tokens": 1_000_000, "output_tokens": 1_000_000},
    )
    assert result["cost_usd"] == 0.15 + 0.60


async def test_lookup_model_price_unknown_model_is_null_not_a_guess(populated_store):
    store, _, _ = populated_store
    server = create_mcp_server(store=store)
    result = await _call(server, "lookup_model_price", {"model": "not-a-real-model-9000"})
    assert result["cost_usd"] is None


async def test_tools_are_registered_with_descriptions(populated_store):
    store, _, _ = populated_store
    server = create_mcp_server(store=store)
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "list_traces",
        "get_trace",
        "cost_summary",
        "compare_two_traces",
        "lookup_model_price",
    }
    assert all(t.description for t in tools)
