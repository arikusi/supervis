"""Streaming display widget for DeepSeek output.

A Static widget that updates in place during streaming.
Content is transferred to RichLog when streaming completes.
"""

from rich.text import Text
from textual.widgets import Static


class StreamDisplay(Static):
    """Shows streaming DeepSeek content. Updates in place via Static.update()."""

    DEFAULT_CSS = """
    StreamDisplay {
        height: auto;
        max-height: 6;
        padding: 0 1;
        display: none;
    }
    StreamDisplay.visible {
        display: block;
    }
    """

    def show_streaming(self, label: str, content: str, style: str) -> None:
        """Update the streaming display with new content."""
        text = Text()
        text.append(f"{label}: ", style=f"bold {style}")
        text.append(content[-300:] if len(content) > 300 else content, style=style)
        self.update(text)
        self.add_class("visible")

    def clear_streaming(self) -> None:
        """Hide and clear the streaming display."""
        self.update("")
        self.remove_class("visible")
