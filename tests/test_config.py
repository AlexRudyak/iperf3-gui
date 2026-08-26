"""Tests for argument construction and validation."""

from __future__ import annotations

import pytest

from iperf_gui.core.config import (
    ConfigError,
    IperfConfig,
    Protocol,
    Role,
)
from iperf_gui.core.metrics import Direction


class TestArgumentConstruction:
    def test_minimal_client(self):
        assert IperfConfig().to_args() == [
            "-c", "127.0.0.1", "-p", "5201", "-i", "0.5",
        ]

    def test_server_omits_host(self):
        args = IperfConfig(role=Role.SERVER).to_args()
        assert "-s" in args
        assert "-c" not in args

    def test_full_client(self):
        config = IperfConfig(
            host="10.0.0.5",
            port=5202,
            protocol=Protocol.UDP,
            bitrate="100M",
            parallel=4,
            duration=30,
            reverse=True,
            interval=1.0,
        )
        # The transport flag sits inside the client-only block, because an
        # iperf3 server rejects -u/--sctp outright.
        assert config.to_args() == [
            "-c", "10.0.0.5", "-p", "5202", "-i", "1",
            "-u", "-b", "100M", "-P", "4", "-t", "30", "-R",
        ]

    def test_parallel_of_one_is_not_emitted(self):
        assert "-P" not in IperfConfig(parallel=1).to_args()

    def test_whole_second_interval_has_no_trailing_zero(self):
        args = IperfConfig(interval=2.0).to_args()
        assert args[args.index("-i") + 1] == "2"

    def test_user_interval_is_not_duplicated(self):
        args = IperfConfig(extra_args=("-i", "3")).to_args()
        assert args.count("-i") == 1
        assert args[-2:] == ["-i", "3"]

    def test_extra_args_are_appended_last(self):
        args = IperfConfig(extra_args=("-N", "--cport", "5000")).to_args()
        assert args[-3:] == ["-N", "--cport", "5000"]


class TestServerModeSuppressesClientFlags:
    """Client-only switches make iperf3 -s exit with a usage error."""

    def test_client_only_flags_are_dropped(self):
        config = IperfConfig(
            role=Role.SERVER,
            bitrate="10M",
            parallel=8,
            duration=20,
            reverse=True,
            zerocopy=True,
        )
        args = config.to_args()
        for flag in ("-b", "-P", "-t", "-R", "-Z"):
            assert flag not in args

    def test_dropped_flags_are_reported(self):
        config = IperfConfig(role=Role.SERVER, parallel=8, zerocopy=True)
        assert config.suppressed_client_flags() == ["-P", "-Z"]

    def test_client_mode_reports_nothing_suppressed(self):
        assert IperfConfig(parallel=8).suppressed_client_flags() == []

    def test_server_compatible_extras_survive(self):
        config = IperfConfig(role=Role.SERVER, extra_args=("--logfile", "out.txt"))
        assert "--logfile" in config.to_args()

    def test_client_only_extras_are_stripped(self):
        config = IperfConfig(role=Role.SERVER, extra_args=("-M", "1400"))
        assert "-M" not in config.to_args()


class TestValidation:
    @pytest.mark.parametrize(
        "config,fragment",
        [
            (IperfConfig(host=""), "required"),
            (IperfConfig(host="   "), "required"),
            (IperfConfig(port=0), "Port"),
            (IperfConfig(port=70000), "Port"),
            (IperfConfig(parallel=0), "Parallel"),
            (IperfConfig(parallel=500), "Parallel"),
            (IperfConfig(duration=0), "Duration"),
            (IperfConfig(interval=0), "interval"),
            (IperfConfig(bidir=True, reverse=True), "mutually exclusive"),
        ],
    )
    def test_rejected(self, config, fragment):
        problems = config.validate()
        assert problems, "expected a validation problem"
        assert any(fragment in p for p in problems)

    def test_server_does_not_require_a_host(self):
        assert IperfConfig(role=Role.SERVER, host="").validate() == []

    def test_to_args_raises_on_invalid_config(self):
        with pytest.raises(ConfigError):
            IperfConfig(host="").to_args()

    def test_valid_config_reports_no_problems(self):
        assert IperfConfig().validate() == []


