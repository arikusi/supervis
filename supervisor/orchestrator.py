"""Pure async orchestrator — no terminal I/O.

Called as a Textual worker from app.py. Reads from message_queue,
drives the DeepSeek agent loop, handles resets.
"""

import asyncio
from collections.abc import Callable

from .deepseek import run_agent_loop
from .events import EventType, emit
from .memory import summarize_if_needed
from .session import Session


async def orchestrate(
    message_queue: asyncio.Queue,
    session: Session,
    system_prompt: str,
    set_agent_running: Callable[[bool], None],
) -> None:
    """
    Main orchestration loop.

    Waits for messages from the queue, runs the agent loop,
    and repeats. Handles /reset via the __RESET__ sentinel.
    Only processes str items — ignores anything else (Textual internal events).
    """
    session.messages = [{"role": "system", "content": system_prompt}]

    while True:
        try:
            item = await message_queue.get()
        except asyncio.CancelledError:
            break

        if not isinstance(item, str):
            continue

        user_input = item

        # Handle reset sentinel
        if user_input == "__RESET__":
            session.reset()
            session.messages = [{"role": "system", "content": system_prompt}]
            continue

        # Drain any additional queued string messages and combine
        extra = []
        while not message_queue.empty():
            try:
                item = message_queue.get_nowait()
                if not isinstance(item, str):
                    continue
                if item == "__RESET__":
                    session.reset()
                    session.messages = [{"role": "system", "content": system_prompt}]
                    continue
                extra.append(item)
            except asyncio.QueueEmpty:
                break

        if extra:
            for msg in extra:
                emit(EventType.STATUS, text=f"[Queued] {msg}")
            user_input = user_input + "\n" + "\n".join(extra)

        # Clear queue count
        emit(EventType.QUEUE_UPDATE, count=0)

        # Add to conversation
        session.messages.append({"role": "user", "content": user_input})
        await summarize_if_needed(session)
        session.interrupt_event.clear()

        # Run agent loop
        set_agent_running(True)
        try:
            await run_agent_loop(session)
        finally:
            set_agent_running(False)
