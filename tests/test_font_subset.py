"""Font subsetting in a child process (app/_font_subset.py).

``Document.subset_fonts()`` can crash natively (Windows, PyMuPDF 1.28.2,
0xC0000005 on a public PDF, 30 runs out of 30), so the compress tool runs it
in a child. These tests start real processes, either the real entry in
``pdfapps.py`` or a stand-in chosen by replacing ``child_command``. There is
no crash hook in production code.

The PDF that really crashes cannot live in the repository, its licence is
not confirmed. Set ``PDFAPPS_SUBSET_CRASH_PDF`` to its path to run the one
test that uses it.
"""

from __future__ import annotations

import ast
import errno
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

import pymupdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import _font_subset as fs
from app import utils
from app.constants import TOOL_PANEL_MIN_WIDTH

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
PASSWORD = "pässção中文\U0001d11e"
SKIPPED = "passB_fonts_skipped"

# Silences a crash completely: WerSetFlags(NO_UI) is what keeps a real or
# simulated access violation from showing anything on the machine's screen,
# and no core files on POSIX.
_QUIET_CRASH = """\
import ctypes, os
if os.name == "nt":
    ctypes.windll.kernel32.SetErrorMode(0x8003)
    ctypes.windll.kernel32.WerSetFlags(0x20)
else:
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
"""

_needs_windows = pytest.mark.skipif(sys.platform != "win32",
                                    reason="Windows only")
_needs_linux = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                  reason="Linux only")


def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int,
                                         ctypes.c_ulong]
        kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as stat:
            return stat.read().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False
    except OSError:
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_for_file(path: Path, timeout: float = 30) -> None:
    end = time.monotonic() + timeout
    while not path.exists() or not path.stat().st_size:
        assert time.monotonic() < end, f"{path.name} never appeared"
        time.sleep(0.02)


def _wait_dead(pid: int, timeout: float = 10) -> None:
    end = time.monotonic() + timeout
    while _alive(pid):
        assert time.monotonic() < end, f"pid {pid} is still alive"
        time.sleep(0.05)


def _make_pdf(path: Path, pages: int = 3, password: str | None = None) -> Path:
    """A PDF that always compresses: uncompressed, with a whole embedded
    font of which it uses a few glyphs."""
    doc = pymupdf.open()
    font = pymupdf.Font("cjk")
    for i in range(pages):
        page = doc.new_page()
        page.insert_font(fontname="F0", fontbuffer=font.buffer)
        page.insert_text((72, 72), f"page {i} 中文", fontname="F0")
    kw = {}
    if password:
        kw = {"encryption": pymupdf.PDF_ENCRYPT_AES_256,
              "user_pw": password, "owner_pw": password}
    doc.save(str(path), **kw)
    doc.close()
    return path


def _script(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
                    + textwrap.dedent(body), encoding="utf-8")
    return str(path)


def _use_child(monkeypatch, *cmd) -> None:
    monkeypatch.setattr(fs, "child_command", lambda: [PY, "-I", *map(str, cmd)])


def _fake_gs(monkeypatch, tmp_path: Path, body: str) -> None:
    """Make *body* the Ghostscript of the pipeline, with the same interface:
    its arguments in sys.argv, the input last."""
    script = _script(tmp_path, "fake_gs.py", body)
    real_popen = subprocess.Popen

    def popen(cmd, *a, **k):
        if cmd and cmd[0] == script:
            cmd = [PY, "-I", *cmd]
        return real_popen(cmd, *a, **k)

    monkeypatch.setattr(utils, "_find_gs", lambda: script)
    monkeypatch.setattr(subprocess, "Popen", popen)


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    """Every temporary of the pipeline lands here, so a leak is visible."""
    root = tmp_path / "temp root"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


@pytest.fixture
def no_gs(monkeypatch):
    monkeypatch.setattr(utils, "_find_gs", lambda: None)


def _stages():
    seen: list[str] = []

    def progress(stage, cur=0, tot=0):
        seen.append(stage)
        return True
    return seen, progress


def _assert_same_text(out: Path, src: Path, password: str | None = None):
    with pymupdf.open(str(src)) as a, pymupdf.open(str(out)) as b:
        if password:
            assert a.authenticate(password)
        assert not b.needs_pass
        assert b.page_count == a.page_count
        assert [p.get_text() for p in b] == [p.get_text() for p in a]


# ── 1. A child that crashes ──────────────────────────────────────────────

CRASH_BODY = _QUIET_CRASH + "import faulthandler\nfaulthandler._read_null()\n"


def test_crashing_child_leaves_a_good_output_and_a_warning(
        tmp_path, monkeypatch, temp_root, no_gs, caplog):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    _use_child(monkeypatch, _script(tmp_path, "crash.py", CRASH_BODY))
    seen, progress = _stages()

    with caplog.at_level(logging.INFO, logger=fs.__name__):
        before, after = utils._compress_pdf(str(src), str(out),
                                            progress_fn=progress)

    assert 0 < after < before
    _assert_same_text(out, src)
    assert SKIPPED in seen
    assert list(temp_root.iterdir()) == []
    # Crashed, not merely failed: rc 3221225477 on Windows, -11 on POSIX.
    assert "rc=3221225477" in caplog.text or "rc=-11" in caplog.text


def test_the_stage_is_reported_once_when_the_winner_is_known(
        tmp_path, monkeypatch, temp_root, no_gs):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    _use_child(monkeypatch, _script(tmp_path, "crash.py", CRASH_BODY))
    at_stage = []

    def progress(stage, cur=0, tot=0):
        at_stage.append((stage, out.exists()))
        return True

    utils._compress_pdf(str(src), str(out), progress_fn=progress)
    assert [s for s, _ in at_stage].count(SKIPPED) == 1
    assert at_stage[-1] == (SKIPPED, False), "last, and before the output"


def test_a_cancel_answered_on_the_skip_notice_still_cancels(
        tmp_path, monkeypatch, temp_root, no_gs):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    _use_child(monkeypatch, _script(tmp_path, "crash.py", CRASH_BODY))
    with pytest.raises(utils.CancelledError):
        utils._compress_pdf(str(src), str(out),
                            progress_fn=lambda s, c=0, n=0: s != SKIPPED)
    assert not out.exists()
    assert list(temp_root.iterdir()) == []


def test_child_that_cannot_start_is_a_failure_not_an_exception(
        tmp_path, monkeypatch, temp_root, no_gs, caplog):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    monkeypatch.setattr(fs, "child_command",
                        lambda: [str(tmp_path / "no such program")])
    seen, progress = _stages()
    with caplog.at_level(logging.INFO, logger=fs.__name__):
        utils._compress_pdf(str(src), str(out), progress_fn=progress)
    assert SKIPPED in seen
    assert "did not start" in caplog.text
    _assert_same_text(out, src)


def test_real_crash_pdf_when_available(tmp_path, monkeypatch, temp_root, no_gs,
                                       caplog):
    real = os.environ.get("PDFAPPS_SUBSET_CRASH_PDF")
    if not real:
        pytest.skip("PDFAPPS_SUBSET_CRASH_PDF is not set")
    # The real entry, under a wrapper that only adds WerSetFlags(NO_UI) so
    # the crash cannot reach the error reporting of the machine running this.
    wrapper = _script(tmp_path, "wrap.py", _QUIET_CRASH + f"""
import runpy
sys.argv = [{str(ROOT / "pdfapps.py")!r}, {fs.WORKER_FLAG!r}]
runpy.run_path(sys.argv[0], run_name="__main__")
""")
    monkeypatch.setattr(fs, "child_command", lambda: [PY, wrapper])
    out = tmp_path / "out.pdf"
    seen, progress = _stages()
    with caplog.at_level(logging.INFO, logger=fs.__name__):
        utils._compress_pdf(real, str(out), progress_fn=progress)
    with pymupdf.open(real) as a, pymupdf.open(str(out)) as b:
        assert a.page_count == b.page_count
    assert list(temp_root.iterdir()) == []
    if sys.platform == "win32":
        assert SKIPPED in seen
        assert "rc=3221225477" in caplog.text


# ── 2. A child that hangs ────────────────────────────────────────────────

def _hang_script(tmp_path: Path, pid_file: Path) -> str:
    return _script(tmp_path, "hang.py", f"""
import os, time
with open({str(pid_file)!r}, "w") as fh:
    fh.write(str(os.getpid()))
time.sleep(600)
""")


_REAL_CHILD_TIMEOUT_S = fs.CHILD_TIMEOUT_S


def test_hung_child_is_killed_at_the_timeout(tmp_path, monkeypatch, temp_root,
                                             no_gs, caplog):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    pid_file = tmp_path / "pid"
    _use_child(monkeypatch, _hang_script(tmp_path, pid_file))
    monkeypatch.setattr(fs, "CHILD_TIMEOUT_S", 2)
    seen, progress = _stages()
    started = time.monotonic()
    with caplog.at_level(logging.INFO, logger=fs.__name__):
        utils._compress_pdf(str(src), str(out), progress_fn=progress)
    elapsed = time.monotonic() - started
    # Half of the real 120 s, so that only a deadline that ignored the patch
    # gets here, however slow the machine: the rest of the run takes seconds.
    assert elapsed < _REAL_CHILD_TIMEOUT_S / 2, f"took {elapsed:.0f} s"
    assert not _alive(int(pid_file.read_text()))
    assert SKIPPED in seen
    assert "timeout" in caplog.text
    _assert_same_text(out, src)
    assert list(temp_root.iterdir()) == []


def test_cancel_kills_the_child_without_waiting_for_the_timeout(
        tmp_path, monkeypatch, temp_root, no_gs):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    pid_file = tmp_path / "pid"
    _use_child(monkeypatch, _hang_script(tmp_path, pid_file))
    # Far from the 0.2 s poll, so that a busy machine cannot fail this.
    monkeypatch.setattr(fs, "CHILD_TIMEOUT_S", 90)
    asked_at = []
    seen = []

    def progress(stage, cur=0, tot=0):
        seen.append(stage)
        if pid_file.exists() and pid_file.stat().st_size:
            if not asked_at:
                asked_at.append(time.monotonic())
            return False
        return True

    with pytest.raises(utils.CancelledError):
        utils._compress_pdf(str(src), str(out), progress_fn=progress)
    assert not _alive(int(pid_file.read_text())), "gone when it returns"
    elapsed = time.monotonic() - asked_at[0]
    assert elapsed < 45, f"cancel took {elapsed:.2f} s"
    assert SKIPPED not in seen, "a cancel is not a failed optimisation"
    assert not out.exists()
    assert list(temp_root.iterdir()) == []


def test_a_cancel_answered_only_once_during_the_child_still_cancels(
        tmp_path, monkeypatch, temp_root, no_gs):
    """The next checkpoint must not be what ends the run: it might say go on."""
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    pid_file = tmp_path / "pid"
    _use_child(monkeypatch, _hang_script(tmp_path, pid_file))
    answered = []

    def progress(stage, cur=0, tot=0):
        if not answered and pid_file.exists() and pid_file.stat().st_size:
            answered.append(stage)
            return False
        return True

    with pytest.raises(utils.CancelledError):
        utils._compress_pdf(str(src), str(out), progress_fn=progress)
    assert answered == ["passB_setup"]
    assert not out.exists()
    assert list(temp_root.iterdir()) == []


