"""Tests for the Textual app: the event bridge, streaming buffers, and input.

These run the real app headless via run_test(), so widget wiring is exercised
rather than mocked. The orchestrator worker is stubbed out — this file is about
the UI layer, not the agent loop.
"""

from unittest.mock import AsyncMock, patch

import pytest

from supervisor.app import SupervisApp
from supervisor.config import Config
from supervisor.events import EventType, emit
from supervisor.widgets import OutputLog, StatusBar, StreamDisplay


def _config() -> Config:
    return Config(api_key="sk-test")


async def _app():
    """An app with the background workers stubbed out."""
    app = SupervisApp(project_dir="/tmp/project", system_prompt="sys", config=_config())
    return app


def _lines(app) -> str:
    log = app.query_one("#output", OutputLog)
    return "\n".join(strip.text for strip in log.lines)


class TestStreamingBuffers:
    @pytest.mark.asyncio
    async def test_tokens_accumulate_and_land_in_the_log_on_done(self):
        app = await _app()
        with (
            patch.object(SupervisApp, "_run_orchestrator", AsyncMock()),
            patch.object(SupervisApp, "_check_update", AsyncMock()),
        ):
            async with app.run_test() as pilot:
                emit(EventType.DEEPSEEK_START)
                emit(EventType.DEEPSEEK_TOKEN, text="hello ")
                emit(EventType.DEEPSEEK_TOKEN, text="world")
                assert app._ds_buffer == "hello world"

                emit(EventType.DEEPSEEK_DONE, cost="in 1.0k · out 0.5k · $0.0001")
                await pilot.pause()

                assert "hello world" in _lines(app)
                assert app._ds_buffer == "", "buffer must reset after the turn is written"

    @pytest.mark.asyncio
    async def test_start_clears_a_leftover_buffer(self):
        app = await _app()
        with (
            patch.object(SupervisApp, "_run_orchestrator", AsyncMock()),
            patch.object(SupervisApp, "_check_update", AsyncMock()),
        ):
            async with app.run_test():
                app._ds_buffer = "stale"
                app._reasoning_buffer = "stale thinking"
                emit(EventType.DEEPSEEK_START)
                assert app._ds_buffer == ""
                assert app._reasoning_buffer == ""

    @pytest.mark.asyncio
    async def test_reasoning_has_its_own_buffer(self):
        app = await _app()
        with (
            patch.object(SupervisApp, "_run_orchestrator", AsyncMock()),
            patch.object(SupervisApp, "_check_update", AsyncMock()),
        ):
            async with app.run_test():
                emit(EventType.DEEPSEEK_START)
                emit(EventType.DEEPSEEK_REASONING, text="thinking hard")
                emit(EventType.DEEPSEEK_TOKEN, text="answer")
                assert app._reasoning_buffer == "thinking hard"
                assert app._ds_buffer == "answer"

    @pytest.mark.asyncio
    async def test_streaming_display_shows_then_hides(self):
        app = await _app()
        with (
            patch.object(SupervisApp, "_run_orchestrator", AsyncMock()),
            patch.object(SupervisApp, "_check_update", AsyncMock()),
        ):
            async with app.run_test() as pilot:
                stream = app.query_one("#stream", StreamDisplay)
                emit(EventType.DEEPSEEK_START)
                emit(EventType.DEEPSEEK_TOKEN, text="partial")
                await pilot.pause()
                assert stream.has_class("visible")

                emit(EventType.DEEPSEEK_DONE, cost="")
                await pilot.pause()
                assert not stream.has_class("visible")


