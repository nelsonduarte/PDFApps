"""Regression test: the Ghostscript pass of ``_compress_pdf`` must not stall
on its own output.

``_compress_pdf`` spawns gs with ``Popen`` and polls it (so Cancel works),
and never reads the child's stdout or stderr. With ``stdout=PIPE`` /
``stderr=PIPE`` a gs that prints more than one pipe buffer blocks on the
write, ``poll()`` keeps returning None, and the pass ends only when the
120 s deadline terminates gs, with no Ghostscript output. Measured in the
emulated snap (gs 9.55.0, one malformed 400-page PDF): drained, gs prints
137,600 bytes to stdout and none to stderr; with PIPE it stopped with
64,976 bytes in the 65,536-byte pipe, the pass took about 120 s instead
of about a second, and gs ended with rc -15. The native gs 9.55.0 of
Ubuntu 22.04 stalled for 120 s on the same PDF. The fix sends both
streams to ``DEVNULL``.

The test replaces gs with a stdlib-only Python script that writes 2 MiB
to stdout and to stderr, then copies a marker PDF (page size 123 x 321) to
``-sOutputFile`` and exits 0. ``_find_gs`` returns the script path, and a
thin ``subprocess.Popen`` wrapper prefixes the interpreter for that one
argv, passing every keyword (``stdout``, ``stderr``, ``env``) through to
the real ``Popen`` untouched, so real pipes are in play on Windows and on
POSIX alike (Windows cannot exec a ``.py`` directly).

Why a cancel budget and not a shorter deadline: the 120 s deadline is a
literal inside ``_compress_pdf``, not a module attribute, so it cannot be
monkeypatched, and patching ``time.monotonic`` would reach pytest itself.
The test instead uses the function's own cancel path: its ``progress_fn``
returns False once the gs pass has polled for ``_GS_PASS_BUDGET_S``. With
DEVNULL the fake finishes well inside the budget; with either stream on
PIPE it cannot finish at all, the cancel fires, and the test fails in
about ``_GS_PASS_BUDGET_S`` seconds instead of hanging for 120.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Each stream gets this much, far above the 64 KiB default pipe buffer on
# Linux. test_fake_gs_fills_an_undrained_pipe checks that it does fill the
# pipe on the platform at hand.
_FLOOD_BYTES = 2 * 1024 * 1024

# Wall time the gs pass may poll before the test cancels it. The fake
# needs well under a second with DEVNULL; the margin is for loaded CI
# runners.
_GS_PASS_BUDGET_S = 15.0

_MARKER_SIZE = (123, 321)

# The base interpreter, not a venv launcher: on Windows the venv
# python.exe runs the real interpreter as a grandchild, and the fake must
# be the direct child that terminate() reaches. The script is stdlib-only.
_PY = getattr(sys, "_base_executable", None) or sys.executable

_FAKE_GS = r'''
import shutil
import sys

out = next(a[len("-sOutputFile="):] for a in sys.argv[1:]
           if a.startswith("-sOutputFile="))
chunk = b"gs noise\n" * 4096
for stream in (sys.stdout.buffer, sys.stderr.buffer):
    left = {flood}
    while left > 0:
        n = stream.write(chunk[:left])
        left -= n
    stream.flush()
shutil.copyfile({template!r}, out)
'''


def _write_fake_gs(tmp_path: Path) -> str:
    template = tmp_path / "marker.pdf"
    doc = pymupdf.open()
    doc.new_page(width=_MARKER_SIZE[0], height=_MARKER_SIZE[1])
    doc.save(str(template))
    doc.close()
    bindir = tmp_path / "gs bin é"
    bindir.mkdir()
    script = bindir / "gs.py"
    script.write_text(_FAKE_GS.format(flood=_FLOOD_BYTES,
                                      template=str(template)),
                      encoding="utf-8")
    return str(script)


def _write_source(tmp_path: Path) -> Path:
    # Incompressible noise, so Pass B/C of the source stay far larger than
    # the fake gs output and the marker page can only come from Pass A.
    src = tmp_path / "in put é.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    pix = pymupdf.Pixmap(pymupdf.csRGB, 400, 400, os.urandom(400 * 400 * 3),
                         False)
    page.insert_image(pymupdf.Rect(0, 0, 595, 842), pixmap=pix)
    doc.save(str(src))
    doc.close()
    return src


def _route_fake_gs(monkeypatch, fake: str) -> None:
    real_popen = subprocess.Popen

    def popen(cmd, *args, **kwargs):
        if cmd and cmd[0] == fake:
            cmd = [_PY, "-I", fake, *cmd[1:]]
        return real_popen(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", popen)


def test_fake_gs_fills_an_undrained_pipe(tmp_path):
    """Control: the fake really blocks on a pipe nobody reads.

    Without this, a platform with a pipe buffer above ``_FLOOD_BYTES``
    would let the test below pass with PIPE as well.
    """
    fake = _write_fake_gs(tmp_path)
    out = tmp_path / "control.pdf"
    proc = subprocess.Popen([_PY, "-I", fake, f"-sOutputFile={out}"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        time.sleep(3)
        assert proc.poll() is None, (
            "the fake gs exited although nothing read its pipes; the "
            f"pipe buffer here holds {_FLOOD_BYTES} bytes and the test "
            "below no longer discriminates")
        assert not out.exists()
    finally:
        proc.kill()
        proc.wait(timeout=10)
        proc.stdout.close()
        proc.stderr.close()


def test_gs_pass_finishes_when_gs_floods_stdout_and_stderr(
        monkeypatch, tmp_path):
    from app import utils

    fake = _write_fake_gs(tmp_path)
    src = _write_source(tmp_path)
    dst = tmp_path / "out é.pdf"
    monkeypatch.setattr(utils, "_find_gs", lambda: fake)
    _route_fake_gs(monkeypatch, fake)

    started: list[float] = []

    def progress(stage, cur, tot):
        if stage != "passA":
            return None
        if not started:
            started.append(time.monotonic())
        return time.monotonic() - started[0] <= _GS_PASS_BUDGET_S

    t0 = time.monotonic()
    try:
        before, after = utils._compress_pdf(str(src), str(dst),
                                            level="recommended",
                                            progress_fn=progress)
    except utils.CancelledError:
        pytest.fail(
            "the Ghostscript pass was still running after "
            f"{time.monotonic() - t0:.0f} s: gs is blocked writing to a "
            "stdout/stderr pipe that _compress_pdf never reads")
    else:
        assert after < before

    out = pymupdf.open(str(dst))
    try:
        r = out[0].rect
        assert (round(r.width), round(r.height)) == _MARKER_SIZE, (
            "the result did not come from the gs pass")
    finally:
        out.close()
