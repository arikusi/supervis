"""Message queue with cancel/list support.

Replaces asyncio.Queue for user messages. Supports cancelling and listing
pending messages, which asyncio.Queue cannot do.
"""

import asyncio


class MessageQueue:
    """Async message queue backed by a list + Event.

    Same basic API as asyncio.Queue (put, get, get_nowait, empty, qsize)
    plus cancel() and pending() for queue management.
    """

    def __init__(self) -> None:
        self._items: list[str] = []
        self._event = asyncio.Event()

    def put(self, msg: str) -> None:
        self._items.append(msg)
        self._event.set()

    def put_nowait(self, msg: str) -> None:
        self.put(msg)

    async def get(self) -> str:
        while not self._items:
            self._event.clear()
            await self._event.wait()
        return self._items.pop(0)

    def get_nowait(self) -> str:
        if not self._items:
            raise asyncio.QueueEmpty()
        return self._items.pop(0)

    def empty(self) -> bool:
        return len(self._items) == 0

    @property
    def qsize(self) -> int:
        return len(self._items)

    def pending(self) -> list[str]:
        return list(self._items)

    def cancel(self, index: int | None = None) -> str:
        if not self._items:
            return "No queued messages."
        if index is not None:
            if 0 <= index < len(self._items):
                removed = self._items.pop(index)
                return f"Cancelled: {removed[:50]}"
            return f"Invalid index. Queue has {len(self._items)} item(s)."
        count = len(self._items)
        self._items.clear()
        return f"Cancelled {count} queued message(s)."
