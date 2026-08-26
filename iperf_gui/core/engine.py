"""Execution of a single ``iperf3`` run on a background thread."""

from __future__ import annotations

import logging
import subprocess
from typing import Iterator

from PyQt6.QtCore import QThread, pyqtSignal

from ..utils.paths import iperf3_executable
from .config import IperfConfig
from .metrics import Sample
from .parser import IperfParser
from .process import creation_flags, terminate_process

logger = logging.getLogger(__name__)

#: Exit code reported when the run failed before iperf3 produced a status.
EXIT_CODE_LAUNCH_FAILED = -1

#: Exit code reported when the user stopped the run deliberately.
EXIT_CODE_CANCELLED = -2

#: Prefix iperf3 uses for fatal diagnostics, e.g.
#: "iperf3: error - unable to connect to server: Connection refused".
_ERROR_PREFIX = "iperf3: error -"

#: Hints for failures whose iperf3 message does not say what to do about it.
#: Matched case-insensitively against the reported reason.
_ERROR_HINTS: tuple[tuple[str, str], ...] = (
    (
        "connection refused",
        "Nothing is listening on that host and port. Start a server there "
        "first with: iperf3 -s -p {port}",
    ),
    (
        "no route to host",
        "The target is unreachable from this machine. Check the address and "
        "that both hosts are on the same network.",
    ),
    (
        "connection timed out",
        "The target did not answer. A firewall is most likely dropping TCP "
        "port {port}, which iperf3 needs for its control connection.",
    ),
    (
        "address already in use",
        "Port {port} is already taken on this machine. Stop the other "
        "process or choose a different port.",
    ),
    (
        "server is busy",
        "The server is already running a test. iperf3 handles one client at "
        "a time unless it was started with -s -D.",
    ),
)


def extract_error(line: str) -> str | None:
    """Return the reason from an ``iperf3: error - ...`` line, if it is one."""
    stripped = line.strip()
    if not stripped.lower().startswith(_ERROR_PREFIX):
        return None
    return stripped[len(_ERROR_PREFIX):].strip() or stripped


def hint_for(reason: str, port: int) -> str | None:
    """Suggest a remedy for a known failure reason.

    ``iperf3`` reports what went wrong but never what to do about it, and
    "Connection refused" in particular reads as a fault in this application
    rather than a missing server on the other end.
    """
    lowered = reason.lower()
    for needle, hint in _ERROR_HINTS:
        if needle in lowered:
            return hint.format(port=port)
    return None


