# Contributing

Thanks for wanting to help. Here is how it works.

## Reporting issues

Open a GitHub issue. Describe what you did, what you expected, and what happened instead. A stack trace helps if there is one.

## Submitting changes

Fork the repo, make your changes, open a pull request. No formal process, no CLA.

A few things that make reviews easier:

- Keep changes focused. One thing per PR.
- If you are adding a new feature, briefly explain why in the PR description.
- If you are fixing a bug, link the issue.

## Project structure

```
supervisor/
  display.py    colors and print helpers
  prompts.py    system prompt (edit this to change DeepSeek behavior)
  tools.py      tool definitions and implementations
  claude.py     Claude Code subprocess management
  deepseek.py   DeepSeek API client and agent loop
  memory.py     conversation history summarization
  chat.py       main loop, input queue, interrupt handling
  config.py     API key resolution
  cost.py       token and cost tracking
  main.py       CLI entry point
```

## Running locally

```bash
git clone https://github.com/yourname/supervis
cd supervis
python -m venv .venv && source .venv/bin/activate
pip install -e .
supervis
```

## Questions

Open an issue or start a discussion. No stupid questions.
