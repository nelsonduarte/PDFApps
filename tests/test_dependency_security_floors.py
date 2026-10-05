"""Security floors in requirements.txt must exclude known-affected releases.

Why this is a test and not left to pip-audit: ``security-deps.yml`` runs
``pip-audit -r requirements.txt --strict``, and pip-audit resolves every
``>=`` requirement to the newest matching release before auditing it.
A floor that still admits a vulnerable release therefore audits clean
for as long as a fixed release exists upstream. Measured on 2026-10-05
with pip-audit 2.10.1: ``pypdf>=6.16.2`` reported no vulnerabilities
(it audited 6.19.0), while ``pypdf==6.16.2`` reported eight.

The floor still matters because every build resolves at build time:
the v1.15.0 binaries (build.yml run 34720950897, all four jobs) shipped
pypdf 6.18.1, which the 6.16.2 floor admitted and which carries three of
the advisories listed below.

What this does NOT catch: an advisory published after the table below
was measured. The test only knows the advisories it lists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import Specifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"

# PEP 503 name -> (first release from which every later release is clear
#                  of every advisory OSV lists for the package,
#                  releases OSV lists as affected that the floor must reject)
# Measured against api.osv.dev on 2026-10-05.
SECURITY_FLOORS = {
    # PYSEC-2026-4158 (fixed 6.17.0), PYSEC-2026-4153 (6.18.0),
    # PYSEC-2026-4154 / 4155 / 4156 (6.18.1),
    # PYSEC-2026-4157 / 4159 / 4160 (6.19.0).
    "pypdf": ("6.19.0", ("6.16.2", "6.17.0", "6.18.0", "6.18.1")),
    # GHSA-537c-gmf6-5ccf (fixed 48.0.1), PYSEC-2026-3553 / 3554 (49.0.0),
    # PYSEC-2026-3552 (introduced 44.0.0, fixed 50.0.0).
    "cryptography": ("50.0.0", ("48.0.0", "48.0.1", "49.0.0")),
    # PYSEC-2026-4175 / 4176 / 4177, all affecting 2.7.0, all fixed 2.8.0.
    "urllib3": ("2.8.0", ("2.6.2", "2.6.3", "2.7.0")),
    # PYSEC-2026-87 (XXE, fixed 6.1.0).
    "lxml": ("6.1.0", ("6.0.2", "6.0.4")),
    # PYSEC-2026-215 (fixed 3.15).
    "idna": ("3.15", ("3.13", "3.14")),
}

# pip strips "#" to end of line when it starts the line or follows
# whitespace; "pypdf>=6.19.0  # note" is a valid requirements line.
_INLINE_COMMENT = re.compile(r"(^|\s)#.*$")


def _parse_line(line: str) -> Requirement | None:
    s = _INLINE_COMMENT.sub("", line).strip()
    return Requirement(s) if s else None


def _requirements(text: str | None = None) -> dict[str, Requirement]:
    if text is None:
        text = REQUIREMENTS.read_text(encoding="utf-8")
    out: dict[str, Requirement] = {}
    for line in text.splitlines():
        req = _parse_line(line)
        if req is None:
            continue
        name = canonicalize_name(req.name)
        assert name not in out, f"{req.name} listed twice"
        out[name] = req
    return out


def _lowest_admitted(clause: Specifier) -> Version | None:
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


def _rejects_everything_below(spec: SpecifierSet, minimum: Version) -> bool:
    """True when some clause of ``spec`` admits nothing below ``minimum``.

    Clauses are ANDed, so one clause with a high enough floor suffices.
    This is operator-agnostic on purpose: ``==``, ``~=`` and ``>`` are as
    safe as ``>=`` when their floor clears the minimum.
    """
    floors = [f for f in map(_lowest_admitted, spec) if f is not None]
    return any(f >= minimum for f in floors)


def _assert_floor(req: Requirement, minimum: Version) -> None:
    # A marker makes pip skip the line wherever it evaluates false, so the
    # floor would not hold there, whatever the specifier says.
    assert req.marker is None, (
        f"requirements.txt '{req}' carries an environment marker; the "
        f"security floor must apply in every environment"
    )
    assert _rejects_everything_below(req.specifier, minimum), (
        f"requirements.txt '{req}' admits releases below {minimum}, the "
        f"first release clear of every known {req.name} advisory"
    )


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("pypdf>=6.19.0", True),
        ("pypdf>=6.19.0,<7", True),
        ("pypdf==6.19.0", True),
        ("pypdf~=6.19", True),
        ("pypdf>6.19.0", True),
        ("pypdf>=6.19.0  # pinned for PYSEC-2026-4157", True),
        ("pypdf>=6.20", True),
        ("pypdf[crypto]>=6.19.0", True),
        ("pypdf>=6.16.2", False),
        ("pypdf>=6.18.1", False),
        ("pypdf>6.18.1", False),  # still admits 6.18.1.post1
        ("pypdf>=6.19.0rc1", False),
        ("pypdf==6.19.*", False),  # admits 6.19.0rc1
        ("pypdf<7", False),
        ("pypdf!=6.18.1", False),
        ("pypdf!=6.20.0", False),  # excludes one release, admits all others
        ("pypdf", False),
        ('pypdf>=6.19.0 ; python_version<"3"', False),
        ('pypdf>=6.19.0 ; sys_platform=="win32"', False),
        ('pypdf>=6.19.0 ; python_version>="3"', False),
    ],
)
def test_floor_check_accepts_safe_forms_and_rejects_unsafe_ones(line, expected):
    req = _parse_line(line)
    if expected:
        _assert_floor(req, Version("6.19.0"))
    else:
        with pytest.raises(AssertionError):
            _assert_floor(req, Version("6.19.0"))


def test_requirement_names_are_pep503_normalised():
    reqs = _requirements("PyPDF>=6.19.0\nPython_Docx.x>=1.2.0  # c\n")
    assert set(reqs) == {"pypdf", "python-docx-x"}
    with pytest.raises(AssertionError, match="listed twice"):
        _requirements("python-docx>=1.2.0\nPython_Docx>=1.2.0\n")


@pytest.mark.parametrize("name", sorted(SECURITY_FLOORS))
def test_specifier_rejects_every_release_below_the_first_clean_one(name):
    minimum, _affected = SECURITY_FLOORS[name]
    req = _requirements().get(name)
    assert req is not None, f"{name} missing from requirements.txt"
    _assert_floor(req, Version(minimum))


@pytest.mark.parametrize("name", sorted(SECURITY_FLOORS))
def test_specifier_rejects_every_known_affected_release(name):
    _minimum, affected = SECURITY_FLOORS[name]
    req = _requirements().get(name)
    assert req is not None, f"{name} missing from requirements.txt"
    admitted = [v for v in affected if req.specifier.contains(v, prereleases=True)]
    assert not admitted, (
        f"requirements.txt '{req}' still admits affected releases {admitted}"
    )
