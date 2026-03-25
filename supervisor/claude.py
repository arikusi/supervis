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
    global _claude_first
    _claude_first = True


async def run_claude(prompt: str, continue_session: bool = True) -> str:
    global _claude_proc, _claude_first

    # Show the prompt DeepSeek sent (compact)
    prompt_preview = prompt[:120] + "..." if len(prompt) > 120 else prompt
    print(f"\n{BLUE}{BOLD}┌─ Claude Code ─────────────────────────────────────{R}")
    print(f"{BLUE}{DIM}  {prompt_preview}{R}")
    print(f"{BLUE}{BOLD}├───────────────────────────────────────────────────{R}")

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
    last_was_tool = False

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
                            if last_was_tool:
                                print()  # newline after tool calls
                                last_was_tool = False
                            print(f"{BLUE}{txt}{R}")
                            chunks.append(txt)

                        elif block.get("type") == "tool_use":
                            tool_count += 1
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            hint = (
                                inp.get("path")
                                or inp.get("command", "")[:50]
                                or inp.get("description", "")[:50]
                                or ""
                            )
                            if hint:
                                print(f"{DIM}  ↳ {name}: {hint}{R}", flush=True)
                            else:
                                print(f"{DIM}  ↳ {name}{R}", flush=True)
                            last_was_tool = True

            except json.JSONDecodeError:
                pass

    except asyncio.CancelledError:
        proc.terminate()
        raise
    finally:
        _claude_proc = None

    await proc.wait()
    summary = f" ({tool_count} tool calls)" if tool_count else ""
    print(f"{BLUE}{BOLD}└─ done{summary} ─────────────────────────────────────{R}\n")

    full = "\n".join(chunks) or "(no output)"
    # Truncate what goes back to DeepSeek (display already showed everything)
    max_len = 4000
    if len(full) > max_len:
        return full[:max_len] + f"\n... (truncated, {len(full)} chars total)"
    return full
