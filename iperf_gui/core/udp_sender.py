"""A connectionless UDP traffic generator.

``iperf3`` cannot do this. It negotiates every test over a TCP control
connection and derives its figures from what the *receiver* reports, so with no
server listening it aborts before opening a data socket.

UDP itself has no such requirement: datagrams can be sent to a closed port, or
to a host that never answers, and the sender neither knows nor cares. This
module sends them directly through a socket, which is useful for exercising a
firewall rule, loading a device that is not an iperf3 server, or simply
confirming that packets leave the interface.

**What it measures.** Only what this host *sent*. Delivery, loss and jitter are
unknowable without a cooperating receiver, so they are reported as unknown
rather than guessed at. This is offered load, not throughput.
"""

from __future__ import annotations

import logging
import socket
import time

from PyQt6.QtCore import QThread, pyqtSignal

from .metrics import Direction, Role, Sample

logger = logging.getLogger(__name__)

#: Default datagram payload. 1472 bytes is the largest that still fits inside a
#: 1500-byte Ethernet MTU once the IPv4 (20) and UDP (8) headers are added, so
#: it is the biggest datagram that will not fragment on a typical link.
DEFAULT_DATAGRAM_BYTES = 1472

MIN_DATAGRAM_BYTES = 1
#: Above the theoretical IPv4 payload limit a send would always fail.
MAX_DATAGRAM_BYTES = 65507

#: How often, at most, the pacing loop yields to the scheduler when it is ahead
#: of the target rate. Small enough to keep pacing tight, large enough not to
#: spin a core.
_IDLE_SLEEP_SECONDS = 0.0005

#: Datagrams sent per pacing check, bounding how far ahead a burst can run.
_MAX_BURST = 64

EXIT_OK = 0
EXIT_CANCELLED = -2
EXIT_FAILED = -1


class UdpBlastConfig:
    """Settings for one traffic-generator run.

    Args:
        host: destination address. It is never connected to, so it need not
            respond or even exist.
        port: destination port.
        bits_per_second: target offered load, or ``None`` to send as fast as
            the machine allows.
        datagram_bytes: payload size of each datagram.
        duration: seconds to send for, or ``None`` to run until stopped.
        report_interval: seconds between telemetry samples.
    """

    def __init__(
        self,
        host: str,
        port: int,
        bits_per_second: float | None = 10_000_000.0,
        datagram_bytes: int = DEFAULT_DATAGRAM_BYTES,
        duration: int | None = 10,
        report_interval: float = 0.5,
    ) -> None:
        self.host = host
        self.port = port
        self.bits_per_second = bits_per_second
        self.datagram_bytes = datagram_bytes
        self.duration = duration
        self.report_interval = report_interval

    def validate(self) -> list[str]:
        """Return human-readable problems; empty means the config is usable."""
        problems: list[str] = []
        if not self.host.strip():
            problems.append("A destination host is required.")
        if not 1 <= self.port <= 65535:
            problems.append("Port must be between 1 and 65535.")
        if not MIN_DATAGRAM_BYTES <= self.datagram_bytes <= MAX_DATAGRAM_BYTES:
            problems.append(
                f"Datagram size must be between {MIN_DATAGRAM_BYTES} and "
                f"{MAX_DATAGRAM_BYTES} bytes."
            )
        if self.bits_per_second is not None and self.bits_per_second <= 0:
            problems.append("Target rate must be greater than zero.")
        if self.duration is not None and self.duration < 1:
            problems.append("Duration must be at least 1 second.")
        if self.report_interval <= 0:
            problems.append("Report interval must be greater than zero.")
        return problems

    def describe(self) -> str:
        """One-line summary for the console."""
        rate = (
            "unlimited"
            if self.bits_per_second is None
            else f"{self.bits_per_second / 1e6:g} Mbit/s"
        )
        length = "until stopped" if self.duration is None else f"{self.duration}s"
        return (
            f"UDP -> {self.host}:{self.port}, {rate}, "
            f"{self.datagram_bytes}-byte datagrams, {length}"
        )


