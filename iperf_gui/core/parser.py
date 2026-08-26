"""Scraping of ``iperf3`` human-readable stdout into :class:`Sample` objects.

``iperf3`` has no stable machine-readable streaming mode across the versions
this app supports (``--json`` suppresses interval reporting on older builds),
so the console output is parsed instead. The format is stable enough to parse
reliably provided three things are respected:

**Fields are positional, not labelled.** The ``Retr`` column has a header but
its values do not, so retransmits must be read from the trailing fields by
position. Searching for the word ``Retr`` only ever matches the header row.

**Summary rows look almost identical to interval rows.** Both carry a stream
id, an interval and a bitrate, and treating a summary row as a live sample
corrupts the time series because its interval spans the whole test. The
``- - - - -`` separator alone is *not* enough to tell them apart: with parallel
streams ``iperf3`` prints one after every interval group, not just before the
summary. Three independent signals are combined instead, described on
:meth:`IperfParser._is_summary_row`.

**The meaning of the trailing integer depends on the protocol.** For TCP it is
the retransmit count; for a UDP client it is the datagram count. The protocol
is therefore supplied by the caller rather than guessed.
"""

from __future__ import annotations

import logging
import re

from .config import IperfConfig, Protocol
from .metrics import Direction, Role, Sample

logger = logging.getLogger(__name__)

#: Separator line. Printed before the closing summary block, and also between
#: interval groups when more than one stream is active.
_SUMMARY_SEPARATOR = "- - - - -"

#: Column header row. Reprinted immediately before the closing summary block.
_HEADER_PREFIX = "[ ID]"

#: Structured prefix shared by every measurement row:
#: ``[ ID]`` or ``[SUM]``, an optional ``[TX-C]``-style bidirectional tag,
#: the interval, the transfer volume and the bitrate.
_ROW_RE = re.compile(
    r"""^\[\s*(?P<stream>[A-Za-z0-9_-]+)\s*\]        # [  5] or [SUM]
        (?:\[\s*(?P<tag>[TR]X-[CS])\s*\])?           # optional [TX-C] bidir tag
        \s+(?P<start>\d+(?:\.\d+)?)                  # interval start
        -\s*(?P<end>\d+(?:\.\d+)?)\s+sec             # interval end
        \s+(?P<transfer>\d+(?:\.\d+)?)\s+(?P<tunit>[KMGT]?Bytes)
        \s+(?P<rate>\d+(?:\.\d+)?)\s+(?P<runit>[KMGT]?bits/sec)
        (?P<tail>.*)$""",
    re.VERBOSE,
)

#: UDP loss report, e.g. ``0/162 (0%)``. The percentage may be ``nan`` or
#: ``-nan`` when no datagrams were sent, which must not become a plotted value.
_LOSS_RE = re.compile(
    r"(?P<lost>\d+)/(?P<total>\d+)\s+\((?P<pct>-?nan|-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)%\)",
    re.IGNORECASE,
)

#: Jitter column present on UDP receiver rows, e.g. ``0.005 ms``.
_JITTER_RE = re.compile(r"(?P<jitter>\d+(?:\.\d+)?)\s+ms")

#: First bare integer in the trailing fields (retransmits or datagram count).
_TRAILING_INT_RE = re.compile(r"^\s+(\d+)(?:\s|$)")

_BYTE_UNIT_SCALE = {
    "Bytes": 1.0,
    "KBytes": 1024.0,
    "MBytes": 1024.0**2,
    "GBytes": 1024.0**3,
    "TBytes": 1024.0**4,
}

#: Bitrate units are decimal in iperf3, unlike the binary transfer units.
_BIT_UNIT_SCALE = {
    "bits/sec": 1.0,
    "Kbits/sec": 1e3,
    "Mbits/sec": 1e6,
    "Gbits/sec": 1e9,
    "Tbits/sec": 1e12,
}


