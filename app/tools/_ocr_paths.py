"""Locate the Tesseract executable and its ``tessdata`` directory.

Helpers for :mod:`app.tools.ocr`. This module has no Qt and no ``app.*``
imports of its own, but importing it through the ``app.tools`` package
loads Qt anyway (see ``app/tools/__init__.py``). ``app.tools.ocr``
re-exports both names.

The tests replace ``os.path.isdir``, ``glob.glob``, ``shutil.which`` and
``sys.platform`` on the module objects, so this file must keep calling them
through the module attribute (``glob.glob``, never ``from glob import
glob``; ``shutil.which``, never ``from shutil import which``).
"""

from __future__ import annotations

import glob
import os
import shutil
import sys


def _find_tesseract() -> str | None:
    """Returns the tesseract executable path or None if not found."""
    found = shutil.which("tesseract")
    if found:
        return found
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/opt/homebrew/bin/tesseract",
            "/usr/local/bin/tesseract",
        ]
    else:
        candidates = [
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
            "/snap/bin/tesseract",
        ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _newest_versioned_tessdata(pattern: str) -> str | None:
    """First existing directory matched by *pattern*, reverse-sorted so the
    newest ``tesseract-ocr/<version>`` wins."""
    for p in sorted(glob.glob(pattern), reverse=True):
        if os.path.isdir(p):
            return p
    return None


def _find_tessdata(tess_exe: str | None) -> str | None:
    """Locate the tessdata directory across platforms.

    Precedence (first match wins):

    1. ``<bindir>/tessdata`` adjacent to the binary: Windows and any
       install that bundles the data next to the executable.
    2. The versioned Debian layout under the binary's own prefix,
       ``<prefix>/share/tesseract-ocr/<version>/tessdata``, newest first.
       This is how the snap ships Tesseract: the binary is
       ``$SNAP/usr/bin/tesseract`` (from the Ubuntu 22.04 ``tesseract-ocr``
       deb) but its compiled-in default is the absolute
       ``/usr/share/tesseract-ocr/4.00/tessdata``, which resolves against
       the base snap's rootfs, where no Tesseract data is installed.
       Without this step OCR in the snap failed with 'Error opening data
       file /usr/share/tesseract-ocr/4.00/tessdata/eng.traineddata'. Deriving
       from the binary instead of hard-coding ``$SNAP`` or ``4.00`` keeps
       working when the snap moves to a newer base (the Tesseract 5 debs
       ship ``.../tesseract-ocr/5/tessdata``), and only ever pairs a binary
       with the data installed alongside it. For ``/usr/bin/tesseract``
       it is the same lookup as step 3.
    3. The versioned system layout
       ``/usr/share/tesseract-ocr/<version>/tessdata``, newest first, for
       a binary that lives outside ``/usr``. Checked *before* the flat
       prefix derivation (step 4) on purpose: the binary often has a
       stale default baked in (Ubuntu 24.04 ships v5 but still points at
       .../4.00/tessdata, see issue #27), and a flat
       ``/usr/share/tessdata``, which step 4 would derive from
       ``/usr/bin/tesseract``, must never shadow a newer versioned
       directory.
    4. ``<prefix>/share/tessdata`` derived relative to the binary
       (``<prefix>/bin/tesseract`` -> ``<prefix>/share/tessdata``). This
       covers Homebrew (Intel ``/usr/local``, Apple Silicon
       ``/opt/homebrew``) and non-standard install prefixes; on those
       systems the versioned globs in steps 2 and 3 find nothing so we
       land here.
    5. Fixed fallbacks for older Debian, manual installs, Homebrew and
       snap layouts.

    Without TESSDATA_PREFIX set explicitly, OCR would otherwise fail with
    'Error opening data file .../4.00/tessdata/eng.traineddata'."""
    unix_like = sys.platform.startswith(("linux", "darwin"))
    prefix = (os.path.dirname(os.path.dirname(tess_exe))
              if tess_exe else None)
    # 1. tessdata adjacent to the binary (Windows and bundled installs).
    if tess_exe:
        adjacent = os.path.join(os.path.dirname(tess_exe), "tessdata")
        if os.path.isdir(adjacent):
            return adjacent
    # 2. Versioned layout under the binary's own prefix (the snap's
    #    $SNAP/usr/share/tesseract-ocr/<version>/tessdata). glob.escape so
    #    a prefix containing [ ] * ? is matched literally.
    if unix_like and prefix:
        found = _newest_versioned_tessdata(os.path.join(
            glob.escape(prefix), "share", "tesseract-ocr", "*", "tessdata"))
        if found:
            return found
    # 3. Versioned Linux layout, newest first. Kept ahead of the relative
    #    prefix derivation so a stale /usr/share/tessdata never shadows a
    #    newer /usr/share/tesseract-ocr/<version>/tessdata (issue #27).
    if unix_like:
        found = _newest_versioned_tessdata(
            "/usr/share/tesseract-ocr/*/tessdata")
        if found:
            return found
    # 4. Homebrew (Intel /usr/local, Apple Silicon /opt/homebrew) and
    #    custom prefixes: <prefix>/bin/tesseract -> <prefix>/share/tessdata.
    if prefix is not None:
        prefixed = os.path.join(prefix, "share", "tessdata")
        if os.path.isdir(prefixed):
            return prefixed
    # 5. Older Debian, manual installs, Homebrew (Intel + Apple Silicon),
    #    snap fallbacks.
    if unix_like:
        for p in ("/usr/share/tessdata",
                  "/usr/local/share/tessdata",
                  "/opt/homebrew/share/tessdata",
                  "/snap/tesseract/current/usr/share/tesseract-ocr/tessdata"):
            if os.path.isdir(p):
                return p
    return None
