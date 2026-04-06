# Fedora RPM (Copr)

This directory contains the RPM spec file for building PDFApps as a Fedora package via [Copr](https://copr.fedorainfracloud.org/).

## Files

- `pdfapps.spec` — RPM spec file

## Local build (for testing)

```bash
# Install build tools
sudo dnf install rpm-build rpmdevtools

# Setup rpmbuild tree
rpmdev-setuptree

# Download the source tarball
spectool -g -R rpm/pdfapps.spec

# Build the SRPM (source RPM)
rpmbuild -bs rpm/pdfapps.spec

# Build the binary RPM (will install build dependencies if missing)
sudo dnf builddep rpm/pdfapps.spec
rpmbuild -bb rpm/pdfapps.spec

# Install
sudo dnf install ~/rpmbuild/RPMS/noarch/pdfapps-1.8.3-1.fc*.noarch.rpm

# Run
pdfapps
```

## Publishing on Copr

1. **Create a Copr account** at https://copr.fedorainfracloud.org/ (uses Fedora Account System)

2. **Create a new project**:
   - Project name: `pdfapps`
   - Description: `Fast, offline, subscription-free PDF editor`
   - Chroots: select `fedora-40-x86_64`, `fedora-41-x86_64`, `fedora-42-x86_64`, `fedora-rawhide-x86_64`

3. **Submit the build** (one of these options):

   **Option A — Upload SRPM via web UI:**
   - Build the SRPM locally: `rpmbuild -bs rpm/pdfapps.spec`
   - Upload `~/rpmbuild/SRPMS/pdfapps-1.8.3-1.*.src.rpm` to Copr

   **Option B — SCM build (Copr clones the repo):**
   - In the Copr project, click "New Build" → "SCM"
   - Type: `git`
   - Clone URL: `https://github.com/nelsonduarte/PDFApps.git`
   - Subdirectory: `rpm`
   - Spec file: `pdfapps.spec`
   - Click Build

   **Option C — `copr-cli` (command line):**
   ```bash
   sudo dnf install copr-cli
   copr-cli login  # follow instructions to set up token
   copr-cli build pdfapps ~/rpmbuild/SRPMS/pdfapps-1.8.3-1.*.src.rpm
   ```

4. **Wait for the build** (usually 5-15 minutes per chroot)

5. **Test the repository** on a clean Fedora install:
   ```bash
   sudo dnf copr enable nelsonduarte/pdfapps
   sudo dnf install pdfapps
   pdfapps
   ```

## Updates

For each new release:

1. Bump `Version:` in the spec file
2. Add a `%changelog` entry at the top
3. Either re-upload the SRPM or trigger a new SCM build in Copr

You can automate this with a GitHub Actions workflow that triggers Copr builds on every release tag.

## Notes

- **Auto-updater is NOT disabled** in the RPM build because Copr/dnf manage updates the standard way (no need to detect a sandbox env var like Flatpak/Snap)
- **Tesseract and Ghostscript** are listed as `Recommends:` (soft dependency) so they install by default but users can opt out
- **Python deps** are listed as `Requires:` and installed from Fedora's official repos (`python3-pyside6`, `python3-pypdf`, etc.)
- **Architecture**: `noarch` because PDFApps is pure Python — the same RPM works on x86_64, aarch64, and any other arch