class TestExtraArgumentParsing:
    def test_plain_arguments(self):
        assert IperfConfig.parse_extra_args("-N --cport 5000") == ("-N", "--cport", "5000")

    def test_quoted_path_stays_one_argument_with_quotes_removed(self):
        parsed = IperfConfig.parse_extra_args(r'--logfile "C:\my logs\run.txt"')
        assert parsed == ("--logfile", r"C:\my logs\run.txt")

    def test_empty_string(self):
        assert IperfConfig.parse_extra_args("") == ()

    def test_unbalanced_quote_is_rejected(self):
        with pytest.raises(ConfigError):
            IperfConfig.parse_extra_args('--logfile "unterminated')


class TestDirectionDefaults:
    @pytest.mark.parametrize(
        "role,reverse,expected",
        [
            (Role.CLIENT, False, Direction.TX),
            (Role.CLIENT, True, Direction.RX),
            (Role.SERVER, False, Direction.RX),
            (Role.SERVER, True, Direction.TX),
        ],
    )
    def test_default_direction(self, role, reverse, expected):
        config = IperfConfig(role=role, reverse=reverse)
        assert config.default_direction() is expected


class TestImmutability:
    def test_with_overrides_returns_a_copy(self):
        original = IperfConfig()
        modified = original.with_overrides(port=9999)
        assert original.port == 5201
        assert modified.port == 9999

    def test_expects_aggregate_row(self):
        assert not IperfConfig(parallel=1).expects_aggregate_row
        assert IperfConfig(parallel=2).expects_aggregate_row


class TestProtocolSelection:
    """The transport flag must reach the command line -- and only as a client."""

    @pytest.mark.parametrize(
        "protocol,expected_flag",
        [(Protocol.TCP, None), (Protocol.UDP, "-u"), (Protocol.SCTP, "--sctp")],
    )
    def test_client_emits_the_transport_flag(self, protocol, expected_flag):
        args = IperfConfig(protocol=protocol).to_args()
        if expected_flag is None:
            assert "-u" not in args and "--sctp" not in args
        else:
            assert expected_flag in args

    @pytest.mark.parametrize("protocol", [Protocol.UDP, Protocol.SCTP])
    def test_server_never_emits_the_transport_flag(self, protocol):
        """iperf3 -s rejects -u/--sctp: 'some option you are trying to set is client only'."""
        args = IperfConfig(role=Role.SERVER, protocol=protocol).to_args()
        assert "-u" not in args
        assert "--sctp" not in args

    def test_server_reports_the_dropped_transport(self):
        config = IperfConfig(role=Role.SERVER, protocol=Protocol.UDP)
        assert "-u" in config.suppressed_client_flags()

    def test_udp_flag_survives_alongside_other_options(self):
        args = IperfConfig(
            protocol=Protocol.UDP, bitrate="10M", parallel=4, reverse=True
        ).to_args()
        assert "-u" in args


class TestServerExtraArgumentFiltering:
    """Client-only extras must not leak into a server command line."""

    def test_flag_value_pairs_are_removed_together(self):
        """Dropping only the flag left its value as a stray positional argument."""
        args = IperfConfig(role=Role.SERVER, extra_args=("-M", "1400")).to_args()
        assert "-M" not in args
        assert "1400" not in args

    @pytest.mark.parametrize(
        "extra",
        [
            ("--udp",),
            ("--parallel", "4"),
            ("--reverse",),
            ("--set-mss", "1400"),
            ("--cport", "5000"),
            ("--no-delay",),
        ],
    )
    def test_long_option_spellings_are_filtered(self, extra):
        args = IperfConfig(role=Role.SERVER, extra_args=extra).to_args()
        for token in extra:
            assert token not in args

    def test_inline_equals_form_is_filtered(self):
        args = IperfConfig(role=Role.SERVER, extra_args=("--bandwidth=10M",)).to_args()
        assert "--bandwidth=10M" not in args

    def test_inline_equals_does_not_eat_the_next_argument(self):
        args = IperfConfig(
            role=Role.SERVER, extra_args=("--bandwidth=10M", "--logfile", "o.txt")
        ).to_args()
        assert args[-2:] == ["--logfile", "o.txt"]

    def test_server_compatible_extras_are_preserved(self):
        args = IperfConfig(
            role=Role.SERVER, extra_args=("-N", "--logfile", "o.txt", "-P", "4", "-V")
        ).to_args()
        assert "--logfile" in args and "o.txt" in args and "-V" in args
        assert "-N" not in args and "-P" not in args and "4" not in args

    def test_client_mode_filters_nothing(self):
        extra = ("-N", "-P", "4", "--cport", "5000")
        args = IperfConfig(extra_args=extra).to_args()
        assert args[-len(extra):] == list(extra)
