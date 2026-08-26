"""Orchestration of a sequential parameter sweep.

Each iteration runs one ``iperf3`` test with a different value substituted for
the swept parameter, waits out a cooldown, and moves on. Results are aggregated
from the closing summary block when the run produced one, since ``iperf3``'s
own end-of-test figures are authoritative; the mean of the interval samples is
used only as a fallback.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..config import IperfConfig
from ..engine import EXIT_CODE_CANCELLED, IperfWorker
from ..metrics import IterationResult, Role, Sample
from .strategies import SweepError, SweepStrategy

logger = logging.getLogger(__name__)


class SweepEngine(QObject):
    """Runs a :class:`SweepStrategy` as a series of ``iperf3`` tests.

    The engine guarantees that every started sweep ends with exactly one of
    :attr:`sweep_finished` or :attr:`sweep_failed`. The previous implementation
    could return from its start method without emitting anything, which left
    the UI's controls disabled with no way to recover; callers here can safely
    drive their entire enabled/disabled state from these signals.
    """

    sweep_started = pyqtSignal(int)
    """Emitted with the total number of iterations when a sweep begins."""

    sweep_failed = pyqtSignal(str)
    """Emitted with a reason when a sweep cannot start or cannot continue."""

    sweep_finished = pyqtSignal()
    """Emitted exactly once when a sweep ends, whether or not it completed."""

    iteration_started = pyqtSignal(int, int, str)
    """Emitted with (index, total, description) as each iteration begins."""

    iteration_finished = pyqtSignal(object)
    """Emitted with an :class:`IterationResult` as each iteration ends."""

    line_received = pyqtSignal(str)
    sample_ready = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._running = False
        self._base_config = IperfConfig()
        self._parameter = ""
        self._values: list[int] = []
        self._index = 0
        self._cooldown = 0
        self._duration = 5
        self._worker: IperfWorker | None = None
        self._results: list[IterationResult] = []
        self._samples: list[Sample] = []
        self._summaries: list[Sample] = []
        self._cooldown_timer = QTimer(self)
        self._cooldown_timer.setSingleShot(True)
        self._cooldown_timer.timeout.connect(self._run_next_iteration)

    # ------------------------------------------------------------- accessors

    @property
    def is_running(self) -> bool:
        """Whether a sweep is currently in progress."""
        return self._running

    @property
    def results(self) -> list[IterationResult]:
        """Results accumulated so far, oldest first."""
        return list(self._results)

    # --------------------------------------------------------------- control

    def start(
        self,
        base_config: IperfConfig,
        parameter: str,
        strategy: SweepStrategy,
        duration: int,
        cooldown: int,
    ) -> bool:
        """Begin a sweep.

        Args:
            base_config: the configuration every iteration starts from.
            parameter: the ``iperf3`` flag to sweep, e.g. ``"-M"``.
            strategy: supplies the values to substitute for ``parameter``.
            duration: seconds to run each iteration for.
            cooldown: seconds to idle between iterations.

        Returns:
            ``True`` if the sweep started. When it returns ``False``,
            :attr:`sweep_failed` has already been emitted with the reason.
        """
        if self._running:
            self.sweep_failed.emit("A sweep is already running.")
            return False

        try:
            values = strategy.values()
        except SweepError as exc:
            self.sweep_failed.emit(str(exc))
            return False

        problems = base_config.validate()
        if problems:
            self.sweep_failed.emit(" ".join(problems))
            return False

        self._base_config = base_config
        self._parameter = parameter
        self._values = values
        self._duration = duration
        self._cooldown = max(0, cooldown)
        self._index = 0
        self._results = []
        self._running = True

        self.sweep_started.emit(len(values))
        self.line_received.emit(
            f"Starting {strategy.describe()} sweep of {parameter} "
            f"({len(values)} iterations, {duration}s each)."
        )
        self._run_next_iteration()
        return True

    def stop(self) -> None:
        """Cancel the sweep and stop any in-flight test."""
        if not self._running:
            return
        self._running = False
        self._cooldown_timer.stop()
        if self._worker is not None:
            self._worker.stop_and_wait()
        self.line_received.emit("Sweep cancelled.")
        self._finish()

    def shutdown(self) -> None:
        """Tear everything down without emitting further signals.

        Used on application exit, where the UI is already gone.
        """
        self._running = False
        self._cooldown_timer.stop()
        if self._worker is not None:
            self._worker.stop_and_wait()
            self._worker = None

    # -------------------------------------------------------------- internals

    def _run_next_iteration(self) -> None:
        if not self._running:
            return
        if self._index >= len(self._values):
            self._finish()
            return

        value = self._values[self._index]
        label = f"{self._parameter} {value}"
        self.line_received.emit(
            f"--- Iteration {self._index + 1}/{len(self._values)}: {label} ---"
        )
        self.iteration_started.emit(self._index + 1, len(self._values), label)

        self._samples = []
        self._summaries = []

        config = self._base_config.with_overrides(
            duration=self._duration,
            extra_args=self._base_config.extra_args + (self._parameter, str(value)),
        )

        worker = IperfWorker(config, parent=self)
        worker.line_received.connect(self.line_received)
        worker.sample_ready.connect(self._on_sample)
        worker.summary_ready.connect(self._summaries.append)
        worker.run_finished.connect(self._on_iteration_finished)
        # Let Qt reclaim each worker once its thread has genuinely ended,
        # rather than relying on the next assignment dropping the reference
        # while the OS thread may still be alive.
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_sample(self, sample: Sample) -> None:
        self._samples.append(sample)
        self.sample_ready.emit(sample)

    def _on_iteration_finished(self, exit_code: int) -> None:
        if not self._running:
            return

        result = self._aggregate(self._values[self._index], exit_code)
        self._results.append(result)
        self.iteration_finished.emit(result)

        self._worker = None
        self._index += 1

        if self._index >= len(self._values):
            self._finish()
            return

        if exit_code == EXIT_CODE_CANCELLED:
            self.line_received.emit("Iteration cancelled; ending sweep.")
            self._finish()
            return

        if self._cooldown:
            self.line_received.emit(f"Cooling down for {self._cooldown}s...")
            self._cooldown_timer.start(self._cooldown * 1000)
        else:
            self._run_next_iteration()

    def _aggregate(self, value: int, exit_code: int) -> IterationResult:
        """Reduce one iteration's samples into a single result row."""
        rates = [s.megabits_per_second for s in self._samples]

        sender = _summary_rate(self._summaries, Role.SENDER)
        receiver = _summary_rate(self._summaries, Role.RECEIVER)

        # iperf3's own end-of-test average is more accurate than the mean of
        # the interval reports, which are unevenly weighted at the tail.
        avg = sender if sender is not None else (sum(rates) / len(rates) if rates else 0.0)

        retransmits = _sum_optional(s.retransmits for s in self._samples)
        lost = _sum_optional(s.lost_packets for s in self._samples)
        losses = [s.loss_percent for s in self._samples if s.loss_percent is not None]

        return IterationResult(
            parameter=self._parameter,
            value=value,
            avg_mbps=avg,
            peak_mbps=max(rates) if rates else 0.0,
            sender_mbps=sender,
            receiver_mbps=receiver,
            retransmits=retransmits,
            lost_packets=lost,
            loss_percent=(sum(losses) / len(losses)) if losses else None,
            sample_count=len(self._samples),
            exit_code=exit_code,
        )

    def _finish(self) -> None:
        self._running = False
        self._worker = None
        self.line_received.emit(
            f"Sweep finished: {len(self._results)}/{len(self._values)} iterations completed."
        )
        self.sweep_finished.emit()


def _summary_rate(summaries: list[Sample], role: Role) -> float | None:
    """Throughput reported by the summary row for ``role``, if present."""
    for sample in summaries:
        if sample.role is role:
            return sample.megabits_per_second
    return None


def _sum_optional(values) -> int | None:
    """Sum values, returning ``None`` when every value is ``None``.

    Distinguishes "the build reports no such column" from "the column read
    zero", which a plain ``sum`` would conflate.
    """
    present = [v for v in values if v is not None]
    return sum(present) if present else None
