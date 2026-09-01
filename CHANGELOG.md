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

### Fixed
- `instrument_openai`/`instrument_anthropic` against `AsyncOpenAI`/`AsyncAnthropic` streaming: the async wrapper returned a sync-only iterator (`__iter__`/`__next__`), so `async for chunk in stream:` against a real async streaming response raised `TypeError` instead of working. Non-streaming async calls were unaffected. Added `_AsyncStreamSpanWrapper` alongside the existing sync one.
- Pricing table re-verified against live OpenAI/Anthropic pricing pages: added `gpt-5` and `o3-pro`, both missing despite sibling tiers (`gpt-5-mini`/`gpt-5-nano`, `o3`/`o3-mini`) already being listed. Anthropic's table checked out unchanged. Noted in `prices.json` that `gpt-5.6-sol`'s current rate is a promotional cut confirmed to hold only through November 21, 2026, and that OpenAI's >272K-input-token pricing tier for that model isn't representable in this table's flat per-model schema.

## [0.2.0] and earlier

Predates this file. Highlights, oldest first: core SDK (`@trace`/`span()`, SQLite storage), OpenAI/Anthropic auto-instrumentation, local dashboard (`tracemeter serve`) with waterfall view and run comparison, LiteLLM integration, OTLP/HTTP ingest (protobuf + JSON), pricing table corrections against live provider data, and the initial PyPI release. See `git log` for the full commit history.
