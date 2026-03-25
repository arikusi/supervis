"""DeepSeek API client and streaming helper."""

import asyncio
import json
from openai import AsyncOpenAI
from .config import get_api_key
from .tools import TOOLS, execute_tool
from .display import CYAN, YELLOW, BOLD, DIM, R
from . import cost

_client: AsyncOpenAI | None = None

_RETRYABLE_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=get_api_key(), base_url="https://api.deepseek.com")
    return _client


async def _api_call(client: AsyncOpenAI, messages: list, quiet: bool = False) -> tuple[str, list, str]:
    """
    Single DeepSeek API call with streaming.
    Returns (content, tool_calls, reasoning_content).
    quiet=True suppresses the 'DeepSeek:' header (used for intermediate loop turns).
    """
    if not quiet:
        print(f"\n{CYAN}{BOLD}DeepSeek:{R} ", end="", flush=True)

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        stream=True,
        stream_options={"include_usage": True},
        extra_body={"thinking": {"type": "enabled"}},
    )

    content = ""
    reasoning = ""
    tc_raw: dict[int, dict] = {}
    thinking_shown = False

    async for chunk in response:
        if chunk.usage:
            u = chunk.usage
            cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
            cost.record(u.prompt_tokens, u.completion_tokens, cached)
            # Only show cost on non-quiet turns (when DeepSeek speaks to user)
            if not quiet:
                print(f"{DIM}[{cost.summary()}]{R}", flush=True)

        choice = chunk.choices[0] if chunk.choices else None
        if not choice:
            continue
        delta = choice.delta

        rc = getattr(delta, "reasoning_content", None)
        if rc:
            if not thinking_shown and not quiet:
                print(f"{DIM}thinking...{R} ", end="", flush=True)
                thinking_shown = True
            reasoning += rc

        if delta.content:
            if quiet:
                # First content on a quiet turn — show a header now
                print(f"\n{CYAN}{BOLD}DeepSeek:{R} ", end="", flush=True)
            print(f"{CYAN}{delta.content}{R}", end="", flush=True)
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

    if content:
        print(f" {DIM}[{cost.summary()}]{R}", flush=True)

    tool_calls = list(tc_raw.values())
    return content, tool_calls, reasoning


async def stream_turn(messages: list, quiet: bool = False) -> tuple[str, list, str]:
    """
    Send messages to DeepSeek with retry on transient errors.
    Returns (content, tool_calls, reasoning_content).
    """
    client = get_client()

    for attempt in range(_MAX_RETRIES):
        try:
            return await _api_call(client, messages, quiet=quiet)
        except Exception as e:
            status = getattr(e, "status_code", None) or getattr(e, "code", None)
            if isinstance(status, int) and status in _RETRYABLE_CODES and attempt < _MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                print(f"\n{YELLOW}{DIM}[API error {status}, retrying in {wait}s...]{R}", flush=True)
                await asyncio.sleep(wait)
                continue
            raise

    return "", [], ""


async def run_agent_loop(messages: list, interrupt_event: asyncio.Event | None = None) -> list:
    """
    Agentic loop: keep calling DeepSeek + executing tools until
    DeepSeek stops making tool calls.
    Returns updated messages list.
    """
    turn = 0
    while True:
        try:
            # First turn: show header. Subsequent tool-only turns: quiet.
            content, tool_calls, reasoning = await stream_turn(
                messages, quiet=(turn > 0),
            )
        except Exception as e:
            print(f"\n{YELLOW}[DeepSeek error: {e}]{R}", flush=True)
            break

        turn += 1

        # Build assistant message with reasoning_content for thinking mode
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
        messages.append(msg)

        if not tool_calls:
            break

        # Check for interrupt before executing tools
        if interrupt_event and interrupt_event.is_set():
            for tc in tool_calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": "(interrupted by user)",
                })
            break

        # Execute tools, append results, loop
        executed_ids: set[str] = set()
        for tc in tool_calls:
            if interrupt_event and interrupt_event.is_set():
                break
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args = {}

            result = await execute_tool(tc["name"], args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": str(result),
            })
            executed_ids.add(tc["id"])

        # Fill placeholders for interrupted tool calls
        for tc in tool_calls:
            if tc["id"] not in executed_ids:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": "(interrupted by user)",
                })

    return messages
