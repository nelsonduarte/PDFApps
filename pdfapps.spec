# -*- mode: python ; coding: utf-8 -*-


import importlib, os
_qa = os.path.dirname(importlib.import_module('qtawesome').__file__)

a = Analysis(
    ['pdfapps.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icon.ico', '.'),
        ('pdfapps.svg', '.'),
        ('app/translations.json', 'app'),
        (os.path.join(_qa, 'fonts'), 'qtawesome/fonts'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='PDFApps',
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
    icon=['icon.ico'],
)
