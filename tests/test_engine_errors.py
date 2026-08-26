"""Tests for turning iperf3's diagnostics into actionable messages.

A failed run used to surface only as "Test finished with exit code 1" in the
console, which reads as the application misbehaving rather than as the target
refusing the connection.
"""

from __future__ import annotations

import pytest

from iperf_gui.core.engine import extract_error, hint_for


class TestExtractError:
    def test_reads_the_reason_from_an_error_line(self):
        line = "iperf3: error - unable to connect to server: Connection refused"
        assert extract_error(line) == "unable to connect to server: Connection refused"

    def test_tolerates_surrounding_whitespace(self):
        line = "   iperf3: error - the server is busy running a test   "
        assert extract_error(line) == "the server is busy running a test"

    @pytest.mark.parametrize(
        "line",
        [
            "",
            "iperf Done.",
            "[  4]   0.00-1.00   sec   114 MBytes   954 Mbits/sec",
            "Connecting to host 127.0.0.1, port 5201",
            "iperf3: warning - something less severe",
        ],
    )
    def test_ignores_non_error_lines(self, line):
        assert extract_error(line) is None


class TestHints:
    def test_connection_refused_names_the_missing_server(self):
        hint = hint_for("unable to connect to server: Connection refused", 5201)
        assert hint is not None
        assert "iperf3 -s -p 5201" in hint

    def test_hint_uses_the_configured_port(self):
        assert "9999" in hint_for("Connection refused", 9999)

    @pytest.mark.parametrize(
        "reason",
        [
            "unable to connect to server: Connection timed out",
            "No route to host",
            "unable to start listener: Address already in use",
            "the server is busy running a test",
        ],
    )
    def test_known_failures_all_get_a_hint(self, reason):
        assert hint_for(reason, 5201)

    def test_matching_is_case_insensitive(self):
        assert hint_for("CONNECTION REFUSED", 5201)

    def test_unknown_failure_gets_no_invented_advice(self):
        assert hint_for("something nobody has seen before", 5201) is None
