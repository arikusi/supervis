"""Tests for supervisor.queue module."""

import asyncio

import pytest

from supervisor.queue import MessageQueue


class TestMessageQueue:
    def test_put_and_get_ordering(self):
        q = MessageQueue()
        q.put("first")
        q.put("second")
        q.put("third")
        assert q.get_nowait() == "first"
        assert q.get_nowait() == "second"
        assert q.get_nowait() == "third"

    def test_empty_and_qsize(self):
        q = MessageQueue()
        assert q.empty()
        assert q.qsize == 0
        q.put("msg")
        assert not q.empty()
        assert q.qsize == 1

    def test_get_nowait_raises_on_empty(self):
        q = MessageQueue()
        with pytest.raises(asyncio.QueueEmpty):
            q.get_nowait()

    def test_pending_returns_copy(self):
        q = MessageQueue()
        q.put("a")
        q.put("b")
        pending = q.pending()
        assert pending == ["a", "b"]
        pending.clear()  # modifying copy shouldn't affect queue
        assert q.qsize == 2

    def test_cancel_all(self):
        q = MessageQueue()
        q.put("a")
        q.put("b")
        q.put("c")
        result = q.cancel()
        assert "3" in result
        assert q.empty()

    def test_cancel_by_index(self):
        q = MessageQueue()
        q.put("a")
        q.put("b")
        q.put("c")
        result = q.cancel(1)
        assert "b" in result
        assert q.pending() == ["a", "c"]

    def test_cancel_invalid_index(self):
        q = MessageQueue()
        q.put("a")
        result = q.cancel(5)
        assert "Invalid" in result
        assert q.qsize == 1

    def test_cancel_empty_queue(self):
        q = MessageQueue()
        result = q.cancel()
        assert "No queued" in result

    @pytest.mark.asyncio
    async def test_get_blocks_until_put(self):
        q = MessageQueue()
        result = None

        async def consumer():
            nonlocal result
            result = await q.get()

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)
        assert result is None  # still waiting
        q.put("hello")
        await task
        assert result == "hello"

    def test_put_nowait_alias(self):
        q = MessageQueue()
        q.put_nowait("test")
        assert q.get_nowait() == "test"
