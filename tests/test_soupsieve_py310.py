"""requirements.txt must keep admitting soupsieve 2.10 while 3.10 builds last.

One build installs requirements.txt on Python 3.10: the snap (core22).
Every soupsieve release after 2.10 requires Python >=3.11, so a
soupsieve line that excludes 2.10 and applies there leaves pip on Python
3.10 with "No matching distribution": the snap fails after the release
is out, when publish.yml builds it.

requirements.txt splits soupsieve by marker since the advisories of
2026-11-13 (4.0.0 is the first clean release and needs Python >=3.11.5),
so the rule here is about the line that applies on Python 3.10, whichever
it is: exactly one line must apply there, and it must admit
LAST_PY310_RELEASE. tests/test_dependency_security_floors.py checks the
security floor of each line, on every Python.

CI cannot catch this on its own, because every job that installs
requirements.txt on a pull request (tests.yml, security-deps.yml) uses
Python 3.14 or 3.12, where the marker skips the 3.10 line, so whatever
it says installs fine there.

Dependabot does not edit that line either (dependabot-core, read on
2026-11-13). With no .python-version, pyproject.toml, setup.py,
runtime.txt, Pipfile or pip-compile header in this repository, its pip
updater takes Python constraints from the python_version markers of
requirements.txt (python_full_version markers do not count) and runs the
lowest Python it ships that meets them all. The markers of pillow's two
lines contradict each other, so none does and it runs the newest it ships
(3.15.2 on 2026-11-13); without pillow's 3.10 line it would run 3.11.18,
still above 3.11.5. It drops every line whose marker is false there, so
it only sees the 3.11.5 line and proposes raising that one. Those PRs
go red in one assertion, tests/test_requirements_floors_script.py,
which pins the exact floor; update it in the same PR.
Before the split, with a single line, it did propose what breaks the
snap: #249 asked for ``>=4.0.1`` and was closed by hand. Its security
updates open no PR for a ``>=`` line. What remains is a hand edit, or a
file or marker that one day sends Dependabot to a Python below 3.11.5,
and this test turns either red.

Why 2.10: according to PyPI it is the last soupsieve release whose
``Requires-Python`` is ``>=3.10`` (2.9 to 2.10 say ``>=3.10``; 3.0 and
3.0.1 say ``>=3.11`` and are yanked; 3.0.2 to 4.1 say ``>=3.11.5``),
measured on 2026-10-16 and again on 2026-11-13. If a later 2.x release
still supports Python 3.10, this constant, the requirements.txt comment
and the soupsieve entry of RESIDUAL_FLOORS in
tests/test_dependency_security_floors.py move together;
test_the_py310_release_is_the_residual_floor fails if the constant and
that entry part.

Remove this test, together with the Python 3.10 line in requirements.txt
and the soupsieve entry of RESIDUAL_FLOORS, once the snap no longer
builds on Python 3.10.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _requirements_parsing import (
    TARGET_ENVIRONMENTS,
    applicable,
    parse_requirement_lines,
    target_environment,
)
from test_dependency_security_floors import RESIDUAL_FLOORS

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"

LAST_PY310_RELEASE = "2.10"

# Every Python 3.10 micro release up to 3.10.20, so a marker on
# python_full_version cannot pass on 3.10.0 and miss the 3.10.12 that
# core22 ships.
PY310_ENVIRONMENTS = [
    target_environment(f"3.10.{micro}", "linux") for micro in range(21)
]


def _py310_problems(text: str) -> list[str]:
    """Why the soupsieve line Python 3.10 takes from ``text`` is wrong.

    Exactly one line must apply on every Python 3.10 environment: none
    leaves the transitive to bs4's own floor, and more than one hands pip
    both. That line must admit LAST_PY310_RELEASE.
    """
    lines = parse_requirement_lines(text).get("soupsieve", [])
    problems = []
    for env in PY310_ENVIRONMENTS:
        where = f"Python {env['python_full_version']}"
        kept = applicable(lines, env)
        if len(kept) != 1:
            problems.append(
                f"{len(kept)} soupsieve lines apply on {where}, expected 1: "
                f"{[str(r) for r in kept] or [str(r) for r in lines]}"
            )
            continue
        if not kept[0].specifier.contains(LAST_PY310_RELEASE):
            problems.append(
                f"'{kept[0]}' applies on {where} and does not admit "
                f"{LAST_PY310_RELEASE}"
            )
    return list(dict.fromkeys(problems))


_SPLIT = (
    'soupsieve>=4.0.0; python_full_version >= "3.11.5"\n'
    'soupsieve>=2.10; python_full_version < "3.11.5"\n'
)
# The 3.10 side is fine; the gap on 3.11.0 to 3.11.4 is
# tests/test_dependency_security_floors.py's to catch.
_SPLIT_ON_PYTHON_VERSION = (
    'soupsieve>=4.0.0; python_version >= "3.11"\n'
    'soupsieve>=2.10; python_version < "3.11"\n'
)
# The 3.10 line raised past what 3.10 installs.
_PY310_LINE_RAISED = (
    'soupsieve>=4.0.0; python_full_version >= "3.11.5"\n'
    'soupsieve>=3.0.2; python_full_version < "3.11.5"\n'
)
# Two lines on 3.10: pip is handed both.
_OVERLAP_ON_PY310 = (
    'soupsieve>=4.0.0; python_full_version >= "3.10"\n'
    'soupsieve>=2.10; python_full_version < "3.11.5"\n'
)
# Only on 3.10.0: the snap's 3.10.12 gets the 4.0.0 line.
_SPLIT_INSIDE_PY310 = (
    'soupsieve>=4.0.0; python_full_version >= "3.10.1"\n'
    'soupsieve>=2.10; python_full_version < "3.10.1"\n'
)
# No line for 3.10: bs4's floor would decide.
_NO_PY310_LINE = 'soupsieve>=2.9; python_version >= "3.11"\n'


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("soupsieve>=2.9\n", True),
        ("soupsieve>=2.10\n", True),
        ("soupsieve>=2.9,<3\n", True),
        (_SPLIT, True),
        (_SPLIT_ON_PYTHON_VERSION, True),
        ("soupsieve>=3.0.3\n", False),
        ("soupsieve>=2.11\n", False),
        ("soupsieve==3.0.3\n", False),
        (_PY310_LINE_RAISED, False),
        (_NO_PY310_LINE, False),
        (_OVERLAP_ON_PY310, False),
        (_SPLIT_INSIDE_PY310, False),
        ("", False),
    ],
)
def test_py310_check_accepts_only_a_single_line_that_admits_2_10(text, ok):
    problems = _py310_problems(text)
    if ok:
        assert not problems, (
            f"{text!r} gives Python 3.10 one line that admits "
            f"{LAST_PY310_RELEASE}, yet the check rejects it: {problems}"
        )
    else:
        assert problems, (
            f"{text!r} gives some Python 3.10 no line, two lines, or a line "
            f"that rejects {LAST_PY310_RELEASE}, yet the check accepts it"
        )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (_OVERLAP_ON_PY310, "2 soupsieve lines apply on Python 3.10.0, expected 1"),
        (_NO_PY310_LINE, "0 soupsieve lines apply on Python 3.10.0, expected 1"),
        ("", "0 soupsieve lines apply on Python 3.10.0, expected 1"),
        (_PY310_LINE_RAISED, "applies on Python 3.10.0 and does not admit 2.10"),
        (_SPLIT_INSIDE_PY310, "applies on Python 3.10.1 and does not admit 2.10"),
    ],
)
def test_py310_check_explains_what_is_wrong(text, expected):
    problems = _py310_problems(text)
    assert any(expected in p for p in problems), (
        f"for {text!r} the check should report {expected!r}; "
        f"it reports {problems or 'nothing'}"
    )


def test_the_snap_python_is_in_the_py310_sweep():
    snap = TARGET_ENVIRONMENTS["linux-py3.10"]
    assert snap in PY310_ENVIRONMENTS, (
        f"the snap's Python {snap['python_full_version']} is not among the "
        "3.10 micro releases this test checks; widen PY310_ENVIRONMENTS"
    )


def test_the_py310_release_is_the_residual_floor():
    covers, _clean, floor, _affected = RESIDUAL_FLOORS["soupsieve"]
    assert floor == LAST_PY310_RELEASE, (
        f"RESIDUAL_FLOORS gives soupsieve {floor} as the floor below "
        f"Python 3.11.5, but this test holds {LAST_PY310_RELEASE} as the "
        "newest release Python 3.10 installs; both name that one release"
    )
    snap = TARGET_ENVIRONMENTS["linux-py3.10"]["python_full_version"]
    assert covers.contains(snap), (
        f"the soupsieve residual covers {covers}, which leaves out the "
        f"snap's Python {snap}"
    )


def test_requirements_keep_admitting_soupsieve_2_10():
    problems = _py310_problems(REQUIREMENTS.read_text(encoding="utf-8"))
    assert not problems, (
        f"requirements.txt must keep admitting soupsieve {LAST_PY310_RELEASE}, "
        "the last release that installs on Python 3.10, on exactly one line "
        "that applies there: the snap (core22) installs requirements.txt on "
        "Python 3.10. See the comment above the soupsieve lines in "
        "requirements.txt: " + "; ".join(problems)
    )
