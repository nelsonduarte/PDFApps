# AUR (Arch User Repository)

This directory contains PKGBUILDs for publishing PDFApps to the [AUR](https://aur.archlinux.org/).

## Packages

| Package | Type | Size | Build time |
|---|---|---|---|
| `pdfapps` | Source — uses Arch Python packages | ~5 MB | < 1 min |
| `pdfapps-bin` | Binary — bundled PyInstaller exe | ~125 MB | instant |

Users typically install one or the other:

```bash
# Source build (recommended)
yay -S pdfapps

# Binary (faster, larger)
yay -S pdfapps-bin
```

## Local testing (on Arch Linux)

```bash
cd aur/pdfapps
makepkg -si --noconfirm

# Or test the binary version
cd ../pdfapps-bin
makepkg -si --noconfirm
```

This builds and installs the package locally so you can verify it works before publishing.

## Generating .SRCINFO

The AUR requires a `.SRCINFO` file alongside the PKGBUILD:

```bash
cd aur/pdfapps
makepkg --printsrcinfo > .SRCINFO

cd ../pdfapps-bin
makepkg --printsrcinfo > .SRCINFO
```

Run this whenever the PKGBUILD changes.

## Publishing to AUR

1. **Create an AUR account** at https://aur.archlinux.org/register
2. **Add your SSH public key** to your AUR profile (Account → My Account → SSH Public Key)
3. **Clone the empty repo** for your package (AUR auto-creates it on first push):
   ```bash
   git clone ssh://aur@aur.archlinux.org/pdfapps.git aur-pdfapps
   ```
4. **Copy the PKGBUILD and .SRCINFO** into the cloned repo
5. **Commit and push**:
   ```bash
   cd aur-pdfapps
   git add PKGBUILD .SRCINFO
   git commit -m "Initial release 1.8.3"
   git push origin master
   ```
6. Repeat for `pdfapps-bin` in a separate clone (`ssh://aur@aur.archlinux.org/pdfapps-bin.git`)

## Updates

For each new PDFApps release:

1. Bump `pkgver` and reset `pkgrel=1`
2. Update `sha256sums` (use `updpkgsums` to compute automatically)
3. Regenerate `.SRCINFO`: `makepkg --printsrcinfo > .SRCINFO`
4. Commit and push

## Notes

- **`pdfapps` (source)**: depends on `pyside6` from `extra` repo. If a Python dep is missing from official Arch repos, it must be added as a separate AUR dep.
- **`pdfapps-bin`**: bundles everything via PyInstaller, so there are minimal system dependencies. Best for users who don't want to install ~10 Python packages.
- **Architecture**: `pdfapps` is `any` (pure Python), `pdfapps-bin` is `x86_64` only (PyInstaller binary).
- **Auto-updater**: NOT disabled — pacman/yay handle updates the standard way.
