"""Regression test for the release.yml inline bump script.

Confirms the snap/snapcraft.yaml freeze bug (Snap Store stuck at v1.13.9
since the v1.13.10 release) cannot recur: even when app/constants.py has
drifted out of sync with the packaging files, the bump script must still
update every required target or fail loudly.
"""
from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _extract_bump_script() -> str:
    """Pull the inline Python heredoc out of the release workflow."""
    text = RELEASE_YML.read_text(encoding="utf-8")
    match = re.search(
        r"python - <<'PY'\n(.*?)\n          PY",
        text,
        flags=re.DOTALL,
    )
    assert match, "could not locate inline bump script in release.yml"
    body = match.group(1)
    # Strip the leading 10-space YAML indentation.
    return textwrap.dedent(body)


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Mirror the directory layout the bump script writes to."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "constants.py").write_text(
        'APP_VERSION = "1.13.14"\n', encoding="utf-8"
    )
    (tmp_path / "installer.py").write_text(
        'APP_VERSION = "1.13.14"\n', encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.html").write_text(
        '"softwareVersion": "1.13.14"\nv1.13.14\n', encoding="utf-8"
    )
    (tmp_path / "docs" / "changelog.html").write_text("v1.13.14\n", encoding="utf-8")
    (tmp_path / "snap").mkdir()
    # Frozen one minor behind app/constants.py — this is exactly the
    # bug we're guarding against.
    (tmp_path / "snap" / "snapcraft.yaml").write_text(
        "name: pdfapps\nversion: '1.13.9'\n", encoding="utf-8"
    )
    (tmp_path / "rpm").mkdir()
    (tmp_path / "rpm" / "pdfapps.spec").write_text(
        "Name:           pdfapps\nVersion:        1.13.9\n", encoding="utf-8"
    )
    for sub in ("pdfapps", "pdfapps-bin"):
        (tmp_path / "aur" / sub).mkdir(parents=True)
        (tmp_path / "aur" / sub / "PKGBUILD").write_text(
            "pkgver=1.13.9\n", encoding="utf-8"
        )
    (tmp_path / "aur" / "pdfapps" / ".SRCINFO").write_text(
        "pkgname = pdfapps\n\tpkgver = 1.13.9\n\tsource = pdfapps-1.13.9.tar.gz::"
        "https://github.com/x/x/archive/v1.13.9.tar.gz\n",
        encoding="utf-8",
    )
    (tmp_path / "aur" / "pdfapps-bin" / ".SRCINFO").write_text(
        "pkgname = pdfapps-bin\n\tpkgver = 1.13.10\n\tprovides = pdfapps=1.13.10\n"
        "\tsource = pdfapps-1.13.10.tar.gz::https://x/v1.13.10/y.tar.gz\n",
        encoding="utf-8",
    )
    (tmp_path / "winget").mkdir()
    (tmp_path / "winget" / "nelsonduarte.PDFApps.installer.yaml").write_text(
        "PackageVersion: 1.13.9\nInstallerUrl: https://x/v1.13.9/y.exe\n",
        encoding="utf-8",
    )
    (tmp_path / "winget" / "nelsonduarte.PDFApps.locale.en-US.yaml").write_text(
        "PackageVersion: 1.13.9\nReleaseNotesUrl: https://x/v1.13.9\n",
        encoding="utf-8",
    )
    (tmp_path / "winget" / "nelsonduarte.PDFApps.yaml").write_text(
        "PackageVersion: 1.13.9\n", encoding="utf-8"
    )
    (tmp_path / "flatpak").mkdir()
    (tmp_path / "flatpak" / "io.github.nelsonduarte.PDFApps.yml").write_text(
        "    sources:\n      - type: git\n        tag: v1.13.9\n",
        encoding="utf-8",
    )
    return tmp_path


def _run_script(repo: Path, *, old: str, new: str) -> subprocess.CompletedProcess[str]:
    script = _extract_bump_script()
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo,
        env={"OLD": old, "PATH": "", "NEW": new, "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")},
        capture_output=True,
        text=True,
    )


def test_bump_script_updates_snap_even_when_constants_drifted(fake_repo: Path) -> None:
    """The exact failure mode that froze the Snap Store at 1.13.9."""
    result = _run_script(fake_repo, old="1.13.14", new="1.13.15")
    assert result.returncode == 0, f"bump failed:\nstdout={result.stdout}\nstderr={result.stderr}"

    snap = yaml.safe_load((fake_repo / "snap" / "snapcraft.yaml").read_text())
    assert snap["version"] == "1.13.15", (
        "snapcraft.yaml must move to the new version even though "
        "the OLD value from constants.py never appeared in it"
    )


def test_bump_script_updates_all_required_packaging_files(fake_repo: Path) -> None:
    result = _run_script(fake_repo, old="1.13.14", new="1.13.15")
    assert result.returncode == 0, result.stderr

    # Spot-check each ecosystem.
    assert 'APP_VERSION = "1.13.15"' in (fake_repo / "app" / "constants.py").read_text()
    assert "Version:        1.13.15" in (fake_repo / "rpm" / "pdfapps.spec").read_text()
    assert "pkgver=1.13.15" in (fake_repo / "aur" / "pdfapps" / "PKGBUILD").read_text()
    assert "pkgver=1.13.15" in (fake_repo / "aur" / "pdfapps-bin" / "PKGBUILD").read_text()
    assert "PackageVersion: 1.13.15" in (
        fake_repo / "winget" / "nelsonduarte.PDFApps.installer.yaml"
    ).read_text()
    assert "tag: v1.13.15" in (
        fake_repo / "flatpak" / "io.github.nelsonduarte.PDFApps.yml"
    ).read_text()
    # No stale 1.13.9 / 1.13.10 / 1.13.14 references in required files.
    for path in [
        fake_repo / "snap" / "snapcraft.yaml",
        fake_repo / "rpm" / "pdfapps.spec",
        fake_repo / "aur" / "pdfapps" / "PKGBUILD",
        fake_repo / "aur" / "pdfapps-bin" / "PKGBUILD",
        fake_repo / "winget" / "nelsonduarte.PDFApps.installer.yaml",
        fake_repo / "flatpak" / "io.github.nelsonduarte.PDFApps.yml",
    ]:
        body = path.read_text()
        assert "1.13.9" not in body, f"{path.name} still references 1.13.9"
        assert "1.13.10" not in body, f"{path.name} still references 1.13.10"
        assert "1.13.14" not in body, f"{path.name} still references 1.13.14"


def test_bump_script_is_idempotent(fake_repo: Path) -> None:
    """Running the bump twice with the same NEW must not fail."""
    first = _run_script(fake_repo, old="1.13.14", new="1.13.15")
    assert first.returncode == 0, first.stderr
    second = _run_script(fake_repo, old="1.13.15", new="1.13.15")
    assert second.returncode == 0, (
        f"second bump should be a no-op, got: {second.stdout}\n{second.stderr}"
    )


def test_current_snapcraft_yaml_is_at_release_version() -> None:
    """Belt-and-braces guard against re-introducing the freeze."""
    constants = (REPO_ROOT / "app" / "constants.py").read_text(encoding="utf-8")
    match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', constants)
    assert match, "APP_VERSION not found in app/constants.py"
    app_version = match.group(1)

    snap = yaml.safe_load((REPO_ROOT / "snap" / "snapcraft.yaml").read_text())
    assert snap["version"] == app_version, (
        f"snap/snapcraft.yaml version ({snap['version']!r}) is out of sync "
        f"with app/constants.py ({app_version!r}) — Snap Store will freeze"
    )
