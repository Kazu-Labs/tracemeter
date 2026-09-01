# Changelog

Notable changes to TraceMeter. Format loosely follows [Keep a Changelog](https://keepachangelog.com/); this project doesn't yet promise strict semantic versioning (pre-1.0).

## [Unreleased]

### Added
- `tracemeter demo` -- seeds ~2 weeks of realistic synthetic pipeline data (multiple providers, a model-switch story for run comparison, an error trace, a streaming call, an unpriced model) and opens the dashboard on it. No API keys or real LLM calls required.
- LangChain integration (`tracemeter.integrations.langchain_wrap.TraceMeterCallbackHandler`), via LangChain's callback handler API. Works across any provider LangChain supports.
- LlamaIndex integration (`tracemeter.integrations.llamaindex_wrap.TraceMeterCallbackHandler`, Python 3.10+), via LlamaIndex's `CallbackManager`.
- MCP server (`tracemeter mcp`, Python 3.10+) exposing trace/cost data (`list_traces`, `get_trace`, `cost_summary`, `compare_two_traces`, `lookup_model_price`) as tools for MCP-aware agents.
- `async with tracemeter.span(...)` support for async pipelines.
- `CONTRIBUTING.md` and GitHub issue templates (pricing correction, bug report, feature request).
- Dashboard: a stat-tile header (total cost, traces, errors, avg latency) over the current filters, backed by a new `/api/stats` endpoint that aggregates over every matching span rather than just the current page of traces.
- Dashboard: waterfall rows are now clickable to expand the span's full attributes (token counts, TTFT, retry count, error message, etc.) -- the CSS for this existed but was never wired up to anything.
- Dashboard: traces, cost-summary rows, and waterfall spans that include a model with no listed price now show an explicit "unpriced" badge instead of silently reading as $0. `list_traces`/`cost_summary` gained `has_unknown_cost`/`unknown_cost_count` fields for this.

### Fixed
- `instrument_openai`/`instrument_anthropic` against `AsyncOpenAI`/`AsyncAnthropic` streaming: the async wrapper returned a sync-only iterator (`__iter__`/`__next__`), so `async for chunk in stream:` against a real async streaming response raised `TypeError` instead of working. Non-streaming async calls were unaffected. Added `_AsyncStreamSpanWrapper` alongside the existing sync one.
- Pricing table re-verified against live OpenAI/Anthropic pricing pages: added `gpt-5` and `o3-pro`, both missing despite sibling tiers (`gpt-5-mini`/`gpt-5-nano`, `o3`/`o3-mini`) already being listed. Anthropic's table checked out unchanged. Noted in `prices.json` that `gpt-5.6-sol`'s current rate is a promotional cut confirmed to hold only through November 21, 2026, and that OpenAI's >272K-input-token pricing tier for that model isn't representable in this table's flat per-model schema.
- `tracemeter serve --db <path>` and `tracemeter mcp --db <path>` crashed with `AttributeError: 'str' object has no attribute 'parent'` -- `args.db` was passed to `SqliteStore` as a plain string instead of a `Path`. Found by manually exercising the CLI while testing the dashboard changes above; `--db` wasn't covered by any existing test.
- The fail-open pricing design ("unknown, never silently wrong") wasn't actually visible in the dashboard: a trace or cost-summary bucket containing an unpriced model showed its cost as if fully known (often $0), the opposite of the guarantee the backend already provides. See the "unpriced" badge above.

## [0.2.0] and earlier

Predates this file. Highlights, oldest first: core SDK (`@trace`/`span()`, SQLite storage), OpenAI/Anthropic auto-instrumentation, local dashboard (`tracemeter serve`) with waterfall view and run comparison, LiteLLM integration, OTLP/HTTP ingest (protobuf + JSON), pricing table corrections against live provider data, and the initial PyPI release. See `git log` for the full commit history.
