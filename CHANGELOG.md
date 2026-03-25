# Changelog

## 0.2.3 — 2026-03-26

### Fixed

* **Display noise in agent loop.** Every intermediate DeepSeek API call (tool-only turns) printed a separate `DeepSeek:` header and cost summary, creating cascading output. Now only the first turn shows the header; intermediate tool-only turns are quiet. Cost is shown when DeepSeek actually speaks.
* **DeepSeek reading files endlessly.** Despite prompt guidance, DeepSeek still called read_file/list_files 10+ times in a row instead of delegating to Claude Code. Rewrote system prompt with explicit prohibition and added "RARELY NEEDED" to exploration tool descriptions.

## 0.2.2 — 2026-03-26

### Fixed

* **400 error after interrupt.** When the user interrupted during tool execution, the assistant message with `tool_calls` was already in the history but tool results were missing. Next API call would fail with "insufficient tool messages following tool_calls". Now injects `(interrupted by user)` placeholder results for every unanswered tool_call_id.
* **Interrupt between tool calls.** If DeepSeek requested multiple tool calls in one turn, interrupt was only checked before the batch, not between individual calls. Now checks between each tool call and fills placeholders for the rest.

### Changed

* **Prompt discourages excessive file reading.** DeepSeek was reading files one by one (10+ read_file calls in a row) instead of telling Claude Code to explore. Prompt now explicitly limits exploration tools to 1-2 quick checks and pushes everything else to run_claude.

## 0.2.1 — 2026-03-26

### Fixed

* **Double Ctrl+C exit broken.** First Ctrl+C set `_ctrl_c_idle = True`, but the next loop iteration immediately reset it to `False` before the second Ctrl+C could be read. Moved the reset so it only clears when the user types actual input.
* **Interrupt watcher race condition.** `_watch_interrupt` blocked indefinitely on `input_queue.get()` even after the agent task finished, preventing clean cancellation. Now polls with a 300ms timeout so it notices when the agent is done.
* **Unused `interrupts` variable.** Drain queue filtered interrupts into a list that was never used. Removed the dead variable, simplified to a single filter.

## 0.2.0 — 2026-03-26

Supervisor overhaul. DeepSeek now thinks before acting, recovers from errors, and respects project-level instructions.

### Changed

* **Thinking mode enabled.** DeepSeek uses `deepseek-chat` with thinking mode (`reasoning_content`) instead of plain chat. Better planning, same pricing. The `reasoning_content` field is properly preserved across multi-turn tool call loops so the API doesn't reject follow-up requests.
* **System prompt rewritten.** DeepSeek acts as a project manager: delegates work to Claude Code, keeps momentum, only stops for real architectural decisions. No more "should I continue?" pauses.
* **Agent loop fixed.** DeepSeek no longer breaks out of the loop when it produces text alongside a tool call. Previously, narrating while calling a tool caused the loop to stop and wait for user input.
* **Summarization tuned.** Threshold raised from 20 to 40 messages, last 12 messages preserved (was 8). Old `reasoning_content` is stripped before summarizing to save tokens.

### Added

* **Thinking indicator.** Terminal shows `thinking...` while DeepSeek reasons, so it no longer looks frozen.
* **Retry with backoff.** DeepSeek API calls retry up to 3 times on transient errors (429, 5xx) with exponential backoff (2s, 4s, 8s). After exhausting retries, returns to the prompt instead of crashing the session.
* **Claude output truncation.** Claude Code responses are truncated to 4000 characters before being sent back to DeepSeek. The full output is still displayed in the terminal. Prevents context bloat from long Claude runs.
* **`run_shell` tool restored.** DeepSeek can run quick shell commands (`git log`, `ls`, `npm run build`) directly without routing through Claude Code.
* **`.supervis/` project directory.** Place a `SUPERVIS.md` file in `.supervis/` at the project root and its contents are injected into DeepSeek's system prompt on startup. Project-specific instructions, constraints, tech stack notes — all picked up automatically.

### Fixed

* **Display cleanup.** Claude Code output properly separates text from tool call indicators. Text blocks get newlines, tool hints are dimmed and indented. The prompt preview is truncated to 120 chars in the box header.
* **Project URLs in pyproject.toml** now point to the actual repository.

## 0.1.0 — 2026-03-25

Initial release. Basic supervisor loop with DeepSeek V3.2 driving Claude Code.
