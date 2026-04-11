"""Textual App for supervis TUI."""

import asyncio

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, Input, RichLog

from .widgets import OutputLog, InputBar, StatusBar
from .events import EventType, Event, subscribe, unsubscribe, emit
from .commands import dispatch, get_help
from .claude import get_proc, reset_session
from . import cost


class SupervisApp(App):
    """DeepSeek Supervisor × Claude Code TUI."""

    TITLE = "supervis"

    BINDINGS = [
        Binding("ctrl+z", "interrupt", "Interrupt agent", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
    ]

    CSS = """
    #output {
        height: 1fr;
    }
    #status {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    #input {
        height: auto;
    }
    """

    def __init__(self, project_dir: str, system_prompt: str) -> None:
        super().__init__()
        self._project_dir = project_dir
        self._system_prompt = system_prompt
        self._user_queue: asyncio.Queue = asyncio.Queue()
        self._interrupt_event = asyncio.Event()
        self._agent_running = False
        self._ctrl_c_count = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield OutputLog(id="output")
        yield StatusBar(id="status")
        yield InputBar(id="input", placeholder="Type a message or /help...")
        yield Footer()

    def on_mount(self) -> None:
        subscribe(self._on_event)
        log = self.query_one("#output", OutputLog)
        log.write_system(f"Project: {self._project_dir}")
        log.write_system("Ctrl+Z = interrupt agent · Ctrl+Q = quit · /help for commands")
        self.query_one("#input", InputBar).focus()
        self.run_worker(self._run_orchestrator(), exclusive=True)

    def on_unmount(self) -> None:
        unsubscribe(self._on_event)

    # ─── Event bridge ────────────────────────────────────────────────────

    def _on_event(self, event: Event) -> None:
        """Bridge from EventBus to Textual widgets. Called from same event loop."""
        self._handle_event(event)

    def _handle_event(self, event: Event) -> None:
        """Handle events on the Textual thread."""
        log = self.query_one("#output", OutputLog)
        status = self.query_one("#status", StatusBar)
        d = event.data

        match event.type:
            case EventType.DEEPSEEK_START:
                log.write_deepseek_start()
                status.thinking = True
            case EventType.DEEPSEEK_THINKING:
                log.write_deepseek_thinking()
                status.thinking = True
            case EventType.DEEPSEEK_TOKEN:
                log.write_deepseek_token(d.get("text", ""))
            case EventType.DEEPSEEK_DONE:
                summary = d.get("cost", "")
                log.write_deepseek_done(summary)
                status.thinking = False
                status.cost_text = summary
            case EventType.DEEPSEEK_ERROR:
                log.write_deepseek_error(d.get("error", ""))
                status.thinking = False
            case EventType.DEEPSEEK_RETRY:
                log.write_deepseek_retry(d.get("status", 0), d.get("wait", 0))
            case EventType.CLAUDE_START:
                log.write_claude_start(d.get("prompt", ""))
            case EventType.CLAUDE_TEXT:
                log.write_claude_text(d.get("text", ""))
            case EventType.CLAUDE_TOOL:
                log.write_claude_tool(d.get("label", ""))
            case EventType.CLAUDE_DONE:
                log.write_claude_done(d.get("tool_count", 0))
            case EventType.CLAUDE_ERROR:
                log.write_deepseek_error(d.get("error", "Claude error"))
            case EventType.TOOL_EXEC:
                log.write_tool_exec(d.get("label", ""))
            case EventType.STATUS:
                log.write_system(d.get("text", ""))
            case EventType.INTERRUPT:
                log.write_interrupt()
                status.thinking = False
            case EventType.QUEUE_UPDATE:
                status.queue_count = d.get("count", 0)
            case EventType.SUMMARY:
                log.write_system("Conversation history summarized.")

    # ─── Input handling ──────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return

        event.input.clear()

        if text.lower() in {"exit", "quit", "q", "çıkış"}:
            self.exit()
            return

        log = self.query_one("#output", OutputLog)
        log.write_user(text)

        if dispatch(text, self):
            return

        self._user_queue.put_nowait(text)
        self._ctrl_c_count = 0

        if self._agent_running:
            count = self._user_queue.qsize()
            emit(EventType.QUEUE_UPDATE, count=count)

    # ─── Interrupt handling ──────────────────────────────────────────────

    def action_interrupt(self) -> None:
        if self._agent_running:
            self._interrupt_event.set()
            proc = get_proc()
            if proc and proc.returncode is None:
                proc.terminate()
            emit(EventType.INTERRUPT)
        else:
            log = self.query_one("#output", OutputLog)
            log.write_system("No agent running. Ctrl+Q to quit.")

    # ─── Slash command handlers ──────────────────────────────────────────

    def handle_reset(self) -> None:
        reset_session()
        cost.reset()
        self._user_queue.put_nowait("__RESET__")
        log = self.query_one("#output", OutputLog)
        log.write_system("Session reset.")
        status = self.query_one("#status", StatusBar)
        status.cost_text = ""

    def handle_help(self) -> None:
        entries = get_help()
        log = self.query_one("#output", OutputLog)
        log.write_help(entries)

    # ─── Orchestrator ────────────────────────────────────────────────────

    async def _run_orchestrator(self) -> None:
        """Main agent loop. Runs as a Textual worker."""
        from .orchestrator import orchestrate
        await orchestrate(
            message_queue=self._user_queue,
            interrupt_event=self._interrupt_event,
            system_prompt=self._system_prompt,
            set_agent_running=self._set_agent_running,
        )

    def _set_agent_running(self, running: bool) -> None:
        self._agent_running = running
