"""CLI entry point."""

import asyncio
import os
import sys
from pathlib import Path


def main() -> None:
    import readline  # noqa: F401 — enables arrow keys + history in input()

    project_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    project_dir = str(Path(project_dir).resolve())

    if not Path(project_dir).is_dir():
        print(f"Directory not found: {project_dir}")
        sys.exit(1)

    from .chat import chat_loop

    try:
        asyncio.run(chat_loop(project_dir))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
