"""Dialogs for exporting sweep results."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..core.metrics import RESULT_COLUMNS


class ExportDialog(QDialog):
    """Lets the user choose which columns a CSV export should contain.

    The checkbox list is generated from :data:`RESULT_COLUMNS` rather than a
    second hard-coded list. Previously the dialog and the result rows each had
    their own copy of the column names, so renaming a column in one place made
    the export silently drop it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Results to CSV")
        self.setMinimumWidth(320)
        self._checkboxes: dict[str, QCheckBox] = {}
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select the columns to include:"))

        for name in RESULT_COLUMNS:
            box = QCheckBox(name)
            box.setChecked(True)
            box.toggled.connect(self._sync_ok_state)
            layout.addWidget(box)
            self._checkboxes[name] = box

        layout.addStretch()

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("Export")
            ok_button.setObjectName("start_btn")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _sync_ok_state(self) -> None:
        """Disable Export when nothing is selected, rather than failing later."""
        ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setEnabled(bool(self.selected_columns()))

    def selected_columns(self) -> list[str]:
        """Checked column names, in their canonical order."""
        return [name for name in RESULT_COLUMNS if self._checkboxes[name].isChecked()]
