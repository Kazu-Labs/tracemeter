from tracemeter.pricing.engine import PricingEngine


def test_known_model_computes_cost():
    engine = PricingEngine()
    cost = engine.compute_cost("gpt-4o-mini", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 0.15 + 0.60


def test_versioned_model_name_falls_back_to_base():
    engine = PricingEngine()
    cost = engine.compute_cost(
        "claude-3-5-sonnet-20241022", input_tokens=1_000_000, output_tokens=0
    )
    assert cost == 3.00


def test_prefix_match_for_dated_model():
    engine = PricingEngine()
    cost = engine.compute_cost("gpt-4o-2024-08-06", input_tokens=1_000_000, output_tokens=0)
    assert cost == 2.50


def test_unknown_model_returns_none():
    engine = PricingEngine()
    cost = engine.compute_cost("some-made-up-model-9000", input_tokens=100, output_tokens=100)
    assert cost is None


def test_reasoning_tokens_billed_at_output_rate():
    engine = PricingEngine()
    cost = engine.compute_cost(
        "o1-mini", input_tokens=0, output_tokens=0, reasoning_tokens=1_000_000
    )
    assert cost == 4.40
