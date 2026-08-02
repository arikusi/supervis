"""Tests for supervisor.orchestrator — the message loop that drives the agent."""

import asyncio
import contextlib
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supervisor.events import Event, EventType, subscribe, unsubscribe
from supervisor.orchestrator import orchestrate
from supervisor.queue import MessageQueue
from supervisor.session import Session

SYSTEM = "you are supervis"


def _make_session() -> Session:
    return Session(client=MagicMock())


async def _drive(queue: MessageQueue, session: Session, run_agent_loop, running: list | None = None) -> None:
    """Run orchestrate() until the queue is drained, then cancel it.

    orchestrate() loops forever by design, so the test drives it just far enough
    to consume what it was given and then stops it.
    """
    with patch("supervisor.orchestrator.run_agent_loop", run_agent_loop):
        task = asyncio.create_task(
            orchestrate(
                message_queue=queue,
                session=session,
                system_prompt=SYSTEM,
                set_agent_running=(running.append if running is not None else (lambda _: None)),
            )
        )
        for _ in range(100):
            await asyncio.sleep(0)
            if queue.empty():
                break
        await asyncio.sleep(0.01)  # let the agent-loop call settle
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class TestMessageHandling:
    @pytest.mark.asyncio
    async def test_seeds_the_system_prompt(self):
        session = _make_session()
        queue = MessageQueue()
        await _drive(queue, session, AsyncMock())
        assert session.messages[0] == {"role": "system", "content": SYSTEM}

    @pytest.mark.asyncio
    async def test_user_message_reaches_the_agent_loop(self):
        session = _make_session()
        queue = MessageQueue()
        queue.put("build the thing")
        await _drive(queue, session, AsyncMock())

        roles = [m["role"] for m in session.messages]
        assert roles == ["system", "user"]
        assert session.messages[1]["content"] == "build the thing"

    @pytest.mark.asyncio
    async def test_queued_messages_are_combined_into_one_turn(self):
        """Anything typed while the agent was busy joins the next turn."""
        session = _make_session()
        queue = MessageQueue()
        queue.put("first")
        queue.put("second")
        queue.put("third")

        loop = AsyncMock()
        await _drive(queue, session, loop)

        assert loop.await_count == 1, "queued input should not start three separate runs"
        assert session.messages[1]["content"] == "first\nsecond\nthird"

    @pytest.mark.asyncio
    async def test_non_string_items_are_ignored(self):
        session = _make_session()
        queue = MessageQueue()
        queue.put(object())  # type: ignore[arg-type]
        queue.put("real message")

        await _drive(queue, session, AsyncMock())
        contents = [m["content"] for m in session.messages if m["role"] == "user"]
        assert contents == ["real message"]


class TestReset:
    @pytest.mark.asyncio
    async def test_reset_sentinel_clears_history_and_does_not_run_the_agent(self):
        session = _make_session()
        session.messages = [{"role": "system", "content": "stale"}, {"role": "user", "content": "old"}]
        queue = MessageQueue()
        queue.put("__RESET__")

        loop = AsyncMock()
        await _drive(queue, session, loop)

        assert session.messages == [{"role": "system", "content": SYSTEM}]
        loop.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reset_inside_a_drained_batch_still_resets(self):
        session = _make_session()
        queue = MessageQueue()
        queue.put("something")
        queue.put("__RESET__")

        await _drive(queue, session, AsyncMock())
        assert session.messages[0]["content"] == SYSTEM


class TestFailureHandling:
    @pytest.mark.asyncio
    async def test_agent_crash_is_reported_and_the_loop_survives(self, caplog):
        session = _make_session()
        queue = MessageQueue()
        queue.put("do it")

        received: list[Event] = []
        subscribe(received.append)
        try:
            with caplog.at_level(logging.ERROR, logger="supervisor.orchestrator"):
                await _drive(queue, session, AsyncMock(side_effect=RuntimeError("boom")))
        finally:
            unsubscribe(received.append)

        errors = [e for e in received if e.type is EventType.DEEPSEEK_ERROR]
        assert errors, "a crash must surface to the user, not vanish"
        assert "crashed" in errors[0].data["error"].lower()
        assert "boom" in caplog.text

    @pytest.mark.asyncio
    async def test_agent_running_flag_is_cleared_even_on_crash(self):
        session = _make_session()
        queue = MessageQueue()
        queue.put("do it")

        running: list[bool] = []
        await _drive(queue, session, AsyncMock(side_effect=RuntimeError("boom")), running=running)

        assert running[0] is True
        assert running[-1] is False, "a crash must not leave the UI stuck in 'running'"

    @pytest.mark.asyncio
    async def test_interrupt_flag_is_cleared_before_each_run(self):
        session = _make_session()
        session.interrupt_event.set()
        queue = MessageQueue()
        queue.put("go")

        await _drive(queue, session, AsyncMock())
        assert not session.interrupt_event.is_set()
