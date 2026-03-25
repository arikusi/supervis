"""Tests for supervisor.cost module."""

from supervisor import cost


def setup_function():
    cost.reset()


def test_record_basic():
    cost.record(1000, 500, cached_tokens=0)
    assert cost._session_input == 1000
    assert cost._session_input_cached == 0
    assert cost._session_output == 500


def test_record_with_cache():
    cost.record(1000, 500, cached_tokens=300)
    assert cost._session_input == 700
    assert cost._session_input_cached == 300
    assert cost._session_output == 500


def test_record_accumulates():
    cost.record(1000, 500)
    cost.record(2000, 1000, cached_tokens=500)
    assert cost._session_input == 1000 + 1500
    assert cost._session_input_cached == 500
    assert cost._session_output == 1500


def test_session_cost_calculation():
    cost.record(1_000_000, 1_000_000, cached_tokens=0)
    expected = 0.28 + 0.42
    assert abs(cost.session_cost() - expected) < 0.001


def test_session_cost_with_cache():
    cost.record(1_000_000, 0, cached_tokens=1_000_000)
    expected = 0.028
    assert abs(cost.session_cost() - expected) < 0.001


def test_summary_format():
    cost.record(10000, 5000, cached_tokens=3000)
    s = cost.summary()
    assert "in " in s
    assert "out " in s
    assert "$" in s
    assert "cached" in s


def test_summary_no_cache():
    cost.record(10000, 5000, cached_tokens=0)
    s = cost.summary()
    assert "cached" not in s


def test_reset():
    cost.record(1000, 500, 200)
    cost.reset()
    assert cost._session_input == 0
    assert cost._session_input_cached == 0
    assert cost._session_output == 0
    assert cost.session_cost() == 0.0
