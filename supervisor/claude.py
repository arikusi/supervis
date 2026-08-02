"""Claude Code subprocess management."""

import asyncio
import contextlib
import json
import logging
import os
import shutil

from .events import EventType, emit
from .session import Session

logger = logging.getLogger(__name__)

# Grace period for the process to exit once stdout has closed. The worker is
# done writing at that point, so this only guards against a child that refuses
# to leave — it is deliberately much shorter than the idle timeout.
_EXIT_GRACE = 10


def claude_available() -> bool:
    """True when the Claude Code CLI is on PATH."""
    return shutil.which("claude") is not None


def reset_session(session: Session) -> None:
    """Make the next run_claude start a fresh Claude Code session."""
    session.claude_first = True


def get_proc(session: Session) -> asyncio.subprocess.Process | None:
    """Return the running Claude subprocess, if any."""
    return session.claude_proc


async def _reap(proc: asyncio.subprocess.Process, timeout: int = 5) -> None:
    """Best-effort wait for a killed/terminated child so it isn't left a zombie."""
    with contextlib.suppress(Exception):
        await asyncio.wait_for(proc.wait(), timeout=timeout)


async def run_claude(prompt: str, continue_session: bool = True, *, session: Session) -> str:
    emit(EventType.CLAUDE_START, prompt=prompt)

    is_first = session.claude_first
    idle_timeout = session.claude_timeout
    truncation = session.truncation_limit

    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "bypassPermissions",
    ]
    if continue_session and not is_first:
        cmd.append("--continue")

    session.claude_first = False

    logger.debug("Claude subprocess start: %s", " ".join(cmd[:4]))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=os.getcwd(),
        limit=1024 * 1024 * 10,
    )
    session.claude_proc = proc

    # Drain stderr concurrently. If we only read stdout and leave stderr=PIPE
    # unread, a chatty subprocess can fill the ~64KB pipe buffer and block,
    # deadlocking until the timeout kills it.
    stderr_chunks: list[str] = []

    async def _drain_stderr() -> None:
        if proc.stderr is None:
            return
        try:
            async for raw in proc.stderr:
                if len(stderr_chunks) < 500:
                    stderr_chunks.append(raw.decode("utf-8", errors="replace"))
        except Exception:
            pass

    stderr_task = asyncio.create_task(_drain_stderr())

    chunks: list[str] = []
    tool_count = 0
    stalled = False

    try:
        assert proc.stdout is not None
        while True:
            # Each read is bounded, so a worker that hangs mid-task is caught.
            # A plain `async for` over stdout would block forever and the exit
            # timeout below would never be reached.
            #
            # The budget is silence, not total run time. Claude Code emits a line
            # per assistant turn and per tool result, so it goes quiet for exactly
            # as long as its current tool takes — a full test suite or a container
            # build is minutes of legitimate silence. Hence the generous default.
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=idle_timeout)
            except asyncio.TimeoutError:
                stalled = True
                break
            except ValueError:
                # Single line longer than the stream limit. readline() clears the
                # buffer before raising, so skipping it is safe.
                logger.warning("Claude subprocess emitted an over-long line; skipped")
                continue

            if not raw:
                break  # EOF

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
        stderr_task.cancel()
        await _reap(proc)
        raise
    finally:
        session.claude_proc = None

    if stalled:
        proc.kill()
        await _reap(proc)
        stderr_task.cancel()
        logger.warning("Claude subprocess produced no output for %ds; killed", idle_timeout)
        emit(EventType.CLAUDE_ERROR, error=f"Claude Code timed out ({idle_timeout}s with no output)")
        # Hand back whatever did arrive — a partial answer beats none, and the
        # wording keeps the supervisor's failure detection working.
        note = f"(Claude Code timed out: no output for {idle_timeout}s, subprocess killed)"
        partial = "\n".join(chunks).strip()
        return f"{partial}\n\n{note}" if partial else note

    # stdout closed, so the worker is done writing. It should exit promptly.
    try:
        await asyncio.wait_for(proc.wait(), timeout=_EXIT_GRACE)
    except asyncio.TimeoutError:
        proc.kill()
        await _reap(proc)
        logger.warning("Claude subprocess did not exit %ds after closing stdout; killed", _EXIT_GRACE)

    with contextlib.suppress(Exception):
        await asyncio.wait_for(stderr_task, timeout=5)

    logger.debug("Claude subprocess done (tool_count=%d, rc=%s)", tool_count, proc.returncode)
    emit(EventType.CLAUDE_DONE, tool_count=tool_count)

    # A hard failure that produced no usable stdout would otherwise look like a
    # plain "(no output)" — surface the exit code and stderr tail instead.
    if not chunks and proc.returncode not in (0, None):
        err_tail = "".join(stderr_chunks).strip()[-500:]
        msg = f"Claude Code exited with code {proc.returncode}"
        if err_tail:
            msg += f": {err_tail}"
        emit(EventType.CLAUDE_ERROR, error=msg)
        return f"({msg})"

    full = "\n".join(chunks) or "(no output)"
    if len(full) > truncation:
        # IMPORTANT: only the head is forwarded to the supervisor to bound its
        # context, but the worker's reply was complete. The old marker read like
        # a cutoff and made the supervisor ask Claude to "continue" in a loop, so
        # spell out that this is a display limit, not a truncated answer.
        return (
            full[:truncation] + f"\n\n[supervis note: Claude's full reply was {len(full)} chars; "
            f"only the first {truncation} are shown here to bound context. "
            "This is a display limit, NOT a cutoff — Claude finished its work. "
            "Treat the output as complete; do not ask Claude to continue or resume.]"
        )
    return full
