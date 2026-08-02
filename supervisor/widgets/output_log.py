"""Scrollable output area for all agent output.

Pure rendering: every method takes what it should print. Streaming state is
coordinated by the App, which is the only place that sees both this widget and
StreamDisplay.
"""

from rich.text import Text
from textual.widgets import RichLog


class OutputLog(RichLog):
    """Main output area. Final, settled lines land here."""

    DEFAULT_CSS = """
    OutputLog {
        height: 1fr;
        border: none;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(highlight=True, markup=True, wrap=True, **kwargs)

    # ─── DeepSeek ────────────────────────────────────────────────────

    def write_deepseek_done(self, content: str, cost_summary: str = "") -> None:
        text = Text()
        text.append("DeepSeek: ", style="bold cyan")
        if content:
            text.append(content, style="cyan")
        else:
            text.append("(tool calls only)", style="dim cyan")
        if cost_summary:
            text.append(f"  [{cost_summary}]", style="dim")
        self.write(text)

    def write_deepseek_error(self, error: str) -> None:
        self.write(Text(f"[DeepSeek error: {error}]", style="yellow"))

    def write_deepseek_retry(self, reason: str, wait: int) -> None:
        self.write(Text(f"[{reason}, retrying in {wait}s...]", style="dim yellow"))

    # ─── Claude ──────────────────────────────────────────────────────

    def write_claude_start(self, prompt_preview: str) -> None:
        t = Text()
        t.append("┌─ Claude Code ", style="bold #e87d3e")
        t.append(prompt_preview, style="dim #e87d3e")
        self.write(t)

    def write_claude_text(self, text: str) -> None:
        self.write(Text(f"│ {text}", style="#e87d3e"))

    def write_claude_tool(self, label: str) -> None:
        self.write(Text(f"│ ↳ {label}", style="dim #e87d3e"))

    def write_claude_done(self, tool_count: int) -> None:
        suffix = f" ({tool_count} tool calls)" if tool_count else ""
        self.write(Text(f"└─ done{suffix}", style="bold #e87d3e"))

    # ─── System / misc ───────────────────────────────────────────────

    def write_system(self, text: str) -> None:
        self.write(Text(text, style="dim"))

    def write_user(self, text: str) -> None:
        self.write(Text(f"You: {text}", style="bold green"))

    def write_tool_exec(self, label: str) -> None:
        self.write(Text(f"  [{label}]", style="dim"))

    def write_interrupt(self) -> None:
        self.write(Text("[Interrupted]", style="bold yellow"))

    def write_help(self, entries: list[tuple[str, str]]) -> None:
        lines = Text()
        lines.append("Commands:\n", style="bold cyan")
        for name, desc in entries:
            lines.append(f"  /{name}", style="bold")
            lines.append(f"  — {desc}\n")
        lines.append("\n  exit", style="bold")
        lines.append("  — quit\n")
        lines.append("  Ctrl+Z", style="bold")
        lines.append("  — interrupt agent\n")
        lines.append("  Ctrl+Q", style="bold")
        lines.append("  — quit\n")
        self.write(lines)
