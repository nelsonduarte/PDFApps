"""requirements.txt must keep admitting soupsieve 2.10 while 3.10 builds last.

Two builds install requirements.txt on Python 3.10: the appimage job in
build.yml (ubuntu-22.04, ``python-version: '3.10'``), which the release
job needs, and the snap (core22). Every soupsieve 3.x requires Python
>=3.11, so a soupsieve line that excludes 2.10 leaves pip on Python 3.10
with "No matching distribution": the AppImage fails on the tag and the
release job never runs, and the snap fails after the release is out.

CI cannot catch this on its own, because every job that installs
requirements.txt on a pull request (tests.yml, security-deps.yml) uses
Python 3.14, where ``soupsieve>=3.0.3`` installs fine.
Dependabot raises ``>=`` floors in this file to the newest release: the
weekly pip version updates in .github/dependabot.yml did so for lxml
(#86, then #176) and idna (#105), and security updates are enabled too.
A PR raising soupsieve to 3.x is therefore to be expected, and this test
is what turns it red. It complements the security floor in
tests/test_dependency_security_floors.py, which guards the other side.

Why 2.10: according to PyPI it is the last soupsieve release whose
``Requires-Python`` is ``>=3.10`` (2.9 to 2.10 say ``>=3.10``; 3.0 and
3.0.1 say ``>=3.11`` and are yanked; 3.0.2 and 3.0.3 say ``>=3.11.5``),
measured on 2026-10-16. If a later 2.x release still supports Python
3.10, this constant and the requirements.txt comment move together.

Remove this test, together with the restriction in the requirements.txt
comment, once neither the snap nor the AppImage builds on Python 3.10.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _requirements_parsing import parse_line, parse_requirements_text
from packaging.requirements import Requirement

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"

LAST_PY310_RELEASE = "2.10"


def _py310_problems(req: Requirement) -> list[str]:
    problems = []
    # A marker makes pip skip the line wherever it evaluates false, so on
    # Python 3.10 the transitive would fall back to bs4's own floor.
    if req.marker is not None:
        problems.append(f"'{req}' carries an environment marker")
    if not req.specifier.contains(LAST_PY310_RELEASE):
        problems.append(f"'{req}' does not admit {LAST_PY310_RELEASE}")
    return problems


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("soupsieve>=2.9", True),
        ("soupsieve>=2.10", True),
        ("soupsieve>=2.9,<3", True),
        ("soupsieve>=3.0.3", False),
        ("soupsieve>=2.11", False),
        ("soupsieve==3.0.3", False),
        ('soupsieve>=2.9; python_version >= "3.11"', False),
    ],
)
def test_py310_check_accepts_only_lines_that_admit_2_10(line, ok):
    assert (_py310_problems(parse_line(line)) == []) is ok


def test_requirements_keep_admitting_soupsieve_2_10():
    req = parse_requirements_text(REQUIREMENTS.read_text(encoding="utf-8"))["soupsieve"]
    problems = _py310_problems(req)
    assert not problems, (
        f"requirements.txt must keep admitting soupsieve {LAST_PY310_RELEASE}, "
        "the last release that installs on Python 3.10: the appimage job "
        "in build.yml and the snap (core22) both install requirements.txt "
        "on Python 3.10, and the release job needs the appimage job. See "
        "the comment above the soupsieve line in requirements.txt: "
        + "; ".join(problems)
    )
