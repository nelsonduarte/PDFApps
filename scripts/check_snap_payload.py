"""Check the payload of a built PDFApps snap against what the app needs.

snap-build.yml runs this on the runner's own python3, after
``unsquashfs -ll <snap> > listing``, so it uses the standard library only.
Payload paths are handled as POSIX strings, never with os.path, because
the unit test runs on Windows too.

The Python version is not written here: it comes from the
``$SNAP/lib/pythonX.Y/`` paths in the manifest's app environment, so a
base change that forgets one of them fails here instead of shipping.

Every check that fails is reported, each with its own name, and the exit
status is 1. Exit status 0 means all of them passed. The snap size and
the installed distributions are printed for the record and never fail.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

LISTING_ROOT = "squashfs-root"
TESSDATA_FILES = (
    "eng.traineddata", "por.traineddata", "spa.traineddata",
    "fra.traineddata", "deu.traineddata", "pdf.ttf",
)
DESKTOP_FILE = "usr/share/applications/io.github.nelsonduarte.PDFApps.desktop"
METAINFO_FILE = "usr/share/metainfo/io.github.nelsonduarte.PDFApps.metainfo.xml"
# libxkbcommon compiles its default keymap from the "evdev" rules, and the
# manifest points XKB_CONFIG_ROOT at this tree because the base has none.
XKB_RULES = "usr/share/X11/xkb/rules/evdev"
APP_ENTRY = "usr/lib/pdfapps/pdfapps.py"
FONTS_CONF = "etc/fonts/fonts.conf"

# One line of ``unsquashfs -ll``: mode, owner/group, size (or a device's
# "major, minor"), date, time, then the path and, for a symlink, " -> target".
_LINE = re.compile(
    r"^(?P<mode>[-dlbcps][-rwxsStT]{9})\s+\S+\s+(?:\d+|\d+,\s*\d+)\s+"
    r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s(?P<rest>.+)$"
)
_MANIFEST_PYTHON = re.compile(r"\$SNAP/lib/python(\d+\.\d+)/")
# The four app environment entries that point into the venv.
MIN_MANIFEST_PYTHON_PATHS = 4


# A NamedTuple, not a dataclass: the test loads this file with
# spec_from_file_location and no sys.modules entry, and dataclasses then
# fail to resolve the string annotations.
class Entry(NamedTuple):
    kind: str  # first character of the mode: "d", "-", "l", ...
    target: str | None  # symlink target, else None


def python_version_from_manifest(text: str) -> str:
    """The X.Y the manifest's ``$SNAP/lib/pythonX.Y/`` paths agree on."""
    found = _MANIFEST_PYTHON.findall(text)
    if not found:
        raise ValueError("manifest: no $SNAP/lib/pythonX.Y/ path found")
    distinct = sorted(set(found))
    if len(distinct) != 1:
        raise ValueError(
            "manifest: $SNAP/lib/pythonX.Y/ paths disagree: " + ", ".join(distinct))
    if len(found) < MIN_MANIFEST_PYTHON_PATHS:
        raise ValueError(
            f"manifest: {len(found)} $SNAP/lib/python{distinct[0]}/ path(s), "
            f"expected at least {MIN_MANIFEST_PYTHON_PATHS}")
    return distinct[0]


def parse_listing(text: str) -> dict[str, Entry]:
    """Payload paths, relative to the snap root, from ``unsquashfs -ll``.

    Lines that are not entries (a header, a blank line) are skipped; a
    format this does not read leaves the result empty and every check
    fails, instead of passing.
    """
    entries: dict[str, Entry] = {}
    prefix = LISTING_ROOT + "/"
    for line in text.splitlines():
        m = _LINE.match(line)
        if m is None:
            continue
        kind, rest = m.group("mode")[0], m.group("rest")
        target = None
        if kind == "l" and " -> " in rest:
            rest, target = rest.split(" -> ", 1)
        if not rest.startswith(prefix):
            continue
        entries[rest[len(prefix):]] = Entry(kind, target)
    return entries


def _versions(entries: dict[str, Entry], pattern: str) -> set[str]:
    rx = re.compile(pattern)
    return {m.group(1) for p in entries if (m := rx.fullmatch(p))}


