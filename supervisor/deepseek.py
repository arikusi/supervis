"""DeepSeek API client and streaming helper."""

import asyncio
import json
import logging

from .events import EventType, emit
from .session import Session
from .tools import TOOLS, execute_tool

logger = logging.getLogger(__name__)

_RETRYABLE_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3


async def _api_call(session: Session, quiet: bool = False) -> tuple[str, list, str]:
    """
    Single DeepSeek API call with streaming.
    Returns (content, tool_calls, reasoning_content).
    """
    if not quiet:
        emit(EventType.DEEPSEEK_START)

    # Always signal the status bar, even in quiet mode
    emit(EventType.DEEPSEEK_THINKING)

    # Strip reasoning_content from older turns before sending
    session.strip_old_reasoning()

    # Thinking mode: only for deepseek-chat when thinking=True
    # deepseek-reasoner has thinking built-in, extra_body would be redundant
    extra_body = None
    if session.model == "deepseek-chat" and session.thinking:
        extra_body = {"thinking": {"type": "enabled"}}

    response = await session.client.chat.completions.create(  # type: ignore[call-overload]
        model=session.model,
        messages=session.messages,
        tools=TOOLS,
        tool_choice="auto",
        stream=True,
        stream_options={"include_usage": True},
        extra_body=extra_body,
    )

    content = ""
    reasoning = ""
    tc_raw: dict[int, dict] = {}
    header_shown = not quiet

    async for chunk in response:
        if chunk.usage:
            u = chunk.usage
            cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
            session.cost.record(u.prompt_tokens, u.completion_tokens, cached)

        choice = chunk.choices[0] if chunk.choices else None
        if not choice:
            continue
        delta = choice.delta

        rc = getattr(delta, "reasoning_content", None)
        if rc:
            reasoning += rc
            if session.show_reasoning:
                emit(EventType.DEEPSEEK_REASONING, text=rc)

        if delta.content:
            if not header_shown:
                emit(EventType.DEEPSEEK_START)
                header_shown = True
            emit(EventType.DEEPSEEK_TOKEN, text=delta.content)
            content += delta.content

        if delta.tool_calls:
            for tc in delta.tool_calls:
                i = tc.index
                if i not in tc_raw:
                    tc_raw[i] = {"id": "", "name": "", "arguments": ""}
                if tc.id:
                    tc_raw[i]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        tc_raw[i]["name"] = tc.function.name
                    if tc.function.arguments:
                        tc_raw[i]["arguments"] += tc.function.arguments

    emit(EventType.DEEPSEEK_DONE, cost=session.cost.summary())

    tool_calls = list(tc_raw.values())
    return content, tool_calls, reasoning


async def stream_turn(session: Session, quiet: bool = False) -> tuple[str, list, str]:
    """
    Send messages to DeepSeek with retry on transient errors.
    Returns (content, tool_calls, reasoning_content).
    """
    # Budget check before API call
    ok, warning = session.check_budget()
    if not ok:
        logger.warning("Budget exceeded: %s", warning)
        emit(EventType.DEEPSEEK_ERROR, error=warning)
        return "", [], ""
    if warning:
        emit(EventType.STATUS, text=warning)

    logger.debug("stream_turn start (model=%s, quiet=%s, messages=%d)", session.model, quiet, len(session.messages))
    for attempt in range(_MAX_RETRIES):
        try:
            result = await _api_call(session, quiet=quiet)
            logger.debug("stream_turn done (content=%d chars, tools=%d)", len(result[0]), len(result[1]))
            return result
        except Exception as e:
            status = getattr(e, "status_code", None) or getattr(e, "code", None)
            if isinstance(status, int) and status in _RETRYABLE_CODES and attempt < _MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                logger.warning("API error %s, retry %d/%d in %ds", status, attempt + 1, _MAX_RETRIES, wait)
                emit(EventType.DEEPSEEK_RETRY, status=status, wait=wait)
                await asyncio.sleep(wait)
                continue
            logger.exception("API call failed (non-retryable)")
            raise

    return "", [], ""


async def run_agent_loop(session: Session) -> None:
    """
    Agentic loop: keep calling DeepSeek + executing tools until
    DeepSeek stops making tool calls.
    """
    logger.debug("agent loop start")
    turn = 0
    while True:
        try:
            content, tool_calls, reasoning = await stream_turn(
                session,
                quiet=(turn > 0),
            )
        except Exception as e:
            logger.exception("Agent loop turn %d failed", turn)
            emit(EventType.DEEPSEEK_ERROR, error=str(e))
            break

        turn += 1

        msg: dict = {"role": "assistant", "content": content or None}
        if reasoning:
            msg["reasoning_content"] = reasoning
        if tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls
            ]
        session.messages.append(msg)

        if not tool_calls:
            break

        if session.interrupt_event.is_set():
            for tc in tool_calls:
                session.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": "(interrupted by user)",
                    }
                )
            break

        executed_ids: set[str] = set()
        for tc in tool_calls:
            if session.interrupt_event.is_set():
                break
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args = {}

            try:
                result = await execute_tool(tc["name"], args, session)
            except Exception as e:
                logger.exception("Tool %s failed", tc["name"])
                result = f"Error executing {tc['name']}: {e}"
                emit(EventType.DEEPSEEK_ERROR, error=f"Tool '{tc['name']}' failed: {e}")
            session.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result),
                }
            )
            executed_ids.add(tc["id"])

        for tc in tool_calls:
            if tc["id"] not in executed_ids:
                session.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": "(interrupted by user)",
                    }
                )
