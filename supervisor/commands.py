"""Slash command registry.

Commands are registered with @register and dispatched from the input bar.
Each handler receives (app, args_string) where app is the Textual App instance.
"""

import json
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

_commands: dict[str, Callable] = {}
_help_entries: list[tuple[str, str]] = []


def register(name: str, description: str = ""):
    """Decorator to register a slash command."""

    def decorator(fn: Callable):
        _commands[name] = fn
        if description:
            _help_entries.append((name, description))
        return fn

    return decorator


def dispatch(text: str, app: Any) -> bool:
    """Try to dispatch a slash command. Returns True if handled."""
    if not text.startswith("/"):
        return False

    parts = text[1:].split(maxsplit=1)
    if not parts:
        return False

    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    handler = _commands.get(cmd)
    if handler:
        handler(app, args)
        return True

    return False


def get_help() -> list[tuple[str, str]]:
    """Return list of (command_name, description) for all registered commands."""
    return list(_help_entries)


# ─── Built-in commands ───────────────────────────────────────────────────────


@register("reset", "Reset Claude session and conversation history")
def _cmd_reset(app, args: str) -> None:
    app.handle_reset()


@register("help", "Show available commands")
def _cmd_help(app, args: str) -> None:
    app.handle_help()


@register("reasoning", "Toggle reasoning/thinking display on/off")
def _cmd_reasoning(app, args: str) -> None:
    from .widgets import OutputLog

    log = app.query_one("#output", OutputLog)
    session = app.session
    session.show_reasoning = not session.show_reasoning
    state = "on" if session.show_reasoning else "off"
    log.write_system(f"Reasoning display: {state}")


# ─── Model switching ─────────────────────────────────────────────────────────

_MODEL_PROFILES = {
    "flash": ("deepseek-v4-flash", True, "deepseek-v4-flash (thinking)"),
    "flash-fast": ("deepseek-v4-flash", False, "deepseek-v4-flash (no thinking, fastest)"),
    "pro": ("deepseek-v4-pro", True, "deepseek-v4-pro (thinking, frontier)"),
    "pro-fast": ("deepseek-v4-pro", False, "deepseek-v4-pro (no thinking)"),
    # Legacy aliases (retired 2026-07-24) → nearest V4 profile
    "chat": ("deepseek-v4-flash", True, "deepseek-v4-flash (thinking)"),
    "chat-fast": ("deepseek-v4-flash", False, "deepseek-v4-flash (no thinking)"),
    "reasoner": ("deepseek-v4-pro", True, "deepseek-v4-pro (thinking)"),
}


@register("model", "Pin a model or return to auto: /model flash | flash-fast | pro | pro-fast | auto")
def _cmd_model(app, args: str) -> None:
    from .widgets import OutputLog, StatusBar

    log = app.query_one("#output", OutputLog)
    session = app.session

    name = args.strip().lower()
    if not name:
        thinking_str = " + thinking" if session.thinking else ""
        mode = "pinned" if session.pinned else ("auto-tiering" if session.auto_escalate else "base only")
        log.write_system(f"Active: {session.model}{thinking_str}  ({mode})")
        log.write_system(
            f"Base: {session.base_model} · Pro: {session.pro_model} · "
            f"auto-escalate: {'on' if session.auto_escalate else 'off'}"
        )
        log.write_system("Switch: /model flash | flash-fast | pro | pro-fast | auto")
        return

    if name == "auto":
        session.unpin()
        log.write_system("Auto-tiering on: flash by default, pro when escalated.")
        app.query_one("#status", StatusBar).model_text = session.base_model
        return

    profile = _MODEL_PROFILES.get(name)
    if not profile:
        log.write_system(f"Unknown model: {name}. Available: flash, flash-fast, pro, pro-fast, auto")
        return

    model, thinking, desc = profile
    session.pin_model(model, thinking)
    log.write_system(f"Pinned to {desc}")
    app.query_one("#status", StatusBar).model_text = model


@register("auto", "Toggle automatic pro-escalation: /auto on | off")
def _cmd_auto(app, args: str) -> None:
    from .widgets import OutputLog

    log = app.query_one("#output", OutputLog)
    session = app.session

    name = args.strip().lower()
    if name in ("on", "true", "yes"):
        session.auto_escalate = True
    elif name in ("off", "false", "no"):
        session.auto_escalate = False
    else:
        state = "on" if session.auto_escalate else "off"
        log.write_system(f"Auto-escalation is {state}. Usage: /auto on | off")
        return
    log.write_system(f"Auto-escalation: {'on' if session.auto_escalate else 'off'}")


# ─── Status ──────────────────────────────────────────────────────────────────


@register("status", "Show session status")
def _cmd_status(app, args: str) -> None:
    from .widgets import OutputLog

    log = app.query_one("#output", OutputLog)
    session = app.session

    uptime = int(time.time() - session.start_time)
    mins, secs = divmod(uptime, 60)
    msg_count = len([m for m in session.messages if m.get("role") != "system"])
    thinking_str = " + thinking" if session.thinking else ""
    if session.pinned:
        tier = "pinned"
    elif session.escalated:
        tier = "escalated → pro"
    else:
        tier = "auto-tiering" if session.auto_escalate else "base only"

    lines = [
        f"Model: {session.model}{thinking_str}  ({tier})",
        f"Tiers: base {session.base_model} · pro {session.pro_model} · "
        f"auto-escalate {'on' if session.auto_escalate else 'off'}",
        f"Messages: {msg_count}",
        f"Cost: {session.cost.summary()}",
        f"Uptime: {mins}m {secs}s",
        f"Project: {app._project_dir}",
    ]
    if session.max_cost:
        ok, budget_msg = session.check_budget()
        lines.append(f"Budget: {budget_msg}" if budget_msg else f"Budget: ${session.max_cost:.2f} (under limit)")

    for line in lines:
        log.write_system(line)


