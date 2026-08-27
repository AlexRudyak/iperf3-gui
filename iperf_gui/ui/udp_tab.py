"""Traffic-generator tab: send UDP with no server on the far end."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.config import DEFAULT_PORT, MAX_PORT, MIN_PORT
from ..core.udp_sender import (
    DEFAULT_DATAGRAM_BYTES,
    MAX_DATAGRAM_BYTES,
    MIN_DATAGRAM_BYTES,
    UdpBlastConfig,
)

_RATE_MULTIPLIERS = {"K": 1e3, "M": 1e6, "G": 1e9}


class UdpBlastTab(QWidget):
    """Configures a connectionless UDP send.

    This path does not involve ``iperf3`` at all. iperf3 negotiates over a TCP
    control connection and reports figures supplied by the receiver, so it
    cannot send to a host that is not running it. A raw socket has no such
    constraint.
    """

    start_requested = pyqtSignal(object)
    """Emitted with a :class:`UdpBlastConfig` when the user starts a run."""

    stop_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        explanation = QLabel(
            "Sends UDP datagrams directly through a socket. No server is "
            "required and no handshake takes place, so this works against a "
            "closed port or a host that never replies.\n\n"
            "Only sent traffic is measured. Delivery, loss and jitter cannot "
            "be known without a cooperating receiver — use the Standard Test "
            "tab against an iperf3 server for those."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("explanation")
        layout.addWidget(explanation)

        group = QGroupBox("Destination")
        form = QFormLayout(group)

        self.host_input = QLineEdit("192.168.1.1")
        self.host_input.setPlaceholderText("hostname or IP address")
        form.addRow("Target IP/Host:", self.host_input)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(MIN_PORT, MAX_PORT)
        self.port_spin.setValue(DEFAULT_PORT)
        form.addRow("Port:", self.port_spin)

        layout.addWidget(group)

        traffic = QGroupBox("Traffic")
        traffic_form = QFormLayout(traffic)

        rate_row = QHBoxLayout()
        self.rate_input = QLineEdit("10")
        self.rate_input.setPlaceholderText("blank = as fast as possible")
        self.rate_unit = QComboBox()
        self.rate_unit.addItems(["K", "M", "G"])
        self.rate_unit.setCurrentText("M")
        rate_row.addWidget(self.rate_input)
        rate_row.addWidget(self.rate_unit)
        traffic_form.addRow("Target Rate:", rate_row)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(MIN_DATAGRAM_BYTES, MAX_DATAGRAM_BYTES)
        self.size_spin.setValue(DEFAULT_DATAGRAM_BYTES)
        self.size_spin.setSuffix(" bytes")
        self.size_spin.setToolTip(
            "1472 is the largest payload that avoids fragmentation on a "
            "standard 1500-byte MTU link."
        )
        traffic_form.addRow("Datagram Size:", self.size_spin)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(0, 86400)
        self.duration_spin.setValue(10)
        self.duration_spin.setSpecialValueText("until stopped")
        self.duration_spin.setSuffix(" s")
        traffic_form.addRow("Duration:", self.duration_spin)

        layout.addWidget(traffic)

        buttons = QHBoxLayout()
        self.start_btn = QPushButton("Start Sending")
        self.start_btn.setObjectName("start_btn")
        self.start_btn.clicked.connect(self._emit_start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested)
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.stop_btn)
        layout.addLayout(buttons)

        self.status_label = QLabel("Idle.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch()

    # ---------------------------------------------------------------- values

    def rate_bits_per_second(self) -> float | None:
        """Target offered load, or ``None`` for unlimited."""
        text = self.rate_input.text().strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        return value * _RATE_MULTIPLIERS[self.rate_unit.currentText()]

    def config(self) -> UdpBlastConfig:
        """Assemble a configuration from the current inputs."""
        return UdpBlastConfig(
            host=self.host_input.text(),
            port=self.port_spin.value(),
            bits_per_second=self.rate_bits_per_second(),
            datagram_bytes=self.size_spin.value(),
            duration=self.duration_spin.value() or None,
        )

    def _emit_start(self) -> None:
        text = self.rate_input.text().strip()
        if text and self.rate_bits_per_second() is None:
            self.status_label.setText(f"Cannot start: {text!r} is not a number.")
            return

        config = self.config()
        problems = config.validate()
        if problems:
            self.status_label.setText("Cannot start: " + " ".join(problems))
            return
        self.start_requested.emit(config)

    # ------------------------------------------------------------- lifecycle

    def on_started(self, config: UdpBlastConfig) -> None:
        """Switch to the running state."""
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"Sending {config.describe()}")

    def on_finished(self, exit_code: int) -> None:
        """Return to the idle state."""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Finished." if exit_code == 0 else "Stopped.")

    def set_inputs_enabled(self, enabled: bool) -> None:
        """Lock the configuration inputs while a run is in progress."""
        for widget in (
            self.host_input,
            self.port_spin,
            self.rate_input,
            self.rate_unit,
            self.size_spin,
            self.duration_spin,
        ):
            widget.setEnabled(enabled)
