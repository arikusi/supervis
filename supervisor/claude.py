"""Claude Code subprocess management."""

import asyncio
import json
import os
from .events import EventType, emit

# Module-level fallback for backward compat (used when no session passed)
_claude_first = True


def reset_session(session=None) -> None:
    global _claude_first
    if session:
        session.claude_first = True
    else:
        _claude_first = True


def get_proc(session=None) -> asyncio.subprocess.Process | None:
    if session:
        return session.claude_proc
    return None


async def run_claude(prompt: str, continue_session: bool = True, session=None) -> str:
    global _claude_first

    emit(EventType.CLAUDE_START, prompt=prompt)

    # Determine first-call state
    is_first = session.claude_first if session else _claude_first
    timeout = session.claude_timeout if session else 300
    truncation = session.truncation_limit if session else 4000

    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--permission-mode", "bypassPermissions",
    ]
    if continue_session and not is_first:
        cmd.append("--continue")

    # Mark first call as done
    if session:
        session.claude_first = False
    else:
        _claude_first = False

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=os.getcwd(),
        limit=1024 * 1024 * 10,
    )
    if session:
        session.claude_proc = proc

    chunks: list[str] = []
    tool_count = 0

    try:
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                t = data.get("type", "")

                if t == "assistant":
                    for block in data.get("message", {}).get("content", []):
                        if not isinstance(block, dict):
                            continue

                        if block.get("type") == "text":
                            txt = block["text"].strip()
                            if not txt:
                                continue
                            emit(EventType.CLAUDE_TEXT, text=txt)
                            chunks.append(txt)

                        elif block.get("type") == "tool_use":
                            tool_count += 1
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            hint = (
                                inp.get("path")
                                or inp.get("pattern")
                                or inp.get("file_path")
                                or inp.get("command", "")[:50]
                                or inp.get("description", "")[:50]
                                or ""
                            )
                            label = f"{name}: {hint}" if hint else name
                            emit(EventType.CLAUDE_TOOL, label=label)

                elif t == "result":
                    result_text = data.get("result", "").strip()
                    if result_text and result_text not in chunks:
                        emit(EventType.CLAUDE_TEXT, text=result_text)
                        chunks.append(result_text)

            except json.JSONDecodeError:
                pass

    except asyncio.CancelledError:
        proc.terminate()
        raise
    finally:
        if session:
            session.claude_proc = None

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        emit(EventType.CLAUDE_ERROR, error=f"Claude Code subprocess timed out ({timeout // 60} min)")
        return f"(Claude Code timed out after {timeout // 60} minutes)"

    emit(EventType.CLAUDE_DONE, tool_count=tool_count)

    full = "\n".join(chunks) or "(no output)"
    if len(full) > truncation:
        return full[:truncation] + f"\n... (truncated, {len(full)} chars total)"
    return full
