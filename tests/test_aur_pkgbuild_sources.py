"""Guards on the AUR PKGBUILDs under ``aur/`` and the ``.SRCINFO`` next to them.

Why these exist: ``pdfapps-bin`` 1.15.1 failed ``makepkg`` with
``pdfapps.metainfo.xml ... FAILED`` for users upgrading from 1.15.0 even
though every URL was pinned to the ``v$pkgver`` tag and every declared
sha256 matched what GitHub serves. The auxiliary sources were saved under
version-less names (``pdfapps.metainfo.xml``), and makepkg reuses a file of
that name already sitting in the build dir or ``$SRCDEST`` (an AUR helper's
cache keeps the 1.15.0 one) instead of downloading it again. The metainfo is
the one auxiliary file that changes every release (a new ``<release>``
entry), so it was the one that failed; the others were byte-identical
between 1.15.0 and 1.15.1 and passed by luck.

So the invariants are: every remote source is pinned to the release tag (or a
commit), never a branch; every source is saved under a name that carries the
version; ``.SRCINFO`` says the same as the PKGBUILD; ``package()`` installs
exactly the files it declared; and the release bump keeps all of that true.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
AUR_DIR = REPO_ROOT / "aur"
PACKAGES = ("pdfapps", "pdfapps-bin")
REPO_SLUG = "nelsonduarte/PDFApps"

_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=([^(\n].*)$", re.MULTILINE)
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _expand(text: str, variables: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(2)
        if name not in variables:
            raise AssertionError(f"PKGBUILD references undefined ${name}")
        return variables[name]

    return _VAR_RE.sub(sub, text)


def _pkgbuild_vars(text: str) -> dict[str, str]:
    variables: dict[str, str] = {}
    for name, raw in _ASSIGN_RE.findall(text):
        variables[name] = _expand(_unquote(raw), variables)
    return variables


def _pkgbuild_array(text: str, name: str) -> list[str]:
    m = re.search(rf"^{name}=\((.*?)\)", text, flags=re.MULTILINE | re.DOTALL)
    assert m, f"no {name}=(...) array in PKGBUILD"
    return [a or b for a, b in re.findall(r"\"([^\"]*)\"|'([^']*)'", m.group(1))]


def _parse_pkgbuild(text: str) -> tuple[dict[str, str], list[str]]:
    variables = _pkgbuild_vars(text)
    sources = [_expand(s, variables) for s in _pkgbuild_array(text, "source")]
    return variables, sources


def _parse_srcinfo(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        if " = " not in line:
            continue
        key, _, value = line.strip().partition(" = ")
        out.setdefault(key, []).append(value)
    return out


def _split_source(entry: str) -> tuple[str | None, str]:
    name, sep, url = entry.partition("::")
    return (name, url) if sep else (None, entry)


def _pinned_ref_problem(url: str, pkgver: str) -> str | None:
    """Return why ``url`` is not pinned to the release, or None if it is."""
    tag = f"v{pkgver}"
    commit = r"[0-9a-f]{40}"
    raw = re.fullmatch(
        rf"https://raw\.githubusercontent\.com/{REPO_SLUG}/([^/]+)/.+", url
    )
    if raw:
        ref = raw.group(1)
        if ref == tag or re.fullmatch(commit, ref):
            return None
        return f"raw file served from ref {ref!r}, not {tag!r} or a commit"
    asset = re.fullmatch(
        rf"https://github\.com/{REPO_SLUG}/releases/download/([^/]+)/[^/]+", url
    )
    if asset:
        return None if asset.group(1) == tag else f"release asset of {asset.group(1)!r}"
    archive = re.fullmatch(
        rf"https://github\.com/{REPO_SLUG}/archive/(?:refs/tags/)?([^/]+)\.tar\.gz", url
    )
    if archive:
        ref = archive.group(1)
        if ref == tag or re.fullmatch(commit, ref):
            return None
        return f"archive of ref {ref!r}, not {tag!r} or a commit"
    return "not a recognised tag- or commit-pinned GitHub URL (branch?)"


def _read(package: str, name: str) -> str:
    return (AUR_DIR / package / name).read_text(encoding="utf-8")


# ── pure checks on the helpers, so a broken parser cannot pass vacuously ──


@pytest.mark.parametrize(
    "url",
    [
        f"https://raw.githubusercontent.com/{REPO_SLUG}/main/LICENSE",
        f"https://raw.githubusercontent.com/{REPO_SLUG}/master/x.png",
        f"https://raw.githubusercontent.com/{REPO_SLUG}/refs/heads/main/x.svg",
        f"https://raw.githubusercontent.com/{REPO_SLUG}/v1.0.0/x.svg",
        f"https://github.com/{REPO_SLUG}/archive/refs/heads/main.tar.gz",
        f"https://github.com/{REPO_SLUG}/archive/main.tar.gz",
        f"https://github.com/{REPO_SLUG}/releases/latest/download/PDFApps-Linux.tar.gz",
        f"https://github.com/{REPO_SLUG}/releases/download/v1.0.0/PDFApps-Linux.tar.gz",
    ],
)
def test_pin_check_rejects_branches_and_other_versions(url: str) -> None:
    assert _pinned_ref_problem(url, "1.15.1") is not None


@pytest.mark.parametrize(
    "url",
    [
        f"https://raw.githubusercontent.com/{REPO_SLUG}/v1.15.1/data/a.metainfo.xml",
        f"https://raw.githubusercontent.com/{REPO_SLUG}/{'a' * 40}/LICENSE",
        f"https://github.com/{REPO_SLUG}/releases/download/v1.15.1/PDFApps-Linux.tar.gz",
        f"https://github.com/{REPO_SLUG}/archive/refs/tags/v1.15.1.tar.gz",
    ],
)
def test_pin_check_accepts_tag_and_commit(url: str) -> None:
    assert _pinned_ref_problem(url, "1.15.1") is None


def test_parser_expands_variables_and_both_quote_styles() -> None:
    text = (
        "pkgname=foo-bin\n_pkgname=foo\npkgver=2.0.0\n"
        'source=(\n    "$_pkgname-$pkgver.png::https://x/v${pkgver}/a.png"\n'
        "    'LICENSE::https://x/LICENSE'\n)\n"
    )
    variables, sources = _parse_pkgbuild(text)
    assert variables["pkgver"] == "2.0.0"
    assert sources == [
        "foo-2.0.0.png::https://x/v2.0.0/a.png",
        "LICENSE::https://x/LICENSE",
    ]


# ── the real PKGBUILDs ──


@pytest.mark.parametrize("package", PACKAGES)
def test_every_source_is_pinned_to_the_release_tag(package: str) -> None:
    variables, sources = _parse_pkgbuild(_read(package, "PKGBUILD"))
    pkgver = variables["pkgver"]
    assert sources
    problems = {
        s: _pinned_ref_problem(_split_source(s)[1], pkgver) for s in sources
    }
    assert not {s: p for s, p in problems.items() if p}, problems


@pytest.mark.parametrize("package", PACKAGES)
def test_srcinfo_sources_are_pinned_to_the_release_tag(package: str) -> None:
    info = _parse_srcinfo(_read(package, ".SRCINFO"))
    (pkgver,) = info["pkgver"]
    problems = {
        s: _pinned_ref_problem(_split_source(s)[1], pkgver) for s in info["source"]
    }
    assert not {s: p for s, p in problems.items() if p}, problems


@pytest.mark.parametrize("package", PACKAGES)
def test_every_source_is_saved_under_a_versioned_name(package: str) -> None:
    """The 1.15.1 failure: a version-less local name lets makepkg reuse the
    copy an earlier version left behind, which then fails its checksum."""
    variables, sources = _parse_pkgbuild(_read(package, "PKGBUILD"))
    pkgver = variables["pkgver"]
    bad = [s for s in sources if pkgver not in (_split_source(s)[0] or "")]
    assert not bad, f"sources saved under a name without {pkgver}: {bad}"


@pytest.mark.parametrize("package", PACKAGES)
def test_srcinfo_matches_pkgbuild(package: str) -> None:
    variables, sources = _parse_pkgbuild(_read(package, "PKGBUILD"))
    info = _parse_srcinfo(_read(package, ".SRCINFO"))
    assert info["pkgver"] == [variables["pkgver"]]
    assert info["pkgrel"] == [variables["pkgrel"]]
    assert info["source"] == sources
    assert len(info["sha256sums"]) == len(sources)
    assert len(_pkgbuild_array(_read(package, "PKGBUILD"), "sha256sums")) == len(sources)


# The AUR web page and helpers resolve dependencies and verify downloads from
# the .SRCINFO, makepkg from the PKGBUILD, so a value that differs between the
# two (not just a count) gives one answer to the helper and another to makepkg.
_PARITY_ARRAYS = ("sha256sums", "depends", "optdepends")


def _srcinfo_drift(pkgbuild_text: str, srcinfo_text: str) -> dict[str, tuple[list[str], list[str]]]:
    """Arrays whose values differ between PKGBUILD and .SRCINFO, in order."""
    info = _parse_srcinfo(srcinfo_text)
    drift = {}
    for name in _PARITY_ARRAYS:
        has_array = re.search(rf"^{name}=\(", pkgbuild_text, flags=re.MULTILINE)
        ours = _pkgbuild_array(pkgbuild_text, name) if has_array else []
        theirs = info.get(name, [])
        if ours != theirs:
            drift[name] = (ours, theirs)
    return drift


@pytest.mark.parametrize("package", PACKAGES)
def test_srcinfo_values_match_pkgbuild(package: str) -> None:
    drift = _srcinfo_drift(_read(package, "PKGBUILD"), _read(package, ".SRCINFO"))
    assert not drift, f"PKGBUILD vs .SRCINFO (PKGBUILD, .SRCINFO): {drift}"


def _mutate_first_sha(text: str, sha: str) -> str:
    flipped = sha[:-1] + ("0" if sha[-1] != "0" else "1")
    assert text.count(sha) == 1
    return text.replace(sha, flipped)


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("side", ["PKGBUILD", ".SRCINFO"])
def test_drift_check_catches_a_sha_changed_on_one_side_only(package: str, side: str) -> None:
    pkgbuild, srcinfo = _read(package, "PKGBUILD"), _read(package, ".SRCINFO")
    sha = _parse_srcinfo(srcinfo)["sha256sums"][0]
    if side == "PKGBUILD":
        pkgbuild = _mutate_first_sha(pkgbuild, sha)
    else:
        srcinfo = _mutate_first_sha(srcinfo, sha)
    assert set(_srcinfo_drift(pkgbuild, srcinfo)) == {"sha256sums"}


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("side", ["PKGBUILD", ".SRCINFO"])
def test_drift_check_catches_a_depend_on_one_side_only(package: str, side: str) -> None:
    pkgbuild, srcinfo = _read(package, "PKGBUILD"), _read(package, ".SRCINFO")
    extra = "only-on-one-side"
    if side == "PKGBUILD":
        pkgbuild = re.sub(r"^depends=\(", f"depends=(\n    '{extra}'",
                          pkgbuild, count=1, flags=re.MULTILINE)
    else:
        srcinfo = srcinfo.replace("\tdepends = ", f"\tdepends = {extra}\n\tdepends = ", 1)
    assert set(_srcinfo_drift(pkgbuild, srcinfo)) == {"depends"}


_BIN_NEEDED = frozenset({
    "libxcb", "libxkbcommon-x11", "xcb-util-keysyms", "xcb-util-wm",
    "wayland", "libdrm", "ttf-font",
})


def _missing_bin_depends(depends: set[str]) -> set[str]:
    """What ``depends`` lacks for the 1.15.1 bundle, measured with ldd on
    every embedded .so (Arch WSL): QtGui links libGL.so.1 and libEGL.so.1;
    the xcb plugin links libxcb-icccm, libxcb-keysyms and libxkbcommon-x11;
    the wayland plugin libwayland-{client,cursor,egl}; linuxfb and eglfs-kms
    libdrm.so.2. None of these is embedded by PyInstaller. ``ttf-font`` is
    there because fontconfig ships no font: on a minimal Arch the UI comes
    up in a fallback font with broken spacing.

    GL is satisfied by ``libglvnd`` or by the ``libgl`` + ``libegl`` virtuals
    it provides (qt6-base spells it ``libgl``), but never by ``libgl`` alone:
    that would admit a provider without libEGL.so.1, which QtGui also needs.
    """
    missing = set(_BIN_NEEDED - depends)
    if "libglvnd" not in depends and not {"libgl", "libegl"} <= depends:
        missing.add("libglvnd (or libgl + libegl)")
    return missing


@pytest.mark.parametrize(
    ("swap", "ok"),
    [
        ({"libglvnd"}, True),
        ({"libgl", "libegl"}, True),
        ({"libgl"}, False),
        (set(), False),
    ],
)
def test_bin_gl_requirement_accepts_only_providers_of_both_libs(swap: set[str], ok: bool) -> None:
    assert (not _missing_bin_depends(set(_BIN_NEEDED) | swap)) is ok


@pytest.mark.parametrize("dropped", sorted(_BIN_NEEDED))
def test_bin_depends_check_notices_each_dropped_package(dropped: str) -> None:
    depends = (set(_BIN_NEEDED) | {"libglvnd"}) - {dropped}
    assert _missing_bin_depends(depends) == {dropped}


def test_bin_package_needs_the_libraries_the_bundle_does_not_carry() -> None:
    """Without libglvnd the binary dies at import with ``libGL.so.1: cannot
    open shared object file``; see ``_missing_bin_depends`` for the rest."""
    depends = set(_pkgbuild_array(_read("pdfapps-bin", "PKGBUILD"), "depends"))
    missing = _missing_bin_depends(depends)
    assert not missing, missing


def test_bin_package_suggests_xdg_utils_for_the_open_folder_buttons() -> None:
    """app/base.py runs ``xdg-open`` for "open folder" / "show file" and
    swallows the OSError, so without xdg-utils those buttons do nothing."""
    optdepends = _pkgbuild_array(_read("pdfapps-bin", "PKGBUILD"), "optdepends")
    assert any(o.split(":", 1)[0].strip() == "xdg-utils" for o in optdepends), optdepends


def test_bin_package_installs_exactly_the_auxiliary_sources_it_declares() -> None:
    """Renaming a source without updating ``package()`` would install nothing
    (``install`` fails on a missing ``$srcdir`` file); declaring one that is
    never installed is dead weight. The binary itself comes out of the
    tarball, so it is the one allowed ``$srcdir`` path that is not a source."""
    text = _read("pdfapps-bin", "PKGBUILD")
    variables, sources = _parse_pkgbuild(text)
    body = text[text.index("package()"):]
    used = {
        _expand(m, variables)
        for m in re.findall(r'"\$srcdir/([^"]+)"', body)
    }
    tarball_contents = {"PDFApps"}
    aux = {
        _split_source(s)[0]
        for s in sources
        if not _split_source(s)[0].endswith(".tar.gz")
    }
    assert used - tarball_contents == aux


# ── the shared desktop file and metainfo must exist where consumers look ──

# They lived in flatpak/ until the Flatpak was retired (D8) and moved to
# data/. pdfapps-bin fetches them from the release tag, pdfapps installs
# them from the tag's source tarball and the snap copies them from the
# tag's checkout, so a consumer left on the old path only breaks after
# the next release is cut.
_DESKTOP_DATA = (
    "data/io.github.nelsonduarte.PDFApps.desktop",
    "data/io.github.nelsonduarte.PDFApps.metainfo.xml",
)


def _raw_paths(sources: list[str], pkgver: str) -> list[str]:
    prefix = f"https://raw.githubusercontent.com/{REPO_SLUG}/v{pkgver}/"
    return [
        url[len(prefix):]
        for url in (_split_source(s)[1] for s in sources)
        if url.startswith(prefix)
    ]


def _repo_paths_fetched_by_bin() -> list[str]:
    variables, sources = _parse_pkgbuild(_read("pdfapps-bin", "PKGBUILD"))
    return _raw_paths(sources, variables["pkgver"])


def test_bin_package_fetches_files_that_exist_at_the_tag() -> None:
    """The raw URLs resolve against the tag, whose tree is this one."""
    paths = _repo_paths_fetched_by_bin()
    assert set(_DESKTOP_DATA) <= set(paths), paths
    assert not [p for p in paths if not (REPO_ROOT / p).is_file()], paths


def test_bin_srcinfo_fetches_the_same_paths_as_the_pkgbuild() -> None:
    info = _parse_srcinfo(_read("pdfapps-bin", ".SRCINFO"))
    (pkgver,) = info["pkgver"]
    assert _raw_paths(info["source"], pkgver) == _repo_paths_fetched_by_bin()


def test_source_package_installs_files_that_exist_in_the_tarball() -> None:
    body = _read("pdfapps", "PKGBUILD")
    installed = re.findall(r"install -Dm644 (\S+) ", body)
    assert set(_DESKTOP_DATA) <= set(installed), installed
    assert not [p for p in installed if not (REPO_ROOT / p).is_file()], installed


def test_snap_copies_the_desktop_file_and_metainfo_from_data() -> None:
    snap = (REPO_ROOT / "snap" / "snapcraft.yaml").read_text(encoding="utf-8")
    copied = re.findall(
        r"^\s*cp (\S+\.(?:desktop|metainfo\.xml)) \\$", snap, flags=re.MULTILINE
    )
    assert sorted(copied) == sorted(_DESKTOP_DATA), copied


def test_publish_hashes_the_files_pdfapps_bin_fetches() -> None:
    """publish.yml recomputes the sha256sums from raw URLs of its own; a
    path there that differs from the PKGBUILD hashes a 404 instead."""
    publish = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    hashed = re.findall(
        rf"https://raw\.githubusercontent\.com/{REPO_SLUG}/v\$\{{VER\}}/([^\"]+)\"",
        publish,
    )
    assert hashed == _repo_paths_fetched_by_bin()


# ── the release bump must keep the .SRCINFO consistent ──


def _load_bump_script() -> str:
    spec = importlib.util.spec_from_file_location(
        "_release_bump_helpers", REPO_ROOT / "tests" / "test_release_bump_script.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module._extract_bump_script()


def test_release_bump_moves_every_bin_source_to_the_new_version(tmp_path: Path) -> None:
    """release.yml bumps aur/pdfapps-bin/.SRCINFO by regex. If it misses a
    versioned source name, the next release ships a .SRCINFO that disagrees
    with its PKGBUILD (the AUR web page and helpers read the .SRCINFO)."""
    target = tmp_path / "aur" / "pdfapps-bin"
    target.mkdir(parents=True)
    for name in ("PKGBUILD", ".SRCINFO"):
        (target / name).write_text(_read("pdfapps-bin", name), encoding="utf-8")
    old = _parse_srcinfo(_read("pdfapps-bin", ".SRCINFO"))["pkgver"][0]
    new = "98.76.54"
    assert old != new

    # Only the AUR files exist here, so the script exits 1 over the other
    # required targets being missing; it still rewrites the files it finds.
    subprocess.run(
        [sys.executable, "-c", _load_bump_script()],
        cwd=tmp_path,
        env={"OLD": old, "NEW": new, "PATH": "",
             "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")},
        capture_output=True,
        text=True,
    )

    variables, sources = _parse_pkgbuild((target / "PKGBUILD").read_text(encoding="utf-8"))
    info = _parse_srcinfo((target / ".SRCINFO").read_text(encoding="utf-8"))
    assert variables["pkgver"] == new
    assert info["pkgver"] == [new]
    assert info["source"] == sources
    assert not [s for s in info["source"] if old in s]
