"""DeepSeek API client and streaming helper."""

import asyncio
import json
from openai import AsyncOpenAI
from .config import get_api_key
from .tools import TOOLS, execute_tool
from .display import CYAN, BOLD, DIM, R
from . import cost

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=get_api_key(), base_url="https://api.deepseek.com")
    return _client


async def stream_turn(messages: list) -> tuple[str, list]:
    """
    Send messages to DeepSeek, stream response.
    Returns (content, tool_calls).
    """
    client = get_client()

    print(f"\n{CYAN}{BOLD}DeepSeek:{R} ", end="", flush=True)

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        stream=True,
        stream_options={"include_usage": True},
        temperature=0.2,
    )

    content = ""
    tc_raw: dict[int, dict] = {}

    async for chunk in response:
        # Track usage from final chunk
        if chunk.usage:
            u = chunk.usage
            cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
            cost.record(u.prompt_tokens, u.completion_tokens, cached)
            print(f" {DIM}[{cost.summary()}]{R}", flush=True)

        choice = chunk.choices[0] if chunk.choices else None
        if not choice:
            continue
        delta = choice.delta

        if delta.content:
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
        print()

    tool_calls = list(tc_raw.values())
    return content, tool_calls


async def run_agent_loop(messages: list, interrupt_event: asyncio.Event | None = None) -> list:
    """
    Agentic loop: keep calling DeepSeek + executing tools until
    DeepSeek stops making tool calls or produces a user-facing response.
    Returns updated messages list.
    """
    while True:
        content, tool_calls = await stream_turn(messages)

        # DeepSeek spoke AND wants to call tools → return to user first
        if content and tool_calls:
            messages.append({"role": "assistant", "content": content})
            break

        messages.append({
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls
            ] if tool_calls else None,
        })

        # No tool calls → DeepSeek is done, return to user
        if not tool_calls:
            break

        # Check for interrupt before executing tools
        if interrupt_event and interrupt_event.is_set():
            break

        # Execute tools, append results, loop
        print()
        for tc in tool_calls:
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

    return messages
