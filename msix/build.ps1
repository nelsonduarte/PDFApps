<#
.SYNOPSIS
    Build a PDFApps .msix package for Microsoft Store / sideload.

.DESCRIPTION
    Reads APP_VERSION from app/constants.py, materialises
    AppxManifest.xml from the template (replaces __VERSION__ and
    __PUBLISHER__), expects the PyInstaller-built PDFApps.exe to
    already exist at dist/PDFApps.exe, and runs makeappx.exe to
    produce dist/PDFApps-<version>.msix.

    For Store submission the resulting MSIX must be uploaded via
    Microsoft Partner Center — Microsoft signs it with their cert.

    For local sideload testing, sign the MSIX with a self-signed cert:
        signtool sign /a /v /fd SHA256 /f cert.pfx /p password \
            dist/PDFApps-<version>.msix
    Then enable "Developer Mode" in Windows Settings and double-click
    the .msix to install.

.PARAMETER Publisher
    The Publisher CN value to embed in the manifest. For Store
    submission, use the CN assigned in Microsoft Partner Center
    (e.g. "CN=ABCDEF12-3456-7890-ABCD-EF1234567890"). For local
    testing with a self-signed cert, match the cert's subject.

.EXAMPLE
    pwsh msix/build.ps1
    pwsh msix/build.ps1 -Publisher "CN=ABCDEF12-3456-7890-ABCD-EF1234567890"
#>
param(
    [string]$Publisher = "CN=PDFApps Sideload Test"
)

$ErrorActionPreference = "Stop"

# Locate makeappx.exe from a Windows 10/11 SDK install.
$makeappx = Get-ChildItem -Path `
    "${env:ProgramFiles(x86)}\Windows Kits\10\bin" `
    -Recurse -Filter makeappx.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "x64" } |
    Sort-Object FullName -Descending |
    Select-Object -First 1
if (-not $makeappx) {
    Write-Error "makeappx.exe not found. Install the Windows 10/11 SDK from https://developer.microsoft.com/windows/downloads/windows-sdk/"
    exit 1
}
Write-Host "Using makeappx: $($makeappx.FullName)"

# Resolve project root (msix/.. relative to this script).
$root = (Resolve-Path "$PSScriptRoot\..").Path

# Read APP_VERSION from constants.py
$constants = Get-Content "$root\app\constants.py" -Raw
if ($constants -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') {
    Write-Error "could not parse APP_VERSION from app/constants.py"
    exit 1
}
$ver = $matches[1]
# MSIX version must be 4 octets x.y.z.0
if ($ver -notmatch '^\d+\.\d+\.\d+$') {
    Write-Error "expected MAJOR.MINOR.PATCH version, got '$ver'"
    exit 1
}
$msixVer = "$ver.0"
Write-Host "App version : $ver  →  MSIX version: $msixVer"
Write-Host "Publisher   : $Publisher"

# Generate visual assets if missing.
$assetsDir = "$PSScriptRoot\Assets"
$missing = @(
    "Square44x44Logo.png", "Square71x71Logo.png", "Square150x150Logo.png",
    "Square310x310Logo.png", "Wide310x150Logo.png",
    "StoreLogo.png", "SplashScreen.png",
    "Square44x44Logo.targetsize-16.png",
    "Square44x44Logo.targetsize-24.png",
    "Square44x44Logo.targetsize-32.png",
    "Square44x44Logo.targetsize-48.png",
    "Square44x44Logo.targetsize-96.png",
    "Square44x44Logo.targetsize-256.png"
) | Where-Object { -not (Test-Path "$assetsDir\$_") }
if ($missing.Count -gt 0) {
    Write-Host "generating $($missing.Count) missing asset(s) via generate_assets.py"
    & py "$PSScriptRoot\generate_assets.py"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "generate_assets.py failed"
        exit 1
    }
}

# Stage layout: one folder with manifest + assets + exe, then pack.
$stage = "$root\dist\msix-stage"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Path $stage | Out-Null
New-Item -ItemType Directory -Path "$stage\Assets" | Out-Null

# Copy assets
Copy-Item "$assetsDir\*.png" "$stage\Assets\"

# Materialise manifest
(Get-Content "$PSScriptRoot\AppxManifest.xml" -Raw) `
    -replace "__VERSION__", $msixVer `
    -replace "__PUBLISHER__", [System.Security.SecurityElement]::Escape($Publisher) |
    Set-Content "$stage\AppxManifest.xml" -Encoding UTF8

# Copy PyInstaller-built PDFApps.exe
$exe = "$root\dist\PDFApps.exe"
if (-not (Test-Path $exe)) {
    Write-Error "$exe not found. Run the PyInstaller build first (see build.yml)."
    exit 1
}
Copy-Item $exe "$stage\PDFApps.exe"

# Generate resources.pri so Windows shell can resolve targetsize-* qualifiers
# for the file type association icon. Without this, .pdf files in Explorer
# show the base 44x44 logo upscaled to 96/128/256, producing a pixelated icon.
$makepri = Join-Path (Split-Path $makeappx.FullName -Parent) "makepri.exe"
if (-not (Test-Path $makepri)) {
    Write-Error "makepri.exe not found next to makeappx.exe at $makepri"
    exit 1
}
Write-Host "Using makepri : $makepri"

$priconfig = Join-Path $stage "priconfig.xml"
& $makepri createconfig /cf $priconfig /dq en-US /o
if ($LASTEXITCODE -ne 0) {
    Write-Error "makepri createconfig failed"
    exit 1
}

$priFile = Join-Path $stage "resources.pri"
Push-Location $stage
try {
    & $makepri new /pr $stage /cf $priconfig /of $priFile /o
    if ($LASTEXITCODE -ne 0) {
        Write-Error "makepri new failed"
        exit 1
    }
}
finally {
    Pop-Location
}

# Defensive: older SDK versions of makepri.exe have been observed to
# return exit code 0 without actually emitting resources.pri. If that
# happens, makeappx pack succeeds but the resulting MSIX is missing
# the resource index and Explorer falls back to upscaling the base
# 44x44 logo — silently regressing the file association icon fix.
if (-not (Test-Path $priFile)) {
    Write-Error "resources.pri was not generated by makepri.exe at $priFile"
    exit 1
}

# Cleanup the temporary config (not needed inside the package)
Remove-Item $priconfig -Force -ErrorAction SilentlyContinue

# Pack
$out = "$root\dist\PDFApps-$ver.msix"
if (Test-Path $out) { Remove-Item $out }
& $makeappx.FullName pack /d $stage /p $out /o
if ($LASTEXITCODE -ne 0) {
    Write-Error "makeappx pack failed"
    exit 1
}

Write-Host ""
Write-Host "[OK] $out"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  Sideload test : signtool sign /a /v /fd SHA256 /f cert.pfx /p PASS '$out'"
Write-Host "  Store submit  : upload via https://partner.microsoft.com/dashboard"
