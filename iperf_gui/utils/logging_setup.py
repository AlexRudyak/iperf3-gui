"""Application-wide logging configuration.

A windowed PyInstaller build has no console, so anything written to stdout or
stderr is discarded -- which previously meant an unhandled exception left no
trace at all. Logging to a rotating file under the user's data directory makes
failures diagnosable after the fact.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from types import TracebackType

from .paths import user_data_dir

LOG_FILENAME = "iperf_gui.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def log_file_path() -> Path:
    """Absolute path of the rotating log file."""
    return user_data_dir() / LOG_FILENAME


def configure(level: int = logging.INFO, console: bool = True) -> Path | None:
    """Install file and console handlers on the root logger.

    Args:
        level: threshold for the root logger.
        console: also mirror records to stderr, useful when run from a terminal.

    Returns:
        The log file path, or ``None`` if the file handler could not be opened
        (a read-only or otherwise unwritable profile must not stop the app from
        starting).
    """
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(_FORMAT)
    path: Path | None = None

    try:
        path = log_file_path()
        file_handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        path = None

    if console and sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    if not root.handlers:
        root.addHandler(logging.NullHandler())

    return path


def install_exception_hook() -> None:
    """Route otherwise-unhandled exceptions into the log.

    Without this, an exception raised inside a Qt signal handler in a windowed
    build vanishes silently and the UI simply appears to do nothing.
    """
    previous = sys.excepthook

    def hook(
        exc_type: type[BaseException],
        value: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, value, traceback)
            return
        logging.getLogger("iperf_gui").critical(
            "Unhandled exception", exc_info=(exc_type, value, traceback)
        )
        previous(exc_type, value, traceback)

    sys.excepthook = hook
