"""Tests for supervisor.widgets.input_bar module."""

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
