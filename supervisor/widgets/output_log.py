"""Scrollable output area for all agent output."""

from rich.text import Text
from textual.widgets import RichLog


class OutputLog(RichLog):
    """Main output area. Buffers DeepSeek tokens, writes final on DONE.
    Live streaming preview is handled by StreamDisplay (separate widget).
    """

    DEFAULT_CSS = """
    OutputLog {
        height: 1fr;
        border: none;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(highlight=True, markup=True, wrap=True, **kwargs)
        self._ds_buffer = ""
        self._reasoning_buffer = ""

    # ─── DeepSeek ────────────────────────────────────────────────────

    def write_deepseek_start(self) -> None:
        self._ds_buffer = ""
        self._reasoning_buffer = ""

    def write_deepseek_token(self, token: str) -> None:
        self._ds_buffer += token

    def write_deepseek_reasoning(self, token: str) -> None:
        self._reasoning_buffer += token

    def write_deepseek_done(self, cost_summary: str) -> None:
        text = Text()
        text.append("DeepSeek: ", style="bold cyan")
        if self._ds_buffer:
            text.append(self._ds_buffer, style="cyan")
        else:
            text.append("(tool calls only)", style="dim cyan")
        if cost_summary:
            text.append(f"  [{cost_summary}]", style="dim")
        self.write(text)
        self._ds_buffer = ""
        self._reasoning_buffer = ""

    def write_deepseek_error(self, error: str) -> None:
        self.write(Text(f"[DeepSeek error: {error}]", style="yellow"))

    def write_deepseek_retry(self, status: int, wait: int) -> None:
        self.write(Text(f"[API error {status}, retrying in {wait}s...]", style="dim yellow"))

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

    def write_queued(self, text: str) -> None:
        self.write(Text(f"[Queued] {text}", style="yellow"))

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
