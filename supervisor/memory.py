"""Conversation history management and summarization."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session import Session

logger = logging.getLogger(__name__)

KEEP_TAIL = 12
DEFAULT_THRESHOLD = 40


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
    """Largest index <= len-keep that is a valid place to resume from.

    The kept tail must not open on a tool result whose assistant `tool_calls`
    got summarized away — DeepSeek rejects that with "must be a response to a
    preceding message with tool_calls". Any user or assistant message is a fine
    boundary: an assistant that made tool calls carries its results along in the
    tail behind it.
    """
    start = max(1, len(messages) - keep)
    for i in range(start, 0, -1):
        if messages[i].get("role") in ("user", "assistant"):
            return i
    return 1  # no safe split point — caller skips summarizing this round


async def summarize_if_needed(session: Session, threshold: int = DEFAULT_THRESHOLD) -> bool:
    """Compact older history once it exceeds threshold. Returns True if it did.

    Safe to call mid-agent-loop: a long single request can run dozens of turns
    without ever returning to the user, and that history has to be bounded too.
    """
    messages = session.messages
    if len([m for m in messages if m["role"] != "system"]) <= threshold:
        return False

    tail_start = _safe_tail_start(messages, keep=KEEP_TAIL)
    if tail_start <= 1:
        logger.debug("No safe split point for summarization; skipping")
        return False

    to_summarize = _clean_for_summarize(messages[1:tail_start])

    from .events import EventType, emit

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
    except Exception:
        # Losing a summary is survivable — the conversation just stays long — but
        # it used to vanish without a trace, which made context bloat unexplainable.
        logger.exception("Summarization failed; keeping full history")
        return False

    # The summary goes in as a user turn so the tail can open on either role
    # without producing two assistant messages back to back.
    session.messages = [
        messages[0],
        {"role": "user", "content": f"[Session summary: {summary}]"},
        *messages[tail_start:],
    ]
    logger.debug("Summarized %d messages down to 1", tail_start - 1)
    emit(EventType.SUMMARY)
    return True
