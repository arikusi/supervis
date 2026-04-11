"""Status bar showing model, queue count, cost, and thinking state."""

from textual.reactive import reactive
from textual.widgets import Static


class StatusBar(Static):
    """Bottom status bar with reactive properties."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    queue_count: reactive[int] = reactive(0)
    thinking: reactive[bool] = reactive(False)
    cost_text: reactive[str] = reactive("")
    model_text: reactive[str] = reactive("")

    def render(self) -> str:
        parts = []

        if self.model_text:
            parts.append(f"[bold]{self.model_text}[/]")

        if self.thinking:
            parts.append("[bold cyan]thinking[/]")

        if self.queue_count > 0:
            parts.append(f"[yellow]queued: {self.queue_count}[/]")

        if self.cost_text:
            parts.append(f"[dim]{self.cost_text}[/]")

        return " · ".join(parts) if parts else ""
