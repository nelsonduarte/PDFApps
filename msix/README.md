# MSIX packaging — Microsoft Store

This folder contains everything needed to build a `PDFApps.msix`
package for sideload testing or Microsoft Store submission.

## Files

- `AppxManifest.xml` — package manifest template (`__VERSION__` and
  `__PUBLISHER__` are replaced at build time).
- `generate_assets.py` — Pillow script that derives the seven required
  visual assets (Square44/71/150/310, Wide310x150, StoreLogo,
  SplashScreen) from `icon_512.png`. Run once; assets are committed
  back so CI doesn't need Pillow.
- `build.ps1` — PowerShell build that materialises the manifest,
  stages the package, and runs `makeappx pack` to produce
  `dist/PDFApps-<version>.msix`.
- `Assets/` — generated PNG assets.

## Local sideload test

Requires:
- **Windows 10 1809** or newer with **Developer Mode** enabled
  (Settings → Update & Security → For developers → Developer Mode).
- **Windows 10/11 SDK** installed (provides `makeappx.exe` and
  `signtool.exe`).
- Existing `dist\PDFApps.exe` from a PyInstaller build.

```powershell
# 1. Build the MSIX (uses a placeholder "CN=PDFApps Sideload Test")
pwsh msix/build.ps1

# 2. Create + trust a self-signed cert (one-time; password=password)
$cert = New-SelfSignedCertificate -Type Custom `
    -Subject "CN=PDFApps Sideload Test" -KeyUsage DigitalSignature `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3","2.5.29.19={text}")
$pwd = ConvertTo-SecureString "password" -AsPlainText -Force
Export-PfxCertificate -cert $cert -FilePath cert.pfx -Password $pwd
Import-PfxCertificate -FilePath cert.pfx `
    -CertStoreLocation Cert:\LocalMachine\TrustedPeople -Password $pwd

# 3. Sign the MSIX
$sdk = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe |
    Where-Object { $_.FullName -match "x64" } | Sort-Object FullName -Desc | Select -First 1
& $sdk.FullName sign /a /v /fd SHA256 /f cert.pfx /p password "dist\PDFApps-1.13.8.msix"

# 4. Install — double-click the .msix in Explorer, or:
Add-AppxPackage -Path "dist\PDFApps-1.13.8.msix"
```

## Microsoft Store submission

1. Reserve the name `PDFApps` (or whatever) at
   <https://partner.microsoft.com/dashboard>. Microsoft assigns you
   a Publisher Identity like `CN=ABCDEF12-...-EF1234567890`.

2. Build with that Publisher value:
   ```powershell
   pwsh msix/build.ps1 -Publisher "CN=<your-microsoft-publisher-id>"
   ```

3. Upload the unsigned MSIX in the Partner Center submission page
   (Microsoft signs it with their own cert).

4. Fill in: screenshots, description (per supported language),
   age rating self-attestation, privacy policy URL
   (<https://pdf-apps.com>), price = free.

5. Submit. Review takes 24–48h typically.

## Implications for the PDFApps codebase

- `app/updater.py` and `app/window.py` already detect Snap/Flatpak/
  AppImage and disable auto-update there. Add MSIX detection — when
  the exe path lives under `WindowsApps`, defer to the Store for
  updates. Done in this PR.

- Tesseract / Ghostscript downloaders in `installer.py` are NOT
  active inside MSIX (the MSIX package ships the bare `PDFApps.exe`,
  not the tkinter installer). Users running the Store version who
  need OCR will have to install Tesseract themselves from the
  system. Consider bundling a stripped Tesseract inside the package
  for v2 if Store users complain.

- File associations are declared inside the manifest (Extensions →
  windows.fileTypeAssociation), not via registry mutations like the
  classic installer does. The manifest registration takes effect on
  install and is removed on uninstall — cleaner than the legacy
  approach.

## Limitations of this first cut

- No Wide tile branding (uses scaled icon — looks generic). A proper
  marketing wide tile would need a 310×150 image with the wordmark.
- No notification badges / live tile updates.
- No `PackageDependency` for Visual C++ runtimes — PyInstaller
  bundles its own, so this should be fine, but worth verifying after
  installing on a clean Windows VM.
