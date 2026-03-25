"""Tests for supervisor.deepseek module — retry logic and agent loop."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from supervisor.deepseek import stream_turn, run_agent_loop, _RETRYABLE_CODES


class FakeAPIError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"API error {status_code}")


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_retries_on_429(self):
        call_count = 0

        async def mock_api_call(client, messages, quiet=False):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise FakeAPIError(429)
            return "content", [], ""

        with patch("supervisor.deepseek._api_call", side_effect=mock_api_call):
            with patch("supervisor.deepseek.get_client"):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    content, tools, reasoning = await stream_turn([])

        assert call_count == 3
        assert content == "content"

    @pytest.mark.asyncio
    async def test_retries_on_500(self):
        call_count = 0

        async def mock_api_call(client, messages, quiet=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FakeAPIError(500)
            return "ok", [], ""

        with patch("supervisor.deepseek._api_call", side_effect=mock_api_call):
            with patch("supervisor.deepseek.get_client"):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    content, _, _ = await stream_turn([])

        assert call_count == 2
        assert content == "ok"

    @pytest.mark.asyncio
    async def test_no_retry_on_400(self):
        async def mock_api_call(client, messages, quiet=False):
            raise FakeAPIError(400)

        with patch("supervisor.deepseek._api_call", side_effect=mock_api_call):
            with patch("supervisor.deepseek.get_client"):
                with pytest.raises(FakeAPIError):
                    await stream_turn([])

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        async def mock_api_call(client, messages, quiet=False):
            raise FakeAPIError(429)

        with patch("supervisor.deepseek._api_call", side_effect=mock_api_call):
            with patch("supervisor.deepseek.get_client"):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(FakeAPIError):
                        await stream_turn([])


class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_stops_when_no_tool_calls(self):
        with patch("supervisor.deepseek.stream_turn", new_callable=AsyncMock) as mock_st:
            mock_st.return_value = ("Done!", [], "")
            messages = [{"role": "system", "content": "sys"}]
            result = await run_agent_loop(messages)

        assert len(result) == 2  # system + assistant
        assert result[-1]["role"] == "assistant"
        assert result[-1]["content"] == "Done!"

    @pytest.mark.asyncio
    async def test_executes_tools_and_continues(self):
        call_count = 0

        async def mock_stream_turn(messages, quiet=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "", [{"id": "tc1", "name": "read_file", "arguments": '{"path": "x.py"}'}], ""
            return "Finished", [], ""

        with patch("supervisor.deepseek.stream_turn", side_effect=mock_stream_turn):
            with patch("supervisor.deepseek.execute_tool", new_callable=AsyncMock, return_value="file content"):
                messages = [{"role": "system", "content": "sys"}]
                result = await run_agent_loop(messages)

        assert call_count == 2
        assert any(m.get("role") == "tool" for m in result)

    @pytest.mark.asyncio
    async def test_preserves_reasoning_content(self):
        with patch("supervisor.deepseek.stream_turn", new_callable=AsyncMock) as mock_st:
            mock_st.return_value = ("Answer", [], "I thought about this...")
            messages = [{"role": "system", "content": "sys"}]
            result = await run_agent_loop(messages)

        assistant_msg = result[-1]
        assert assistant_msg["reasoning_content"] == "I thought about this..."

    @pytest.mark.asyncio
    async def test_interrupt_stops_loop(self):
        call_count = 0

        async def mock_stream_turn(messages, quiet=False):
            nonlocal call_count
            call_count += 1
            return "", [{"id": "tc1", "name": "read_file", "arguments": '{"path": "x"}'}], ""

        interrupt = asyncio.Event()
        interrupt.set()  # pre-set, should stop after first turn

        with patch("supervisor.deepseek.stream_turn", side_effect=mock_stream_turn):
            messages = [{"role": "system", "content": "sys"}]
            result = await run_agent_loop(messages, interrupt_event=interrupt)

        assert call_count == 1
        # Should have placeholder tool result
        assert any(m.get("content") == "(interrupted by user)" for m in result)

    @pytest.mark.asyncio
    async def test_api_error_breaks_gracefully(self):
        with patch("supervisor.deepseek.stream_turn", new_callable=AsyncMock) as mock_st:
            mock_st.side_effect = Exception("Connection failed")
            messages = [{"role": "system", "content": "sys"}]
            result = await run_agent_loop(messages)

        assert result == messages  # unchanged, didn't crash
