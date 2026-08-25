# TraceMeter

[![CI](https://github.com/Kazu-Labs/tracemeter/actions/workflows/ci.yml/badge.svg)](https://github.com/Kazu-Labs/tracemeter/actions/workflows/ci.yml)

Local-first, zero-infra cost & latency dashboard for LLM pipelines — built on [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/), not competing with them.

OTel standardized the *schema* for LLM telemetry (`gen_ai.*` attributes). It deliberately ships no collector, no cost layer, and no UI for a solo developer to just run. TraceMeter is that missing piece: a single `pip install` gets you OTel-GenAI-compliant tracing, a local SQLite store, automatic cost calculation, and a dashboard — no collector, no exporter config, no account signup.

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
- Auto-instrumentation for `openai`, `anthropic`, `litellm` client instances (sync + streaming)
- Pricing engine with a versioned, PR-friendly table; unknown models fail open
- Local dashboard (`tracemeter serve`): waterfall view, cost breakdown by model, run comparison, filtering, CSV/JSON export
- OTLP/HTTP ingest (`POST /v1/traces`, both protobuf and JSON) so any OTel-instrumented app can use TraceMeter as a backend without its own SDK

Not yet published to PyPI, and not yet used in production anywhere — see [Issues](https://github.com/Kazu-Labs/tracemeter/issues) and `PRD.md` for the roadmap.

## Install

```
git clone https://github.com/Kazu-Labs/tracemeter
cd tracemeter
pip install -e ".[all]"
```

`pip install tracemeter` once it's published to PyPI. Extras: `[openai]`, `[anthropic]`, `[server]` (dashboard), `[otlp]` (OTLP ingest), `[all]` (everything).

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

## Using TraceMeter without its own SDK

Point any OTel SDK's OTLP exporter at a running `tracemeter serve` instance:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:8765
```

Spans with `gen_ai.*` attributes get cost computed automatically on ingest, same as spans from TraceMeter's own SDK. Verified against a real `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-http` export during development.

## Core concepts

- **Spans** are OTel-GenAI-compliant: `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, etc., plus TraceMeter-specific extensions (`tracemeter.cost.usd`, `tracemeter.latency_ms`) namespaced so they never collide with future upstream additions.
- **Storage** is local SQLite by default (`~/.tracemeter/traces.db`, override with `TRACEMETER_DB_PATH`). No infra required.
- **Pricing** is a versioned JSON table (`src/tracemeter/pricing/prices.json`). Unknown models fail open: cost shows as "unknown," never silently wrong. PRs to keep it current are welcome.

## Contributing

Pricing table updates are the easiest and most valuable contribution — see `src/tracemeter/pricing/prices.json`. It's a plain JSON file: add a model, open a PR.

```
pip install -e ".[dev,server,otlp]"
pytest
```

## License

Apache 2.0
