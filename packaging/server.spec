# -*- mode: python ; coding: utf-8 -*-

# Build from the repository root:
# pyinstaller packaging/server.spec

a = Analysis(
    ["server.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["flask", "waitress", "PIL"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ScreenshotServer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