class UdpBlastWorker(QThread):
    """Sends UDP datagrams at a paced rate, with no handshake of any kind."""

    line_received = pyqtSignal(str)
    sample_ready = pyqtSignal(object)
    summary_ready = pyqtSignal(object)
    run_failed = pyqtSignal(str)
    run_finished = pyqtSignal(int)

    def __init__(self, config: UdpBlastConfig, parent: object | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._cancelled = False

    @property
    def config(self) -> UdpBlastConfig:
        """The configuration this worker was constructed with."""
        return self._config

    # ------------------------------------------------------------------- run

    def run(self) -> None:  # noqa: D102 - QThread entry point
        problems = self._config.validate()
        if problems:
            self._fail(" ".join(problems))
            return

        try:
            address = self._resolve()
        except OSError as exc:
            self._fail(f"Could not resolve {self._config.host}: {exc}")
            return

        self.line_received.emit(f"Sending {self._config.describe()}")
        self.line_received.emit(
            "NOTE: no server is involved. Only sent traffic is measured; "
            "delivery, loss and jitter cannot be known without a receiver."
        )

        try:
            sent_datagrams, sent_bytes, elapsed = self._blast(address)
        except OSError as exc:
            self._fail(f"Send failed: {exc}")
            return

        self._emit_summary(sent_datagrams, sent_bytes, elapsed)
        self.run_finished.emit(EXIT_CANCELLED if self._cancelled else EXIT_OK)

    def _resolve(self) -> tuple:
        """Resolve the destination once, up front, so failures are reported early."""
        infos = socket.getaddrinfo(
            self._config.host.strip(),
            self._config.port,
            proto=socket.IPPROTO_UDP,
        )
        family, socktype, proto, _canon, sockaddr = infos[0]
        self._family = family
        return sockaddr

    def _blast(self, address: tuple) -> tuple[int, int, float]:
        """Run the paced send loop. Returns (datagrams, bytes, elapsed)."""
        config = self._config
        payload = self._make_payload(config.datagram_bytes)
        bytes_per_second = (
            None if config.bits_per_second is None else config.bits_per_second / 8.0
        )

        sock = socket.socket(self._family, socket.SOCK_DGRAM)
        try:
            self._configure_socket(sock)

            start = time.perf_counter()
            deadline = None if config.duration is None else start + config.duration
            next_report = start + config.report_interval

            total_datagrams = 0
            total_bytes = 0
            window_bytes = 0
            window_datagrams = 0
            window_start = start

            while not self._cancelled:
                now = time.perf_counter()
                if deadline is not None and now >= deadline:
                    break

                # Pace by comparing what has been sent against what the target
                # rate says should have been sent by now. This self-corrects
                # after any scheduling hiccup instead of drifting.
                if bytes_per_second is not None:
                    owed = bytes_per_second * (now - start) - total_bytes
                    if owed < len(payload):
                        time.sleep(_IDLE_SLEEP_SECONDS)
                        continue
                    burst = min(int(owed // len(payload)), _MAX_BURST)
                else:
                    burst = _MAX_BURST

                for _ in range(burst):
                    if self._cancelled:
                        break
                    sent = self._send(sock, payload, address)
                    if sent:
                        total_datagrams += 1
                        window_datagrams += 1
                        total_bytes += sent
                        window_bytes += sent

                now = time.perf_counter()
                if now >= next_report:
                    self._emit_sample(
                        window_start - start, now - start, window_bytes, window_datagrams
                    )
                    window_bytes = 0
                    window_datagrams = 0
                    window_start = now
                    next_report = now + config.report_interval

            elapsed = time.perf_counter() - start
            return total_datagrams, total_bytes, elapsed
        finally:
            sock.close()

    @staticmethod
    def _configure_socket(sock: socket.socket) -> None:
        """Prepare the socket to keep sending regardless of the far end."""
        sock.setblocking(True)
        try:
            # A large send buffer keeps high rates from blocking on every call.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
        except OSError:
            pass

    def _send(self, sock: socket.socket, payload: bytes, address: tuple) -> int:
        """Send one datagram, tolerating an ICMP rejection from the far end.

        ``sendto`` is used rather than ``connect`` + ``send`` deliberately. On a
        connected UDP socket Windows reports an incoming ICMP port-unreachable
        as ``WSAECONNRESET`` on the *next* send, which would abort a run against
        a closed port -- precisely the case this feature exists to support.
        """
        try:
            return sock.sendto(payload, address)
        except ConnectionResetError:
            # ICMP port unreachable: the datagram still left this host.
            return len(payload)
        except BlockingIOError:
            return 0
        except OSError as exc:
            if exc.errno in (socket.ENETUNREACH, socket.EHOSTUNREACH):
                raise
            logger.debug("Transient send error: %s", exc)
            return 0

    @staticmethod
    def _make_payload(size: int) -> bytes:
        """Build a datagram body of ``size`` bytes.

        The content is an incompressible repeating pattern rather than zeros, so
        any link doing opportunistic compression cannot flatter the result.
        """
        return bytes(range(256)) * (size // 256) + bytes(range(size % 256))

    # -------------------------------------------------------------- reporting

    def _emit_sample(
        self, start: float, end: float, window_bytes: int, datagrams: int
    ) -> None:
        span = max(end - start, 1e-9)
        self.sample_ready.emit(
            Sample(
                stream_id="udp",
                direction=Direction.TX,
                interval_start=start,
                interval_end=end,
                bits_per_second=(window_bytes * 8) / span,
                transfer_bytes=float(window_bytes),
                total_packets=datagrams,
                # Loss and jitter are genuinely unknown here, not zero.
                lost_packets=None,
                loss_percent=None,
                jitter_ms=None,
            )
        )

    def _emit_summary(self, datagrams: int, sent_bytes: int, elapsed: float) -> None:
        span = max(elapsed, 1e-9)
        bits_per_second = (sent_bytes * 8) / span
        self.summary_ready.emit(
            Sample(
                stream_id="udp",
                direction=Direction.TX,
                interval_start=0.0,
                interval_end=elapsed,
                bits_per_second=bits_per_second,
                transfer_bytes=float(sent_bytes),
                total_packets=datagrams,
                is_summary=True,
                role=Role.SENDER,
            )
        )
        self.line_received.emit(
            f"Sent {datagrams} datagrams ({sent_bytes / 1e6:.2f} MB) in "
            f"{elapsed:.2f}s = {bits_per_second / 1e6:.2f} Mbit/s offered."
        )

    def _fail(self, message: str) -> None:
        logger.error("%s", message)
        self.line_received.emit(f"ERROR: {message}")
        self.run_failed.emit(message)
        self.run_finished.emit(EXIT_FAILED)

    # ------------------------------------------------------------- lifecycle

    def stop(self) -> None:
        """Ask the send loop to finish."""
        self._cancelled = True

    def stop_and_wait(self, timeout_ms: int = 5000) -> bool:
        """Stop and block until the thread has exited."""
        if not self.isRunning():
            return True
        self.stop()
        return self.wait(timeout_ms)
