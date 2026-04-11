"""Tests for supervisor.claude module — output truncation and timeout logic."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supervisor.claude import run_claude


def _make_stream_line(text: str) -> bytes:
    """Create a stream-json line as Claude Code would emit."""
    data = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }
    return (json.dumps(data) + "\n").encode()


async def _aiter(items):
    for item in items:
        yield item


def _make_mock_proc(lines, returncode=0):
    """Create a mock subprocess with given stdout lines."""
    mock_proc = AsyncMock()
    mock_proc.stdout.__aiter__ = lambda self: _aiter(lines)
    mock_proc.returncode = returncode
    mock_proc.wait = AsyncMock(return_value=returncode)
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    return mock_proc


@pytest.mark.asyncio
async def test_short_output_not_truncated():
    short_text = "Hello, this is a short response."
    mock_proc = _make_mock_proc([_make_stream_line(short_text)])

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await run_claude("test prompt", continue_session=False)

    assert result == short_text
    assert "truncated" not in result


@pytest.mark.asyncio
async def test_long_output_truncated():
    long_text = "x" * 6000
    mock_proc = _make_mock_proc([_make_stream_line(long_text)])

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await run_claude("test prompt", continue_session=False)

    assert len(result) < 6000
    assert "truncated" in result
    assert "6000 chars total" in result


@pytest.mark.asyncio
async def test_subprocess_timeout():
    """A hanging Claude subprocess is killed after timeout."""
    short_text = "partial output"
    mock_proc = _make_mock_proc([_make_stream_line(short_text)])
    mock_proc.kill = MagicMock()
    # After kill, wait returns
    mock_proc.wait = AsyncMock(return_value=-9)

    async def fake_wait_for(coro, *, timeout):
        # Consume the coroutine to avoid warnings
        coro.close() if hasattr(coro, "close") else None
        raise asyncio.TimeoutError()

    with (
        patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)),
        patch("asyncio.wait_for", side_effect=fake_wait_for),
    ):
        result = await run_claude("test prompt", continue_session=False)

    assert "timed out" in result.lower()
    mock_proc.kill.assert_called_once()
