# supervis

DeepSeek reads your codebase and drives Claude Code so you don't have to babysit every prompt.

## What it does

- Explores the project before writing a single line
- Sends precise, context-aware prompts to Claude Code
- Reviews the diff, fixes mistakes, continues on its own
- Only asks you for real decisions (architecture, trade-offs)
- Queues your messages while it works, type anytime, nothing is lost

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

→ DeepSeek reads the codebase
→ Claude Code writes the implementation
→ DeepSeek checks the diff, corrects if needed
→ "Done. Added verify_token() in auth/tokens.py, middleware in auth/middleware.py."

You: actually make it session-based    ← typed while agent was working, queued automatically
```

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
You → DeepSeek (reads files, plans) → Claude Code (writes code) → DeepSeek (verifies) → You
```

DeepSeek uses [DeepSeek V3.2](https://platform.deepseek.com) via API. Claude Code runs locally with `bypassPermissions` so it edits files without asking for each one.

## Cost

Shown after each response:

```
[in 12.3k  4.1k cached · out 0.8k · $0.0031]
```

DeepSeek V3.2 pricing: $0.28/1M input · $0.028/1M cached · $0.42/1M output.

## License

MIT