def test_cancel_during_the_child_also_removes_ghostscripts_output(
        tmp_path, monkeypatch, temp_root):
    """The leak the original report found, this time from a cancel."""
    src = _make_pdf(tmp_path / "in.pdf")
    pid_file = tmp_path / "pid"
    _fake_gs(monkeypatch, tmp_path, _GS_COPIES_THE_INPUT)
    _use_child(monkeypatch, _hang_script(tmp_path, pid_file))
    with pytest.raises(utils.CancelledError):
        utils._compress_pdf(
            str(src), str(tmp_path / "out.pdf"),
            progress_fn=lambda s, c=0, n=0: not pid_file.exists()
            or not pid_file.stat().st_size)
    assert list(temp_root.iterdir()) == []


def test_a_job_the_child_never_reads_cannot_block_cancel(tmp_path, monkeypatch):
    """Larger than any pipe buffer, and the child ignores its stdin."""
    pid_file = tmp_path / "pid"
    _use_child(monkeypatch, _hang_script(tmp_path, pid_file))
    result = {}

    def run():
        result["outcome"] = fs.run_subset(
            "src", str(tmp_path / "out.pdf"), "x" * (4 * 1024 * 1024), 1,
            should_cancel=lambda: pid_file.exists())

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(30)
    assert not worker.is_alive(), "run_subset blocked writing the job"
    assert result["outcome"] == fs.SUBSET_CANCELLED


def test_timeout_is_one_constant_shared_with_ghostscript(
        tmp_path, monkeypatch, temp_root):
    assert fs.CHILD_TIMEOUT_S == 120
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    pid_file = tmp_path / "gs pid"
    _fake_gs(monkeypatch, tmp_path, f"""
import os, time
with open({str(pid_file)!r}, "w") as fh:
    fh.write(str(os.getpid()))
time.sleep(600)
""")
    monkeypatch.setattr(fs, "CHILD_TIMEOUT_S", 3)
    # A deadline of its own would keep gs alive here for much longer.
    budget = time.monotonic() + 60
    utils._compress_pdf(
        str(src), str(out),
        progress_fn=lambda s, c=0, n=0: time.monotonic() < budget)
    assert not _alive(int(pid_file.read_text()))
    _assert_same_text(out, src)


# ── 3. rc 0 with an unusable output ──────────────────────────────────────

_DAMAGE_ONE_OFFSET = """
import re
d = pymupdf.open(job['src'])
d.save(job['dst'])
d.close()
raw = bytearray(open(job['dst'], 'rb').read())
table = re.search(rb'xref\\r?\\n0 \\d+\\r?\\n', raw).end()
raw[table + 20 * %d:table + 20 * %d + 10] = b'0000000099'
open(job['dst'], 'wb').write(raw)
"""

_BAD_OUTPUTS = {
    "nothing written": "",
    "empty": "open(job['dst'], 'wb').close()",
    "not a pdf": "open(job['dst'], 'wb').write(b'%PDF-1.7\\n')",
    "other page count": """
d = pymupdf.open(job['src'])
d.select([0])
d.save(job['dst'])
""",
    # load_page on the expected pages alone would accept the extra one.
    "one page too many": """
d = pymupdf.open(job['src'])
d.new_page()
d.save(job['dst'])
""",
    # Still reports every page when reopened, through MuPDF's repair.
    "truncated": """
d = pymupdf.open(job['src'])
d.save(job['dst'])
d.close()
size = os.path.getsize(job['dst'])
with open(job['dst'], 'r+b') as fh:
    fh.truncate(size - 400)
""",
    "still encrypted": """
d = pymupdf.open(job['src'])
d.save(job['dst'], encryption=pymupdf.PDF_ENCRYPT_AES_256,
       user_pw='other', owner_pw='other')
""",
    # Delivered as three pages, the third an error, without this being caught.
    "a page that leads nowhere": """
d = pymupdf.open(job['src'])
tree = int(d.xref_get_key(d.pdf_catalog(), 'Pages')[1].split()[0])
first, second = d.xref_get_key(tree, 'Kids')[1].strip('[]').split(' 0 R')[:2]
d.xref_set_key(tree, 'Kids', f'[{first} 0 R {second.strip()} 0 R 9999 0 R]')
d.save(job['dst'])
""",
    # Pages and first /Resources: MuPDF reports nothing until they are read.
    "offset of object 2": _DAMAGE_ONE_OFFSET % (2, 2),
    "offset of object 3": _DAMAGE_ONE_OFFSET % (3, 3),
}


@pytest.mark.parametrize("kind", _BAD_OUTPUTS)
def test_rc_zero_with_a_bad_output_is_a_failure(kind, tmp_path, monkeypatch,
                                                temp_root, no_gs, caplog):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    script = _script(tmp_path, "bad.py",
                     "import json, os, pymupdf\n"
                     "job = json.loads(sys.stdin.buffer.read())\n"
                     + _BAD_OUTPUTS[kind] + "\nos._exit(0)\n")
    _use_child(monkeypatch, script)
    seen, progress = _stages()
    with caplog.at_level(logging.INFO, logger=fs.__name__):
        utils._compress_pdf(str(src), str(out), progress_fn=progress)
    assert SKIPPED in seen
    assert "rc=0 but the output is unusable" in caplog.text
    _assert_same_text(out, src)
    assert list(temp_root.iterdir()) == []


def test_the_truncated_fixture_really_goes_through_repair(tmp_path):
    """Control for "truncated": without is_repaired it would be accepted."""
    src = _make_pdf(tmp_path / "in.pdf")
    bad = tmp_path / "bad.pdf"
    with pymupdf.open(str(src)) as doc:
        doc.save(str(bad))
    with open(bad, "r+b") as fh:
        fh.truncate(bad.stat().st_size - 400)
    with pymupdf.open(str(bad)) as doc:
        assert doc.page_count == 3 and doc.is_repaired
    assert not fs._is_good_output(str(bad), 3)


def _damaged_offset(raw: bytes, xref: int) -> bytes:
    table = re.search(rb"xref\r?\n0 \d+\r?\n", raw).end()
    out = bytearray(raw)
    out[table + 20 * xref:table + 20 * xref + 10] = b"0000000099"
    return bytes(out)


def test_a_wrong_offset_is_found_on_any_object(tmp_path):
    """Fonts and content streams too, which load_page alone never reaches."""
    src = _make_pdf(tmp_path / "in.pdf")
    good = tmp_path / "good.pdf"
    with pymupdf.open(str(src)) as doc:
        doc.save(str(good))
        count = doc.xref_length()
    assert fs._is_good_output(str(good), 3), "the control must pass"
    assert count > 10
    raw = good.read_bytes()
    accepted = []
    for xref in range(1, count):
        bad = tmp_path / f"off{xref}.pdf"
        bad.write_bytes(_damaged_offset(raw, xref))
        if fs._is_good_output(str(bad), 3):
            accepted.append(xref)
    assert accepted == []


def _source_truncated(tmp_path):
    src = _make_pdf(tmp_path / "in.pdf")
    src.write_bytes(src.read_bytes()[:-400])
    return src, None


def _source_with_junk_in_front(tmp_path):
    src = _make_pdf(tmp_path / "in.pdf")
    src.write_bytes(b"junk before the header\n" + src.read_bytes())
    return src, None


def _source_with_object_streams(tmp_path):
    src = _make_pdf(tmp_path / "plain.pdf")
    packed = tmp_path / "in.pdf"
    with pymupdf.open(str(src)) as doc:
        doc.save(str(packed), garbage=3, deflate=True, use_objstms=1)
    return packed, None


def _source_with_incremental_saves(tmp_path):
    src = _make_pdf(tmp_path / "in.pdf")
    for i in range(3):
        with pymupdf.open(str(src)) as doc:
            doc[0].insert_text((72, 200 + 20 * i), f"update {i}",
                               fontname="helv")
            doc.saveIncr()
    return src, None


def _source_encrypted(tmp_path):
    return _make_pdf(tmp_path / "in.pdf", password=PASSWORD), PASSWORD


@pytest.mark.parametrize("make", [
    _source_truncated, _source_with_junk_in_front,
    _source_with_object_streams, _source_with_incremental_saves,
    _source_encrypted,
], ids=lambda f: f.__name__)
def test_a_real_subset_of_an_awkward_source_is_not_refused(make, tmp_path):
    """Reading every object must not turn a good save into a failure."""
    src, password = make(tmp_path)
    dst = tmp_path / "subset.pdf"
    assert fs.run_subset(str(src), str(dst), password, 3) == fs.SUBSET_OK


_LAST_KID = {"two": "]", "null": " null]", "dangling": " 9999 0 R]"}


@pytest.mark.parametrize("kids", _LAST_KID)
def test_a_page_tree_with_a_missing_page_is_refused(kids, tmp_path):
    """/Count still says 3 and every object in the table reads fine.
    Nothing is repaired here either, so is_repaired alone would accept it."""
    src = _make_pdf(tmp_path / "in.pdf")
    bad = tmp_path / "bad.pdf"
    with pymupdf.open(str(src)) as doc:
        tree = int(doc.xref_get_key(doc.pdf_catalog(), "Pages")[1].split()[0])
        first, second, _third = doc.xref_get_key(tree, "Kids")[1].strip(
            "[]").split(" 0 R")[:3]
        doc.xref_set_key(tree, "Kids",
                         f"[{first} 0 R {second.strip()} 0 R{_LAST_KID[kids]}")
        doc.save(str(bad))
    with pymupdf.open(str(bad)) as doc:
        assert doc.page_count == 3
        for xref in range(1, doc.xref_length()):
            doc.xref_object(xref, compressed=True)
        assert not doc.is_repaired
    assert not fs._is_good_output(str(bad), 3)


def _last_kid_is_an_object(doc, body: str) -> None:
    tree = int(doc.xref_get_key(doc.pdf_catalog(), "Pages")[1].split()[0])
    first, second, _ = doc.xref_get_key(tree, "Kids")[1].strip("[]").split(
        " 0 R")[:3]
    new = doc.get_new_xref()
    doc.update_object(new, body)
    doc.xref_set_key(tree, "Kids",
                     f"[{first} 0 R {second.strip()} 0 R {new} 0 R]")


# A hex string starts with "<" as a dictionary does, but with one only. Its
# bytes must be unprintable: MuPDF writes "<414243>" back as "(ABC)".
@pytest.mark.parametrize("body", ["42", "null", "<00ff10>"],
                         ids=["integer", "free", "hex string"])
def test_a_kid_that_is_no_dictionary_is_refused(body, tmp_path):
    src = _make_pdf(tmp_path / "in.pdf")
    bad = tmp_path / "bad.pdf"
    with pymupdf.open(str(src)) as doc:
        _last_kid_is_an_object(doc, body)
        doc.save(str(bad))
    with pymupdf.open(str(bad)) as doc:
        page = doc.load_page(2)
        assert page.rect, "load_page alone would let it through"
        assert doc.xref_object(page.xref, compressed=True).lower() == body
    assert not fs._is_good_output(str(bad), 3)


def _inherit_page_attributes(doc):
    tree = int(doc.xref_get_key(doc.pdf_catalog(), "Pages")[1].split()[0])
    box = doc.xref_get_key(doc.page_xref(0), "MediaBox")[1]
    doc.xref_set_key(tree, "MediaBox", box)
    for number in range(doc.page_count):
        doc.xref_set_key(doc.page_xref(number), "MediaBox", "null")


def _nest_the_last_page(doc):
    tree = int(doc.xref_get_key(doc.pdf_catalog(), "Pages")[1].split()[0])
    first, second, third = (kid.strip() for kid in doc.xref_get_key(
        tree, "Kids")[1].strip("[]").split(" 0 R")[:3])
    node = doc.get_new_xref()
    doc.update_object(
        node, f"<</Type/Pages/Parent {tree} 0 R/Count 1/Kids[{third} 0 R]>>")
    doc.xref_set_key(int(third), "Parent", f"{node} 0 R")
    doc.xref_set_key(tree, "Kids", f"[{first} 0 R {second} 0 R {node} 0 R]")


