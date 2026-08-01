# Contributing

Thanks for wanting to help. Here is how it works.

## Reporting issues

Open a GitHub issue. Describe what you did, what you expected, and what happened instead. A stack trace helps if there is one. `~/.local/share/supervis/supervis.log` holds the last few runs and is usually the fastest way to see what went wrong.

## Submitting changes

Fork the repo, make your changes, open a pull request. No formal process, no CLA.

A few things that make reviews easier:

* Keep changes focused. One thing per PR.
* If you are adding a new feature, briefly explain why in the PR description.
* If you are fixing a bug, link the issue.

## Project structure

```
supervisor/
  main.py            — CLI entry point, argument parsing, startup preflight
  app.py             — Textual App: layout, key bindings, event bridge
  orchestrator.py    — async message loop, drives the agent
  deepseek.py        — DeepSeek API client, streaming, retry, agent loop
  claude.py          — Claude Code subprocess, stream-json parsing
  session.py         — Session + CostTracker, model tiering, self-correction
  pricing.py         — per-model token rates
  events.py          — EventBus + typed event definitions
  commands.py        — slash command registry
  tools.py           — tool definitions and implementations for DeepSeek
  queue.py           — user message queue with cancel/list support
  config.py          — TOML config (global + per-project + env vars)
  memory.py          — conversation summarization
  prompts.py         — DeepSeek system prompt
  logging_config.py  — rotating file log, optional stderr debug
  version_check.py   — PyPI update checker
  widgets/           — OutputLog, StreamDisplay, StatusBar, InputBar
```

The rule that keeps the layers apart: business logic never imports UI. Modules like `deepseek.py`, `claude.py`, and `tools.py` call `emit()` with a typed event; `app.py` subscribes and renders. If you find yourself importing a widget into logic, that is the sign to add an event instead.

Slash commands live in `commands.py` and register themselves with the `@register` decorator, so adding one is a single function. The current set is `/reset`, `/help`, `/model`, `/auto`, `/status`, `/config`, `/export`, `/undo`, `/update`, `/queue`, `/cancel`, `/budget`, `/reasoning`.

## Running locally

```bash
git clone https://github.com/arikusi/supervis
cd supervis
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,test]"
supervis
```

You will need the Claude Code CLI on your PATH and a DeepSeek API key. supervis checks for both at startup.

## Linting and type checking

ruff for linting and formatting, mypy for types. CI runs all three on every push, and the format check is not advisory — a PR that is not formatted will fail.

```bash
ruff check supervisor/ tests/
ruff format --check supervisor/ tests/
mypy supervisor/ --ignore-missing-imports
```

## Running tests

```bash
pytest
```

Tests are offline by design: no test makes a real API call or spawns a real Claude Code process. Anything that would talk to the network is mocked. Keep it that way.

CI runs the suite on Python 3.10 through 3.14.

## Questions

Open an issue or start a discussion. No stupid questions.
