# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['uninstaller.py'],
    binaries=[],
    datas=[('icon.ico', '.')],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['PySide6','pypdf','qtawesome','PIL'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='PDFAppsUninstall',
    debug=False, strip=False, upx=True,
    console=False,
    icon=['icon.ico'],
)
