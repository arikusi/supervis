"""Session state container. Replaces module-level globals across the codebase."""

import asyncio
import time
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from .defaults import DEFAULT_BASE_URL
from .pricing import price_for

# Auto-escalation tuning
ESCALATE_AFTER = 2  # consecutive unproductive run_claude results before escalating to pro
REPEAT_THRESHOLD = 3  # identical run_claude prompt sent this many times = stuck
STUCK_CAP = 5  # past this many failures, surface to the user

# Substrings that mark a run_claude result as unproductive. Kept deliberately strong
# so ordinary output that merely mentions "error" doesn't trip escalation.
_FAILURE_MARKERS = (
    "(no output)",
    "timed out",
    "traceback (most recent call last)",
    "build failed",
    "tests failed",
    "test failed",
    "compilation failed",
    "command not found",
    "no such file or directory",
    "fatal:",
    "segmentation fault",
)


@dataclass
class CostTracker:
    """Token and cost tracking for a single session.

    Dollars are accrued at record() time using each model's own rate, so a session
    that mixes flash and pro tokens (tiering) is billed correctly per tier.
    """

    input_tokens: int = 0
    input_cached: int = 0
    output_tokens: int = 0
    accrued_cost: float = 0.0
    unpriced_tokens: int = 0  # tokens from models with no known rate card

    def record(
        self,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        model: str = "deepseek-v4-flash",
    ) -> None:
        miss = input_tokens - cached_tokens
        self.input_tokens += miss
        self.input_cached += cached_tokens
        self.output_tokens += output_tokens

        rates = price_for(model)
        if rates is None:
            # Pointed at an endpoint we have no rates for. Count the tokens, but
            # do not invent a dollar figure — a wrong number is worse than none.
            self.unpriced_tokens += input_tokens + output_tokens
            return

        p_miss, p_cached, p_out = rates
        self.accrued_cost += (
            miss / 1_000_000 * p_miss + cached_tokens / 1_000_000 * p_cached + output_tokens / 1_000_000 * p_out
        )

    def session_cost(self) -> float:
        return self.accrued_cost

    @property
    def fully_priced(self) -> bool:
        return self.unpriced_tokens == 0

    def summary(self) -> str:
        total_in = self.input_tokens + self.input_cached
        cached = self.input_cached
        out = self.output_tokens

        cached_note = f"  {cached / 1000:.1f}k cached" if cached else ""
        counts = f"in {total_in / 1000:.1f}k{cached_note} · out {out / 1000:.1f}k"

        if self.fully_priced:
            return f"{counts} · ${self.session_cost():.4f}"
        if self.accrued_cost:
            # Some turns were priced and some weren't, so the total is a floor.
            return f"{counts} · ${self.session_cost():.4f}+ (some models unpriced)"
        return f"{counts} · cost unknown (no rate card for this model)"

    def reset(self) -> None:
        self.input_tokens = self.input_cached = self.output_tokens = 0
        self.accrued_cost = 0.0
        self.unpriced_tokens = 0


