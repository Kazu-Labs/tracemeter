"""Cost calculation from `gen_ai.usage.*` token attributes.

This is the layer OTel's GenAI conventions deliberately leave out: the
spec standardizes *how token counts are reported*, not what they cost.
TraceMeter maintains a versioned, PR-friendly pricing table and computes
cost automatically -- no custom instrumentation required as long as the
spans already carry standard usage attributes.

Unknown models fail open: tokens/latency are still logged, cost is
reported as `None` (surfaced in the UI as "unknown") rather than silently
wrong.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

_DEFAULT_PRICES_PATH = Path(__file__).parent / "prices.json"

# Matches a dated-snapshot suffix appended to a base model name, e.g. the
# "-2024-08-06" in "gpt-4o-2024-08-06" or the "-20241022" in
# "claude-3-5-sonnet-20241022". Deliberately does NOT match arbitrary
# suffixes like "-mini" -- that distinction is what stops "o1-mini" from
# incorrectly falling back to "o1"'s price (a real bug caught by a test).
_DATED_SUFFIX_RE = re.compile(r"^-(\d{4}-\d{2}-\d{2}|\d{8})$")


@lru_cache(maxsize=1)
def _load_prices(path_str: str) -> dict:
    with open(path_str, "r") as f:
        return json.load(f)


def _prices_path() -> str:
    return os.environ.get("TRACEMETER_PRICING_PATH", str(_DEFAULT_PRICES_PATH))


def _find_model_rate(system: Optional[str], model: str, table: dict) -> Optional[dict]:
    systems = [table["models"][system]] if system in table.get("models", {}) else list(
        table.get("models", {}).values()
    )
    for models in systems:
        if model in models:
            return models[model]
    # Fallback: dated-snapshot model names (e.g. "gpt-4o-2024-08-06") should
    # still match their base entry ("gpt-4o"). Only strip a suffix that
    # actually looks like a date -- a plain prefix match would also (and
    # incorrectly) match unrelated sibling models like "o1-mini" against "o1".
    best: Optional[dict] = None
    best_len = -1
    for models in systems:
        for key, rate in models.items():
            if model.startswith(key) and len(key) > best_len:
                suffix = model[len(key):]
                if suffix and not _DATED_SUFFIX_RE.match(suffix):
                    continue
                best = rate
                best_len = len(key)
    return best


class PricingEngine:
    def __init__(self, prices_path: Optional[str] = None):
        self._path = prices_path or _prices_path()

    def reload(self) -> None:
        _load_prices.cache_clear()

    def compute_cost(
        self,
        model: Optional[str],
        input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        system: Optional[str] = None,
    ) -> Optional[float]:
        if not model:
            return None
        table = _load_prices(self._path)
        rate = _find_model_rate(system, model, table)
        if rate is None:
            return None
        input_cost = (input_tokens / 1_000_000) * rate.get("input", 0.0)
        # Reasoning tokens are billed at the output rate (matches how
        # providers meter them today; revisit if that changes upstream).
        output_cost = ((output_tokens + reasoning_tokens) / 1_000_000) * rate.get(
            "output", 0.0
        )
        return round(input_cost + output_cost, 8)


_default_engine: Optional[PricingEngine] = None


def compute_cost(
    model: Optional[str],
    input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
    system: Optional[str] = None,
) -> Optional[float]:
    global _default_engine
    if _default_engine is None:
        _default_engine = PricingEngine()
    return _default_engine.compute_cost(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        system=system,
    )
