# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition.

This is the single source of truth for the bundle: ``build_exe.bat`` invokes
this spec rather than repeating the options on the command line, so the two
cannot drift apart.

Every Cygwin DLL that ``iperf3.exe`` links against must be listed here. The
previous build shipped only ``cygwin1.dll``, so the bundled binary failed to
start on machines without a Cygwin installation of its own.
"""

import os

block_cipher = None

#: Runtime files copied next to the executable inside the bundle.
#: Missing entries are dropped with a warning rather than failing the build,
#: so the spec still works in a checkout that lacks the optional DLLs.
_RUNTIME_FILES = [
    'iperf3.exe',
    'cygwin1.dll',
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
        print(f'WARNING: {_name} not found; the bundle will be incomplete.')


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