def _drop_a_page_type(doc):
    doc.xref_set_key(doc.page_xref(0), "Type", "null")


def _nothing(doc):
    pass


@pytest.mark.parametrize("change, save_kw", [
    (_nothing, {}),
    (_inherit_page_attributes, {}),
    (_nest_the_last_page, {}),
    # Read fine by MuPDF, text included, so it is no reason to lose the subset.
    (_drop_a_page_type, {}),
    (_nothing, {"garbage": 3, "deflate": True, "use_objstms": 1}),
], ids=["plain", "inherited", "nested", "no type", "object stream"])
def test_good_page_trees_are_not_refused(change, save_kw, tmp_path):
    src = _make_pdf(tmp_path / "in.pdf")
    good = tmp_path / "good.pdf"
    with pymupdf.open(str(src)) as doc:
        change(doc)
        doc.save(str(good), **save_kw)
    with pymupdf.open(str(good)) as doc:
        assert doc.page_count == 3
        assert [f"page {i}" in page.get_text()
                for i, page in enumerate(doc)] == [True, True, True]
    assert fs._is_good_output(str(good), 3)


@pytest.mark.parametrize("method", ["load_page", "xref_object"])
def test_a_read_that_raises_means_a_bad_output_not_an_exception(
        method, tmp_path, monkeypatch):
    good = _make_pdf(tmp_path / "in.pdf")
    assert fs._is_good_output(str(good), 3)

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(pymupdf.Document, method, boom)
    assert fs._is_good_output(str(good), 3) is False


def _assert_pass_b_survived(out: Path, src: Path, seen: list) -> None:
    assert SKIPPED in seen
    _assert_same_text(out, src)


def test_no_private_folder_means_no_pass_runs(tmp_path, monkeypatch,
                                             temp_root):
    """Each pass would otherwise write its decrypted copy where others can
    read it, which is what the folder is there to stop."""
    src = _make_pdf(tmp_path / "in.pdf", password=PASSWORD)
    out = tmp_path / "out.pdf"
    spawned, made = [], []

    def refuse(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(tempfile, "mkdtemp", refuse)
    monkeypatch.setattr(tempfile, "mkstemp",
                        lambda *a, **k: made.append(a) or refuse())
    monkeypatch.setattr(utils, "_find_gs", lambda: "gs that must not run")
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: spawned.append(a) or refuse())
    seen, progress = _stages()
    with pytest.raises(OSError, match="disk full"):
        utils._compress_pdf(str(src), str(out), progress_fn=progress,
                            password=PASSWORD)
    assert (seen, spawned, made) == ([], [], [])
    assert not out.exists()
    assert list(temp_root.iterdir()) == []


def test_a_subset_that_does_not_reopen_costs_only_the_subset(
        tmp_path, monkeypatch, temp_root, no_gs):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    # OK with no file behind it: the next open fails.
    monkeypatch.setattr(fs, "run_subset", lambda *a, **k: fs.SUBSET_OK)
    seen, progress = _stages()
    utils._compress_pdf(str(src), str(out), progress_fn=progress)
    _assert_pass_b_survived(out, src, seen)
    assert "passB_save" in seen
    assert list(temp_root.iterdir()) == []


def test_run_subset_raising_costs_only_the_subset(
        tmp_path, monkeypatch, temp_root, no_gs, caplog):
    src = _make_pdf(tmp_path / "in.pdf", password=PASSWORD)
    out = tmp_path / "out.pdf"

    def boom(*a, **k):
        raise RuntimeError(f"can't start new thread {PASSWORD}")

    monkeypatch.setattr(fs, "run_subset", boom)
    seen, progress = _stages()
    with caplog.at_level(logging.DEBUG):
        utils._compress_pdf(str(src), str(out), progress_fn=progress,
                            password=PASSWORD)
    assert SKIPPED in seen and "passB_save" in seen
    _assert_same_text(out, src, PASSWORD)
    assert "RuntimeError" in caplog.text
    assert PASSWORD not in caplog.text


def test_a_work_folder_that_survives_is_reported_without_the_password(
        tmp_path, monkeypatch, temp_root, no_gs, caplog):
    src = _make_pdf(tmp_path / "in.pdf", password=PASSWORD)
    real_rmtree = shutil.rmtree

    def refuse(path, ignore_errors=False, **kwargs):
        assert ignore_errors, "a failure here must not change the outcome"

    monkeypatch.setattr(shutil, "rmtree", refuse)
    with caplog.at_level(logging.DEBUG):
        utils._compress_pdf(str(src), str(tmp_path / "out.pdf"),
                            password=PASSWORD)
    monkeypatch.setattr(shutil, "rmtree", real_rmtree)
    (left,) = temp_root.iterdir()
    assert left.name.startswith("pdfapps-compress-")
    real_rmtree(left)
    reports = [r for r in caplog.records
               if f"temporary directory not removed: {left}" in r.getMessage()]
    assert reports, "the folder left behind was not reported"
    # The app's log keeps INFO and above (app/utils.py), so DEBUG would be
    # lost, and among the INFO lines this has to stand out.
    assert all(r.levelno >= logging.WARNING for r in reports)
    assert PASSWORD not in caplog.text


def test_a_removed_work_folder_is_not_reported(tmp_path, temp_root, no_gs,
                                               caplog):
    src = _make_pdf(tmp_path / "in.pdf")
    with caplog.at_level(logging.DEBUG):
        utils._compress_pdf(str(src), str(tmp_path / "out.pdf"))
    assert "temporary directory not removed" not in caplog.text
    assert list(temp_root.iterdir()) == []


# ── The private work folder ──────────────────────────────────────────────

def _gs_reports_its_temp_dir(record: Path, temp_root: Path) -> str:
    """Ghostscript stand-in: copies the input, says where its scratch files
    would go and leaves one there, as a terminated gs does. Only under
    *temp_root*, so that code sending it elsewhere leaks nothing."""
    return f"""
import json, os, shutil, tempfile, time
args = sys.argv[1:]
out = next(a for a in args if a.startswith("-sOutputFile="))[13:]
shutil.copyfile(args[-1], out)
where = os.path.realpath(tempfile.gettempdir())
with open({str(record)!r}, "w", encoding="utf-8") as fh:
    json.dump({{"gettempdir": where,
               "env": {{k: os.path.realpath(os.environ[k])
                        for k in ("TMPDIR", "TEMP", "TMP")
                        if k in os.environ}}}}, fh)
if where.startswith(os.path.realpath({str(temp_root)!r}) + os.sep):
    fd, _ = tempfile.mkstemp(prefix="gs_")
    os.write(fd, b"scratch")
    os.close(fd)
time.sleep(0.5)
"""


# Saves a copy, then stays long enough for Cancel to be polled during it.
_CHILD_COPIES_SLOWLY = """
import json, os, time, pymupdf
job = json.loads(sys.stdin.buffer.read())
doc = pymupdf.open(job['src'])
doc.save(job['dst'])
doc.close()
time.sleep(0.5)
os._exit(0)
"""


@pytest.fixture
def work_spy(tmp_path, monkeypatch, temp_root, fake_pikepdf):
    """Every pass with a stand-in that runs fast, and a record of where each
    temporary is made."""
    rec = {"mkdtemp": [], "mkstemp": [], "subset_dst": [],
           "gs": tmp_path / "gs.json"}
    real_mkdtemp, real_mkstemp = tempfile.mkdtemp, tempfile.mkstemp

    def mkdtemp(*a, **k):
        path = real_mkdtemp(*a, **k)
        rec["mkdtemp"].append(path)
        return path

    def mkstemp(*a, **k):
        fd, path = real_mkstemp(*a, **k)
        rec["mkstemp"].append(path)
        return fd, path

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(tempfile, "mkstemp", mkstemp)
    real_run = fs.run_subset

    def run_subset(src, dst, *a, **k):
        rec["subset_dst"].append(dst)
        return real_run(src, dst, *a, **k)

    monkeypatch.setattr(fs, "run_subset", run_subset)
    _fake_gs(monkeypatch, tmp_path, _gs_reports_its_temp_dir(rec["gs"],
                                                             temp_root))
    _use_child(monkeypatch, _script(tmp_path, "slow.py", _CHILD_COPIES_SLOWLY))
    return rec


def _assert_one_private_folder(rec, temp_root: Path, out: Path,
                               gs_ran: bool = True) -> None:
    (work,) = rec["mkdtemp"]
    assert Path(work).parent == temp_root
    assert Path(work).name.startswith("pdfapps-compress-")
    # The one file allowed elsewhere is the final write's, next to the output.
    assert [p for p in rec["mkstemp"]
            if Path(p).parent not in (Path(work), out.parent)] == []
    assert rec["subset_dst"] in ([], [os.path.join(work, "subset.pdf")])
    if gs_ran:
        seen = json.loads(rec["gs"].read_text(encoding="utf-8"))
        real = os.path.normcase(os.path.realpath(work))
        assert {k: os.path.normcase(v) for k, v in seen["env"].items()} == {
            "TMPDIR": real, "TEMP": real, "TMP": real}
        assert os.path.normcase(seen["gettempdir"]) == real
    assert list(temp_root.iterdir()) == []


def test_one_private_folder_holds_every_temporary_and_goes(
        tmp_path, temp_root, work_spy):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    subset_at_pass_c = []
    work = []

    def progress(stage, cur=0, tot=0):
        if stage == "passC":
            work[:] = work_spy["mkdtemp"]
            subset_at_pass_c.append(
                os.path.exists(os.path.join(work[0], "subset.pdf")))
        return True

    before, after = utils._compress_pdf(str(src), str(out),
                                        progress_fn=progress)
    assert 0 < after < before
    _assert_same_text(out, src)
    assert work_spy["subset_dst"], "the child never ran"
    # Through pass C the copy would only take disk space.
    assert subset_at_pass_c and not any(subset_at_pass_c)
    _assert_one_private_folder(work_spy, temp_root, out)


# (stage, the call of it to answer, what must exist by then). "gs" is with
# Ghostscript running and its scratch file written, "subset" with the child
# running and its copy saved; passC #2 is between pass C's open and save.
_CANCEL_POINTS = [("passA", 1, None), ("passA", 2, "gs"),
                  ("passB_setup", 1, None), ("passB_setup", 2, None),
                  ("passB_setup", 3, "subset"), ("passB_images", 1, None),
                  ("passB_save", 1, None), ("passC", 1, None),
                  ("passC", 2, None)]


@pytest.mark.parametrize("stage, n, wait_for", _CANCEL_POINTS,
                         ids=[f"{s}#{n}" for s, n, _w in _CANCEL_POINTS])
def test_a_cancel_at_any_point_leaves_nothing(stage, n, wait_for, tmp_path,
                                              temp_root, work_spy):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    calls = []

    def ready():
        if wait_for == "gs":
            return work_spy["gs"].exists()
        if wait_for == "subset":
            (work,) = work_spy["mkdtemp"]
            return os.path.exists(os.path.join(work, "subset.pdf"))
        return True

    def progress(s, cur=0, tot=0):
        if s == stage and calls.count(s) == n - 1 and not ready():
            return True  # not counted: wait for the state named above
        calls.append(s)
        return not (s == stage and calls.count(s) == n)

    with pytest.raises(utils.CancelledError):
        utils._compress_pdf(str(src), str(out), progress_fn=progress)
    assert calls.count(stage) == n
    assert not out.exists()
    gs_ran = (stage, n) != ("passA", 1)
    assert work_spy["gs"].exists() == gs_ran
    _assert_one_private_folder(work_spy, temp_root, out, gs_ran=gs_ran)


