"""Tests for the pricing table."""

from pytest import approx

from supervisor.pricing import PRICING, price_for
from supervisor.session import CostTracker


class TestPriceFor:
    def test_known_models_return_their_own_rates(self):
        assert price_for("deepseek-v4-flash") == (0.14, 0.0028, 0.28)
        assert price_for("deepseek-v4-pro") == (0.435, 0.003625, 0.87)

    def test_unknown_model_falls_back_to_flash(self):
        assert price_for("some-model-that-does-not-exist") == PRICING["deepseek-v4-flash"]

    def test_fallback_is_the_cheapest_entry(self):
        """An unknown id must never be priced above a known one, or costs inflate."""
        fallback = price_for("unknown")
        for model, rates in PRICING.items():
            assert fallback <= rates, f"{model} is cheaper than the fallback"

    def test_every_rate_is_positive_and_cache_is_cheaper_than_miss(self):
        for model, (miss, cached, out) in PRICING.items():
            assert miss > 0 and cached > 0 and out > 0, model
            assert cached < miss, f"{model}: cache hit should undercut cache miss"


class TestTieredBilling:
    def test_mixed_tier_session_bills_each_turn_at_its_own_rate(self):
        ct = CostTracker()
        ct.record(1_000_000, 1_000_000, model="deepseek-v4-flash")
        assert ct.session_cost() == approx(0.14 + 0.28)

        ct.record(1_000_000, 1_000_000, model="deepseek-v4-pro")
        assert ct.session_cost() == approx(0.14 + 0.28 + 0.435 + 0.87)

    def test_cached_input_is_billed_at_the_cache_rate(self):
        ct = CostTracker()
        ct.record(1_000_000, 0, cached_tokens=1_000_000, model="deepseek-v4-flash")
        assert ct.session_cost() == approx(0.0028)
        assert ct.input_tokens == 0
        assert ct.input_cached == 1_000_000
