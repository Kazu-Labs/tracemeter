# TraceMeter

Local-first, zero-infra cost & latency dashboard for LLM pipelines — built on [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/), not competing with them.

OTel standardized the *schema* for LLM telemetry (`gen_ai.*` attributes). It deliberately ships no collector, no cost layer, and no UI for a solo developer to just run. TraceMeter is that missing piece: a single `pip install` gets you OTel-GenAI-compliant tracing, a local SQLite store, automatic cost calculation, and a dashboard — no collector, no exporter config, no account signup.

```python
import tracemeter

with tracemeter.span("my_pipeline"):
    ...  # your LLM calls, auto-traced if using a wrapped client
```

```
tracemeter serve
```

Opens a local dashboard showing cost and latency broken down by run, step, and model.

## Why

1. **A product, not just a spec.** OTel GenAI conventions describe the shape of the data; you still need a collector + backend + UI to see anything. TraceMeter is that consumer, ready to run locally in minutes.
2. **A cost layer.** OTel captures token counts as attributes and stops there. TraceMeter ships a maintained, PR-friendly pricing table and computes cost automatically from standard `gen_ai.usage.*` attributes.
3. **A fast path to first insight.** No collector to stand up, no exporter to configure, no backend to connect. `pip install tracemeter` to a cost-annotated dashboard in minutes.
4. **Interoperable by construction.** Every span TraceMeter emits follows `gen_ai.*` naming, so the same data is portable to Datadog, Grafana/Tempo, Jaeger, or any OTLP-compatible backend. TraceMeter isn't a silo.

## Status

Early / pre-alpha. Core SDK (tracer, SQLite storage, pricing engine) is functional. Provider auto-instrumentation (OpenAI, Anthropic, LiteLLM), the local dashboard, and the OTLP ingest endpoint are under active development — see [Issues](https://github.com/Kazu-Labs/tracemeter/issues) and the PRD in this repo for the full roadmap.

## Install

```
pip install tracemeter
```

(Not yet published to PyPI — install from source for now: `pip install -e .`)

## Core concepts

- **Spans** are OTel-GenAI-compliant: `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, etc., plus TraceMeter-specific extensions (`tracemeter.cost.usd`, `tracemeter.latency_ms`) namespaced so they never collide with future upstream additions.
- **Storage** is local SQLite by default (`~/.tracemeter/traces.db`, override with `TRACEMETER_DB_PATH`). No infra required.
- **Pricing** is a versioned JSON table (`src/tracemeter/pricing/prices.json`). Unknown models fail open: cost shows as "unknown," never silently wrong. PRs to keep it current are welcome.

## Contributing

Pricing table updates are the easiest and most valuable contribution — see `src/tracemeter/pricing/prices.json`. It's a plain JSON file: add a model, open a PR.

## License

Apache 2.0
