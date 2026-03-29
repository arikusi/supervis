"""Slash command registry.

Commands are registered with @register and dispatched from the input bar.
Each handler receives (app, args_string) where app is the Textual App instance.
"""

from typing import Callable, Any

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
