"""Application shell: assembles the panels and wires them to the core engines.

This class deliberately owns no domain logic. Building the argument vector
lives in :mod:`iperf_gui.core.config`, writing CSV lives in
:mod:`iperf_gui.core.export`, and running tests lives in
:mod:`iperf_gui.core.engine`; what remains here is composition and the
translation of engine signals into widget state.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent, QIcon
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.capabilities import CapabilityProbeError, IperfCapabilities, cached_probe
from ..core.config import ConfigError, IperfConfig, Protocol, Role
from ..core.engine import EXIT_CODE_CANCELLED, IperfWorker
from ..core.export import ExportError, write_results_csv
from ..core.metrics import IterationResult, Sample
from ..core.sweep import SweepEngine, SweepStrategy
from ..core.udp_sender import UdpBlastConfig, UdpBlastWorker
from ..utils.paths import resource_path
from .dashboard import TelemetryDashboard
from .dialogs import ExportDialog
from .fuzzer_tab import FuzzerTab
from .panels.connection_panel import ConnectionPanel
from .panels.options_panel import OptionsPanel
from .udp_tab import UdpBlastTab
from .widgets.console import LogConsole

logger = logging.getLogger(__name__)

#: Milliseconds to wait for a worker to stop when the window is closing.
SHUTDOWN_TIMEOUT_MS = 5000

#: Shown once at startup. GPL-3.0 section 5(d) expects an interactive work to
#: carry appropriate legal notices.
_LICENCE_NOTICE = (
    f"iperf3 Advanced GUI & Sweeper {__version__} - "
    "Copyright (C) 2026 Sasha Rudyak. "
    "This program comes with ABSOLUTELY NO WARRANTY. It is free software, and "
    "you are welcome to redistribute it under the terms of the GNU GPL v3 or "
    "later; see the LICENSE file for details."
)


class MainWindow(QMainWindow):
    """The application's only top-level window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("iperf3 Advanced GUI & Sweeper")
        self.resize(1200, 800)

        icon = resource_path("app_icon.ico")
        if icon.is_file():
            self.setWindowIcon(QIcon(str(icon)))

        self._capabilities = self._detect_capabilities()
        self._worker: IperfWorker | None = None
        self._udp_worker: UdpBlastWorker | None = None
        self._sweep = SweepEngine(self)

        self._build()
        self._connect_sweep()
        self._report_environment()

    # ----------------------------------------------------------- composition

    def _detect_capabilities(self) -> IperfCapabilities | None:
        """Probe the bundled binary, tolerating a failure to find it."""
        try:
            return cached_probe()
        except CapabilityProbeError as exc:
            logger.error("iperf3 capability probe failed: %s", exc)
            return None

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 780])
        root.addWidget(splitter)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(400)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()

        standard = QWidget()
        standard_layout = QVBoxLayout(standard)

        self.connection_panel = ConnectionPanel()
        self.options_panel = OptionsPanel(self._capabilities)
        self.connection_panel.role_changed.connect(self._on_role_changed)
        self._on_role_changed(self.connection_panel.role())
        standard_layout.addWidget(self.connection_panel)
        standard_layout.addWidget(self.options_panel)

        buttons = QHBoxLayout()
        self.start_btn = QPushButton("Start Test")
        self.start_btn.setObjectName("start_btn")
        self.start_btn.clicked.connect(self.start_test)

        self.stop_btn = QPushButton("Stop / Kill")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_test)

        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.stop_btn)
        standard_layout.addLayout(buttons)
        standard_layout.addStretch()

        self.tabs.addTab(standard, "Standard Test")

        self.fuzzer_tab = FuzzerTab()
        self.fuzzer_tab.start_requested.connect(self.start_sweep)
        self.fuzzer_tab.stop_requested.connect(self._sweep.stop)
        self.tabs.addTab(self.fuzzer_tab, "Sweep")

        self.udp_tab = UdpBlastTab()
        self.udp_tab.start_requested.connect(self.start_udp_blast)
        self.udp_tab.stop_requested.connect(self.stop_test)
        self.tabs.addTab(self.udp_tab, "UDP Send")

        layout.addWidget(self.tabs)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.dashboard = TelemetryDashboard()
        splitter.addWidget(self.dashboard)

        console_container = QWidget()
        console_layout = QVBoxLayout(console_container)
        console_layout.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        clear_btn = QPushButton("Clear Graphs")
        clear_btn.clicked.connect(self._clear_output)
        self.export_btn = QPushButton("Export Sweep Results (CSV)")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_results)
        controls.addWidget(clear_btn)
        controls.addWidget(self.export_btn)
        controls.addStretch()
        console_layout.addLayout(controls)

        self.console = LogConsole()
        console_layout.addWidget(self.console)
        splitter.addWidget(console_container)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)
        return panel

    def _connect_sweep(self) -> None:
        self._sweep.line_received.connect(self.console.append_line)
        self._sweep.sample_ready.connect(self.dashboard.add_sample)
        self._sweep.sweep_started.connect(self._on_sweep_started)
        self._sweep.sweep_started.connect(self.fuzzer_tab.on_sweep_started)
        self._sweep.iteration_started.connect(self._on_iteration_started)
        self._sweep.iteration_started.connect(self.fuzzer_tab.on_iteration_started)
        self._sweep.iteration_finished.connect(self._on_iteration_finished)
        self._sweep.sweep_finished.connect(self._on_sweep_finished)
        self._sweep.sweep_failed.connect(self.fuzzer_tab.on_sweep_failed)
        self._sweep.sweep_failed.connect(self._on_sweep_failed)

    def _on_role_changed(self, role: Role) -> None:
        """Disable transport selection in server mode, where it has no effect."""
        self.options_panel.set_server_mode(role is Role.SERVER)

    def _report_environment(self) -> None:
        """Log what was detected, so the console explains any disabled controls."""
        if self._capabilities is None:
            self.console.append_line(_LICENCE_NOTICE)
            self.console.append_line(
                "WARNING: iperf3 could not be found or run. Tests will fail until "
                "it is available."
            )
            return

        self.console.append_line(_LICENCE_NOTICE)
        self.console.append_line(f"Detected {self._capabilities.version_banner}")
        for note in self.options_panel.unsupported_notes():
            self.console.append_line(f"NOTE: {note}; the control has been disabled.")

    # -------------------------------------------------------- configuration

    def current_config(self) -> IperfConfig | None:
        """Assemble a config from the panels, reporting problems to the user.

        Returns:
            The configuration, or ``None`` if it was rejected (in which case
            the user has already been shown why).
        """
        try:
            config = self.options_panel.apply_to(
                IperfConfig(
                    role=self.connection_panel.role(),
                    host=self.connection_panel.host(),
                    port=self.connection_panel.port(),
                )
            )
        except ConfigError as exc:
            QMessageBox.warning(self, "Invalid Options", str(exc))
            return None

        problems = config.validate()
        if problems:
            QMessageBox.warning(self, "Invalid Configuration", "\n".join(problems))
            return None

        for flag in config.suppressed_client_flags():
            self.console.append_line(f"NOTE: {flag} is ignored in server mode.")

        return config

    # ------------------------------------------------------------ single run

    def start_test(self) -> None:
        """Launch a one-off test using the current panel settings."""
        if self._worker is not None and self._worker.isRunning():
            return

        config = self.current_config()
        if config is None:
            return

        self._clear_output()
        self._note_control_channel(config)

        worker = IperfWorker(config, parent=self)
        worker.line_received.connect(self.console.append_line)
        worker.sample_ready.connect(self.dashboard.add_sample)
        worker.summary_ready.connect(self._on_summary)
        worker.run_failed.connect(self._on_run_failed)
        worker.run_finished.connect(self._on_run_finished)
        # Qt reclaims the worker once its thread has genuinely ended. Relying
        # on the next assignment to drop the reference risked collecting a
        # QThread whose OS thread was still alive.
        worker.finished.connect(worker.deleteLater)
        self._worker = worker

        self._set_running(True)
        worker.start()

    def _note_control_channel(self, config: IperfConfig) -> None:
        """Warn that a non-TCP test still opens a TCP control connection.

        iperf3 negotiates every test over TCP on the server port and carries
        only the payload over the selected transport. A packet capture filtered
        on that port therefore shows TCP even for a UDP run, which reads as the
        protocol setting having been ignored.
        """
        if config.protocol is Protocol.TCP:
            return
        self.console.append_line(
            f"NOTE: iperf3 always opens a TCP control connection on port "
            f"{config.port}; only the {config.protocol.label.upper()} payload uses "
            f"the selected transport. In Wireshark, filter on "
            f"'{config.protocol.label}.port == {config.port}' to see the test data."
        )

    def start_udp_blast(self, config: UdpBlastConfig) -> None:
        """Send UDP straight through a socket, with no iperf3 involved.

        iperf3 cannot do this: it negotiates over a TCP control connection and
        reports figures supplied by the receiver, so it refuses to run when
        nothing is listening. A raw socket has no such requirement.
        """
        if self._udp_worker is not None and self._udp_worker.isRunning():
            return

        self._clear_output()

        worker = UdpBlastWorker(config, parent=self)
        worker.line_received.connect(self.console.append_line)
        worker.sample_ready.connect(self.dashboard.add_sample)
        worker.summary_ready.connect(self._on_summary)
        worker.run_failed.connect(self._on_run_failed)
        worker.run_finished.connect(self._on_udp_finished)
        worker.finished.connect(worker.deleteLater)
        self._udp_worker = worker

        self.udp_tab.on_started(config)
        self._set_running(True)
        worker.start()

    def _on_udp_finished(self, exit_code: int) -> None:
        self._udp_worker = None
        self._set_running(False)
        self.udp_tab.on_finished(exit_code)
        self.console.append_line(
            "Sending stopped." if exit_code else "Sending complete."
        )

    def stop_test(self) -> None:
        """Stop whichever engine is currently running."""
        if self._sweep.is_running:
            self._sweep.stop()
        if self._worker is not None:
            self._worker.stop()
        if self._udp_worker is not None:
            self._udp_worker.stop()

    def _on_summary(self, sample: Sample) -> None:
        role = sample.role.value if sample.role else "total"
        self.console.append_line(
            f"Summary ({role}): {sample.megabits_per_second:.2f} Mbit/s "
            f"over {sample.interval_end:.2f}s"
        )

    def _on_run_failed(self, reason: str) -> None:
        for line in reason.splitlines():
            if line.strip():
                self.console.append_line(f"FAILED: {line.strip()}")
        QMessageBox.critical(self, "Test Failed", reason)

    def _on_run_finished(self, exit_code: int) -> None:
        self._worker = None
        self._set_running(False)
        if exit_code == EXIT_CODE_CANCELLED:
            self.console.append_line("Test stopped.")
        elif exit_code == 0:
            self.console.append_line("Test completed successfully.")
        else:
            # The reason and any hint were already reported via run_failed.
            self.console.append_line(f"Test failed (exit code {exit_code}).")

    # ----------------------------------------------------------------- sweep

    def start_sweep(
        self, parameter: str, strategy: SweepStrategy, duration: int, cooldown: int
    ) -> None:
        """Begin a parameter sweep from the current panel settings."""
        config = self.current_config()
        if config is None:
            return

        self._clear_output()
        # The engine emits sweep_started or sweep_failed, and the UI state is
        # driven entirely from those signals. The previous implementation
        # disabled controls optimistically before knowing whether the sweep had
        # started, which left them stuck when validation rejected it.
        self._sweep.start(config, parameter, strategy, duration, cooldown)

    def _on_sweep_started(self, total: int) -> None:
        self._set_running(True)

    def _on_iteration_started(self, index: int, total: int, description: str) -> None:
        """Clear the plots for the iteration that is about to run.

        Each iteration is an independent test with its own time axis, so the
        traces must not accumulate. Clearing here rather than after the run
        leaves the final iteration's trace on screen once the sweep ends,
        instead of wiping it the moment there is something to look at.
        """
        self.dashboard.reset()

    def _on_iteration_finished(self, result: IterationResult) -> None:
        self.fuzzer_tab.on_iteration_finished(result)
        self.export_btn.setEnabled(True)

    def _on_sweep_finished(self) -> None:
        self._set_running(False)
        self.fuzzer_tab.on_sweep_finished()
        if self._sweep.results:
            self.export_btn.setEnabled(True)

    def _on_sweep_failed(self, reason: str) -> None:
        self._set_running(False)
        QMessageBox.warning(self, "Sweep Problem", reason)

    # ------------------------------------------------------------------ misc

    def _set_running(self, running: bool) -> None:
        """Single point of truth for which controls are usable."""
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.connection_panel.setEnabled(not running)
        self.options_panel.setEnabled(not running)
        self.fuzzer_tab.set_inputs_enabled(not running)
        self.udp_tab.set_inputs_enabled(not running)
        if self._udp_worker is None:
            self.udp_tab.start_btn.setEnabled(not running)
            self.udp_tab.stop_btn.setEnabled(running)
        if not self._sweep.is_running:
            self.fuzzer_tab.start_btn.setEnabled(not running)
            self.fuzzer_tab.stop_btn.setEnabled(running)

    def _clear_output(self) -> None:
        self.console.clear_log()
        self.dashboard.reset()

    def export_results(self) -> None:
        """Write the accumulated sweep results to a CSV file."""
        results = self._sweep.results
        if not results:
            QMessageBox.information(self, "Nothing to Export", "No sweep results yet.")
            return

        dialog = ExportDialog(self)
        if not dialog.exec():
            return

        columns = dialog.selected_columns()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV", "sweep_results.csv", "CSV Files (*.csv)"
        )
        if not path:
            return

        try:
            written = write_results_csv(path, results, columns)
        except ExportError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            return

        QMessageBox.information(
            self, "Export Complete", f"Wrote {written} row(s) to {path}."
        )

    # ------------------------------------------------------------- shutdown

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: D102 - Qt override
        """Stop background work before the window is destroyed.

        Without this, closing the window mid-test destroyed a running QThread,
        which aborts the process, and left the iperf3 child running.
        """
        logger.info("Shutting down; stopping any active run")
        self._sweep.shutdown()

        for worker in (self._worker, self._udp_worker):
            if worker is not None and worker.isRunning():
                if not worker.stop_and_wait(SHUTDOWN_TIMEOUT_MS):
                    logger.warning("%s did not stop cleanly", type(worker).__name__)
        self._worker = None
        self._udp_worker = None

        super().closeEvent(event)
