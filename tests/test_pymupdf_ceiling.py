"""requirements.txt must keep PyMuPDF below 2 while the ceiling lasts.

PyMuPDF 2.0 (2026-10-19, Requires-Python >=3.11) is a new major that
also pulls onnxruntime, numpy, networkx, pymupdf-layout and pymupdf4llm.
Once ``pymupdf>=1.28.2`` started resolving to it on Python 3.11+, the
pytest job on pull requests failed in
``tests/test_watermark_characterization.py::
test_form_widget_survives_on_the_page_without_its_acroform`` (tests.yml
run 39544717071), and no frozen build has been tested with it.

This test exists only to stop the ceiling being widened or dropped by
accident (a Dependabot PR, a hand edit). It is removed together with
the ceiling, once the suite and the frozen builds pass with 2.x. The
floor is guarded separately, by tests/test_pymupdf_floor.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _requirements_parsing import parse_line, parse_requirements_text
from packaging.requirements import Requirement

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"

# Checked with prereleases=True, so a 2.0 pre-release counts as admitted.
_BEYOND_CEILING = ("2.0rc1", "2.0.dev0", "2.0", "2.0.1", "2.1", "3.0")
# The ceiling must not shut out the 1.28 series the app runs on today.
_SERIES_1_28 = tuple(f"1.28.{i}" for i in range(2, 100))


def _ceiling_problems(req: Requirement) -> list[str]:
    problems = []
    if req.marker is not None:
        problems.append(f"'{req}' carries an environment marker")
    admitted = [
        v for v in _BEYOND_CEILING if req.specifier.contains(v, prereleases=True)
    ]
    if admitted:
        problems.append(f"'{req}' admits {admitted}")
    if not any(req.specifier.contains(v) for v in _SERIES_1_28):
        problems.append(f"'{req}' admits no 1.28.x release from 1.28.2 on")
    return problems


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("pymupdf>=1.28.2,<2", True),
        ("PyMuPDF>=1.28.2,<2  # cap", True),
        ("pymupdf>=1.28.2,<2.0.dev0", True),
        ("pymupdf~=1.28.2", True),
        ("pymupdf>=1.28.2", False),
        ("pymupdf>=1.28.2,<3", False),
        ("pymupdf>=1.28.2,!=2.0", False),  # admits 2.0rc1 and 2.0.1
        ("pymupdf>=1.28.2,<=2.0", False),
        ("pymupdf>=1.28.2,<2.0.1", False),
        ("pymupdf<1.28", False),
        ("pymupdf>=2", False),
        ('pymupdf>=1.28.2,<2; sys_platform == "win32"', False),
    ],
)
def test_ceiling_check_accepts_1_x_only_specifiers(line, ok):
    assert (_ceiling_problems(parse_line(line)) == []) is ok


def test_requirements_keep_pymupdf_below_2():
    req = parse_requirements_text(REQUIREMENTS.read_text(encoding="utf-8"))["pymupdf"]
    problems = _ceiling_problems(req)
    assert not problems, (
        "requirements.txt must keep PyMuPDF below 2 until the suite and "
        "the frozen builds pass with 2.x: " + "; ".join(problems)
    )
