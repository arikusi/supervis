"""Logging configuration for supervis.

Sets up file-based logging (always) and optional stderr debug output.
Log file: ~/.local/share/supervis/supervis.log (2MB rotating, 3 backups).
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path.home() / ".local" / "share" / "supervis"
_LOG_FILE = _LOG_DIR / "supervis.log"
_MAX_BYTES = 2 * 1024 * 1024  # 2MB
_BACKUP_COUNT = 3
_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"


def setup_logging(debug: bool = False) -> None:
    """Configure logging for the supervis process.

    Always writes DEBUG+ to the log file.
    If debug=True, also writes DEBUG+ to stderr.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("supervisor")
    root.setLevel(logging.DEBUG)

    # File handler (always active)
    fh = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(fh)

    # Console handler (only with --debug)
    if debug:
        sh = logging.StreamHandler()
        sh.setLevel(logging.DEBUG)
        sh.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(sh)
