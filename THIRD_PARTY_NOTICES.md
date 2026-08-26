# Third-Party Notices

This application bundles and depends on the following third-party components.
This file is informational; it is not legal advice, and the upstream licence
texts are authoritative.

## Bundled binaries (Windows distribution)

### iperf3

- **File:** `iperf3.exe` (version 3.1.3)
- **Upstream:** https://github.com/esnet/iperf
- **Licence:** BSD 3-Clause, © University of California, Lawrence Berkeley
  National Laboratory
- **Obligation:** the copyright notice and licence text must accompany
  redistributions.

### Cygwin runtime

- **Files:** `cygwin1.dll`, `cygcrypto-3.dll`, `cygz.dll`
- **Upstream:** https://cygwin.com/
- **Licence:** `cygwin1.dll` is distributed under the GNU LGPL v3.
  `cygcrypto-3.dll` derives from OpenSSL (Apache 2.0); `cygz.dll` derives from
  zlib (zlib licence).
- **Obligation:** the LGPL requires that recipients be able to relink the
  application against a modified version of the library, and that the licence
  text and corresponding source be made available.

> **Note on redistribution.** The bundled `iperf3.exe` is a Cygwin build, which
> is why the Cygwin DLLs are required. If you intend to publish builds of this
> application, review the LGPL obligations above. Linking against a native
> (non-Cygwin) `iperf3` build, or shipping without a bundled binary and
> requiring one on `PATH`, avoids them entirely.

## Python dependencies

| Package | Licence | Upstream |
|---|---|---|
| PyQt6 | GPL v3 or Riverbank Commercial | https://www.riverbankcomputing.com/software/pyqt/ |
| Qt 6 (via PyQt6) | LGPL v3 or Qt Commercial | https://www.qt.io/ |
| pyqtgraph | MIT | https://www.pyqtgraph.org/ |
| numpy | BSD 3-Clause | https://numpy.org/ |

> **Note on PyQt6.** PyQt6 is offered under the GPL v3 or a commercial licence.
> Distributing this application under the GPL requires making its source
> available under compatible terms; distributing it under any other terms
> requires a commercial PyQt licence from Riverbank. This constrains the
> licence that can be chosen for the project itself.
