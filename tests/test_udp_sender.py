"""Tests for the connectionless UDP traffic generator.

The point of this feature is that it works where iperf3 refuses to: with no
server, and against a closed port. The tests exercise exactly that.
"""

from __future__ import annotations

import socket
import threading

import pytest

from iperf_gui.core.udp_sender import (
    MAX_DATAGRAM_BYTES,
    UdpBlastConfig,
    UdpBlastWorker,
)
from iperf_gui.core.metrics import Direction


class TestConfigValidation:
    def test_defaults_are_usable(self):
        assert UdpBlastConfig("127.0.0.1", 5201).validate() == []

    @pytest.mark.parametrize(
        "config,fragment",
        [
            (UdpBlastConfig("", 5201), "host is required"),
            (UdpBlastConfig("  ", 5201), "host is required"),
            (UdpBlastConfig("h", 0), "Port"),
            (UdpBlastConfig("h", 70000), "Port"),
            (UdpBlastConfig("h", 5201, datagram_bytes=0), "Datagram size"),
            (
                UdpBlastConfig("h", 5201, datagram_bytes=MAX_DATAGRAM_BYTES + 1),
                "Datagram size",
            ),
            (UdpBlastConfig("h", 5201, bits_per_second=0), "Target rate"),
            (UdpBlastConfig("h", 5201, duration=0), "Duration"),
            (UdpBlastConfig("h", 5201, report_interval=0), "Report interval"),
        ],
    )
    def test_rejected(self, config, fragment):
        problems = config.validate()
        assert problems
        assert any(fragment in p for p in problems)

    def test_unlimited_rate_is_allowed(self):
        assert UdpBlastConfig("h", 5201, bits_per_second=None).validate() == []

    def test_run_until_stopped_is_allowed(self):
        assert UdpBlastConfig("h", 5201, duration=None).validate() == []

    def test_describe_mentions_rate_and_size(self):
        text = UdpBlastConfig("10.0.0.1", 9, 10_000_000, 1472, 5).describe()
        assert "10.0.0.1:9" in text and "1472" in text

    def test_describe_says_unlimited_when_unpaced(self):
        assert "unlimited" in UdpBlastConfig("h", 9, None).describe()


class TestPayload:
    def test_payload_is_the_requested_length(self):
        for size in (1, 100, 256, 1472, 5000):
            assert len(UdpBlastWorker._make_payload(size)) == size

    def test_payload_is_not_all_zeros(self):
        """Zero-filled datagrams would flatter any compressing link."""
        assert len(set(UdpBlastWorker._make_payload(1472))) > 1


@pytest.fixture
def receiver():
    """A plain UDP socket that counts what arrives."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.3)
    state = {"datagrams": 0, "bytes": 0}
    stop = threading.Event()

    def pump():
        while not stop.is_set():
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            state["datagrams"] += 1
            state["bytes"] += len(data)

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    yield sock.getsockname()[1], state
    stop.set()
    thread.join(timeout=2)
    sock.close()


def drain(worker, timeout_ms=30000):
    """Run a worker to completion on a Qt event loop."""
    from PyQt6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    result = {"code": None, "samples": [], "summaries": [], "lines": []}
    worker.sample_ready.connect(result["samples"].append)
    worker.summary_ready.connect(result["summaries"].append)
    worker.line_received.connect(result["lines"].append)
    worker.run_finished.connect(lambda c: (result.__setitem__("code", c), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    worker.start()
    loop.exec()
    worker.wait(5000)
    return result


@pytest.mark.usefixtures("qapp")
class TestSending:
    """These need a QApplication for the worker's signals."""

    def test_sends_with_nothing_listening(self, qapp):
        """iperf3 aborts here; a raw socket does not care."""
        worker = UdpBlastWorker(
            UdpBlastConfig("127.0.0.1", 9, 5_000_000, 1472, duration=1)
        )
        result = drain(worker)
        assert result["code"] == 0
        assert result["summaries"], "expected a closing summary"
        assert result["summaries"][0].total_packets > 0

    def test_datagrams_actually_arrive(self, qapp, receiver):
        port, state = receiver
        worker = UdpBlastWorker(
            UdpBlastConfig("127.0.0.1", port, 5_000_000, 1000, duration=1)
        )
        result = drain(worker)
        sent = result["summaries"][0].total_packets
        assert sent > 0
        # Loopback should not drop, but allow a small margin for scheduling.
        assert state["datagrams"] >= sent * 0.9

    def test_samples_are_tx_and_carry_real_timestamps(self, qapp):
        worker = UdpBlastWorker(
            UdpBlastConfig("127.0.0.1", 9, 5_000_000, 1472, duration=1)
        )
        result = drain(worker)
        assert result["samples"]
        assert all(s.direction is Direction.TX for s in result["samples"])
        ends = [s.interval_end for s in result["samples"]]
        assert ends == sorted(ends)

    def test_loss_is_reported_as_unknown_not_zero(self, qapp):
        """Nothing reports back, so claiming zero loss would be a lie."""
        worker = UdpBlastWorker(
            UdpBlastConfig("127.0.0.1", 9, 5_000_000, 1472, duration=1)
        )
        result = drain(worker)
        assert all(s.loss_percent is None for s in result["samples"])
        assert all(s.lost_packets is None for s in result["samples"])

    def test_rate_is_paced_near_the_target(self, qapp):
        target = 8_000_000.0
        worker = UdpBlastWorker(
            UdpBlastConfig("127.0.0.1", 9, target, 1472, duration=2)
        )
        result = drain(worker)
        achieved = result["summaries"][0].bits_per_second
        assert 0.8 * target <= achieved <= 1.2 * target

    def test_unresolvable_host_fails_cleanly(self, qapp):
        worker = UdpBlastWorker(
            UdpBlastConfig("no-such-host.invalid", 9, 1_000_000, 100, duration=1)
        )
        failures = []
        worker.run_failed.connect(failures.append)
        result = drain(worker)
        assert result["code"] != 0
        assert failures

    def test_invalid_config_fails_without_sending(self, qapp):
        worker = UdpBlastWorker(UdpBlastConfig("", 5201))
        result = drain(worker)
        assert result["code"] != 0
        assert not result["summaries"]
