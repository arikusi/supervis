"""Tests for supervisor.widgets.input_bar module.

Reading history is plain state, but assigning `value` runs Textual's reactive
machinery, which needs a running app — so the navigation tests mount the widget.
"""

from contextlib import asynccontextmanager

import pytest
from textual.app import App, ComposeResult

from supervisor.widgets.input_bar import InputBar


class TestInputBarHistory:
    def test_add_to_history(self):
        bar = InputBar()
        bar.add_to_history("hello")
        bar.add_to_history("world")
        assert bar._history == ["hello", "world"]

    def test_dedup_consecutive(self):
        bar = InputBar()
        bar.add_to_history("same")
        bar.add_to_history("same")
        bar.add_to_history("same")
        assert bar._history == ["same"]

    def test_allows_non_consecutive_duplicates(self):
        bar = InputBar()
        bar.add_to_history("a")
        bar.add_to_history("b")
        bar.add_to_history("a")
        assert bar._history == ["a", "b", "a"]

    def test_empty_string_not_added(self):
        bar = InputBar()
        bar.add_to_history("")
        assert bar._history == []

    def test_history_index_resets_on_add(self):
        bar = InputBar()
        bar.add_to_history("first")
        bar._history_index = 0  # simulate browsing
        bar.add_to_history("second")
        assert bar._history_index == -1


class FakeKey:
    """Stands in for a Textual key event; records whether the widget claimed it."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.prevented = False

    def prevent_default(self) -> None:
        self.prevented = True


class _Host(App):
    def compose(self) -> ComposeResult:
        yield InputBar(id="input")


@asynccontextmanager
async def _mounted(*entries: str):
    app = _Host()
    async with app.run_test():
        bar = app.query_one("#input", InputBar)
        for entry in entries:
            bar.add_to_history(entry)
        yield bar


class TestHistoryNavigation:
    @pytest.mark.asyncio
    async def test_up_recalls_the_most_recent_entry(self):
        async with _mounted("first", "second") as bar:
            bar.on_key(FakeKey("up"))
            assert bar.value == "second"

    @pytest.mark.asyncio
    async def test_repeated_up_walks_further_back(self):
        async with _mounted("first", "second", "third") as bar:
            for _ in range(3):
                bar.on_key(FakeKey("up"))
            assert bar.value == "first"

    @pytest.mark.asyncio
    async def test_up_stops_at_the_oldest_entry(self):
        async with _mounted("only") as bar:
            for _ in range(5):
                bar.on_key(FakeKey("up"))
            assert bar.value == "only"

    @pytest.mark.asyncio
    async def test_down_returns_toward_the_present(self):
        async with _mounted("first", "second") as bar:
            bar.on_key(FakeKey("up"))
            bar.on_key(FakeKey("up"))
            assert bar.value == "first"
            bar.on_key(FakeKey("down"))
            assert bar.value == "second"

    @pytest.mark.asyncio
    async def test_down_past_the_end_restores_the_draft(self):
        """Whatever was half-typed before browsing must come back."""
        async with _mounted("old message") as bar:
            bar.value = "half-typed draft"
            bar.on_key(FakeKey("up"))
            assert bar.value == "old message"

            bar.on_key(FakeKey("down"))
            assert bar.value == "half-typed draft"

    @pytest.mark.asyncio
    async def test_up_with_no_history_does_nothing(self):
        async with _mounted() as bar:
            bar.value = "typing"
            event = FakeKey("up")
            bar.on_key(event)
            assert bar.value == "typing"
            assert not event.prevented

    @pytest.mark.asyncio
    async def test_down_without_browsing_does_nothing(self):
        async with _mounted("a") as bar:
            bar.value = "typing"
            event = FakeKey("down")
            bar.on_key(event)
            assert bar.value == "typing"
            assert not event.prevented

    @pytest.mark.asyncio
    async def test_navigation_keys_are_claimed(self):
        async with _mounted("a") as bar:
            event = FakeKey("up")
            bar.on_key(event)
            assert event.prevented, "the input must swallow the key so the app does not scroll"

    @pytest.mark.asyncio
    async def test_other_keys_pass_through(self):
        async with _mounted("a") as bar:
            event = FakeKey("left")
            bar.on_key(event)
            assert not event.prevented

    @pytest.mark.asyncio
    async def test_submitting_after_browsing_resets_the_cursor(self):
        async with _mounted("a", "b") as bar:
            bar.on_key(FakeKey("up"))
            bar.add_to_history("c")
            assert bar._history_index == -1
            bar.on_key(FakeKey("up"))
            assert bar.value == "c"
