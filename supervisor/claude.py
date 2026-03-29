"""Claude Code subprocess management."""

import asyncio
import json
import os
from .events import EventType, emit

_claude_proc: asyncio.subprocess.Process | None = None
_claude_first = True


def get_proc() -> asyncio.subprocess.Process | None:
    return _claude_proc


def reset_session() -> None:
    global _claude_first
    _claude_first = True


async def run_claude(prompt: str, continue_session: bool = True) -> str:
    global _claude_proc, _claude_first

    emit(EventType.CLAUDE_START, prompt=prompt)

    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--permission-mode", "bypassPermissions",
    ]
    if continue_session and not _claude_first:
        cmd.append("--continue")
    _claude_first = False

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=os.getcwd(),
        limit=1024 * 1024 * 10,
    )
    _claude_proc = proc

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
        _claude_proc = None

    await proc.wait()
    emit(EventType.CLAUDE_DONE, tool_count=tool_count)

    full = "\n".join(chunks) or "(no output)"
    max_len = 4000
    if len(full) > max_len:
        return full[:max_len] + f"\n... (truncated, {len(full)} chars total)"
    return full