def _refuse_replace(*a, **k):
    raise PermissionError("the output is open elsewhere")


@pytest.mark.parametrize("failure", ["no gain", "wrong password",
                                     "output not writable",
                                     "old output not writable"])
def test_a_failure_leaves_nothing(failure, tmp_path, monkeypatch, temp_root,
                                  work_spy):
    """The last two fail with every pass's file still in the folder, and an
    output that was there before comes out of it as it was."""
    out = tmp_path / "out.pdf"
    old = None
    if failure == "old output not writable":
        old = b"old"
        out.write_bytes(old)
    password = None
    expected = ValueError
    if failure == "no gain":
        src = tmp_path / "in.pdf"
        with pymupdf.open() as doc:
            doc.new_page()
            # Without no_new_id MuPDF writes a random /ID, as hex or as an
            # escaped string depending on its bytes, so this file's size
            # moved by a few bytes from run to run: measured, in 8 runs of
            # 1000 it came out 2 bytes larger than what the passes made of
            # it, a gain, and no ValueError. With no /ID this file's size is
            # fixed, and so is the outcome (measured: 0 failures in 1000):
            # the fake gs's copy and pass C's save, neither with an /ID,
            # come out the same size as this file, pass B's save has an
            # /ID and comes out larger, and the tie is no gain by
            # construction. A MuPDF change that made pass C's save one
            # byte smaller would turn this test red again.
            doc.save(str(src), garbage=4, deflate=True, use_objstms=1,
                     no_new_id=True)
    else:
        src = _make_pdf(tmp_path / "in.pdf", password=PASSWORD)
    if failure == "wrong password":
        password, expected = "wrong", utils.WrongPasswordError
    elif failure.endswith("output not writable"):
        password, expected = PASSWORD, PermissionError
        monkeypatch.setattr(os, "replace", _refuse_replace)
    with pytest.raises(expected):
        utils._compress_pdf(str(src), str(out), password=password)
    if old is None:
        assert not out.exists()
    else:
        assert out.read_bytes() == old
    _assert_one_private_folder(work_spy, temp_root, out,
                               gs_ran=failure != "wrong password")
    left = sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".pdf")
    assert left == (["in.pdf"] if old is None else ["in.pdf", "out.pdf"])


def test_an_output_on_another_file_system_is_still_delivered(
        tmp_path, monkeypatch, temp_root, work_spy):
    """Off Windows the result is renamed out of the work folder, and a
    rename to another file system (a /tmp on tmpfs, the output on disk)
    fails with EXDEV: then it is copied next to the output and renamed
    there. Windows never renames out of the work folder, so there nothing
    is refused and the copy is the only way."""
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    real_replace = os.replace
    refused = []

    def replace(a, b, *args, **kwargs):
        if temp_root in Path(a).parents and temp_root not in Path(b).parents:
            refused.append(a)
            raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))
        return real_replace(a, b, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    before, after = utils._compress_pdf(str(src), str(out))
    assert 0 < after < before
    assert out.stat().st_size == after
    _assert_same_text(out, src)
    assert bool(refused) == (sys.platform != "win32")
    _assert_one_private_folder(work_spy, temp_root, out)
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".pdf") \
        == ["in.pdf", "out.pdf"]


def _readable_by_others(root: Path) -> list[str]:
    """Files under *root* that a user other than the owner can open: the
    file and every folder on the way to it, below *root*, let them in."""
    import stat
    found = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            path = Path(folder) / name
            try:
                mode = stat.S_IMODE(path.stat().st_mode)
                way = [stat.S_IMODE(d.stat().st_mode)
                       for d in path.parents if d != root
                       and root in d.parents]
            except FileNotFoundError:  # deleted while we looked
                continue
            if mode & 0o044 and all(m & 0o011 for m in way):
                found.append(f"{path.relative_to(root)} {oct(mode)}")
    return found


@_needs_linux
def test_no_temporary_is_readable_by_others_at_any_stage(tmp_path, temp_root,
                                                         work_spy):
    """Measured on the code before the folder, with umask 022: PyMuPDF's
    save turns pass B's 0600 mkstemp file into 0644, and it lay directly in
    the shared temporary folder."""
    src = _make_pdf(tmp_path / "in.pdf")
    exposed, stages = [], []

    def progress(stage, cur=0, tot=0):
        stages.append(stage)
        exposed.extend(f"{stage}: {f}" for f in _readable_by_others(temp_root))
        return True

    old = os.umask(0o022)
    try:
        utils._compress_pdf(str(src), str(tmp_path / "out.pdf"),
                            progress_fn=progress)
    finally:
        os.umask(old)
    assert {"passA", "passB_setup", "passB_save", "passC"} <= set(stages)
    assert exposed == []
    assert list(temp_root.iterdir()) == []


def _dacl(path) -> str | None:
    """The DACL of *path* in SDDL ("D:<flags>(ace)(ace)..."), None if it
    no longer exists."""
    import ctypes
    import ctypes.wintypes as wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32")
    get = advapi32.GetNamedSecurityInfoW
    get.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    get.restype = wintypes.DWORD
    to_str = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
    to_str.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                       ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    sd = ctypes.c_void_p()
    # SE_FILE_OBJECT = 1, DACL_SECURITY_INFORMATION = 4
    err = get(str(path), 1, 4, None, None, None, None, ctypes.byref(sd))
    if err in (2, 3):  # ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND
        return None
    assert err == 0, f"GetNamedSecurityInfoW({path}) failed: {err}"
    text = wintypes.LPWSTR()
    try:
        assert to_str(sd, 1, 4, ctypes.byref(text), None)
        value = text.value
    finally:
        kernel32.LocalFree(sd)
        if text:
            kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    return value


def _dacl_parts(sddl: str) -> tuple[str, set[str]]:
    """(the DACL's flags, the trustee of each ACE)."""
    m = re.fullmatch(r"D:([A-Z]*)((?:\([^)]*\))*)", sddl)
    assert m, sddl
    return m[1], {ace.split(";")[5] for ace in re.findall(r"\(([^)]*)\)", m[2])}


def _let_users_read(folder: Path) -> None:
    """Give the Users group read access to *folder* and what is made in it,
    so that something inheriting from it is plain to see."""
    icacls = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                          "System32", "icacls.exe")
    subprocess.run([icacls, str(folder), "/grant", "*S-1-5-32-545:(OI)(CI)R"],
                   check=True, capture_output=True)
    sddl = _dacl(folder)
    assert sddl is not None
    assert "BU" in _dacl_parts(sddl)[1]


# What mkdtemp gives the folder on Windows since the fix for CVE-2024-4030:
# only SYSTEM, Administrators and the owner.
_PRIVATE = {"SY", "BA", "OW"}


@_needs_windows
def test_no_temporary_is_open_to_others_at_any_stage_on_windows(
        tmp_path, temp_root, work_spy):
    """The Windows side of the test above. The temporary folder lets the
    Users group in, as a shared one would: the work folder must cut that
    off, and every file in it must inherit only the folder's own entries.
    A plain os.mkdir would inherit the temporary folder's entries."""
    _let_users_read(temp_root)
    src = _make_pdf(tmp_path / "in.pdf")
    seen, stages = {}, []

    def progress(stage, cur=0, tot=0):
        stages.append(stage)
        for work in work_spy["mkdtemp"]:
            for folder, _dirs, files in os.walk(work):
                for path in [folder, *(os.path.join(folder, f) for f in files)]:
                    sddl = _dacl(path)
                    if sddl is not None:  # deleted while we looked
                        seen[path] = sddl
        return True

    utils._compress_pdf(str(src), str(tmp_path / "out.pdf"),
                        progress_fn=progress)
    assert {"passA", "passB_setup", "passB_save", "passC"} <= set(stages)
    (work,) = work_spy["mkdtemp"]
    names = {Path(p).name for p in seen}
    # Not vacuous: gs's scratch file and the child's copy were looked at.
    assert "subset.pdf" in names
    assert any(n.startswith("gs_") for n in names)
    flags, trustees = _dacl_parts(seen.pop(work))
    assert "P" in flags, "the work folder inherits from the temporary folder"
    assert trustees <= _PRIVATE
    assert {p: _dacl_parts(s)[1] for p, s in seen.items()
            if not _dacl_parts(s)[1] <= _PRIVATE} == {}
    assert list(temp_root.iterdir()) == []


@_needs_windows
@pytest.mark.parametrize("existing", [False, True], ids=["new", "overwrite"])
def test_the_output_takes_the_access_list_of_its_folder(
        tmp_path, temp_root, no_gs, existing):
    """Renamed out of the private folder, the result kept that folder's
    entries, made explicit and protected: it did not inherit from where it
    landed and replaced the access list of the file it overwrote."""
    src = _make_pdf(tmp_path / "in.pdf")
    shared = tmp_path / "shared"
    shared.mkdir()
    _let_users_read(shared)
    out = shared / "out.pdf"
    if existing:
        out.write_bytes(b"old")
    utils._compress_pdf(str(src), str(out))
    fresh = shared / "fresh.txt"
    fresh.write_text("")
    assert _dacl(out) == _dacl(fresh)
    assert "BU" in _dacl_parts(_dacl(out))[1]
    assert sorted(p.name for p in shared.iterdir()) == ["fresh.txt", "out.pdf"]
    _assert_same_text(out, src)


def test_failed_child_means_the_original_is_what_pass_b_reads(
        tmp_path, monkeypatch, temp_root, no_gs):
    src = _make_pdf(tmp_path / "in.pdf")
    monkeypatch.setattr(fs, "run_subset", lambda *a, **k: fs.SUBSET_FAILED)
    opened = []
    real_open = pymupdf.open
    monkeypatch.setattr(pymupdf, "open",
                        lambda *a, **k: opened.append(a) or real_open(*a, **k))
    utils._compress_pdf(str(src), str(tmp_path / "out.pdf"))
    assert not [a for a in opened if a and "subset.pdf" in str(a[0])]


# ── 3b. run_subset does not raise ────────────────────────────────────────

def _boom(*a, **k):
    raise RuntimeError(f"boom {PASSWORD}")


@pytest.fixture
def spawned(monkeypatch, tmp_path):
    """A child that would wait forever, and the Popen objects made for it."""
    _use_child(monkeypatch, _hang_script(tmp_path, tmp_path / "pid"))
    procs: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def popen(*a, **k):
        procs.append(real_popen(*a, **k))
        return procs[-1]

    monkeypatch.setattr(subprocess, "Popen", popen)
    return procs


def _assert_failed_with_the_child_gone(tmp_path, procs, caplog, **kwargs):
    with caplog.at_level(logging.DEBUG, logger=fs.__name__):
        outcome = fs.run_subset("src", str(tmp_path / "o.pdf"), PASSWORD, 1,
                                **kwargs)
    assert outcome == fs.SUBSET_FAILED
    assert len(procs) == 1
    assert procs[0].poll() is not None, "the child outlived run_subset"
    # The patched failure was what ended it: the same outcome also comes from
    # the 120 s timeout, had the patch not bitten.
    assert "RuntimeError" in caplog.text
    assert PASSWORD not in caplog.text


def test_should_cancel_raising_is_a_failure_with_the_child_gone(
        tmp_path, spawned, caplog):
    _assert_failed_with_the_child_gone(tmp_path, spawned, caplog,
                                       should_cancel=_boom)


def test_the_feeder_thread_not_starting_is_a_failure_with_the_child_gone(
        tmp_path, monkeypatch, spawned, caplog):
    class NoThread(threading.Thread):
        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(fs.threading, "Thread", NoThread)
    _assert_failed_with_the_child_gone(tmp_path, spawned, caplog)


