# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller — TraderDesk.exe (Windows, fichier unique).

    pyinstaller --noconfirm --clean TraderDesk.spec

Tout est embarqué : dashboard (html/css/js), les 11 SKILL.md, les 11 scripts
Python d'origine et les données de démonstration. Le dossier de travail est
créé dans %APPDATA%\\TraderDesk au premier lancement.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve()
datas = []
for folder in ("traderdesk/web", "traderdesk/skills", "traderdesk/data/seed"):
    base = ROOT / folder
    if not base.exists():
        continue
    for p in base.rglob("*"):
        if p.is_file() and "__pycache__" not in str(p) and not p.name.endswith(".pyc"):
            datas.append((str(p), str(p.parent.relative_to(ROOT))))

a = Analysis(
    ["run.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=["traderdesk.mt5.bridge"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "numpy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="TraderDesk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
