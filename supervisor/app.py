"""Textual App for supervis TUI."""

from openai import AsyncOpenAI
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input

from .claude import get_proc, reset_session
from .commands import dispatch, get_help
from .config import Config
from .deepseek import REQUEST_TIMEOUT
from .events import Event, EventType, emit, subscribe, unsubscribe
from .queue import MessageQueue
from .session import Session
from .widgets import InputBar, OutputLog, StatusBar, StreamDisplay


class SupervisApp(App):
    """DeepSeek Supervisor × Claude Code TUI."""

    TITLE = "supervis"
    ALLOW_SELECT = True

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

    def __init__(self, project_dir: str, system_prompt: str, config: Config | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._project_dir = project_dir
        self._system_prompt = system_prompt
        self._user_queue = MessageQueue()
        self._agent_running = False

        # Streaming buffers. They belong here rather than in a widget: both
        # OutputLog and StreamDisplay render from them, and only the App sees both.
        self._ds_buffer = ""
        self._reasoning_buffer = ""

        # Create session from config
        if config is None:
            config = Config()
        client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=REQUEST_TIMEOUT,
            max_retries=0,  # stream_turn does its own retry with backoff
        )
        self.session = Session(
            client=client,
            model=config.model,
            thinking=config.thinking,
            base_model=config.model,
            base_thinking=config.thinking,
            pro_model=config.pro_model,
            auto_escalate=config.auto_escalate,
            max_cost=config.max_cost,
            max_turns=config.max_turns,
            shell_timeout=config.shell_timeout,
            claude_timeout=config.claude_timeout,
            truncation_limit=config.truncation_limit,
            base_url=config.base_url,
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield OutputLog(id="output")
        yield StreamDisplay(id="stream")
        yield StatusBar(id="status")
        yield InputBar(id="input", placeholder="Type a message or /help...")
        yield Footer()

    def on_mount(self) -> None:
        subscribe(self._on_event)
        log = self.query_one("#output", OutputLog)
        log.write_system(f"Project: {self._project_dir}")
        log.write_system("Ctrl+Z = interrupt agent · Ctrl+Q = quit · /help for commands")
        self.query_one("#status", StatusBar).model_text = self.session.model
        self.query_one("#input", InputBar).focus()
        self.run_worker(self._run_orchestrator(), exclusive=True)
        self.run_worker(self._check_update())

    def on_unmount(self) -> None:
        unsubscribe(self._on_event)

    # ─── Event bridge ────────────────────────────────────────────────────

    def _on_event(self, event: Event) -> None:
        """Bridge from EventBus to Textual widgets. Called from same event loop."""
        self._handle_event(event)

    def _handle_event(self, event: Event) -> None:
        """Handle events on the Textual thread."""
        log = self.query_one("#output", OutputLog)
        stream = self.query_one("#stream", StreamDisplay)
        status = self.query_one("#status", StatusBar)
        d = event.data

        match event.type:
            case EventType.DEEPSEEK_START:
                self._ds_buffer = ""
                self._reasoning_buffer = ""
                status.thinking = True
            case EventType.DEEPSEEK_THINKING:
                status.thinking = True
            case EventType.DEEPSEEK_TOKEN:
                self._ds_buffer += d.get("text", "")
                stream.show_streaming("DeepSeek", self._ds_buffer, "cyan")
            case EventType.DEEPSEEK_REASONING:
                self._reasoning_buffer += d.get("text", "")
                stream.show_streaming("thinking", self._reasoning_buffer, "#5f87af")
            case EventType.DEEPSEEK_DONE:
                stream.clear_streaming()
                summary = d.get("cost", "")
                log.write_deepseek_done(self._ds_buffer, summary)
                self._ds_buffer = ""
                self._reasoning_buffer = ""
                status.thinking = False
                status.cost_text = summary
            case EventType.DEEPSEEK_ERROR:
                stream.clear_streaming()
                log.write_deepseek_error(d.get("error", ""))
                status.thinking = False
            case EventType.DEEPSEEK_RETRY:
                log.write_deepseek_retry(d.get("reason", "API error"), d.get("wait", 0))
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
                stream.clear_streaming()
                log.write_interrupt()
                status.thinking = False
            case EventType.QUEUE_UPDATE:
                status.queue_count = d.get("count", 0)
            case EventType.SUMMARY:
                log.write_system("Conversation history summarized.")
            case EventType.MODEL_SWITCH:
                model = d.get("model", "")
                escalated = model == self.session.pro_model
                status.model_text = f"{model} ↑" if escalated else model
                reason = d.get("reason", "")
                if escalated:
                    log.write_system(f"↑ escalated to {model}" + (f": {reason}" if reason else ""))
                elif reason:
                    log.write_system(f"↓ back to {model}")

    # ─── Input handling ──────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return

        input_bar = self.query_one("#input", InputBar)
        input_bar.add_to_history(text)
        event.input.clear()

        if text.lower() in {"exit", "quit", "q", "çıkış"}:
            self.exit()
            return

        log = self.query_one("#output", OutputLog)
        log.write_user(text)

        if dispatch(text, self):
            return

        self._user_queue.put_nowait(text)

        if self._agent_running:
            count = self._user_queue.qsize
            emit(EventType.QUEUE_UPDATE, count=count)

    # ─── Interrupt handling ──────────────────────────────────────────────

    def action_interrupt(self) -> None:
        if self._agent_running:
            self.session.interrupt_event.set()
            proc = get_proc(self.session)
            if proc and proc.returncode is None:
                proc.terminate()
            emit(EventType.INTERRUPT)
        else:
            log = self.query_one("#output", OutputLog)
            log.write_system("No agent running. Ctrl+Q to quit.")

    # ─── Slash command handlers ──────────────────────────────────────────

    def handle_reset(self) -> None:
        reset_session(self.session)
        self.session.cost.reset()
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

    async def _check_update(self) -> None:
        """Non-blocking version check on startup."""
        from .version_check import check_for_update

        latest = await check_for_update()
        if latest:
            from . import __version__

            msg = f"Update available: supervis {latest} (you have {__version__}). Run: pipx upgrade supervis"
            emit(EventType.STATUS, text=msg)

    async def _run_orchestrator(self) -> None:
        """Main agent loop. Runs as a Textual worker."""
        from .orchestrator import orchestrate

        await orchestrate(
            message_queue=self._user_queue,
            session=self.session,
            system_prompt=self._system_prompt,
            set_agent_running=self._set_agent_running,
        )

    def _set_agent_running(self, running: bool) -> None:
        self._agent_running = running
