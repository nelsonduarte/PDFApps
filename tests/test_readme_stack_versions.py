"""README.md's tech stack table and PySide6 badge must match requirements.txt.

In the README at 1ef2721, five floors in the table were behind
requirements.txt (PySide6, pypdf, Pillow, QtAwesome and PyInstaller)
and the PySide6 badge said 6.10, with no test failing. By this test's
rules, 7 of the 8 rows fail there: those five, PyMuPDF (no ceiling)
and OCR (the cell does not name pytesseract). Only python-docx passes.

Each row's Version cell gives the package's floor, then in parentheses
either its ceiling ("below X") or, for Pillow, the floor of its
Python < 3.11 line ("X below Python Y").
This test reads both files and compares them, so a floor or ceiling
moved in one and not the other fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

from _requirements_parsing import (
    applicable,
    floor_of,
    parse_requirement_lines,
    target_environment,
)
from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
REQUIREMENTS = ROOT / "requirements.txt"

# Component cell -> (name the Technology cell links to, PEP 503 name in
# requirements.txt). A row added to the table, or removed from it,
# fails until this mapping follows.
COMPONENTS = {
    "GUI": ("PySide6", "pyside6"),
    "PDF rendering": ("PyMuPDF", "pymupdf"),
    "PDF manipulation": ("pypdf", "pypdf"),
    "OCR": ("pytesseract", "pytesseract"),
    "DOCX export": ("python-docx", "python-docx"),
    "Image processing": ("Pillow", "pillow"),
    "Icons": ("QtAwesome", "qtawesome"),
    "Packaging": ("PyInstaller", "pyinstaller"),
}

# Pillow is the one package split by marker: one line from Python 3.11
# on, one below. The README gives both floors and the boundary.
SPLIT_PACKAGE = "pillow"

_VERSION_CELL = re.compile(
    r"^(?:(?P<named>[A-Za-z][\w.-]*) )?(?P<floor>\d[\w.]*)"
    r"(?: \(below (?P<ceiling>\d[\w.]*)\)"
    r"| \((?P<low_floor>\d[\w.]*) below Python (?P<boundary>\d+\.\d+)\))?$"
)
_BADGE = re.compile(r"img\.shields\.io/badge/PySide6-(\d+)\.(\d+)-")


def _stack_rows(readme: str) -> dict[str, tuple[str, str]]:
    """Component -> (Technology cell, Version cell) of the tech stack table."""
    match = re.search(r"^## Tech stack\n(.*?)(?=^## |^---)", readme, re.MULTILINE | re.DOTALL)
    assert match, "README.md has no '## Tech stack' section"
    rows: dict[str, tuple[str, str]] = {}
    for line in match.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] == "Component" or set(cells[0]) <= {"-"}:
            continue
        assert cells[0] not in rows, f"README.md: component {cells[0]!r} listed twice"
        rows[cells[0]] = (cells[1], cells[2])
    return rows


def _ceiling(req: Requirement) -> Version | None:
    caps = [Version(c.version) for c in req.specifier if c.operator == "<"]
    return min(caps) if caps else None


def _bound_problems(label: str, req: Requirement, floor: str, ceiling: str | None) -> list[str]:
    problems = []
    others = sorted({c.operator for c in req.specifier} - {">=", "<"})
    if others:
        problems.append(f"{label}: '{req}' uses {others}, which the table cannot express")
    actual_floor = floor_of(req.specifier)
    if actual_floor != Version(floor):
        problems.append(f"{label}: README says {floor}, requirements.txt floor is {actual_floor}")
    actual_ceiling = _ceiling(req)
    expected_ceiling = Version(ceiling) if ceiling else None
    if actual_ceiling != expected_ceiling:
        problems.append(
            f"{label}: README ceiling is {expected_ceiling}, "
            f"requirements.txt ceiling is {actual_ceiling}"
        )
    return problems


def _split_problems(label: str, reqs: list[Requirement], m: re.Match[str]) -> list[str]:
    if m["low_floor"] is None:
        message = (
            f"{label}: requirements.txt splits it by marker, so the README "
            "must give '<floor> (<floor> below Python <X.Y>)'"
        )
        return [message]
    if len(reqs) != 2:
        return [f"{label}: expected 2 marker lines in requirements.txt, found {len(reqs)}"]
    boundary = Version(m["boundary"])
    below = f"{boundary.major}.{boundary.minor - 1}"
    problems = []
    for python, floor in ((m["boundary"], m["floor"]), (below, m["low_floor"])):
        env = target_environment(python, "linux")
        kept = applicable(reqs, env)
        if len(kept) != 1:
            problems.append(f"{label}: {len(kept)} lines apply on Python {python}")
            continue
        problems += _bound_problems(f"{label} on Python {python}", kept[0], floor, None)
    return problems


def table_problems(readme: str, requirements: str) -> list[str]:
    rows = _stack_rows(readme)
    reqs = parse_requirement_lines(requirements)
    problems = []
    if set(rows) != set(COMPONENTS):
        problems.append(
            f"README.md components {sorted(rows)} do not match the mapping "
            f"in this test {sorted(COMPONENTS)}"
        )
    for component, (tech, version) in rows.items():
        if component not in COMPONENTS:
            continue
        display, package = COMPONENTS[component]
        label = f"{component} ({display})"
        if f"[{display}](" not in tech:
            problems.append(f"{label}: the Technology cell does not link {display}")
        m = _VERSION_CELL.match(version)
        if not m:
            problems.append(f"{label}: cannot read the Version cell {version!r}")
            continue
        if tech.count("](") > 1 and m["named"] is None:
            problems.append(
                f"{label}: the row links more than one project, so the Version "
                f"cell must name the package ('{display} {m['floor']}')"
            )
        if m["named"] is not None and m["named"] != display:
            problems.append(f"{label}: the Version cell names {m['named']!r}")
        if package not in reqs:
            problems.append(f"{label}: {package} is not in requirements.txt")
            continue
        if package == SPLIT_PACKAGE:
            problems += _split_problems(label, reqs[package], m)
            continue
        if m["low_floor"] is not None:
            problems.append(f"{label}: only {SPLIT_PACKAGE} has a per-Python floor")
        if len(reqs[package]) != 1 or reqs[package][0].marker is not None:
            problems.append(f"{label}: expected one unmarked line in requirements.txt")
            continue
        problems += _bound_problems(label, reqs[package][0], m["floor"], m["ceiling"])
    return problems


def badge_problems(readme: str, requirements: str) -> list[str]:
    badges = _BADGE.findall(readme)
    if len(badges) != 1:
        return [f"README.md has {len(badges)} PySide6 badges, expected 1"]
    lines = parse_requirement_lines(requirements).get("pyside6", [])
    if len(lines) != 1 or lines[0].marker is not None:
        message = (
            "PySide6 badge: expected one unmarked pyside6 line in requirements.txt, "
            f"found {[str(r) for r in lines]}"
        )
        return [message]
    floor = floor_of(lines[0].specifier)
    if floor is None:
        return [f"PySide6 badge: requirements.txt line '{lines[0]}' sets no floor to compare with"]
    badge = tuple(int(part) for part in badges[0])
    if badge != floor.release[:2]:
        return [f"PySide6 badge says {badge[0]}.{badge[1]}, requirements.txt floor is {floor}"]
    return []


def test_tech_stack_table_matches_requirements():
    problems = table_problems(
        README.read_text(encoding="utf-8"), REQUIREMENTS.read_text(encoding="utf-8")
    )
    assert not problems, "README.md tech stack table:\n" + "\n".join(problems)


def test_pyside6_badge_matches_the_floor():
    problems = badge_problems(
        README.read_text(encoding="utf-8"), REQUIREMENTS.read_text(encoding="utf-8")
    )
    assert not problems, "; ".join(problems)
