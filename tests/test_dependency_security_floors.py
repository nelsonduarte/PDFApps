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
the advisories listed below; the v1.15.1 ones (run 38148726512) shipped
pypdf 6.20.0 and Pillow 12.3.0.

A package may be split across lines by environment marker when its first
clean release cannot install everywhere (Pillow 13.0.0 needs Python
3.11, and the AppImage and the snap build on 3.10). Such a split must
give exactly one line in every environment, and each line must hold the
floor where it applies: the clean floor, or, only on the Python versions
the clean release cannot install on, the accepted residual floor in
RESIDUAL_FLOORS.

What this does NOT catch: an advisory published after the table below
was measured. The test only knows the advisories it lists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _requirements_parsing import TARGET_ENVIRONMENTS, applicable, target_environment
from _requirements_parsing import lowest_admitted as _lowest_admitted
from _requirements_parsing import parse_line as _parse_line
from _requirements_parsing import parse_requirement_lines, parse_requirements_text
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"

# PEP 503 name -> (first release from which every later release is clear
#                  of every advisory OSV lists for the package,
#                  releases OSV lists as affected that the floor must reject)
# Measured against api.osv.dev on 2026-10-05; pypdf and pillow again on
# 2026-10-28.
SECURITY_FLOORS = {
    # PYSEC-2026-4158 (fixed 6.17.0), PYSEC-2026-4153 (6.18.0),
    # PYSEC-2026-4154 / 4155 / 4156 (6.18.1),
    # PYSEC-2026-4157 / 4159 / 4160 (6.19.0),
    # GHSA-39mj-jf6j-2qj3 / GHSA-7mh2-4gg2-979f (6.20.0),
    # GHSA-9mx8-4j7g-633p / GHSA-qfv9-64jg-mh7p (6.20.1),
    # GHSA-6vvc-x485-93v7 / GHSA-cgf9-327m-v77c / GHSA-f54x-cmq8-qg57
    # (6.21.0), GHSA-5hx5-vpf9-5wcv (6.21.1), and the three HIGH
    # GHSA-6c7f-9265-g8fw / GHSA-jr96-gvgh-j3r4 / GHSA-gmh7-3g9r-mjh5
    # (6.21.2).
    "pypdf": (
        "6.21.2",
        ("6.16.2", "6.17.0", "6.18.0", "6.18.1", "6.19.0", "6.20.0",
         "6.20.1", "6.21.0", "6.21.1"),
    ),
    # 59 advisories against 12.3.0 (85 against 12.2.0), five CRITICAL,
    # every one fixed in 13.0.0.
    "pillow": ("13.0.0", ("12.2.0", "12.3.0")),
    # GHSA-537c-gmf6-5ccf (fixed 48.0.1), PYSEC-2026-3553 / 3554 (49.0.0),
    # PYSEC-2026-3552 (introduced 44.0.0, fixed 50.0.0).
    "cryptography": ("50.0.0", ("48.0.0", "48.0.1", "49.0.0")),
    # PYSEC-2026-4175 / 4176 / 4177, all affecting 2.7.0, all fixed 2.8.0.
    "urllib3": ("2.8.0", ("2.6.2", "2.6.3", "2.7.0")),
    # PYSEC-2026-87 (XXE, fixed 6.1.0).
    "lxml": ("6.1.0", ("6.0.2", "6.0.4")),
    # PYSEC-2026-215 (fixed 3.15).
    "idna": ("3.15", ("3.13", "3.14")),
    # PYSEC-2026-3071 / 3072 (fixed 2.8.4), PYSEC-2026-4170 / 4171 (fixed
    # 2.9; OSV writes it 2.9.0, PyPI publishes it as "2.9"). Measured on
    # 2026-10-16.
    "soupsieve": ("2.9", ("2.8.3", "2.8.4")),
}

# Accepted residuals, where the first clean release cannot be installed.
# PEP 503 name -> (Python versions the residual floor covers,
#                  Requires-Python of the first clean release, from PyPI,
#                  floor on those versions, releases it must still reject)
# test_residual_floors_cover_only_pythons_the_clean_release_excludes keeps
# the first two disjoint, so a residual cannot spread to a Python version
# that could install the fixed release.
RESIDUAL_FLOORS = {
    # Pillow 13.0.0 declares Requires-Python >=3.11 (PyPI, 2026-10-28).
    # 12.3.0 is the newest release 3.10 can install and carries fewer
    # advisories than 12.2.0.
    "pillow": (SpecifierSet("<3.11"), SpecifierSet(">=3.11"), "12.3.0",
               ("12.1.1", "12.2.0")),
}

