"""A log console that cannot grow without bound."""

from __future__ import annotations

from PyQt6.QtWidgets import QPlainTextEdit, QWidget

#: Lines retained before the oldest are discarded. A long run with many
#: parallel streams can emit hundreds of thousands of lines; the previous
#: unbounded QTextEdit grew its document until the process ran out of memory.
DEFAULT_MAX_LINES = 5000


class LogConsole(QPlainTextEdit):
    """Read-only, append-only text view with a fixed retention limit.

    :class:`QPlainTextEdit` is used in preference to :class:`QTextEdit` because
    it is optimised for exactly this append-heavy, plain-text workload and
    provides ``maximumBlockCount`` for automatic trimming.
    """

    def __init__(
        self,
        max_lines: int = DEFAULT_MAX_LINES,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(max_lines)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def append_line(self, text: str) -> None:
        """Append one line, scrolling to follow it."""
        self.appendPlainText(text)

    def clear_log(self) -> None:
        """Remove all retained output."""
        self.clear()
