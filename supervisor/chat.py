"""Main chat loop, signal handling, input queue."""

import asyncio
import os
import sys
import termios
import tty

try:
    import readline  # arrow keys + history
except ImportError:
    pass

from .deepseek import run_agent_loop
from .memory import summarize_if_needed
from .prompts import SYSTEM_PROMPT
from .display import GREEN, BOLD, DIM, YELLOW, CYAN, R, header
from .claude import get_proc, reset_session
from .deepseek import get_client
from . import cost

_EXIT_COMMANDS   = {"exit", "quit", "q", "çıkış"}
_BUILTIN_COMMANDS = {"/reset", "/help"}

# Sentinels
_ESC    = "__ESC__"
_CTRL_C = "__CTRL_C__"


# ─── Raw stdin reader ────────────────────────────────────────────────────────

def _read_line_raw() -> str:
    """
    Read one line in raw terminal mode.
    Detects ESC → returns _ESC
    Detects Ctrl+C → returns _CTRL_C
    Handles backspace + echo manually.
    Preserves readline history for normal lines.
    """
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buf: list[str] = []

    try:
        tty.setraw(fd)
        while True:
            b = sys.stdin.buffer.read(1)
            if not b:
                return ""

            byte = b[0]

            if byte == 0x1b:  # ESC — drain any escape sequence (arrow keys etc.)
                sys.stdin.buffer.read(0)
                return _ESC

            if byte == 0x03:  # Ctrl+C
                return _CTRL_C

            if byte in (0x0d, 0x0a):  # Enter
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                line = "".join(buf)
                if line:
                    try:
                        readline.add_history(line)
                    except Exception:
                        pass
                return line

            if byte == 0x7f:  # Backspace
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()

            elif 32 <= byte <= 126:  # Printable ASCII
                ch = chr(byte)
                buf.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


async def _stdin_reader(queue: asyncio.Queue) -> None:
    """Runs _read_line_raw in executor, puts results to queue."""
    loop = asyncio.get_running_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, _read_line_raw)
            await queue.put(line)
        except (EOFError, asyncio.CancelledError):
            break
        except Exception:
            break


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _drain_queue(queue: asyncio.Queue) -> list[str]:
    items = []
    while not queue.empty():
        try:
            items.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return items


def _handle_builtin(cmd: str, messages: list) -> tuple[list, bool]:
    if cmd.lower() == "/reset":
        reset_session()
        cost.reset()
        new_messages = [messages[0]]
        print(f"{YELLOW}Session reset.{R}\n")
        return new_messages, True

    if cmd.lower() == "/help":
        print(
            f"\n{CYAN}Commands:{R}\n"
            f"  {BOLD}/reset{R}        — reset Claude session and conversation\n"
            f"  {BOLD}/help{R}         — show this\n"
            f"  {BOLD}exit{R}          — quit\n"
            f"  {BOLD}ESC{R}           — interrupt agent, return to prompt\n"
            f"  {BOLD}Ctrl+C{R}        — interrupt agent (first) / exit (second)\n"
            f"\n{DIM}Type anytime — messages queue while agent works.{R}\n"
        )
        return messages, True

    return messages, False


# ─── Main loop ───────────────────────────────────────────────────────────────

async def chat_loop(project_dir: str) -> None:
    os.chdir(project_dir)

    header()
    print(f"{DIM}Project: {project_dir}{R}")
    print(f"{DIM}ESC / Ctrl+C = interrupt  ·  Type anytime = queue  ·  exit = quit{R}\n")

    messages  = [{"role": "system", "content": SYSTEM_PROMPT}]
    client    = get_client()

    input_queue:     asyncio.Queue[str] = asyncio.Queue()
    interrupt_event: asyncio.Event      = asyncio.Event()

    reader_task = asyncio.create_task(_stdin_reader(input_queue))

    _ctrl_c_idle = False  # second Ctrl+C while idle → exit

    try:
        while True:

            # ── Drain queue (typed while agent ran) ──────────────────────────
            queued = _drain_queue(input_queue)

            # Filter interrupts that came in during agent run
            interrupts = [m for m in queued if m in (_ESC, _CTRL_C)]
            queued     = [m for m in queued if m not in (_ESC, _CTRL_C)]

            if queued:
                for msg in queued:
                    print(f"\n{YELLOW}[Queued]{R} {msg}")

                if any(m.lower() in _EXIT_COMMANDS for m in queued):
                    print(f"\n{DIM}Goodbye.{R}\n")
                    break

                for msg in queued:
                    if msg in _BUILTIN_COMMANDS:
                        messages, _ = _handle_builtin(msg, messages)

                real = [
                    m for m in queued
                    if m not in _BUILTIN_COMMANDS and m.lower() not in _EXIT_COMMANDS
                ]
                if real:
                    combined = "\n".join(real)
                    messages.append({"role": "user", "content": combined})
                    messages = await summarize_if_needed(messages, client)
                    interrupt_event.clear()
                    messages = await run_agent_loop(messages, interrupt_event)
                    print()
                    continue

            # ── Normal prompt ─────────────────────────────────────────────────
            _ctrl_c_idle = False
            interrupt_event.clear()

            print(f"{GREEN}{BOLD}You:{R} ", end="", flush=True)
            try:
                user_input = await input_queue.get()
            except asyncio.CancelledError:
                print(f"\n{DIM}Goodbye.{R}\n")
                break

            # Handle ESC / Ctrl+C at idle
            if user_input in (_ESC, _CTRL_C):
                if _ctrl_c_idle or user_input == _ESC:
                    print(f"\n{DIM}Goodbye.{R}\n")
                    break
                print(f"\n{YELLOW}(Press Ctrl+C again or type 'exit' to quit){R}\n")
                _ctrl_c_idle = True
                continue

            _ctrl_c_idle = False

            if not user_input:
                continue

            if user_input.lower() in _EXIT_COMMANDS:
                print(f"\n{DIM}Goodbye.{R}\n")
                break

            messages, handled = _handle_builtin(user_input, messages)
            if handled:
                continue

            messages.append({"role": "user", "content": user_input})
            messages = await summarize_if_needed(messages, client)
            interrupt_event.clear()

            # ── Agent loop — watch for interrupt ─────────────────────────────
            agent_task = asyncio.create_task(
                run_agent_loop(messages, interrupt_event)
            )

            # While agent runs, watch for ESC / Ctrl+C from queue
            async def _watch_interrupt() -> None:
                while not agent_task.done():
                    item = await input_queue.get()
                    if item in (_ESC, _CTRL_C):
                        interrupt_event.set()
                        proc = get_proc()
                        if proc and proc.returncode is None:
                            proc.terminate()
                        print(f"\n{YELLOW}[Interrupted]{R}", flush=True)
                        return
                    else:
                        # Re-queue non-interrupt messages
                        await input_queue.put(item)

            watcher = asyncio.create_task(_watch_interrupt())
            try:
                messages = await agent_task
            finally:
                watcher.cancel()

            print()

    finally:
        reader_task.cancel()
