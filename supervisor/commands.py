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


# ─── Model switching ─────────────────────────────────────────────────────────

_MODEL_PROFILES = {
    "chat": ("deepseek-chat", True, "deepseek-chat (thinking enabled, 8K max output)"),
    "chat-fast": ("deepseek-chat", False, "deepseek-chat (no thinking, faster responses, 8K max output)"),
    "reasoner": ("deepseek-reasoner", False, "deepseek-reasoner (thinking built-in, 64K max output)"),
}


@register("model", "Switch model: /model chat | chat-fast | reasoner")
def _cmd_model(app, args: str) -> None:
    from .widgets import OutputLog

    log = app.query_one("#output", OutputLog)
    session = app.session

    name = args.strip().lower()
    if not name:
        # Show current
        thinking_str = " + thinking" if session.thinking else ""
        log.write_system(f"Current model: {session.model}{thinking_str}")
        log.write_system("Available: /model chat | chat-fast | reasoner")
        return

    profile = _MODEL_PROFILES.get(name)
    if not profile:
        log.write_system(f"Unknown model: {name}. Available: chat, chat-fast, reasoner")
        return

    model, thinking, desc = profile
    session.switch_model(model, thinking)
    log.write_system(f"Switched to {desc}")
    from .widgets import StatusBar

    app.query_one("#status", StatusBar).model_text = name


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

    lines = [
        f"Model: {session.model}{thinking_str}",
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
        f"model = {session.model}",
        f"thinking = {session.thinking}",
        f"max_cost = {session.max_cost}",
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
