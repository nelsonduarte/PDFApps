#!/bin/bash
# Build PDFApps AppImage from the project root
# Run on Ubuntu 22.04 (oldest target glibc)
set -e

VERSION="${VERSION:-1.8.3}"
ARCH="${ARCH:-x86_64}"
APPDIR="$(pwd)/AppDir"
APP_ID="io.github.nelsonduarte.PDFApps"

echo "→ Cleaning previous build"
rm -rf "$APPDIR" PDFApps-*.AppImage

echo "→ Setting up AppDir structure"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/lib"
mkdir -p "$APPDIR/usr/share/pdfapps"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/metainfo"
mkdir -p "$APPDIR/usr/share/icons/hicolor/512x512/apps"
mkdir -p "$APPDIR/usr/share/icons/hicolor/scalable/apps"

echo "→ Copying app files"
cp -r app pdfapps.py icon.ico icon_512.png pdfapps.svg "$APPDIR/usr/share/pdfapps/"

echo "→ Bundling Python + dependencies via pip"
python3 -m venv "$APPDIR/usr"
"$APPDIR/usr/bin/pip" install --no-cache-dir -r requirements.txt
# Remove pyinstaller (only needed for Windows builds)
"$APPDIR/usr/bin/pip" uninstall -y pyinstaller pyinstaller-hooks-contrib || true

echo "→ Installing AppRun launcher"
cp appimage/AppRun "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"

echo "→ Installing desktop file (must be at AppDir root for AppImage)"
cp flatpak/io.github.nelsonduarte.PDFApps.desktop "$APPDIR/$APP_ID.desktop"
cp flatpak/io.github.nelsonduarte.PDFApps.desktop "$APPDIR/usr/share/applications/$APP_ID.desktop"

echo "→ Installing AppStream metainfo"
cp flatpak/io.github.nelsonduarte.PDFApps.metainfo.xml "$APPDIR/usr/share/metainfo/$APP_ID.metainfo.xml"

echo "→ Installing icons"
cp icon_512.png "$APPDIR/$APP_ID.png"
cp icon_512.png "$APPDIR/usr/share/icons/hicolor/512x512/apps/$APP_ID.png"
cp pdfapps.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"

echo "→ Downloading appimagetool"
if [ ! -f appimagetool ]; then
    wget -qO appimagetool \
      "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${ARCH}.AppImage"
    chmod +x appimagetool
fi

echo "→ Building AppImage"
ARCH=$ARCH ./appimagetool --no-appstream "$APPDIR" "PDFApps-${VERSION}-${ARCH}.AppImage"

echo "Done: PDFApps-${VERSION}-${ARCH}.AppImage"
ls -lh "PDFApps-${VERSION}-${ARCH}.AppImage"