class TestStatusBar:
    @pytest.mark.asyncio
    async def test_queue_count_and_cost_reach_the_status_bar(self):
        app = await _app()
        with (
            patch.object(SupervisApp, "_run_orchestrator", AsyncMock()),
            patch.object(SupervisApp, "_check_update", AsyncMock()),
        ):
            async with app.run_test() as pilot:
                status = app.query_one("#status", StatusBar)
                emit(EventType.QUEUE_UPDATE, count=3)
                emit(EventType.DEEPSEEK_DONE, cost="$0.0042")
                await pilot.pause()
                assert status.queue_count == 3
                assert status.cost_text == "$0.0042"

    @pytest.mark.asyncio
    async def test_escalation_is_marked_with_an_arrow(self):
        app = await _app()
        with (
            patch.object(SupervisApp, "_run_orchestrator", AsyncMock()),
            patch.object(SupervisApp, "_check_update", AsyncMock()),
        ):
            async with app.run_test() as pilot:
                status = app.query_one("#status", StatusBar)
                emit(EventType.MODEL_SWITCH, model=app.session.pro_model, reason="2 failed attempts")
                await pilot.pause()
                assert "↑" in status.model_text
                assert "escalated" in _lines(app)

    @pytest.mark.asyncio
    async def test_dropping_back_to_base_clears_the_arrow(self):
        app = await _app()
        with (
            patch.object(SupervisApp, "_run_orchestrator", AsyncMock()),
            patch.object(SupervisApp, "_check_update", AsyncMock()),
        ):
            async with app.run_test() as pilot:
                status = app.query_one("#status", StatusBar)
                emit(EventType.MODEL_SWITCH, model=app.session.pro_model, reason="hard")
                emit(EventType.MODEL_SWITCH, model=app.session.base_model, reason="back to base")
                await pilot.pause()
                assert "↑" not in status.model_text


class TestInput:
    @pytest.mark.asyncio
    async def test_a_message_is_echoed_and_queued(self):
        app = await _app()
        with (
            patch.object(SupervisApp, "_run_orchestrator", AsyncMock()),
            patch.object(SupervisApp, "_check_update", AsyncMock()),
        ):
            async with app.run_test() as pilot:
                await pilot.press(*"build it")
                await pilot.press("enter")
                await pilot.pause()

                assert "You: build it" in _lines(app)
                assert app._user_queue.pending() == ["build it"]

    @pytest.mark.asyncio
    async def test_a_slash_command_is_not_queued_for_the_agent(self):
        app = await _app()
        with (
            patch.object(SupervisApp, "_run_orchestrator", AsyncMock()),
            patch.object(SupervisApp, "_check_update", AsyncMock()),
        ):
            async with app.run_test() as pilot:
                await pilot.press(*"/status")
                await pilot.press("enter")
                await pilot.pause()

                assert app._user_queue.pending() == []
                assert "Model:" in _lines(app)

    @pytest.mark.asyncio
    async def test_blank_input_is_ignored(self):
        app = await _app()
        with (
            patch.object(SupervisApp, "_run_orchestrator", AsyncMock()),
            patch.object(SupervisApp, "_check_update", AsyncMock()),
        ):
            async with app.run_test() as pilot:
                await pilot.press("enter")
                await pilot.pause()
                assert app._user_queue.pending() == []


class TestInterrupt:
    @pytest.mark.asyncio
    async def test_interrupt_with_no_agent_running_just_says_so(self):
        app = await _app()
        with (
            patch.object(SupervisApp, "_run_orchestrator", AsyncMock()),
            patch.object(SupervisApp, "_check_update", AsyncMock()),
        ):
            async with app.run_test() as pilot:
                app._agent_running = False
                app.action_interrupt()
                await pilot.pause()
                assert "No agent running" in _lines(app)
                assert not app.session.interrupt_event.is_set()

    @pytest.mark.asyncio
    async def test_interrupt_sets_the_event_the_stream_watches(self):
        app = await _app()
        with (
            patch.object(SupervisApp, "_run_orchestrator", AsyncMock()),
            patch.object(SupervisApp, "_check_update", AsyncMock()),
        ):
            async with app.run_test() as pilot:
                app._agent_running = True
                app.action_interrupt()
                await pilot.pause()
                assert app.session.interrupt_event.is_set()
                assert "Interrupted" in _lines(app)


class TestSessionWiring:
    @pytest.mark.asyncio
    async def test_config_limits_reach_the_session(self):
        config = Config(api_key="sk-test", max_cost=2.5, max_turns=7, claude_timeout=99)
        app = SupervisApp(project_dir="/tmp/p", system_prompt="sys", config=config)
        assert app.session.max_cost == 2.5
        assert app.session.max_turns == 7
        assert app.session.claude_timeout == 99

    @pytest.mark.asyncio
    async def test_client_has_a_timeout_and_no_internal_retries(self):
        app = SupervisApp(project_dir="/tmp/p", system_prompt="sys", config=_config())
        assert app.session.client.max_retries == 0, "retry policy lives in stream_turn"
        assert app.session.client.timeout is not None