def check_payload(
    entries: dict[str, Entry], py: str,
) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """``(failures, facts)``: each failure is ``(check name, message)``."""
    failures: list[tuple[str, str]] = []
    facts: dict[str, str] = {}

    def fail(name: str, message: str) -> None:
        failures.append((name, message))

    if not entries:
        fail("listing", "no squashfs-root/ entry could be read from the listing")

    qxcb = f"lib/python{py}/site-packages/PySide6/Qt/plugins/platforms/libqxcb.so"
    if qxcb not in entries:
        fail("qt-xcb-plugin", f"missing {qxcb}")

    other_pythons = sorted(
        p for p in entries
        if re.fullmatch(r"lib/python[^/]*", p) and p != f"lib/python{py}")
    if other_pythons:
        fail("single-lib-python",
             f"expected only lib/python{py}, also found: " + ", ".join(other_pythons))

    venv_python = entries.get("bin/python3")
    if venv_python is None or venv_python.kind != "l" or not re.search(
            rf"(?:^|/)python{re.escape(py)}$", venv_python.target or ""):
        shown = ("missing" if venv_python is None
                 else f"-> {venv_python.target}" if venv_python.kind == "l"
                 else f"not a symlink (type {venv_python.kind!r})")
        fail("venv-python-link",
             f"bin/python3 must be a symlink to python{py}, it is {shown}")

    usr_pythons = sorted(p for p in entries if re.fullmatch(r"usr/bin/python3[^/]*", p))
    if usr_pythons:
        fail("no-usr-bin-python",
             "found " + ", ".join(usr_pythons)
             + "; it would come before bin/python3 on the app's PATH")

    tools = [t for t in ("usr/bin/gs", "usr/bin/tesseract") if t not in entries]
    if tools:
        fail("gs-tesseract-binaries", "missing " + ", ".join(tools))

    gs = _versions(entries, r"usr/share/ghostscript/([^/]+)/Resource/Init/gs_init\.ps")
    if len(gs) == 1:
        facts["Ghostscript resource version"] = next(iter(gs))
    else:
        fail("ghostscript-init",
             "expected usr/share/ghostscript/<v>/Resource/Init/gs_init.ps for "
             f"exactly one <v>, found {sorted(gs) or 'none'}")

    per_file = {
        name: _versions(entries, rf"usr/share/tesseract-ocr/([^/]+)/tessdata/{re.escape(name)}")
        for name in TESSDATA_FILES
    }
    missing = [name for name, vs in per_file.items() if not vs]
    tess = set().union(*per_file.values())
    if missing or len(tess) != 1:
        fail("tessdata",
             "expected " + ", ".join(TESSDATA_FILES)
             + " under one usr/share/tesseract-ocr/<v>/tessdata; "
             + (f"missing {', '.join(missing)}; " if missing else "")
             + f"<v> found: {sorted(tess) or 'none'}")
    else:
        facts["tessdata version"] = next(iter(tess))

    if XKB_RULES not in entries:
        fail("xkb-data", f"missing {XKB_RULES}")

    appstream = [p for p in (DESKTOP_FILE, METAINFO_FILE) if p not in entries]
    if appstream:
        fail("desktop-metainfo", "missing " + ", ".join(appstream))

    if APP_ENTRY not in entries:
        fail("app-entry-point", f"missing {APP_ENTRY}")

    facts[FONTS_CONF] = "present" if FONTS_CONF in entries else "absent"
    return failures, facts


def dist_infos(entries: dict[str, Entry], py: str) -> list[str]:
    """``name-version`` of every ``*.dist-info`` directory in site-packages."""
    rx = re.compile(rf"lib/python{re.escape(py)}/site-packages/([^/]+)\.dist-info")
    return sorted((m.group(1) for p in entries if (m := rx.fullmatch(p))), key=str.lower)


def render_summary(py: str, size: str | None, failures, facts, dists) -> str:
    lines = ["## Snap payload", "", f"- Python, from the manifest: {py}"]
    if size is not None:
        lines.append(f"- Snap size: {size}")
    lines += [f"- {k}: {v}" for k, v in facts.items()]
    lines.append("")
    if failures:
        lines.append(f"### {len(failures)} check(s) failed")
        lines += [f"- `{name}`: {message}" for name, message in failures]
    else:
        lines.append("### All checks passed")
    lines += ["", f"### Python distributions ({len(dists)})", ""]
    lines += [f"- {d}" for d in dists]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--listing", required=True, type=Path)
    parser.add_argument("--snap", type=Path, help="the .snap, only for its size")
    parser.add_argument(
        "--summary", type=Path, default=os.environ.get("GITHUB_STEP_SUMMARY") or None,
        help="file to append the Markdown summary to "
             "(default: $GITHUB_STEP_SUMMARY when set)")
    args = parser.parse_args(argv)

    try:
        py = python_version_from_manifest(args.manifest.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1

    entries = parse_listing(args.listing.read_text(encoding="utf-8", errors="replace"))
    failures, facts = check_payload(entries, py)
    size = None
    if args.snap is not None:
        size = (f"{args.snap.stat().st_size} bytes" if args.snap.is_file()
                else f"{args.snap} not found")
    summary = render_summary(py, size, failures, facts, dist_infos(entries, py))

    sys.stdout.write(summary)
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(summary)
    for name, message in failures:
        print(f"FAIL {name}: {message}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
