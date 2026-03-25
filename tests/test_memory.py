"""Tests for supervisor.memory module."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from supervisor.memory import summarize_if_needed, _clean_for_summarize


class TestCleanForSummarize:
    def test_removes_reasoning_content(self):
        msgs = [
            {"role": "assistant", "content": "hello", "reasoning_content": "thinking..."},
            {"role": "user", "content": "hi"},
        ]
        cleaned = _clean_for_summarize(msgs)
        assert "reasoning_content" not in cleaned[0]
        assert cleaned[0]["content"] == "hello"
        assert cleaned[1] == msgs[1]

    def test_leaves_messages_without_reasoning(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        cleaned = _clean_for_summarize(msgs)
        assert cleaned == msgs

    def test_does_not_mutate_original(self):
        msgs = [{"role": "assistant", "content": "x", "reasoning_content": "y"}]
        _clean_for_summarize(msgs)
        assert "reasoning_content" in msgs[0]


@pytest.mark.asyncio
async def test_below_threshold_no_change():
    messages = [{"role": "system", "content": "sys"}]
    for i in range(10):
        messages.append({"role": "user", "content": f"msg {i}"})

    client = AsyncMock()
    result = await summarize_if_needed(messages, client, threshold=40)
    assert result == messages
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_above_threshold_summarizes():
    messages = [{"role": "system", "content": "sys"}]
    for i in range(50):
        messages.append({"role": "user", "content": f"msg {i}"})
        messages.append({"role": "assistant", "content": f"reply {i}"})

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Summary of conversation"

    client = AsyncMock()
    client.chat.completions.create.return_value = mock_response

    result = await summarize_if_needed(messages, client, threshold=40)
    assert len(result) == 1 + 1 + 12  # system + summary + last 12
    assert result[0]["role"] == "system"
    assert "Summary" in result[1]["content"]


@pytest.mark.asyncio
async def test_api_failure_returns_original():
    messages = [{"role": "system", "content": "sys"}]
    for i in range(50):
        messages.append({"role": "user", "content": f"msg {i}"})

    client = AsyncMock()
    client.chat.completions.create.side_effect = Exception("API down")

    result = await summarize_if_needed(messages, client, threshold=40)
    assert result == messages