class IperfParser:
    """Converts ``iperf3`` output lines into :class:`Sample` objects.

    The parser is stateful: it tracks whether the summary block has begun, so
    it must see every line of a run in order, and must be reset between runs.

    Args:
        config: the configuration the run was launched with, which supplies the
            protocol, the default flow direction and whether ``[SUM]`` rows are
            expected.
    """

    def __init__(self, config: IperfConfig | None = None) -> None:
        self._config = config or IperfConfig()
        self._in_summary = False
        self._saw_separator = False
        self._max_interval_start: dict[str, float] = {}

    def reset(self) -> None:
        """Clear per-run state so the instance can parse another run."""
        self._in_summary = False
        self._saw_separator = False
        self._max_interval_start.clear()

    @property
    def in_summary(self) -> bool:
        """Whether the closing summary block has been reached."""
        return self._in_summary

    def parse_line(self, line: str) -> Sample | None:
        """Parse one output line.

        Returns:
            A :class:`Sample`, or ``None`` if the line is not a measurement row
            or describes a stream this configuration does not care about.
        """
        stripped = line.strip()
        if not stripped:
            return None

        if _SUMMARY_SEPARATOR in stripped:
            self._saw_separator = True
            return None

        if stripped.startswith(_HEADER_PREFIX):
            # A header immediately after a separator introduces the closing
            # summary. A separator followed straight by data rows is only the
            # divider between per-interval groups of parallel streams.
            if self._saw_separator:
                self._in_summary = True
            return None

        match = _ROW_RE.match(stripped)
        if not match:
            return None

        self._saw_separator = False

        stream_id = match.group("stream")
        if not self._is_selected_stream(stream_id):
            return None

        try:
            return self._build_sample(match, stripped)
        except (ValueError, KeyError):
            # A malformed row must never abort the run; skip it and continue.
            logger.debug("Unparseable measurement row: %r", stripped, exc_info=True)
            return None

    # ------------------------------------------------------------- internals

    def _is_selected_stream(self, stream_id: str) -> bool:
        """Filter out rows that would double-count throughput.

        With parallel streams ``iperf3`` prints one row per stream *and* a
        ``[SUM]`` row per interval. Plotting both interleaves per-stream and
        aggregate values into a single meaningless series, so exactly one of
        the two is selected based on whether an aggregate row is expected.
        """
        is_aggregate = stream_id.upper() == "SUM"
        if self._config.expects_aggregate_row:
            return is_aggregate
        return not is_aggregate

    def _build_sample(self, match: re.Match[str], line: str) -> Sample:
        rate_unit = match.group("runit")
        transfer_unit = match.group("tunit")

        bits_per_second = float(match.group("rate")) * _BIT_UNIT_SCALE[rate_unit]
        transfer_bytes = float(match.group("transfer")) * _BYTE_UNIT_SCALE[transfer_unit]

        tail = match.group("tail")
        role = _role_from_tail(tail)
        stream_id = match.group("stream")
        interval_start = float(match.group("start"))
        is_summary = self._is_summary_row(stream_id, interval_start, role)

        jitter_ms, lost, total, loss_percent = _parse_udp_fields(tail)
        retransmits = _parse_retransmits(tail, self._config.protocol, lost is not None)

        return Sample(
            stream_id=stream_id,
            direction=self._direction(match.group("tag"), role),
            interval_start=interval_start,
            interval_end=float(match.group("end")),
            bits_per_second=bits_per_second,
            transfer_bytes=transfer_bytes,
            retransmits=retransmits,
            jitter_ms=jitter_ms,
            lost_packets=lost,
            total_packets=total,
            loss_percent=loss_percent,
            is_summary=is_summary,
            role=role,
        )

    def _is_summary_row(
        self, stream_id: str, interval_start: float, role: Role | None
    ) -> bool:
        """Decide whether a measurement row belongs to the closing summary.

        Three signals are combined, because no single one covers every build
        and configuration:

        1. A separator followed by a column header, which only ever precedes
           the summary block (:meth:`parse_line` sets ``_in_summary``).
        2. An explicit ``sender``/``receiver`` tag, which TCP summaries carry
           but interval rows never do.
        3. The interval restarting at zero for a stream that has already
           reported a later interval. This is what catches the UDP client
           summary, which has neither a tag nor, on some builds, a preceding
           header.
        """
        if self._in_summary or role is not None:
            return True

        previous_start = self._max_interval_start.get(stream_id)
        restarted = interval_start == 0.0 and previous_start is not None and previous_start > 0.0

        self._max_interval_start[stream_id] = max(
            interval_start, previous_start if previous_start is not None else 0.0
        )
        return restarted

    def _direction(self, tag: str | None, role: Role | None) -> Direction:
        """Resolve which way the traffic in a row was flowing.

        An explicit ``[TX-C]``-style tag from ``--bidir`` is authoritative.
        Otherwise the direction follows from the configuration: a client sends
        unless ``-R`` was given, and a server receives unless it was.
        """
        if tag:
            return Direction.TX if tag.upper().startswith("TX") else Direction.RX

        default = self._config.default_direction()
        if role is None:
            return default

        # On summary rows, "sender" and "receiver" describe the two ends of the
        # same flow, not two flows. Reporting the receiver row as an inbound
        # measurement would invent a reverse flow that never existed, so both
        # rows keep the direction the data actually travelled.
        return default


def _role_from_tail(tail: str) -> Role | None:
    """Detect a trailing ``sender``/``receiver`` tag on a summary row."""
    lowered = tail.lower()
    if "receiver" in lowered:
        return Role.RECEIVER
    if "sender" in lowered:
        return Role.SENDER
    return None


def _parse_udp_fields(
    tail: str,
) -> tuple[float | None, int | None, int | None, float | None]:
    """Extract jitter and datagram-loss fields from a UDP row's trailing text."""
    loss_match = _LOSS_RE.search(tail)
    if not loss_match:
        return None, None, None, None

    lost = int(loss_match.group("lost"))
    total = int(loss_match.group("total"))

    raw_pct = loss_match.group("pct").lower()
    # iperf3 prints nan when no datagrams were sent; a nan would silently
    # poison both the plot and the sweep aggregates.
    loss_percent = None if "nan" in raw_pct else float(raw_pct)

    jitter_match = _JITTER_RE.search(tail)
    jitter_ms = float(jitter_match.group("jitter")) if jitter_match else None

    return jitter_ms, lost, total, loss_percent


def _parse_retransmits(tail: str, protocol: Protocol, has_loss_fields: bool) -> int | None:
    """Read the TCP retransmit count from a row's trailing fields.

    Returns ``None`` rather than ``0`` when the column is absent, so that a
    build which reports no ``Retr`` column at all is distinguishable from one
    reporting genuinely zero retransmits.
    """
    if protocol is Protocol.UDP or has_loss_fields:
        # The bare integer on a UDP client row is a datagram count.
        return None
    match = _TRAILING_INT_RE.match(tail)
    return int(match.group(1)) if match else None
