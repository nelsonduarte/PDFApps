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


def target_environment(python_version: str, sys_platform: str) -> dict[str, str]:
    """A complete PEP 508 marker environment for one build target.

    Complete on purpose: ``Marker.evaluate`` fills any missing key from
    the interpreter running pytest, so a partial dict would make the
    result depend on the machine the suite happens to run on.
    """
    system, os_name, machine = {
        "win32": ("Windows", "nt", "AMD64"),
        "darwin": ("Darwin", "posix", "arm64"),
        "linux": ("Linux", "posix", "x86_64"),
    }[sys_platform]
    return {
        "implementation_name": "cpython",
        "implementation_version": f"{python_version}.0",
        "os_name": os_name,
        "platform_machine": machine,
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": system,
        "platform_version": "",
        "python_full_version": f"{python_version}.0",
        "python_version": python_version,
        "sys_platform": sys_platform,
    }


# Every environment that installs requirements.txt, keyed by a label
# used in test ids. The Python versions come from the workflows and
# manifests named below; when one of them moves, this table moves with it.
TARGET_ENVIRONMENTS = {
    # build.yml matrix; tests.yml and security-deps.yml also run 3.14,
    # on Linux.
    "windows-py3.14": target_environment("3.14", "win32"),
    "macos-py3.14": target_environment("3.14", "darwin"),
    "linux-py3.14": target_environment("3.14", "linux"),
    # The snap (base: core22, python3.10 in snap/snapcraft.yaml).
    "linux-py3.10": target_environment("3.10", "linux"),
}


def parse_line(line: str) -> Requirement | None:
    s = INLINE_COMMENT.sub("", line).strip()
    return Requirement(s) if s else None


def parse_requirement_lines(text: str) -> dict[str, list[Requirement]]:
    """Map PEP 503 name -> every line for it, in file order.

    A name may appear on more than one line only when every one of those
    lines carries an environment marker (a marker split, such as Pillow's
    Python 3.10 line). A repeated line without a marker fails.
    """
    out: dict[str, list[Requirement]] = {}
    for line in text.splitlines():
        req = parse_line(line)
        if req is None:
            continue
        out.setdefault(canonicalize_name(req.name), []).append(req)
    for reqs in out.values():
        if len(reqs) > 1:
            assert all(r.marker is not None for r in reqs), (
                f"{reqs[0].name} listed twice"
            )
    return out


def applicable(reqs: list[Requirement], environment: dict[str, str]) -> list[Requirement]:
    """The lines of ``reqs`` that pip installs in ``environment``."""
    return [r for r in reqs if r.marker is None or r.marker.evaluate(environment)]


def parse_requirements_text(
    text: str, environment: dict[str, str] | None = None
) -> dict[str, Requirement]:
    """Map PEP 503 name -> Requirement, failing on a repeated name.

    Without ``environment``, a marker-split name has no single
    requirement and is left out: a caller that needs it must pass an
    environment. With ``environment``, lines whose marker is false there
    are dropped and a kept line keeps its marker, so callers that reject
    markers still see it. More than one line applying in ``environment``
    fails, as pip would then be handed both.
    """
    out: dict[str, Requirement] = {}
    for name, reqs in parse_requirement_lines(text).items():
        if environment is None:
            if len(reqs) == 1:
                out[name] = reqs[0]
            continue
        kept = applicable(reqs, environment)
        assert len(kept) <= 1, (
            f"{reqs[0].name}: {len(kept)} lines apply in the same environment: "
            + "; ".join(str(r) for r in kept)
        )
        if kept:
            out[name] = kept[0]
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
