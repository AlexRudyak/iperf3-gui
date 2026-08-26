"""Parser tests built from real ``iperf3`` output.

The interval lines in ``REAL_313_TCP_RUN`` were captured verbatim from the
bundled iperf 3.1.3 binary; the 3.7-style fixtures cover the columns that build
does not emit. Between them they pin the three behaviours the previous parser
got wrong: retransmits are positional, summary rows are not interval samples,
and ``[SUM]`` must not be mixed with per-stream rows.
"""

from __future__ import annotations

import pytest

from iperf_gui.core.config import IperfConfig, Protocol, Role
from iperf_gui.core.metrics import Direction
from iperf_gui.core.parser import IperfParser

REAL_313_TCP_RUN = [
    "Connecting to host 127.0.0.1, port 5299",
    "[  4] local 127.0.0.1 port 56079 connected to 127.0.0.1 port 5299",
    "[ ID] Interval           Transfer     Bandwidth",
    "[  4]   0.00-0.51   sec   380 MBytes  6.26 Gbits/sec                  ",
    "[  4]   0.51-1.00   sec   457 MBytes  7.78 Gbits/sec                  ",
    "[  4]   1.00-1.51   sec   452 MBytes  7.44 Gbits/sec                  ",
    "- - - - - - - - - - - - - - - - - - - - - - - - -",
    "[ ID] Interval           Transfer     Bandwidth",
    "[  4]   0.00-2.01   sec  1.51 GBytes  6.45 Gbits/sec                  sender",
    "[  4]   0.00-2.01   sec  1.51 GBytes  6.45 Gbits/sec                  receiver",
    "",
    "iperf Done.",
]


def parse_all(lines, config=None):
    """Run every line through one parser instance, keeping only the samples."""
    parser = IperfParser(config or IperfConfig())
    return [s for s in (parser.parse_line(line) for line in lines) if s is not None]


class TestNonMeasurementLines:
    @pytest.mark.parametrize(
        "line",
        [
            "",
            "   ",
            "iperf Done.",
            "Connecting to host 127.0.0.1, port 5201",
            "[ ID] Interval           Transfer     Bitrate         Retr  Cwnd",
            "[  4] local 127.0.0.1 port 56079 connected to 127.0.0.1 port 5299",
            "iperf3: error - unable to connect to server: Connection refused",
        ],
    )
    def test_ignored(self, line):
        assert IperfParser(IperfConfig()).parse_line(line) is None


class TestIntervalRows:
    def test_real_313_run_yields_three_intervals_and_two_summaries(self):
        samples = parse_all(REAL_313_TCP_RUN)
        intervals = [s for s in samples if not s.is_summary]
        summaries = [s for s in samples if s.is_summary]
        assert len(intervals) == 3
        assert len(summaries) == 2

    def test_timestamps_come_from_the_data(self):
        intervals = [s for s in parse_all(REAL_313_TCP_RUN) if not s.is_summary]
        assert [s.interval_end for s in intervals] == [0.51, 1.00, 1.51]

    def test_bitrate_units_are_decimal(self):
        sample = parse_all(REAL_313_TCP_RUN)[0]
        assert sample.bits_per_second == pytest.approx(6.26e9)
        assert sample.megabits_per_second == pytest.approx(6260.0)

    @pytest.mark.parametrize(
        "line,expected_mbps",
        [
            ("[  5]   0.00-1.00   sec   114 MBytes   954 Mbits/sec", 954.0),
            ("[  5]   0.00-1.00   sec   128 KBytes  1.05 Mbits/sec", 1.05),
            ("[  5]   0.00-1.00   sec  1.09 GBytes  9.32 Gbits/sec", 9320.0),
            ("[  5]   0.00-1.00   sec  12.0 KBytes   750 Kbits/sec", 0.75),
            ("[  5]   0.00-1.00   sec  0.00 Bytes  0.00 bits/sec", 0.0),
        ],
    )
    def test_unit_normalisation(self, line, expected_mbps):
        sample = IperfParser(IperfConfig()).parse_line(line)
        assert sample is not None
        assert sample.megabits_per_second == pytest.approx(expected_mbps)


class TestRetransmits:
    """The Retr column is positional; the word 'Retr' only ever appears in the header."""

    def test_positional_retransmits_are_read(self):
        line = "[  5]   1.00-2.00   sec   112 MBytes   943 Mbits/sec   12    201 KBytes"
        sample = IperfParser(IperfConfig()).parse_line(line)
        assert sample.retransmits == 12

    def test_zero_retransmits_are_distinguished_from_absent(self):
        with_column = "[  5]   0.00-1.00   sec   114 MBytes   954 Mbits/sec    0    187 KBytes"
        without_column = "[  4]   0.00-0.51   sec   380 MBytes  6.26 Gbits/sec"
        parser = IperfParser(IperfConfig())
        assert parser.parse_line(with_column).retransmits == 0
        assert parser.parse_line(without_column).retransmits is None

    def test_udp_datagram_count_is_not_read_as_retransmits(self):
        line = "[  5]   0.00-1.00   sec   128 KBytes  1.05 Mbits/sec  162"
        sample = IperfParser(IperfConfig(protocol=Protocol.UDP)).parse_line(line)
        assert sample.retransmits is None


