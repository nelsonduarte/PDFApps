"""The Windows installer must download a Ghostscript clear of known CVEs.

installer.py downloads the Ghostscript setup from the official
ArtifexSoftware/ghostpdl-downloads release and runs it elevated with
``/S``, so its version is part of what PDFApps ships on Windows. 10.07.0
is affected by CVE-2026-39919 (CRITICAL, heap overflow in the JPEG 2000
output adapter), CVE-2026-103226 (stack overflow in pdfwrite) and
CVE-2026-19547 (Windows privilege escalation via C:\\gs\\ resources);
all three are fixed in 10.08.0 (NVD, 2026-10-27).

The constants are read with ``ast`` instead of importing installer.py,
which imports tkinter at module scope and picks its branch from
``sys.platform``, so the win32 values are checked on every OS.

What this cannot check offline: that the SHA256 matches the file at the
URL. It was computed from the downloaded file on 2026-10-28, whose
SHA512 matched the release's SHA512SUMS and whose Authenticode signature
verified as Artifex Software, Inc.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from packaging.version import Version

INSTALLER = Path(__file__).resolve().parent.parent / "installer.py"

MINIMUM = Version("10.8.0")
RELEASES = "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/"


def _is_win32_test(test: ast.expr) -> bool:
    return (
        isinstance(test, ast.Compare)
        and ast.unparse(test.left) == "sys.platform"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "win32"
    )


def _win32_ghostscript_constants(source: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in ast.parse(source).body:
        if not (isinstance(node, ast.If) and _is_win32_test(node.test)):
            continue
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id.startswith("GHOSTSCRIPT_")
            ):
                out[stmt.targets[0].id] = ast.literal_eval(stmt.value)
    return out


def _pin_problems(consts: dict[str, str]) -> list[str]:
    missing = {"GHOSTSCRIPT_EXE", "GHOSTSCRIPT_URL", "GHOSTSCRIPT_SHA256"} - set(consts)
    if missing:
        return [f"missing {sorted(missing)}"]
    problems = []
    url, exe, sha = (
        consts["GHOSTSCRIPT_URL"], consts["GHOSTSCRIPT_EXE"], consts["GHOSTSCRIPT_SHA256"]
    )
    m = re.fullmatch(re.escape(RELEASES) + r"gs(\d{5})/gs(\d{5})w64\.exe", url)
    if not m:
        return [f"URL is not an official ghostpdl-downloads w64 asset: {url}"]
    tag, asset = m.groups()
    if tag != asset:
        problems.append(f"release tag gs{tag} and asset gs{asset} disagree")
    # gs10080 -> 10.08.0, the scheme Artifex uses for tags and folders.
    url_version = f"{int(tag[:2])}.{tag[2:4]}.{tag[4]}"
    m_exe = re.fullmatch(r"C:\\Program Files\\gs\\gs(\d+\.\d\d\.\d+)\\bin\\gswin64c\.exe", exe)
    if not m_exe:
        problems.append(f"unexpected GHOSTSCRIPT_EXE {exe}")
    elif m_exe.group(1) != url_version:
        problems.append(f"GHOSTSCRIPT_EXE is for {m_exe.group(1)}, URL for {url_version}")
    if Version(url_version) < MINIMUM:
        problems.append(f"Ghostscript {url_version} is below {MINIMUM}")
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        problems.append(f"GHOSTSCRIPT_SHA256 is not a lowercase SHA256: {sha!r}")
    return problems


_OK = {
    "GHOSTSCRIPT_EXE": r"C:\Program Files\gs\gs10.08.0\bin\gswin64c.exe",
    "GHOSTSCRIPT_URL": RELEASES + "gs10080/gs10080w64.exe",
    "GHOSTSCRIPT_SHA256": "0" * 64,
}


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({}, None),
        ({"GHOSTSCRIPT_URL": RELEASES + "gs10070/gs10070w64.exe",
          "GHOSTSCRIPT_EXE": r"C:\Program Files\gs\gs10.07.0\bin\gswin64c.exe"},
         "below 10.8.0"),
        ({"GHOSTSCRIPT_URL": RELEASES + "gs10080/gs10070w64.exe"}, "disagree"),
        ({"GHOSTSCRIPT_EXE": r"C:\Program Files\gs\gs10.07.0\bin\gswin64c.exe"},
         "GHOSTSCRIPT_EXE is for 10.07.0"),
        ({"GHOSTSCRIPT_URL": "https://example.com/gs10080/gs10080w64.exe"},
         "not an official"),
        ({"GHOSTSCRIPT_SHA256": "0" * 63}, "not a lowercase SHA256"),
    ],
)
def test_pin_check_rejects_old_or_inconsistent_pins(override, expected):
    problems = _pin_problems({**_OK, **override})
    if expected is None:
        assert problems == []
    else:
        assert any(expected in p for p in problems), problems


def test_installer_downloads_ghostscript_10_08_0_or_later():
    consts = _win32_ghostscript_constants(INSTALLER.read_text(encoding="utf-8"))
    problems = _pin_problems(consts)
    assert not problems, "\n".join(problems)
