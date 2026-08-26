"""Shared pytest configuration.

Qt must be told to use the offscreen platform before any QApplication is
created, otherwise the GUI tests need a real display and fail in CI.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
