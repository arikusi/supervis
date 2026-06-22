"""Conversation history management and summarization."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session import Session


def _clean_for_summarize(messages: list) -> list:
    """Strip reasoning_content from messages before summarizing (saves tokens, not needed for summary)."""
    cleaned = []
    for m in messages:
        if "reasoning_content" in m:
            c = dict(m)
            del c["reasoning_content"]
            cleaned.append(c)
        else:
            cleaned.append(m)
    return cleaned


def _format_messages_for_summary(messages: list) -> str:
    """Format messages as clean markdown for the summarizer.

    Replaces the old str(messages)[:8000] approach which sent Python repr
    of nested dicts — unreadable for the LLM.
    """
    parts = []
    for m in messages:
        role = m.get("role", "unknown")
        content = m.get("content", "") or ""

        if role == "assistant":
            tool_calls = m.get("tool_calls", [])
            if tool_calls:
                tools = ", ".join(tc.get("function", {}).get("name", "?") for tc in tool_calls)
                parts.append(f"**Assistant** (called: {tools}): {content or '(tools only)'}")
            elif content:
                parts.append(f"**Assistant**: {content}")
        elif role == "tool":
            parts.append(f"**Tool result**: {content[:500]}")
        elif role == "user":
            parts.append(f"**User**: {content}")

    return "\n\n".join(parts)[:12000]


def _safe_tail_start(messages: list, keep: int) -> int:
    """Largest index <= len-keep that starts on a user message.

    The kept tail must begin on a user message: if it started on a tool result
    whose assistant tool_calls got summarized away, DeepSeek rejects the orphaned
    tool message ("must be a response to a preceding message with tool_calls").
    """
    start = max(1, len(messages) - keep)
    for i in range(start, 0, -1):
        if messages[i].get("role") == "user":
            return i
    return 1  # no safe split point — caller skips summarizing this round


async def summarize_if_needed(session: Session, threshold: int = 40) -> None:
    """When history exceeds threshold, summarize older messages to save tokens."""
    messages = session.messages
    user_msgs = [m for m in messages if m["role"] != "system"]
    if len(user_msgs) <= threshold:
        return

    tail_start = _safe_tail_start(messages, keep=12)
    if tail_start <= 1:
        return

    to_summarize = _clean_for_summarize(messages[1:tail_start])

    from .events import EventType, emit

    emit(EventType.SUMMARY)
    try:
        resp = await session.client.chat.completions.create(
            model=session.base_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize this conversation history concisely. "
                        "Preserve key decisions, code changes made, file names, and important context. "
                        "Be brief."
                    ),
                },
                {
                    "role": "user",
                    "content": _format_messages_for_summary(to_summarize),
                },
            ],
            max_tokens=600,
        )
        summary = resp.choices[0].message.content
        session.messages = [
            messages[0],
            {"role": "assistant", "content": f"[Session summary: {summary}]"},
            *messages[tail_start:],
        ]
    except Exception:
        pass  # Keep original messages on failure