def test_job_helper_raising_is_a_failure_with_the_child_gone(
        tmp_path, monkeypatch, spawned, caplog):
    monkeypatch.setattr(fs, "_create_job_for", _boom)
    _assert_failed_with_the_child_gone(tmp_path, spawned, caplog)


def test_a_command_that_cannot_be_built_is_a_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(fs, "child_command", _boom)
    assert fs.run_subset("src", str(tmp_path / "o.pdf"), None, 1) == fs.SUBSET_FAILED


def test_a_job_that_cannot_be_serialized_is_a_failure(monkeypatch, tmp_path):
    def no_spawn(*a, **k):
        raise AssertionError("nothing to send: no child should start")

    monkeypatch.setattr(subprocess, "Popen", no_spawn)
    assert fs.run_subset(tmp_path, "dst", None, 1) == fs.SUBSET_FAILED


def test_a_spawn_error_of_another_type_is_a_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "Popen", _boom)
    assert fs.run_subset("src", str(tmp_path / "o.pdf"), None, 1) == fs.SUBSET_FAILED


def test_a_failed_kill_is_logged_and_still_waited_for(caplog):
    class Stubborn:
        pid = 1
        waited = False

        def poll(self):
            return None

        def kill(self):
            raise PermissionError("denied")

        def wait(self, timeout):
            self.waited = True
            return 0

    proc = Stubborn()
    with caplog.at_level(logging.INFO, logger=fs.__name__):
        fs._kill_and_wait(proc)
    assert proc.waited
    assert "kill failed" in caplog.text


@_needs_windows
def test_a_job_error_outside_the_usual_types_does_not_cost_the_subset(caplog):
    """int(object()) is a TypeError, as ctypes.ArgumentError is its own type."""
    from types import SimpleNamespace
    with caplog.at_level(logging.INFO, logger=fs.__name__):
        assert fs._create_job_for(SimpleNamespace(_handle=object())) is None
    assert "no kill-on-close Job" in caplog.text


@_needs_windows
def test_a_job_that_cannot_be_closed_does_not_change_the_outcome(
        tmp_path, monkeypatch, caplog):
    import ctypes

    src = _make_pdf(tmp_path / "in.pdf")
    dst = tmp_path / "out.pdf"
    real_close = fs._close_job

    def close(job):
        monkeypatch.setattr(ctypes, "WinDLL", _boom)
        real_close(job)

    monkeypatch.setattr(fs, "_close_job", close)
    with caplog.at_level(logging.INFO, logger=fs.__name__):
        assert fs.run_subset(str(src), str(dst), None, 3) == fs.SUBSET_OK
    assert "Job not closed" in caplog.text


def test_real_helpers_failing_inside_the_pipeline_cost_only_the_subset(
        tmp_path, monkeypatch, temp_root, no_gs):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    monkeypatch.setattr(fs, "child_command", _boom)
    seen, progress = _stages()
    utils._compress_pdf(str(src), str(out), progress_fn=progress)
    _assert_pass_b_survived(out, src, seen)
    assert list(temp_root.iterdir()) == []


# ── 4. The real entry ────────────────────────────────────────────────────

@pytest.fixture
def popen_spy(monkeypatch):
    calls = []
    real_popen = subprocess.Popen

    def popen(cmd, *a, **k):
        calls.append((list(cmd), k))
        return real_popen(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "Popen", popen)
    return calls


def test_real_entry_on_a_normal_pdf(tmp_path, temp_root, no_gs, popen_spy,
                                    monkeypatch):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    seen, progress = _stages()
    _, after = utils._compress_pdf(str(src), str(out), progress_fn=progress)
    assert SKIPPED not in seen
    assert len(popen_spy) == 1
    _assert_same_text(out, src)
    assert list(temp_root.iterdir()) == []
    # The windowed bundle has no console: without this each run flashes one.
    expected = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    assert popen_spy[0][1].get("creationflags") == expected

    # What the subset is worth: the same file, with the child failing.
    monkeypatch.setattr(fs, "run_subset", lambda *a, **k: fs.SUBSET_FAILED)
    _, without = utils._compress_pdf(str(src), str(tmp_path / "plain.pdf"))
    assert after < without * 0.75, (after, without)


def test_real_entry_on_encrypted_pdf_and_non_ascii_path(
        tmp_path, temp_root, no_gs, popen_spy, caplog):
    folder = tmp_path / "pasta çãé 中文"
    folder.mkdir()
    src = _make_pdf(folder / "ficheiro 中.pdf", password=PASSWORD)
    out = folder / "saída 中.pdf"
    seen, progress = _stages()
    with caplog.at_level(logging.DEBUG):
        before, after = utils._compress_pdf(str(src), str(out),
                                            progress_fn=progress,
                                            password=PASSWORD)
    assert SKIPPED not in seen
    assert after < before
    _assert_same_text(out, src, PASSWORD)
    assert list(temp_root.iterdir()) == []

    (cmd, kwargs), = popen_spy
    assert not [arg for arg in cmd if PASSWORD in arg]
    assert kwargs.get("env") is None
    assert not [v for v in os.environ.values() if PASSWORD in v]
    assert PASSWORD not in caplog.text
    assert "font subset child: ok, rc=0" in caplog.text


def test_password_stays_out_of_the_log_when_the_child_fails(
        tmp_path, monkeypatch, temp_root, no_gs, caplog):
    src = _make_pdf(tmp_path / "in.pdf", password=PASSWORD)
    _use_child(monkeypatch, _script(tmp_path, "crash.py", CRASH_BODY))
    with caplog.at_level(logging.DEBUG):
        utils._compress_pdf(str(src), str(tmp_path / "out.pdf"),
                            password=PASSWORD)
    assert "font subset child" in caplog.text
    assert PASSWORD not in caplog.text


def _run_entry(job: dict, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, str(ROOT / "pdfapps.py"), fs.WORKER_FLAG],
        input=json.dumps(job).encode("ascii"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, **kwargs)


def _job(src, dst, password=None):
    return {"src": str(src), "dst": str(dst), "password": password,
            "parent_pid": os.getpid()}


def test_entry_with_the_wrong_password_exits_two_without_output(tmp_path):
    src = _make_pdf(tmp_path / "in.pdf", password=PASSWORD)
    dst = tmp_path / "out.pdf"
    result = _run_entry(_job(src, dst, "wrong"))
    assert result.returncode == 2
    assert not dst.exists()


def test_entry_from_source_never_loads_qt(tmp_path):
    """A PySide6 that blows up on import must not disturb the child.

    From source only: in the bundle PyInstaller's runtime hook has already
    imported part of PySide6 before pdfapps.py runs. See app/_font_subset.py.
    """
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "PySide6.py").write_text("raise SystemExit(99)\n",
                                       encoding="utf-8")
    src = _make_pdf(tmp_path / "in.pdf")
    dst = tmp_path / "out.pdf"
    env = dict(os.environ, PYTHONPATH=str(poison))
    result = _run_entry(_job(src, dst), env=env)
    assert result.returncode == 0, result.stderr
    _assert_same_text(dst, src)


def test_entry_does_not_set_up_logging_or_touch_the_config(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
               APPDATA=str(home), LOCALAPPDATA=str(home),
               XDG_CONFIG_HOME=str(home))
    src = _make_pdf(tmp_path / "in.pdf")
    assert _run_entry(_job(src, tmp_path / "o.pdf"), env=env).returncode == 0
    assert list(home.iterdir()) == []


def test_child_reads_the_job_with_no_sys_stdin(tmp_path):
    """The fallback of _read_job_bytes. No bundle reaches it today (measured:
    the frozen child has a sys.stdin), but the pipe would still be fd 0."""
    script = _script(tmp_path, "none.py", """
sys.stdin = None
from app._font_subset import worker_main
worker_main()
""")
    src = _make_pdf(tmp_path / "in.pdf")
    dst = tmp_path / "out.pdf"
    result = subprocess.run([PY, "-I", script],
                            input=json.dumps(_job(src, dst)).encode("ascii"),
                            timeout=60, check=False)
    assert result.returncode == 0
    _assert_same_text(dst, src)


@pytest.mark.parametrize("stdin", [b"", b"not json", b'{"src": "x"}'])
def test_entry_with_a_bad_job_exits_two_silently(stdin):
    result = subprocess.run(
        [PY, str(ROOT / "pdfapps.py"), fs.WORKER_FLAG], input=stdin,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert result.returncode == 2
    assert result.stderr == b""


@pytest.mark.parametrize("body", ["raise RuntimeError('boom')\n",
                                  "raise SystemExit(7)\n",
                                  "import no_such_module_at_all\n",
                                  "syntax error here\n"])
def test_failing_import_of_the_module_leaves_by_os_exit(tmp_path, body):
    """The whole flag block is guarded: an escape means the bootloader's
    "Unhandled exception" dialog in the windowed bundle."""
    shutil.copy(ROOT / "pdfapps.py", tmp_path / "pdfapps.py")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "_font_subset.py").write_text(body, encoding="utf-8")
    result = subprocess.run(
        [PY, str(tmp_path / "pdfapps.py"), fs.WORKER_FLAG],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=60)
    assert result.returncode == 2
    assert result.stderr == b""


def test_the_child_saves_without_rewriting_content_streams(tmp_path):
    """clean=True reads "(f)Tj 0 0 TD (faeces)Tj" back as "ffaeces"."""
    src = tmp_path / "overprint.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    # Registers /helv in the page resources for the hand-written stream.
    page.insert_text((0, -50), " ", fontname="helv", fontsize=1)
    doc.update_stream(page.get_contents()[0],
                      b"BT /helv 24 Tf 1 0 0 1 100 700 Tm "
                      b"(f)Tj 0 0 TD (faeces)Tj ET")
    doc.save(str(src))
    doc.close()
    dst = tmp_path / "out.pdf"
    assert fs.run_subset(str(src), str(dst), None, 1) == fs.SUBSET_OK
    with pymupdf.open(str(dst)) as saved:
        assert saved[0].get_text().split() == ["faeces"]


def test_a_non_ascii_password_survives_the_trip(tmp_path):
    src = _make_pdf(tmp_path / "in.pdf", password=PASSWORD)
    dst = tmp_path / "out.pdf"
    assert fs.run_subset(str(src), str(dst), PASSWORD, 3) == fs.SUBSET_OK
    _assert_same_text(dst, src, PASSWORD)


# ── 5. Order and shape of the entry ──────────────────────────────────────

def test_flag_check_comes_before_every_heavy_import():
    tree = ast.parse((ROOT / "pdfapps.py").read_text(encoding="utf-8"))
    flag_index = next(
        i for i, node in enumerate(tree.body)
        if isinstance(node, ast.If) and fs.WORKER_FLAG in ast.dump(node.test))
    flag = tree.body[flag_index]

    for node in tree.body[:flag_index]:
        if isinstance(node, ast.Import):
            assert {a.name for a in node.names} <= {"os", "sys"}
        else:  # the module docstring
            assert isinstance(node, ast.Expr)

    # Everything after it, at any depth, including main()'s setup_logging()
    # and send_to_existing(): nothing else runs before the flag is tested.
    def names(node):
        if isinstance(node, ast.Import):
            return [a.name for a in node.names]
        if isinstance(node, ast.ImportFrom):
            return [node.module or ""]
        return []

    later = [n for stmt in tree.body[flag_index + 1:] for sub in ast.walk(stmt)
             for n in names(sub)]
    assert any(n.startswith("PySide6") for n in later), "guard went vacuous"
    inside = [n for sub in ast.walk(flag) for n in names(sub)]
    assert inside == ["app._font_subset"]

    # M3: all of it under one try whose finally leaves through os._exit.
    guard = next(n for n in flag.body if isinstance(n, ast.Try))
    assert len(flag.body) == 1
    assert "_exit" in ast.dump(guard.finalbody[0])


