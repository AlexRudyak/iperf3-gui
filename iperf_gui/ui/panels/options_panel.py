"""Protocol and stress options, gated by what the iperf3 binary supports."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.capabilities import IperfCapabilities
from ...core.config import (
    DEFAULT_INTERVAL_SECONDS,
    MAX_PARALLEL_STREAMS,
    ConfigError,
    IperfConfig,
    Protocol,
)

#: Options that exist only in some iperf3 builds, mapped to their UI label.
OPTIONAL_FEATURES = {
    "--bidir": "Bidirectional",
    "--sctp": "SCTP",
    "-Z": "Zero-Copy",
}


class OptionsPanel(QWidget):
    """Collects protocol, rate, stream count and the free-form extra arguments.

    Controls for features the detected ``iperf3`` build does not implement are
    disabled and annotated, rather than being offered and then failing at run
    time with a usage error.
    """

    def __init__(
        self,
        capabilities: IperfCapabilities | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._capabilities = capabilities
        self._build()
        self.apply_capabilities(capabilities)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("L3/L4 Stress & Transport Options")
        form = QFormLayout(group)

        self.protocol_combo = QComboBox()
        for protocol, label in (
            (Protocol.TCP, "TCP (default)"),
            (Protocol.UDP, "UDP (-u)"),
            (Protocol.SCTP, "SCTP (--sctp)"),
        ):
            self.protocol_combo.addItem(label, protocol)
        self.protocol_combo.currentIndexChanged.connect(self._sync_protocol)
        self.protocol_label = QLabel("Protocol:")
        form.addRow(self.protocol_label, self.protocol_combo)

        rate_row = QHBoxLayout()
        self.rate_input = QLineEdit()
        self.rate_input.setPlaceholderText("unlimited")
        self.rate_unit = QComboBox()
        self.rate_unit.addItems(["K", "M", "G"])
        self.rate_unit.setCurrentText("M")
        rate_row.addWidget(self.rate_input)
        rate_row.addWidget(self.rate_unit)
        form.addRow("Target Rate (-b):", rate_row)

        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, MAX_PARALLEL_STREAMS)
        self.parallel_spin.setValue(1)
        form.addRow("Parallel Streams (-P):", self.parallel_spin)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(0, 86400)
        self.duration_spin.setValue(10)
        self.duration_spin.setSpecialValueText("until stopped")
        self.duration_spin.setSuffix(" s")
        form.addRow("Duration (-t):", self.duration_spin)

        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 60.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setValue(DEFAULT_INTERVAL_SECONDS)
        self.interval_spin.setSuffix(" s")
        form.addRow("Report Interval (-i):", self.interval_spin)

        self.reverse_cb = QCheckBox("Reverse (-R)")
        self.bidir_cb = QCheckBox("Bidir (--bidir)")
        self.zerocopy_cb = QCheckBox("Zero-Copy (-Z)")
        # iperf3 rejects -R and --bidir together, so make them exclusive here
        # rather than letting the run fail.
        self.reverse_cb.toggled.connect(
            lambda on: on and self.bidir_cb.setChecked(False)
        )
        self.bidir_cb.toggled.connect(
            lambda on: on and self.reverse_cb.setChecked(False)
        )

        checks = QHBoxLayout()
        for box in (self.reverse_cb, self.bidir_cb, self.zerocopy_cb):
            checks.addWidget(box)
        form.addRow(checks)

        self.extra_input = QLineEdit()
        self.extra_input.setPlaceholderText('e.g. -N --cport 5000')
        form.addRow("Extra Args:", self.extra_input)

        layout.addWidget(group)
        self._sync_protocol()

    # ---------------------------------------------------------- capabilities

    def apply_capabilities(self, capabilities: IperfCapabilities | None) -> None:
        """Disable controls the detected binary cannot honour.

        Args:
            capabilities: probe result, or ``None`` to leave everything enabled
                (used when probing failed and we cannot know either way).
        """
        self._capabilities = capabilities
        if capabilities is None:
            return

        for flag, checkbox in (
            ("--bidir", self.bidir_cb),
            ("-Z", self.zerocopy_cb),
        ):
            supported = capabilities.supports(flag)
            checkbox.setEnabled(supported)
            if not supported:
                checkbox.setChecked(False)
                checkbox.setToolTip(
                    f"Not supported by iperf {capabilities.version_string}"
                )

        sctp_index = self.protocol_combo.findData(Protocol.SCTP)
        if sctp_index >= 0 and not capabilities.supports("--sctp"):
            item = self.protocol_combo.model().item(sctp_index)
            if item is not None:
                item.setEnabled(False)
            self.protocol_combo.setItemData(
                sctp_index,
                f"Not supported by iperf {capabilities.version_string}",
                Qt.ItemDataRole.ToolTipRole,
            )
            if self.protocol_combo.currentIndex() == sctp_index:
                self.protocol_combo.setCurrentIndex(0)

    def unsupported_notes(self) -> list[str]:
        """Human-readable notes about every unavailable optional feature."""
        if self._capabilities is None:
            return []
        return self._capabilities.describe_missing(OPTIONAL_FEATURES)

    def set_server_mode(self, is_server: bool) -> None:
        """Reflect that only a client chooses the transport.

        An iperf3 server accepts whichever transport the connecting client
        selects, and rejects ``-u``/``--sctp`` outright, so the control is
        disabled rather than silently ignored.
        """
        self.protocol_combo.setDisabled(is_server)
        self.protocol_label.setEnabled(not is_server)
        self.protocol_combo.setToolTip(
            "In server mode the transport is chosen by the connecting client."
            if is_server
            else ""
        )

    def _sync_protocol(self) -> None:
        """UDP needs an explicit target rate; without -b iperf3 defaults to 1 Mbit/s."""
        is_udp = self.protocol() is Protocol.UDP
        self.rate_input.setPlaceholderText(
            "recommended for UDP" if is_udp else "unlimited"
        )
        # Zero-copy is a TCP sendfile optimisation and is ignored for UDP.
        if self._capabilities is None or self._capabilities.supports("-Z"):
            self.zerocopy_cb.setEnabled(not is_udp)
            if is_udp:
                self.zerocopy_cb.setChecked(False)

    # ---------------------------------------------------------------- values

    def protocol(self) -> Protocol:
        """The selected transport protocol."""
        return self.protocol_combo.currentData()

    def bitrate(self) -> str | None:
        """Target rate with its unit suffix, or ``None`` for unlimited."""
        text = self.rate_input.text().strip()
        if not text:
            return None
        return f"{text}{self.rate_unit.currentText()}"

    def duration(self) -> int | None:
        """Test duration in seconds, or ``None`` to run until stopped."""
        value = self.duration_spin.value()
        return value or None

    def extra_args(self) -> tuple[str, ...]:
        """Parsed extra arguments.

        Raises:
            ConfigError: if the text contains an unbalanced quote.
        """
        return IperfConfig.parse_extra_args(self.extra_input.text())

    def apply_to(self, config: IperfConfig) -> IperfConfig:
        """Return ``config`` with this panel's selections applied.

        Raises:
            ConfigError: if the extra-arguments field cannot be parsed.
        """
        return config.with_overrides(
            protocol=self.protocol(),
            bitrate=self.bitrate(),
            parallel=self.parallel_spin.value(),
            duration=self.duration(),
            reverse=self.reverse_cb.isChecked(),
            bidir=self.bidir_cb.isChecked() and self.bidir_cb.isEnabled(),
            zerocopy=self.zerocopy_cb.isChecked() and self.zerocopy_cb.isEnabled(),
            interval=self.interval_spin.value(),
            extra_args=self.extra_args(),
        )


__all__ = ["OptionsPanel", "OPTIONAL_FEATURES", "ConfigError"]
