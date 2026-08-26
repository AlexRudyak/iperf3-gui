"""Translation of user intent into an ``iperf3`` argument vector.

Keeping this separate from the widget tree means the CLI vocabulary has exactly
one definition, and that definition can be validated and unit tested without
instantiating Qt.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field, replace
from enum import Enum

from .metrics import Direction

MIN_PORT = 1
MAX_PORT = 65535
MAX_PARALLEL_STREAMS = 128
DEFAULT_PORT = 5201
DEFAULT_INTERVAL_SECONDS = 0.5


class Role(Enum):
    """Which side of the iperf3 connection this process will act as."""

    CLIENT = "client"
    SERVER = "server"


class Protocol(Enum):
    """Transport protocol under test.

    ``flag`` is the ``iperf3`` switch that selects it; TCP is the default and
    therefore needs no switch.
    """

    TCP = ("tcp", None)
    UDP = ("udp", "-u")
    SCTP = ("sctp", "--sctp")

    def __init__(self, label: str, flag: str | None) -> None:
        self.label = label
        self.flag = flag


class ConfigError(ValueError):
    """Raised when a configuration cannot be turned into a valid command."""


#: Options iperf3 accepts only in client mode, mapped to whether they consume a
#: following value. Passing any of them to ``iperf3 -s`` aborts startup with
#: "parameter error - some option you are trying to set is client only".
#:
#: ``-u`` and ``--sctp`` are in here because the transport is chosen solely by
#: the client; a server serves whichever transport connects to it.
#:
#: Both spellings of every option are listed. Filtering only the short form let
#: a user's ``--udp`` in the extra-arguments field through untouched.
_CLIENT_ONLY_OPTIONS: dict[str, bool] = {
    "-c": True, "--client": True,
    "-u": False, "--udp": False,
    "--sctp": False,
    "--bidir": False,
    "-b": True, "--bandwidth": True, "--bitrate": True,
    "-t": True, "--time": True,
    "-n": True, "--bytes": True,
    "-k": True, "--blockcount": True,
    "-l": True, "--len": True,
    "--cport": True,
    "-P": True, "--parallel": True,
    "-R": False, "--reverse": False,
    "-w": True, "--window": True,
    "-M": True, "--set-mss": True,
    "-N": False, "--no-delay": False,
    "-4": False, "--version4": False,
    "-6": False, "--version6": False,
    "-Z": False, "--zerocopy": False,
    "-T": True, "--title": True,
    "-C": True, "--congestion": True, "--linux-congestion": True,
    "--get-server-output": False,
}

#: Backwards-compatible view used for membership tests.
_CLIENT_ONLY_FLAGS = frozenset(_CLIENT_ONLY_OPTIONS)


def _strip_client_only(args: tuple[str, ...]) -> list[str]:
    """Remove client-only options, and the values that belong to them.

    Dropping just the flag would leave its value behind as a stray positional
    argument -- ``("-M", "1400")`` became a bare ``1400`` on the server command
    line. Both the ``--flag value`` and ``--flag=value`` spellings are handled.
    """
    kept: list[str] = []
    skip_value = False

    for arg in args:
        if skip_value:
            skip_value = False
            continue

        name, sep, _ = arg.partition("=")
        if name in _CLIENT_ONLY_OPTIONS:
            # An inline "=value" carries its own value, so nothing to skip.
            skip_value = _CLIENT_ONLY_OPTIONS[name] and not sep
            continue

        kept.append(arg)

    return kept


@dataclass(frozen=True)
class IperfConfig:
    """A complete, validated description of one ``iperf3`` invocation."""

    role: Role = Role.CLIENT
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    protocol: Protocol = Protocol.TCP

    #: Target rate including its unit suffix, e.g. "10M". None means unlimited.
    bitrate: str | None = None

    parallel: int = 1
    duration: int | None = None
    reverse: bool = False
    bidir: bool = False
    zerocopy: bool = False
    interval: float = DEFAULT_INTERVAL_SECONDS
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def parse_extra_args(text: str) -> tuple[str, ...]:
        """Split a free-form argument string, honouring shell-style quoting.

        Naive ``str.split()`` would break a quoted Windows path into two
        arguments; :func:`shlex.split` keeps it intact.

        Non-POSIX mode is used so that Windows path separators survive rather
        than being eaten as escape characters, which means the surrounding
        quotes remain in each token and must be stripped by hand -- otherwise
        the quote characters would be passed through to ``iperf3`` verbatim.

        Raises:
            ConfigError: if the string contains an unbalanced quote.
        """
        try:
            tokens = shlex.split(text, posix=False)
        except ValueError as exc:
            raise ConfigError(f"Could not parse extra arguments: {exc}") from exc
        return tuple(_strip_matched_quotes(token) for token in tokens)

    @property
    def expects_aggregate_row(self) -> bool:
        """Whether ``iperf3`` will emit ``[SUM]`` rows for this configuration."""
        return self.parallel > 1

    def default_direction(self) -> Direction:
        """Flow direction to assume for rows that carry no explicit TX/RX tag.

        A client sends unless ``-R`` is given; a server receives unless ``-R`` is
        given. The ``!=`` on two booleans is the exclusive-or expressing that.
        """
        is_client = self.role is Role.CLIENT
        return Direction.TX if (is_client != self.reverse) else Direction.RX

    # ------------------------------------------------------------- validation

    def validate(self) -> list[str]:
        """Return human-readable problems; an empty list means the config is usable."""
        problems: list[str] = []

        if self.role is Role.CLIENT and not self.host.strip():
            problems.append("Target IP/host is required in client mode.")

        if not MIN_PORT <= self.port <= MAX_PORT:
            problems.append(f"Port must be between {MIN_PORT} and {MAX_PORT}.")

        if not 1 <= self.parallel <= MAX_PARALLEL_STREAMS:
            problems.append(
                f"Parallel streams must be between 1 and {MAX_PARALLEL_STREAMS}."
            )

        if self.duration is not None and self.duration < 1:
            problems.append("Duration must be at least 1 second.")

        if self.interval <= 0:
            problems.append("Report interval must be greater than zero.")

        if self.bidir and self.reverse:
            problems.append(
                "Reverse (-R) and Bidirectional (--bidir) are mutually exclusive."
            )

        if self.bitrate is not None and not self.bitrate.strip():
            problems.append("Target rate was set but is empty.")

        return problems

    def suppressed_client_flags(self) -> list[str]:
        """Client-only options that are set but will be dropped in server mode.

        Surfaced as a warning rather than an error so that switching to server
        mode never blocks the user; the options are simply not emitted.
        """
        if self.role is Role.CLIENT:
            return []
        active: set[str] = set()
        if self.protocol.flag:
            active.add(self.protocol.flag)
        if self.bitrate:
            active.add("-b")
        if self.parallel > 1:
            active.add("-P")
        if self.reverse:
            active.add("-R")
        if self.bidir:
            active.add("--bidir")
        if self.zerocopy:
            active.add("-Z")
        if self.duration is not None:
            active.add("-t")
        active.update(
            a.partition("=")[0]
            for a in self.extra_args
            if a.partition("=")[0] in _CLIENT_ONLY_OPTIONS
        )
        return sorted(active)

    def ensure_valid(self) -> None:
        """Raise :class:`ConfigError` if :meth:`validate` reports any problem."""
        problems = self.validate()
        if problems:
            raise ConfigError(" ".join(problems))

    # ------------------------------------------------------------- generation

    def with_overrides(self, **changes: object) -> "IperfConfig":
        """Return a copy with the named fields replaced."""
        return replace(self, **changes)  # type: ignore[arg-type]

    def to_args(self) -> list[str]:
        """Build the ``iperf3`` argument vector, excluding the executable itself.

        Client-only switches are omitted in server mode rather than passed and
        rejected. User-supplied extra arguments are appended last so that they
        win when ``iperf3`` sees a duplicated switch.
        """
        self.ensure_valid()

        args: list[str] = []
        if self.role is Role.CLIENT:
            args += ["-c", self.host.strip()]
        else:
            args.append("-s")

        args += ["-p", str(self.port)]

        # The report interval governs how often measurements arrive and is
        # meaningful on both sides of the connection. It is skipped when the
        # user supplies their own so that iperf3 sees only one.
        if "-i" not in self.extra_args and "--interval" not in self.extra_args:
            args += ["-i", _format_interval(self.interval)]

        if self.role is Role.CLIENT:
            # The transport is chosen by the client only; a server follows
            # whatever the client connects with.
            if self.protocol.flag:
                args.append(self.protocol.flag)
            if self.bitrate:
                args += ["-b", self.bitrate.strip()]
            if self.parallel > 1:
                args += ["-P", str(self.parallel)]
            if self.duration is not None:
                args += ["-t", str(self.duration)]
            if self.reverse:
                args.append("-R")
            if self.bidir:
                args.append("--bidir")
            if self.zerocopy:
                args.append("-Z")
            args.extend(self.extra_args)
        else:
            # Preserve genuinely server-compatible extras such as --logfile,
            # dropping client-only options together with their values.
            args.extend(_strip_client_only(self.extra_args))

        return args


def _format_interval(interval: float) -> str:
    """Render a report interval without a trailing ``.0`` for whole seconds."""
    return f"{interval:g}"


def _strip_matched_quotes(token: str) -> str:
    """Remove one layer of matched surrounding single or double quotes."""
    for quote in ('"', "'"):
        if len(token) >= 2 and token.startswith(quote) and token.endswith(quote):
            return token[1:-1]
    return token
