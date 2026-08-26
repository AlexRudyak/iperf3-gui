"""Application entry point.

iperf3 Advanced GUI & Sweeper
Copyright (C) 2026 Sasha Rudyak

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication

from iperf_gui import __version__
from iperf_gui.ui.main_window import MainWindow
from iperf_gui.utils.logging_setup import configure, install_exception_hook
from iperf_gui.utils.paths import resource_path

logger = logging.getLogger(__name__)


def load_stylesheet(app: QApplication) -> None:
    """Apply the bundled dark theme, if it is present.

    A missing stylesheet is a cosmetic problem, not a fatal one, so it is
    logged rather than raised.
    """
    path = resource_path("style.qss")
    try:
        app.setStyleSheet(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("Could not load stylesheet from %s: %s", path, exc)


def main(argv: list[str] | None = None) -> int:
    """Start the GUI and run until the user closes it.

    Returns:
        The Qt exit code.
    """
    log_path = configure()
    install_exception_hook()
    logger.info("Starting iperf_gui %s (logging to %s)", __version__, log_path)

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("iperf_gui")
    app.setApplicationVersion(__version__)

    load_stylesheet(app)

    window = MainWindow()
    window.show()

    try:
        return app.exec()
    finally:
        # Destroy the window while the QApplication is still alive. Leaving it
        # to interpreter teardown lets Python free the two in an arbitrary
        # order, which can crash Qt on the way out.
        window.close()
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    sys.exit(main())
