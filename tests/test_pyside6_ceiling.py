"""requirements.txt must keep PySide6 below 6.12 while the ceiling lasts.

The ceiling is temporary, for the 1.15.1 release: the frozen macOS and
Linux builds and the snap have not been tested with PySide6 6.12. It
goes once the frozen Windows, macOS and Linux builds and the snap all
pass the smoke test with 6.12. This test exists only to stop the
ceiling being widened or dropped by accident (a Dependabot PR, a hand
edit), and it is removed together with the ceiling.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _requirements_parsing import parse_line, parse_requirements_text
from packaging.requirements import Requirement

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"

# Checked with prereleases=True, so a 6.12 pre-release counts as admitted
# whatever the packaging release: before packaging 26.0, contains() with
# the default rejected a pre-release unless the specifier named one.
_BEYOND_CEILING = ("6.12.0rc1", "6.12.0.dev0", "6.12.0", "6.12.1", "6.13.0", "7.0.0")
# A ceiling must not shut out the 6.11 series the app is built on; a
# floor raised within 6.11 is fine, so any 6.11.x will do.
_SERIES_6_11 = tuple(f"6.11.{i}" for i in range(100))


def _ceiling_problems(req: Requirement) -> list[str]:
    problems = []
    if req.marker is not None:
        problems.append(f"'{req}' carries an environment marker")
    admitted = [
        v for v in _BEYOND_CEILING if req.specifier.contains(v, prereleases=True)
    ]
    if admitted:
        problems.append(f"'{req}' admits {admitted}")
    if not any(req.specifier.contains(v) for v in _SERIES_6_11):
        problems.append(f"'{req}' admits no 6.11.x release")
    return problems


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("PySide6>=6.11.1,<6.12", True),
        ("PySide6>=6.11.2,<6.12", True),
        ("PySide6>=6.11.1,<6.12  # cap", True),
        ("PySide6~=6.11.1", True),
        ("PySide6>=6.11.1", False),
        ("PySide6>=6.11.1,<6.13", False),
        ("PySide6>=6.11.1,!=6.12.0", False),
        ("PySide6>=6.11.1,<=6.12.0rc1", False),
        ("PySide6>=6.11.1,<6.12.0.dev1", False),
        ("PySide6>=6.11.1,!=6.12.0,!=6.12.1,<6.13", False),  # 6.12.0rc1
        ("PySide6<6.11", False),
        ("PySide6>=6.12", False),
        ('PySide6>=6.11.1,<6.12; sys_platform == "win32"', False),
    ],
)
def test_ceiling_check_accepts_6_11_only_specifiers(line, ok):
    assert (_ceiling_problems(parse_line(line)) == []) is ok


def test_requirements_keep_pyside6_below_6_12():
    req = parse_requirements_text(REQUIREMENTS.read_text(encoding="utf-8"))["pyside6"]
    problems = _ceiling_problems(req)
    assert not problems, (
        "requirements.txt must keep PySide6 below 6.12 until the "
        "frozen Windows, macOS and Linux builds and the snap all "
        "pass the smoke test with 6.12: "
        + "; ".join(problems)
    )
