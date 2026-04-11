# Contributing

Thanks for wanting to help. Here is how it works.

## Reporting issues

Open a GitHub issue. Describe what you did, what you expected, and what happened instead. A stack trace helps if there is one.

## Submitting changes

Fork the repo, make your changes, open a pull request. No formal process, no CLA.

A few things that make reviews easier:

* Keep changes focused. One thing per PR.
* If you are adding a new feature, briefly explain why in the PR description.
* If you are fixing a bug, link the issue.

## Project structure

```
supervisor/
  app.py           — Textual App: layout, key bindings, event bridge
  orchestrator.py  — async message loop, drives the agent
  deepseek.py      — DeepSeek API client, streaming, agent loop
  claude.py        — Claude Code subprocess, stream-json parsing
  session.py       — Session + CostTracker dataclasses
  events.py        — EventBus + typed event definitions
  commands.py      — slash command registry (/reset, /model, /status, /config, /export, /undo, /budget, /update)
  tools.py         — tool definitions for DeepSeek
  widgets/         — OutputLog, InputBar, StatusBar
  config.py        — TOML config system (global + per-project + env vars)
  cost.py          — token tracking (backward compat wrapper)
  memory.py        — conversation summarization
  prompts.py       — DeepSeek system prompt
  version_check.py — PyPI update checker
  main.py          — CLI entry point
```

## Running locally

```bash
git clone https://github.com/yourname/supervis
cd supervis
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,test]"
supervis
```

## Linting and type checking

The project uses ruff for linting and mypy for type checking. CI runs both on every push.

```bash
ruff check .
mypy supervisor/
```

## Running tests

```bash
pytest
```

Tests cover session management, cost tracking, version checking, and config loading. CI runs the test suite across Python 3.10 through 3.13.

## Questions

Open an issue or start a discussion. No stupid questions.
