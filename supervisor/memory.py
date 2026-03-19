"""Conversation history management and summarization."""

from openai import AsyncOpenAI


async def summarize_if_needed(
    messages: list,
    client: AsyncOpenAI,
    threshold: int = 20,
) -> list:
    """When history exceeds threshold, summarize older messages to save tokens."""
    user_msgs = [m for m in messages if m["role"] != "system"]
    if len(user_msgs) <= threshold:
        return messages

    to_summarize = messages[1:-8]
    if not to_summarize:
        return messages

    print("\n\033[2m[Summarizing conversation history...]\033[0m", flush=True)
    try:
        resp = await client.chat.completions.create(
            model="deepseek-chat",
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
        return [
            messages[0],
            {"role": "assistant", "content": f"[Session summary: {summary}]"},
            *messages[-8:],
        ]
    except Exception:
        return messages
