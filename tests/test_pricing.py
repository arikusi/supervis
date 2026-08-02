"""Tests for the pricing table."""

from pytest import approx

from supervisor.pricing import PRICING, clear_user_pricing, price_for, register_pricing
from supervisor.session import CostTracker


class TestPriceFor:
    def test_known_models_return_their_own_rates(self):
        assert price_for("deepseek-v4-flash") == (0.14, 0.0028, 0.28)
        assert price_for("deepseek-v4-pro") == (0.435, 0.003625, 0.87)

    def test_unknown_model_has_no_price(self):
        """supervis can point at any endpoint, so guessing a rate would be a lie."""
        assert price_for("some-model-that-does-not-exist") is None

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


class TestUserSuppliedPricing:
    def setup_method(self):
        clear_user_pricing()

    def teardown_method(self):
        clear_user_pricing()

    def test_registered_rates_are_used(self):
        register_pricing("acme/model-x", input_miss=0.60, output=2.50, cached=0.15)
        assert price_for("acme/model-x") == (0.60, 0.15, 2.50)

    def test_cached_defaults_to_the_miss_rate(self):
        """A provider without prompt caching bills every input token at full price."""
        register_pricing("acme/no-cache", input_miss=1.0, output=3.0)
        assert price_for("acme/no-cache") == (1.0, 1.0, 3.0)

    def test_user_rates_win_over_the_built_in_table(self):
        register_pricing("deepseek-v4-flash", input_miss=99.0, output=99.0)
        assert price_for("deepseek-v4-flash") == (99.0, 99.0, 99.0)

    def test_a_registered_model_becomes_billable(self):
        ct = CostTracker()
        ct.record(1_000_000, 1_000_000, model="acme/model-x")
        assert ct.session_cost() == 0.0
        assert not ct.fully_priced

        clear_user_pricing()
        register_pricing("acme/model-x", input_miss=1.0, output=2.0)
        ct2 = CostTracker()
        ct2.record(1_000_000, 1_000_000, model="acme/model-x")
        assert ct2.session_cost() == approx(3.0)
        assert ct2.fully_priced


class TestUnpricedReporting:
    def setup_method(self):
        clear_user_pricing()

    def test_tokens_are_still_counted_without_a_rate_card(self):
        ct = CostTracker()
        ct.record(1000, 500, model="mystery-model")
        assert ct.input_tokens == 1000
        assert ct.output_tokens == 500
        assert ct.session_cost() == 0.0

    def test_summary_says_cost_is_unknown_rather_than_showing_zero(self):
        ct = CostTracker()
        ct.record(1000, 500, model="mystery-model")
        summary = ct.summary()
        assert "cost unknown" in summary
        assert "$0.0000" not in summary, "a fabricated zero reads as 'this was free'"

    def test_a_mixed_session_marks_the_total_as_a_floor(self):
        ct = CostTracker()
        ct.record(1_000_000, 0, model="deepseek-v4-flash")
        ct.record(1_000_000, 0, model="mystery-model")
        summary = ct.summary()
        assert "$0.1400+" in summary
        assert "unpriced" in summary

    def test_a_fully_priced_session_reads_normally(self):
        ct = CostTracker()
        ct.record(1_000_000, 0, model="deepseek-v4-flash")
        summary = ct.summary()
        assert summary.endswith("$0.1400")
        assert "unknown" not in summary
        assert ct.fully_priced

    def test_reset_clears_the_unpriced_marker(self):
        ct = CostTracker()
        ct.record(1000, 500, model="mystery-model")
        ct.reset()
        assert ct.fully_priced
        assert ct.unpriced_tokens == 0
