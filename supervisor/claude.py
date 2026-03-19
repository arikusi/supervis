"""Claude Code subprocess management."""

import asyncio
import json
import os
from .display import BLUE, BOLD, DIM, R

_claude_proc: asyncio.subprocess.Process | None = None
_claude_first = True


def get_proc() -> asyncio.subprocess.Process | None:
    return _claude_proc


def reset_session() -> None:
    """Taze Claude session'ı için state sıfırla."""
    global _claude_first
    _claude_first = True


async def run_claude(prompt: str, continue_session: bool = True) -> str:
    global _claude_proc, _claude_first

    print(f"\n{BLUE}{BOLD}┌─ Claude Code ──────────────────────────────────────────{R}")
    print(f"{BLUE}{DIM}{prompt}{R}\n")

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
                            txt = block["text"]
                            print(f"{BLUE}{txt}{R}", end="", flush=True)
                            chunks.append(txt)
                        elif block.get("type") == "tool_use":
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            hint = (
                                inp.get("path")
                                or inp.get("command", "")
                                or inp.get("description", "")
                            )[:60]
                            print(f"\n{DIM}  ↳ {name}: {hint}{R}", flush=True)

            except json.JSONDecodeError:
                pass

    except asyncio.CancelledError:
        proc.terminate()
        raise
    finally:
        _claude_proc = None

    await proc.wait()
    print(f"\n{BLUE}{BOLD}└────────────────────────────────────────────────────────{R}\n")
    return "\n".join(chunks) or "(no output)"
