"""Configuration: TOML-based, layered (global + per-project + env vars)."""

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

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
    model: str = "deepseek-v4-flash"  # base/driver tier
    pro_model: str = "deepseek-v4-pro"  # escalation tier
    thinking: bool = True
    auto_escalate: bool = True

    # Behavior
    max_cost: float | None = None
    max_turns: int = 50  # tool-calling turns per user message; 0 disables the cap
    shell_timeout: int = 15
    claude_timeout: int = 1800  # idle, not total: seconds of silence before the worker is killed
    truncation_limit: int = 16000


def _warn(message: str) -> None:
    """Surface a config problem. Startup happens before the TUI, so stderr works."""
    logger.warning(message)
    print(f"supervis: {message}", file=sys.stderr)


def _write_secret(path: Path, content: str) -> None:
    """Write a file containing a credential, 0600 from the moment it exists.

    write_text() then chmod() leaves the key readable at the umask default for
    however long the two calls take.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    # O_CREAT's mode is ignored when the file already existed, so fix that case too.
    path.chmod(0o600)


def _read_toml(path: Path) -> dict:  # type: ignore[type-arg]
    """Read a TOML file. Missing is normal; broken is worth saying out loud."""
    try:
        result: dict = tomllib.loads(path.read_text(encoding="utf-8"))  # type: ignore[type-arg]
        return result
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        _warn(f"ignoring {path}: invalid TOML ({e}). Running with defaults for those settings.")
        return {}
    except OSError as e:
        _warn(f"ignoring {path}: {e}")
        return {}


def _apply_toml(config: Config, data: dict) -> None:
    """Apply TOML dict to config, handling flat and [behavior] keys."""
    if "api_key" in data:
        config.api_key = str(data["api_key"]).strip()
    if "model" in data:
        config.model = str(data["model"]).strip()
    if "pro_model" in data:
        config.pro_model = str(data["pro_model"]).strip()
    if "thinking" in data:
        config.thinking = bool(data["thinking"])
    if "auto_escalate" in data:
        config.auto_escalate = bool(data["auto_escalate"])

    behavior = data.get("behavior", {})
    if "max_cost" in behavior:
        config.max_cost = float(behavior["max_cost"])
    if "max_turns" in behavior:
        config.max_turns = int(behavior["max_turns"])
    if "shell_timeout" in behavior:
        config.shell_timeout = int(behavior["shell_timeout"])
    if "claude_timeout" in behavior:
        config.claude_timeout = int(behavior["claude_timeout"])
    if "truncation_limit" in behavior:
        config.truncation_limit = int(behavior["truncation_limit"])

    # Also accept flat keys for convenience (no [behavior] section needed)
    for key in ("max_cost", "max_turns", "shell_timeout", "claude_timeout", "truncation_limit"):
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

    pro_model = os.environ.get("SUPERVIS_PRO_MODEL", "").strip()
    if pro_model:
        config.pro_model = pro_model

    thinking = os.environ.get("SUPERVIS_THINKING", "").strip().lower()
    if thinking in ("0", "false", "no", "off"):
        config.thinking = False
    elif thinking in ("1", "true", "yes", "on"):
        config.thinking = True

    auto = os.environ.get("SUPERVIS_AUTO_ESCALATE", "").strip().lower()
    if auto in ("0", "false", "no", "off"):
        config.auto_escalate = False
    elif auto in ("1", "true", "yes", "on"):
        config.auto_escalate = True


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
            _write_secret(_GLOBAL_CONFIG_FILE, f'api_key = "{api_key}"\n')
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

    # Legacy model ids were retired 2026-07-24. Remap so old configs keep working.
    _migrate_legacy_model(config)

    return config


_LEGACY_MODELS = {
    "deepseek-chat": ("deepseek-v4-flash", False),
    "deepseek-reasoner": ("deepseek-v4-flash", True),
}


def _migrate_legacy_model(config: Config) -> None:
    """Remap retired model ids to their V4 equivalent, with a one-line notice."""
    mapped = _LEGACY_MODELS.get(config.model)
    if not mapped:
        return
    new_model, thinking = mapped
    print(f"Note: '{config.model}' was retired on 2026-07-24 — using {new_model} instead.")
    config.model = new_model
    config.thinking = thinking


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

    _write_secret(_GLOBAL_CONFIG_FILE, f'api_key = "{key}"\n')
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
