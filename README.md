<p align="center">
  <img src="assets/logo.svg" width="280" alt="supervis logo">
</p>

<h1 align="center">supervis</h1>

<p align="center">
  <a href="https://pypi.org/project/supervis/"><img src="https://img.shields.io/pypi/v/supervis" alt="PyPI version"></a>
  <a href="https://pypi.org/project/supervis/"><img src="https://img.shields.io/pypi/dm/supervis" alt="PyPI downloads"></a>
  <a href="https://pypi.org/project/supervis/"><img src="https://img.shields.io/pypi/pyversions/supervis" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://github.com/arikusi/supervis"><img src="https://img.shields.io/github/stars/arikusi/supervis" alt="GitHub stars"></a>
</p>

<p align="center">DeepSeek thinks, plans, and drives Claude Code through your project so you don't babysit every prompt.</p>

## Demo

<p align="center">
  <img src="assets/demo.svg" alt="supervis demo" width="100%">
</p>

## What it does

* Breaks your request into steps and sends each one to Claude Code
* Keeps going until the full task is done, not just one step
* Uses DeepSeek V3.2 with thinking mode for better planning and reasoning
* Full TUI with scrollable output, fixed input, and live status bar
* Watch Claude Code work in real time — every tool call, every file edit
* Type while the agent works — messages queue automatically
* Only asks you when there's a real decision to make
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

DeepSeek: thinking...
┌─ Claude Code  Implement JWT auth with verify_token()...
│ Read: src/auth/tokens.py
│ Write: src/auth/middleware.py
│ ↳ Bash: npm run build
│ Auth middleware added with JWT verification.
└─ done (8 tool calls)
DeepSeek: JWT auth done. Moving to route protection...  [$0.003]

You: actually make it session-based    ← typed while agent was working, queued
```

## Project Instructions

Create `.supervis/SUPERVIS.md` in your project root to give supervis context:

```bash
mkdir .supervis
cat > .supervis/SUPERVIS.md << 'EOF'
Tech stack: Next.js 15, TypeScript, PostgreSQL, Tailwind CSS.
Follow the plan in PLAN.md.
Always run `npm run build` after making changes.
EOF
```

Contents are injected into DeepSeek's system prompt on startup.

## Controls

| Key | Action |
|-----|--------|
| `Ctrl+D` | Interrupt running agent |
| `Ctrl+Q` | Quit |
| `exit` | Quit |

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

## Architecture

supervis uses an event-driven architecture. Business logic (DeepSeek API, Claude subprocess, tools) emits typed events through an EventBus. The Textual TUI subscribes and renders. No business logic imports UI code.

```
supervisor/
  app.py           — Textual App: layout, key bindings, event bridge
  orchestrator.py  — async message loop, drives the agent
  deepseek.py      — DeepSeek API client, streaming, agent loop
  claude.py        — Claude Code subprocess, stream-json parsing
  events.py        — EventBus + typed event definitions
  commands.py      — slash command registry (/reset, /help)
  tools.py         — tool definitions for DeepSeek
  widgets/         — OutputLog, InputBar, StatusBar
  config.py        — API key + project instructions
  cost.py          — token and cost tracking
  memory.py        — conversation summarization
  prompts.py       — DeepSeek system prompt
```

## Cost

Shown in the status bar after each DeepSeek response:

```
in 12.3k  4.1k cached · out 0.8k · $0.0031
```

DeepSeek V3.2 pricing: $0.28/1M input · $0.028/1M cached · $0.42/1M output.

## Contributing

Issues and PRs welcome at [github.com/arikusi/supervis](https://github.com/arikusi/supervis). Use [Discussions](https://github.com/arikusi/supervis/discussions) for questions and ideas.

## License

MIT
