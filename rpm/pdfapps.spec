Name:           pdfapps
Version:        1.8.3
Release:        1%{?dist}
Summary:        Fast, offline, subscription-free PDF editor

License:        MIT
URL:            https://nelsonduarte.github.io/PDFApps/
Source0:        https://github.com/nelsonduarte/PDFApps/archive/refs/tags/v%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib

Requires:       python3 >= 3.10
Requires:       python3-pyside6
Requires:       python3-pypdf
Requires:       python3-pymupdf
Requires:       python3-pillow
Requires:       python3-pytesseract
Requires:       python3-docx
Requires:       python3-qtawesome
Requires:       hicolor-icon-theme

Recommends:     tesseract
Recommends:     tesseract-langpack-eng
Recommends:     tesseract-langpack-por
Recommends:     tesseract-langpack-spa
Recommends:     tesseract-langpack-fra
Recommends:     tesseract-langpack-deu
Recommends:     ghostscript

%description
PDFApps is an all-in-one PDF editor with 13 built-in tools: split, merge,
rotate, extract, reorder, compress, encrypt, watermark, OCR, convert
(PNG/JPG/DOCX/TXT), visual editor (redact, text, images, signatures,
highlights, notes), import (TXT/images/Markdown), and metadata viewer.

Features include continuous-scroll viewer, presentation mode (F5),
fullscreen (F11), tabbed viewing, dark/light themes, drag and drop,
multi-select PDF open, and 8-language interface.

100%% offline. No subscriptions, no cloud uploads, no account required.

%prep
%autosetup -n PDFApps-%{version}

%build
# Pure Python — no compilation needed

%install
# App package
install -d %{buildroot}%{_datadir}/%{name}
cp -r app pdfapps.py %{buildroot}%{_datadir}/%{name}/
cp icon.ico icon_512.png pdfapps.svg %{buildroot}%{_datadir}/%{name}/

# Launcher script
install -d %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/%{name} <<'EOF'
#!/bin/sh
cd %{_datadir}/pdfapps
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

# AppStream metainfo
install -d %{buildroot}%{_metainfodir}
cp flatpak/io.github.nelsonduarte.PDFApps.metainfo.xml \
   %{buildroot}%{_metainfodir}/

appstream-util validate-relax --nonet \
  %{buildroot}%{_metainfodir}/io.github.nelsonduarte.PDFApps.metainfo.xml

# Icons
install -Dm644 icon_512.png \
  %{buildroot}%{_datadir}/icons/hicolor/512x512/apps/io.github.nelsonduarte.PDFApps.png
install -Dm644 pdfapps.svg \
  %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.nelsonduarte.PDFApps.svg

# License
install -Dm644 LICENSE %{buildroot}%{_datadir}/licenses/%{name}/LICENSE

%files
%license LICENSE
%doc README.md
%{_bindir}/%{name}
%{_datadir}/%{name}/
%{_datadir}/applications/io.github.nelsonduarte.PDFApps.desktop
%{_metainfodir}/io.github.nelsonduarte.PDFApps.metainfo.xml
%{_datadir}/icons/hicolor/512x512/apps/io.github.nelsonduarte.PDFApps.png
%{_datadir}/icons/hicolor/scalable/apps/io.github.nelsonduarte.PDFApps.svg

%changelog
* Mon Apr 06 2026 Nelson Duarte <nelson@example.com> - 1.8.3-1
- Global keyboard shortcuts (Ctrl+O/S/P/W)
- Multi-select PDFs in file dialog and drag and drop
- Canvas adapts to light/dark theme
- Theme-aware dialogs in light mode

* Sun Apr 05 2026 Nelson Duarte <nelson@example.com> - 1.8.2-1
- Digital signature tool (draw, type, or import)
- Continuous scroll editor
- Security hardening
