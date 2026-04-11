"""Session state container. Replaces module-level globals across the codebase."""

import asyncio
import time
from dataclasses import dataclass, field
from openai import AsyncOpenAI


@dataclass
class CostTracker:
    """Token and cost tracking for a single session."""

    input_tokens: int = 0
    input_cached: int = 0
    output_tokens: int = 0

    # DeepSeek V3.2 pricing (per 1M tokens)
    price_input: float = 0.28
    price_input_cached: float = 0.028
    price_output: float = 0.42

    def record(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> None:
        self.input_tokens += input_tokens - cached_tokens
        self.input_cached += cached_tokens
        self.output_tokens += output_tokens

    def session_cost(self) -> float:
        return (
            self.input_tokens / 1_000_000 * self.price_input
            + self.input_cached / 1_000_000 * self.price_input_cached
            + self.output_tokens / 1_000_000 * self.price_output
        )

    def summary(self) -> str:
        total_in = self.input_tokens + self.input_cached
        cached = self.input_cached
        out = self.output_tokens
        cost = self.session_cost()

        cached_note = f"  {cached / 1000:.1f}k cached" if cached else ""
        return f"in {total_in / 1000:.1f}k{cached_note} · out {out / 1000:.1f}k · ${cost:.4f}"

    def reset(self) -> None:
        self.input_tokens = self.input_cached = self.output_tokens = 0


@dataclass
class Session:
    """All mutable state for one supervisor session."""

    client: AsyncOpenAI
    messages: list = field(default_factory=list)
    cost: CostTracker = field(default_factory=CostTracker)
    interrupt_event: asyncio.Event = field(default_factory=asyncio.Event)
    claude_proc: asyncio.subprocess.Process | None = None
    claude_first: bool = True

    # Model config
    model: str = "deepseek-chat"
    thinking: bool = True

    # Limits
    max_cost: float | None = None
    shell_timeout: int = 15
    claude_timeout: int = 300
    truncation_limit: int = 4000

    # Tracking
    start_time: float = field(default_factory=time.time)

    def reset(self) -> None:
        """Reset conversation state. Keeps client and config."""
        self.messages = [self.messages[0]] if self.messages else []
        self.cost.reset()
        self.claude_first = True

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

    def switch_model(self, model: str, thinking: bool) -> None:
        """Switch DeepSeek model. Resets Claude session for fresh context."""
        self.model = model
        self.thinking = thinking
        self.claude_first = True

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
                self.messages[i] = {
                    k: v for k, v in self.messages[i].items() if k != "reasoning_content"
                }