class IperfWorker(QThread):
    """Runs one ``iperf3`` process and streams its output as Qt signals.

    Note the deliberate absence of a signal named ``finished``. The previous
    implementation declared one, which shadowed :attr:`QThread.finished` and
    made Qt's own thread-lifecycle notification unreachable -- including the
    standard ``finished.connect(deleteLater)`` cleanup idiom. Consumers that
    want the exit code connect to :attr:`run_finished`; consumers that want to
    know the *thread* has ended connect to the inherited ``finished``.
    """

    line_received = pyqtSignal(str)
    """Emitted for every line of ``iperf3`` output, for the console view."""

    sample_ready = pyqtSignal(object)
    """Emitted with a :class:`Sample` for each live interval measurement."""

    summary_ready = pyqtSignal(object)
    """Emitted with a :class:`Sample` for each row of the closing summary."""

    run_failed = pyqtSignal(str)
    """Emitted with a human-readable reason when the run could not complete."""

    run_finished = pyqtSignal(int)
    """Emitted with the process exit code once the run has ended."""

    def __init__(self, config: IperfConfig, parent: object | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._parser = IperfParser(config)
        self._process: subprocess.Popen[str] | None = None
        self._cancelled = False
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        """The most recent ``iperf3: error`` reason seen on this run."""
        return self._last_error

    @property
    def config(self) -> IperfConfig:
        """The configuration this worker was constructed with."""
        return self._config

    # ------------------------------------------------------------------- run

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            args = self._config.to_args()
        except ValueError as exc:
            self._fail(f"Invalid configuration: {exc}")
            return

        command = [iperf3_executable(), *args]
        self.line_received.emit(f"Executing: {subprocess.list2cmdline(command)}")
        logger.info("Launching %s", command)

        try:
            exit_code = self._execute(command)
        except FileNotFoundError:
            self._fail(
                f"iperf3 executable not found at {command[0]}. "
                "Reinstall the application or place iperf3 on your PATH."
            )
            return
        except PermissionError as exc:
            self._fail(f"Not permitted to run iperf3: {exc}")
            return
        except OSError as exc:
            self._fail(f"Could not start iperf3: {exc}")
            return
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected failure while running iperf3")
            self._fail(f"Unexpected error: {exc}")
            return

        if self._cancelled:
            self.line_received.emit("Run stopped by user.")
            self.run_finished.emit(EXIT_CODE_CANCELLED)
            return

        if exit_code != 0:
            # iperf3 prints the reason and exits; surface it rather than
            # leaving the user with a bare non-zero status.
            reason = self._last_error or f"iperf3 exited with status {exit_code}"
            hint = hint_for(reason, self._config.port)
            self.run_failed.emit(f"{reason}\n\n{hint}" if hint else reason)

        self.run_finished.emit(exit_code)

    def _execute(self, command: list[str]) -> int:
        """Spawn the process, pump its output, and return its exit code."""
        # encoding is pinned rather than left to the locale so that output is
        # decoded identically regardless of the user's Windows code page, and
        # errors="replace" keeps a stray byte from killing the run.
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags(),
        )

        process = self._process
        try:
            for line in self._iter_output(process):
                self.line_received.emit(line)
                self._dispatch(line)
        finally:
            if process.stdout is not None:
                process.stdout.close()

        return process.wait()

    def _iter_output(self, process: subprocess.Popen[str]) -> Iterator[str]:
        """Yield stripped output lines until the process ends or is cancelled."""
        assert process.stdout is not None
        for raw in process.stdout:
            if self._cancelled:
                return
            line = raw.rstrip("\r\n")
            if line.strip():
                yield line

    def _dispatch(self, line: str) -> None:
        """Parse one line and emit it on the appropriate signal.

        Parsing failures are contained here rather than allowed to escape into
        :meth:`_execute`, where a single malformed row would abort the run.
        """
        error = extract_error(line)
        if error is not None:
            # Remembered rather than raised: iperf3 reports the reason on
            # stdout and then exits, so the exit code alone cannot say why.
            self._last_error = error

        try:
            sample: Sample | None = self._parser.parse_line(line)
        except Exception:  # pragma: no cover - parser is defensive already
            logger.exception("Parser raised on line %r", line)
            return

        if sample is None:
            return
        if sample.is_summary:
            self.summary_ready.emit(sample)
        else:
            self.sample_ready.emit(sample)

    def _fail(self, message: str) -> None:
        logger.error("%s", message)
        self.line_received.emit(f"ERROR: {message}")
        self.run_failed.emit(message)
        self.run_finished.emit(EXIT_CODE_LAUNCH_FAILED)

    # ------------------------------------------------------------- lifecycle

    def stop(self) -> None:
        """Ask the run to end, terminating the child process if necessary.

        Safe to call from the GUI thread while the worker is running, and safe
        to call more than once.
        """
        self._cancelled = True
        process = self._process
        if process is not None:
            terminate_process(process)

    def stop_and_wait(self, timeout_ms: int = 5000) -> bool:
        """Stop the run and block until the thread has actually exited.

        Returns:
            ``True`` if the thread finished within ``timeout_ms``.
        """
        if not self.isRunning():
            return True
        self.stop()
        finished = self.wait(timeout_ms)
        if not finished:
            logger.warning("iperf3 worker did not stop within %d ms", timeout_ms)
        return finished
