# TraceMeter

[![CI](https://github.com/Kazu-Labs/tracemeter/actions/workflows/ci.yml/badge.svg)](https://github.com/Kazu-Labs/tracemeter/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/tracemeter.svg)](https://pypi.org/project/tracemeter/)

Local-first, zero-infra cost & latency dashboard for LLM pipelines — built on [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/), not competing with them.

OTel standardized the *schema* for LLM telemetry (`gen_ai.*` attributes). It deliberately ships no collector, no cost layer, and no UI for a solo developer to just run. TraceMeter is that missing piece: a single `pip install` gets you OTel-GenAI-compliant tracing, a local SQLite store, automatic cost calculation, and a dashboard — no collector, no exporter config, no account signup.

**See it with zero setup, no API keys:**

```
pip install "tracemeter[server]"
tracemeter demo
```

Seeds ~2 weeks of realistic synthetic pipeline runs (multiple models and providers, a run comparison, an error, a streaming call) and opens the dashboard on it. Point it at your own traces once you like what you see: `tracemeter serve` reads `~/.tracemeter/traces.db` instead.

**Instrument your own pipeline:**

```python
from openai import OpenAI
import tracemeter

client = tracemeter.instrument_openai(OpenAI())

with tracemeter.span("my_pipeline"):
    client.chat.completions.create(model="gpt-4o-mini", messages=[...])
```

```
tracemeter serve
```

Opens a local dashboard at `http://127.0.0.1:8765` showing cost and latency broken down by run, step, and model — waterfall view per trace, cost breakdown by model, run-vs-run comparison, CSV/JSON export.

## Why

1. **A product, not just a spec.** OTel GenAI conventions describe the shape of the data; you still need a collector + backend + UI to see anything. TraceMeter is that consumer, ready to run locally in minutes.
2. **A cost layer.** OTel captures token counts as attributes and stops there. TraceMeter ships a maintained, PR-friendly pricing table and computes cost automatically from standard `gen_ai.usage.*` attributes.
3. **A fast path to first insight.** No collector to stand up, no exporter to configure, no backend to connect. `pip install tracemeter` to a cost-annotated dashboard in minutes.
4. **Interoperable by construction.** Every span TraceMeter emits follows `gen_ai.*` naming, so the same data is portable to Datadog, Grafana/Tempo, Jaeger, or any OTLP-compatible backend. TraceMeter isn't a silo.

## Status

Early / pre-alpha, but functional end-to-end. Working today:

- Core SDK: `@trace` / `tracemeter.span()`, nested spans, SQLite storage
- Auto-instrumentation for `openai`, `anthropic`, `litellm` client instances (sync + async, streaming included)
- LangChain callback handler (`TraceMeterCallbackHandler`), works across any LangChain chat model integration (OpenAI, Anthropic, Bedrock, Vertex AI, etc.)
- LlamaIndex callback handler (Python 3.10+), same idea via LlamaIndex's `CallbackManager`
- Pricing engine with a versioned, PR-friendly table; unknown models fail open
- Local dashboard (`tracemeter serve`): waterfall view, cost breakdown by model, run comparison, filtering, CSV/JSON export
- OTLP/HTTP ingest (`POST /v1/traces`, both protobuf and JSON) so any OTel-instrumented app can use TraceMeter as a backend without its own SDK
- MCP server (`tracemeter mcp`, Python 3.10+) exposing trace/cost data as tools for MCP-aware agents like Claude Code

Published on PyPI; not yet used in production anywhere — see [Issues](https://github.com/Kazu-Labs/tracemeter/issues) and `PRD.md` for the roadmap, or [CHANGELOG.md](CHANGELOG.md) for what's shipped since the last release.

## Install

```
pip install "tracemeter[all]"
```

Extras: `[openai]`, `[anthropic]`, `[langchain]`, `[llamaindex]` (Python 3.10+), `[server]` (dashboard), `[otlp]` (OTLP ingest), `[all]` (everything). For local development: `git clone` + `pip install -e ".[all]"`.

## Quickstart

```python
from openai import OpenAI
import tracemeter

client = tracemeter.instrument_openai(OpenAI())

with tracemeter.span("summarize_doc"):
    client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Summarize this in one sentence: ..."}],
    )
```

```
tracemeter serve
```

Traces land in `~/.tracemeter/traces.db` (override with `TRACEMETER_DB_PATH`); the dashboard reads from there. No collector, no exporter config, no account.

`instrument_openai`/`instrument_anthropic` work the same way against `AsyncOpenAI`/`AsyncAnthropic` -- including streaming, where token usage and time-to-first-token are captured as the async iterator is consumed:

```python
from openai import AsyncOpenAI
import tracemeter

client = tracemeter.instrument_openai(AsyncOpenAI())

async with tracemeter.span("summarize_doc"):
    stream = await client.chat.completions.create(
        model="gpt-4o-mini", messages=[...], stream=True, stream_options={"include_usage": True}
    )
    async for chunk in stream:
        ...
```

## LangChain

Instead of wrapping a client instance, LangChain integrations go through its callback handler API, which works across any LangChain-supported chat model:

```python
from langchain_openai import ChatOpenAI
from tracemeter.integrations.langchain_wrap import TraceMeterCallbackHandler

llm = ChatOpenAI(model="gpt-4o-mini", callbacks=[TraceMeterCallbackHandler()])
llm.invoke("hello")
```

```
tracemeter serve
```

Requires `pip install "tracemeter[langchain]"`. Works with any provider LangChain supports (OpenAI, Anthropic, Bedrock, Vertex AI, etc.) — the underlying provider is inferred from the model integration and reported as `gen_ai.system`, falling back to `"langchain"` for integrations not yet recognized.

## LlamaIndex

Same idea, through LlamaIndex's own `CallbackManager`:

```python
from llama_index.core import Settings
from tracemeter.integrations.llamaindex_wrap import TraceMeterCallbackHandler

Settings.callback_manager.add_handler(TraceMeterCallbackHandler())
```

```
tracemeter serve
```

Requires `pip install "tracemeter[llamaindex]"` (Python 3.10+, matching `llama-index-core`'s own floor). Covers LLM and embedding calls across LlamaIndex's provider integrations; the underlying provider is inferred from the LLM class and reported as `gen_ai.system`, falling back to `"llamaindex"` for integrations not yet recognized.

## Using TraceMeter without its own SDK

Point any OTel SDK's OTLP exporter at a running `tracemeter serve` instance:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:8765
```

Spans with `gen_ai.*` attributes get cost computed automatically on ingest, same as spans from TraceMeter's own SDK. Verified against a real `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-http` export during development.

## Using TraceMeter with an AI coding assistant

If you're using Claude Code, Cursor, or another AI coding assistant and want it to add cost/latency tracing to your LLM calls, point it at this repo or paste something like:

> Add tracing with tracemeter (`pip install "tracemeter[all]"`, https://github.com/Kazu-Labs/tracemeter). Wrap the OpenAI/Anthropic client with `tracemeter.instrument_openai()` / `instrument_anthropic()`, wrap the pipeline in `with tracemeter.span("..."):`, and run `tracemeter serve` to see cost and latency locally.

The repo also includes [llms.txt](llms.txt), a machine-readable summary of the API surface for agents that check for it.

### MCP server

`pip install "tracemeter[mcp]"` (Python 3.10+) also gets you an MCP server, so an MCP-aware agent can query your trace/cost data directly as tools instead of only reading about the package. It exposes `list_traces`, `get_trace`, `cost_summary`, `compare_two_traces`, and `lookup_model_price`, all reading the same local SQLite store as `tracemeter serve`.

Add it to any MCP client's config (Claude Desktop's `claude_desktop_config.json`, Claude Code's `.mcp.json`, Cursor, etc.):

```json
{
  "mcpServers": {
    "tracemeter": {
      "command": "tracemeter",
      "args": ["mcp"]
    }
  }
}
```

Or run it directly for testing: `tracemeter mcp` (talks stdio JSON-RPC; not meant to be run interactively). Add `--db /path/to/traces.db` to point it at a specific trace database.

## Core concepts

- **Spans** are OTel-GenAI-compliant: `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, etc., plus TraceMeter-specific extensions (`tracemeter.cost.usd`, `tracemeter.latency_ms`) namespaced so they never collide with future upstream additions.
- **Storage** is local SQLite by default (`~/.tracemeter/traces.db`, override with `TRACEMETER_DB_PATH`). No infra required.
- **Pricing** is a versioned JSON table (`src/tracemeter/pricing/prices.json`). Unknown models fail open: cost shows as "unknown," never silently wrong. PRs to keep it current are welcome.

## Contributing

Pricing table updates are the easiest and most valuable contribution — see `src/tracemeter/pricing/prices.json`. It's a plain JSON file: add a model, open a PR. See [CONTRIBUTING.md](CONTRIBUTING.md) for details and the dev setup.

```
pip install -e ".[dev,server,otlp]"
pytest
```

## License

Apache 2.0
