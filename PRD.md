# PRD: TraceMeter — Open-Source, Local-First Cost & Latency Dashboard for LLM Pipelines
*(built on OpenTelemetry GenAI conventions, not competing with them)*

**Status:** Draft v2 — repositioned around the OTel gap analysis
**Owner:** TBD
**Last updated:** 2026-08-24

---

## 1. Problem Statement

OpenTelemetry's GenAI Semantic Conventions have solved the **schema** problem for LLM observability: standardized `gen_ai.*` attributes for model calls, agent spans, tool/MCP execution, and token/latency metrics, so telemetry is consistent across OpenAI, Anthropic, Gemini, and others.

What OTel does **not** give a developer:

1. **A product.** OTel is a spec. To see anything, you still need a collector, an exporter, a storage backend, and a UI — typically Datadog, Grafana/Tempo, Jaeger, or a hosted platform. There is no zero-infra, local, "just works" consumer of this data.
2. **A cost layer.** OTel captures token counts as attributes. It has no pricing table and computes no cost — every backend bolts this on separately, and most don't do it well for a solo developer's use case.
3. **A fast path to first insight.** Every current GenAI-observability setup guide starts with "stand up a collector," "configure an OTLP exporter," "connect a backend." That's 30–60+ minutes of infra work before a developer sees a single number. There's no `pip install` → dashboard in 10 minutes today.
4. **Stability for casual adopters.** As of mid-2026 every `gen_ai.*` attribute is still marked "Development," not stable, and names have already been renamed mid-year — painful for someone who just wants their bill breakdown, not to track a moving spec.

