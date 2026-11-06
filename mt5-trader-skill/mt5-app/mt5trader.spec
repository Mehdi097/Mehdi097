# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for mt5trader.exe.

Build (on Windows, from this folder):

    pip install pyinstaller MetaTrader5
    pyinstaller mt5trader.spec --noconfirm --clean

The result is dist/mt5trader.exe: one file, no Python needed on the target
machine. The MT5 terminal still has to be installed and running, because
MetaTrader5 talks to the terminal, not to the internet.
"""

import os

HERE = os.path.abspath(SPECPATH)
PACK = os.path.abspath(os.path.join(HERE, os.pardir))

FOLDERS = [
    "mt5-core", "mt5-analyst", "mt5-screener", "mt5-copycat", "mt5-budget",
    "mt5-risk", "mt5-broker", "mt5-journal", "mt5-alerts", "mt5-exposure",
    "mt5-calendar", "mt5-news",
]

# every skill folder is data: the runner loads them by path at runtime
datas = []
for folder in FOLDERS:
    source = os.path.join(PACK, folder)
    if os.path.isdir(source):
        datas.append((source, folder))

for doc in ("README.md", "SETUP.md", "PROMPT.md", "BUILD-EXE.md", "LICENSE"):
    path = os.path.join(PACK, doc)
    if os.path.isfile(path):
        datas.append((path, "."))

hiddenimports = []
binaries = []

# MetaTrader5 ships a native core dll; PyInstaller does not always see it
try:
    from PyInstaller.utils.hooks import collect_all

    mt5_datas, mt5_binaries, mt5_hidden = collect_all("MetaTrader5")
    datas += mt5_datas
    binaries += mt5_binaries
    hiddenimports += mt5_hidden
except Exception as exc:  # pragma: no cover - only runs during a build
    print("collect_all(MetaTrader5) failed: %s" % exc)
    hiddenimports.append("MetaTrader5")

hiddenimports += ["MetaTrader5", "numpy"]

a = Analysis(
    [os.path.join(HERE, "runner.py")],
    pathex=[HERE, PACK],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "test", "pytest", "setuptools", "pip",
              "PIL", "matplotlib", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mt5trader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
