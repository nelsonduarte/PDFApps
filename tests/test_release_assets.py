"""What build.yml publishes on a GitHub release, and what it must not.

D8 (2026-10-05) retired the AppImage, which never started for anyone, and
the ``.msix`` as a GitHub release asset. The Microsoft Store still needs
the ``.msix``, so build.yml keeps building it and hands it over as a
workflow artifact of its own that the release job does not publish.

The published set must also be exactly what the in-app updater asks for
by name (``app.updater._find_asset``), each with a SHA256 line in the
release body: the updater refuses an asset whose hash is not published.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from app import updater

ROOT = Path(__file__).resolve().parent.parent
BUILD_YML = ROOT / ".github" / "workflows" / "build.yml"


def _workflow() -> dict:
    return yaml.safe_load(BUILD_YML.read_text(encoding="utf-8"))


def _release_step(name: str) -> dict:
    for step in _workflow()["jobs"]["release"]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"release step {name!r} not found")


def _published() -> set[str]:
    files = _release_step("Create Release")["with"]["files"]
    return {Path(line.strip()).name for line in files.splitlines() if line.strip()}


def _checksummed() -> set[str]:
    run = _release_step("Append SHA256 checksums to release notes")["run"]
    loop = run[run.index("for f in"):run.index("; do")]
    return set(re.findall(r"artifacts/[^/\s]+/(\S+)", loop))


def _updater_names() -> set[str]:
    names = set()
    for platform in ("win32", "darwin", "linux"):
        assets = [{"name": n} for n in (
            "PDFAppsSetup.exe", "PDFApps-macOS.dmg", "PDFApps-Linux.tar.gz",
        )]
        with patch.object(sys, "platform", platform):
            found = updater._find_asset({"assets": assets})
        assert found is not None, platform
        names.add(found["name"])
    return names


def test_release_publishes_exactly_what_the_updater_downloads():
    assert _published() == _updater_names() == {
        "PDFAppsSetup.exe", "PDFApps-macOS.dmg", "PDFApps-Linux.tar.gz",
    }


def test_every_published_asset_gets_a_checksum_line():
    assert _checksummed() == _published()


@pytest.mark.parametrize("suffix", [".msix", ".AppImage"])
def test_retired_assets_are_not_published(suffix):
    text = BUILD_YML.read_text(encoding="utf-8")
    release = text[text.index("\n  release:\n"):]
    assert suffix not in release
    assert not [n for n in _published() | _checksummed() if n.endswith(suffix)]


def test_no_appimage_job():
    jobs = _workflow()["jobs"]
    assert set(jobs) == {"build", "release"}, sorted(jobs)
    assert jobs["release"]["needs"] == ["build"]


def test_msix_is_still_built_and_kept_as_a_store_artifact():
    steps = _workflow()["jobs"]["build"]["steps"]
    names = [s.get("name") for s in steps]
    assert "Build MSIX (Windows)" in names
    uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    msix = [s for s in uploads if ".msix" in s["with"]["path"]]
    assert len(msix) == 1, msix
    (store,) = msix
    assert store["if"] == "runner.os == 'Windows'"
    assert store["with"]["name"] == "PDFApps-MSIX-Store"
    assert store["with"].get("if-no-files-found") == "error"
    # The release job reads artifacts/PDFApps-Windows/...; the .msix must
    # not travel in that artifact, or a glob added later would ship it.
    windows = [s for s in uploads if s["with"]["name"] == "${{ matrix.artifact }}"
               and s.get("if") == "runner.os == 'Windows'"]
    assert len(windows) == 1
    assert ".msix" not in windows[0]["with"]["path"]
