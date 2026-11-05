"""Run the font subsetting child of a built app on a real job.

    python scripts/smoke_font_subset_child.py dist/PDFApps

Nothing else in CI executes the frozen binary, and a child that cannot
start in the bundle looks like a working compress: the pipeline carries on
without subsetting. The check is that the fonts really shrink.

Extra arguments are placed between the program and the flag, which is how
the tests run this against pdfapps.py from source. On Windows ".exe" is
added to the program when the path without it does not exist, because the
build workflow is not allowed to spell out the raw binary's path
(tests/test_audit_pr_j.py).

This starts the child as a fresh process, with no ``_PYI_*`` variables, so
the bootloader unpacks the bundle: the inherited-environment path of a real
compress is not exercised here. For the same reason the job has no
``parent_pid``: on POSIX the bootloader is the parent of the Python code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pymupdf

_FLAG = "--internal-subset-fonts"
# Generous: a one-file bundle has to unpack on a CI runner.
_TIMEOUT_S = 300
_PASSWORD = "contrasenya-ç中"


def _make_pdf(path: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    # A full font from MuPDF's built-in set, using very few of its glyphs.
    font = pymupdf.Font("cjk")
    page.insert_font(fontname="F0", fontbuffer=font.buffer)
    page.insert_text((72, 72), "中文 subset", fontname="F0")
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256,  # type: ignore[attr-defined]
             user_pw=_PASSWORD, owner_pw=_PASSWORD, garbage=3, deflate=True)
    doc.close()


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    program = argv[0]
    if (sys.platform == "win32" and not os.path.exists(program)
            and os.path.exists(program + ".exe")):
        program += ".exe"
    command = [os.path.abspath(program), *argv[1:], _FLAG]

    with tempfile.TemporaryDirectory(prefix="pdfapps smoke ç") as tmp:
        src = os.path.join(tmp, "in ç中.pdf")
        dst = os.path.join(tmp, "out.pdf")
        _make_pdf(src)
        job = json.dumps({"src": src, "dst": dst, "password": _PASSWORD})
        result = subprocess.run(command, input=job.encode("ascii"),
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                timeout=_TIMEOUT_S, check=False)
        if result.returncode != 0:
            print(f"FAILED: child exited with {result.returncode}")
            return 1
        before = os.path.getsize(src)
        after = os.path.getsize(dst) if os.path.exists(dst) else 0
        if not after:
            print("FAILED: rc 0 but no output")
            return 1
        with pymupdf.open(dst) as out:
            text = out[0].get_text()
            pages = out.page_count
        if pages != 1 or "subset" not in text:
            print(f"FAILED: bad output ({pages} pages, text {text!r})")
            return 1
        if after >= before // 2:
            print(f"FAILED: fonts were not subset ({before} -> {after} bytes)")
            return 1
        print(f"OK: rc 0, {before} -> {after} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
