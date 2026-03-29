"""Pure async orchestrator — no terminal I/O.

Called as a Textual worker from app.py. Reads from message_queue,
drives the DeepSeek agent loop, handles resets.
"""

import asyncio
from typing import Callable

from .deepseek import run_agent_loop, get_client
from .memory import summarize_if_needed
from .events import EventType, emit


async def orchestrate(
    message_queue: asyncio.Queue,
    interrupt_event: asyncio.Event,
    system_prompt: str,
    set_agent_running: Callable[[bool], None],
) -> None:
    """
    Main orchestration loop.

    Waits for messages from the queue, runs the agent loop,
    and repeats. Handles /reset via the __RESET__ sentinel.
    Only processes str items — ignores anything else (Textual internal events).
    """
    messages = [{"role": "system", "content": system_prompt}]
    client = get_client()

    while True:
        # Wait for next user message, skip non-string items
        try:
            item = await message_queue.get()
        except asyncio.CancelledError:
            break

        if not isinstance(item, str):
            continue

        user_input = item

        # Handle reset sentinel
        if user_input == "__RESET__":
            messages = [messages[0]]
            continue

        # Drain any additional queued string messages and combine
        extra = []
        while not message_queue.empty():
            try:
                item = message_queue.get_nowait()
                if not isinstance(item, str):
                    continue
                if item == "__RESET__":
                    messages = [messages[0]]
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
        messages.append({"role": "user", "content": user_input})
        messages = await summarize_if_needed(messages, client)
        interrupt_event.clear()

        # Run agent loop
        set_agent_running(True)
        try:
            messages = await run_agent_loop(messages, interrupt_event)
        finally:
            set_agent_running(False)