@dataclass
class Session:
    """All mutable state for one supervisor session."""

    client: AsyncOpenAI
    messages: list = field(default_factory=list)
    cost: CostTracker = field(default_factory=CostTracker)
    interrupt_event: asyncio.Event = field(default_factory=asyncio.Event)
    claude_proc: asyncio.subprocess.Process | None = None
    claude_first: bool = True

    # Active model for the current turn (derived by select_turn_model).
    model: str = "deepseek-v4-flash"
    thinking: bool = True
    show_reasoning: bool = False

    # Tiering: cheap driver (base) + frontier model for hard moments (pro).
    base_model: str = "deepseek-v4-flash"
    base_thinking: bool = True
    pro_model: str = "deepseek-v4-pro"
    pro_thinking: bool = True
    reasoning_effort: str = "high"  # used on pro turns

    # Escalation control
    auto_escalate: bool = True
    pinned: bool = False  # user pinned a model via /model; disables auto-tiering
    _pinned_model: str = ""
    _pinned_thinking: bool = True
    _escalate_next: bool = False  # one-shot: run the next turn on pro
    _failures: int = 0  # consecutive unproductive run_claude results
    _recent_prompts: list = field(default_factory=list)
    _pending_nudge: str | None = None
    _stuck_alert: bool = False

    # Limits
    max_cost: float | None = None
    max_turns: int = 50  # tool-calling turns per user message; 0 disables the cap
    shell_timeout: int = 15
    claude_timeout: int = 1800
    truncation_limit: int = 16000

    # Provider endpoint, kept for display only — the client is already built.
    base_url: str = DEFAULT_BASE_URL

    # Tracking
    start_time: float = field(default_factory=time.time)

    def reset(self) -> None:
        """Reset conversation state. Keeps client, config, and model preference."""
        self.messages = [self.messages[0]] if self.messages else []
        self.cost.reset()
        self.claude_first = True
        self._failures = 0
        self._escalate_next = False
        self._recent_prompts = []
        self._pending_nudge = None
        self._stuck_alert = False

    def check_budget(self) -> tuple[bool, str]:
        """Check cost against max_cost. Returns (ok_to_proceed, warning_or_empty)."""
        if self.max_cost is None:
            return True, ""

        current = self.cost.session_cost()
        ratio = current / self.max_cost

        if ratio >= 1.0:
            return False, f"Budget exceeded: ${current:.4f} / ${self.max_cost:.2f}"
        if ratio >= 0.8:
            return True, f"Budget warning: ${current:.4f} / ${self.max_cost:.2f} ({ratio:.0%})"
        return True, ""

    # ─── Model tiering ───────────────────────────────────────────────────────

    @property
    def escalated(self) -> bool:
        """True when the active model is the pro tier."""
        return self.model == self.pro_model

    def pin_model(self, model: str, thinking: bool) -> None:
        """Pin a model chosen by the user via /model. Disables auto-tiering."""
        self.pinned = True
        self._pinned_model = model
        self._pinned_thinking = thinking
        self.model = model
        self.thinking = thinking
        self.claude_first = True

    def unpin(self) -> None:
        """Return to automatic tiering (flash base, pro on escalation)."""
        self.pinned = False
        self._escalate_next = False
        self._failures = 0

    def request_escalation(self) -> None:
        """Run the next supervisor turn on pro (model-requested, one-shot)."""
        self._escalate_next = True

    def select_turn_model(self) -> tuple[bool, str]:
        """Pick the model for the upcoming supervisor turn.

        Returns (changed, reason) where changed is True if the active model id
        differs from the previous turn, so the caller can announce the switch.
        """
        prev = self.model
        reason = ""

        if self.pinned:
            target_model, target_thinking = self._pinned_model, self._pinned_thinking
        elif self.auto_escalate and (self._escalate_next or self._failures >= ESCALATE_AFTER):
            target_model, target_thinking = self.pro_model, self.pro_thinking
            reason = "requested" if self._escalate_next else f"{self._failures} failed attempts"
        else:
            target_model, target_thinking = self.base_model, self.base_thinking

        self._escalate_next = False  # one-shot, consumed
        self.model = target_model
        self.thinking = target_thinking

        changed = target_model != prev
        if changed and not reason and target_model == self.base_model:
            reason = "back to base"
        return changed, reason

    def note_claude_result(self, prompt: str, result: str) -> None:
        """Classify a run_claude outcome and update escalation counters.

        Failure markers or a repeated identical prompt count as "stuck". When the
        failure streak crosses ESCALATE_AFTER, a one-time self-correction nudge is
        queued (read via consume_nudge); STUCK_CAP queues a user alert.
        """
        text = result.lower()
        failed = any(m in text for m in _FAILURE_MARKERS)

        prefix = " ".join(prompt.split())[:80].lower()
        self._recent_prompts.append(prefix)
        self._recent_prompts = self._recent_prompts[-REPEAT_THRESHOLD:]
        repeating = len(self._recent_prompts) == REPEAT_THRESHOLD and len(set(self._recent_prompts)) == 1

        if failed or repeating:
            self._failures += 1
            if self._failures == ESCALATE_AFTER and self.auto_escalate and not self.pinned:
                self._pending_nudge = (
                    f"The last {self._failures} Claude Code attempts didn't make progress "
                    "(errors, timeouts, or the same step repeating). Stop repeating the same "
                    "approach. Step back, diagnose the root cause first, then form a corrected "
                    f"plan before the next run_claude. You are now on {self.pro_model} — think carefully."
                )
            if self._failures >= STUCK_CAP:
                self._stuck_alert = True
        else:
            self._failures = 0

    def consume_nudge(self) -> str | None:
        """Return a queued self-correction nudge once, then clear it."""
        nudge, self._pending_nudge = self._pending_nudge, None
        return nudge

    def consume_stuck_alert(self) -> bool:
        """Return True once when the session has crossed the stuck cap.

        Surfacing the alert ends the current run, so the counters start over —
        otherwise the very next failure would trip the cap again immediately.
        The next turn is queued on pro: whatever the user comes back with is
        answering a problem that already beat the cheap model five times.
        """
        alert, self._stuck_alert = self._stuck_alert, False
        if alert:
            self._failures = 0
            self._recent_prompts = []
            if self.auto_escalate and not self.pinned:
                self._escalate_next = True
        return alert

    def strip_old_reasoning(self) -> None:
        """Strip reasoning_content from older assistant messages.

        DeepSeek API rule: reasoning_content from previous turns should not
        be sent back. Only the current tool-call chain needs it.
        """
        # Find the last user message index — everything before it is "old"
        last_user_idx = -1
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].get("role") == "user":
                last_user_idx = i
                break

        if last_user_idx <= 0:
            return

        for i in range(last_user_idx):
            if "reasoning_content" in self.messages[i]:
                self.messages[i] = {k: v for k, v in self.messages[i].items() if k != "reasoning_content"}