# Every Python a source install could plausibly use, on every desktop
# platform, plus the build targets. A marker split is judged on all of
# them, not only on the targets, so a gap or overlap cannot hide in a
# version no build happens to use today.
SWEEP_ENVIRONMENTS = [
    target_environment(f"3.{minor}", platform)
    for minor in range(8, 21)
    for platform in ("win32", "darwin", "linux")
] + list(TARGET_ENVIRONMENTS.values())


def _requirements(text: str | None = None) -> dict[str, Requirement]:
    if text is None:
        text = REQUIREMENTS.read_text(encoding="utf-8")
    return parse_requirements_text(text)


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


def _floor_for(name: str, environment: dict[str, str]) -> tuple[str, tuple[str, ...]]:
    minimum, affected = SECURITY_FLOORS[name]
    residual = RESIDUAL_FLOORS.get(name)
    if residual is not None and residual[0].contains(environment["python_version"]):
        return residual[2], residual[3]
    return minimum, affected


def _floor_problems(text: str, name: str) -> tuple[list[str], list[str]]:
    """(problems with the floor, affected releases admitted), deduplicated.

    One line: it must carry no marker and hold the clean floor, as
    before. A marker split: in every environment of SWEEP_ENVIRONMENTS
    exactly one line must apply, and it must hold the floor for that
    environment.
    """
    lines = parse_requirement_lines(text).get(name)
    if not lines:
        return [f"{name} missing from requirements.txt"], []
    floor_problems: list[str] = []
    admitted: list[str] = []
    if len(lines) == 1:
        req = lines[0]
        minimum, affected = SECURITY_FLOORS[name]
        try:
            _assert_floor(req, Version(minimum))
        except AssertionError as exc:
            floor_problems.append(str(exc))
        admitted += [
            f"'{req}' admits {v}"
            for v in affected
            if req.specifier.contains(v, prereleases=True)
        ]
        return floor_problems, admitted
    for env in SWEEP_ENVIRONMENTS:
        where = f"Python {env['python_version']} on {env['sys_platform']}"
        kept = applicable(lines, env)
        if len(kept) != 1:
            floor_problems.append(f"{name}: {len(kept)} lines apply on {where}")
            continue
        req = kept[0]
        minimum, affected = _floor_for(name, env)
        if not _rejects_everything_below(req.specifier, Version(minimum)):
            floor_problems.append(
                f"'{req}' admits releases below {minimum} on {where}"
            )
        admitted += [
            f"'{req}' admits {v} on {where}"
            for v in affected
            if req.specifier.contains(v, prereleases=True)
        ]
    return list(dict.fromkeys(floor_problems)), list(dict.fromkeys(admitted))


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


_PILLOW_SPLIT = (
    'pillow>=13.0.0; python_version >= "3.11"\n'
    'pillow>=12.3.0; python_version < "3.11"\n'
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (_PILLOW_SPLIT, None),
        ("pillow>=13.0.0\n", None),
        ("pillow>=13.0.0,<14  # note\n", None),
        # Overlap: on 3.11 pip would be handed both lines.
        ('pillow>=13.0.0; python_version >= "3.11"\n'
         'pillow>=12.3.0; python_version < "3.12"\n',
         "2 lines apply on Python 3.11"),
        # Gap: nothing installs Pillow on 3.11.
        ('pillow>=13.0.0; python_version >= "3.12"\n'
         'pillow>=12.3.0; python_version < "3.11"\n',
         "0 lines apply on Python 3.11"),
        # The residual floor must not leak to versions 13.0.0 installs on.
        ('pillow>=12.3.0; python_version >= "3.11"\n'
         'pillow>=12.3.0; python_version < "3.11"\n',
         "below 13.0.0 on Python 3.11"),
        # Nor may the 3.10 line drop below the residual floor.
        ('pillow>=13.0.0; python_version >= "3.11"\n'
         'pillow>=12.2.0; python_version < "3.11"\n',
         "below 12.3.0 on Python 3.10"),
        # The residual is for old Pythons, not for a platform.
        ('pillow>=13.0.0; sys_platform != "win32"\n'
         'pillow>=12.3.0; sys_platform == "win32"\n',
         "below 13.0.0 on Python 3.14 on win32"),
        ("pillow>=12.3.0\n", "admits releases below 13.0.0"),
        ('pillow>=13.0.0; python_version >= "3.11"\n', "environment marker"),
        ("", "missing"),
    ],
)
def test_split_floor_check_requires_one_line_holding_the_floor_everywhere(
    text, expected
):
    floor_problems, _admitted = _floor_problems(text, "pillow")
    if expected is None:
        assert floor_problems == []
    else:
        assert any(expected in p for p in floor_problems), floor_problems


