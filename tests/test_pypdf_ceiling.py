"""requirements.txt must keep pypdf below 7 while the ceiling lasts.

pypdf 7.0.0 (2026-11-06, Requires-Python >=3.10) is a new major that
removes deprecated code, drops cryptography <43, makes file identifiers
non-deterministic and writes XMP without an XML declaration. Without
the ceiling, ``pypdf>=6.21.4`` resolves to it in tests.yml, build.yml
and the snap. The suite has passed with it (tests.yml run 42247044575,
before the ceiling existed), but the frozen builds and the snap have
not been tested with it, nor what the /ID and XMP changes do to the
files the app writes.

This test exists only to stop the ceiling being widened or dropped by
accident (a Dependabot PR, a hand edit). It is removed together with
the ceiling, in the pull request that moves the app to 7.x. The floor
is guarded separately, by tests/test_dependency_security_floors.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _requirements_parsing import parse_line, parse_requirements_text
from packaging.requirements import Requirement

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"

# Checked with prereleases=True, so a 7.0 pre-release counts as admitted.
_BEYOND_CEILING = ("7.0.0rc1", "7.0.0.dev0", "7.0.0", "7.0.1", "7.1.0", "8.0.0")
# The ceiling must not shut out the 6.x series the app runs on today; a
# floor raised within 6.x is fine, so any 6.x from 6.21.4 on will do.
_SERIES_6 = tuple(f"6.21.{i}" for i in range(4, 100)) + tuple(
    f"6.{minor}.{i}" for minor in range(22, 100) for i in range(10)
)


def _ceiling_problems(req: Requirement) -> list[str]:
    problems = []
    if req.marker is not None:
        problems.append(f"'{req}' carries an environment marker")
    admitted = [
        v for v in _BEYOND_CEILING if req.specifier.contains(v, prereleases=True)
    ]
    if admitted:
        problems.append(f"'{req}' admits {admitted}")
    if not any(req.specifier.contains(v) for v in _SERIES_6):
        problems.append(f"'{req}' admits no 6.x release from 6.21.4 on")
    return problems


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("pypdf>=6.21.4,<7", True),
        ("PyPDF>=6.21.4,<7  # cap", True),
        ("pypdf[crypto]>=6.21.4,<7", True),
        ("pypdf>=6.21.4,<7.0.0.dev0", True),
        ("pypdf~=6.21.4", True),
        ("pypdf>=6.22,<7", True),
        ("pypdf>=6.21.4", False),
        ("pypdf>=6.21.4,<8", False),
        ("pypdf>=6.21.4,!=7.0.0", False),  # admits 7.0.0rc1 and 7.0.1
        ("pypdf>=6.21.4,<=7.0.0", False),
        ("pypdf>=6.21.4,<7.0.1", False),
        ("pypdf>=6.21.4,<7.0.0rc1", False),  # admits 7.0.0.dev0
        ("pypdf>=6.21.4,<=7.0.0rc1", False),
        ("pypdf>=6.21.4,<7.1", False),
        ("pypdf>=6.21.4,<7.2,!=7.0.*", False),  # admits only 7.1.0 of the list
        ("pypdf>=6.21.4,!=7.*", False),  # admits only 8.0.0 of the list
        # Admits only 7.0.0rc1 and 7.0.0.dev0 of the list; packaging 24.2
        # sees them only with prereleases=True (26.2 sees them either way).
        ("pypdf>=6.21.4,<7.0.1,!=7.0.0", False),
        ("pypdf>=6.21.4,<=7.0.0,!=7.0.0rc1,!=7.0.0.dev0", False),  # admits only 7.0.0 of the list
        ("pypdf>=6.21.4,<7.1,!=7.0.0.*", False),  # admits only 7.0.1 of the list
        ("pypdf>=6.21.4,<7.0.0rc2,!=7.0.0.dev0", False),  # admits only 7.0.0rc1 of the list
        ("pypdf<6.21", False),
        ("pypdf>=7", False),
        ('pypdf>=6.21.4,<7; sys_platform == "win32"', False),
    ],
)
def test_ceiling_check_accepts_6_x_only_specifiers(line, ok):
    assert (_ceiling_problems(parse_line(line)) == []) is ok


def test_requirements_keep_pypdf_below_7():
    req = parse_requirements_text(REQUIREMENTS.read_text(encoding="utf-8"))["pypdf"]
    problems = _ceiling_problems(req)
    assert not problems, (
        "requirements.txt must keep pypdf below 7 until the frozen "
        "builds and the snap have been tested with 7.x and the suite "
        "passes with it: " + "; ".join(problems)
    )