def test_the_module_stays_free_of_qt_and_app_imports():
    source = (ROOT / "app" / "_font_subset.py").read_text(encoding="utf-8")
    # The snap still runs on Python 3.10.
    tree = ast.parse(source, feature_version=(3, 10))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            assert not name.startswith(("PySide6", "app", "qtawesome")), name
    assert "from __future__ import annotations" in source


def test_importing_the_module_does_not_load_pymupdf_or_qt(tmp_path):
    script = _script(tmp_path, "probe.py", """
import app._font_subset
bad = sorted(m for m in sys.modules
             if m.split(".")[0] in ("PySide6", "pymupdf", "shiboken6"))
sys.exit(1 if bad else 0)
""")
    assert subprocess.run([PY, "-I", script], check=False,
                          timeout=60).returncode == 0


def test_command_from_source_is_absolute_and_independent_of_argv(
        monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["wrong/thing.py"])
    monkeypatch.chdir(tmp_path)
    cmd = fs.child_command()
    assert cmd == [sys.executable, str(ROOT / "pdfapps.py"), fs.WORKER_FLAG]
    assert "-I" not in cmd


def test_frozen_command_is_the_executable_and_the_flag(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["launcher"])
    assert fs.child_command() == [sys.executable, fs.WORKER_FLAG]


# ── 6. Environment ───────────────────────────────────────────────────────

def test_child_inherits_the_bootloader_variables(tmp_path, monkeypatch,
                                                 popen_spy):
    planted = {"_PYI_APPLICATION_HOME_DIR": "/mei/x",
               "_PYI_PARENT_PROCESS_LEVEL": "1",
               "_PYI_ARCHIVE_FILE": "/bundle",
               "_MEIPASS2": "/mei/x",
               "LD_LIBRARY_PATH": "/mei/x",
               "PYTHONPATH": "/snap/lib"}
    for name, value in planted.items():
        monkeypatch.setenv(name, value)
    dump = tmp_path / "env.json"
    script = _script(tmp_path, "env.py", f"""
import json, os
with open({str(dump)!r}, "w") as fh:
    json.dump(dict(os.environ), fh)
""")
    _use_child(monkeypatch, script)
    fs.run_subset("src", str(tmp_path / "o.pdf"), None, 1)
    seen = json.loads(dump.read_text())
    assert {k: seen.get(k) for k in planted} == planted
    assert popen_spy[0][1].get("env") is None


# ── 7. Nothing else calls it in the app's process ────────────────────────

def test_subset_fonts_only_in_the_module_and_the_editor():
    # The Editor is a known exception, not an oversight: it has no reproducer
    # and that path is being rewritten by the redesign.
    allowed = {"app/_font_subset.py": 1, "app/editor/apply_edits.py": 1}
    found: dict[str, int] = {}
    files = [*(ROOT / "app").rglob("*.py"), ROOT / "pdfapps.py"]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            hit = ((isinstance(node, ast.Attribute)
                    and node.attr == "subset_fonts")
                   or (isinstance(node, ast.Constant)
                       and node.value == "subset_fonts"))
            if hit:
                found[rel] = found.get(rel, 0) + 1
    assert found == allowed


# ── 8. The child ends with its parent ────────────────────────────────────

def _spawn_orphanable(tmp_path: Path, patch_child: str = ""):
    """A driver in the middle: pytest -> driver (run_subset) -> real worker,
    with only subset() replaced by a wait. Returns (driver, child pid)."""
    src = _make_pdf(tmp_path / "in.pdf")
    pid_file = tmp_path / "pid"
    child = _script(tmp_path, "child.py", f"""
import os, time
import app._font_subset as m
def hang(*a, **k):
    with open({str(pid_file)!r}, "w") as fh:
        fh.write(str(os.getpid()))
    time.sleep(600)
m.subset = hang
{patch_child}
m.worker_main()
""")
    driver = _script(tmp_path, "driver.py", f"""
import threading
import app._font_subset as m
m.child_command = lambda: [sys.executable, "-I", {child!r}]
# From a secondary thread, as the app does: PDEATHSIG belongs to the thread.
threading.Thread(target=m.run_subset,
                 args=({str(src)!r}, {str(tmp_path / "o.pdf")!r}, None, 3)
                 ).start()
threading.Event().wait()
""")
    proc = subprocess.Popen([PY, "-I", driver], stdin=subprocess.DEVNULL)
    _wait_for_file(pid_file)
    return proc, int(pid_file.read_text())


def test_child_dies_when_the_parent_is_killed(tmp_path):
    driver, pid = _spawn_orphanable(tmp_path)
    try:
        time.sleep(1.5)
        assert _alive(pid), "the child did not survive with a live parent"
        driver.kill()
        driver.wait(10)
        _wait_dead(pid)
    finally:
        driver.kill()
        driver.wait(10)
        if _alive(pid):
            _kill_pid(pid)


def _kill_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.kill(pid, 9)


@pytest.mark.skipif(os.name == "nt", reason="the POSIX fallback")
def test_getppid_watch_works_without_prctl(tmp_path):
    """What macOS gets, exercised wherever POSIX is available."""
    driver, pid = _spawn_orphanable(
        tmp_path, patch_child="m._set_pdeathsig = lambda: False")
    try:
        time.sleep(1.5)
        assert _alive(pid)
        driver.kill()
        driver.wait(10)
        _wait_dead(pid)
    finally:
        driver.kill()
        driver.wait(10)
        if _alive(pid):
            _kill_pid(pid)


class _FakeSignal:
    """Stands in for the signal module, which on Windows has no SIGALRM, so
    that the fallback macOS depends on is exercised on every platform."""
    SIGALRM = 14
    SIG_DFL = 0

    def __init__(self):
        self.calls: list[tuple] = []

    def signal(self, number, handler):
        self.calls.append(("disposition", number, handler))

    def alarm(self, seconds):
        self.calls.append(("alarm", seconds))


@pytest.fixture
def posix_tie(monkeypatch):
    """_tie_life_to_parent as on macOS, with nothing really armed or started."""
    from types import SimpleNamespace

    class Harness:
        signals = _FakeSignal()
        threads: list[dict] = []

    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            Harness.threads.append(self.kwargs)

    def exit_now(code):
        raise SystemExit(code)

    Harness.threads = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(fs, "signal", Harness.signals)
    monkeypatch.setattr(fs, "threading", SimpleNamespace(Thread=FakeThread))
    monkeypatch.setattr(os, "getppid", lambda: 42)
    monkeypatch.setattr(os, "_exit", exit_now)
    return Harness


def test_macos_arms_the_watch_and_the_alarm_after_the_parents_deadline(
        posix_tie):
    fs._tie_life_to_parent(42)
    (thread,) = posix_tie.threads
    assert thread["target"] is fs._watch_parent
    assert thread["args"] == (42,)
    assert thread["daemon"] is True
    # Default action first, or an inherited SIG_IGN turns the alarm into
    # nothing; the delay is past the parent's own 120 s, so it cannot end a
    # child whose parent is still alive and waiting for it.
    assert posix_tie.signals.calls == [
        ("disposition", _FakeSignal.SIGALRM, _FakeSignal.SIG_DFL),
        ("alarm", fs.CHILD_TIMEOUT_S + fs._ALARM_MARGIN_S)]
    assert fs._ALARM_MARGIN_S > 0


def test_working_prctl_arms_neither(posix_tie, monkeypatch):
    monkeypatch.setattr(fs, "_set_pdeathsig", lambda: True)
    fs._tie_life_to_parent(42)
    assert posix_tie.threads == []
    assert posix_tie.signals.calls == []


