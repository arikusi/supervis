"""Non-blocking PyPI version check."""

import asyncio
import json
from urllib.error import URLError
from urllib.request import urlopen

from . import __version__

_PYPI_URL = "https://pypi.org/pypi/supervis/json"


def _fetch_latest() -> str | None:
    """Synchronous PyPI fetch. Returns latest version string or None."""
    try:
        with urlopen(_PYPI_URL, timeout=5) as resp:
            info = json.loads(resp.read())
            return str(info["info"]["version"])
    except (URLError, KeyError, json.JSONDecodeError, OSError):
        return None


async def check_for_update() -> str | None:
    """Check PyPI for a newer version. Non-blocking (runs in thread executor).

    Returns the latest version string if newer than installed, else None.
    Silent on any failure.
    """
    try:
        loop = asyncio.get_event_loop()
        latest = await loop.run_in_executor(None, _fetch_latest)
        if latest and latest != __version__:
            return latest
    except Exception:
        pass
    return None


def check_for_update_sync() -> tuple[str, str | None]:
    """Synchronous version check. Returns (current_version, latest_or_none)."""
    latest = _fetch_latest()
    if latest and latest != __version__:
        return __version__, latest
    return __version__, None
