"""Regression tests for ``app._gs_paths`` and its use in ``_compress_pdf``.

The bug (snap stable rev 43, 1.15.0): the snap stages the Ubuntu 22.04
``ghostscript`` debs, built with ``--disable-compile-inits``. ``_find_gs``
returns ``$SNAP/usr/bin/gs``, whose compiled-in search path is
``/usr/share/ghostscript/9.55.0/...``; inside the snap that resolves against
core22, which has no Ghostscript data, so gs exits with "Can't find
initialization file gs_init.ps". ``_compress_pdf`` discards a non-zero exit
without a message, so Compress lost its Ghostscript pass silently.

The fix passes ``GS_LIB=<prefix>/share/ghostscript/<version>/Resource/Init``
plus ``.../lib`` to the gs child, where ``<prefix>`` comes from the binary
path and ``<version>`` from ``gs --version``. It is applied only when that
``Resource/Init`` directory exists. These tests check that the version
directory is the binary's and not the newest one on disk (``gs_init.ps``
aborts on a version mismatch), that ``os.environ`` is not written, and that
a ``GS_LIB`` the user already set stays ahead of the derived entries. A
failed probe is cached for the session and logged once. On Windows both
the probe and the gs child get ``CREATE_NO_WINDOW``, so the windowed build
opens no console window.

The unit tests fake ``subprocess.run`` and, where they use literal paths,
``os.path.isdir``. The ``tmp_path`` tests build the layout on disk and fake
only ``subprocess.run``. The ``_compress_pdf`` tests fake ``_find_gs``,
``subprocess.Popen`` and ``subprocess.run``, and do not import
``app._gs_paths``, so on a tree without it they fail on the assertion. The
console-window tests also set ``sys.platform``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── helpers ──────────────────────────────────────────────────────────────

class _Runs:
    """Fake ``subprocess.run`` for ``gs --version``; records every call."""

    def __init__(self, stdout=b"9.55.0\n", returncode=0, exc=None):
        self.stdout = stdout
        self.returncode = returncode
        self.exc = exc
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        assert kwargs.get("shell") in (None, False)
        if self.exc is not None:
            raise self.exc
        return subprocess.CompletedProcess(args, self.returncode,
                                           stdout=self.stdout, stderr=b"")


@pytest.fixture
def gp(monkeypatch):
    import app._gs_paths as mod
    monkeypatch.setattr(mod, "_GS_LIB_CACHE", {})
    return mod


def _fake_isdir(existing):
    existing = {os.path.normpath(p) for p in existing}
    return lambda p: os.path.normpath(p) in existing


def _gs_dirs(prefix, version):
    base = os.path.join(prefix, "share", "ghostscript", version)
    return (os.path.join(base, "Resource", "Init"), os.path.join(base, "lib"))


def _make_gs_tree(root: Path, versions=("9.55.0",), with_lib=True) -> str:
    """``<root>/usr/bin/gs`` plus one data directory per version."""
    usr = root / "usr"
    (usr / "bin").mkdir(parents=True)
    gs = usr / "bin" / "gs"
    gs.write_bytes(b"")
    for v in versions:
        init, lib = _gs_dirs(str(usr), v)
        os.makedirs(init)
        if with_lib:
            os.makedirs(lib)
    return str(gs)


# ── derivation ───────────────────────────────────────────────────────────

SNAP_GS = "/snap/x/1/usr/bin/gs"


def test_snap_layout_gets_init_and_lib(gp, monkeypatch):
    init, lib = _gs_dirs("/snap/x/1/usr", "9.55.0")
    share = os.path.join("/snap/x/1/usr", "share", "ghostscript")
    monkeypatch.setattr(os.path, "isdir", _fake_isdir({share, init, lib}))
    runs = _Runs(b"9.55.0\n")
    monkeypatch.setattr(subprocess, "run", runs)
    assert gp._gs_lib_dirs(SNAP_GS) == (init, lib)
    env = gp._gs_subprocess_env(SNAP_GS, environ={"PATH": "/x"})
    assert env == {"PATH": "/x", "GS_LIB": init + os.pathsep + lib}
    assert runs.calls == [[SNAP_GS, "--version"]]


def test_snap_layout_on_disk(gp, monkeypatch, tmp_path):
    gs = _make_gs_tree(tmp_path / "snap" / "pdfapps" / "43")
    monkeypatch.setattr(subprocess, "run", _Runs(b"9.55.0\n"))
    prefix = os.path.dirname(os.path.dirname(gs))
    init, lib = _gs_dirs(prefix, "9.55.0")
    env = gp._gs_subprocess_env(gs, environ={})
    assert env == {"GS_LIB": init + os.pathsep + lib}


def test_init_without_lib_gets_init_only(gp, monkeypatch, tmp_path):
    gs = _make_gs_tree(tmp_path, with_lib=False)
    monkeypatch.setattr(subprocess, "run", _Runs(b"9.55.0\n"))
    init, _ = _gs_dirs(os.path.dirname(os.path.dirname(gs)), "9.55.0")
    assert gp._gs_lib_dirs(gs) == (init,)


def test_version_without_matching_directory_changes_nothing(
        gp, monkeypatch, tmp_path):
    gs = _make_gs_tree(tmp_path, versions=("10.02.1",))
    monkeypatch.setattr(subprocess, "run", _Runs(b"9.55.0\n"))
    assert gp._gs_lib_dirs(gs) is None
    assert gp._gs_subprocess_env(gs, environ={"A": "1"}) is None


def test_binary_version_wins_over_newest_directory(gp, monkeypatch, tmp_path):
    # gs_init.ps aborts unless its version matches the binary, so the
    # directory must be the binary's own, not the newest on disk. The
    # binary's version is neither the newest by string order (9.55.0)
    # nor the newest by number (10.06.0).
    gs = _make_gs_tree(tmp_path, versions=("9.55.0", "10.02.1", "10.06.0"))
    monkeypatch.setattr(subprocess, "run", _Runs(b"10.02.1\n"))
    init, lib = _gs_dirs(os.path.dirname(os.path.dirname(gs)), "10.02.1")
    assert gp._gs_lib_dirs(gs) == (init, lib)


def test_version_directory_that_is_a_file_is_ignored(gp, monkeypatch, tmp_path):
    gs = _make_gs_tree(tmp_path, versions=())
    base = os.path.join(os.path.dirname(os.path.dirname(gs)),
                        "share", "ghostscript")
    os.makedirs(os.path.join(base, "9.55.0", "Resource"))
    Path(base, "9.55.0", "Resource", "Init").write_bytes(b"")
    monkeypatch.setattr(subprocess, "run", _Runs(b"9.55.0\n"))
    assert gp._gs_lib_dirs(gs) is None


def test_windows_install_without_share_spawns_nothing(gp, monkeypatch):
    # The Windows installer keeps its init files in %rom% and ships no
    # share directory (measured on gs10.05.0).
    gs = r"C:\Program Files\gs\gs10.05.0\bin\gswin64c.exe"
    monkeypatch.setattr(os.path, "isdir", _fake_isdir(set()))
    runs = _Runs(b"10.05.0\n")
    monkeypatch.setattr(subprocess, "run", runs)
    assert gp._gs_subprocess_env(gs, environ={"GS_LIB": "u"}) is None
    assert runs.calls == []


def test_usr_bin_gs_gets_its_compiled_in_directories(gp, monkeypatch):
    # For /usr/bin/gs the derived entries are the head of the compiled-in
    # default search path: redundant, same files.
    init, lib = _gs_dirs("/usr", "10.06.0")
    share = os.path.join("/usr", "share", "ghostscript")
    monkeypatch.setattr(os.path, "isdir", _fake_isdir({share, init, lib}))
    monkeypatch.setattr(subprocess, "run", _Runs(b"10.06.0\n"))
    assert gp._gs_lib_dirs("/usr/bin/gs") == (init, lib)


# kwargs, not _Runs instances: an instance built here at import time
# would carry its recorded calls from one run of the test into the next
# (pytest --keep-duplicates, or the same file collected twice).
@pytest.mark.parametrize("kw", [
    {"returncode": 1},
    {"exc": subprocess.TimeoutExpired(["gs"], 5)},
    {"exc": FileNotFoundError(2, "gone")},
    {"exc": PermissionError(13, "denied")},
    {"stdout": b""},
    {"stdout": b"GPL Ghostscript 9.55.0\n"},
    {"stdout": b"../../../etc\n"},
    {"stdout": b"9.55.0/../../x\n"},
    {"stdout": b"9.55.0\xff\n"},
], ids=["rc1", "timeout", "enoent", "eacces", "empty", "prose",
        "traversal", "suffix-traversal", "non-ascii"])
def test_failed_or_unusable_version_probe_changes_nothing(
        gp, monkeypatch, tmp_path, caplog, kw):
    caplog.set_level(logging.WARNING, logger=gp.__name__)
    gs = _make_gs_tree(tmp_path, versions=("9.55.0",))
    runs = _Runs(**kw)
    monkeypatch.setattr(subprocess, "run", runs)
    assert gp._gs_lib_dirs(gs) is None
    assert gp._gs_subprocess_env(gs, environ={}) is None
    assert len(runs.calls) == 1
    # The failure is cached for the session, so it must leave a trace.
    logged = [r for r in caplog.records if r.name == gp.__name__]
    assert len(logged) == 1
    assert logged[0].levelno == logging.WARNING
    assert gs in logged[0].getMessage()


def test_successful_probe_logs_nothing(gp, monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger=gp.__name__)
    gs = _make_gs_tree(tmp_path)
    monkeypatch.setattr(subprocess, "run", _Runs(b"9.55.0\n"))
    assert gp._gs_lib_dirs(gs) is not None
    assert [r for r in caplog.records if r.name == gp.__name__] == []


@pytest.mark.parametrize("version", [b"../evil\n", b"9.55.0/../../evil\n"],
                         ids=["dotdot", "version-then-dotdot"])
def test_version_with_path_components_is_rejected_even_if_it_resolves(
        gp, monkeypatch, tmp_path, version):
    # The version is joined into a path: it must not reach a directory
    # outside share/ghostscript even when that directory exists. The
    # second case starts with a valid version, so a prefix match (re.match
    # instead of re.fullmatch) would let it through.
    gs = _make_gs_tree(tmp_path, versions=("9.55.0",))
    usr = os.path.dirname(os.path.dirname(gs))
    os.makedirs(os.path.join(usr, "share", "evil", "Resource", "Init"))
    joined = os.path.join(usr, "share", "ghostscript",
                          version.decode().strip(), "Resource", "Init")
    assert os.path.isdir(joined)  # the path really resolves
    monkeypatch.setattr(subprocess, "run", _Runs(version))
    assert gp._gs_lib_dirs(gs) is None


def _probe_kwargs(gp, monkeypatch, tmp_path):
    gs = _make_gs_tree(tmp_path)
    seen = {}

    def fake(args, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout=b"9.55.0\n")

    monkeypatch.setattr(subprocess, "run", fake)
    assert gp._gs_lib_dirs(gs) is not None
    return seen


def test_version_probe_has_a_timeout_and_no_shell(gp, monkeypatch, tmp_path):
    seen = _probe_kwargs(gp, monkeypatch, tmp_path)
    assert 0 < seen["timeout"] <= 10
    assert not seen.get("shell")
    # With stdout=DEVNULL res.stdout is None, every probe fails and the
    # snap's gs is back to exiting 1. The fakes return stdout whatever
    # the kwargs say, so only this assertion catches it.
    assert seen["stdout"] == subprocess.PIPE
    assert seen["stdin"] == subprocess.DEVNULL


# The real value, hard-coded so the Linux run can stand it in for the
# attribute that only exists on Windows.
_CREATE_NO_WINDOW = 0x08000000


def _pretend_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    if not hasattr(subprocess, "CREATE_NO_WINDOW"):  # not on Windows
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW",
                            _CREATE_NO_WINDOW, raising=False)
    assert subprocess.CREATE_NO_WINDOW == _CREATE_NO_WINDOW


def test_version_probe_opens_no_console_on_windows(gp, monkeypatch, tmp_path):
    _pretend_windows(monkeypatch)
    seen = _probe_kwargs(gp, monkeypatch, tmp_path)
    assert seen["creationflags"] & _CREATE_NO_WINDOW


def test_version_probe_passes_no_window_flag_on_linux(
        gp, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    seen = _probe_kwargs(gp, monkeypatch, tmp_path)
    # POSIX Popen raises ValueError for any non-zero creationflags.
    assert seen.get("creationflags", 0) == 0


def test_none_binary(gp):
    assert gp._gs_lib_dirs(None) is None
    assert gp._gs_subprocess_env(None, environ={}) is None


# ── environment ──────────────────────────────────────────────────────────

def test_user_gs_lib_keeps_precedence(gp, monkeypatch, tmp_path):
    gs = _make_gs_tree(tmp_path)
    monkeypatch.setattr(subprocess, "run", _Runs(b"9.55.0\n"))
    init, lib = _gs_dirs(os.path.dirname(os.path.dirname(gs)), "9.55.0")
    user = os.pathsep.join(["/home/u/gsfonts", "/home/u/more"])
    env = gp._gs_subprocess_env(gs, environ={"GS_LIB": user, "K": "v"})
    assert env == {"GS_LIB": os.pathsep.join([user, init, lib]), "K": "v"}


def test_empty_user_gs_lib_adds_no_empty_entry(gp, monkeypatch, tmp_path):
    gs = _make_gs_tree(tmp_path)
    monkeypatch.setattr(subprocess, "run", _Runs(b"9.55.0\n"))
    init, lib = _gs_dirs(os.path.dirname(os.path.dirname(gs)), "9.55.0")
    env = gp._gs_subprocess_env(gs, environ={"GS_LIB": ""})
    assert env == {"GS_LIB": init + os.pathsep + lib}


def test_process_environment_is_copied_not_modified(gp, monkeypatch, tmp_path):
    gs = _make_gs_tree(tmp_path)
    monkeypatch.setattr(subprocess, "run", _Runs(b"9.55.0\n"))
    monkeypatch.setenv("GS_LIB", "/home/u/gsfonts")
    monkeypatch.setenv("PDFAPPS_GS_TEST", "kept")
    before = dict(os.environ)
    env = gp._gs_subprocess_env(gs)
    assert dict(os.environ) == before
    assert env is not os.environ
    assert env["PDFAPPS_GS_TEST"] == "kept"
    init, lib = _gs_dirs(os.path.dirname(os.path.dirname(gs)), "9.55.0")
    assert env["GS_LIB"] == os.pathsep.join(["/home/u/gsfonts", init, lib])


def test_caller_mapping_is_not_modified(gp, monkeypatch, tmp_path):
    gs = _make_gs_tree(tmp_path)
    monkeypatch.setattr(subprocess, "run", _Runs(b"9.55.0\n"))
    src = {"GS_LIB": "/u"}
    gp._gs_subprocess_env(gs, environ=src)
    assert src == {"GS_LIB": "/u"}


# ── cache ────────────────────────────────────────────────────────────────

def test_probe_runs_once_per_binary(gp, monkeypatch, tmp_path):
    gs1 = _make_gs_tree(tmp_path / "a")
    gs2 = _make_gs_tree(tmp_path / "b", versions=("10.06.0",))
    runs = _Runs(b"9.55.0\n")
    monkeypatch.setattr(subprocess, "run", runs)
    first = gp._gs_lib_dirs(gs1)
    assert first is not None
    assert gp._gs_lib_dirs(gs1) == first
    gp._gs_subprocess_env(gs1, environ={})
    assert runs.calls == [[gs1, "--version"]]
    # A different binary is probed on its own (and 9.55.0 has no
    # directory under it).
    assert gp._gs_lib_dirs(gs2) is None
    assert runs.calls == [[gs1, "--version"], [gs2, "--version"]]


def test_failed_probe_is_cached_too(gp, monkeypatch, tmp_path, caplog):
    # Cached on purpose: a gs that hangs on --version would otherwise cost
    # the whole timeout on every compress run. Logged once, not per call.
    caplog.set_level(logging.WARNING, logger=gp.__name__)
    gs = _make_gs_tree(tmp_path)
    runs = _Runs(exc=subprocess.TimeoutExpired(["gs"], 5))
    monkeypatch.setattr(subprocess, "run", runs)
    assert gp._gs_lib_dirs(gs) is None
    assert gp._gs_lib_dirs(gs) is None
    assert gp._gs_subprocess_env(gs, environ={}) is None
    assert len(runs.calls) == 1
    assert len([r for r in caplog.records if r.name == gp.__name__]) == 1


def test_user_gs_lib_is_read_per_call_not_cached(gp, monkeypatch, tmp_path):
    gs = _make_gs_tree(tmp_path)
    monkeypatch.setattr(subprocess, "run", _Runs(b"9.55.0\n"))
    init, lib = _gs_dirs(os.path.dirname(os.path.dirname(gs)), "9.55.0")
    assert gp._gs_subprocess_env(gs, environ={})["GS_LIB"] == (
        init + os.pathsep + lib)
    assert gp._gs_subprocess_env(gs, environ={"GS_LIB": "/u"})["GS_LIB"] == (
        os.pathsep.join(["/u", init, lib]))


# ── _compress_pdf wiring (no import of app._gs_paths) ────────────────────

class _FakeProc:
    returncode = 1

    def poll(self):
        return 1

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 1

    def kill(self):
        pass


def _run_compress(monkeypatch, tmp_path, gs, version=b"9.55.0\n"):
    import pymupdf

    from app import utils

    src = tmp_path / "in put é.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "hello")
    doc.save(str(src))
    doc.close()

    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((list(cmd), kwargs))
        return _FakeProc()

    monkeypatch.setattr(utils, "_find_gs", lambda: gs)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", _Runs(version))
    try:
        utils._compress_pdf(str(src), str(tmp_path / "out.pdf"),
                            level="extreme")
    except (ValueError, RuntimeError):
        pass  # no size gain on a one-line PDF; only the gs call matters
    assert len(popen_calls) == 1
    assert popen_calls[0][0][0] == gs
    return popen_calls[0][1]


def test_compress_passes_gs_lib_to_snap_gs(monkeypatch, tmp_path):
    gs = _make_gs_tree(tmp_path / "snap" / "pdfapps" / "43")
    monkeypatch.setenv("GS_LIB", "/home/u/gsfonts")
    kwargs = _run_compress(monkeypatch, tmp_path, gs)
    init, lib = _gs_dirs(os.path.dirname(os.path.dirname(gs)), "9.55.0")
    env = kwargs.get("env")
    assert env is not None, "gs was spawned without the derived GS_LIB"
    assert env["GS_LIB"] == os.pathsep.join(["/home/u/gsfonts", init, lib])
    # (Importing app.utils sets QT_API, so compare GS_LIB, not the whole
    # environment.)
    assert os.environ["GS_LIB"] == "/home/u/gsfonts"


def test_compress_inherits_environment_without_init_dirs(monkeypatch, tmp_path):
    gs = _make_gs_tree(tmp_path / "other", versions=("10.02.1",))
    kwargs = _run_compress(monkeypatch, tmp_path, gs)
    assert kwargs.get("env") is None


def test_compress_spawns_gs_without_a_console_on_windows(monkeypatch, tmp_path):
    # Import app.utils before faking sys.platform. Run alone, the first
    # import would otherwise happen in _run_compress, so app.i18n would
    # keep config paths for the fake platform for the whole session, and
    # on Linux without pytest-qt the first PySide6 import fails as win32.
    from app import utils  # noqa: F401
    # Layout of the Windows installer: no share directory, so no probe.
    gs = _make_gs_tree(tmp_path / "gs10.05.0", versions=())
    _pretend_windows(monkeypatch)
    kwargs = _run_compress(monkeypatch, tmp_path, gs)
    assert kwargs.get("creationflags", 0) & _CREATE_NO_WINDOW
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs.get("env") is None


def test_compress_passes_no_window_flag_on_linux(monkeypatch, tmp_path):
    from app import utils  # noqa: F401  (before sys.platform; see above)
    gs = _make_gs_tree(tmp_path / "usr-bin", versions=())
    monkeypatch.setattr(sys, "platform", "linux")
    kwargs = _run_compress(monkeypatch, tmp_path, gs)
    assert kwargs.get("creationflags", 0) == 0
