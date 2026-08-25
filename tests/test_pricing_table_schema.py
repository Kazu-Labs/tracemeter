"""Validates prices.json structure so a malformed community PR fails CI
loudly instead of silently breaking cost calculation."""

import json
from pathlib import Path

PRICES_PATH = Path(__file__).parent.parent / "src" / "tracemeter" / "pricing" / "prices.json"


def test_prices_json_is_valid():
    with open(PRICES_PATH) as f:
        data = json.load(f)

    assert "schema_version" in data
    assert "as_of" in data
    assert "models" in data

    for system, models in data["models"].items():
        assert isinstance(system, str) and system
        for model_name, rate in models.items():
            assert isinstance(model_name, str) and model_name
            assert "input" in rate and "output" in rate
            assert isinstance(rate["input"], (int, float)) and rate["input"] >= 0
            assert isinstance(rate["output"], (int, float)) and rate["output"] >= 0
