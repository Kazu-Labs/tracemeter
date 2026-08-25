"""OpenTelemetry GenAI semantic convention attribute names.

Mirrors the (still "Development" status, as of mid-2026) `gen_ai.*`
attribute names from the OTel GenAI Semantic Conventions, so spans emitted
by TraceMeter are portable to any OTLP-compatible backend.

Reference: https://opentelemetry.io/docs/specs/semconv/gen-ai/
"""

# Span kind / operation
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"  # e.g. "chat", "text_completion"
GEN_AI_SYSTEM = "gen_ai.system"  # e.g. "openai", "anthropic"

# Request attributes
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
GEN_AI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"

# Response attributes
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_RESPONSE_ID = "gen_ai.response.id"
GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"

# Usage / token attributes
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
# Not yet standardized upstream; TraceMeter tracks it as a namespaced
# extension until/unless the spec adopts a reasoning-token attribute.
GEN_AI_USAGE_REASONING_TOKENS = "tracemeter.usage.reasoning_tokens"

# TraceMeter-specific extensions (namespaced so they never collide with
# upstream `gen_ai.*` additions).
TRACEMETER_COST_USD = "tracemeter.cost.usd"
TRACEMETER_COST_UNKNOWN = "tracemeter.cost.unknown"  # bool: True if model unpriced
TRACEMETER_LATENCY_MS = "tracemeter.latency_ms"
TRACEMETER_TTFT_MS = "tracemeter.ttft_ms"  # time to first token (streaming)
TRACEMETER_RETRY_COUNT = "tracemeter.retry_count"
TRACEMETER_STATUS = "tracemeter.status"  # "ok" | "error"
TRACEMETER_ERROR_MESSAGE = "tracemeter.error.message"

# Known gen_ai.system values
SYSTEM_OPENAI = "openai"
SYSTEM_ANTHROPIC = "anthropic"

# Known gen_ai.operation.name values
OPERATION_CHAT = "chat"
OPERATION_TEXT_COMPLETION = "text_completion"
OPERATION_EMBEDDINGS = "embeddings"
