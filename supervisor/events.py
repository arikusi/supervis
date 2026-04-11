"""Event bus for decoupling business logic from UI.

Business logic modules (deepseek, claude, tools) call emit() with typed events.
The UI layer subscribes and renders. No business logic file imports UI modules.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable

logger = logging.getLogger(__name__)


class EventType(Enum):
    # DeepSeek turns
    DEEPSEEK_START = auto()
    DEEPSEEK_THINKING = auto()
    DEEPSEEK_TOKEN = auto()
    DEEPSEEK_DONE = auto()
    DEEPSEEK_ERROR = auto()
    DEEPSEEK_RETRY = auto()

    # Claude Code subprocess
    CLAUDE_START = auto()
    CLAUDE_TEXT = auto()
    CLAUDE_TOOL = auto()
    CLAUDE_DONE = auto()
    CLAUDE_ERROR = auto()

    # Non-claude tool execution
    TOOL_EXEC = auto()

    # System
    STATUS = auto()
    INTERRUPT = auto()
    QUEUE_UPDATE = auto()
    SUMMARY = auto()


@dataclass
class Event:
    type: EventType
    data: dict = field(default_factory=dict)


# Module-level subscriber list
_subscribers: list[Callable[[Event], None]] = []


def subscribe(fn: Callable[[Event], None]) -> None:
    _subscribers.append(fn)


def unsubscribe(fn: Callable[[Event], None]) -> None:
    try:
        _subscribers.remove(fn)
    except ValueError:
        pass


def emit(event_type: EventType, **data) -> None:
    event = Event(type=event_type, data=data)
    for fn in _subscribers:
        try:
            fn(event)
        except Exception:
            logger.exception("Event subscriber %s raised an error", getattr(fn, "__name__", fn))
