"""Configuration: TOML-based, layered (global + per-project + env vars)."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

_GLOBAL_CONFIG_DIR = Path.home() / ".config" / "supervis"
_GLOBAL_CONFIG_FILE = _GLOBAL_CONFIG_DIR / "config.toml"
_OLD_CONFIG_FILE = _GLOBAL_CONFIG_DIR / "config"


@dataclass
class Config:
    """All supervis settings. Resolved once at startup."""

    # Provider
    api_key: str = ""
    model: str = "deepseek-chat"
    thinking: bool = True

    # Behavior
    max_cost: float | None = None
    shell_timeout: int = 15
    claude_timeout: int = 300
    truncation_limit: int = 4000


def _read_toml(path: Path) -> dict:
    """Read a TOML file, return empty dict if missing or broken."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, tomllib.TOMLDecodeError):
        return {}


def _apply_toml(config: Config, data: dict) -> None:
    """Apply TOML dict to config, handling flat and [behavior] keys."""
    if "api_key" in data:
        config.api_key = str(data["api_key"]).strip()
    if "model" in data:
        config.model = str(data["model"]).strip()
    if "thinking" in data:
        config.thinking = bool(data["thinking"])

    behavior = data.get("behavior", {})
    if "max_cost" in behavior:
        config.max_cost = float(behavior["max_cost"])
    if "shell_timeout" in behavior:
        config.shell_timeout = int(behavior["shell_timeout"])
    if "claude_timeout" in behavior:
        config.claude_timeout = int(behavior["claude_timeout"])
    if "truncation_limit" in behavior:
        config.truncation_limit = int(behavior["truncation_limit"])

    # Also accept flat keys for convenience (no [behavior] section needed)
    for key in ("max_cost", "shell_timeout", "claude_timeout", "truncation_limit"):
        if key in data and key not in behavior:
            val = data[key]
            if key == "max_cost":
                config.max_cost = float(val)
            else:
                setattr(config, key, int(val))


def _apply_env(config: Config) -> None:
    """Environment variables override everything."""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        config.api_key = key

    model = os.environ.get("SUPERVIS_MODEL", "").strip()
    if model:
        config.model = model

    thinking = os.environ.get("SUPERVIS_THINKING", "").strip().lower()
    if thinking in ("0", "false", "no", "off"):
        config.thinking = False
    elif thinking in ("1", "true", "yes", "on"):
        config.thinking = True


def _migrate_old_config() -> None:
    """Migrate old flat config to TOML if needed."""
    if _GLOBAL_CONFIG_FILE.exists() or not _OLD_CONFIG_FILE.exists():
        return

    try:
        api_key = ""
        for line in _OLD_CONFIG_FILE.read_text().splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break

        if api_key:
            _GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            _GLOBAL_CONFIG_FILE.write_text(f'api_key = "{api_key}"\n')
            _GLOBAL_CONFIG_FILE.chmod(0o600)
            print(f"Migrated config to {_GLOBAL_CONFIG_FILE}")
    except Exception:
        pass


def load_config(project_dir: str | None = None) -> Config:
    """Load config: defaults <- global TOML <- per-project TOML <- env vars."""
    _migrate_old_config()

    config = Config()

    # Layer 1: global TOML
    _apply_toml(config, _read_toml(_GLOBAL_CONFIG_FILE))

    # Layer 2: per-project TOML
    if project_dir:
        project_config = Path(project_dir) / ".supervis" / "config.toml"
        _apply_toml(config, _read_toml(project_config))

    # Layer 3: env vars (highest priority)
    _apply_env(config)

    return config


def prompt_api_key() -> str:
    """Interactive prompt for first-run API key setup. Saves to TOML config."""
    # Key is passed to AsyncOpenAI only; never logged or emitted via EventBus
    print("\nNo DeepSeek API key found.")
    print("Get one at: https://platform.deepseek.com/api-keys\n")
    try:
        key = input("Enter your API key: ").strip()
    except (EOFError, KeyboardInterrupt) as exc:
        print("\nCancelled.")
        raise SystemExit(1) from exc

    if not key:
        print("No key entered. Exiting.")
        raise SystemExit(1)

    _GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _GLOBAL_CONFIG_FILE.write_text(f'api_key = "{key}"\n')
    _GLOBAL_CONFIG_FILE.chmod(0o600)
    print(f"Saved to {_GLOBAL_CONFIG_FILE}\n")
    return key


def load_project_instructions(project_dir: str) -> str | None:
    """Load .supervis/SUPERVIS.md if it exists in the project directory."""
    path = Path(project_dir) / ".supervis" / "SUPERVIS.md"
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except (FileNotFoundError, PermissionError):
        return None


# Backward compat: get_api_key() still works for existing code
def get_api_key() -> str:
    """Resolve API key (env var -> config file -> interactive prompt)."""
    config = load_config()
    if config.api_key:
        return config.api_key
    return prompt_api_key()
