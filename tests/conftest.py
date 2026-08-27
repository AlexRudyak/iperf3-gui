"""Shared pytest configuration.

Qt must be told to use the offscreen platform before any QApplication is
created, otherwise the GUI tests need a real display and fail in CI.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication shared by every test that needs one.

    Qt allows only one instance per process, so this is session-scoped and
    reuses any instance an earlier import may already have created.
    """
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
