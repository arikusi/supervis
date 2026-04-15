"""Fixed input bar at the bottom of the TUI with command history."""

from textual.widgets import Input


class InputBar(Input):
    """User input widget with up/down arrow history."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._history_index: int = -1
        self._current_input: str = ""

    def add_to_history(self, text: str) -> None:
        """Add a message to history. Deduplicates consecutive entries."""
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
        self._history_index = -1

    def on_key(self, event) -> None:
        if event.key == "up" and self._history:
            if self._history_index == -1:
                self._current_input = self.value
                self._history_index = len(self._history) - 1
            elif self._history_index > 0:
                self._history_index -= 1
            self.value = self._history[self._history_index]
            event.prevent_default()
        elif event.key == "down" and self._history_index >= 0:
            self._history_index += 1
            if self._history_index >= len(self._history):
                self._history_index = -1
                self.value = self._current_input
            else:
                self.value = self._history[self._history_index]
            event.prevent_default()
