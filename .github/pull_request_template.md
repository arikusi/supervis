## What this changes

<!-- One or two sentences. If it fixes an issue, link it: Fixes #123 -->

## Why

<!-- The problem behind the change. For a bug, what went wrong; for a feature, what it unblocks. -->

## Checklist

* [ ] `ruff check supervisor/ tests/` and `ruff format --check supervisor/ tests/` pass
* [ ] `mypy supervisor/ --ignore-missing-imports` passes
* [ ] `pytest` passes and coverage stays above the floor
* [ ] Tests cover the new behavior (no test hits a real API or spawns a real Claude Code process)
* [ ] CHANGELOG.md has an entry if this is user-visible
