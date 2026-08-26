"""Tests for iperf3 feature detection.

The help text below is trimmed from the real output of the two builds that
matter: the bundled Cygwin iperf 3.1.3, which has neither ``--bidir`` nor
``--sctp``, and a current build that has both.
"""

from __future__ import annotations

import pytest

from iperf_gui.core import capabilities
from iperf_gui.core.capabilities import (
    CapabilityProbeError,
    IperfCapabilities,
    probe,
)

HELP_313 = """Usage: iperf [-s|-c host] [options]
  -p, --port      #         server port to listen on/connect to
  -i, --interval  #         seconds between periodic bandwidth reports
  -u, --udp                 use UDP rather than TCP
  -b, --bandwidth #[KMG]    target bandwidth in bits/sec
  -P, --parallel  #         number of parallel client streams to run
  -R, --reverse             run in reverse mode
  -M, --set-mss   #         set TCP/SCTP maximum segment size
  -Z, --zerocopy            use a 'zero copy' method of sending data
"""

HELP_MODERN = HELP_313 + """  --bidir                   run in bidirectional mode
  --sctp                    use SCTP rather than TCP
  --dont-fragment           set IPv4 Don't Fragment bit
"""

VERSION_313 = "iperf 3.1.3\nCYGWIN_NT-10.0 HOST 2.5.1(0.297/5/3) 2016-04-21 x86_64\n"
VERSION_MODERN = "iperf 3.17.1 (cJSON 1.7.15)\nLinux host 6.5.0\n"


@pytest.fixture
def fake_iperf(monkeypatch):
    """Patch the probe's subprocess call with canned output."""

    def install(version_output, help_output):
        def fake_run(executable, arg):
            return version_output if arg == "--version" else help_output

        monkeypatch.setattr(capabilities, "_run", fake_run)

    return install


class TestVersionParsing:
    def test_three_part_version(self, fake_iperf):
        fake_iperf(VERSION_313, HELP_313)
        caps = probe("iperf3")
        assert caps.version == (3, 1, 3)
        assert caps.version_string == "3.1.3"
        assert caps.version_banner == "iperf 3.1.3"

    def test_version_with_trailing_metadata(self, fake_iperf):
        fake_iperf(VERSION_MODERN, HELP_MODERN)
        assert probe("iperf3").version == (3, 17, 1)

    def test_unparseable_version_degrades_gracefully(self, fake_iperf):
        fake_iperf("something unexpected\n", HELP_313)
        assert probe("iperf3").version == (0, 0, 0)

    def test_requires_at_least(self, fake_iperf):
        fake_iperf(VERSION_313, HELP_313)
        caps = probe("iperf3")
        assert caps.requires_at_least(3, 1)
        assert not caps.requires_at_least(3, 7)


class TestFeatureDetection:
    def test_bundled_build_lacks_bidir_and_sctp(self, fake_iperf):
        fake_iperf(VERSION_313, HELP_313)
        caps = probe("iperf3")
        assert not caps.supports("--bidir")
        assert not caps.supports("--sctp")
        assert caps.supports("-Z")
        assert caps.supports("-u")

    def test_modern_build_has_them(self, fake_iperf):
        fake_iperf(VERSION_MODERN, HELP_MODERN)
        caps = probe("iperf3")
        assert caps.supports("--bidir")
        assert caps.supports("--sctp")

    def test_describe_missing_lists_only_unsupported(self, fake_iperf):
        fake_iperf(VERSION_313, HELP_313)
        caps = probe("iperf3")
        notes = caps.describe_missing(
            {"--bidir": "Bidirectional", "--sctp": "SCTP", "-Z": "Zero-Copy"}
        )
        assert len(notes) == 2
        assert all("Zero-Copy" not in note for note in notes)
        assert all("3.1.3" in note for note in notes)


class TestProbeFailures:
    def test_missing_binary_raises(self, monkeypatch):
        def boom(executable, arg):
            raise FileNotFoundError(executable)

        monkeypatch.setattr(capabilities, "_run", boom)
        with pytest.raises(CapabilityProbeError, match="not found"):
            probe("nowhere/iperf3")

    def test_os_error_raises(self, monkeypatch):
        def boom(executable, arg):
            raise OSError("permission denied")

        monkeypatch.setattr(capabilities, "_run", boom)
        with pytest.raises(CapabilityProbeError, match="Could not run"):
            probe("iperf3")


class TestRealBundledBinary:
    """Exercises the actual binary shipped with the app, if it is present."""

    def test_probe_succeeds_and_reports_a_version(self):
        try:
            caps = probe()
        except CapabilityProbeError:
            pytest.skip("no iperf3 binary available in this environment")
        assert isinstance(caps, IperfCapabilities)
        assert caps.version >= (3, 0, 0)
        assert caps.flags, "expected at least one flag from --help"
