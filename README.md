# supervis

DeepSeek thinks, plans, and drives Claude Code through your project so you don't babysit every prompt. You give the goal, supervis manages the execution.

## What it does

* Breaks your request into steps and sends each one to Claude Code
* Keeps going until the full task is done, not just one step
* Uses DeepSeek V3.2 with thinking mode for better planning and reasoning
* Only asks you when there's a real decision to make (architecture, trade-offs)
* Queues your messages while it works — type anytime, nothing is lost
* Reads `.supervis/SUPERVIS.md` for project-specific instructions

## Install

```bash
pipx install supervis
```

Requires [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and a [DeepSeek API key](https://platform.deepseek.com/api-keys).

## Usage

```bash
cd myproject
supervis
```

```
You: add JWT authentication

→ DeepSeek plans the approach (thinking mode)
→ Claude Code writes auth/tokens.py, auth/middleware.py
→ DeepSeek sends the next step, Claude Code continues
→ "Done. JWT auth added with verify_token() and require_auth() middleware."

You: actually make it session-based    ← typed while agent was working, queued automatically
```

## Project Instructions

Create `.supervis/SUPERVIS.md` in your project root to give DeepSeek context about your project:

```bash
mkdir .supervis
cat > .supervis/SUPERVIS.md << 'EOF'
Tech stack: Next.js 15, TypeScript, PostgreSQL, Tailwind CSS.
Follow the plan in PLAN.md.
Always run `npm run build` after making changes.
EOF
```

These instructions are injected into DeepSeek's system prompt on startup.

## Controls

| Key | Action |
|-----|--------|
| `ESC` or `Ctrl+C` | Interrupt agent, return to prompt |
| `Ctrl+C` (idle) × 2 | Exit |
| `exit` | Exit |

## Commands

| Command | Description |
|---------|-------------|
| `/reset` | Reset Claude session and conversation history |
| `/help` | Show available commands |

## API Key

First run will prompt you if no key is set:

```
No DeepSeek API key found.
Get one at: https://platform.deepseek.com/api-keys

Enter your API key: sk-...
Saved to ~/.config/supervis/config
```

Or set it yourself (takes precedence):

```bash
set -Ux DEEPSEEK_API_KEY sk-...   # fish
export DEEPSEEK_API_KEY=sk-...    # bash/zsh
```

## How it works

```
You → DeepSeek (thinks, plans) → Claude Code (writes code) → DeepSeek (next step) → ... → You
```

DeepSeek uses [DeepSeek V3.2](https://platform.deepseek.com) with thinking mode via API. Claude Code runs locally with `bypassPermissions` so it edits files without asking for each one.

DeepSeek has access to these tools:
* **run_claude** — send a task to Claude Code
* **read_file, list_files, search_code** — understand the codebase before delegating
* **run_shell** — quick shell commands (git log, build checks)
* **get_git_status** — see what changed

## Cost

Shown after each DeepSeek response:

```
[in 12.3k  4.1k cached · out 0.8k · $0.0031]
```

DeepSeek V3.2 pricing: $0.28/1M input · $0.028/1M cached · $0.42/1M output.

## License

MIT
