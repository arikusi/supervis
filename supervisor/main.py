"""CLI entry point."""

import os
import sys
from pathlib import Path


def main() -> None:
    # Parse --debug flag before anything else
    debug = "--debug" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--debug"]

    project_dir = args[0] if args else os.getcwd()
    project_dir = str(Path(project_dir).resolve())

    if not Path(project_dir).is_dir():
        print(f"Directory not found: {project_dir}")
        sys.exit(1)

    os.chdir(project_dir)

    # Set up logging before anything else
    from .logging_config import setup_logging

    setup_logging(debug=debug)

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
