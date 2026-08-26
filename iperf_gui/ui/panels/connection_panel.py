"""Connection settings: target host, port and client/server role."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.config import DEFAULT_PORT, MAX_PORT, MIN_PORT, Role


class ConnectionPanel(QWidget):
    """Collects the host, port and role for a test run.

    Numeric entry uses :class:`QSpinBox` rather than a validated
    :class:`QLineEdit`: a validator permits an empty field as a valid
    intermediate state, so reading it back with ``int()`` could raise, whereas
    a spin box always holds a usable integer.
    """

    role_changed = pyqtSignal(object)
    """Emitted with the new :class:`Role` when the client/server mode changes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()
        self._sync_role()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Connection Parameters")
        form = QFormLayout(group)

        self.role_combo = QComboBox()
        self.role_combo.addItem("Client (-c)", Role.CLIENT)
        self.role_combo.addItem("Server (-s)", Role.SERVER)
        self.role_combo.currentIndexChanged.connect(self._sync_role)
        form.addRow("Mode:", self.role_combo)

        self.host_input = QLineEdit("127.0.0.1")
        self.host_input.setPlaceholderText("hostname or IP address")
        self.host_label = QLabel("Target IP/Host:")
        form.addRow(self.host_label, self.host_input)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(MIN_PORT, MAX_PORT)
        self.port_spin.setValue(DEFAULT_PORT)
        form.addRow("Port (-p):", self.port_spin)

        layout.addWidget(group)

    def _sync_role(self) -> None:
        """Grey out the host field in server mode, where it has no meaning."""
        is_client = self.role() is Role.CLIENT
        self.host_input.setEnabled(is_client)
        self.host_label.setEnabled(is_client)
        self.role_changed.emit(self.role())

    # ---------------------------------------------------------------- values

    def role(self) -> Role:
        """The selected client/server role."""
        return self.role_combo.currentData()

    def host(self) -> str:
        """The target host, stripped of surrounding whitespace."""
        return self.host_input.text().strip()

    def port(self) -> int:
        """The selected port."""
        return self.port_spin.value()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the whole panel while a test is running."""
        self.setEnabled(enabled)
