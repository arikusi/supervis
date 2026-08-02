"""Tests for supervisor.session module."""

from unittest.mock import MagicMock

from supervisor.session import ESCALATE_AFTER, REPEAT_THRESHOLD, STUCK_CAP, CostTracker, Session


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
        ct.record(1_000_000, 1_000_000)  # defaults to flash rates
        cost = ct.session_cost()
        assert abs(cost - (0.14 + 0.28)) < 0.001

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
        assert session.model == "deepseek-v4-flash"
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
        session.cost.record(3000, 1500)  # ~$0.00084 → ~84% of the tiny budget
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


class TestCostTrackerModels:
    def test_flash_vs_pro_rates(self):
        flash = CostTracker()
        flash.record(1_000_000, 1_000_000, model="deepseek-v4-flash")
        pro = CostTracker()
        pro.record(1_000_000, 1_000_000, model="deepseek-v4-pro")
        assert pro.session_cost() > flash.session_cost()
        assert abs(pro.session_cost() - (0.435 + 0.87)) < 0.001

    def test_mixed_tiers_accrue_separately(self):
        ct = CostTracker()
        ct.record(1_000_000, 0, model="deepseek-v4-flash")  # 0.14
        ct.record(1_000_000, 0, model="deepseek-v4-pro")  # 0.435
        assert abs(ct.session_cost() - (0.14 + 0.435)) < 0.001
        # token counters aggregate regardless of tier
        assert ct.input_tokens == 2_000_000

    def test_unknown_model_falls_back_to_flash(self):
        ct = CostTracker()
        ct.record(1_000_000, 0, model="some-future-model")
        assert abs(ct.session_cost() - 0.14) < 0.001

    def test_cached_tokens_priced_lower(self):
        ct = CostTracker()
        ct.record(1_000_000, 0, cached_tokens=1_000_000, model="deepseek-v4-flash")
        assert abs(ct.session_cost() - 0.0028) < 0.0001


class TestEscalation:
    def _session(self, **kw):
        return Session(client=MagicMock(), **kw)

    def test_base_by_default(self):
        s = self._session()
        changed, _ = s.select_turn_model()
        assert s.model == s.base_model
        assert s.escalated is False

    def test_failures_escalate_to_pro(self):
        s = self._session()
        for _ in range(ESCALATE_AFTER):
            s.note_claude_result("do the thing", "build failed: error")
        changed, reason = s.select_turn_model()
        assert s.model == s.pro_model
        assert s.escalated is True
        assert changed is True
        assert "failed" in reason

    def test_success_resets_and_deescalates(self):
        s = self._session()
        for i in range(ESCALATE_AFTER):
            s.note_claude_result(f"attempt {i}", "traceback (most recent call last)")
        s.select_turn_model()
        assert s.escalated is True
        s.note_claude_result("now a different step", "all tests green, done")
        changed, _ = s.select_turn_model()
        assert s.model == s.base_model

    def test_nudge_queued_once_on_escalation(self):
        s = self._session()
        for _ in range(ESCALATE_AFTER):
            s.note_claude_result("x", "command not found")
        nudge = s.consume_nudge()
        assert nudge and "root cause" in nudge
        assert s.consume_nudge() is None  # only once

    def test_repeat_detector_counts_as_failure(self):
        s = self._session()
        for _ in range(REPEAT_THRESHOLD):
            s.note_claude_result("identical prompt", "ok, looks fine")  # no failure marker
        assert s._failures >= 1

    def test_stuck_alert_after_cap(self):
        s = self._session()
        for _ in range(STUCK_CAP):
            s.note_claude_result("x", "fatal: boom")
        assert s.consume_stuck_alert() is True
        assert s.consume_stuck_alert() is False

    def test_request_escalation_one_shot(self):
        s = self._session()
        s.request_escalation()
        s.select_turn_model()
        assert s.escalated is True
        # next turn drops back (one-shot, no failures)
        s.select_turn_model()
        assert s.model == s.base_model

    def test_pinned_ignores_auto(self):
        s = self._session()
        s.pin_model("deepseek-v4-pro", True)
        for _ in range(ESCALATE_AFTER + 3):
            s.note_claude_result("x", "build failed")
        s.select_turn_model()
        assert s.model == "deepseek-v4-pro"  # stays where the user pinned it
        s.unpin()
        assert s.pinned is False

    def test_auto_off_never_escalates(self):
        s = self._session(auto_escalate=False)
        for _ in range(ESCALATE_AFTER + 2):
            s.note_claude_result("x", "build failed")
        s.select_turn_model()
        assert s.model == s.base_model


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


class TestStuckCap:
    def test_alert_fires_once_and_resets_the_counters(self):
        session = Session(client=MagicMock())
        for _ in range(STUCK_CAP):
            session.note_claude_result("fix the build", "Traceback (most recent call last): boom")

        assert session.consume_stuck_alert() is True
        assert session.consume_stuck_alert() is False, "the alert must not repeat"
        assert session._failures == 0, "counters restart so the next failure does not re-trip instantly"

    def test_alert_queues_the_next_turn_on_pro(self):
        """Whatever the user comes back with is answering a problem flash lost to."""
        session = Session(client=MagicMock())
        for _ in range(STUCK_CAP):
            session.note_claude_result("fix the build", "tests failed")
        session.consume_stuck_alert()

        changed, _ = session.select_turn_model()
        assert changed is True
        assert session.model == session.pro_model

    def test_a_pinned_model_is_not_overridden_by_the_alert(self):
        session = Session(client=MagicMock())
        session.pin_model("deepseek-v4-flash", thinking=False)
        for _ in range(STUCK_CAP):
            session.note_claude_result("fix the build", "tests failed")
        session.consume_stuck_alert()

        session.select_turn_model()
        assert session.model == "deepseek-v4-flash", "a pin is the user's call and outranks escalation"

    def test_a_success_clears_the_failure_streak(self):
        session = Session(client=MagicMock())
        for i in range(STUCK_CAP - 1):
            session.note_claude_result(f"attempt {i}", "tests failed")
        session.note_claude_result("different step", "All 40 tests pass. Build is clean.")

        assert session._failures == 0
        assert session.consume_stuck_alert() is False

    def test_the_same_prompt_repeating_counts_as_stuck_even_when_it_reports_success(self):
        """Re-dispatching an identical step is a loop, whatever the worker says."""
        session = Session(client=MagicMock())
        for _ in range(REPEAT_THRESHOLD):
            session.note_claude_result("run the tests", "All tests pass.")

        assert session._failures > 0

    def test_varied_successful_prompts_never_look_stuck(self):
        session = Session(client=MagicMock())
        for i in range(10):
            session.note_claude_result(f"step {i}", "Done, build is clean.")

        assert session._failures == 0
        assert session.consume_stuck_alert() is False
