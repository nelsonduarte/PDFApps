"""requirements.txt must not admit a PyMuPDF release older than 1.28.2.

PyMuPDF 1.28.0 can segfault in ``Document.subset_fonts()``
(pymupdf/PyMuPDF#5049): MuPDF's ``do_adjust_simple_font`` replaced a
simple font's ``/Widths`` array and then kept reading the one it had
just freed. Fixed in 1.28.2; there is no 1.28.1 on PyPI. PDFApps calls
``subset_fonts()`` in compress pass B (``app/utils.py``) and after a text
edit that re-embeds the original font (``app/editor/apply_edits.py``).
The ``try/except`` around both calls cannot catch a segfault, so the
whole app dies, background thread or not.

Measured on 2026-10-16 (Ubuntu 26.04, Python 3.14.4, PySide6 6.11.2,
the PDF attached to #5049), 200 runs per version, each in a fresh
process: ``_compress_pdf`` crashed 6 times on 1.28.0 and never on
1.28.2; ``apply_pending_edits`` crashed 8 times on 1.28.0 and never on
1.28.2. On Windows, 300 compress runs on 1.28.0 did not crash.

The frozen builds resolve ``>=`` at build time and the v1.15.1 ones
already took 1.28.2, so the floor is what protects everything that
installs from requirements.txt as it stands: source installs, dev venvs,
and any build run while 1.28.2 is not the newest release a resolver
picks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _requirements_parsing import floor_of, parse_line, parse_requirements_text
from packaging.requirements import Requirement
from packaging.version import Version

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"

MINIMUM = Version("1.28.2")
# Checked with prereleases=True so a 1.28.2 pre-release counts as admitted.
_BELOW_MINIMUM = ("1.27.2.3", "1.28.0", "1.28.0.post1", "1.28.1", "1.28.2rc1")


def _floor_problems(req: Requirement) -> list[str]:
    problems = []
    # A marker makes pip skip the line wherever it evaluates false, so
    # the floor would not hold there.
    if req.marker is not None:
        problems.append(f"'{req}' carries an environment marker")
    floor = floor_of(req.specifier)
    if floor is None or floor < MINIMUM:
        problems.append(f"'{req}' has floor {floor}, below {MINIMUM}")
    admitted = [
        v for v in _BELOW_MINIMUM if req.specifier.contains(v, prereleases=True)
    ]
    if admitted:
        problems.append(f"'{req}' admits {admitted}")
    return problems


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("pymupdf>=1.28.2", True),
        ("pymupdf>=1.28.2  # note", True),
        ("pymupdf~=1.28.2", True),
        ("pymupdf==1.28.2", True),
        ("pymupdf>=1.29", True),
        ("PyMuPDF>=1.28.2,<2", True),
        ("pymupdf>=1.28.0", False),
        ("pymupdf>1.28.0", False),  # admits 1.28.0.post1 and 1.28.1
        ("pymupdf>=1.28.2rc1", False),
        ("pymupdf==1.28.*", False),
        ("pymupdf!=1.28.0", False),
        ("pymupdf<2", False),
        ("pymupdf", False),
        ('pymupdf>=1.28.2; sys_platform == "win32"', False),
    ],
)
def test_floor_check_accepts_1_28_2_and_up_only(line, ok):
    assert (_floor_problems(parse_line(line)) == []) is ok


def test_requirements_floor_excludes_the_subset_fonts_segfault():
    req = parse_requirements_text(REQUIREMENTS.read_text(encoding="utf-8")).get(
        "pymupdf"
    )
    assert req is not None, "pymupdf missing from requirements.txt"
    problems = _floor_problems(req)
    assert not problems, (
        "requirements.txt must not admit a PyMuPDF release below "
        f"{MINIMUM} (subset_fonts segfault, pymupdf/PyMuPDF#5049): "
        + "; ".join(problems)
    )