**The gap TraceMeter fills:** be the local-first, zero-infra, cost-aware **consumer** of OTel GenAI data — not a competing schema. Emit and ingest standard `gen_ai.*` spans so the tool is interoperable with the rest of the ecosystem (Datadog, Grafana, etc. can read TraceMeter's data too), while owning the part nobody has made easy: a single-command local backend + dashboard + pricing engine that works with zero signup and zero collector setup.

---

## 2. Goal

Ship an open-source tool that:

- Is **OTel-GenAI-compliant on the wire** (spans/attributes follow `gen_ai.*` conventions) — so it's a legitimate part of the ecosystem, not a silo
- Requires **no collector, no exporter config, no backend signup** to get a working dashboard
- Adds the **cost calculation layer** OTel deliberately leaves out, via a maintained, community-updatable pricing table
- Gets a developer from `pip install` to "I can see which call is costing me the most" in **under 10 minutes**, with zero infrastructure decisions along the way

**North star metric:** time from install to first visualized, cost-annotated trace, with zero non-Python infrastructure required.

---

## 3. Target Users

| Persona | Need | Why OTel alone doesn't serve them today |
|---|---|---|
| **Indie hacker / solo dev** | Wants to know why their API bill spiked, immediately | Won't stand up Jaeger/Grafana for a side project |
| **Small startup team (2–10 eng)** | Shared visibility without enterprise observability spend | Datadog/enterprise OTel backends are priced and scoped for later-stage teams |
| **ML/backend engineer prototyping** | Wants to validate an architecture before justifying spend on a heavier platform | Needs something they can rip out in an afternoon, not commit infra budget to |
| **OSS maintainer of an agent framework** | Wants an easy, standards-based integration to recommend | Wants OTel-compliant output so it plays well with whatever backend their users already run, but also wants something they can point solo users to without "go set up a collector" |

Non-goal for v1: teams that already run Datadog/Grafana with OTel and just need another dashboard on the same data — that's a "TraceMeter can also read your existing OTLP stream" nice-to-have, not the initial wedge.

---

## 4. Why This, Why Now

- OTel GenAI conventions reaching real (if unstable) adoption means there's now a *standard shape* of data to build on — this product doesn't have to invent its own schema, which lowers build risk and increases interoperability for free.
- The conventions are explicitly schema-only; the SIG is not building reference backends or dashboards, so there is a real, acknowledged gap between "spec exists" and "solo dev has something useful to run."
- No pricing/cost layer exists as a first-class, well-maintained open component — every team currently hand-rolls this.
- Self-hosted / local-first remains the differentiator against every existing GenAI-observability product, which are cloud-account-first almost without exception.

---

## 5. Scope — v1 (MVP)

### 5.1 Core instrumentation SDK (Python first)
- `@trace` decorator and `with tracer.span("step_name"):` context manager
- **Emits OTel-GenAI-compliant spans** (`gen_ai.*` attributes) so output is portable to any OTLP-compatible backend, not just TraceMeter's own dashboard
- Auto-detects and wraps common clients: `openai`, `anthropic`, `litellm`
- Captures per-call: provider, model, input/output/reasoning tokens, computed cost, start/end timestamps, latency, time-to-first-token (streaming), success/error, retry count
- Nested spans so a full pipeline shows as a tree, matching OTel's agent-span model rather than inventing a parallel one
- Zero required config to start; optional config for custom pricing/self-hosted models

### 5.2 Local storage — the "no collector required" layer
- Traces written to local SQLite by default; **no OTel Collector, no exporter config, no external service** needed to get a working pipeline
- Optional lightweight local server mode (`tracemeter serve`) for team-shared dashboard over the local network
- **OTLP ingest endpoint** as an option: TraceMeter can also *receive* standard OTLP GenAI data from other instrumentation (e.g., if someone's already using an OTel-instrumented framework), so it works as a lightweight local backend even without using TraceMeter's own SDK

### 5.3 Dashboard (local web UI) — the part OTel doesn't ship
- Timeline/waterfall view per pipeline run
- Cost and latency breakdown by step, model, and day
- Run comparison (e.g., prompt v2 vs v1 cost/latency diff)
- Filtering/search by trace name, model, date range
- CSV/JSON export

### 5.4 Pricing engine — the layer OTel explicitly excludes
- Maintained, versioned, PR-friendly pricing table for major providers/models
- Cost computed automatically from the standard `gen_ai.usage.*` token attributes — no custom instrumentation needed if the spans are already OTel-compliant
- Graceful fallback for unknown models: tokens/latency still logged, cost shown as "unknown" rather than silently wrong

### 5.5 Packaging & DX — the 10-minute promise
- `pip install tracemeter`
- One-line quickstart producing a visible, cost-annotated dashboard in under 10 minutes, with no collector, exporter, or account setup
- Nothing phones home; fully offline-capable

---

## 6. Explicitly Out of Scope for v1

- Competing with or replacing OTel's semantic conventions — TraceMeter adopts them rather than inventing its own
- Hosted/cloud version (candidate for v2)
- Non-Python SDKs (JS/TS SDK is the obvious v2 target)
- Alerting/paging integrations
- Auto-optimization suggestions ("switch to a cheaper model here") — good v2 feature once the underlying data is solid
- Full OTel Collector feature parity (sampling, complex routing, multi-backend fan-out) — v1 stays intentionally simple; power users who need that should export to a real collector, which TraceMeter's compliant output makes possible

---

## 7. Success Metrics

- **Adoption:** GitHub stars, PyPI weekly downloads, integrations built by agent-framework maintainers
- **Activation:** % of installs producing a visualized, cost-annotated trace within the first session (opt-in, disclosed, off-by-default telemetry only)
- **Interoperability proof point:** number of users who feed existing OTLP/GenAI streams into TraceMeter without ever using its SDK — validates the "local backend for the ecosystem" positioning, not just "another SDK"
- **Community health:** external PRs, especially to the pricing table

---

## 8. Risks & Open Questions

| Risk | Mitigation |
|---|---|
| OTel GenAI conventions are still unstable and renaming attributes | Track the spec's changelog explicitly; use `OTEL_SEMCONV_STABILITY_OPT_IN`-style dual-emission during transitions so users aren't broken by upstream changes |
| Pricing table goes stale | Community-maintained JSON file with a clear contribution path + a scheduled staleness check |
| "Just point your OTel data at Datadog/Grafana" objection | Lead with *zero-infra, zero-account, local-first* — a genuinely different tradeoff for the pre-infra-commitment stage, not a feature race against enterprise platforms |
| Being seen as "yet another GenAI observability tool" despite the positioning | Make OTel-compliance and the "no collector needed" framing central to every piece of messaging, README, and launch post — the wedge is the packaging, not the data model |
| Scope creep into full observability platform | Hold the v1 scope above; resist alerting/auth/multi-tenant until there's clear pull |

---

## 9. Rough Milestones

1. **Week 1–2:** Core SDK — decorator/context manager, OTel-GenAI-compliant span emission, OpenAI + Anthropic wrapping, SQLite storage
2. **Week 3–4:** Pricing engine + cost calculation from `gen_ai.usage.*` attributes, nested span support, OTLP ingest endpoint
3. **Week 5–6:** Local dashboard v1 (waterfall view, basic filtering, run comparison)
4. **Week 7:** Docs, quickstart, launch (Show HN / r/LocalLLaMA / relevant Discords) — lead with "OTel-compliant, zero-infra, cost-aware in 10 minutes"
5. **Post-launch:** iterate based on GitHub issues; prioritize framework integrations (LangChain, LlamaIndex, LiteLLM) requested by early adopters

---

## 10. Open Decisions

- Exact name/branding (working name: TraceMeter)
- License (MIT vs Apache 2.0 — Apache 2.0 likely safer for company adoption)
- Whether to build the OTLP ingest endpoint in v1 or defer to v1.1 — it's the strongest interoperability proof point but adds real scope
- How much of the OTel Collector's config surface (sampling, filtering) is worth replicating even in minimal form, vs. telling power users to graduate to a real collector
