"""Runtime discovery of what the bundled ``iperf3`` binary can actually do.

The feature set of ``iperf3`` varies enormously between builds. ``--bidir``
only exists from 3.7 onwards, and ``--sctp`` is compiled in conditionally, so
it can be absent even from a current release. Offering those controls
unconditionally produces a usage error and a dead test run, so the UI asks this
module what is supported and disables the rest.

Detection is done by scraping ``--help``, which reflects the actual compiled
feature set, rather than by comparing version numbers alone.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache

from ..utils.paths import iperf3_executable
from .process import creation_flags

logger = logging.getLogger(__name__)

#: How long to wait for the probe subprocess before giving up.
PROBE_TIMEOUT_SECONDS = 10

_VERSION_RE = re.compile(r"iperf\s+(\d+)\.(\d+)(?:\.(\d+))?")

#: Matches every long and short option token in an iperf3 help screen.
_FLAG_RE = re.compile(r"(--[a-zA-Z][\w-]*|-[a-zA-Z])")


class CapabilityProbeError(RuntimeError):
    """Raised when the ``iperf3`` binary cannot be executed at all."""


@dataclass(frozen=True)
class IperfCapabilities:
    """The feature set of a specific ``iperf3`` executable."""

    executable: str
    version: tuple[int, int, int]
    version_banner: str
    flags: frozenset[str] = field(default_factory=frozenset)

    def supports(self, flag: str) -> bool:
        """Whether ``flag`` (e.g. ``"--bidir"``) appears in the binary's help."""
        return flag in self.flags

    def requires_at_least(self, major: int, minor: int) -> bool:
        """Whether the binary is at least version ``major.minor``."""
        return self.version[:2] >= (major, minor)

    @property
    def version_string(self) -> str:
        """Dotted version, e.g. ``"3.1.3"``."""
        return ".".join(str(part) for part in self.version)

    def describe_missing(self, wanted: dict[str, str]) -> list[str]:
        """Human-readable notes for each unsupported flag in ``wanted``.

        Args:
            wanted: mapping of flag to the label shown in the UI.
        """
        return [
            f"{label} ({flag}) is not supported by iperf {self.version_string}"
            for flag, label in sorted(wanted.items())
            if not self.supports(flag)
        ]


def _run(executable: str, arg: str) -> str:
    """Run ``executable arg`` and return its combined output.

    ``iperf3`` writes its help to stdout on some builds and stderr on others,
    and exits non-zero for ``--help`` on several versions, so neither the
    stream nor the exit status can be relied upon.
    """
    completed = subprocess.run(
        [executable, arg],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        timeout=PROBE_TIMEOUT_SECONDS,
        creationflags=creation_flags(),
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.stdout or ""


def probe(executable: str | None = None) -> IperfCapabilities:
    """Interrogate an ``iperf3`` binary for its version and supported flags.

    Args:
        executable: path to the binary; defaults to the bundled one.

    Raises:
        CapabilityProbeError: if the binary is missing or will not run.
    """
    path = executable or iperf3_executable()

    try:
        version_output = _run(path, "--version")
        help_output = _run(path, "--help")
    except FileNotFoundError as exc:
        raise CapabilityProbeError(f"iperf3 executable not found at {path}") from exc
    except OSError as exc:
        raise CapabilityProbeError(f"Could not run iperf3 at {path}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CapabilityProbeError(
            f"iperf3 at {path} did not respond within {PROBE_TIMEOUT_SECONDS}s"
        ) from exc

    banner = version_output.strip().splitlines()
    version_banner = banner[0].strip() if banner else "unknown"

    match = _VERSION_RE.search(version_output)
    if match:
        version = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3) or 0),
        )
    else:
        logger.warning("Could not parse iperf3 version from %r", version_banner)
        version = (0, 0, 0)

    flags = frozenset(_FLAG_RE.findall(help_output))

    capabilities = IperfCapabilities(
        executable=path,
        version=version,
        version_banner=version_banner,
        flags=flags,
    )
    logger.info(
        "Detected %s with %d documented flags", version_banner, len(capabilities.flags)
    )
    return capabilities


@lru_cache(maxsize=4)
def cached_probe(executable: str | None = None) -> IperfCapabilities:
    """Memoised :func:`probe`, so startup pays the subprocess cost only once."""
    return probe(executable)
