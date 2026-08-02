"""DeepSeek API client and streaming helper."""

import asyncio
import contextlib
import json
import logging

from openai import APIConnectionError

from .events import EventType, emit
from .memory import summarize_if_needed
from .session import Session
from .tools import TOOLS, execute_tool

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Applied per read, not per request, so a healthy stream can run as long as it
# likes. Generous on purpose: prefill on a long conversation can take a while to
# produce the first chunk, and killing a live request costs more than waiting.
REQUEST_TIMEOUT = 300.0

_RETRYABLE_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3


def _retry_plan(exc: Exception, attempt: int) -> tuple[int, str] | None:
    """Return (seconds_to_wait, reason) for a retryable error, else None.

    APITimeoutError subclasses APIConnectionError, so both dropped connections
    and read timeouts land in the first branch. They carry no status code, which
    is why checking status alone used to let them through as fatal.
    """
    wait = 2 ** (attempt + 1)
    if isinstance(exc, APIConnectionError):
        return wait, "Connection error"
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int) and status in _RETRYABLE_CODES:
        return wait, f"API error {status}"
    return None


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

    # Thinking mode: both V4 models toggle it the same way via extra_body. On pro
    # turns we also raise the reasoning effort, since pro is only used for the hard
    # moments where the extra deliberation is worth paying for.
    #
    # Only DeepSeek gets this. `thinking` is a DeepSeek extension, and sending it
    # to another OpenAI-compatible endpoint is a 400 waiting to happen — those
    # providers expose their own reasoning controls under different names.
    extra_body: dict | None = None
    if session.model.startswith("deepseek-v4"):
        extra_body = {"thinking": {"type": "enabled" if session.thinking else "disabled"}}
        if session.model == session.pro_model and session.thinking:
            extra_body["reasoning_effort"] = session.reasoning_effort

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
    interrupted = False

    async for chunk in response:
        # Ctrl+Z during a long reasoning turn used to do nothing visible: the
        # event was set but nobody read it until the stream had finished on its
        # own. Closing the response here is what makes the key feel connected.
        if session.interrupt_event.is_set():
            interrupted = True
            logger.debug("stream interrupted by user after %d chars", len(content))
            with contextlib.suppress(Exception):
                await response.close()
            break

        if chunk.usage:
            u = chunk.usage
            cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
            session.cost.record(u.prompt_tokens, u.completion_tokens, cached, session.model)

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

    if interrupted:
        # Half-streamed tool calls have truncated JSON arguments and possibly no
        # id yet. Dropping them leaves a plain assistant message, which is a
        # valid point to resume from; keeping them would poison the next request.
        return content or "(interrupted)", [], reasoning

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
            plan = _retry_plan(e, attempt)
            if plan and attempt < _MAX_RETRIES - 1:
                wait, reason = plan
                logger.warning("%s, retry %d/%d in %ds", reason, attempt + 1, _MAX_RETRIES, wait)
                emit(EventType.DEEPSEEK_RETRY, reason=reason, wait=wait)
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
        # Hard stop. The loop's only natural exit is the model deciding to stop
        # calling tools, so a model that keeps re-dispatching the same step would
        # otherwise run until the budget or the user stopped it.
        if session.max_turns and turn >= session.max_turns:
            logger.warning("Agent loop hit max_turns=%d", session.max_turns)
            emit(
                EventType.STATUS,
                text=(
                    f"Stopped after {session.max_turns} turns (max_turns). "
                    "Send a message to carry on, or raise max_turns in config."
                ),
            )
            break

        # Pick flash vs pro for this turn (tiering / escalation) before calling out.
        changed, reason = session.select_turn_model()
        if changed:
            emit(EventType.MODEL_SWITCH, model=session.model, reason=reason)

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

            # Self-correction: watch how Claude Code did and escalate if stuck.
            if tc["name"] == "run_claude":
                session.note_claude_result(args.get("prompt", ""), str(result))

        for tc in tool_calls:
            if tc["id"] not in executed_ids:
                session.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": "(interrupted by user)",
                    }
                )

        # Inject a one-time replan nudge when the failure streak triggered escalation.
        nudge = session.consume_nudge()
        if nudge:
            session.messages.append({"role": "user", "content": nudge})
            emit(EventType.STATUS, text="supervis: stepping back to re-plan after repeated failures")
        # Past the stuck cap, grinding on costs money and gets nowhere. Hand back.
        if session.consume_stuck_alert():
            emit(
                EventType.STATUS,
                text=(
                    "supervis is stuck — several attempts in a row failed the same way, so it stopped. "
                    "Send a hint about what to try instead, or /model pro to steer it yourself."
                ),
            )
            break

        # A single request can run dozens of turns without returning to the user,
        # so the history has to be compacted here too, not only on new input.
        await summarize_if_needed(session)
