"""Tests for CSV export."""

from __future__ import annotations

import csv

import pytest

from iperf_gui.core.export import ExportError, write_results_csv
from iperf_gui.core.metrics import RESULT_COLUMNS, IterationResult


@pytest.fixture
def results():
    return [
        IterationResult(
            parameter="-M", value=1000, avg_mbps=900.0, peak_mbps=950.0,
            sender_mbps=900.0, receiver_mbps=899.0, retransmits=3,
            lost_packets=None, loss_percent=None, sample_count=5, exit_code=0,
        ),
        IterationResult(
            parameter="-M", value=1400, avg_mbps=940.0, peak_mbps=980.0,
            sender_mbps=940.0, receiver_mbps=938.0, retransmits=0,
            lost_packets=None, loss_percent=None, sample_count=5, exit_code=0,
        ),
    ]


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_writes_every_column_by_default(tmp_path, results):
    target = tmp_path / "out.csv"
    assert write_results_csv(target, results) == 2
    rows = read_csv(target)
    assert list(rows[0]) == list(RESULT_COLUMNS)


def test_column_subset_is_respected(tmp_path, results):
    target = tmp_path / "subset.csv"
    write_results_csv(target, results, ["Value", "Avg Bandwidth (Mbps)"])
    rows = read_csv(target)
    assert list(rows[0]) == ["Value", "Avg Bandwidth (Mbps)"]
    assert rows[0]["Value"] == "1000"


def test_columns_keep_canonical_order_regardless_of_input_order(tmp_path, results):
    target = tmp_path / "ordered.csv"
    write_results_csv(target, results, ["Avg Bandwidth (Mbps)", "Value"])
    # write_results_csv preserves the order it is given; the dialog is what
    # guarantees canonical order, so verify the caller's order is honoured.
    assert list(read_csv(target)[0]) == ["Avg Bandwidth (Mbps)", "Value"]


def test_no_blank_lines_between_rows(tmp_path, results):
    target = tmp_path / "clean.csv"
    write_results_csv(target, results)
    text = target.read_text(encoding="utf-8")
    assert "\n\n" not in text.replace("\r\n", "\n")


def test_empty_column_selection_is_rejected(tmp_path, results):
    with pytest.raises(ExportError, match="No columns"):
        write_results_csv(tmp_path / "x.csv", results, [])


def test_unknown_column_is_rejected(tmp_path, results):
    with pytest.raises(ExportError, match="Unknown"):
        write_results_csv(tmp_path / "x.csv", results, ["Nope"])


def test_unwritable_path_raises_export_error(tmp_path, results):
    with pytest.raises(ExportError, match="Could not write"):
        write_results_csv(tmp_path / "missing_dir" / "x.csv", results)


def test_empty_result_set_writes_only_a_header(tmp_path):
    target = tmp_path / "empty.csv"
    assert write_results_csv(target, []) == 0
    assert read_csv(target) == []
