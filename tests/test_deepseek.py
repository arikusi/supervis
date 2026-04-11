"""Tests for supervisor.deepseek module — retry logic and agent loop."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from supervisor.deepseek import stream_turn, run_agent_loop, _RETRYABLE_CODES
from supervisor.session import Session, CostTracker


class FakeAPIError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"API error {status_code}")


def _make_session(messages=None) -> Session:
    """Create a test session with a mock client."""
    client = MagicMock()
    session = Session(client=client)
    if messages is not None:
        session.messages = messages
    return session


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_retries_on_429(self):
        call_count = 0

        async def mock_api_call(session, quiet=False):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise FakeAPIError(429)
            return "content", [], ""

        session = _make_session([{"role": "system", "content": "sys"}])
        with patch("supervisor.deepseek._api_call", side_effect=mock_api_call):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                content, tools, reasoning = await stream_turn(session)

        assert call_count == 3
        assert content == "content"

    @pytest.mark.asyncio
    async def test_retries_on_500(self):
        call_count = 0

        async def mock_api_call(session, quiet=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FakeAPIError(500)
            return "ok", [], ""

        session = _make_session([{"role": "system", "content": "sys"}])
        with patch("supervisor.deepseek._api_call", side_effect=mock_api_call):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                content, _, _ = await stream_turn(session)

        assert call_count == 2
        assert content == "ok"

    @pytest.mark.asyncio
    async def test_no_retry_on_400(self):
        async def mock_api_call(session, quiet=False):
            raise FakeAPIError(400)

        session = _make_session([{"role": "system", "content": "sys"}])
        with patch("supervisor.deepseek._api_call", side_effect=mock_api_call):
            with pytest.raises(FakeAPIError):
                await stream_turn(session)

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        async def mock_api_call(session, quiet=False):
            raise FakeAPIError(429)

        session = _make_session([{"role": "system", "content": "sys"}])
        with patch("supervisor.deepseek._api_call", side_effect=mock_api_call):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(FakeAPIError):
                    await stream_turn(session)


class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_stops_when_no_tool_calls(self):
        with patch("supervisor.deepseek.stream_turn", new_callable=AsyncMock) as mock_st:
            mock_st.return_value = ("Done!", [], "")
            session = _make_session([{"role": "system", "content": "sys"}])
            await run_agent_loop(session)

        assert len(session.messages) == 2  # system + assistant
        assert session.messages[-1]["role"] == "assistant"
        assert session.messages[-1]["content"] == "Done!"

    @pytest.mark.asyncio
    async def test_executes_tools_and_continues(self):
        call_count = 0

        async def mock_stream_turn(session, quiet=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "", [{"id": "tc1", "name": "read_file", "arguments": '{"path": "x.py"}'}], ""
            return "Finished", [], ""

        with patch("supervisor.deepseek.stream_turn", side_effect=mock_stream_turn):
            with patch("supervisor.deepseek.execute_tool", new_callable=AsyncMock, return_value="file content"):
                session = _make_session([{"role": "system", "content": "sys"}])
                await run_agent_loop(session)

        assert call_count == 2
        assert any(m.get("role") == "tool" for m in session.messages)

    @pytest.mark.asyncio
    async def test_preserves_reasoning_content(self):
        with patch("supervisor.deepseek.stream_turn", new_callable=AsyncMock) as mock_st:
            mock_st.return_value = ("Answer", [], "I thought about this...")
            session = _make_session([{"role": "system", "content": "sys"}])
            await run_agent_loop(session)

        assistant_msg = session.messages[-1]
        assert assistant_msg["reasoning_content"] == "I thought about this..."

    @pytest.mark.asyncio
    async def test_interrupt_stops_loop(self):
        call_count = 0

        async def mock_stream_turn(session, quiet=False):
            nonlocal call_count
            call_count += 1
            return "", [{"id": "tc1", "name": "read_file", "arguments": '{"path": "x"}'}], ""

        session = _make_session([{"role": "system", "content": "sys"}])
        session.interrupt_event.set()  # pre-set, should stop after first turn

        with patch("supervisor.deepseek.stream_turn", side_effect=mock_stream_turn):
            await run_agent_loop(session)

        assert call_count == 1
        assert any(m.get("content") == "(interrupted by user)" for m in session.messages)

    @pytest.mark.asyncio
    async def test_api_error_breaks_gracefully(self):
        with patch("supervisor.deepseek.stream_turn", new_callable=AsyncMock) as mock_st:
            mock_st.side_effect = Exception("Connection failed")
            session = _make_session([{"role": "system", "content": "sys"}])
            original_len = len(session.messages)
            await run_agent_loop(session)

        assert len(session.messages) == original_len  # unchanged, didn't crash