class TestSummaryDetection:
    def test_summary_rows_are_flagged_not_treated_as_intervals(self):
        samples = parse_all(REAL_313_TCP_RUN)
        assert all(s.is_summary for s in samples[-2:])
        assert not any(s.is_summary for s in samples[:-2])

    def test_summary_roles_are_captured(self):
        summaries = [s for s in parse_all(REAL_313_TCP_RUN) if s.is_summary]
        assert [s.role.value for s in summaries] == ["sender", "receiver"]

    def test_receiver_summary_does_not_invent_a_reverse_flow(self):
        """Both summary rows describe the same flow, so both keep its direction."""
        summaries = [s for s in parse_all(REAL_313_TCP_RUN) if s.is_summary]
        assert {s.direction for s in summaries} == {Direction.TX}

    def test_parser_resets_between_runs(self):
        parser = IperfParser(IperfConfig())
        for line in REAL_313_TCP_RUN:
            parser.parse_line(line)
        assert parser.in_summary
        parser.reset()
        assert not parser.in_summary
        sample = parser.parse_line("[  4]   0.00-0.51   sec   380 MBytes  6.26 Gbits/sec")
        assert not sample.is_summary


class TestParallelStreams:
    PARALLEL_INTERVAL = [
        "[  5]   0.00-1.00   sec  27.0 MBytes   226 Mbits/sec    0",
        "[  7]   0.00-1.00   sec  28.1 MBytes   236 Mbits/sec    0",
        "[  9]   0.00-1.00   sec  27.5 MBytes   231 Mbits/sec    3",
        "[SUM]   0.00-1.00   sec  82.6 MBytes   693 Mbits/sec    3",
    ]

    def test_aggregate_row_selected_when_parallel(self):
        samples = parse_all(self.PARALLEL_INTERVAL, IperfConfig(parallel=3))
        assert len(samples) == 1
        assert samples[0].is_aggregate
        assert samples[0].megabits_per_second == pytest.approx(693.0)

    def test_per_stream_rows_selected_when_single(self):
        single = ["[  5]   0.00-1.00   sec  27.0 MBytes   226 Mbits/sec    0"]
        samples = parse_all(single, IperfConfig(parallel=1))
        assert len(samples) == 1
        assert not samples[0].is_aggregate

    def test_single_stream_config_ignores_a_sum_row(self):
        samples = parse_all(self.PARALLEL_INTERVAL, IperfConfig(parallel=1))
        assert len(samples) == 3
        assert not any(s.is_aggregate for s in samples)


#: Captured from the bundled binary with ``-P 2``. Note the separator printed
#: after *every* interval group, not only before the summary.
REAL_PARALLEL_RUN = """[ ID] Interval           Transfer     Bandwidth
[  4]   0.00-0.50   sec   812 MBytes  13.6 Gbits/sec
[  6]   0.00-0.50   sec   617 MBytes  10.4 Gbits/sec
[SUM]   0.00-0.50   sec  2.90 GBytes  49.9 Gbits/sec
- - - - - - - - - - - - - - - - - - - - - - - - -
[  4]   0.50-1.00   sec   772 MBytes  12.9 Gbits/sec
[  6]   0.50-1.00   sec   797 MBytes  13.4 Gbits/sec
[SUM]   0.50-1.00   sec  3.02 GBytes  51.8 Gbits/sec
- - - - - - - - - - - - - - - - - - - - - - - - -
[  4]   1.00-1.50   sec   672 MBytes  11.3 Gbits/sec
[  6]   1.00-1.50   sec   762 MBytes  12.8 Gbits/sec
[SUM]   1.00-1.50   sec  2.96 GBytes  50.8 Gbits/sec
- - - - - - - - - - - - - - - - - - - - - - - - -
[ ID] Interval           Transfer     Bandwidth
[  4]   0.00-1.50   sec  2.04 GBytes  17.5 Gbits/sec                  sender
[  4]   0.00-1.50   sec  2.04 GBytes  17.5 Gbits/sec                  receiver
[SUM]   0.00-1.50   sec  4.07 GBytes  34.9 Gbits/sec                  sender
[SUM]   0.00-1.50   sec  4.07 GBytes  34.9 Gbits/sec                  receiver""".splitlines()

