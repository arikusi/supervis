"""Tests for supervisor.claude module — output truncation and timeout logic."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supervisor.claude import claude_available, run_claude


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


def _fake_session(claude_timeout=300, truncation_limit=16000):
    """Minimal stand-in for Session — only the fields run_claude touches."""
    return SimpleNamespace(
        claude_first=True,
        claude_proc=None,
        claude_timeout=claude_timeout,
        truncation_limit=truncation_limit,
    )


def _make_mock_proc(lines, returncode=0, stderr_lines=None, stall=False, raise_once=False):
    """Mock subprocess whose stdout.readline() yields the given lines, then EOF.

    stall=True makes readline() hang after the lines run out, which is what a
    wedged Claude Code process looks like.
    raise_once=True makes the first read raise ValueError, as readline() does
    for a line longer than the stream limit.
    """
    mock_proc = AsyncMock()
    pending = list(lines)
    raised = []

    async def _readline():
        if raise_once and not raised:
            raised.append(True)
            raise ValueError("Separator is not found, and chunk exceed the limit")
        if pending:
            return pending.pop(0)
        if stall:
            await asyncio.sleep(3600)
        return b""

    mock_proc.stdout.readline = _readline

    if stderr_lines is None:
        mock_proc.stderr = None
    else:
        mock_proc.stderr.__aiter__ = lambda self: _aiter(stderr_lines)
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
    long_text = "x" * 20000
    mock_proc = _make_mock_proc([_make_stream_line(long_text)])

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await run_claude("test prompt", continue_session=False)

    assert len(result) < 20000
    # The forwarded head is bounded, but the note must tell the supervisor the
    # reply was complete so it does not loop asking Claude to "continue".
    assert "supervis note" in result
    assert "20000 chars" in result
    assert "NOT a cutoff" in result
    assert "do not ask Claude to continue" in result


@pytest.mark.asyncio
async def test_stalled_subprocess_is_killed():
    """A worker that stops producing output is killed, not waited on forever."""
    mock_proc = _make_mock_proc([], stall=True)
    session = _fake_session(claude_timeout=0.05)

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await asyncio.wait_for(
            run_claude("test prompt", continue_session=False, session=session),
            timeout=5,
        )

    assert "timed out" in result.lower()
    mock_proc.kill.assert_called_once()
    assert session.claude_proc is None


@pytest.mark.asyncio
async def test_stall_returns_partial_output():
    """Output collected before the stall is handed back, not thrown away."""
    mock_proc = _make_mock_proc([_make_stream_line("got this far")], stall=True)
    session = _fake_session(claude_timeout=0.05)

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await asyncio.wait_for(
            run_claude("test prompt", continue_session=False, session=session),
            timeout=5,
        )

    assert "got this far" in result
    assert "timed out" in result.lower()


@pytest.mark.asyncio
async def test_slow_but_productive_run_is_not_killed():
    """Steady output keeps the run alive even past the idle timeout."""
    lines = [_make_stream_line(f"step {i}") for i in range(4)]
    mock_proc = _make_mock_proc(lines)
    session = _fake_session(claude_timeout=1)

    pending = list(lines)

    async def _slow_readline():
        await asyncio.sleep(0.05)
        return pending.pop(0) if pending else b""

    mock_proc.stdout.readline = _slow_readline

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await run_claude("test prompt", continue_session=False, session=session)

    assert "step 3" in result
    mock_proc.kill.assert_not_called()


@pytest.mark.asyncio
async def test_over_long_line_is_skipped():
    """A line past the stream limit raises ValueError; the run continues."""
    mock_proc = _make_mock_proc([_make_stream_line("after the big line")], raise_once=True)

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await run_claude("test prompt", continue_session=False)

    assert result == "after the big line"


@pytest.mark.asyncio
async def test_failure_surfaces_stderr():
    """Non-zero exit with no stdout surfaces the exit code and stderr tail."""
    mock_proc = _make_mock_proc([], returncode=1, stderr_lines=[b"boom: something broke\n"])

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await run_claude("test prompt", continue_session=False)

    assert "exited with code 1" in result
    assert "boom: something broke" in result


def test_claude_available_reflects_path():
    with patch("supervisor.claude.shutil.which", return_value="/usr/bin/claude"):
        assert claude_available() is True
    with patch("supervisor.claude.shutil.which", return_value=None):
        assert claude_available() is False
