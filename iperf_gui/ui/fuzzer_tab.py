"""Parameter sweep configuration, progress and live results."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.metrics import IterationResult
from ..core.sweep import (
    ExplicitSweep,
    ExponentialSweep,
    LinearSweep,
    SweepError,
    SweepStrategy,
)
from .widgets.results_table import ResultsTable

#: Sweepable iperf3 parameters, as (label, flag) pairs.
SWEEPABLE_PARAMETERS = (
    ("MSS / MTU (-M)", "-M"),
    ("Window Size (-w)", "-w"),
    ("Buffer Length (-l)", "-l"),
    ("Parallel Streams (-P)", "-P"),
)


class FuzzerTab(QWidget):
    """Configures and monitors a linear, exponential or explicit sweep."""

    start_requested = pyqtSignal(str, object, int, int)
    """Emitted with (parameter flag, strategy, duration, cooldown)."""

    stop_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        group = QGroupBox("Parameter Sweep")
        form = QFormLayout(group)

        self.param_combo = QComboBox()
        for label, flag in SWEEPABLE_PARAMETERS:
            self.param_combo.addItem(label, flag)
        form.addRow("Target Parameter:", self.param_combo)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Linear", "Exponential", "Explicit list"])
        self.mode_combo.currentIndexChanged.connect(self._sync_mode)
        form.addRow("Progression:", self.mode_combo)

        # Each progression needs different inputs; a stack keeps only the
        # relevant ones visible instead of greying out the rest.
        self._modes = QStackedWidget()
        self._modes.addWidget(self._build_linear_page())
        self._modes.addWidget(self._build_exponential_page())
        self._modes.addWidget(self._build_explicit_page())
        form.addRow(self._modes)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 3600)
        self.duration_spin.setValue(5)
        self.duration_spin.setSuffix(" s")
        form.addRow("Duration per iteration:", self.duration_spin)

        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(0, 3600)
        self.cooldown_spin.setValue(2)
        self.cooldown_spin.setSuffix(" s")
        form.addRow("Cooldown between tests:", self.cooldown_spin)

        layout.addWidget(group)

        self.start_btn = QPushButton("Start Sweep")
        self.start_btn.setObjectName("start_btn")
        self.start_btn.clicked.connect(self._emit_start)
        layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop Sweep")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested)
        layout.addWidget(self.stop_btn)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status_label = QLabel("Idle.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.results_table = ResultsTable()
        layout.addWidget(self.results_table, stretch=1)

        self._sync_mode()

    def _build_linear_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self.lin_start = _int_spin(500)
        self.lin_end = _int_spin(1500)
        self.lin_step = _int_spin(100, minimum=1)
        form.addRow("Start:", self.lin_start)
        form.addRow("End:", self.lin_end)
        form.addRow("Step:", self.lin_step)
        return page

    def _build_exponential_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self.exp_start = _int_spin(1024, minimum=1)
        self.exp_end = _int_spin(65536, minimum=1)
        self.exp_factor = QDoubleSpinBox()
        self.exp_factor.setRange(1.1, 10.0)
        self.exp_factor.setSingleStep(0.5)
        self.exp_factor.setValue(2.0)
        form.addRow("Start:", self.exp_start)
        form.addRow("End:", self.exp_end)
        form.addRow("Factor:", self.exp_factor)
        return page

    def _build_explicit_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self.explicit_input = QLineEdit("576, 1024, 1280, 1460")
        self.explicit_input.setPlaceholderText("comma or space separated integers")
        form.addRow("Values:", self.explicit_input)
        return page

    def _sync_mode(self) -> None:
        self._modes.setCurrentIndex(self.mode_combo.currentIndex())

    # -------------------------------------------------------------- strategy

    def strategy(self) -> SweepStrategy:
        """Build the strategy described by the current inputs.

        Raises:
            SweepError: if the inputs cannot produce a valid sequence.
        """
        index = self.mode_combo.currentIndex()
        if index == 0:
            return LinearSweep(
                self.lin_start.value(), self.lin_end.value(), self.lin_step.value()
            )
        if index == 1:
            return ExponentialSweep(
                self.exp_start.value(), self.exp_end.value(), self.exp_factor.value()
            )
        return ExplicitSweep.from_text(self.explicit_input.text())

    def parameter(self) -> str:
        """The iperf3 flag to sweep."""
        return self.param_combo.currentData()

    def _emit_start(self) -> None:
        try:
            strategy = self.strategy()
            strategy.values()
        except SweepError as exc:
            self.status_label.setText(f"Cannot start: {exc}")
            return
        self.start_requested.emit(
            self.parameter(),
            strategy,
            self.duration_spin.value(),
            self.cooldown_spin.value(),
        )

    # ------------------------------------------------------------- lifecycle

    def on_sweep_started(self, total: int) -> None:
        """Switch to the running state and reset progress."""
        self.results_table.clear_results()
        self.progress.setVisible(True)
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"Running 0/{total}...")

    def on_iteration_started(self, index: int, total: int, description: str) -> None:
        """Update the progress readout as each iteration begins."""
        self.progress.setValue(index - 1)
        self.status_label.setText(f"Running {index}/{total}: {description}")

    def on_iteration_finished(self, result: IterationResult) -> None:
        """Append a completed iteration to the table."""
        self.results_table.add_result(result)
        self.progress.setValue(self.progress.value() + 1)

    def on_sweep_finished(self) -> None:
        """Return to the idle state."""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        self.status_label.setText(
            f"Finished. {self.results_table.rowCount()} iteration(s) recorded."
        )

    def on_sweep_failed(self, reason: str) -> None:
        """Show why a sweep could not start or continue."""
        self.status_label.setText(f"Sweep failed: {reason}")

    def set_inputs_enabled(self, enabled: bool) -> None:
        """Lock the configuration inputs while a run is in progress."""
        for widget in (
            self.param_combo,
            self.mode_combo,
            self._modes,
            self.duration_spin,
            self.cooldown_spin,
        ):
            widget.setEnabled(enabled)


def _int_spin(value: int, minimum: int = 0, maximum: int = 1_000_000) -> QSpinBox:
    """Create a configured integer spin box."""
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin
