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
        else:
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
