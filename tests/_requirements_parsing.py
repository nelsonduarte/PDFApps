"""requirements.txt parsing shared by the dependency tests.

Not a test module: pytest does not collect it because its name matches
neither ``test_*.py`` nor ``*_test.py``, the default ``python_files``
patterns. The tests import it by bare name, which works because
``tests/`` has no ``__init__.py``, so pytest's default import mode
puts ``tests/`` on ``sys.path``.
"""

from __future__ import annotations

import re

from packaging.requirements import Requirement
from packaging.specifiers import Specifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

# pip strips "#" to end of line when it starts the line or follows
# whitespace; "pypdf>=6.19.0  # note" is a valid requirements line.
INLINE_COMMENT = re.compile(r"(^|\s)#.*$")


def parse_line(line: str) -> Requirement | None:
    s = INLINE_COMMENT.sub("", line).strip()
    return Requirement(s) if s else None


def parse_requirements_text(text: str) -> dict[str, Requirement]:
    """Map PEP 503 name -> Requirement, failing on a repeated name."""
    out: dict[str, Requirement] = {}
    for line in text.splitlines():
        req = parse_line(line)
        if req is None:
            continue
        name = canonicalize_name(req.name)
        assert name not in out, f"{req.name} listed twice"
        out[name] = req
    return out


def lowest_admitted(clause: Specifier) -> Version | None:
    """Lowest version ``clause`` can admit, or None if it has no floor.

    ``==X.*`` admits X's dev and pre-releases, which sort below X, so its
    floor is ``X.dev0``. Every other bounding operator admits nothing
    below its own version (``>X`` admits nothing at or below X).
    """
    if clause.operator in ("<", "<=", "!="):
        return None
    ver = clause.version
    if ver.endswith(".*"):
        ver = ver[:-2] + ".dev0"
    try:
        return Version(ver)
    except InvalidVersion:
        return None  # "===" with a non-PEP 440 string


def floor_of(spec: SpecifierSet) -> Version | None:
    """The highest clause floor in ``spec``, or None if no clause has one.

    Clauses are ANDed, so the highest floor is the one that binds.
    """
    floors = [f for f in map(lowest_admitted, spec) if f is not None]
    return max(floors) if floors else None
