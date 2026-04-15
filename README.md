<p align="center">
  <img src="assets/logo.svg" width="300" alt="supervis">
</p>

<p align="center">
  <a href="https://pypi.org/project/supervis/"><img src="https://img.shields.io/pypi/v/supervis" alt="PyPI version"></a>
  <a href="https://pepy.tech/projects/supervis"><img src="https://static.pepy.tech/badge/supervis" alt="PyPI downloads"></a>
  <a href="https://pypi.org/project/supervis/"><img src="https://img.shields.io/pypi/pyversions/supervis" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://deepwiki.com/arikusi/supervis"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
  <a href="https://github.com/arikusi/supervis"><img src="https://img.shields.io/github/stars/arikusi/supervis" alt="GitHub stars"></a>
</p>

<h3 align="center">DeepSeek thinks, plans, and drives Claude Code through your project<br>so you don't babysit every prompt.</h3>

## What if you weren't the bottleneck?

Claude Code can read your codebase, write code, run builds, fix errors. It's remarkably capable. But here's the catch: **you** are still the one deciding what to do next. You break the task into steps, you prompt for each piece, you review and redirect. Even with plan mode and task lists, you're babysitting.

supervis puts [DeepSeek](https://platform.deepseek.com) between you and Claude Code as a technical lead. You describe what you want once. supervis handles the rest.

## Demo

<p align="center">
  <img src="assets/demo.svg" alt="supervis demo" width="100%">
</p>

## How supervis works

DeepSeek tells Claude Code what to do. Claude Code explores the codebase, writes code, runs builds, and reports back. DeepSeek reviews the results and decides the next step. DeepSeek doesn't read your files directly. It directs and decides, Claude Code does the hands-on work. This keeps the supervisor's token usage low.

The loop keeps going until the **entire task** is done. You watch it work in real time, and step in only when you want to.

No more "can I edit this file?" prompts either. supervis runs Claude Code with `--permission-mode bypassPermissions`, so it reads, writes, builds, and tests without stopping to ask at every step. Under the hood, every task is a call to:

```
claude -p <prompt> --output-format stream-json --verbose --permission-mode bypassPermissions
```

You see everything Claude Code does: every file read, every edit, every shell command, live in the TUI. Full transparency, zero interruptions.

## Before supervis

Claude Code is great. You can give it plan mode, task lists, detailed prompts. But you're still the one leading the session. You check in after each step, redirect when something goes off track, decide what to tackle next, and prompt again when it stalls. That's fine for small tasks. For anything bigger, you're babysitting.

## With supervis

You describe the end goal once, and it drives Claude Code through the entire thing:

```
You: add JWT authentication with a login endpoint, protect all routes, make sure the build passes

DeepSeek: thinking...
┌─ Claude Code  Read project structure and check for existing auth...
│ Read: src/routes/index.ts
│ Read: package.json
│ No existing auth found.
└─ done (4 tool calls)
DeepSeek: No auth layer yet. Starting with JWT middleware, then login
          endpoint, then route protection.
┌─ Claude Code  Create JWT middleware and wire it up...
│ Write: src/auth/middleware.ts
│ Write: src/auth/login.ts
│ Edit: src/routes/index.ts
│ ↳ Bash: npm run build
│ Build passed.
└─ done (12 tool calls)
DeepSeek: Done. POST /auth/login returns a token, all routes
          verify it. Build is clean.
```

If the build had failed, supervis would have told Claude Code to fix the errors and try again, without you typing a single follow-up. It keeps going until the task is actually done.

Less technical knowledge? supervis handles the decisions you wouldn't know to make. More technical knowledge? You write better prompts and supervis becomes a serious force multiplier.

## Install

```bash
pipx install supervis
```

Or ask Claude Code: *"install supervis from github.com/arikusi/supervis"*

You need two things:
* [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed (subscription is enough, no Anthropic API key needed)
* A [DeepSeek API key](https://platform.deepseek.com/api-keys)

supervis calls Claude Code as a local subprocess, not through the API. DeepSeek handles the planning via its own API, which is [remarkably cheap](https://api-docs.deepseek.com/quick_start/pricing) for what it delivers.

```bash
cd your-project
supervis
```

First run will ask for your DeepSeek API key and save it.

**Quick start:**
```bash
pipx install supervis && cd your-project && supervis
```

## Getting better results

supervis is only as good as the context it gets. A blank project works, but a project with a `.supervis/SUPERVIS.md` works significantly better:

```bash
mkdir .supervis
cat > .supervis/SUPERVIS.md << 'EOF'
Tech stack: Next.js 15, TypeScript, PostgreSQL, Tailwind CSS.
Follow the plan in PLAN.md.
Always run `npm run build` after making changes.
Use the existing auth patterns in src/lib/auth.
EOF
```

Think of it like onboarding a new developer. The more context you give (tech stack, conventions, existing patterns, a plan document), the fewer wrong turns supervis takes. Setting up relevant MCP servers and environment variables for your project also helps Claude Code do its job better.

**One important thing:** you're talking to a supervisor, not a code editor. supervis will delegate everything to Claude Code. Frame your prompts that way.

Example prompts:

```
Have Claude build me a personal portfolio site. I'm a frontend developer based
in Berlin, 3 years of experience, React and TypeScript. Include an about page,
project showcase, and contact form. Keep it clean and modern.
```

```
Have Claude set up a REST API for a todo app. Express, TypeScript. CRUD
endpoints, input validation, error handling. Have it write tests and run
them before finishing.
```

```
Have Claude read through this project, understand the architecture, then
add dark mode. Nothing should break. Run the build when done.
```

You tell supervis what you want. supervis tells Claude Code how to build it.

## Commands

| Command | What it does |
|---------|-------------|
| `/model chat` | DeepSeek-chat with thinking, best quality (default) |
| `/model chat-fast` | DeepSeek-chat without thinking, faster |
| `/model reasoner` | DeepSeek-reasoner, maximum reasoning, 64K output |
| `/status` | Model, cost, uptime, message count |
| `/budget` | Cost vs. budget limit |
| `/export md` or `json` | Export conversation to file |
| `/undo` | Git stash or revert last changes |
| `/update` | Check for new supervis version |
| `/reasoning` | Toggle DeepSeek thinking/reasoning display |
| `/queue` | Show queued messages |
| `/cancel` | Cancel queued messages (`/cancel N` for specific) |
| `/reset` | Clear session and start fresh |

`Ctrl+Z` interrupts the running agent. `Ctrl+Q` quits. Up/down arrows cycle through input history.

## Configuration

TOML config, layered: built-in defaults → `~/.config/supervis/config.toml` → `.supervis/config.toml` → environment variables.

<details>
<summary>Example global config</summary>

```toml
api_key = "sk-..."
model = "deepseek-chat"
thinking = true

[behavior]
max_cost = 1.00
shell_timeout = 15
claude_timeout = 300
truncation_limit = 4000
```
</details>

<details>
<summary>Per-project override</summary>

```toml
model = "deepseek-reasoner"

[behavior]
max_cost = 2.00
```
</details>

**Environment variables:** `DEEPSEEK_API_KEY`, `SUPERVIS_MODEL`, `SUPERVIS_THINKING`

**Cost budget:** Set `max_cost` to cap spending. supervis warns at 80% and stops at 100%.

## Cost

DeepSeek pricing: **$0.28/1M input** · $0.028/1M cached · **$0.42/1M output**. How much you spend depends on the task. Simple changes take fewer turns, complex features take more. The status bar tracks cost in real time so there are no surprises.

## What it doesn't do

* It's not magic. Vague prompts get vague results. Be specific about what you want.
* Claude Code runs with `bypassPermissions` (explained above). It edits files without asking. That's intentional, but be aware.
* DeepSeek only, for now. It works well. Contributors are welcome to add other providers.
* No session persistence yet. Closing supervis loses the conversation.
* Large monorepos benefit from a focused `.supervis/SUPERVIS.md`. Without guidance, supervis may wander.

## Architecture

Event-driven, async. Business logic emits typed events through an EventBus. The Textual TUI subscribes and renders. Zero coupling between logic and UI.

<details>
<summary>Modules</summary>

```
supervisor/
  app.py           — Textual App, layout, key bindings, event bridge
  orchestrator.py  — async message loop, drives the agent
  deepseek.py      — DeepSeek API client, streaming, agent loop
  claude.py        — Claude Code subprocess, stream-json parsing
  session.py       — Session + CostTracker dataclasses
  events.py        — EventBus + typed event definitions
  commands.py      — slash command registry
  tools.py         — tool definitions for DeepSeek
  version_check.py — PyPI update checker
  config.py        — TOML config (global + per-project + env vars)
  memory.py        — conversation summarization
  prompts.py       — system prompt
  widgets/         — OutputLog, InputBar, StatusBar
```
</details>

## Contributing

Issues and PRs welcome at [github.com/arikusi/supervis](https://github.com/arikusi/supervis). Use [Discussions](https://github.com/arikusi/supervis/discussions) for questions and ideas.

## License

MIT — built by [arikusi](https://github.com/arikusi)
