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


async def summarize_if_needed(session: Session, threshold: int = 40) -> None:
    """When history exceeds threshold, summarize older messages to save tokens."""
    messages = session.messages
    user_msgs = [m for m in messages if m["role"] != "system"]
    if len(user_msgs) <= threshold:
        return

    to_summarize = messages[1:-12]
    if not to_summarize:
        return

    to_summarize = _clean_for_summarize(to_summarize)

    from .events import EventType, emit
    emit(EventType.SUMMARY)
    try:
        resp = await session.client.chat.completions.create(
            model=session.model,
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
                    "content": str(to_summarize)[:8000],
                },
            ],
            max_tokens=600,
        )
        summary = resp.choices[0].message.content
        session.messages = [
            messages[0],
            {"role": "assistant", "content": f"[Session summary: {summary}]"},
            *messages[-12:],
        ]
    except Exception:
        pass  # Keep original messages on failure
