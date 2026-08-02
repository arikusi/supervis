"""Tests for supervisor.deepseek module — retry logic and agent loop."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

from supervisor.deepseek import _api_call, _retry_plan, run_agent_loop, stream_turn
from supervisor.events import Event, EventType, subscribe, unsubscribe
from supervisor.session import STUCK_CAP, Session


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
        with patch("supervisor.deepseek._api_call", side_effect=mock_api_call), pytest.raises(FakeAPIError):
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

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self):
        """Dropped connections carry no status code and used to be fatal."""
        call_count = 0

        async def mock_api_call(session, quiet=False):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise APIConnectionError(request=httpx.Request("POST", "https://api.deepseek.com"))
            return "recovered", [], ""

        session = _make_session([{"role": "system", "content": "sys"}])
        with patch("supervisor.deepseek._api_call", side_effect=mock_api_call):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                content, _, _ = await stream_turn(session)

        assert call_count == 2
        assert content == "recovered"

    @pytest.mark.asyncio
    async def test_retries_on_read_timeout(self):
        """APITimeoutError subclasses APIConnectionError, so it retries too."""
        call_count = 0

        async def mock_api_call(session, quiet=False):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise APITimeoutError(request=httpx.Request("POST", "https://api.deepseek.com"))
            return "recovered", [], ""

        session = _make_session([{"role": "system", "content": "sys"}])
        with patch("supervisor.deepseek._api_call", side_effect=mock_api_call):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                content, _, _ = await stream_turn(session)

        assert call_count == 2
        assert content == "recovered"


class TestRetryPlan:
    def test_connection_error_is_retryable(self):
        exc = APIConnectionError(request=httpx.Request("POST", "https://api.deepseek.com"))
        plan = _retry_plan(exc, 0)
        assert plan is not None
        wait, reason = plan
        assert wait == 2
        assert reason == "Connection error"

    def test_retryable_status_reports_the_code(self):
        assert _retry_plan(FakeAPIError(503), 1) == (4, "API error 503")

    def test_client_error_is_not_retryable(self):
        assert _retry_plan(FakeAPIError(400), 0) is None

    def test_unknown_exception_is_not_retryable(self):
        assert _retry_plan(RuntimeError("boom"), 0) is None

    def test_backoff_grows_with_attempt(self):
        waits = [_retry_plan(FakeAPIError(429), i)[0] for i in range(3)]
        assert waits == [2, 4, 8]


class FakeDelta:
    def __init__(self, content=None, reasoning=None, tool_calls=None):
        self.content = content
        self.reasoning_content = reasoning
        self.tool_calls = tool_calls


class FakeChunk:
    def __init__(self, content=None, reasoning=None, tool_calls=None, usage=None):
        self.usage = usage
        self.choices = [SimpleNamespace(delta=FakeDelta(content, reasoning, tool_calls))]


class FakeStream:
    """Stands in for the openai AsyncStream.

    Records whether it was closed, and counts how many chunks were actually
    pulled — an interrupt that works stops pulling.
    """

    def __init__(self, chunks, before_chunk=None):
        self._chunks = list(chunks)
        self.closed = False
        self.yielded = 0
        self._before_chunk = before_chunk

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for i, chunk in enumerate(self._chunks):
            if self._before_chunk:
                self._before_chunk(i)
            self.yielded += 1
            yield chunk

    async def close(self):
        self.closed = True


def _session_with_stream(stream) -> Session:
    session = Session(client=MagicMock())
    session.messages = [{"role": "system", "content": "sys"}]
    session.client.chat.completions.create = AsyncMock(return_value=stream)
    return session


class TestStreamInterrupt:
    @pytest.mark.asyncio
    async def test_interrupt_stops_reading_and_closes_the_stream(self):
        session = None

        def interrupt_before_second(index: int) -> None:
            if index == 1:
                session.interrupt_event.set()

        stream = FakeStream(
            [FakeChunk(content="one"), FakeChunk(content="two"), FakeChunk(content="three")],
            before_chunk=interrupt_before_second,
        )
        session = _session_with_stream(stream)

        content, tool_calls, _ = await _api_call(session)

        assert stream.closed, "an interrupted stream must be closed, not abandoned"
        assert content == "one", "content after the interrupt should be dropped"
        assert stream.yielded == 2, "reading must stop, not run the stream to completion"
        assert tool_calls == []

    @pytest.mark.asyncio
    async def test_partial_tool_calls_are_dropped_on_interrupt(self):
        """Half-streamed tool calls have truncated JSON and would break the next call."""
        partial = [SimpleNamespace(index=0, id="tc1", function=SimpleNamespace(name="run_claude", arguments='{"pro'))]
        stream = FakeStream([FakeChunk(tool_calls=partial), FakeChunk(tool_calls=partial)])
        session = _session_with_stream(stream)
        session.interrupt_event.set()

        content, tool_calls, _ = await _api_call(session)

        assert tool_calls == []
        assert content == "(interrupted)", "the assistant turn still needs a body"

    @pytest.mark.asyncio
    async def test_uninterrupted_stream_keeps_its_tool_calls(self):
        calls = [SimpleNamespace(index=0, id="tc1", function=SimpleNamespace(name="run_claude", arguments='{"a":1}'))]
        stream = FakeStream([FakeChunk(tool_calls=calls)])
        session = _session_with_stream(stream)

        _, tool_calls, _ = await _api_call(session)

        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "run_claude"
        assert not stream.closed


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

    @pytest.mark.asyncio
    async def test_tool_execution_error_doesnt_crash_loop(self):
        """If execute_tool raises, the error becomes the tool result and the loop continues."""
        call_count = 0

        async def mock_stream_turn(session, quiet=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "", [{"id": "tc1", "name": "run_claude", "arguments": '{"prompt": "test"}'}], ""
            return "Done after error", [], ""

        async def mock_execute_tool(name, args, session):
            raise RuntimeError("subprocess exploded")

        with patch("supervisor.deepseek.stream_turn", side_effect=mock_stream_turn):
            with patch("supervisor.deepseek.execute_tool", side_effect=mock_execute_tool):
                session = _make_session([{"role": "system", "content": "sys"}])
                await run_agent_loop(session)

        assert call_count == 2  # loop continued after error
        tool_msgs = [m for m in session.messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert "subprocess exploded" in tool_msgs[0]["content"]


class TestLoopCaps:
    @pytest.mark.asyncio
    async def test_max_turns_stops_a_model_that_never_stops_calling_tools(self):
        """The loop's only natural exit is the model choosing to stop. This is the backstop."""
        calls = 0

        async def always_calls_a_tool(session, quiet=False):
            nonlocal calls
            calls += 1
            return "", [{"id": f"tc{calls}", "name": "get_git_status", "arguments": "{}"}], ""

        session = _make_session([{"role": "system", "content": "sys"}])
        session.max_turns = 4

        received: list[Event] = []
        subscribe(received.append)
        try:
            with patch("supervisor.deepseek.stream_turn", side_effect=always_calls_a_tool):
                with patch("supervisor.deepseek.execute_tool", new_callable=AsyncMock, return_value="clean"):
                    await asyncio.wait_for(run_agent_loop(session), timeout=5)
        finally:
            unsubscribe(received.append)

        assert calls == 4, f"expected the cap to stop it at 4 turns, ran {calls}"
        notes = [e.data.get("text", "") for e in received if e.type is EventType.STATUS]
        assert any("max_turns" in n for n in notes), "the user has to be told why it stopped"

    @pytest.mark.asyncio
    async def test_max_turns_zero_disables_the_cap(self):
        calls = 0

        async def stops_on_its_own(session, quiet=False):
            nonlocal calls
            calls += 1
            if calls >= 3:
                return "done", [], ""
            return "", [{"id": f"tc{calls}", "name": "get_git_status", "arguments": "{}"}], ""

        session = _make_session([{"role": "system", "content": "sys"}])
        session.max_turns = 0

        with patch("supervisor.deepseek.stream_turn", side_effect=stops_on_its_own):
            with patch("supervisor.deepseek.execute_tool", new_callable=AsyncMock, return_value="clean"):
                await asyncio.wait_for(run_agent_loop(session), timeout=5)

        assert calls == 3

    @pytest.mark.asyncio
    async def test_repeated_failures_stop_the_loop_and_hand_back(self):
        """Past the stuck cap, grinding costs money and gets nowhere."""
        calls = 0

        async def always_dispatches_claude(session, quiet=False):
            nonlocal calls
            calls += 1
            return "", [{"id": f"tc{calls}", "name": "run_claude", "arguments": '{"prompt": "fix it"}'}], ""

        session = _make_session([{"role": "system", "content": "sys"}])

        received: list[Event] = []
        subscribe(received.append)
        try:
            with patch("supervisor.deepseek.stream_turn", side_effect=always_dispatches_claude):
                with patch(
                    "supervisor.deepseek.execute_tool",
                    new_callable=AsyncMock,
                    return_value="Traceback (most recent call last): boom",
                ):
                    await asyncio.wait_for(run_agent_loop(session), timeout=5)
        finally:
            unsubscribe(received.append)

        assert calls == STUCK_CAP, f"should stop at the stuck cap, ran {calls} turns"
        notes = [e.data.get("text", "") for e in received if e.type is EventType.STATUS]
        assert any("stuck" in n.lower() for n in notes)

    @pytest.mark.asyncio
    async def test_history_is_compacted_inside_a_long_run(self):
        """A single request can run dozens of turns without returning to the user."""
        calls = 0

        async def keeps_going(session, quiet=False):
            nonlocal calls
            calls += 1
            if calls > 30:
                return "done", [], ""
            return "", [{"id": f"tc{calls}", "name": "get_git_status", "arguments": "{}"}], ""

        session = _make_session([{"role": "system", "content": "sys"}])
        session.max_turns = 0

        with patch("supervisor.deepseek.stream_turn", side_effect=keeps_going):
            with patch("supervisor.deepseek.execute_tool", new_callable=AsyncMock, return_value="clean"):
                with patch("supervisor.deepseek.summarize_if_needed", new_callable=AsyncMock) as mock_sum:
                    await asyncio.wait_for(run_agent_loop(session), timeout=5)

        assert mock_sum.await_count > 0, "the loop must compact its own history, not only on new input"