# ─── Config ──────────────────────────────────────────────────────────────────


@register("config", "Show current configuration")
def _cmd_config(app, args: str) -> None:
    from .widgets import OutputLog

    log = app.query_one("#output", OutputLog)
    session = app.session

    # Mask API key
    key = session.client.api_key or ""
    masked = key[:3] + "..." + key[-4:] if len(key) > 8 else "***"

    lines = [
        f"api_key = {masked}",
        f"model = {session.base_model}",
        f"pro_model = {session.pro_model}",
        f"thinking = {session.thinking}",
        f"auto_escalate = {session.auto_escalate}",
        f"max_cost = {session.max_cost}",
        f"max_turns = {session.max_turns}",
        f"shell_timeout = {session.shell_timeout}",
        f"claude_timeout = {session.claude_timeout}",
        f"truncation_limit = {session.truncation_limit}",
    ]
    for line in lines:
        log.write_system(line)


# ─── Export ──────────────────────────────────────────────────────────────────


@register("export", "Export conversation: /export md | json")
def _cmd_export(app, args: str) -> None:
    from .widgets import OutputLog

    log = app.query_one("#output", OutputLog)
    session = app.session

    fmt = args.strip().lower() or "md"
    if fmt not in ("md", "json"):
        log.write_system("Usage: /export md | json")
        return

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"supervis-export-{timestamp}.{fmt}"

    if fmt == "json":
        content = json.dumps(session.messages, indent=2, ensure_ascii=False)
    else:
        parts = []
        for m in session.messages:
            role = m.get("role", "unknown")
            text = m.get("content", "") or ""
            if role == "system":
                continue
            elif role == "user":
                parts.append(f"## You\n\n{text}")
            elif role == "assistant":
                parts.append(f"## Assistant\n\n{text}")
            elif role == "tool":
                parts.append(f"*Tool result:* {text[:200]}")
        content = "\n\n---\n\n".join(parts)

    try:
        Path(filename).write_text(content, encoding="utf-8")
        log.write_system(f"Exported to {filename}")
    except Exception as e:
        log.write_system(f"Export failed: {e}")


# ─── Undo ────────────────────────────────────────────────────────────────────


@register("undo", "Undo last changes (git stash)")
def _cmd_undo(app, args: str) -> None:
    from .widgets import OutputLog

    log = app.query_one("#output", OutputLog)

    try:
        diff = subprocess.run("git diff --stat HEAD", shell=True, capture_output=True, text=True, timeout=10)
        if diff.stdout.strip():
            log.write_system(f"Changes:\n{diff.stdout.strip()}")
            result = subprocess.run("git stash", shell=True, capture_output=True, text=True, timeout=10)
            log.write_system(result.stdout.strip() or "Stashed.")
        else:
            # Nothing to stash, try reverting last commit
            result = subprocess.run("git revert HEAD --no-edit", shell=True, capture_output=True, text=True, timeout=10)
            output = (result.stdout + result.stderr).strip()
            log.write_system(output or "Reverted last commit.")
    except Exception as e:
        log.write_system(f"Undo failed: {e}")


# ─── Budget ──────────────────────────────────────────────────────────────────


@register("update", "Check for supervis updates")
def _cmd_update(app, args: str) -> None:
    from .version_check import check_for_update_sync
    from .widgets import OutputLog

    log = app.query_one("#output", OutputLog)

    log.write_system("Checking for updates...")
    current, latest = check_for_update_sync()
    if latest:
        log.write_system(f"Update available: supervis {latest} (you have {current})")
        log.write_system("Run: pipx upgrade supervis")
    else:
        log.write_system(f"supervis {current} is up to date.")


@register("queue", "Show queued messages")
def _cmd_queue(app, args: str) -> None:
    from .widgets import OutputLog

    log = app.query_one("#output", OutputLog)
    items = app._user_queue.pending()
    if not items:
        log.write_system("No queued messages.")
        return
    for i, msg in enumerate(items):
        log.write_system(f"  [{i}] {msg[:80]}")


@register("cancel", "Cancel queued messages: /cancel [index]")
def _cmd_cancel(app, args: str) -> None:
    from .widgets import OutputLog

    log = app.query_one("#output", OutputLog)
    import contextlib

    index = None
    with contextlib.suppress(ValueError):
        index = int(args.strip()) if args.strip() else None
    result = app._user_queue.cancel(index)
    log.write_system(result)
    from .events import EventType, emit

    emit(EventType.QUEUE_UPDATE, count=app._user_queue.qsize)


@register("budget", "Show cost budget status")
def _cmd_budget(app, args: str) -> None:
    from .widgets import OutputLog

    log = app.query_one("#output", OutputLog)
    session = app.session

    current = session.cost.session_cost()
    if session.max_cost:
        remaining = session.max_cost - current
        pct = (current / session.max_cost) * 100
        log.write_system(f"Cost: ${current:.4f} / ${session.max_cost:.2f} ({pct:.0f}%)")
        log.write_system(f"Remaining: ${remaining:.4f}")
    else:
        log.write_system(f"Cost: ${current:.4f}")
        log.write_system("No budget limit set. Use config to set max_cost.")
