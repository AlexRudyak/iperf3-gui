# Third-Party Notices

This application depends on the following third-party components, and bundles
some of them into its distributable build. This file is informational; it is
not legal advice, and the upstream licence texts are authoritative.

> **The binaries below are not tracked in this repository.** They are supplied
> separately by whoever builds or runs the app (see "Getting iperf3" in the
> README). The obligations here apply when you **distribute a built executable**
> that bundles them, not to the source repository itself.

## Binaries bundled into a Windows build

### iperf3

- **File:** `iperf3.exe` (whichever build you supply; 3.1.3 was used in development)
- **Upstream:** https://github.com/esnet/iperf
- **Licence:** BSD 3-Clause, © University of California, Lawrence Berkeley
  National Laboratory
- **Obligation:** the copyright notice and licence text must accompany
  redistributions.

### Cygwin runtime

- **Files:** `cygwin1.dll`, and for OpenSSL-enabled builds also
  `cygcrypto-*.dll` and `cygz.dll`. The Cygwin build of iperf 3.1.3 links only
  against `cygwin1.dll`.
- **Upstream:** https://cygwin.com/
- **Licence:** `cygwin1.dll` is distributed under the GNU LGPL v3.
  `cygcrypto-3.dll` derives from OpenSSL (Apache 2.0); `cygz.dll` derives from
  zlib (zlib licence).
- **Obligation:** the LGPL requires that recipients be able to relink the
  application against a modified version of the library, and that the licence
  text and corresponding source be made available.

> **Note on redistribution.** A Cygwin `iperf3.exe` build is why the Cygwin
> DLLs are needed at all; a native (MinGW/MSVC) build needs none of them. If you
> intend to publish builds of this application, review the LGPL obligations
> above. Two approaches avoid them entirely: bundle a native `iperf3` build, or
> ship no binary at all and require one on the user's `PATH`.

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
