"""Tests for sweep value generation and result aggregation."""

from __future__ import annotations

import pytest

from iperf_gui.core.metrics import RESULT_COLUMNS, IterationResult
from iperf_gui.core.sweep import (
    ExplicitSweep,
    ExponentialSweep,
    LinearSweep,
    SweepError,
)
from iperf_gui.core.sweep.strategies import MAX_SWEEP_POINTS


class TestLinearSweep:
    def test_inclusive_of_end_when_it_lands_on_a_step(self):
        assert LinearSweep(500, 1500, 500).values() == [500, 1000, 1500]

    def test_never_overshoots_end(self):
        """range(start, end + step, step) used to run past the requested end."""
        values = LinearSweep(1, 10, 3).values()
        assert values == [1, 4, 7, 10]
        assert max(values) <= 10

    def test_uneven_step_stops_before_end(self):
        values = LinearSweep(1, 10, 4).values()
        assert values == [1, 5, 9]

    def test_single_value_when_start_equals_end(self):
        assert LinearSweep(100, 100, 10).values() == [100]

    @pytest.mark.parametrize(
        "strategy,fragment",
        [
            (LinearSweep(1500, 500, 100), "must not exceed"),
            (LinearSweep(1, 10, 0), "greater than zero"),
            (LinearSweep(1, 10, -5), "greater than zero"),
        ],
    )
    def test_invalid_parameters_raise(self, strategy, fragment):
        with pytest.raises(SweepError, match=fragment):
            strategy.values()

    def test_runaway_sweep_is_capped(self):
        with pytest.raises(SweepError, match="maximum"):
            LinearSweep(1, MAX_SWEEP_POINTS * 10, 1).values()


class TestExponentialSweep:
    def test_doubling(self):
        assert ExponentialSweep(1024, 16384).values() == [1024, 2048, 4096, 8192, 16384]

    def test_does_not_exceed_end(self):
        assert max(ExponentialSweep(1000, 5000).values()) <= 5000

    def test_values_are_strictly_increasing(self):
        values = ExponentialSweep(1, 20, 1.5).values()
        assert values == sorted(set(values))

    @pytest.mark.parametrize(
        "strategy",
        [
            ExponentialSweep(0, 100),
            ExponentialSweep(10, 100, 1.0),
            ExponentialSweep(100, 10),
        ],
    )
    def test_invalid_parameters_raise(self, strategy):
        with pytest.raises(SweepError):
            strategy.values()


class TestExplicitSweep:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("100,200,300", [100, 200, 300]),
            ("100 200 300", [100, 200, 300]),
            ("100, 200  300", [100, 200, 300]),
            (" 42 ", [42]),
        ],
    )
    def test_parsing(self, text, expected):
        assert ExplicitSweep.from_text(text).values() == expected

    def test_order_is_preserved(self):
        assert ExplicitSweep.from_text("300,100,200").values() == [300, 100, 200]

    def test_non_integer_is_rejected(self):
        with pytest.raises(SweepError):
            ExplicitSweep.from_text("100, abc")

    def test_empty_is_rejected(self):
        with pytest.raises(SweepError):
            ExplicitSweep.from_text("").values()


class TestStrategyDescriptions:
    @pytest.mark.parametrize(
        "strategy",
        [LinearSweep(1, 10, 1), ExponentialSweep(1, 10), ExplicitSweep((1, 2))],
    )
    def test_describe_is_non_empty(self, strategy):
        assert strategy.describe()


class TestIterationResult:
    def make(self, **overrides):
        defaults = dict(
            parameter="-M", value=1400, avg_mbps=940.123456, peak_mbps=955.5,
            sender_mbps=940.1, receiver_mbps=939.0, retransmits=12,
            lost_packets=None, loss_percent=None, sample_count=10, exit_code=0,
        )
        defaults.update(overrides)
        return IterationResult(**defaults)

    def test_row_covers_every_declared_column(self):
        assert set(self.make().as_row()) == set(RESULT_COLUMNS)

    def test_values_are_rounded(self):
        assert self.make().as_row()["Avg Bandwidth (Mbps)"] == 940.12

    def test_absent_metrics_stay_none_rather_than_zero(self):
        row = self.make(retransmits=None, lost_packets=None).as_row()
        assert row["Total Retransmits"] is None
        assert row["Lost Packets"] is None
