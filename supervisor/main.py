"""CLI entry point."""

import argparse
import os
import sys
from pathlib import Path

from . import __version__

_CLAUDE_MISSING = (
    "Claude Code CLI not found on PATH.\n"
    "supervis drives `claude` as a local subprocess, so it has to be installed first:\n"
    "  https://docs.anthropic.com/en/docs/claude-code"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="supervis",
        description="DeepSeek supervisor that drives Claude Code through your project.",
    )
    parser.add_argument(
        "project_dir",
        nargs="?",
        default=None,
        metavar="DIRECTORY",
        help="project to work in (default: current directory)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="also write debug logs to stderr",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"supervis {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    project_dir = str(Path(args.project_dir or os.getcwd()).resolve())
    if not Path(project_dir).is_dir():
        print(f"Directory not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    os.chdir(project_dir)

    # Set up logging before anything else
    from .logging_config import setup_logging

    setup_logging(debug=args.debug)

    # Nothing to supervise without the worker. Fail here with something readable
    # instead of burying a FileNotFoundError in the first tool result.
    from .claude import claude_available

    if not claude_available():
        print(_CLAUDE_MISSING, file=sys.stderr)
        sys.exit(1)

    # Load config (TOML, layered)
    from .config import load_config, load_project_instructions, prompt_api_key

    config = load_config(project_dir)

    # Resolve API key if not in config or env
    if not config.api_key:
        config.api_key = prompt_api_key()

    # Build system prompt
    from .prompts import SYSTEM_PROMPT

    system_prompt = SYSTEM_PROMPT
    project_instructions = load_project_instructions(project_dir)
    if project_instructions:
        system_prompt += f"\n\n## Project Instructions\n{project_instructions}"

    # Launch TUI
    from .app import SupervisApp

    app = SupervisApp(project_dir=project_dir, system_prompt=system_prompt, config=config)
    app.run()


if __name__ == "__main__":
    main()
