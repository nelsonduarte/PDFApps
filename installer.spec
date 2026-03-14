# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['installer.py'],
    binaries=[],
    datas=[
        ('dist/PDFApps.exe',          '.'),
        ('dist/PDFAppsUninstall.exe', '.'),
        ('icon.ico',                  '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['PySide6','pypdf','qtawesome','PIL'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='PDFAppsSetup',
    debug=False, strip=False, upx=True,
    console=False,
    uac_admin=True,
    icon=['icon.ico'],
)