def test_refused_prctl_falls_back_to_both(posix_tie, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(fs, "_set_pdeathsig", lambda: False)
    fs._tie_life_to_parent(42)
    assert len(posix_tie.threads) == 1
    assert posix_tie.signals.calls[-1][0] == "alarm"


def test_no_parent_pid_arms_nothing_and_does_not_exit(posix_tie):
    """The smoke script's case: the bootloader stands in between."""
    fs._tie_life_to_parent(None)
    assert posix_tie.threads == []
    assert posix_tie.signals.calls == []


def test_windows_arms_nothing_here(posix_tie, monkeypatch):
    """There the Job does it, and the signal module has no alarm at all."""
    monkeypatch.setattr(sys, "platform", "win32")
    fs._tie_life_to_parent(99)
    assert posix_tie.threads == []
    assert posix_tie.signals.calls == []


def test_a_parent_already_gone_after_arming_exits(posix_tie):
    with pytest.raises(SystemExit) as gone:
        fs._tie_life_to_parent(99)
    assert gone.value.code == fs._RC_PARENT_GONE
    assert posix_tie.signals.calls[-1][0] == "alarm", "checked after arming"


@pytest.mark.skipif(os.name == "nt", reason="the POSIX fallback")
def test_alarm_ends_a_native_call_that_holds_the_gil_and_never_returns(
        tmp_path):
    """The case the getppid thread cannot reach: it would need the GIL."""
    pid_file = tmp_path / "pid"
    child = _script(tmp_path, "gil.py", f"""
import ctypes, os, signal
# As if inherited from a parent that ignores it: SIG_IGN survives exec.
signal.signal(signal.SIGALRM, signal.SIG_IGN)
import app._font_subset as m
def hang(*a, **k):
    with open({str(pid_file)!r}, "w") as fh:
        fh.write(str(os.getpid()))
    # PyDLL keeps the GIL through the call, as a native crash path can.
    ctypes.PyDLL(None).sleep(300)
m.subset = hang
m._set_pdeathsig = lambda: False
m.CHILD_TIMEOUT_S = 2
m._ALARM_MARGIN_S = 0
m.worker_main()
""")
    proc = subprocess.Popen([PY, "-I", child], stdin=subprocess.PIPE)
    try:
        proc.communicate(json.dumps(_job("s", "d")).encode("ascii"), timeout=60)
    finally:
        proc.kill()
    import signal
    assert proc.returncode == -signal.SIGALRM
    assert pid_file.exists()


@_needs_linux
def test_prctl_working_leaves_no_alarm_armed(tmp_path):
    """A long subset under a live parent is only bound by the parent."""
    script = _script(tmp_path, "noalarm.py", """
import os, signal
import app._font_subset as m
m._tie_life_to_parent(os.getppid())
sys.exit(0 if signal.alarm(0) == 0 else 1)
""")
    assert subprocess.run([PY, "-I", script], check=False,
                          timeout=60).returncode == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX only")
def test_child_of_an_already_dead_parent_exits(tmp_path):
    """The race: parent gone before the child armed anything."""
    src = _make_pdf(tmp_path / "in.pdf")
    dst = tmp_path / "out.pdf"
    job = _job(src, dst)
    job["parent_pid"] = os.getpid() + 1
    result = _run_entry(job)
    assert result.returncode == 3
    assert not dst.exists()


@_needs_linux
def test_prctl_is_really_armed(tmp_path):
    script = _script(tmp_path, "arm.py", """
import ctypes, signal
import app._font_subset as m
assert m._set_pdeathsig() is True
libc = ctypes.CDLL(None)
value = ctypes.c_int()
libc.prctl(2, ctypes.byref(value), 0, 0, 0)  # PR_GET_PDEATHSIG
sys.exit(0 if value.value == signal.SIGKILL else 1)
""")
    assert subprocess.run([PY, "-I", script], check=False,
                          timeout=60).returncode == 0


@_needs_windows
def test_job_failure_does_not_cost_the_subset(tmp_path, monkeypatch, caplog):
    import ctypes

    def refuse(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(ctypes, "WinDLL", refuse)
    src = _make_pdf(tmp_path / "in.pdf")
    dst = tmp_path / "out.pdf"
    with caplog.at_level(logging.INFO, logger=fs.__name__):
        assert fs.run_subset(str(src), str(dst), None, 3) == fs.SUBSET_OK
    assert "no kill-on-close Job" in caplog.text


@_needs_windows
def test_job_refused_by_the_system_is_logged_and_survived(monkeypatch, caplog):
    """A nested Job can be refused: AssignProcessToJobObject returns 0."""
    from types import SimpleNamespace
    invalid = SimpleNamespace(_handle=0)
    with caplog.at_level(logging.INFO, logger=fs.__name__):
        assert fs._create_job_for(invalid) is None
    assert "no kill-on-close Job" in caplog.text


@_needs_windows
def test_child_sets_the_error_mode_before_anything_else(tmp_path):
    """CREATE_DEFAULT_ERROR_MODE, or Git Bash's mode 3 hides the difference.

    Only reads the mode: no crash happens here, so WER is not involved.
    """
    out = tmp_path / "mode"
    script = _script(tmp_path, "mode.py", f"""
import ctypes
import app._font_subset as m
before = ctypes.windll.kernel32.GetErrorMode()
def report():
    after = ctypes.windll.kernel32.GetErrorMode()
    with open({str(out)!r}, "w") as fh:
        fh.write(f"{{before}} {{after}}")
    raise SystemExit
m._read_job_bytes = report
m.worker_main()
""")
    result = subprocess.run(
        [PY, "-I", script], stdin=subprocess.DEVNULL, timeout=60, check=False,
        creationflags=subprocess.CREATE_DEFAULT_ERROR_MODE)
    assert result.returncode == 2
    before, after = map(int, out.read_text().split())
    assert before & 0x8003 != 0x8003, "the control does not discriminate"
    assert after & 0x8003 == 0x8003


# ── 9. The warning ───────────────────────────────────────────────────────

def test_warning_is_in_all_languages_and_keeps_parity():
    data = json.loads((ROOT / "app" / "translations.json")
                      .read_text(encoding="utf-8"))
    assert len(data) == 8
    texts = [bundle["tool.compress.fonts_skipped"] for bundle in data.values()]
    assert all(text.strip() for text in texts)
    assert len(set(texts)) == 8
    assert all("PDF" in text for text in texts), "the word every string uses"
    assert data["pt"]["tool.compress.fonts_skipped"] == (
        "As fontes deste PDF não foram otimizadas. O ficheiro está "
        "correto, mas pode ficar maior.")
    assert len({frozenset(bundle) for bundle in data.values()}) == 1


@pytest.fixture
def page(monkeypatch, tmp_path):
    """TabComprimir with _compress_pdf replaced and the task run inline."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.i18n import t
    from app.tools import compress as tool

    _unused_app = QApplication.instance() or QApplication([])
    src = _make_pdf(tmp_path / "in.pdf", pages=1)

    class Harness:
        pass

    h = Harness()
    h.note = t("tool.compress.fonts_skipped")
    h.emitted, h.dialogs, h.pipeline, h.stages = [], [], [], []
    h.result = (1000, 500)
    h.widget = tool.TabComprimir(lambda *_: None)
    h.widget.drop_in.set_path(str(src))
    h.widget.drop_out.set_path(str(tmp_path / "out.pdf"))
    h.widget._pdf_password = None

    def fake_compress(_src, _dst, _level, progress_fn=None, password=None):
        for stage in h.stages:
            progress_fn(stage)
        if isinstance(h.result, Exception):
            raise h.result
        return h.result

    def fake_run_task(_parent, runner, _dlg, on_finished, on_error=None):
        runner.progress.connect(
            lambda pct, label: h.emitted.append((pct, label)))
        on_finished(runner.do_work())

    monkeypatch.setattr(tool, "_compress_pdf", fake_compress)
    monkeypatch.setattr(tool, "run_task", fake_run_task)
    monkeypatch.setattr(tool, "_find_gs", lambda: "gs")
    monkeypatch.setattr(QMessageBox, "information",
                        lambda _p, _title, text: h.dialogs.append(text))
    monkeypatch.setattr(h.widget, "_pipeline_success",
                        lambda msg, path: h.pipeline.append(msg))
    h.run = h.widget._run
    yield h
    h.widget.deleteLater()


def test_skip_stage_does_not_touch_the_bar(page):
    page.stages = ["passB_setup", "passB_fonts_skipped", "passB_save"]
    page.run()
    assert [pct for pct, _ in page.emitted] == [20, 70]
    assert all(label for _, label in page.emitted)


def test_final_dialog_gets_the_warning_only_when_fonts_were_skipped(page):
    page.stages = ["passB_setup"]
    page.run()
    assert page.note not in page.dialogs[-1]

    page.stages = ["passB_fonts_skipped"]
    page.run()
    assert page.note in page.dialogs[-1]


def test_a_later_run_does_not_inherit_the_warning(page):
    page.stages = ["passB_fonts_skipped"]
    page.run()
    page.stages = []
    page.run()
    assert page.note not in page.dialogs[-1]


def test_pipeline_toast_gets_the_warning(page):
    page.widget._pipeline_active = True
    page.stages = ["passB_fonts_skipped"]
    page.run()
    assert page.dialogs == []
    assert page.note in page.pipeline[-1]


def test_no_gain_dialog_does_not_claim_the_file_is_fine(page):
    """No file was written, so "the file is correct" would be false there."""
    page.stages = ["passB_fonts_skipped"]
    page.result = ValueError("no gain")
    page.run()
    assert len(page.dialogs) == 1
    assert page.note not in page.dialogs[0]


# ── 10. The warning is true ──────────────────────────────────────────────
#
# Ghostscript subsets fonts on its own, so a failed child costs its result
# nothing. Measured: same size and same fonts with the child failing or not.

_GS_COPIES_THE_INPUT = """
import shutil
args = sys.argv[1:]
out = next(a for a in args if a.startswith("-sOutputFile="))[13:]
shutil.copyfile(args[-1], out)
"""


def _gs_writes_a_small_pdf(lines: int, copy_to: Path | None = None) -> str:
    """Far smaller than the whole font, with a Producer to recognise it by."""
    copy = "" if copy_to is None else f"shutil.copyfile(out, {str(copy_to)!r})"
    return f"""
import shutil
import pymupdf
args = sys.argv[1:]
out = next(a for a in args if a.startswith("-sOutputFile="))[13:]
doc = pymupdf.open()
for i in range(3):
    page = doc.new_page()
    for y in range({lines}):
        page.insert_text((72, 72 + y), "fake gs " * 8, fontname="helv", fontsize=1)
doc.set_metadata({{"producer": "fake gs"}})
doc.save(out)
{copy}
"""


def _producer(path: Path) -> str:
    with pymupdf.open(str(path)) as doc:
        return doc.metadata["producer"]


def _crash_child(monkeypatch, tmp_path) -> None:
    _use_child(monkeypatch, _script(tmp_path, "crash.py", CRASH_BODY))


def test_no_warning_when_ghostscripts_result_wins(tmp_path, monkeypatch,
                                                  temp_root):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    _fake_gs(monkeypatch, tmp_path, _gs_writes_a_small_pdf(1))
    _crash_child(monkeypatch, tmp_path)
    seen, progress = _stages()
    utils._compress_pdf(str(src), str(out), progress_fn=progress)
    assert _producer(out) == "fake gs"
    assert SKIPPED not in seen
    assert list(temp_root.iterdir()) == []


def test_no_warning_when_pass_c_improved_on_ghostscript(tmp_path, monkeypatch,
                                                        temp_root):
    """Pass C's file is Ghostscript's file, restructured: the same fonts."""
    pytest.importorskip("pikepdf")
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    gs_result = tmp_path / "gs result.pdf"
    _fake_gs(monkeypatch, tmp_path, _gs_writes_a_small_pdf(600, gs_result))
    _crash_child(monkeypatch, tmp_path)
    seen, progress = _stages()
    utils._compress_pdf(str(src), str(out), progress_fn=progress)
    assert _producer(out) == "fake gs"
    assert out.stat().st_size < gs_result.stat().st_size, "pass C did not win"
    assert SKIPPED not in seen


@pytest.fixture
def fake_pikepdf(monkeypatch):
    """Pass C without pikepdf, which is optional and absent from CI and from
    the project's venv: it copies the best result so far with a stronger save,
    so that the file it writes is that result, only smaller."""
    from types import SimpleNamespace

    class Opened:
        def __init__(self, path):
            self.path = path

        def save(self, out, **_kwargs):
            with pymupdf.open(self.path) as doc:
                doc.save(out, garbage=4, deflate=True, deflate_fonts=True,
                         use_objstms=1)

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "pikepdf", SimpleNamespace(
        open=lambda path, **_k: Opened(path),
        ObjectStreamMode=SimpleNamespace(generate=None)))


def test_no_warning_when_a_stand_in_pass_c_improved_on_ghostscript(
        tmp_path, monkeypatch, temp_root, fake_pikepdf):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    gs_result = tmp_path / "gs result.pdf"
    _fake_gs(monkeypatch, tmp_path, _gs_writes_a_small_pdf(600, gs_result))
    _crash_child(monkeypatch, tmp_path)
    seen, progress = _stages()
    utils._compress_pdf(str(src), str(out), progress_fn=progress)
    assert _producer(out) == "fake gs"
    assert out.stat().st_size < gs_result.stat().st_size, "pass C did not win"
    assert SKIPPED not in seen


def test_warning_when_a_stand_in_pass_c_improved_on_pass_b(
        tmp_path, monkeypatch, temp_root, no_gs, fake_pikepdf):
    src = _make_pdf(tmp_path / "in.pdf")
    _crash_child(monkeypatch, tmp_path)
    seen, progress = _stages()
    utils._compress_pdf(str(src), str(tmp_path / "out.pdf"),
                        progress_fn=progress)
    assert SKIPPED in seen


def test_warning_when_pass_b_beats_a_worse_ghostscript(tmp_path, monkeypatch,
                                                       temp_root):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    # The whole font uncompressed: larger than what pass B makes of it.
    _fake_gs(monkeypatch, tmp_path, _GS_COPIES_THE_INPUT)
    _crash_child(monkeypatch, tmp_path)
    seen, progress = _stages()
    utils._compress_pdf(str(src), str(out), progress_fn=progress)
    assert SKIPPED in seen
    assert list(temp_root.iterdir()) == []


def test_cancel_on_the_final_notice_cleans_up_with_a_ghostscript_result(
        tmp_path, monkeypatch, temp_root):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    _fake_gs(monkeypatch, tmp_path, _GS_COPIES_THE_INPUT)
    _crash_child(monkeypatch, tmp_path)
    with pytest.raises(utils.CancelledError):
        utils._compress_pdf(str(src), str(out),
                            progress_fn=lambda s, c=0, n=0: s != SKIPPED)
    assert not out.exists()
    assert list(temp_root.iterdir()) == []


def test_no_warning_when_the_child_worked_and_ghostscript_lost(
        tmp_path, monkeypatch, temp_root):
    src = _make_pdf(tmp_path / "in.pdf")
    _fake_gs(monkeypatch, tmp_path, _GS_COPIES_THE_INPUT)
    seen, progress = _stages()
    utils._compress_pdf(str(src), str(tmp_path / "out.pdf"),
                        progress_fn=progress)
    assert SKIPPED not in seen


def test_no_warning_when_no_file_comes_out(tmp_path, monkeypatch, temp_root,
                                           no_gs):
    """The stage says the file delivered lacks a subset: there is no file."""
    src = tmp_path / "in.pdf"
    doc = pymupdf.open()
    doc.new_page()
    # no_new_id fixes this file's size. Pass B's save, the only candidate
    # here, has an /ID and always comes out 142 to 149 bytes larger, so
    # there is no gain (see test_a_failure_leaves_nothing).
    doc.save(str(src), garbage=4, deflate=True, use_objstms=1,
             no_new_id=True)
    doc.close()
    _crash_child(monkeypatch, tmp_path)
    seen, progress = _stages()
    with pytest.raises(ValueError):
        utils._compress_pdf(str(src), str(tmp_path / "out.pdf"),
                            progress_fn=progress)
    assert SKIPPED not in seen
    assert list(temp_root.iterdir()) == []


@pytest.mark.skipif(not utils._find_gs(), reason="needs a real Ghostscript")
def test_real_ghostscript_with_a_failing_child_gives_no_warning(
        tmp_path, monkeypatch, temp_root):
    src = _make_pdf(tmp_path / "in.pdf")
    out = tmp_path / "out.pdf"
    _crash_child(monkeypatch, tmp_path)
    seen, progress = _stages()
    utils._compress_pdf(str(src), str(out), progress_fn=progress)
    assert "Ghostscript" in _producer(out)
    assert SKIPPED not in seen
    _assert_same_text(out, src)


@pytest.mark.parametrize("gs_wins", [True, False])
def test_the_dialog_tells_the_truth_with_the_real_pipeline(
        gs_wins, page, tmp_path, monkeypatch):
    from app.tools import compress as tool

    monkeypatch.setattr(tool, "_compress_pdf", utils._compress_pdf)
    src = _make_pdf(tmp_path / "large.pdf")
    page.widget.drop_in.set_path(str(src))
    _crash_child(monkeypatch, tmp_path)
    if gs_wins:
        _fake_gs(monkeypatch, tmp_path, _gs_writes_a_small_pdf(1))
    else:
        monkeypatch.setattr(utils, "_find_gs", lambda: None)
    page.run()
    assert (page.note in page.dialogs[-1]) is not gs_wins


# ── 11. The toast shows all of it ────────────────────────────────────────

LANGUAGES = ("en", "pt", "es", "fr", "de", "zh", "it", "nl")
_LONG_PATH = (r"C:\Users\nelso\AppData\Local\Temp\pdfapps_abc123"
              r"\um_ficheiro_com_nome_bastante_comprido_rotated.pdf")


def _settle(app):
    for _ in range(6):
        app.processEvents()


@pytest.fixture
def toast_page(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication

    from app import i18n
    from app.tools import compress as tool

    app = QApplication.instance() or QApplication([])
    if not i18n._TRANSLATIONS:
        i18n._load_translations()
    result = tmp_path / "result.pdf"
    result.write_bytes(b"%PDF-1.7\n")

    def build(lang: str, width: int, sheet: str):
        # Not set_language(): that one writes the user's config.
        monkeypatch.setattr(i18n, "_LANG", lang)
        built = tool.TabComprimir(lambda *_: None)
        built.setStyleSheet(sheet)
        built.resize(width, 700)
        built.show()
        _settle(app)
        return built, str(result), app

    made = []

    def tracked(*args):
        built = build(*args)
        made.append(built[0])
        return built

    yield tracked
    for widget in made:
        widget.close()
        widget.deleteLater()


def _assert_toast_is_whole(page, app, message: str, width: int) -> None:
    from PySide6.QtCore import QPoint, QRect, Qt
    from PySide6.QtWidgets import QLabel, QPushButton

    _settle(app)
    # Every check below is relative to the page, and a label that does not
    # wrap makes the top-level page grow to fit it: on its own that passes all.
    assert page.width() == width, "the toast widened the page"
    toast = page._toast_widget
    label = toast.findChild(QLabel)
    assert label.text().replace("\u200b", "") == f"✔ {message}"
    # Worked out here and not with heightForWidth, which is -1 for a label
    # that does not wrap: as tall as the wrapped text needs, and no single
    # piece of it wider than the label, which is what a clipped path looks like.
    area = label.contentsRect()
    needed = label.fontMetrics().boundingRect(
        QRect(0, 0, area.width(), 100000), int(Qt.TextFlag.TextWordWrap),
        label.text())
    assert needed.height() <= area.height(), (needed, area)
    assert needed.width() <= area.width(), (needed, area)
    assert label.mapTo(page, QPoint(0, 0)).x() + label.width() <= page.width()
    buttons = toast.findChildren(QPushButton)
    assert len(buttons) == 3
    for button in buttons:
        assert button.width() >= button.sizeHint().width(), button.text()
        right = button.mapTo(page, QPoint(0, 0)).x() + button.width()
        assert right <= page.width(), button.text()
    # The action below it stays usable.
    assert page.action_btn.height() >= page.action_btn.sizeHint().height()
    assert toast.width() <= page.width()


@pytest.mark.parametrize("dark", [True, False], ids=["dark", "light"])
@pytest.mark.parametrize("width", [TOOL_PANEL_MIN_WIDTH, 380, 450, 600])
@pytest.mark.parametrize("lang", LANGUAGES)
def test_toast_with_the_warning_is_whole(lang, width, dark, toast_page):
    from app.i18n import t
    from app.styles import STYLE, STYLE_LIGHT

    page, path, app = toast_page(lang, width, STYLE if dark else STYLE_LIGHT)
    message = (t("tool.compress.done", before="1234", after="567", pct="54")
               + "\n" + t("tool.compress.fonts_skipped"))
    page._show_toast(message, path, with_save=True)
    _assert_toast_is_whole(page, app, message, width)


@pytest.mark.parametrize("width", [TOOL_PANEL_MIN_WIDTH, 600])
@pytest.mark.parametrize("lang", LANGUAGES)
def test_toast_with_a_long_path_is_whole(lang, width, toast_page):
    """Rotate puts the path in its message: one word for Qt, 500 px wide."""
    from app.i18n import t
    from app.styles import STYLE

    page, path, app = toast_page(lang, width, STYLE)
    message = t("tool.rotate.done", path=_LONG_PATH)
    page._show_toast(message, path, with_save=True)
    _assert_toast_is_whole(page, app, message, width)


def test_the_window_gives_the_panel_the_width_the_toast_is_laid_out_for(
        monkeypatch, tmp_path):
    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtWidgets import QApplication

    from app.tools.compress import TabComprimir
    from app.update_controller import UpdateController
    from app.window import NAV_ITEMS, MainWindow

    class NoServer(QObject):
        new_paths = Signal(list)

    _unused_app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.i18n._CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(UpdateController, "check_async", lambda self: None)
    # A real one would listen on the user's own pipe while the suite runs.
    monkeypatch.setattr("app.window.SingleInstanceServer", NoServer)
    win = MainWindow()
    try:
        index = next(i for i, entry in enumerate(NAV_ITEMS)
                     if entry[2] is TabComprimir)
        item = next(win.nav.item(row) for row in range(win.nav.count())
                    if win.nav.item(row).data(Qt.ItemDataRole.UserRole) == index)
        win._on_nav_clicked(item)
        assert win.stack.minimumWidth() == TOOL_PANEL_MIN_WIDTH
    finally:
        win.close()
        win.deleteLater()


@pytest.mark.parametrize("panel, same_row", [(10000, True), (1, False)])
def test_toast_decides_its_rows_from_the_shared_width(
        panel, same_row, toast_page, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    from app.styles import STYLE

    monkeypatch.setattr("app.base.TOOL_PANEL_MIN_WIDTH", panel)
    page, path, app = toast_page("en", 600, STYLE)
    page._show_toast("Done", path)
    _settle(app)
    file_btn, folder_btn = page._toast_widget.findChildren(QPushButton)
    assert (file_btn.y() == folder_btn.y()) is same_row


def test_toast_without_a_message_to_wrap_stays_compact(toast_page):
    """A short message takes one line: the column adds only the buttons."""
    from PySide6.QtWidgets import QLabel

    from app.styles import STYLE

    page, path, app = toast_page("en", 600, STYLE)
    page._show_toast("Done", path, with_save=True)
    _settle(app)
    label = page._toast_widget.findChild(QLabel)
    assert label.height() == label.heightForWidth(label.width())
    assert label.height() < 2 * label.fontMetrics().height()


def test_breakable_only_touches_what_cannot_wrap():
    from app.base import _breakable

    text = "1234 KB  →  567 KB\nThe fonts in this PDF were not optimized."
    assert _breakable(text) == text
    long_path = _breakable(_LONG_PATH)
    assert long_path.replace("\u200b", "") == _LONG_PATH
    assert max(map(len, long_path.split("\u200b"))) <= 25


# ── The check the build workflow runs ────────────────────────────────────

_SMOKE = ROOT / "scripts" / "smoke_font_subset_child.py"


def _smoke(*args) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-I", str(_SMOKE), *args],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=120, check=False)


def test_smoke_script_passes_on_the_real_entry():
    result = _smoke(PY, str(ROOT / "pdfapps.py"))
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("body", [
    "sys.exit(0)\n",  # rc 0, no output
    "sys.exit(9)\n",
    # A copy: well formed, but the fonts did not shrink.
    """
import json, pymupdf
job = json.loads(sys.stdin.buffer.read())
d = pymupdf.open(job["src"]); d.authenticate(job["password"])
d.save(job["dst"])
""",
])
def test_smoke_script_rejects_a_child_that_did_no_real_work(tmp_path, body):
    fake = _script(tmp_path, "fake.py", body)
    result = _smoke(PY, "-I", fake)
    assert result.returncode == 1, result.stdout


_SMOKE_REAL_WORK = """
import json
from app._font_subset import subset
job = json.loads(sys.stdin.buffer.read())
subset(job["src"], job["dst"], job["password"])
sys.exit({rc})
"""


def test_smoke_script_rejects_a_good_output_with_a_bad_exit_code(tmp_path):
    """The output is all a later step sees, so only the rc can tell these two
    apart: this one also died after saving, say in a teardown."""
    control = _smoke(PY, "-I", _script(tmp_path, "rc0.py",
                                       _SMOKE_REAL_WORK.format(rc=0)))
    assert control.returncode == 0, control.stdout
    result = _smoke(PY, "-I", _script(tmp_path, "rc9.py",
                                      _SMOKE_REAL_WORK.format(rc=9)))
    assert result.returncode == 1, result.stdout
    assert b"exited with 9" in result.stdout


def test_every_build_runs_the_smoke_test_on_what_it_ships():
    from _workflow_steps import load_workflow

    steps = load_workflow("build.yml")["jobs"]["build"]["steps"]
    smoke = {}
    for index, step in enumerate(steps):
        run = step.get("run", "")
        if "smoke_font_subset_child.py" in run:
            smoke[step["if"].split("'")[1]] = (index, run)
    assert set(smoke) == {"Windows", "Linux", "macOS"}
    for os_name, (index, run) in smoke.items():
        built = [i for i, s in enumerate(steps)
                 if s.get("name") == f"Build ({os_name})"]
        assert built and built[0] < index
    assert "dist/dmg/PDFApps.app/Contents/MacOS/PDFApps" in smoke["macOS"][1]
    # Before the MSIX is built from the binary this step has just run.
    msix = next(i for i, s in enumerate(steps)
                if s.get("name") == "Build MSIX (Windows)")
    assert smoke["Windows"][0] < msix
