"""Live table of sweep iteration results.

This gives the previously unused ``iteration_finished`` signal somewhere to go:
results now appear as each iteration completes, instead of the user waiting
through a multi-minute sweep with no feedback but a message box at the end.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ...core.metrics import RESULT_COLUMNS, IterationResult


class ResultsTable(QTableWidget):
    """Read-only grid of completed sweep iterations.

    Columns are driven by :data:`RESULT_COLUMNS` so they cannot drift out of
    step with the CSV export or the result rows themselves.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(RESULT_COLUMNS), parent)
        self.setHorizontalHeaderLabels(list(RESULT_COLUMNS))
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

    def add_result(self, result: IterationResult) -> None:
        """Append one iteration's result as a new row."""
        row_data = result.as_row()
        row = self.rowCount()
        self.insertRow(row)
        for column, name in enumerate(RESULT_COLUMNS):
            value = row_data.get(name)
            text = "-" if value is None else str(value)
            self.setItem(row, column, QTableWidgetItem(text))
        self.scrollToBottom()

    def clear_results(self) -> None:
        """Remove every row, keeping the headers."""
        self.setRowCount(0)
