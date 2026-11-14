"""Tests for scripts/check_snap_payload.py, the payload check of snap-build.yml.

The listing below is lines of ``unsquashfs -ll`` run on the published
snap 1.15.2 (revision 45, core22), copied verbatim with squashfs-tools
4.7.5 (Ubuntu 26.04) on 2026-11-11, with the Python version turned into a
placeholder so the same payload can stand for another base. The runner's
squashfs-tools may print it differently; the first snap-build.yml run
shows that.

Each check has a case that removes or breaks exactly what it looks for
and expects that check, and only that one, to fail: a check reduced to a
no-op turns its case red.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_snap_payload.py"
MANIFEST = ROOT / "snap" / "snapcraft.yaml"


def _load():
    spec = importlib.util.spec_from_file_location("_check_snap_payload", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


payload = _load()

_REV45 = """\
drwxr-xr-x root/root               176 2026-10-29 12:31 squashfs-root
drwxr-xr-x root/root              1088 2026-10-29 12:31 squashfs-root/bin
lrwxrwxrwx root/root                 7 2026-10-29 12:31 squashfs-root/bin/python -> python3
lrwxrwxrwx root/root                19 2026-10-29 12:31 squashfs-root/bin/python3 -> /usr/bin/python@PY@
lrwxrwxrwx root/root                 7 2026-10-29 12:31 squashfs-root/bin/python@PY@ -> python3
-rw-r--r-- root/root              2808 2022-03-23 13:52 squashfs-root/etc/fonts/fonts.conf
lrwxrwxrwx root/root                31 2022-03-23 13:52 squashfs-root/etc/fonts/conf.d/10-antialias.conf -> ../conf.avail/10-antialias.conf
drwxr-xr-x root/root                57 2026-10-29 12:31 squashfs-root/lib
drwxr-xr-x root/root                36 2026-10-29 12:31 squashfs-root/lib/python@PY@
drwxr-xr-x root/root              1999 2026-10-29 12:31 squashfs-root/lib/python@PY@/site-packages
-rwxr-xr-x root/root             19000 2026-10-29 12:31 squashfs-root/lib/python@PY@/site-packages/PySide6/Qt/plugins/platforms/libqxcb.so
drwxr-xr-x root/root               158 2026-10-29 12:31 squashfs-root/lib/python@PY@/site-packages/pillow-12.3.0.dist-info
drwxr-xr-x root/root               108 2026-10-29 12:31 squashfs-root/lib/python@PY@/site-packages/pypdf-6.21.4.dist-info
-rw-r--r-- root/root               628 2026-10-29 12:31 squashfs-root/lib/python@PY@/site-packages/setuptools/launcher manifest.xml
lrwxrwxrwx root/root                 3 2026-10-29 12:31 squashfs-root/lib64 -> lib
drwxr-xr-x root/root              1076 2026-10-29 12:31 squashfs-root/usr/bin
-rwxr-xr-x root/root             14488 2026-10-29 12:31 squashfs-root/usr/bin/gs
-rwxr-xr-x root/root               350 2026-10-29 12:31 squashfs-root/usr/bin/gsbj
-rwxr-xr-x root/root             35128 2026-10-29 12:31 squashfs-root/usr/bin/tesseract
-rw-r--r-- root/root              6707 2026-10-29 12:31 squashfs-root/usr/lib/pdfapps/pdfapps.py
-rw-r--r-- root/root             44155 2021-08-18 10:26 squashfs-root/usr/share/X11/xkb/rules/evdev
-rw-r--r-- root/root               335 2026-10-29 12:31 squashfs-root/usr/share/applications/io.github.nelsonduarte.PDFApps.desktop
-rw-r--r-- root/root             94625 2026-10-20 17:40 squashfs-root/usr/share/ghostscript/9.55.0/Resource/Init/gs_init.ps
-rw-r--r-- root/root              9244 2026-10-29 12:31 squashfs-root/usr/share/metainfo/io.github.nelsonduarte.PDFApps.metainfo.xml
-rw-r--r-- root/root           1525436 2017-09-15 21:52 squashfs-root/usr/share/tesseract-ocr/4.00/tessdata/deu.traineddata
-rw-r--r-- root/root           4113088 2017-09-15 21:52 squashfs-root/usr/share/tesseract-ocr/4.00/tessdata/eng.traineddata
-rw-r--r-- root/root           1130365 2017-09-15 21:52 squashfs-root/usr/share/tesseract-ocr/4.00/tessdata/fra.traineddata
-rw-r--r-- root/root          10562727 2017-09-15 21:52 squashfs-root/usr/share/tesseract-ocr/4.00/tessdata/osd.traineddata
-rw-r--r-- root/root               572 2022-02-09 04:42 squashfs-root/usr/share/tesseract-ocr/4.00/tessdata/pdf.ttf
-rw-r--r-- root/root           1982756 2017-09-15 21:52 squashfs-root/usr/share/tesseract-ocr/4.00/tessdata/por.traineddata
-rw-r--r-- root/root           2294433 2017-09-15 21:52 squashfs-root/usr/share/tesseract-ocr/4.00/tessdata/spa.traineddata
"""

_QXCB = "lib/python3.10/site-packages/PySide6/Qt/plugins/platforms/libqxcb.so"
_GS_INIT = "usr/share/ghostscript/9.55.0/Resource/Init/gs_init.ps"
_TESSDATA = "usr/share/tesseract-ocr/4.00/tessdata/"


def _listing(py: str = "3.10") -> str:
    return _REV45.replace("@PY@", py)


def _manifest(py: str = "3.10") -> str:
    return "".join(
        f'  {key}: "$SNAP/lib/python{py}/site-packages{rest}"\n'
        for key, rest in (("PYTHONPATH", ":$SNAP/usr/lib/python3/dist-packages"),
                          ("QT_PLUGIN_PATH", "/PySide6/Qt/plugins"),
                          ("QT_QPA_PLATFORM_PLUGIN_PATH", "/PySide6/Qt/plugins/platforms"),
                          ("LD_LIBRARY_PATH", "/PySide6/Qt/lib:$LD_LIBRARY_PATH")))


def _without(path: str, listing: str | None = None) -> str:
    listing = _listing() if listing is None else listing
    suffix = " squashfs-root/" + path
    lines = listing.splitlines(keepends=True)
    kept = [ln for ln in lines
            if not (ln.rstrip("\n").endswith(suffix) or (suffix + " -> ") in ln)]
    assert len(kept) == len(lines) - 1, f"{path} is not exactly one fixture line"
    return "".join(kept)


def _with(listing: str, *lines: str) -> str:
    return listing + "".join(line + "\n" for line in lines)


def _failed(listing: str, py: str = "3.10") -> dict[str, str]:
    failures, _ = payload.check_payload(payload.parse_listing(listing), py)
    return dict(failures)


# ── the complete payload ──


@pytest.mark.parametrize("py", ["3.10", "3.12"])
def test_the_complete_payload_passes(py):
    failures, facts = payload.check_payload(payload.parse_listing(_listing(py)), py)
    assert failures == []
    assert facts["Ghostscript resource version"] == "9.55.0"
    assert facts["tessdata version"] == "4.00"
    assert facts["etc/fonts/fonts.conf"] == "present"


def test_the_listing_is_read_as_unsquashfs_writes_it():
    entries = payload.parse_listing(_listing())
    assert payload.LISTING_ROOT not in entries
    assert entries["bin/python3"] == payload.Entry("l", "/usr/bin/python3.10")
    assert entries["usr/bin/gs"] == payload.Entry("-", None)
    assert entries["lib/python3.10"].kind == "d"
    # A real path with a space, from setuptools.
    assert "lib/python3.10/site-packages/setuptools/launcher manifest.xml" in entries


def test_lines_that_are_not_entries_are_skipped():
    noise = "Parallel unsquashfs: Using 4 processors\n14080 inodes (1 blocks) to write\n\n"
    assert _failed(noise + _listing()) == {}


def test_a_listing_with_no_entry_fails_every_check():
    failed = _failed("Parallel unsquashfs: Using 4 processors\n")
    assert {"listing", "qt-xcb-plugin", "venv-python-link",
            "gs-tesseract-binaries", "ghostscript-init", "tessdata",
            "xkb-data", "desktop-metainfo", "app-entry-point"} <= set(failed)


# ── one case per check ──


@pytest.mark.parametrize(("path", "check", "message"), [
    (_QXCB, "qt-xcb-plugin", "missing " + _QXCB),
    ("bin/python3", "venv-python-link", "bin/python3 must be a symlink to python3.10, it is missing"),
    ("usr/bin/gs", "gs-tesseract-binaries", "missing usr/bin/gs"),
    ("usr/bin/tesseract", "gs-tesseract-binaries", "missing usr/bin/tesseract"),
    (_GS_INIT, "ghostscript-init", "found none"),
    (_TESSDATA + "eng.traineddata", "tessdata", "missing eng.traineddata;"),
    (_TESSDATA + "por.traineddata", "tessdata", "missing por.traineddata;"),
    (_TESSDATA + "spa.traineddata", "tessdata", "missing spa.traineddata;"),
    (_TESSDATA + "fra.traineddata", "tessdata", "missing fra.traineddata;"),
    (_TESSDATA + "deu.traineddata", "tessdata", "missing deu.traineddata;"),
    (_TESSDATA + "pdf.ttf", "tessdata", "missing pdf.ttf;"),
    ("usr/share/X11/xkb/rules/evdev", "xkb-data", "missing usr/share/X11/xkb/rules/evdev"),
    ("usr/share/applications/io.github.nelsonduarte.PDFApps.desktop", "desktop-metainfo",
     "missing usr/share/applications/io.github.nelsonduarte.PDFApps.desktop"),
    ("usr/share/metainfo/io.github.nelsonduarte.PDFApps.metainfo.xml", "desktop-metainfo",
     "missing usr/share/metainfo/io.github.nelsonduarte.PDFApps.metainfo.xml"),
    ("usr/lib/pdfapps/pdfapps.py", "app-entry-point", "missing usr/lib/pdfapps/pdfapps.py"),
])
def test_a_missing_required_path_fails_its_own_check(path, check, message):
    failed = _failed(_without(path))
    assert set(failed) == {check}, failed
    assert message in failed[check], failed[check]


def test_a_second_lib_python_fails():
    listing = _with(_listing(), "drwxr-xr-x root/root                36 2026-10-29 12:31 "
                                "squashfs-root/lib/python3.11")
    failed = _failed(listing)
    assert set(failed) == {"single-lib-python"}, failed
    assert "lib/python3.11" in failed["single-lib-python"]


def test_the_venv_python_linked_to_another_version_fails():
    listing = _listing("3.12").replace(
        "squashfs-root/bin/python3 -> /usr/bin/python3.12",
        "squashfs-root/bin/python3 -> /usr/bin/python3.11")
    failed = _failed(listing, "3.12")
    assert set(failed) == {"venv-python-link"}, failed
    assert "python3.11" in failed["venv-python-link"]


def test_a_link_to_another_program_named_like_the_right_one_fails():
    listing = _listing().replace("-> /usr/bin/python3.10", "-> /usr/bin/xpython3.10")
    assert set(_failed(listing)) == {"venv-python-link"}


@pytest.mark.parametrize("py", ["3.10", "3.12"])
def test_a_link_to_a_longer_version_fails(py):
    listing = _listing(py).replace(f"-> /usr/bin/python{py}", f"-> /usr/bin/python{py}0")
    assert listing != _listing(py)
    assert set(_failed(listing, py)) == {"venv-python-link"}


@pytest.mark.parametrize("py", ["3.10", "3.12"])
def test_a_link_whose_version_dot_is_another_character_fails(py):
    listing = _listing(py).replace(f"-> /usr/bin/python{py}",
                                   f"-> /usr/bin/python{py.replace('.', 'x')}")
    assert listing != _listing(py)
    assert set(_failed(listing, py)) == {"venv-python-link"}


def test_a_venv_python_that_is_not_a_symlink_fails():
    listing = _with(_without("bin/python3"),
                    "-rwxr-xr-x root/root           5904048 2026-10-29 12:31 "
                    "squashfs-root/bin/python3")
    failed = _failed(listing)
    assert set(failed) == {"venv-python-link"}, failed
    assert "not a symlink" in failed["venv-python-link"]


@pytest.mark.parametrize("name", ["python3", "python3.12", "python3-config"])
def test_a_python_in_usr_bin_fails(name):
    listing = _with(_listing(), "-rwxr-xr-x root/root           6621048 2024-04-08 15:48 "
                                f"squashfs-root/usr/bin/{name}")
    failed = _failed(listing)
    assert set(failed) == {"no-usr-bin-python"}, failed
    assert f"usr/bin/{name}" in failed["no-usr-bin-python"]


def test_two_ghostscript_versions_fail():
    listing = _with(_listing(), "-rw-r--r-- root/root             94625 2026-10-20 17:40 "
                                "squashfs-root/usr/share/ghostscript/10.02.1/Resource/Init/gs_init.ps")
    failed = _failed(listing)
    assert set(failed) == {"ghostscript-init"}, failed
    assert "10.02.1" in failed["ghostscript-init"] and "9.55.0" in failed["ghostscript-init"]


def test_tessdata_split_over_two_versions_fails():
    listing = _listing().replace(_TESSDATA + "por.traineddata",
                                 "usr/share/tesseract-ocr/5/tessdata/por.traineddata")
    failed = _failed(listing)
    assert set(failed) == {"tessdata"}, failed
    assert "'4.00', '5'" in failed["tessdata"]


def test_a_missing_fonts_conf_is_reported_without_failing():
    failures, facts = payload.check_payload(
        payload.parse_listing(_without("etc/fonts/fonts.conf")), "3.10")
    assert failures == []
    assert facts["etc/fonts/fonts.conf"] == "absent"


def test_dist_infos_are_listed_by_name_and_version():
    entries = payload.parse_listing(_listing())
    assert payload.dist_infos(entries, "3.10") == ["pillow-12.3.0", "pypdf-6.21.4"]


# ── the Python version comes from the manifest ──


def test_the_version_is_read_from_the_manifest():
    assert payload.python_version_from_manifest(_manifest("3.12")) == "3.12"


def test_the_real_manifest_names_one_python_version():
    text = MANIFEST.read_text(encoding="utf-8")
    assert re.fullmatch(r"3\.\d+", payload.python_version_from_manifest(text))


def test_paths_with_different_versions_fail():
    text = _manifest("3.12").replace("python3.12", "python3.10", 1)
    with pytest.raises(ValueError, match="disagree: 3.10, 3.12"):
        payload.python_version_from_manifest(text)


def test_a_manifest_without_the_paths_fails():
    with pytest.raises(ValueError, match="no \\$SNAP/lib/pythonX.Y/ path"):
        payload.python_version_from_manifest("base: core24\n")


def test_fewer_than_four_paths_fail():
    text = "".join(_manifest("3.12").splitlines(keepends=True)[:3])
    with pytest.raises(ValueError, match="3 \\$SNAP/lib/python3.12/ path"):
        payload.python_version_from_manifest(text)


# ── the command line ──


def _run(tmp_path, listing, manifest=None, *extra):
    (tmp_path / "listing.txt").write_text(listing, encoding="utf-8")
    (tmp_path / "snapcraft.yaml").write_text(manifest or _manifest(), encoding="utf-8")
    summary = tmp_path / "summary.md"
    rc = payload.main(["--manifest", str(tmp_path / "snapcraft.yaml"),
                       "--listing", str(tmp_path / "listing.txt"),
                       "--summary", str(summary), *extra])
    return rc, summary


def test_main_passes_and_writes_the_summary(tmp_path, capsys):
    snap = tmp_path / "pdfapps 1.15.2 ação.snap"
    snap.write_bytes(b"\0" * 1234)
    rc, summary = _run(tmp_path, _listing(), None, "--snap", str(snap))
    assert rc == 0
    text = summary.read_text(encoding="utf-8")
    assert "Snap size: 1234 bytes" in text
    assert "Ghostscript resource version: 9.55.0" in text
    assert "tessdata version: 4.00" in text
    assert "- pypdf-6.21.4" in text
    assert "All checks passed" in text
    assert capsys.readouterr().err == ""


def test_main_reports_every_failure_and_exits_1(tmp_path, capsys):
    listing = _without("usr/bin/gs", _without("usr/lib/pdfapps/pdfapps.py"))
    rc, summary = _run(tmp_path, listing)
    assert rc == 1
    err = capsys.readouterr().err
    assert "FAIL gs-tesseract-binaries: missing usr/bin/gs" in err
    assert "FAIL app-entry-point: missing usr/lib/pdfapps/pdfapps.py" in err
    assert "2 check(s) failed" in summary.read_text(encoding="utf-8")


def test_main_fails_on_a_manifest_it_cannot_read_a_version_from(tmp_path, capsys):
    rc, summary = _run(tmp_path, _listing(), "base: core24\n")
    assert rc == 1
    assert "FAIL manifest:" in capsys.readouterr().err
    assert not summary.exists()


def test_the_summary_goes_to_the_step_summary_by_default(tmp_path, monkeypatch):
    step_summary = tmp_path / "step-summary.md"
    step_summary.write_text("earlier step\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary))
    (tmp_path / "listing.txt").write_text(_listing(), encoding="utf-8")
    (tmp_path / "snapcraft.yaml").write_text(_manifest(), encoding="utf-8")
    rc = payload.main(["--manifest", str(tmp_path / "snapcraft.yaml"),
                       "--listing", str(tmp_path / "listing.txt")])
    assert rc == 0
    text = step_summary.read_text(encoding="utf-8")
    assert text.startswith("earlier step\n## Snap payload")


def test_importing_the_script_has_no_side_effect(capsys):
    _load()
    assert capsys.readouterr() == ("", "")


def test_the_script_runs_as_a_program(tmp_path):
    (tmp_path / "listing.txt").write_text(_listing(), encoding="utf-8")
    (tmp_path / "snapcraft.yaml").write_text(_manifest(), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-I", str(SCRIPT),
         "--manifest", str(tmp_path / "snapcraft.yaml"),
         "--listing", str(tmp_path / "listing.txt"),
         "--summary", str(tmp_path / "summary.md")],
        check=False, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "All checks passed" in proc.stdout
