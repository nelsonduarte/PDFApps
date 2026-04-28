Name:           pdfapps
Version:        1.13.3
Release:        1%{?dist}
Summary:        Fast, offline, subscription-free PDF editor

License:        MIT
URL:            https://nelsonduarte.github.io/PDFApps/
Source0:        https://github.com/nelsonduarte/PDFApps/archive/refs/tags/v%{version}.tar.gz#/PDFApps-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib

Requires:       python3
Requires:       python3-pip
Requires:       python3-pyside6
Requires:       python3-pypdf
Requires:       python3-pymupdf
Requires:       python3-pillow
Requires:       python3-cryptography
Requires:       hicolor-icon-theme

# OCR/compression engines
Recommends:     tesseract
Recommends:     tesseract-langpack-eng
Recommends:     tesseract-langpack-por
Recommends:     ghostscript

%description
PDFApps is an all-in-one PDF editor with 13 built-in tools: split, merge,
rotate, extract, reorder, compress, encrypt, watermark, OCR, convert,
visual editor, import, and metadata viewer. 100%% offline, no subscriptions.

%prep
%autosetup -n PDFApps-%{version}

%build
# Pure Python — no compilation needed

%install
# App package
install -d %{buildroot}%{_datadir}/%{name}
cp -r app pdfapps.py %{buildroot}%{_datadir}/%{name}/
cp icon.ico icon_512.png pdfapps.svg %{buildroot}%{_datadir}/%{name}/

# Launcher script — installs missing pip deps on first run
install -d %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/%{name} <<'EOF'
#!/bin/sh
# Auto-install Python deps not packaged for Fedora (qtawesome, python-docx)
if ! python3 -c "import qtawesome" 2>/dev/null; then
    python3 -m pip install --user --quiet qtawesome python-docx pytesseract 2>/dev/null || true
fi
cd /usr/share/pdfapps
exec python3 pdfapps.py "$@"
EOF
chmod +x %{buildroot}%{_bindir}/%{name}

# Desktop file
install -d %{buildroot}%{_datadir}/applications
cat > %{buildroot}%{_datadir}/applications/io.github.nelsonduarte.PDFApps.desktop <<EOF
[Desktop Entry]
Name=PDFApps
GenericName=PDF Editor
Comment=Fast, offline, subscription-free PDF editor
Exec=%{name} %F
Icon=io.github.nelsonduarte.PDFApps
Terminal=false
Type=Application
Categories=Office;Viewer;
MimeType=application/pdf;
Keywords=PDF;Editor;Viewer;Split;Merge;OCR;Compress;
StartupNotify=true
StartupWMClass=PDFApps
EOF

desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.nelsonduarte.PDFApps.desktop

# Icons
install -Dm644 icon_512.png \
  %{buildroot}%{_datadir}/icons/hicolor/512x512/apps/io.github.nelsonduarte.PDFApps.png
install -Dm644 pdfapps.svg \
  %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.nelsonduarte.PDFApps.svg

# License
install -Dm644 LICENSE %{buildroot}%{_datadir}/licenses/%{name}/LICENSE

%files
%license LICENSE
%{_bindir}/%{name}
%{_datadir}/%{name}/
%{_datadir}/applications/io.github.nelsonduarte.PDFApps.desktop
%{_datadir}/icons/hicolor/512x512/apps/io.github.nelsonduarte.PDFApps.png
%{_datadir}/icons/hicolor/scalable/apps/io.github.nelsonduarte.PDFApps.svg

%changelog
* Tue Apr 07 2026 Nelson Duarte <nelson@example.com> - 1.9.0-1
- Add bookmarks/TOC panel
- Add night reading mode (invert PDF colors)
- Show release notes in update dialog

* Mon Apr 06 2026 Nelson Duarte <nelson@example.com> - 1.8.3-1
- Initial Copr release
