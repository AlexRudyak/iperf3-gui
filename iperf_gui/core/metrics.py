"""Value objects describing measurements scraped from ``iperf3`` output.

These types are deliberately free of any Qt or I/O dependency so that the
parsing and aggregation logic can be unit tested without a ``QApplication``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: Identifier ``iperf3`` uses for the aggregate row emitted when more than one
#: parallel stream is active (``-P N`` with ``N > 1``).
AGGREGATE_STREAM_ID = "SUM"

_BITS_PER_MBIT = 1_000_000.0


class Direction(Enum):
    """Direction of a measured flow, relative to the host running this GUI."""

    TX = "tx"
    """Data leaving the local host."""

    RX = "rx"
    """Data arriving at the local host."""


class Role(Enum):
    """Which side of the test a summary line describes."""

    SENDER = "sender"
    RECEIVER = "receiver"


@dataclass(frozen=True)
class Sample:
    """A single measurement row from ``iperf3`` stdout.

    One ``Sample`` corresponds to exactly one output line, which is either a
    periodic interval report or a line from the closing summary block.
    """

    stream_id: str
    """Stream tag, e.g. ``"5"`` for a data stream or ``"SUM"`` for the aggregate."""

    direction: Direction
    interval_start: float
    """Seconds since test start at which this measurement window opened."""

    interval_end: float
    """Seconds since test start at which this measurement window closed."""

    bits_per_second: float
    transfer_bytes: float | None = None
    retransmits: int | None = None
    """TCP retransmit count. ``None`` when the build reports no ``Retr`` column."""

    jitter_ms: float | None = None
    lost_packets: int | None = None
    total_packets: int | None = None
    loss_percent: float | None = None
    is_summary: bool = False
    """True for rows in the closing summary block rather than a live interval."""

    role: Role | None = None
    """Populated only for summary rows tagged ``sender`` or ``receiver``."""

    @property
    def is_aggregate(self) -> bool:
        """Whether this row is the ``[SUM]`` total across parallel streams."""
        return self.stream_id == AGGREGATE_STREAM_ID

    @property
    def megabits_per_second(self) -> float:
        """Throughput in Mbit/s, the unit used by the dashboard's Y axis."""
        return self.bits_per_second / _BITS_PER_MBIT


#: Ordered column definitions for a sweep result row.
#:
#: This is the single source of truth shared by the CSV export dialog, the live
#: results table and :meth:`IterationResult.as_row`, so a rename cannot silently
#: desynchronise them.
RESULT_COLUMNS: tuple[str, ...] = (
    "Parameter",
    "Value",
    "Avg Bandwidth (Mbps)",
    "Peak Bandwidth (Mbps)",
    "Sender Bandwidth (Mbps)",
    "Receiver Bandwidth (Mbps)",
    "Total Retransmits",
    "Lost Packets",
    "Loss (%)",
    "Samples",
    "Exit Code",
)


@dataclass(frozen=True)
class IterationResult:
    """Aggregated outcome of one iteration of a parameter sweep."""

    parameter: str
    value: int
    avg_mbps: float
    peak_mbps: float
    sender_mbps: float | None
    receiver_mbps: float | None
    retransmits: int | None
    lost_packets: int | None
    loss_percent: float | None
    sample_count: int
    exit_code: int

    def as_row(self) -> dict[str, object]:
        """Render this result as a mapping keyed by :data:`RESULT_COLUMNS`."""
        return {
            "Parameter": self.parameter,
            "Value": self.value,
            "Avg Bandwidth (Mbps)": round(self.avg_mbps, 2),
            "Peak Bandwidth (Mbps)": round(self.peak_mbps, 2),
            "Sender Bandwidth (Mbps)": (
                None if self.sender_mbps is None else round(self.sender_mbps, 2)
            ),
            "Receiver Bandwidth (Mbps)": (
                None if self.receiver_mbps is None else round(self.receiver_mbps, 2)
            ),
            "Total Retransmits": self.retransmits,
            "Lost Packets": self.lost_packets,
            "Loss (%)": (
                None if self.loss_percent is None else round(self.loss_percent, 4)
            ),
            "Samples": self.sample_count,
            "Exit Code": self.exit_code,
        }
