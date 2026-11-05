#!/usr/bin/env python3
"""build_exe.py - build mt5trader.exe with PyInstaller, on Windows.

    python build_exe.py              # onefile (dist/mt5trader.exe)
    python build_exe.py --check      # only report what is missing

Needs: Windows, Python 3.8+, `pip install pyinstaller MetaTrader5`.
PyInstaller cannot cross-compile: run this on Windows, or let the GitHub
Actions workflow (.github/workflows/build-exe.yml) build it for you.
"""

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "mt5trader.spec")
EXE = os.path.join(HERE, "dist", "mt5trader.exe")


def module_ok(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


def report():
    print("python      : %s (%s)" % (sys.version.split()[0], "64-bit" if sys.maxsize > 2**32 else "32-bit"))
    print("platform    : %s" % sys.platform)
    print("pyinstaller : %s" % ("ok" if module_ok("PyInstaller") else "MISSING -> pip install pyinstaller"))
    print("MetaTrader5 : %s" % ("ok" if module_ok("MetaTrader5") else "MISSING -> pip install MetaTrader5 (Windows)"))
    print("spec        : %s" % ("ok" if os.path.isfile(SPEC) else "MISSING"))
    for folder in ("mt5-core", "mt5-broker", "mt5-app"):
        path = os.path.join(os.path.dirname(HERE), folder)
        print("%-11s : %s" % (folder, "ok" if os.path.isdir(path) else "MISSING"))
    if not sys.platform.startswith("win"):
        print("\n!! machi Windows / not Windows: PyInstaller ma kay-cross-compilich.")
        print("   khdem f Windows wla khelli GitHub Actions ybniha (BUILD-EXE.md).")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build mt5trader.exe")
    ap.add_argument("--check", action="store_true", help="report only, build nothing")
    ap.add_argument("--no-clean", action="store_true")
    a = ap.parse_args(argv)

    report()
    if a.check:
        return 0
    if not sys.platform.startswith("win"):
        print("\nBLOCKED: build on Windows (or push and let Actions do it).")
        return 2
    if not module_ok("PyInstaller"):
        print("\ninstalling pyinstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    if not module_ok("MetaTrader5"):
        print("\ninstalling MetaTrader5 (needed inside the exe)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "MetaTrader5"])

    cmd = [sys.executable, "-m", "PyInstaller", SPEC, "--noconfirm"]
    if not a.no_clean:
        cmd.append("--clean")
    print("\n%s\n" % " ".join(cmd))
    code = subprocess.call(cmd, cwd=HERE)
    if code != 0:
        print("\nBUILD FAILED (exit %d) - chouf l'log f %s/build/mt5trader/warn-mt5trader.txt"
              % (code, HERE))
        return code
    if os.path.isfile(EXE):
        size = os.path.getsize(EXE) / (1024.0 * 1024.0)
        print("\nOK: %s  (%.1f MB)" % (EXE, size))
        print("Jarreb:  cd %s && dist\\mt5trader.exe help" % HERE)
        return 0
    print("\nPyInstaller tle3 b 0 walakin ma l9itch l'exe. Chouf dist/.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
