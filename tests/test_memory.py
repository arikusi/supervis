"""Tests for supervisor.memory module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from supervisor.memory import _clean_for_summarize, _safe_tail_start, summarize_if_needed
from supervisor.session import Session


def _make_session(messages) -> Session:
    """Create a test session with given messages and a mock client."""
    client = AsyncMock()
    session = Session(client=client)
    session.messages = messages
    return session


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


class TestSafeTailStart:
    def test_avoids_orphan_tool_message(self):
        # tail boundary would land on a tool result; must walk back to the user
        msgs = [
            {"role": "system"},
            {"role": "user"},
            {"role": "assistant", "tool_calls": [{}]},
            {"role": "tool"},
            {"role": "tool"},
        ]
        # keep=2 → raw start is index 3 (a tool message) → walk back to user at 1
        assert _safe_tail_start(msgs, keep=2) == 1

    def test_lands_on_user_when_safe(self):
        msgs = [{"role": "system"}] + [
            {"role": "user"},
            {"role": "assistant"},
            {"role": "user"},
            {"role": "assistant"},
        ]
        # keep=2 → start index 3 is a user message, used as-is
        assert _safe_tail_start(msgs, keep=2) == 3

    def test_no_user_returns_one(self):
        msgs = [{"role": "system"}, {"role": "assistant"}, {"role": "tool"}]
        assert _safe_tail_start(msgs, keep=1) == 1


@pytest.mark.asyncio
async def test_below_threshold_no_change():
    messages = [{"role": "system", "content": "sys"}]
    for i in range(10):
        messages.append({"role": "user", "content": f"msg {i}"})

    session = _make_session(messages)
    await summarize_if_needed(session, threshold=40)
    assert session.messages == messages
    session.client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_above_threshold_summarizes():
    messages = [{"role": "system", "content": "sys"}]
    for i in range(50):
        messages.append({"role": "user", "content": f"msg {i}"})
        messages.append({"role": "assistant", "content": f"reply {i}"})

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Summary of conversation"

    session = _make_session(messages)
    session.client.chat.completions.create.return_value = mock_response

    await summarize_if_needed(session, threshold=40)
    assert len(session.messages) == 1 + 1 + 12  # system + summary + last 12
    assert session.messages[0]["role"] == "system"
    assert "Summary" in session.messages[1]["content"]


@pytest.mark.asyncio
async def test_api_failure_returns_original():
    messages = [{"role": "system", "content": "sys"}]
    for i in range(50):
        messages.append({"role": "user", "content": f"msg {i}"})

    session = _make_session(list(messages))  # copy so we can compare
    session.client.chat.completions.create.side_effect = Exception("API down")

    await summarize_if_needed(session, threshold=40)
    assert len(session.messages) == len(messages)  # unchanged
