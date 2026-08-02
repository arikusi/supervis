"""Tests for supervisor.widgets.output_log module.

OutputLog is pure rendering — it holds no streaming state. The buffering it used
to own now lives on the App, which is the only object that sees both this widget
and StreamDisplay; see test_app.py.

RichLog only lays out text once it is mounted and sized, so these run the widget
inside a throwaway app rather than poking at its internals.
"""

from collections.abc import Callable

import pytest
from textual.app import App, ComposeResult

from supervisor.widgets.output_log import OutputLog


class _Host(App):
    def compose(self) -> ComposeResult:
        yield OutputLog(id="output")


async def _render(write: Callable[[OutputLog], None]) -> str:
    """Run `write` against a mounted OutputLog and return what it printed."""
    app = _Host()
    async with app.run_test() as pilot:
        log = app.query_one("#output", OutputLog)
        write(log)
        await pilot.pause()
        return "\n".join(strip.text for strip in log.lines)


class TestDeepSeekRendering:
    @pytest.mark.asyncio
    async def test_done_writes_the_content_it_is_given(self):
        out = await _render(lambda log: log.write_deepseek_done("hello world", "$0.0001"))
        assert "hello world" in out
        assert "$0.0001" in out

    @pytest.mark.asyncio
    async def test_done_without_content_marks_a_tool_only_turn(self):
        out = await _render(lambda log: log.write_deepseek_done("", "$0.0001"))
        assert "tool calls only" in out

    @pytest.mark.asyncio
    async def test_done_without_cost_omits_the_bracket(self):
        out = await _render(lambda log: log.write_deepseek_done("hello"))
        assert "[" not in out

    def test_holds_no_streaming_state(self):
        log = OutputLog()
        assert not hasattr(log, "_ds_buffer")
        assert not hasattr(log, "_reasoning_buffer")


class TestOtherLines:
    @pytest.mark.asyncio
    async def test_retry_reason_is_rendered_verbatim(self):
        out = await _render(lambda log: log.write_deepseek_retry("Connection error", 4))
        assert "Connection error" in out
        assert "4s" in out

    @pytest.mark.asyncio
    async def test_claude_done_counts_tools(self):
        out = await _render(lambda log: log.write_claude_done(12))
        assert "12 tool calls" in out

    @pytest.mark.asyncio
    async def test_claude_done_without_tools_is_bare(self):
        out = await _render(lambda log: log.write_claude_done(0))
        assert "tool calls" not in out

    @pytest.mark.asyncio
    async def test_help_lists_every_command(self):
        entries = [("reset", "Reset session"), ("status", "Show status")]
        out = await _render(lambda log: log.write_help(entries))
        assert "/reset" in out
        assert "/status" in out
        assert "Ctrl+Z" in out
