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
splash = Splash(
    'splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(200, 160),
    text_size=12,
    text_color='#94A3B8',
    text_default='Loading...',
)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, splash, splash.binaries, [],
    name='PDFAppsSetup',
    debug=False, strip=False, upx=True,
    console=False,
    uac_admin=False,
    icon=['icon.ico'],
)
