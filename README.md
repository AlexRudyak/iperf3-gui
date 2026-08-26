# iperf3 Advanced GUI & Sweeper

A desktop front-end for [iperf3](https://iperf.fr/), adding live throughput and
reliability charts plus an automated parameter sweeper that runs a series of
tests across a range of values and exports the results as CSV.

Built with PyQt6 and pyqtgraph.

---

## Features

- **Standard tests** — client or server mode, TCP/UDP/SCTP, target bitrate,
  parallel streams, reverse and bidirectional modes, plus a free-form field for
  any other `iperf3` switch.
- **Live telemetry** — separate outbound and inbound throughput plots and a
  reliability plot showing TCP retransmits and UDP datagram loss. The time axis
  is taken from the intervals `iperf3` reports, so it stays correct at any
  `-i` setting.
- **Parameter sweeps** — step a parameter (`-M`, `-w`, `-l`, `-P`) through a
  linear, exponential or explicit series of values, running one test per value
  with a configurable duration and cooldown. Results appear in a table as each
  iteration completes.
- **CSV export** — choose which columns to write.
- **Capability detection** — the app probes the `iperf3` binary at startup and
  disables any control that binary does not support, instead of offering it and
  failing at run time.

## Requirements

- Python 3.10 or newer
- An `iperf3` binary (one is bundled for Windows; see [Bundled iperf3](#bundled-iperf3))

## Setup

```bash
pip install -r requirements.txt
```

For development and building, install the extra tooling instead:

```bash
pip install -r requirements-dev.txt
```

## Running

```bash
python main.py
```

The app resolves its assets relative to the package, so it can be started from
any working directory.

## Testing

```bash
python -m pytest
```

The suite covers the parsing, configuration, sweep and export logic with no
display required; the GUI tests run on Qt's `offscreen` platform.

## Building a Windows executable

```bash
build_exe.bat
```

This runs the tests, then builds `dist\iperf-gui.exe` from `main.spec`. All
bundle options live in the spec file — the batch script only invokes it.

---

## Bundled iperf3

The Windows build ships `iperf3.exe` together with the Cygwin runtime DLLs it
links against (`cygwin1.dll`, `cygcrypto-3.dll`, `cygz.dll`).

**The bundled binary is iperf 3.1.3, built in 2016.** It does not support:

| Feature | Requires | Status here |
|---|---|---|
| `--bidir` (bidirectional) | iperf3 ≥ 3.7 | Unavailable |
| `--sctp` | an SCTP-enabled build | Unavailable |
| `Retr` (retransmit) column | a build with TCP_INFO | Not reported |
| UDP with `-P` > 1 | iperf3 ≥ 3.2 | Hangs; use Stop to cancel |

The app detects this at startup, disables the affected controls and notes the
reason in the console. **Replacing `iperf3.exe` with a current build from
[software.es.net/iperf](https://software.es.net/iperf/) enables these features
automatically** — no code change is needed, since detection is done by probing
the binary rather than by hard-coding a version.

If no bundled binary is present, the app falls back to any `iperf3` on `PATH`.

---

## Architecture

The codebase is split into a Qt-free domain layer and a presentation layer.
Nothing in `core/` imports from `ui/`, so the entire domain is testable without
a running `QApplication`.

```
main.py                       Entry point: logging, stylesheet, window

iperf_gui/
├── core/                     Domain layer - no Qt widgets
│   ├── config.py             IperfConfig: validation and argument building
│   ├── metrics.py            Sample / IterationResult value objects
│   ├── capabilities.py       Probes the binary for supported features
│   ├── parser.py             iperf3 stdout -> Sample
│   ├── engine.py             IperfWorker: runs one test on a QThread
│   ├── process.py            Cross-platform subprocess helpers
│   ├── export.py             CSV writing
│   └── sweep/
│       ├── engine.py         SweepEngine: sequences iterations
│       └── strategies.py     Linear / Exponential / Explicit value series
│
├── ui/                       Presentation layer
│   ├── main_window.py        Composition and signal wiring only
│   ├── dashboard.py          Throttled pyqtgraph plots
│   ├── fuzzer_tab.py         Sweep configuration, progress and results
│   ├── dialogs.py            CSV column picker
│   ├── panels/               Connection and options panels
│   └── widgets/              Bounded log console, results table
│
└── utils/
    ├── paths.py              Resource resolution (source and frozen builds)
    └── logging_setup.py      Rotating file log + exception hook
```

### Data flow

```
Panels  ──build──▶  IperfConfig  ──to_args()──▶  IperfWorker (QThread)
                                                       │
                                                  iperf3 stdout
                                                       │
                                                  IperfParser
                                                       │
                                      ┌────────────────┴────────────────┐
                                 sample_ready                    summary_ready
                                      │                                │
                              TelemetryDashboard                 SweepEngine
                              (throttled repaint)              (aggregates rows)
```

A sweep wraps the same worker: `SweepEngine` substitutes each value into the
base config, runs one `IperfWorker` per iteration, and aggregates the result
from the closing summary block.

### Design notes

**Configuration is a value object.** `IperfConfig` is an immutable dataclass
that validates itself and knows how to render its own argument vector. The
widgets only read values into it, so the CLI vocabulary has one definition and
can be tested without Qt.

**Parsing is positional and stateful.** `iperf3`'s columns are not labelled on
data rows, so the retransmit count is read by position. The parser tracks the
`- - - - -` separator to tell live interval rows from the closing summary,
and filters `[SUM]` against per-stream rows so parallel-stream runs are not
double-counted.

**Sweep progressions are strategies.** Adding a new progression means adding a
`SweepStrategy` subclass, not another branch in the engine.

**Thread ownership is explicit.** Workers are parented to their owner and
reclaimed via `finished` → `deleteLater`; the window's `closeEvent` stops any
running test and waits for it, so closing the app mid-test cannot destroy a
live `QThread` or orphan an `iperf3` child process.

## Logging

Logs are written to a rotating file in the per-user data directory:

- Windows: `%LOCALAPPDATA%\iperf_gui\iperf_gui.log`
- macOS: `~/Library/Application Support/iperf_gui/iperf_gui.log`
- Linux: `~/.local/share/iperf_gui/iperf_gui.log`

Unhandled exceptions are captured there too, which matters for the windowed
build where there is no console to print to.

## Third-party components

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Licence

No licence has been chosen for this project yet. Note that redistributing the
bundled Cygwin DLLs carries obligations — see the notices file before
publishing a build.
