#!/usr/bin/env python3
"""Print requirements.txt with every requirement pinned to its floor.

Used by .github/workflows/security-deps.yml. ``pip-audit -r`` audits the
newest release each ``>=`` admits, so a floor that still admits a
vulnerable release audits clean for as long as a fixed release exists.
Auditing the floors themselves, as ``==`` pins with
``pip-audit --no-deps --disable-pip``, closes that gap for whatever
advisory OSV or PyPI know about today, not only for the ones
tests/test_dependency_security_floors.py lists.

Environment markers are kept: pip-audit evaluates them against the
interpreter it runs on, so a Python 3.10-only line is left out when the
workflow audits on 3.14.

Needs ``packaging``, which pip-audit depends on, so the workflow step
that installs pip-audit already provides it.

Usage: python scripts/requirements_floors.py requirements.txt > floors.txt
"""

from __future__ import annotations

import argparse
import re
import sys

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import Version

# pip strips "#" to end of line when it starts the line or follows
# whitespace, as tests/_requirements_parsing.py does.
_INLINE_COMMENT = re.compile(r"(^|\s)#.*$")

# Operators whose version is itself the lowest release the clause admits.
# ">X" admits X.post1 and up, and "==X.*" admits X's pre-releases, so
# neither names a release that is the floor; "<", "<=" and "!=" have none.
_FLOOR_OPERATORS = ("==", ">=", "~=")


def floor_pins(text: str) -> list[str]:
    """One ``name==floor`` line (marker kept) per requirement in ``text``.

    Raises ValueError for any line without a floor this can name exactly,
    so a new requirement written in an unexpected form fails the workflow
    instead of dropping out of the floor audit.
    """
    out = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = _INLINE_COMMENT.sub("", raw).strip()
        if not line:
            continue
        if line.startswith("-"):
            raise ValueError(f"line {lineno}: pip option not supported: {line}")
        try:
            req = Requirement(line)
        except InvalidRequirement as exc:
            raise ValueError(f"line {lineno}: {exc}") from exc
        floors = [
            c.version
            for c in req.specifier
            if c.operator in _FLOOR_OPERATORS and not c.version.endswith(".*")
        ]
        # A ">" or "===" clause could bind above the floors collected here.
        if not floors or any(c.operator in (">", "===") for c in req.specifier):
            raise ValueError(f"line {lineno}: '{req}' has no exact floor")
        floor = max(floors, key=Version)
        pin = f"{req.name}=={floor}"
        if req.marker is not None:
            pin += f"; {req.marker}"
        out.append(pin)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("requirements")
    args = parser.parse_args(argv)
    with open(args.requirements, encoding="utf-8") as f:
        text = f.read()
    try:
        pins = floor_pins(text)
    except ValueError as exc:
        print(f"{args.requirements}: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write("".join(p + "\n" for p in pins))
    return 0


if __name__ == "__main__":
    sys.exit(main())
