"""Consistency tests for the three files that pin Python dependencies.

The Flatpak build is driven by ``flatpak/python-modules.yml``, which has
**zero references anywhere in .github/**: no workflow audits it and no
workflow regenerates it. ``security-deps.yml`` audits
``flatpak/requirements-pinned.txt`` instead, so the wheel list can drift
away from the pin file and CI stays green while the shipped Flatpak
installs a different (possibly vulnerable) version. That is exactly how
``pypdf`` stayed at 6.14.2 in the Flatpak with six known CVEs while the
root ``requirements.txt`` had already moved on.

These tests close that loop without needing network access or pip-audit:
they assert the three files agree with each other.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from _requirements_parsing import floor_of, parse_requirements_text
from packaging.version import Version

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a dev dependency
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
PINNED = ROOT / "flatpak" / "requirements-pinned.txt"
MODULES = ROOT / "flatpak" / "python-modules.yml"
FLATPAK_README = ROOT / "flatpak" / "README.md"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"

# Packages the Flatpak deliberately does not ship: PyInstaller only
# builds the Windows executable, and the rest are the still-missing
# converters documented in flatpak/README.md. Listing them here keeps
# the parity test honest about what is knowingly absent instead of
# silently ignoring every mismatch.
FLATPAK_OMITTED = {
    "pyinstaller",
    "python-pptx",
    "openpyxl",
    "beautifulsoup4",
    "ebooklib",
    "lxml",
    "urllib3",
    "idna",
}


def _normalise(name: str) -> str:
    """PEP 503 normalisation, so ``PySide6``/``pyside6`` compare equal."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def _parse_requirements(path: Path) -> dict[str, str]:
    """Map normalised package name -> version specifier text."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.\-]*)\s*(.*)$", s)
        assert m, f"unparsable requirement line in {path.name}: {line!r}"
        out[_normalise(m.group(1))] = m.group(2)
    return out


def _load_modules() -> dict:
    if yaml is None:
        pytest.skip("PyYAML not available")
    with MODULES.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _wheel_versions() -> dict[str, str]:
    """Map normalised package name -> version, read from wheel filenames.

    Wheel names are ``{distribution}-{version}(-{build})?-{tags}.whl``
    per PEP 427, so the first two dash-separated fields are all we need.
    """
    data = _load_modules()
    out: dict[str, str] = {}
    for source in data["sources"]:
        filename = source["url"].rsplit("/", 1)[-1]
        assert filename.endswith(".whl"), f"non-wheel source: {filename}"
        dist, version = filename[: -len(".whl")].split("-")[:2]
        out[_normalise(dist)] = version
    return out


def test_pinned_file_and_wheel_list_cover_the_same_packages():
    pinned = set(_parse_requirements(PINNED))
    wheels = set(_wheel_versions())
    assert pinned == wheels, (
        "flatpak/requirements-pinned.txt and flatpak/python-modules.yml "
        "list different packages; regenerate the wheel list with "
        "req2flatpak (see flatpak/README.md).\n"
        f"only in pin file: {sorted(pinned - wheels)}\n"
        f"only in wheel list: {sorted(wheels - pinned)}"
    )


def test_wheel_versions_match_the_pinned_versions():
    pinned = _parse_requirements(PINNED)
    wheels = _wheel_versions()
    mismatches = []
    for name, spec in pinned.items():
        m = re.fullmatch(r"==\s*(.+)", spec)
        assert m, f"{name} must be pinned with '==' in {PINNED.name}, got {spec!r}"
        want = m.group(1).strip()
        got = wheels.get(name)
        if got != want:
            mismatches.append(f"{name}: pin={want} wheel={got}")
    assert not mismatches, (
        "flatpak/python-modules.yml ships versions that differ from "
        "flatpak/requirements-pinned.txt, so pip-audit on the pin file "
        "does not describe what the Flatpak actually installs:\n"
        + "\n".join(mismatches)
    )


def test_build_command_installs_every_pinned_package():
    data = _load_modules()
    command = " ".join(data["build-commands"])
    listed = {
        _normalise(tok)
        for tok in command.split("--no-build-isolation", 1)[1].split()
    }
    assert listed == set(_parse_requirements(PINNED)), (
        "the pip3 install command in python-modules.yml does not name the "
        "same packages as requirements-pinned.txt; a wheel present in "
        "sources but absent from the command is downloaded and never "
        "installed."
    )


def _stale_pins(root_text: str, pin_text: str) -> list[str]:
    """Flatpak pins below their requirements.txt floor, one line each.

    Fail-closed: a root line this check cannot judge (an environment
    marker, no floor at all) or a pin that is not an exact ``==`` is
    reported too. Skipping such lines would be fail-open: a floor raised
    as ``pypdf>=6.99.0  # note`` would then let a 6.19.0 pin pass.
    """
    root = parse_requirements_text(root_text)
    problems = []
    for name, pin in parse_requirements_text(pin_text).items():
        req = root.get(name)
        if req is None:
            continue  # e.g. shiboken6, a PySide6 transitive not pinned at root
        if req.marker is not None:
            problems.append(
                f"{name}: requirements.txt '{req}' carries an environment "
                "marker, so its floor does not hold everywhere"
            )
            continue
        floor = floor_of(req.specifier)
        if floor is None:
            problems.append(f"{name}: requirements.txt '{req}' has no floor")
            continue
        clauses = list(pin.specifier)
        if (
            len(clauses) != 1
            or clauses[0].operator != "=="
            or clauses[0].version.endswith(".*")
        ):
            problems.append(f"{name}: flatpak pin '{pin}' is not an exact '==' pin")
            continue
        got = Version(clauses[0].version)
        if got < floor:
            problems.append(f"{name}: flatpak pin {got} < requirements floor {floor}")
    return problems


_SAMPLE_PINS = "PySide6==6.11.1\nshiboken6==6.11.1\npypdf==6.19.0\n"


@pytest.mark.parametrize(
    ("root_line", "expected"),
    [
        ("pypdf>=6.99.0  # note", "< requirements floor 6.99.0"),
        ('pypdf>=6.99.0; sys_platform != "emscripten"', "environment marker"),
        ("PySide6~=6.11.2", "< requirements floor 6.11.2"),
        ("PySide6<6.12,>=6.11.2", "< requirements floor 6.11.2"),
        ("PySide6>=6.11.1,<6.12  # cap", None),
        ("pypdf>=6.19.0", None),
        ("pypdf>=6.19.1", "< requirements floor 6.19.1"),
        ("pypdf>=6.0,>=6.99.0", "< requirements floor 6.99.0"),
        ("PySide6<6.12", "has no floor"),
        ("pypdf", "has no floor"),
    ],
)
def test_stale_pins_flags_stale_and_unjudgeable_root_lines(root_line, expected):
    problems = _stale_pins(root_line, _SAMPLE_PINS)
    if expected is None:
        assert problems == []
    else:
        assert len(problems) == 1 and expected in problems[0], problems


@pytest.mark.parametrize("pin", [">=6.19.0", "==6.19.*", "", "==6.19.0,<7"])
def test_stale_pins_rejects_a_pin_that_is_not_exact(pin):
    problems = _stale_pins("pypdf>=6.19.0", f"pypdf{pin}")
    assert len(problems) == 1 and "not an exact" in problems[0], problems


@pytest.mark.parametrize("ceiling", ["", ",<6.12"])
def test_stale_pins_accepts_the_real_files_with_and_without_a_ceiling(ceiling):
    real = REQUIREMENTS.read_text(encoding="utf-8")
    floor = floor_of(parse_requirements_text(real)["pyside6"].specifier)
    root_text, n = re.subn(
        r"(?m)^PySide6\b.*$", f"PySide6>={floor}{ceiling}", real
    )
    assert n == 1
    assert _stale_pins(root_text, PINNED.read_text(encoding="utf-8")) == []


def test_flatpak_pins_satisfy_the_root_requirements_floor():
    """Every Flatpak pin must be >= the floor in requirements.txt.

    Without this, a security bump to requirements.txt can land while the
    Flatpak keeps installing the vulnerable version.
    """
    problems = _stale_pins(
        REQUIREMENTS.read_text(encoding="utf-8"),
        PINNED.read_text(encoding="utf-8"),
    )
    assert not problems, "\n".join(problems)


def test_no_root_dependency_is_silently_dropped_from_the_flatpak():
    """Guard the *known* gap in flatpak/README.md against growing.

    New runtime deps must either be added to the Flatpak pins or listed
    explicitly in FLATPAK_OMITTED, so an omission is a deliberate,
    reviewed decision rather than an oversight nobody noticed.
    """
    root = set(_parse_requirements(REQUIREMENTS))
    pinned = set(_parse_requirements(PINNED))
    unaccounted = root - pinned - {_normalise(n) for n in FLATPAK_OMITTED}
    assert not unaccounted, (
        "these requirements.txt packages are neither pinned for the "
        "Flatpak nor listed as deliberately omitted: "
        f"{sorted(unaccounted)}"
    )


def test_cryptography_is_pinned_for_the_flatpak():
    """pypdf needs cryptography for AES; it is only an optional extra.

    pypdf declares cryptography under the ``crypto``/``full`` extras, so
    a --no-index install of the bare ``pypdf`` wheel resolves
    ``pypdf._crypt_providers`` to the pure-Python fallback, whose
    CryptAES raises DependencyError. The app requests AES-256 in
    app/tools/encrypt.py and app/editor/tab.py, so without this pin
    encrypting and opening AES PDFs is broken inside the Flatpak only.
    """
    assert "cryptography" in _parse_requirements(PINNED)
    assert "cryptography" in _wheel_versions()


def test_flatpak_readme_documents_every_omitted_package():
    """FLATPAK_OMITTED is canonical; the README must not drift from it.

    The README previously listed only four of the omitted packages, which
    hid the fact that ``lxml`` is a *build* blocker (a hard dependency of
    the pinned ``python-docx``) and not just another missing converter.
    """
    status = FLATPAK_README.read_text(encoding="utf-8").split(
        "**Before submitting to Flathub**", 1
    )[0]
    undocumented = [n for n in sorted(FLATPAK_OMITTED) if f"`{n}`" not in status]
    assert not undocumented, (
        "flatpak/README.md does not mention these deliberately omitted "
        f"packages: {undocumented}"
    )


def test_dependabot_does_not_cover_the_flatpak_directory():
    """Pin the assumption the README now states.

    The README used to claim Dependabot bumped shared packages inside
    ``flatpak/``. It does not: the ``pip`` ecosystem is declared only for
    ``directory: "/"``. If a ``/flatpak`` entry is ever added, this test
    fails so the README stops being wrong in the other direction.
    """
    if yaml is None:
        pytest.skip("PyYAML not available")
    with DEPENDABOT.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    pip_dirs = {
        u.get("directory")
        for u in cfg["updates"]
        if u.get("package-ecosystem") == "pip"
    }
    assert pip_dirs == {"/"}, (
        "dependabot pip coverage changed; update the claim in "
        f"flatpak/README.md. Directories: {sorted(pip_dirs)}"
    )
