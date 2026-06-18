# -*- mode: python ; coding: utf-8 -*-


import importlib, os, re, sys as _sys
_qa = os.path.dirname(importlib.import_module('qtawesome').__file__)

# Read APP_VERSION from app/constants.py so the macOS bundle stays in sync.
with open('app/constants.py', encoding='utf-8') as _f:
    _m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', _f.read())
_app_version = _m.group(1) if _m else '0.0.0'

# R11-L5: regenerate version_info.txt with APP_VERSION on each build so
# the Windows PE header stays in sync. PyInstaller picks it up via the
# ``version=`` kwarg on EXE(). Helps mitigate AV false positives that
# flag PyInstaller binaries lacking a version-info resource.
_vparts = _app_version.split('.')
while len(_vparts) < 4:
    _vparts.append('0')
_vtuple = ', '.join(_vparts[:4])
with open('version_info.txt', 'w', encoding='utf-8') as _vf:
    _vf.write(
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers=({_vtuple}),\n"
        f"    prodvers=({_vtuple}),\n"
        "    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,\n"
        "    subtype=0x0, date=(0, 0),\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable('040904B0', [\n"
        "        StringStruct('CompanyName', 'PDFApps'),\n"
        "        StringStruct('FileDescription', 'PDFApps - PDF Editor'),\n"
        f"        StringStruct('FileVersion', '{_app_version}'),\n"
        "        StringStruct('InternalName', 'PDFApps'),\n"
        "        StringStruct('LegalCopyright', 'Copyright (c) 2025-2026 PDFApps'),\n"
        "        StringStruct('OriginalFilename', 'PDFApps.exe'),\n"
        "        StringStruct('ProductName', 'PDFApps'),\n"
        f"        StringStruct('ProductVersion', '{_app_version}'),\n"
        "      ])\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])])\n"
        "  ]\n"
        ")\n"
    )

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
    # R11-L5: stamp PE version-info on Windows builds (no-op elsewhere).
    version='version_info.txt' if _sys.platform == 'win32' else None,
)

# macOS .app bundle (ignored on other platforms)
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
