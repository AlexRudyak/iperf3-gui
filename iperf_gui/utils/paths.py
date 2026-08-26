"""Resolution of bundled resources in both source checkouts and frozen builds.

The previous implementation resolved resources against the *current working
directory*, which meant assets loaded only when the app happened to be launched
from the project root, and never at all from a source checkout (where assets
live under ``iperf_gui/assets`` rather than ``./assets``).

Paths here are anchored to the package directory instead, so behaviour no
longer depends on where the process was started from.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

#: Directory containing the ``iperf_gui`` package in a source checkout.
_PACKAGE_DIR = Path(__file__).resolve().parent.parent

#: Name of the bundled iperf3 binary, by platform.
_IPERF_BINARY = "iperf3.exe" if sys.platform == "win32" else "iperf3"


def is_frozen() -> bool:
    """Whether the app is running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_root() -> Path:
    """Root directory that bundled data files are unpacked into.

    Under PyInstaller this is the temporary ``_MEIPASS`` extraction directory;
    from source it is the package directory.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return _PACKAGE_DIR


def project_root() -> Path:
    """Directory that holds the bundled executables next to the application.

    Frozen builds unpack ``iperf3.exe`` into the bundle root; a source checkout
    keeps it in the repository root, one level above the package.
    """
    if is_frozen():
        return bundle_root()
    return _PACKAGE_DIR.parent


def resource_path(*parts: str) -> Path:
    """Absolute path to a bundled data file such as an icon or stylesheet.

    Args:
        *parts: path components relative to the assets root, e.g. ``"style.qss"``.
    """
    return bundle_root() / "assets" / Path(*parts)


def iperf3_executable() -> str:
    """Absolute path to the ``iperf3`` binary shipped alongside the app.

    Falls back to the bare binary name so that a copy on ``PATH`` is still
    usable when no bundled binary is present.
    """
    candidate = project_root() / _IPERF_BINARY
    if candidate.is_file():
        return str(candidate)

    bundled = bundle_root() / _IPERF_BINARY
    if bundled.is_file():
        return str(bundled)

    logger.warning(
        "No bundled %s found under %s; falling back to PATH lookup",
        _IPERF_BINARY,
        project_root(),
    )
    return _IPERF_BINARY


def user_data_dir() -> Path:
    """Per-user directory for logs and settings, created on first use."""
    if sys.platform == "win32":
        import os

        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"

    directory = base / "iperf_gui"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