def test_split_floor_check_reports_affected_releases_per_environment():
    text = (
        'pillow>=13.0.0; python_version >= "3.11"\n'
        'pillow>=12.1.0; python_version < "3.11"\n'
    )
    _floor_problems_, admitted = _floor_problems(text, "pillow")
    assert any("admits 12.1.1 on Python 3.10" in a for a in admitted), admitted
    # Only the Python versions below 3.11, where the residual line applies.
    assert all(
        any(f" on Python {v} on " in a for v in ("3.8", "3.9", "3.10"))
        for a in admitted
    ), admitted


def test_a_repeated_line_without_a_marker_is_rejected():
    with pytest.raises(AssertionError, match="listed twice"):
        _floor_problems('pillow>=13.0.0\npillow>=12.3.0; python_version < "3.11"\n',
                        "pillow")


def test_requirement_names_are_pep503_normalised():
    reqs = _requirements("PyPDF>=6.19.0\nPython_Docx.x>=1.2.0  # c\n")
    assert set(reqs) == {"pypdf", "python-docx-x"}
    with pytest.raises(AssertionError, match="listed twice"):
        _requirements("python-docx>=1.2.0\nPython_Docx>=1.2.0\n")


def test_marker_split_resolves_to_one_line_per_environment():
    by_env = {
        label: parse_requirements_text(_PILLOW_SPLIT, environment=env)["pillow"]
        for label, env in TARGET_ENVIRONMENTS.items()
    }
    assert str(by_env["linux-py3.10"].specifier) == ">=12.3.0"
    for label in ("windows-py3.14", "macos-py3.14", "linux-py3.14", "flatpak-py3.12"):
        assert str(by_env[label].specifier) == ">=13.0.0", label
    # Without an environment there is no single Pillow requirement.
    assert "pillow" not in parse_requirements_text(_PILLOW_SPLIT)
    overlap = 'pillow>=13.0.0; python_version >= "3.10"\n' + _PILLOW_SPLIT.splitlines()[1]
    with pytest.raises(AssertionError, match="2 lines apply"):
        parse_requirements_text(overlap, environment=TARGET_ENVIRONMENTS["linux-py3.10"])


def test_residual_floors_cover_only_pythons_the_clean_release_excludes():
    for name, (covers, clean_requires, floor, _affected) in RESIDUAL_FLOORS.items():
        assert Version(floor) < Version(SECURITY_FLOORS[name][0]), name
        overlap = [
            env["python_version"]
            for env in SWEEP_ENVIRONMENTS
            if covers.contains(env["python_version"])
            and clean_requires.contains(env["python_version"])
        ]
        assert not overlap, (
            f"{name}: the residual floor {floor} covers Python {sorted(set(overlap))}, "
            f"where {SECURITY_FLOORS[name][0]} installs"
        )


def _residual_install_problems(text: str, name: str) -> list[str]:
    """Residual lines that no longer admit their own residual floor.

    The residual floor is the newest release those Python versions can
    install, so a line there that rejects it (Dependabot raising
    ``pillow>=12.3.0; python_version < "3.11"`` to 13.0.0, say) leaves
    pip with "No matching distribution": the AppImage job fails on the
    tag and the snap after the release, as tests/test_soupsieve_py310.py
    explains for soupsieve.
    """
    covers, _clean, floor, _affected = RESIDUAL_FLOORS[name]
    lines = parse_requirement_lines(text).get(name, [])
    problems = []
    for env in SWEEP_ENVIRONMENTS:
        if not covers.contains(env["python_version"]):
            continue
        for req in applicable(lines, env):
            if not req.specifier.contains(floor):
                problems.append(
                    f"'{req}' rejects {floor}, the newest {name} Python "
                    f"{env['python_version']} can install"
                )
    return list(dict.fromkeys(problems))


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        (_PILLOW_SPLIT, True),
        ('pillow>=13.0.0; python_version >= "3.11"\n'
         'pillow>=13.0.0; python_version < "3.11"\n', False),
        ("pillow>=13.0.0\n", False),
    ],
)
def test_residual_install_check(text, ok):
    assert (_residual_install_problems(text, "pillow") == []) is ok


@pytest.mark.parametrize("name", sorted(RESIDUAL_FLOORS))
def test_residual_lines_admit_a_release_their_python_can_install(name):
    problems = _residual_install_problems(
        REQUIREMENTS.read_text(encoding="utf-8"), name
    )
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("name", sorted(SECURITY_FLOORS))
def test_specifier_rejects_every_release_below_the_first_clean_one(name):
    floor_problems, _admitted = _floor_problems(
        REQUIREMENTS.read_text(encoding="utf-8"), name
    )
    assert not floor_problems, "\n".join(floor_problems)


@pytest.mark.parametrize("name", sorted(SECURITY_FLOORS))
def test_specifier_rejects_every_known_affected_release(name):
    _floor_problems_, admitted = _floor_problems(
        REQUIREMENTS.read_text(encoding="utf-8"), name
    )
    assert not admitted, (
        f"requirements.txt still admits affected releases: {admitted}"
    )
