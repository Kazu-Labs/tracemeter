"""TraceMeter: local-first, zero-infra cost & latency tracing for LLM pipelines.

Emits OpenTelemetry GenAI-compliant spans (`gen_ai.*` attributes) to a
local SQLite store -- no collector, no exporter config, no account
signup required to see a cost-annotated trace.

Quickstart:

    import tracemeter

    with tracemeter.span("my_pipeline"):
        ...

    @tracemeter.trace()
    def my_step():
        ...
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from tracemeter.tracer import Tracer, get_default_tracer, trace
from tracemeter.pricing.engine import compute_cost
from tracemeter.integrations.openai_wrap import instrument_openai
from tracemeter.integrations.anthropic_wrap import instrument_anthropic
from tracemeter.integrations.litellm_wrap import instrument_litellm

try:
    # Single source of truth is pyproject.toml's [project].version; reading
    # it via package metadata (rather than also hardcoding it here) is what
    # keeps this from drifting out of sync with it, which it already did
    # once (this stayed "0.1.0" through the 0.1.1 release).
    __version__ = _pkg_version("tracemeter")
except PackageNotFoundError:
    # Running from a source checkout without an editable/regular install.
    __version__ = "0.0.0+unknown"

__all__ = [
    "Tracer",
    "get_default_tracer",
    "trace",
    "span",
    "compute_cost",
    "instrument_openai",
    "instrument_anthropic",
    "instrument_litellm",
]


def span(name: str, **attributes):
    """Shorthand for tracemeter.get_default_tracer().span(name, **attrs)."""
    return get_default_tracer().span(name, **attributes)
