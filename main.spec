# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition.

This is the single source of truth for the bundle: ``build_exe.bat`` invokes
this spec rather than repeating the options on the command line, so the two
cannot drift apart.

The iperf3 binary is not tracked in this repository; see the "Getting iperf3"
section of README.md. If it is absent the bundle is still built, but the
resulting application will need an ``iperf3`` on the user's PATH.

``_RUNTIME_FILES`` must list every DLL the chosen ``iperf3`` build links
against. The Cygwin build of iperf 3.1.3 needs only ``cygwin1.dll``; a
different build may need more (an OpenSSL-enabled one also wants
``cygcrypto-*.dll`` and ``cygz.dll``), so add them here if you swap the binary.
"""

import os

block_cipher = None

#: Runtime files copied next to the executable inside the bundle.
#: Missing entries are dropped with a warning rather than failing the build,
#: so the spec still works in a checkout that lacks the optional DLLs.
_RUNTIME_FILES = [
    'iperf3.exe',
    'cygwin1.dll',
    # Only required by OpenSSL-enabled iperf3 builds; harmlessly skipped when
    # absent, which is the case for the Cygwin build of 3.1.3.
    'cygcrypto-3.dll',
    'cygz.dll',
]

datas = [
    ('iperf_gui/assets/app_icon.ico', 'assets'),
    ('iperf_gui/assets/style.qss', 'assets'),
]

for _name in _RUNTIME_FILES:
    if os.path.exists(_name):
        datas.append((_name, '.'))
    else:
        print(f'NOTE: {_name} not found; it will not be bundled.')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt ships modules this app never touches; excluding them trims the bundle.
    excludes=[
        'PyQt6.QtQml',
        'PyQt6.QtQuick',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtMultimedia',
        'PyQt6.QtBluetooth',
        'PyQt6.Qt3DCore',
        'tkinter',
        'unittest',
        'pydoc_data',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='iperf-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['iperf_gui/assets/app_icon.ico'],
)
