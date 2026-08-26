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
- An `iperf3` binary — **not included in this repository**, see
  [Getting iperf3](#getting-iperf3)

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

## Getting iperf3

`iperf3` is a third-party binary with its own licence, so it is deliberately
**not tracked in this repository**. Provide it in either of two ways:

1. **Next to the project** — place `iperf3.exe` (and the DLLs it links against)
   in the repository root. This is what the PyInstaller build bundles.
2. **On your `PATH`** — the app falls back to a `PATH` lookup and logs a
   warning when no local copy is found.

Download a Windows build from
[software.es.net/iperf](https://software.es.net/iperf/) or
[files.budman.pw/files/iperf3](https://files.budman.pw/files/iperf3/), and copy
the `.exe` together with every DLL in the same archive.

If no binary is available the app still starts; it reports the problem in the
console and tests fail until one is provided.

### Version matters

The app probes the binary at startup and disables anything it cannot do, so a
newer `iperf3` unlocks more features with no code change. Against **iperf 3.1.3**
(the Cygwin build this project was originally developed with) the following are
unavailable:

| Feature | Requires | Status on 3.1.3 |
|---|---|---|
| `--bidir` (bidirectional) | iperf3 ≥ 3.7 | Unavailable |
| `--sctp` | an SCTP-enabled build | Unavailable |
| `Retr` (retransmit) column | a build reporting TCP_INFO | Not reported |
| UDP with `-P` > 1 | iperf3 ≥ 3.2 | Hangs; use Stop to cancel |

**Using iperf3 3.17 or newer is recommended** — it enables all of the above.

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
data rows, so the retransmit count is read by position — searching for the word
`Retr` only ever matches the header. Live interval rows are told apart from the
closing summary by three combined signals: a separator followed by a column
header, an explicit `sender`/`receiver` tag, and the interval restarting at
zero. No single signal suffices — the `- - - - -` separator is printed after
*every* interval group once `-P > 1`, and the UDP client summary carries no
tag at all. `[SUM]` rows are filtered against per-stream rows so parallel runs
are not double-counted.

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

No licence has been chosen for this project yet, which means default copyright
applies and others have no granted rights to reuse the code.

Note that PyQt6 is offered under the GPL v3 or a commercial licence, which
constrains what this project can be licensed as. If you distribute a built
executable that bundles `iperf3` and its Cygwin DLLs, review
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) first — the LGPL carries
relinking obligations that the source repository itself does not.
