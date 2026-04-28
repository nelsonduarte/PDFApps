# -*- mode: python ; coding: utf-8 -*-


import importlib, os, re
_qa = os.path.dirname(importlib.import_module('qtawesome').__file__)

# Read APP_VERSION from app/constants.py so the macOS bundle stays in sync.
with open('app/constants.py', encoding='utf-8') as _f:
    _m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', _f.read())
_app_version = _m.group(1) if _m else '0.0.0'

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

# macOS .app bundle (ignored on other platforms)
import sys as _sys
if _sys.platform == 'darwin':
    _icon = 'icon.icns' if os.path.isfile('icon.icns') else 'icon.ico'
    app = BUNDLE(
        exe,
        name='PDFApps.app',
        icon=_icon,
        bundle_identifier='com.pdfapps.app',
        version=_app_version,
        info_plist={
            'CFBundleName': 'PDFApps',
            'CFBundleDisplayName': 'PDFApps',
            'CFBundleExecutable': 'PDFApps',
            'CFBundleIdentifier': 'com.pdfapps.app',
            'CFBundleVersion': _app_version,
            'CFBundleShortVersionString': _app_version,
            'LSMinimumSystemVersion': '10.14',
            'NSHighResolutionCapable': True,
            'CFBundleDocumentTypes': [{
                'CFBundleTypeName': 'PDF Document',
                'CFBundleTypeRole': 'Editor',
                'LSItemContentTypes': ['com.adobe.pdf'],
            }],
        },
    )
