# Snap Store Submission

This directory contains the files needed to publish PDFApps to the [Snap Store](https://snapcraft.io/).

## Files

- `snapcraft.yaml` — Snap build manifest (uses `core22` base + `kde-neon-6` extension)
- `gui/pdfapps.png` — Icon for the snap

## Local build (Linux only)

You need a Linux machine (or WSL Ubuntu) with snapcraft installed:

```bash
# Install snapcraft (Ubuntu/Debian)
sudo snap install snapcraft --classic
sudo snap install lxd
sudo lxd init --auto

# Build (from project root)
snapcraft

# Install locally to test
sudo snap install ./pdfapps_1.8.3_amd64.snap --dangerous

# Run
pdfapps
```

## Publishing to Snap Store

1. **Create a Snapcraft account** at https://snapcraft.io/account (uses Ubuntu One)
2. **Login from CLI**:
   ```bash
   snapcraft login
   ```
3. **Register the snap name** (only the first time):
   ```bash
   snapcraft register pdfapps
   ```
4. **Upload and release**:
   ```bash
   snapcraft upload --release=stable pdfapps_1.8.3_amd64.snap
   ```

The snap will be available immediately at `https://snapcraft.io/pdfapps` and users can install via:
```bash
sudo snap install pdfapps
```

## Channels

Snap Store has 4 risk levels (channels):
- `edge` — bleeding edge, untested
- `beta` — pre-release builds
- `candidate` — release candidates
- `stable` — production

Recommended workflow: push to `edge` first, then promote to `beta` → `candidate` → `stable` after testing.

## Notes

- **Confinement**: `strict` — sandboxed with explicit interface plugs
- **Bundled tools**: Tesseract OCR (5 languages) and Ghostscript are INCLUDED via `stage-packages` (unlike Flatpak)
- **File access**: `home` interface allows opening PDFs from the home directory; `removable-media` for USB drives
- **Auto-updater**: Should be disabled in snap (snap manages its own updates) — TODO: detect via `SNAP` env var
- **Qt6**: Provided by the `kde-neon-6` extension (Qt 6.x runtime)
