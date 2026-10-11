"""Which OCR languages the tool offers, and which one it selects first.

Helpers for :mod:`app.tools.ocr`, with no Qt and no ``app.*`` imports.

The tests replace ``subprocess.run`` and ``sys.platform`` on the module
objects, so this file must keep calling them through the module attribute
(``subprocess.run``, never ``from subprocess import run``).
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable

# The 8 UI locales in app/translations.json -> Tesseract language codes.
# The zh strings are Simplified Chinese, hence chi_sim.
UI_TO_TESSERACT = {
    "en": "eng", "pt": "por", "es": "spa", "fr": "fra",
    "de": "deu", "it": "ita", "zh": "chi_sim", "nl": "nld",
}

# A warm `tesseract --list-langs` took about 29 ms on Windows; the margin
# is for a cold start. The bound matters twice: _run waits for the call
# on the GUI thread, and the app's exit waits for a scan still running on
# the thread pool.
LIST_LANGS_TIMEOUT = 5  # seconds

# pytesseract's LANG_PATTERN. The header line ("List of available
# languages in ...") does not match.
_LANG_LINE = re.compile(r"^[a-z_]+$")


def parse_list_langs(output: str) -> list[str]:
    """Language codes in ``tesseract --list-langs`` output, in its order."""
    return [line.strip() for line in output.splitlines()
            if _LANG_LINE.match(line.strip())]


def list_installed_langs(tesseract_cmd: str) -> list[str]:
    """Run ``tesseract --list-langs`` and return the codes it lists.

    Replaces pytesseract's ``get_languages`` and ``get_tesseract_version``,
    which start Tesseract without ``CREATE_NO_WINDOW``: in the windowed
    Windows build each of those calls opened a visible console window.

    Raises ``OSError`` when the binary cannot be started (not installed),
    ``subprocess.TimeoutExpired`` after :data:`LIST_LANGS_TIMEOUT`, and
    ``subprocess.CalledProcessError`` for an exit code other than 0 or 1
    (pytesseract accepts 1 too, for Tesseract 3).
    """
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW
    else:
        # 0 is the only value POSIX accepts.
        flags = 0
    result = subprocess.run(
        [tesseract_cmd, "--list-langs"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        # Merged as in pytesseract's get_languages, so the parse below
        # sees the same text it did.
        stderr=subprocess.STDOUT,
        timeout=LIST_LANGS_TIMEOUT,
        check=False,
        creationflags=flags,
    )
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout)
    # The header carries the tessdata path; a byte in it that is not
    # UTF-8 must not fail the call. The codes themselves are ASCII.
    return parse_list_langs(result.stdout.decode("utf-8", errors="replace"))


def offered_codes(installed: Iterable[str]) -> list[str]:
    """Codes to offer for ``tesseract --list-langs`` output, in its order.

    ``osd`` is orientation detection, not a language. ``por+eng`` is
    offered only when both halves are installed. Nothing stands in for an
    empty list: ``--list-langs`` reads the same tessdata the OCR call
    would, so an ``eng`` it did not list would fail there too.
    """
    codes = [c for c in installed if c != "osd"]
    if "por" in codes and "eng" in codes:
        codes.append("por+eng")
    return codes


def default_code(codes: list[str], ui_lang: str) -> str | None:
    """The UI language's code if offered, else ``eng``, else the first."""
    for code in (UI_TO_TESSERACT.get(ui_lang), "eng"):
        if code in codes:
            return code
    return codes[0] if codes else None
