"""Live plots of throughput and link reliability.

Two behaviours here differ deliberately from the original implementation:

**The X axis comes from the data.** Timestamps are taken from the interval each
sample reports, not synthesised by adding a hard-coded 0.5 s per sample. The
old approach silently produced a wrong time axis whenever the report interval
was anything other than 0.5 s.

**Repainting is throttled.** Samples are buffered and the curves redrawn on a
timer, rather than redrawing all three plots on every parsed line. With many
parallel streams the per-line approach spent most of its time in Qt's paint
path.
"""

from __future__ import annotations

from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ..core.metrics import Direction, Sample

#: Samples retained per series before the oldest are dropped.
DEFAULT_HISTORY = 600

#: Redraw cadence. 20 Hz is smooth to the eye and bounds the paint cost
#: independently of how fast iperf3 produces output.
REPAINT_INTERVAL_MS = 50

_TX_COLOUR = "#00d2ff"
_RX_COLOUR = "#00ff88"
_RETR_COLOUR = "#d13438"
_LOSS_COLOUR = "#ffb900"


class _Series:
    """A pair of bounded x/y buffers backing one plot curve."""

    def __init__(self, maxlen: int) -> None:
        self.x: deque[float] = deque(maxlen=maxlen)
        self.y: deque[float] = deque(maxlen=maxlen)

    def append(self, x: float, y: float) -> None:
        self.x.append(x)
        self.y.append(y)

    def clear(self) -> None:
        self.x.clear()
        self.y.clear()

    def as_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        return np.fromiter(self.x, dtype=float), np.fromiter(self.y, dtype=float)


class TelemetryDashboard(QWidget):
    """Three stacked plots: outbound rate, inbound rate, and reliability."""

    def __init__(self, history: int = DEFAULT_HISTORY, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._history = history
        self._tx = _Series(history)
        self._rx = _Series(history)
        self._retransmits = _Series(history)
        self._loss = _Series(history)
        self._dirty = False

        self._build()

        self._repaint_timer = QTimer(self)
        self._repaint_timer.timeout.connect(self._repaint_if_dirty)
        self._repaint_timer.start(REPAINT_INTERVAL_MS)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        pg.setConfigOption("background", "#1e1e1e")
        pg.setConfigOption("foreground", "#cccccc")
        pg.setConfigOptions(antialias=True)

        self._tx_plot = self._make_plot("Throughput (Outbound / TX)", "Mbit/s")
        self._tx_curve = self._tx_plot.plot(pen=pg.mkPen(_TX_COLOUR, width=2), name="TX")

        self._rx_plot = self._make_plot("Throughput (Inbound / RX)", "Mbit/s")
        self._rx_curve = self._rx_plot.plot(pen=pg.mkPen(_RX_COLOUR, width=2), name="RX")

        self._rel_plot = self._make_plot("Reliability", "Count / %")
        self._rel_plot.addLegend(offset=(-10, 10))
        self._retr_curve = self._rel_plot.plot(
            pen=pg.mkPen(_RETR_COLOUR, width=2), name="Retransmits"
        )
        self._loss_curve = self._rel_plot.plot(
            pen=pg.mkPen(_LOSS_COLOUR, width=2), name="Loss %"
        )

        for plot in (self._tx_plot, self._rx_plot, self._rel_plot):
            layout.addWidget(plot)

    @staticmethod
    def _make_plot(title: str, y_label: str) -> pg.PlotWidget:
        plot = pg.PlotWidget(title=title)
        plot.setLabel("left", y_label)
        plot.setLabel("bottom", "Elapsed", "s")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.setMouseEnabled(x=True, y=False)
        return plot

    # ------------------------------------------------------------------ data

    def add_sample(self, sample: Sample) -> None:
        """Buffer one interval measurement for the next repaint.

        Summary rows are ignored: their interval spans the entire test, so
        plotting them would append a final point whose X value jumps backwards
        to the start of the run.
        """
        if sample.is_summary:
            return

        timestamp = sample.interval_end
        if sample.direction is Direction.TX:
            self._tx.append(timestamp, sample.megabits_per_second)
        else:
            self._rx.append(timestamp, sample.megabits_per_second)

        if sample.retransmits is not None:
            self._retransmits.append(timestamp, float(sample.retransmits))
        if sample.loss_percent is not None:
            self._loss.append(timestamp, sample.loss_percent)

        self._dirty = True

    def reset(self) -> None:
        """Discard all buffered data and clear the plots immediately."""
        for series in (self._tx, self._rx, self._retransmits, self._loss):
            series.clear()
        self._dirty = True
        self._repaint_if_dirty()

    # ------------------------------------------------------------- rendering

    def _repaint_if_dirty(self) -> None:
        if not self._dirty:
            return
        self._dirty = False
        for curve, series in (
            (self._tx_curve, self._tx),
            (self._rx_curve, self._rx),
            (self._retr_curve, self._retransmits),
            (self._loss_curve, self._loss),
        ):
            x, y = series.as_arrays()
            curve.setData(x, y)

    def closeEvent(self, event) -> None:  # noqa: D102 - Qt override
        self._repaint_timer.stop()
        super().closeEvent(event)