#: Captured UDP client run. Its summary row carries no sender/receiver tag,
#: so it can only be recognised by the interval restarting at zero.
REAL_UDP_RUN = """[ ID] Interval           Transfer     Bandwidth       Total Datagrams
[  4]   0.00-1.00   sec   568 KBytes  4.65 Mbits/sec  71
[  4]   1.00-2.00   sec   608 KBytes  4.97 Mbits/sec  76
- - - - - - - - - - - - - - - - - - - - - - - - -
[ ID] Interval           Transfer     Bandwidth       Jitter    Lost/Total Datagrams
[  4]   0.00-2.00   sec  1.15 MBytes  4.81 Mbits/sec  0.020 ms  0/147 (0%)
[  4] Sent 147 datagrams""".splitlines()


class TestSummaryDetectionWithRealRuns:
    """Regressions for summary detection across the formats iperf3 actually emits."""

    def test_inter_group_separators_do_not_end_the_run(self):
        """A separator prints after every interval group when -P > 1."""
        samples = parse_all(REAL_PARALLEL_RUN, IperfConfig(parallel=2))
        intervals = [s for s in samples if not s.is_summary]
        assert [s.interval_end for s in intervals] == [0.5, 1.0, 1.5]

    def test_parallel_summary_rows_are_still_detected(self):
        samples = parse_all(REAL_PARALLEL_RUN, IperfConfig(parallel=2))
        summaries = [s for s in samples if s.is_summary]
        assert len(summaries) == 2
        assert all(s.is_aggregate for s in summaries)

    def test_per_stream_selection_across_groups(self):
        samples = parse_all(REAL_PARALLEL_RUN, IperfConfig(parallel=1))
        intervals = [s for s in samples if not s.is_summary]
        assert len(intervals) == 6
        assert {s.stream_id for s in intervals} == {"4", "6"}

    def test_untagged_udp_summary_detected_by_interval_restart(self):
        samples = parse_all(REAL_UDP_RUN, IperfConfig(protocol=Protocol.UDP))
        intervals = [s for s in samples if not s.is_summary]
        summaries = [s for s in samples if s.is_summary]
        assert [s.interval_end for s in intervals] == [1.0, 2.0]
        assert len(summaries) == 1
        assert summaries[0].role is None
        assert summaries[0].loss_percent == pytest.approx(0.0)

    def test_udp_interval_datagram_counts_are_not_retransmits(self):
        intervals = [
            s
            for s in parse_all(REAL_UDP_RUN, IperfConfig(protocol=Protocol.UDP))
            if not s.is_summary
        ]
        assert all(s.retransmits is None for s in intervals)


class TestUdpFields:
    def test_jitter_and_loss(self):
        line = "[  5]   1.00-2.00   sec   128 KBytes  1.05 Mbits/sec  0.012 ms  7/162 (4.3%)"
        sample = IperfParser(IperfConfig(protocol=Protocol.UDP)).parse_line(line)
        assert sample.jitter_ms == pytest.approx(0.012)
        assert sample.lost_packets == 7
        assert sample.total_packets == 162
        assert sample.loss_percent == pytest.approx(4.3)

    @pytest.mark.parametrize("token", ["nan", "-nan", "NAN"])
    def test_nan_loss_becomes_none_rather_than_a_nan_value(self, token):
        line = f"[  5]   2.00-3.00   sec  0.00 KBytes  0.00 bits/sec  0.000 ms  0/0 ({token}%)"
        sample = IperfParser(IperfConfig(protocol=Protocol.UDP)).parse_line(line)
        assert sample.loss_percent is None
        assert sample.lost_packets == 0


class TestDirection:
    @pytest.mark.parametrize(
        "config,expected",
        [
            (IperfConfig(), Direction.TX),
            (IperfConfig(reverse=True), Direction.RX),
            (IperfConfig(role=Role.SERVER), Direction.RX),
            (IperfConfig(role=Role.SERVER, reverse=True), Direction.TX),
        ],
    )
    def test_direction_follows_configuration(self, config, expected):
        line = "[  5]   0.00-1.00   sec   114 MBytes   954 Mbits/sec"
        assert IperfParser(config).parse_line(line).direction is expected

    @pytest.mark.parametrize(
        "tag,expected",
        [("TX-C", Direction.TX), ("RX-C", Direction.RX),
         ("TX-S", Direction.TX), ("RX-S", Direction.RX)],
    )
    def test_bidir_tags_override_the_default(self, tag, expected):
        line = f"[  5][{tag}]   0.00-1.00   sec   114 MBytes   954 Mbits/sec"
        # Configured as reverse so the default would be RX; the tag must win.
        config = IperfConfig(reverse=True)
        assert IperfParser(config).parse_line(line).direction is expected


class TestRobustness:
    @pytest.mark.parametrize(
        "line",
        [
            "[  5]   0.00-1.00   sec   114 MBytes",
            "[  5]   sec   114 MBytes   954 Mbits/sec",
            "[]   0.00-1.00   sec   114 MBytes   954 Mbits/sec",
            "[  5]   0.00-1.00   sec   114 ZBytes   954 Zbits/sec",
        ],
    )
    def test_malformed_rows_return_none_instead_of_raising(self, line):
        assert IperfParser(IperfConfig()).parse_line(line) is None
