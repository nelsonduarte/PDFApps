# AppImage

This directory contains files for building PDFApps as a portable AppImage that runs on any Linux distribution without installation.

## Files

- `build.sh` — Build script (run on Ubuntu 22.04 for max glibc compatibility)
- `AppRun` — Launcher script embedded in the AppImage

## Local build (Ubuntu 22.04 recommended)

```bash
# Install build dependencies
sudo apt update
sudo apt install -y python3 python3-venv python3-pip wget file libfuse2

# From the project root
chmod +x appimage/build.sh
./appimage/build.sh
```

Result: `PDFApps-1.8.3-x86_64.AppImage` (~150-200 MB).

## Why Ubuntu 22.04?

AppImage uses the **oldest glibc** available on the build machine. Building on Ubuntu 22.04 (glibc 2.35) means the AppImage runs on:
- Ubuntu 22.04+
- Debian 12+
- Fedora 37+
- openSUSE Leap 15.5+
- Arch / Manjaro / EndeavourOS (always recent)

Building on Fedora 41 would require glibc 2.40 — too new for many users.

## Distribution

AppImages don't go through any store. Distribute directly via:

- **GitHub Releases** — upload `PDFApps-1.8.3-x86_64.AppImage` as a release asset
- **AppImageHub** — optional listing at https://www.appimagehub.com/

Users download once and run:

```bash
chmod +x PDFApps-1.8.3-x86_64.AppImage
./PDFApps-1.8.3-x86_64.AppImage
```

## Optional: Auto-update

AppImage supports updates via `zsync`. To enable:

1. Embed update info in the AppImage with `--updateinformation`:
   ```bash
   ARCH=x86_64 ./appimagetool --updateinformation \
     "gh-releases-zsync|nelsonduarte|PDFApps|latest|PDFApps-*-x86_64.AppImage.zsync" \
     AppDir PDFApps-1.8.3-x86_64.AppImage
   ```

2. The AppImage gains a built-in updater that checks GitHub releases.

3. Users update with:
   ```bash
   ./PDFApps-1.8.3-x86_64.AppImage --appimage-update
   ```

## Notes

- **Tesseract / Ghostscript** are NOT bundled — they must be installed via the host distro's package manager. The OCR and compression tools will show clear errors if they're missing.
- **PySide6** is bundled inside the AppImage's venv, so no Qt dependency on the host.
- **Tests**: Test the AppImage on at least Ubuntu 22.04, Fedora 40, and Debian 12 before publishing.
