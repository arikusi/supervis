"""API key resolution: env var → config file → interactive prompt."""

import os
from pathlib import Path

_CONFIG_DIR  = Path.home() / ".config" / "supervis"
_CONFIG_FILE = _CONFIG_DIR / "config"


def _read_saved() -> str | None:
    try:
        for line in _CONFIG_FILE.read_text().splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return None


def _save(key: str) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(f"DEEPSEEK_API_KEY={key}\n")
    _CONFIG_FILE.chmod(0o600)  # owner read/write only


def load_project_instructions(project_dir: str) -> str | None:
    """Load .supervis/SUPERVIS.md if it exists in the project directory."""
    path = Path(project_dir) / ".supervis" / "SUPERVIS.md"
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except (FileNotFoundError, PermissionError):
        return None


def get_api_key() -> str:
    # 1. Environment variable (takes precedence)
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key

    # 2. Saved config file
    key = _read_saved()
    if key:
        return key

    # 3. Interactive prompt — first run
    print("\nNo DeepSeek API key found.")
    print("Get one at: https://platform.deepseek.com/api-keys\n")
    try:
        key = input("Enter your API key: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        raise SystemExit(1)

    if not key:
        print("No key entered. Exiting.")
        raise SystemExit(1)

    _save(key)
    print(f"Saved to {_CONFIG_FILE}\n")
    return key
