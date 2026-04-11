"""Tests for supervisor.session module."""

import pytest
from unittest.mock import MagicMock

from supervisor.session import Session, CostTracker


class TestCostTracker:
    def test_record_basic(self):
        ct = CostTracker()
        ct.record(1000, 500)
        assert ct.input_tokens == 1000
        assert ct.output_tokens == 500
        assert ct.input_cached == 0

    def test_record_with_cache(self):
        ct = CostTracker()
        ct.record(1000, 500, cached_tokens=300)
        assert ct.input_tokens == 700
        assert ct.input_cached == 300

    def test_record_accumulates(self):
        ct = CostTracker()
        ct.record(100, 50)
        ct.record(200, 100, cached_tokens=50)
        assert ct.input_tokens == 250
        assert ct.input_cached == 50
        assert ct.output_tokens == 150

    def test_session_cost(self):
        ct = CostTracker()
        ct.record(1_000_000, 1_000_000)
        cost = ct.session_cost()
        assert abs(cost - (0.28 + 0.42)) < 0.001

    def test_summary_format(self):
        ct = CostTracker()
        ct.record(12300, 800, cached_tokens=4100)
        summary = ct.summary()
        assert "in 12.3k" in summary
        assert "4.1k cached" in summary
        assert "out 0.8k" in summary
        assert "$" in summary

    def test_reset(self):
        ct = CostTracker()
        ct.record(1000, 500, 200)
        ct.reset()
        assert ct.input_tokens == 0
        assert ct.input_cached == 0
        assert ct.output_tokens == 0


class TestSession:
    def test_creation(self):
        client = MagicMock()
        session = Session(client=client)
        assert session.model == "deepseek-chat"
        assert session.thinking is True
        assert session.claude_first is True
        assert session.max_cost is None

    def test_reset(self):
        client = MagicMock()
        session = Session(client=client)
        session.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        session.cost.record(1000, 500)
        session.claude_first = False

        session.reset()
        assert len(session.messages) == 1
        assert session.messages[0]["role"] == "system"
        assert session.cost.input_tokens == 0
        assert session.claude_first is True

    def test_reset_empty_messages(self):
        client = MagicMock()
        session = Session(client=client)
        session.messages = []
        session.reset()
        assert session.messages == []

    def test_check_budget_no_limit(self):
        client = MagicMock()
        session = Session(client=client)
        ok, msg = session.check_budget()
        assert ok is True
        assert msg == ""

    def test_check_budget_under(self):
        client = MagicMock()
        session = Session(client=client, max_cost=1.0)
        session.cost.record(100_000, 50_000)  # very small cost
        ok, msg = session.check_budget()
        assert ok is True
        assert msg == ""

    def test_check_budget_warning(self):
        client = MagicMock()
        session = Session(client=client, max_cost=0.001)
        session.cost.record(2000, 1000)  # small but > 80% of tiny budget
        ok, msg = session.check_budget()
        # Either warning or exceeded
        assert "Budget" in msg

    def test_check_budget_exceeded(self):
        client = MagicMock()
        session = Session(client=client, max_cost=0.0001)
        session.cost.record(1_000_000, 500_000)  # definitely over
        ok, msg = session.check_budget()
        assert ok is False
        assert "exceeded" in msg.lower()


class TestStripOldReasoning:
    def test_strips_before_last_user(self):
        client = MagicMock()
        session = Session(client=client)
        session.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1", "reasoning_content": "think1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2", "reasoning_content": "think2"},
        ]
        session.strip_old_reasoning()
        # think1 should be stripped (before last user msg at idx 3)
        assert "reasoning_content" not in session.messages[2]
        # think2 should remain (after last user msg)
        assert session.messages[4]["reasoning_content"] == "think2"

    def test_no_strip_when_single_turn(self):
        client = MagicMock()
        session = Session(client=client)
        session.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1", "reasoning_content": "think1"},
        ]
        session.strip_old_reasoning()
        # Only one user message, nothing before it to strip
        assert session.messages[2]["reasoning_content"] == "think1"

    def test_no_user_messages(self):
        client = MagicMock()
        session = Session(client=client)
        session.messages = [{"role": "system", "content": "sys"}]
        session.strip_old_reasoning()  # should not crash
        assert len(session.messages) == 1
