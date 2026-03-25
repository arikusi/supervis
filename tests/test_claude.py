"""Tests for supervisor.claude module — output truncation logic."""

import json
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from supervisor.claude import run_claude


def _make_stream_line(text: str) -> bytes:
    """Create a stream-json line as Claude Code would emit."""
    data = {
        "type": "assistant",
        "message": {
            "content": [{"type": "text", "text": text}]
        },
    }
    return (json.dumps(data) + "\n").encode()


@pytest.mark.asyncio
async def test_short_output_not_truncated():
    short_text = "Hello, this is a short response."
    lines = [_make_stream_line(short_text)]

    mock_proc = AsyncMock()
    mock_proc.stdout.__aiter__ = lambda self: aiter(lines)
    mock_proc.wait = AsyncMock()
    mock_proc.returncode = 0

    with patch("supervisor.claude.asyncio") as mock_asyncio:
        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_proc)

        result = await run_claude("test prompt", continue_session=False)

    assert result == short_text
    assert "truncated" not in result


@pytest.mark.asyncio
async def test_long_output_truncated():
    long_text = "x" * 6000
    lines = [_make_stream_line(long_text)]

    mock_proc = AsyncMock()
    mock_proc.stdout.__aiter__ = lambda self: aiter(lines)
    mock_proc.wait = AsyncMock()
    mock_proc.returncode = 0

    with patch("supervisor.claude.asyncio") as mock_asyncio:
        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_proc)

        result = await run_claude("test prompt", continue_session=False)

    assert len(result) < 6000
    assert "truncated" in result
    assert "6000 chars total" in result


async def aiter(items):
    for item in items:
        yield item
