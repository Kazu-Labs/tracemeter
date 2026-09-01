# Contributing

## Pricing table corrections (the easiest and most valuable contribution)

`src/tracemeter/pricing/prices.json` is a plain JSON file: USD per 1,000,000 tokens, grouped by provider. If a price is wrong, stale, or a model is missing:

1. Check the provider's official pricing page.
2. Add or fix the entry -- `{ "input": ..., "output": ... }` under the right provider.
3. Open a PR. No test changes needed unless you're adding a new provider key (see `tests/test_pricing_table_schema.py` for the schema it's validated against).

Prompt-caching, batch, and regional pricing multipliers aren't modeled yet -- base input/output rates only. If you're unsure of a number, [open a pricing issue](.github/ISSUE_TEMPLATE/pricing_correction.yml) instead of guessing; a listed model always beats a wrong one, but a wrong one is worse than "unknown."

## Code changes

```
git clone https://github.com/Kazu-Labs/tracemeter.git
cd tracemeter
pip install -e ".[dev,server,otlp]"
pytest
```

- New integrations (a framework, a provider client) belong in `src/tracemeter/integrations/`, following the shape of the existing ones -- see `openai_wrap.py` for the "monkeypatch a client's create method" pattern or `langchain_wrap.py`/`llamaindex_wrap.py` for the "hook a framework's own callback/event system" pattern, whichever fits.
- Every span TraceMeter emits should use standard `gen_ai.*` attribute names (`src/tracemeter/semconv.py`) where one exists; TraceMeter-specific extensions are namespaced under `tracemeter.*` so they never collide with future upstream additions.
- `PRD.md` has the current scope, explicit non-goals, and open decisions -- check it before proposing something that might already be a deliberate v1 boundary.

## Reporting a bug

Include the smallest reproduction you can, which integration is involved, and `python -c "import tracemeter; print(tracemeter.__version__)"`. The bug report issue template will prompt for this.
