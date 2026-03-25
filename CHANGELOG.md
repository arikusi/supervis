# Changelog

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
