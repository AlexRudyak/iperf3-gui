"""Headless GUI tests.

These run against a real ``QApplication`` on Qt's ``offscreen`` platform, so no
display is required. They cover the regressions that were only reachable
through the widgets: a crash on an empty numeric field, and a failed sweep
leaving the controls permanently disabled.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from iperf_gui.core.capabilities import IperfCapabilities  # noqa: E402
from iperf_gui.core.config import Protocol, Role  # noqa: E402
from iperf_gui.core.metrics import (  # noqa: E402
    RESULT_COLUMNS,
    Direction,
    Role as SampleRole,
    Sample,
)
from iperf_gui.ui.dashboard import TelemetryDashboard  # noqa: E402
from iperf_gui.ui.dialogs import ExportDialog  # noqa: E402
from iperf_gui.ui.panels.connection_panel import ConnectionPanel  # noqa: E402
from iperf_gui.ui.panels.options_panel import OptionsPanel  # noqa: E402
from iperf_gui.ui.widgets.console import LogConsole  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


CAPS_OLD = IperfCapabilities(
    executable="iperf3",
    version=(3, 1, 3),
    version_banner="iperf 3.1.3",
    flags=frozenset({"-u", "-Z", "-P", "-R", "-M"}),
)
CAPS_NEW = IperfCapabilities(
    executable="iperf3",
    version=(3, 17, 1),
    version_banner="iperf 3.17.1",
    flags=frozenset({"-u", "-Z", "-P", "-R", "-M", "--bidir", "--sctp"}),
)


class TestConnectionPanel:
    def test_port_is_always_a_usable_integer(self, qapp):
        """A spin box cannot be left empty, unlike the validated line edit it replaced."""
        panel = ConnectionPanel()
        panel.port_spin.clear()
        assert isinstance(panel.port(), int)

    def test_port_is_clamped_to_the_valid_range(self, qapp):
        panel = ConnectionPanel()
        panel.port_spin.setValue(999999)
        assert panel.port() <= 65535

    def test_host_field_disabled_in_server_mode(self, qapp):
        panel = ConnectionPanel()
        panel.role_combo.setCurrentIndex(1)
        assert panel.role() is Role.SERVER
        assert not panel.host_input.isEnabled()


class TestOptionsPanel:
    def test_parallel_streams_never_raises_on_empty_input(self, qapp):
        """int('') on the old QLineEdit crashed Start Test with no visible error."""
        panel = OptionsPanel(CAPS_OLD)
        panel.parallel_spin.clear()
        config = panel.apply_to(_base_config())
        assert config.parallel >= 1

    def test_unsupported_controls_are_disabled(self, qapp):
        panel = OptionsPanel(CAPS_OLD)
        assert not panel.bidir_cb.isEnabled()
        assert panel.zerocopy_cb.isEnabled()

    def test_supported_controls_stay_enabled(self, qapp):
        panel = OptionsPanel(CAPS_NEW)
        assert panel.bidir_cb.isEnabled()

    def test_disabled_feature_never_reaches_the_command_line(self, qapp):
        panel = OptionsPanel(CAPS_OLD)
        panel.bidir_cb.setChecked(True)  # ignored: the control is disabled
        assert not panel.apply_to(_base_config()).bidir

    def test_sctp_entry_is_disabled_when_unsupported(self, qapp):
        panel = OptionsPanel(CAPS_OLD)
        index = panel.protocol_combo.findData(Protocol.SCTP)
        assert not panel.protocol_combo.model().item(index).isEnabled()

    def test_reverse_and_bidir_are_mutually_exclusive(self, qapp):
        panel = OptionsPanel(CAPS_NEW)
        panel.reverse_cb.setChecked(True)
        panel.bidir_cb.setChecked(True)
        assert not panel.reverse_cb.isChecked()

    def test_unsupported_notes_mention_the_version(self, qapp):
        notes = OptionsPanel(CAPS_OLD).unsupported_notes()
        assert notes and all("3.1.3" in note for note in notes)

    def test_duration_zero_means_run_until_stopped(self, qapp):
        panel = OptionsPanel(CAPS_OLD)
        panel.duration_spin.setValue(0)
        assert panel.duration() is None

    def test_bitrate_combines_value_and_unit(self, qapp):
        panel = OptionsPanel(CAPS_OLD)
        panel.rate_input.setText("100")
        panel.rate_unit.setCurrentText("G")
        assert panel.bitrate() == "100G"

    def test_blank_bitrate_is_none(self, qapp):
        assert OptionsPanel(CAPS_OLD).bitrate() is None


class TestDashboard:
    def test_x_axis_uses_reported_timestamps(self, qapp):
        dashboard = TelemetryDashboard()
        for end in (1.0, 2.0, 3.0):
            dashboard.add_sample(_sample(interval_end=end))
        assert list(dashboard._tx.x) == [1.0, 2.0, 3.0]

    def test_non_default_interval_is_honoured(self, qapp):
        """The old code added a hard-coded 0.5s per sample regardless of -i."""
        dashboard = TelemetryDashboard()
        for end in (2.0, 4.0, 6.0):
            dashboard.add_sample(_sample(interval_end=end))
        assert list(dashboard._tx.x) == [2.0, 4.0, 6.0]

    def test_summary_rows_are_not_plotted(self, qapp):
        dashboard = TelemetryDashboard()
        dashboard.add_sample(_sample(interval_end=1.0))
        dashboard.add_sample(
            _sample(interval_end=10.0, is_summary=True, role=SampleRole.RECEIVER)
        )
        assert list(dashboard._tx.x) == [1.0]

    def test_directions_go_to_separate_series(self, qapp):
        dashboard = TelemetryDashboard()
        dashboard.add_sample(_sample(direction=Direction.TX))
        dashboard.add_sample(_sample(direction=Direction.RX))
        assert len(dashboard._tx.x) == 1
        assert len(dashboard._rx.x) == 1

    def test_absent_retransmits_add_no_point(self, qapp):
        dashboard = TelemetryDashboard()
        dashboard.add_sample(_sample(retransmits=None))
        assert len(dashboard._retransmits.x) == 0

    def test_history_is_bounded(self, qapp):
        dashboard = TelemetryDashboard(history=10)
        for index in range(50):
            dashboard.add_sample(_sample(interval_end=float(index)))
        assert len(dashboard._tx.x) == 10

    def test_reset_clears_every_series(self, qapp):
        dashboard = TelemetryDashboard()
        dashboard.add_sample(_sample(retransmits=4, loss_percent=1.0))
        dashboard.reset()
        assert not dashboard._tx.x
        assert not dashboard._retransmits.x
        assert not dashboard._loss.x


class TestLogConsole:
    def test_retention_limit_is_enforced(self, qapp):
        console = LogConsole(max_lines=50)
        for index in range(500):
            console.append_line(f"line {index}")
        assert console.blockCount() <= 50

    def test_last_line_is_kept(self, qapp):
        console = LogConsole(max_lines=10)
        for index in range(100):
            console.append_line(f"line {index}")
        assert "line 99" in console.toPlainText()


class TestExportDialog:
    def test_columns_match_the_shared_definition(self, qapp):
        assert ExportDialog().selected_columns() == list(RESULT_COLUMNS)

    def test_deselecting_everything_disables_export(self, qapp):
        dialog = ExportDialog()
        for box in dialog._checkboxes.values():
            box.setChecked(False)
        assert dialog.selected_columns() == []
        from PyQt6.QtWidgets import QDialogButtonBox

        button = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert not button.isEnabled()


def _base_config():
    from iperf_gui.core.config import IperfConfig

    return IperfConfig()


def _sample(**overrides) -> Sample:
    defaults = dict(
        stream_id="5",
        direction=Direction.TX,
        interval_start=0.0,
        interval_end=1.0,
        bits_per_second=1e9,
    )
    defaults.update(overrides)
    return Sample(**defaults)
