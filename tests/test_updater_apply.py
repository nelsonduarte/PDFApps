"""The Linux self-update, end to end, against a fictitious installed binary.

The bug (v1.12.2 to v1.15.2): the download's temp name ended in ``.gz``, the
check for ``.tar.gz`` was false, and the tarball was copied over the
executable. The result was a gzip file with mode 0700, ``execv`` failed with
``Exec format error``, and the backup had already been deleted.

Nothing here touches a real binary: ``sys.executable`` points into tmp_path,
the temp dir is redirected there too, ``os.execve`` only records its call and
the ``--version`` probe is replaced, except in the tests of the probe itself,
which run small shell scripts.
"""
from __future__ import annotations

import contextlib
import errno
import gzip
import hashlib
import io
import json
import os
import random
import re
import select
import signal
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import update_apply, updater
from app._font_subset import WORKER_FLAG
from app.i18n import t
from app.update_apply import BACKUP_ENV, RestoreFailed, UpdateError

ROOT = Path(__file__).resolve().parent.parent
NEW_NAME = "PDFApps-Linux-x86_64.tar.gz"
OLD_NAME = "PDFApps-Linux.tar.gz"
OLD_BINARY = b"\x7fELF old binary " + b"\x01" * 512
NEW_BINARY = b"\x7fELF new binary " + b"\x02" * 2048
MACHO_BINARY = b"\xcf\xfa\xed\xfe new binary"
GZIP_MAGIC = b"\x1f\x8b"
TAG = "v9.9.9"

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX modes and processes")


def _tarball(*members) -> bytes:
    """Bytes of a tarball. A member is (name, data) or (name, type, target)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for member in members:
            info = tarfile.TarInfo(member[0])
            if len(member) == 2:
                info.size = len(member[1])
                info.mode = 0o700
                tar.addfile(info, io.BytesIO(member[1]))
            else:
                info.type = member[1]
                info.linkname = member[2]
                tar.addfile(info)
    return buf.getvalue()


GOOD_TARBALL = _tarball(("PDFApps", NEW_BINARY))


class _Box:
    """A fictitious install: the binary, a temp dir, the probe and execve."""

    def __init__(self, tmp_path: Path, exe_name: str = "PDFApps"):
        self.install = tmp_path / "install dir ç"
        self.install.mkdir()
        self.exe = self.install / exe_name
        self.exe.write_bytes(OLD_BINARY)
        self.exe.chmod(0o755)
        self.tmp = tmp_path / "tmp"
        self.tmp.mkdir()
        self.exec_calls: list[dict] = []
        self.exec_error: Exception | None = None
        self.probe_calls: list[dict] = []
        self.probe_error: Exception | None = None
        self.events: list[str] = []

    def fake_execve(self, path, argv, env):
        self.events.append("execve")
        with open(path, "rb") as f:
            image = f.read()
        self.exec_calls.append({
            "path": path, "argv": list(argv), "env": dict(env),
            "os_environ": dict(os.environ), "image": image,
            "backups": self.backups(),
        })
        if self.exec_error is not None:
            raise self.exec_error

    def fake_probe(self, staged, version, **_kw):
        self.events.append("probe")
        self.probe_calls.append({
            "staged": staged, "version": version,
            "image": Path(staged).read_bytes(),
            "installed": self.exe.read_bytes(),
            "backups": self.backups(),
            "on_main_thread": threading.current_thread() is threading.main_thread(),
        })
        if self.probe_error is not None:
            raise self.probe_error

    def download(self, payload: bytes, suffix: str = ".gz") -> str:
        # The name _start_download really produces, not one that helps.
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="PDFApps_update_",
                                    dir=self.tmp)
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        return path

    def backups(self) -> list[Path]:
        return sorted(self.tmp.glob("*.pdfapps-backup"))

    def assert_untouched(self):
        assert self.exe.read_bytes() == OLD_BINARY
        assert not self.exec_calls
        assert not self.backups()
        assert os.listdir(self.install) == [self.exe.name], "staged file left behind"


def _install_box(b: _Box, monkeypatch) -> _Box:
    monkeypatch.setattr(tempfile, "tempdir", str(b.tmp))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(b.exe))
    monkeypatch.setattr(sys, "argv", [str(b.exe), "file with space.pdf"])
    monkeypatch.setattr(os, "execve", b.fake_execve)
    monkeypatch.setattr(update_apply, "_probe_version", b.fake_probe)
    monkeypatch.delenv(BACKUP_ENV, raising=False)
    return b


@pytest.fixture
def box(tmp_path, monkeypatch):
    return _install_box(_Box(tmp_path), monkeypatch)


def _apply(path: str, asset_name: str = NEW_NAME, before_exec=None) -> None:
    """Both halves, the way the dialog chains them."""
    update = update_apply.install_new_binary(path, asset_name, TAG)
    update_apply.restart_into(update, before_exec)


# ── R1: the binary, not the archive, ends up installed ───────────────────


@pytest.mark.parametrize("suffix", [".gz", ".tmp", ".tar.gz"])
def test_installs_the_extracted_binary_whatever_the_temp_name(box, suffix):
    downloaded = box.download(GOOD_TARBALL, suffix)
    _apply(downloaded)

    final = box.exe.read_bytes()
    assert final == NEW_BINARY
    assert not final.startswith(GZIP_MAGIC)
    assert final.startswith(b"\x7fELF")
    assert len(box.exec_calls) == 1
    call = box.exec_calls[0]
    assert os.path.realpath(call["path"]) == os.path.realpath(box.exe)
    assert call["argv"] == [str(box.exe), "file with space.pdf"]
    assert call["image"] == NEW_BINARY
    assert os.listdir(box.install) == ["PDFApps"]


def test_the_staged_binary_is_renamed_from_the_binary_s_own_folder(box, monkeypatch):
    """Only a rename inside one directory is atomic; across filesystems
    os.replace is not even possible."""
    real_replace = os.replace
    renames = []

    def spy(src, dst):
        renames.append((os.path.dirname(os.path.realpath(src)),
                        os.path.dirname(os.path.realpath(dst))))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    _apply(box.download(GOOD_TARBALL))
    assert renames == [(os.path.realpath(box.install),) * 2]


def test_the_staged_binary_is_on_disk_before_the_rename(box, monkeypatch):
    real_fsync, real_replace = os.fsync, os.replace
    synced, order = [], []

    def fsync(fd):
        synced.append(os.fstat(fd).st_ino)
        order.append("fsync")
        real_fsync(fd)

    def replace(src, dst):
        order.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    _apply(box.download(GOOD_TARBALL))
    assert os.stat(box.exe).st_ino in synced
    assert order.index("fsync") < order.index("replace")


@posix_only
@pytest.mark.parametrize("before, after", [
    (0o755, 0o755), (0o750, 0o750), (0o700, 0o700), (0o644, 0o744),
])
def test_installed_binary_keeps_the_installed_mode(box, before, after):
    """Inherited, not forced to 0755: a binary kept private stays private,
    and the owner can always run it. The member's own mode is ignored."""
    box.exe.chmod(before)
    _apply(box.download(GOOD_TARBALL))
    assert stat.S_IMODE(box.exe.stat().st_mode) == after


@posix_only
def test_a_symlinked_executable_keeps_the_link_and_replaces_the_target(box, monkeypatch):
    link = box.tmp / "launcher"
    link.symlink_to(box.exe)
    monkeypatch.setattr(sys, "executable", str(link))
    _apply(box.download(GOOD_TARBALL))
    assert link.is_symlink()
    assert box.exe.read_bytes() == NEW_BINARY


@pytest.mark.parametrize("binary", [NEW_BINARY, MACHO_BINARY])
def test_macos_never_replaces_its_binary_this_way(box, monkeypatch, binary):
    """macOS updates through the dmg; this path only knows ELF."""
    monkeypatch.setattr(sys, "platform", "darwin")
    downloaded = box.download(_tarball(("PDFApps", binary)))
    with pytest.raises(UpdateError) as err:
        _apply(downloaded)
    assert str(err.value) == t("update.error.bad_archive")
    box.assert_untouched()
    assert not os.path.exists(downloaded)


# ── refused archives leave the installed binary alone ────────────────────


def _bad_tarballs():
    return {
        "no member": _tarball(),
        "other member": _tarball(("README", NEW_BINARY)),
        "parent traversal": _tarball(("../PDFApps", NEW_BINARY)),
        "nested traversal": _tarball(("x/../../PDFApps", NEW_BINARY)),
        "absolute path": _tarball(("/tmp/PDFApps", NEW_BINARY)),
        "dot slash name": _tarball(("./PDFApps", NEW_BINARY)),
        "symlink member": _tarball(("PDFApps", tarfile.SYMTYPE, "/etc/passwd")),
        "hardlink member": _tarball(("PDFApps", tarfile.LNKTYPE, "other")),
        "directory member": _tarball(("PDFApps", tarfile.DIRTYPE, "")),
        "extra member": _tarball(("PDFApps", NEW_BINARY), ("evil", NEW_BINARY)),
        "symlink next to it": _tarball(
            ("PDFApps", NEW_BINARY), ("link", tarfile.SYMTYPE, "/etc/passwd")),
        "traversal next to it": _tarball(
            ("PDFApps", NEW_BINARY), ("../evil", NEW_BINARY)),
        "duplicate member": _tarball(("PDFApps", NEW_BINARY), ("PDFApps", NEW_BINARY)),
        "member is an archive": _tarball(("PDFApps", gzip.compress(b"inner"))),
        "member is empty": _tarball(("PDFApps", b"")),
        "member is text": _tarball(("PDFApps", b"#!/bin/sh\nrm -rf ~\n")),
        "member is mach-o": _tarball(("PDFApps", MACHO_BINARY)),
        "plain gzip": gzip.compress(NEW_BINARY),
        "bare binary": NEW_BINARY,
        "empty file": b"",
        "truncated": GOOD_TARBALL[:len(GOOD_TARBALL) // 2],
        "damaged deflate stream": _damaged(_COMPRESSIBLE_TARBALL, len(_COMPRESSIBLE_TARBALL) // 2),
        "wrong gzip checksum": _damaged(GOOD_TARBALL, len(GOOD_TARBALL) - 8),
        "invalid deflate block after the archive": _invalid_block_after(
            gzip.decompress(GOOD_TARBALL) + b"\0" * 300_000),
    }


# Compressible, so the middle of the stream is Huffman codes and damage
# there is a zlib.error rather than a stored block of other bytes.
_COMPRESSIBLE_TARBALL = _tarball(("PDFApps", b"\x7fELF" + bytes(
    random.Random(1).choices(b"\x00\x01\x02\x03", k=300000))))


def _damaged(data: bytes, at: int) -> bytes:
    raw = bytearray(data)
    raw[at:at + 4] = bytes(b ^ 0xFF for b in raw[at:at + 4])
    return bytes(raw)


def _invalid_block_after(plain: bytes) -> bytes:
    """*plain* in stored deflate blocks, then a block of type 11, which
    deflate does not have. Built by hand so it fails the same way with any
    zlib. The 300 KB of padding put the bad block beyond what tarfile
    reads ahead: only reading the stream to its end meets it, and that
    raises a bare zlib.error instead of tarfile's ReadError."""
    out = bytearray(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff")
    for i in range(0, len(plain), 65535):
        chunk = plain[i:i + 65535]
        out += b"\x00" + struct.pack("<HH", len(chunk), len(chunk) ^ 0xFFFF) + chunk
    return bytes(out + b"\x07")


@pytest.mark.parametrize("case", sorted(_bad_tarballs()))
def test_a_bad_tarball_is_refused(box, case):
    downloaded = box.download(_bad_tarballs()[case])
    with pytest.raises(UpdateError) as err:
        _apply(downloaded)
    assert str(err.value) == t("update.error.bad_archive")
    box.assert_untouched()
    assert not box.probe_calls, "refused before anything ran"
    assert not os.path.exists(downloaded)


@pytest.mark.parametrize("name", ["PDFApps", "PDFApps.zip", "PDFApps.gz", "PDFApps-Linux.tgz"])
def test_any_other_asset_is_refused_rather_than_copied_over(box, name):
    """The payload is a tarball the updater would install: only the asset's
    name can be what refuses it."""
    with pytest.raises(UpdateError) as err:
        _apply(box.download(GOOD_TARBALL), name)
    assert str(err.value) == t("update.error.bad_archive")
    box.assert_untouched()


# ── the --version probe, wired in ────────────────────────────────────────


def test_the_probe_runs_the_staged_copy_before_anything_is_replaced(box):
    _apply(box.download(GOOD_TARBALL))
    (call,) = box.probe_calls
    assert call["version"] == TAG
    assert call["image"] == NEW_BINARY
    assert os.path.dirname(call["staged"]) == str(box.install)
    assert call["installed"] == OLD_BINARY, "ran after the swap"
    assert call["backups"] == [], "ran after the backup"
    assert box.events == ["probe", "execve"]


def test_a_failed_probe_changes_nothing(box):
    box.probe_error = update_apply._probe_failed("exit status 127: libfoo.so.1")
    downloaded = box.download(GOOD_TARBALL)
    with pytest.raises(UpdateError) as err:
        _apply(downloaded)
    assert str(err.value) == t("update.error.probe_failed",
                               error="exit status 127: libfoo.so.1")
    box.assert_untouched()
    assert not os.path.exists(downloaded)


# ── rollback ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("error", [
    OSError(8, "Exec format error"),
    PermissionError(13, "Permission denied"),
    ValueError("execv() arg 2 must not be empty"),
])
def test_failed_execv_restores_the_old_binary(box, error):
    box.exec_error = error
    downloaded = box.download(GOOD_TARBALL)
    with pytest.raises(UpdateError) as err:
        _apply(downloaded)
    assert not isinstance(err.value, RestoreFailed)
    assert len(box.exec_calls) == 1
    assert box.exec_calls[0]["image"] == NEW_BINARY
    assert box.exe.read_bytes() == OLD_BINARY
    assert str(err.value) == t("update.error.restart_failed", error=error)
    assert not box.backups(), "the restored backup has no further use"
    assert os.listdir(box.install) == ["PDFApps"]
    assert not os.path.exists(downloaded)


@posix_only
def test_restored_binary_keeps_its_mode(box):
    box.exe.chmod(0o750)
    box.exec_error = OSError(8, "Exec format error")
    with pytest.raises(UpdateError):
        _apply(box.download(GOOD_TARBALL))
    assert stat.S_IMODE(box.exe.stat().st_mode) == 0o750


def test_backup_exists_while_execv_runs_and_outlives_success(box):
    """Execv succeeding ends the process, so nothing here deletes the backup:
    the new process does (see the startup tests below)."""
    _apply(box.download(GOOD_TARBALL))
    (backup,) = box.exec_calls[0]["backups"]
    assert backup.read_bytes() == OLD_BINARY
    assert box.backups() == [backup]
    assert box.exec_calls[0]["env"][BACKUP_ENV] == str(backup)


def test_the_next_update_removes_the_previous_backup_only(box):
    other = box.tmp / "Other.abc.pdfapps-backup"
    other.write_bytes(b"not ours")
    _apply(box.download(GOOD_TARBALL))
    assert len(box.backups()) == 2

    second = b"\x7fELF third binary"
    _apply(box.download(_tarball(("PDFApps", second))))
    remaining = [p for p in box.backups() if p != other]
    assert len(remaining) == 1
    assert remaining[0].read_bytes() == NEW_BINARY, "backs up what was running"
    assert other.read_bytes() == b"not ours"
    assert box.exe.read_bytes() == second


def test_a_refused_update_keeps_the_previous_backup(box):
    _apply(box.download(GOOD_TARBALL))
    before = box.backups()
    with pytest.raises(UpdateError):
        _apply(box.download(b"junk"))
    assert box.backups() == before


def test_a_backup_that_cannot_be_made_does_not_cost_the_previous_one(box, monkeypatch):
    """Measured: with /tmp full the old backup went first, then the new one
    failed, and the only copy was gone."""
    _apply(box.download(GOOD_TARBALL))
    (previous,) = box.backups()
    with patch("shutil.copy2", side_effect=OSError(errno.ENOSPC, "No space left on device")):
        with pytest.raises(UpdateError):
            _apply(box.download(_tarball(("PDFApps", b"\x7fELF third"))))
    assert box.backups() == [previous]
    assert previous.read_bytes() == OLD_BINARY


def test_failed_restore_says_where_the_copy_is(box, monkeypatch):
    box.exec_error = OSError(8, "Exec format error")
    real_replace = os.replace
    calls = []

    def replace(src, dst):
        calls.append(src)
        if len(calls) == 2:
            raise PermissionError(13, "Permission denied")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(RestoreFailed) as err:
        _apply(box.download(GOOD_TARBALL))
    (backup,) = box.backups()
    assert backup.read_bytes() == OLD_BINARY
    assert str(backup) in str(err.value)
    assert err.value.backup == str(backup)
    assert os.listdir(box.install) == ["PDFApps"]


def _full_disk_on_restore(monkeypatch):
    """shutil.copy2 runs twice: the backup, then the restore. Fail the second."""
    import shutil
    real_copy2 = shutil.copy2
    calls = []

    def copy2(src, dst, *a, **k):
        calls.append(src)
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_copy2(src, dst, *a, **k)

    monkeypatch.setattr(shutil, "copy2", copy2)


def test_a_full_disk_during_the_restore_names_the_copy(box, monkeypatch):
    box.exec_error = OSError(8, "Exec format error")
    _full_disk_on_restore(monkeypatch)
    with pytest.raises(RestoreFailed) as err:
        _apply(box.download(GOOD_TARBALL))
    (backup,) = box.backups()
    assert backup.read_bytes() == OLD_BINARY
    assert str(err.value) == t(
        "update.error.restore_failed", path=str(backup),
        error=OSError(errno.ENOSPC, "No space left on device"))
    assert os.listdir(box.install) == ["PDFApps"], "restore temp file left"


def test_after_a_failed_restore_no_update_sweeps_that_copy(box, monkeypatch):
    """Measured: retrying deleted the copy the message pointed at, and the
    new backup was the version that had just failed to start."""
    box.exec_error = OSError(8, "Exec format error")
    _full_disk_on_restore(monkeypatch)
    with pytest.raises(RestoreFailed) as err:
        _apply(box.download(GOOD_TARBALL))
    monkeypatch.undo()
    _install_box(box, monkeypatch)
    box.exec_error = None

    _apply(box.download(_tarball(("PDFApps", b"\x7fELF third"))))
    assert Path(err.value.backup).read_bytes() == OLD_BINARY
    assert len(box.backups()) == 2


def test_a_marker_without_its_copy_does_not_stop_the_sweep(box):
    """A temp cleaner may take the copy and leave the marker."""
    _apply(box.download(GOOD_TARBALL))
    (first,) = box.backups()
    (box.tmp / "PDFApps.gone.pdfapps-backup.restore-failed").write_bytes(b"")
    _apply(box.download(_tarball(("PDFApps", b"\x7fELF third"))))
    assert first not in box.backups()
    assert len(box.backups()) == 1


def test_another_binary_s_failed_restore_does_not_stop_this_sweep(box):
    """Only this binary's marks count: one left by a copy installed under
    another name, in the same temp dir, used to keep every backup here."""
    other = box.tmp / "pdfapps-old.k2j3h4ab.pdfapps-backup"
    other.write_bytes(b"the other copy")
    (box.tmp / (other.name + ".restore-failed")).write_bytes(b"")
    stale = box.tmp / "PDFApps.a1b2c3d4.pdfapps-backup"
    stale.write_bytes(OLD_BINARY)
    _apply(box.download(GOOD_TARBALL))
    assert not stale.exists()
    assert other.read_bytes() == b"the other copy"


@posix_only
def test_the_failed_restore_mark_never_goes_through_a_planted_link(box, tmp_path):
    """The temp dir may be shared: a dangling link named like the mark must
    not make it create a file wherever the link points."""
    backup = box.tmp / "PDFApps.a1b2c3d4.pdfapps-backup"
    backup.write_bytes(OLD_BINARY)
    target = tmp_path / "planted target"
    os.symlink(target, str(backup) + ".restore-failed")
    update_apply._mark_restore_failed(str(backup))
    assert not os.path.lexists(target)
    assert backup.read_bytes() == OLD_BINARY


def _writer_came(read_end: int) -> bool:
    """Whether a writer opened the FIFO since *read_end* was opened.

    Linux reports POLLHUP on a FIFO's read end only once a writer has come
    and gone, never for one no writer ever opened.
    """
    poller = select.poll()
    poller.register(read_end, select.POLLIN)
    return any(ev & select.POLLHUP for _fd, ev in poller.poll(0))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux FIFO semantics")
@pytest.mark.parametrize("reader", [False, True], ids=["nobody-reads", "someone-reads"])
def test_a_fifo_planted_as_the_mark_neither_freezes_nor_is_opened(box, reader):
    """The mark is made on the GUI thread. Opened for writing, a FIFO with
    no reader waits for one, and the app froze for as long as nobody came
    (measured without O_EXCL); with a reader there, the mark would go to
    whoever holds that pipe."""
    backup = box.tmp / "PDFApps.a1b2c3d4.pdfapps-backup"
    backup.write_bytes(OLD_BINARY)
    mark = str(backup) + ".restore-failed"
    os.mkfifo(mark, 0o600)
    read_end = os.open(mark, os.O_RDONLY | os.O_NONBLOCK) if reader else None
    returned = threading.Event()

    def mark_it():
        update_apply._mark_restore_failed(str(backup))
        returned.set()

    worker = threading.Thread(target=mark_it, daemon=True)
    worker.start()
    try:
        assert returned.wait(2.0), "blocked on the FIFO"
        if read_end is not None:
            assert not _writer_came(read_end), "opened the FIFO"
    finally:
        if not returned.is_set():
            # A reader lets the blocked open through, so the thread ends.
            release = os.open(mark, os.O_RDONLY | os.O_NONBLOCK)
            worker.join(5.0)
            os.close(release)
        if read_end is not None:
            os.close(read_end)
    assert stat.S_ISFIFO(os.lstat(mark).st_mode)
    assert backup.read_bytes() == OLD_BINARY


@pytest.mark.parametrize("failing", ["os.replace", "shutil.copy2"])
def test_failure_before_the_swap_changes_nothing(box, failing):
    with patch(failing, side_effect=PermissionError(13, "Permission denied")):
        with pytest.raises(UpdateError) as err:
            _apply(box.download(GOOD_TARBALL))
    assert t("update.error.apply_failed", error="X").split("(")[0] in str(err.value)
    box.assert_untouched()


def test_the_name_of_the_binary_is_not_a_glob(tmp_path, monkeypatch):
    """``PDFApps[1]`` as a pattern matches ``PDFApps1``, not itself."""
    b = _install_box(_Box(tmp_path, exe_name="PDFApps[1]"), monkeypatch)
    stale = b.tmp / "PDFApps[1].old.pdfapps-backup"
    stale.write_bytes(b"stale")
    lookalike = b.tmp / "PDFApps1.old.pdfapps-backup"
    lookalike.write_bytes(b"someone else's")
    _apply(b.download(GOOD_TARBALL))
    assert not stale.exists()
    assert lookalike.read_bytes() == b"someone else's"


@posix_only
def test_the_sweep_skips_links_and_other_users_files(box, monkeypatch):
    target = box.tmp / "precious"
    target.write_bytes(b"precious")
    link = box.tmp / "PDFApps.link.pdfapps-backup"
    link.symlink_to(target)
    foreign = box.tmp / "PDFApps.foreign.pdfapps-backup"
    foreign.write_bytes(b"foreign")
    real_lstat = os.lstat

    def lstat(path, *a, **k):
        st = real_lstat(path, *a, **k)
        if os.fspath(path) == str(foreign):
            fields = list(st)
            fields[stat.ST_UID] = os.getuid() + 1
            return os.stat_result(fields)
        return st

    monkeypatch.setattr(os, "lstat", lstat)
    _apply(box.download(GOOD_TARBALL))
    assert link.is_symlink() and target.read_bytes() == b"precious"
    assert foreign.exists()


# ── before_exec ──────────────────────────────────────────────────────────


def test_before_exec_runs_right_before_execve(box):
    _apply(box.download(GOOD_TARBALL),
           before_exec=lambda: box.events.append("before_exec"))
    assert box.events == ["probe", "before_exec", "execve"]


def test_a_failing_before_exec_restores_the_old_binary(box):
    def boom():
        raise RuntimeError("drain failed")

    with pytest.raises(UpdateError) as err:
        _apply(box.download(GOOD_TARBALL), before_exec=boom)
    assert str(err.value) == t("update.error.restart_failed",
                               error=RuntimeError("drain failed"))
    assert box.exe.read_bytes() == OLD_BINARY
    assert not box.exec_calls


def test_a_blocked_restart_puts_the_old_binary_back_and_says_why(box):
    """"Could not be started" would be false: the window refused, and
    its message is the one that tells the user what to do."""
    def blocked():
        raise update_apply.UpdateBlocked("save your work first")

    update = update_apply.install_new_binary(box.download(GOOD_TARBALL), NEW_NAME, TAG)
    with pytest.raises(update_apply.UpdateBlocked) as err:
        update_apply.restart_into(update, blocked)
    assert str(err.value) == "save your work first"
    assert box.exe.read_bytes() == OLD_BINARY
    assert not box.exec_calls
    assert not box.backups()


# ── A6: another instance running the same binary ────────────────────────


def _fake_proc(tmp_path: Path, procs: dict) -> Path:
    """A /proc with ``{pid: (ppid, exe or None[, argv])}``; the comm has ") " in it.

    argv defaults to the exe alone; a kernel thread has an empty cmdline.
    """
    root = tmp_path / "proc"
    for pid, (ppid, exe, *argv) in procs.items():
        entry = root / str(pid)
        entry.mkdir(parents=True)
        (entry / "stat").write_text(f"{pid} (PDF Apps) (x) S {ppid} {pid} {pid} 0\n")
        args = argv[0] if argv else ([exe] if exe is not None else [])
        # As the kernel shows it: each argument ends in a NUL.
        (entry / "cmdline").write_bytes(b"".join(os.fsencode(a) + b"\0" for a in args))
        if exe is not None:
            os.symlink(exe, entry / "exe")
    (root / "self").mkdir()
    (root / "sys").mkdir()
    return root


A6_EXE = "/opt/PDF Apps ç/PDFApps"


def _a6_proc(tmp_path: Path) -> Path:
    return _fake_proc(tmp_path, {
        1: (0, "/sbin/init"),
        40: (1, "/usr/bin/bash"),
        50: (40, A6_EXE + " (deleted)"),  # the bootloader an earlier execve left
        60: (50, A6_EXE),                 # this process's bootloader
        61: (60, A6_EXE),                 # this process
        70: (1, A6_EXE),                  # another instance: its bootloader
        71: (70, A6_EXE),                 # and its Python process
        80: (1, A6_EXE + " (deleted)"),   # an instance from before an earlier swap
        90: (1, "/usr/bin/PDFApps"),      # another copy, elsewhere
        91: (1, "/opt/PDF Apps ç/pdfapps_staged_x"),
        92: (2, None),                    # a kernel thread: no exe
    })


@posix_only
def test_other_instances_are_found_and_this_one_s_lineage_is_not(tmp_path):
    root = _a6_proc(tmp_path)
    assert update_apply._instances_of(A6_EXE, proc=str(root), own_pid=61) == [70, 71, 80]
    # From the other side, the instance in 60/61 is the other one.
    assert update_apply._instances_of(A6_EXE, proc=str(root), own_pid=71) == [50, 60, 61, 80]


# The command line Compress starts its font-subset child with, in the bundle.
SUBSET_CHILD = [A6_EXE, WORKER_FLAG]


@posix_only
def test_the_font_subset_child_of_this_process_is_not_another_instance(tmp_path):
    """Compress runs ``sys.executable`` with ``WORKER_FLAG`` as a child.
    Taken for another window, it showed "open in another window" instead
    of "a task is running" (measured). Any other descendant is a window:
    one started through a shell that is still alive was not counted, and
    its imports broke after the swap (measured with the real binary)."""
    root = _fake_proc(tmp_path, {
        1: (0, "/sbin/init"),
        40: (1, "/usr/bin/bash"),
        60: (40, A6_EXE),                        # this process's bootloader
        61: (60, A6_EXE),                        # this process
        62: (61, A6_EXE, SUBSET_CHILD),          # the font-subset child it started
        63: (62, A6_EXE, SUBSET_CHILD),          # and that child's own child
        64: (61, "/usr/bin/sh", ["sh", "-c", "PDFApps"]),  # a shell it started
        65: (64, A6_EXE),                        # a window started from that shell
        66: (65, A6_EXE),                        # and its Python process
        67: (61, A6_EXE, [A6_EXE, "x.pdf", WORKER_FLAG]),  # a window
        68: (61, A6_EXE, [A6_EXE, f"/home/u/{WORKER_FLAG}"]),   # a window
        69: (61, A6_EXE, [WORKER_FLAG]),  # a window, argv[0] spoofed
        70: (40, A6_EXE),                        # another instance, from the same shell
        71: (70, A6_EXE),                        # and its Python process
    })
    assert update_apply._instances_of(A6_EXE, proc=str(root), own_pid=61) == [
        65, 66, 67, 68, 69, 70, 71]
    # From the other side, the subset child is just another process of
    # that other window.
    assert update_apply._instances_of(A6_EXE, proc=str(root), own_pid=71) == [
        60, 61, 62, 63, 65, 66, 67, 68, 69]


@posix_only
def test_the_subset_child_s_command_line_is_read_from_its_own_entry(tmp_path):
    """One that cannot be read is counted: a window has to be told apart
    from the subset child, not assumed to be one."""
    root = _fake_proc(tmp_path, {
        60: (1, A6_EXE),
        61: (60, A6_EXE),
        62: (61, A6_EXE, SUBSET_CHILD),
    })
    assert update_apply._instances_of(A6_EXE, proc=str(root), own_pid=61) == []
    (root / "62" / "cmdline").unlink()
    assert update_apply._instances_of(A6_EXE, proc=str(root), own_pid=61) == [62]


@posix_only
def test_other_users_processes_are_not_counted(tmp_path, monkeypatch):
    root = _a6_proc(tmp_path)
    monkeypatch.setattr(os, "getuid", lambda: os.stat(root).st_uid + 1)
    assert update_apply._instances_of(A6_EXE, proc=str(root), own_pid=61) == []


def test_an_unreadable_proc_finds_nobody(tmp_path):
    """Fails open: where /proc cannot be read the update behaves as before."""
    assert update_apply._instances_of(A6_EXE, proc=str(tmp_path / "missing"), own_pid=61) == []


def _wait_for(condition, what, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, what()
        time.sleep(0.02)


def _exe_of(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return None


def _start_unrelated(tmp_path: Path, exe: Path) -> int:
    """Run *exe* as ``sleep 60`` from a process that exits at once.

    Orphaned, it is nobody's descendant here, as another instance is.
    """
    script = tmp_path / "start_unrelated.py"
    script.write_text(
        "import subprocess, sys\n"
        "p = subprocess.Popen(['sleep', '60'], executable=sys.argv[1],\n"
        "                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,\n"
        "                     stderr=subprocess.DEVNULL, start_new_session=True)\n"
        "print(p.pid)\n")
    out = subprocess.run([sys.executable, str(script), str(exe)],
                         capture_output=True, text=True, timeout=30, check=True)
    return int(out.stdout)


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="needs a real /proc")
def test_a_real_process_running_the_binary_is_found_even_once_replaced(tmp_path):
    # Named sleep: the multicall coreutils of Ubuntu 26.04 picks its tool
    # by the executable's own name, whatever argv[0] says, and a copy named
    # PDFApps exited at once (measured).
    exe = tmp_path / "PDF Apps ç" / "sleep"
    exe.parent.mkdir()
    exe.write_bytes(Path("/bin/sleep").read_bytes())
    exe.chmod(0o755)
    current = os.path.realpath(exe)
    assert update_apply._instances_of(current) == []
    # A window started below this one, through a shell that stays alive
    # (the ": " after it keeps sh from exec'ing into it).
    shell = subprocess.Popen(["/bin/sh", "-c", '"$0" 60; :', str(exe)],
                             stdin=subprocess.DEVNULL, start_new_session=True)
    other = None
    try:
        _wait_for(lambda: len(update_apply._instances_of(current)) == 1,
                  lambda: update_apply._instances_of(current))
        (below,) = update_apply._instances_of(current)
        assert update_apply._parent_pid("/proc", below) == shell.pid
        other = _start_unrelated(tmp_path, exe)
        both = sorted([below, other])
        _wait_for(lambda: update_apply._instances_of(current) == both,
                  lambda: (both, update_apply._instances_of(current)))
        replacement = tmp_path / "new"
        replacement.write_bytes(b"\x7fELF new")
        os.replace(replacement, exe)
        assert os.readlink(f"/proc/{other}/exe").endswith(" (deleted)")
        assert update_apply._instances_of(current) == both
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(shell.pid, signal.SIGKILL)
        shell.wait()
        if other is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(other, signal.SIGKILL)
    # Whoever adopted it reaps it; until then a zombie has no exe.
    _wait_for(lambda: update_apply._instances_of(current) == [],
              lambda: update_apply._instances_of(current))


def test_an_instance_started_during_the_probe_stops_the_swap(box, monkeypatch):
    asked = []

    def instances(current, **kw):
        asked.append((current, list(box.events)))
        return [4242]

    monkeypatch.setattr(update_apply, "_instances_of", instances)
    downloaded = box.download(GOOD_TARBALL)
    with pytest.raises(UpdateError) as err:
        update_apply.install_new_binary(downloaded, NEW_NAME, TAG)
    assert str(err.value) == t("update.error.other_instance")
    assert asked == [(os.path.realpath(box.exe), ["probe"])], "asked after the probe"
    box.assert_untouched()
    assert not os.path.exists(downloaded)


def test_a_source_run_is_not_compared_with_other_pythons(box, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(update_apply, "_instances_of",
                        lambda *a, **k: pytest.fail("scanned for a source run"))
    update_apply.refuse_if_running_elsewhere()


def test_dialog_refuses_before_asking_or_downloading(box, qapp, monkeypatch):
    monkeypatch.setattr(update_apply, "_instances_of", lambda current, **kw: [4242])
    asked = []
    dlg = _run_dialog(qapp, monkeypatch, _release(GOOD_TARBALL, NEW_NAME), GOOD_TARBALL,
                      confirm_discard=lambda: asked.append(1) or True)
    assert dlg._status.text() == t("update.error.other_instance")
    assert asked == []
    assert dlg._update_btn.isEnabled() and dlg._cancel_btn.isEnabled()
    assert not list(box.tmp.glob("PDFApps_update_*")), "something was downloaded"
    box.assert_untouched()


# ── R6: the new binary must start as a fresh launch ──────────────────────


BOOTLOADER_VARS = {
    "_PYI_APPLICATION_HOME_DIR": "/tmp/_MEIold",
    "_PYI_PARENT_PROCESS_LEVEL": "1",
    "_PYI_ARCHIVE_FILE": "/old/PDFApps",
    "_PYI_SPLASH_IPC": "0",
    "_MEIPASS": "/tmp/_MEIold",
    "_MEIPASS2": "/tmp/_MEIold",
}


def _set_bootloader_env(monkeypatch):
    for key, value in BOOTLOADER_VARS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("KEEP_ME", "yes")


def test_no_bootloader_variable_reaches_execv(box, monkeypatch):
    _set_bootloader_env(monkeypatch)
    _apply(box.download(GOOD_TARBALL))
    env = box.exec_calls[0]["env"]
    assert not [k for k in env if k.startswith(("_PYI_", "_MEIPASS"))]
    assert env["KEEP_ME"] == "yes"


def test_the_running_process_environment_is_never_modified(box, monkeypatch):
    """The process keeps running on this environment if execve fails, and
    the new one gets its environment as an argument."""
    _set_bootloader_env(monkeypatch)
    before = dict(os.environ)
    box.exec_error = OSError(8, "Exec format error")
    with pytest.raises(UpdateError):
        _apply(box.download(GOOD_TARBALL))
    assert not [k for k in box.exec_calls[0]["env"] if k in BOOTLOADER_VARS]
    assert box.exec_calls[0]["os_environ"] == before
    assert dict(os.environ) == before


def test_refused_update_does_not_touch_the_environment(box, monkeypatch):
    _set_bootloader_env(monkeypatch)
    before = dict(os.environ)
    with pytest.raises(UpdateError):
        _apply(box.download(b"junk"))
    assert dict(os.environ) == before


def test_bundle_is_taken_out_of_the_library_path(box, monkeypatch):
    """The old bootloader stays alive across execv, so its directory still
    exists, and the new bootloader would record it as the pre-launch value."""
    mei = os.path.normpath("/tmp/_MEIold")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "_MEIPASS", mei, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", f"{mei}:/opt/userlib")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/opt/userlib")
    _apply(box.download(GOOD_TARBALL))
    env = box.exec_calls[0]["env"]
    assert env["LD_LIBRARY_PATH"] == "/opt/userlib"
    assert "LD_LIBRARY_PATH_ORIG" not in env


# ── never replace an interpreter ─────────────────────────────────────────


@pytest.mark.parametrize("frozen", [None, False])
def test_source_run_is_refused(box, monkeypatch, frozen):
    if frozen is None:
        monkeypatch.delattr(sys, "frozen", raising=False)
    else:
        monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    downloaded = box.download(GOOD_TARBALL)
    with pytest.raises(UpdateError) as err:
        _apply(downloaded)
    assert str(err.value) == t("update.error.not_frozen")
    box.assert_untouched()
    assert not os.path.exists(downloaded)


# ── the downloaded file never outlives the attempt (R5/F3) ───────────────


@pytest.mark.parametrize("payload, error", ids=["applied", "restart fails", "refused"], argvalues=[
    (GOOD_TARBALL, None),
    (GOOD_TARBALL, OSError(8, "Exec format error")),
    (b"junk", None),
])
def test_downloaded_file_is_removed(box, payload, error):
    box.exec_error = error
    downloaded = box.download(payload)
    # Whether the update went through or not, the download is removed.
    with contextlib.suppress(UpdateError):
        _apply(downloaded)
    assert not os.path.exists(downloaded)


# ── the new process deletes the backup it was handed ─────────────────────


def _backup_for_startup(box) -> Path:
    _apply(box.download(GOOD_TARBALL))
    (backup,) = box.backups()
    return backup


def test_the_new_process_deletes_the_backup_it_was_handed(box):
    backup = _backup_for_startup(box)
    env = {BACKUP_ENV: box.exec_calls[0]["env"][BACKUP_ENV], "OTHER": "1"}
    update_apply.discard_backup_after_update(env)
    assert not backup.exists()
    assert env == {"OTHER": "1"}, "no child process may inherit it"


def test_it_reads_and_clears_os_environ_by_default(box, monkeypatch):
    backup = _backup_for_startup(box)
    monkeypatch.setenv(BACKUP_ENV, str(backup))
    update_apply.discard_backup_after_update()
    assert not backup.exists()
    assert BACKUP_ENV not in os.environ


def test_a_restore_failed_marker_keeps_it(box):
    backup = _backup_for_startup(box)
    Path(str(backup) + ".restore-failed").write_bytes(b"")
    update_apply.discard_backup_after_update({BACKUP_ENV: str(backup)})
    assert backup.exists()


@pytest.mark.parametrize("where", ["elsewhere", "other prefix", "no infix", "missing"])
def test_only_a_backup_of_this_binary_in_the_temp_dir_is_deleted(box, tmp_path, where):
    victim = {
        "elsewhere": tmp_path / "PDFApps.x.pdfapps-backup",
        "other prefix": box.tmp / "Other.x.pdfapps-backup",
        "no infix": box.tmp / "PDFApps..pdfapps-backup",
        "missing": box.tmp / "PDFApps.gone.pdfapps-backup",
    }[where]
    if where != "missing":
        victim.write_bytes(b"keep")
    update_apply.discard_backup_after_update({BACKUP_ENV: str(victim)})
    if where != "missing":
        assert victim.read_bytes() == b"keep"


@posix_only
def test_a_link_named_like_a_backup_is_not_followed(box, tmp_path):
    target = tmp_path / "precious"
    target.write_bytes(b"precious")
    link = box.tmp / "PDFApps.x.pdfapps-backup"
    link.symlink_to(target)
    update_apply.discard_backup_after_update({BACKUP_ENV: str(link)})
    assert link.is_symlink() and target.read_bytes() == b"precious"


def test_a_source_run_deletes_nothing_but_still_clears_the_variable(box, monkeypatch):
    backup = _backup_for_startup(box)
    monkeypatch.delattr(sys, "frozen", raising=False)
    env = {BACKUP_ENV: str(backup)}
    update_apply.discard_backup_after_update(env)
    assert backup.exists()
    assert env == {}


def test_pdfapps_main_calls_it_once_the_window_is_shown():
    """Behaviour of main() needs a full app; the order is what matters."""
    import ast
    tree = ast.parse((ROOT / "pdfapps.py").read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [ast.unparse(n.func) for n in ast.walk(main) if isinstance(n, ast.Call)]
    assert "discard_backup_after_update" in calls
    assert calls.index("window.show") < calls.index("discard_backup_after_update")


# ── the --version probe itself (POSIX: it runs scripts) ──────────────────


def _script(tmp_path: Path, body: str, name: str = "staged") -> str:
    path = tmp_path / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def probe_tmp(tmp_path, monkeypatch):
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp))
    return tmp


@posix_only
def test_probe_accepts_the_announced_version(tmp_path, probe_tmp):
    staged = _script(tmp_path, 'echo "PDFApps 9.9.9"\n')
    update_apply._probe_version(staged, "v9.9.9")
    update_apply._probe_version(staged, "9.9.9")
    assert list(probe_tmp.iterdir()) == []


def _message_head(key: str, **kwargs) -> str:
    """The translated text up to its first placeholder."""
    return t(key, **{k: "\0" for k in kwargs}).split("\0")[0]


@posix_only
@pytest.mark.parametrize("body, key", [
    ('echo "PDFApps 9.9.8"\n', "update.error.probe_wrong_version"),
    ('echo "PDFApps 9.9.90"\n', "update.error.probe_wrong_version"),
    ('echo "PDFApps 9.9.9" >&2\n', "update.error.probe_wrong_version"),
    ('', "update.error.probe_wrong_version"),
    ('echo "PDFApps 9.9.9"\nexit 1\n', "update.error.probe_failed"),
    ('echo "[PYI-1:ERROR] Failed to load Python shared library" >&2\nexit 255\n',
     "update.error.probe_failed"),
], ids=["older", "prefix of another", "on stderr", "silent", "exit 1", "bootloader error"])
def test_probe_refuses_anything_else(tmp_path, probe_tmp, body, key):
    """A binary that ran and answered something else did start: saying it
    did not would send the user after a problem their system lacks."""
    staged = _script(tmp_path, body)
    with pytest.raises(UpdateError) as err:
        update_apply._probe_version(staged, "v9.9.9")
    other = ({"update.error.probe_failed", "update.error.probe_wrong_version"}
             - {key}).pop()
    assert str(err.value).startswith(_message_head(key, expected=1, error=1))
    assert not str(err.value).startswith(_message_head(other, expected=1, error=1))
    if key == "update.error.probe_wrong_version":
        assert str(err.value).startswith(
            t(key, expected="9.9.9", error="X").split("(")[0])
    assert list(probe_tmp.iterdir()) == []


@posix_only
def test_probe_refuses_a_file_it_cannot_execute(tmp_path, probe_tmp):
    """What a noexec install dir or a foreign binary look like to Popen."""
    staged = _script(tmp_path, 'echo "PDFApps 9.9.9"\n')
    os.chmod(staged, 0o600)
    with pytest.raises(UpdateError) as err:
        update_apply._probe_version(staged, "v9.9.9")
    assert t("update.error.probe_failed", error="X").split("(")[0] in str(err.value)
    assert list(probe_tmp.iterdir()) == []


@posix_only
def test_probe_gets_the_launch_environment_and_its_own_tmpdir(tmp_path, probe_tmp, monkeypatch):
    _set_bootloader_env(monkeypatch)
    out = tmp_path / "env.txt"
    staged = _script(tmp_path, f'env > "{out}"\necho "PDFApps 9.9.9"\n')
    update_apply._probe_version(staged, "v9.9.9")
    env = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    assert not [k for k in env if k.startswith(("_PYI_", "_MEIPASS"))]
    assert env["KEEP_ME"] == "yes"
    assert os.path.dirname(env["TMPDIR"]) == str(probe_tmp)
    assert not os.path.exists(env["TMPDIR"])


@posix_only
def test_a_hanging_probe_is_killed_with_its_children_and_its_extraction(tmp_path, probe_tmp):
    """The one-file bootloader forks; a timeout must not leave the child
    running, nor its ~200 MB extraction in the temp dir."""
    pidfile = tmp_path / "child.pid"
    staged = _script(tmp_path, (
        'mkdir "$TMPDIR/_MEIfake" && echo data > "$TMPDIR/_MEIfake/lib.so"\n'
        'sleep 60 &\n'
        f'echo $! > "{pidfile}"\n'
        'wait\n'
    ))
    started = time.monotonic()
    with pytest.raises(UpdateError) as err:
        update_apply._probe_version(staged, "v9.9.9", timeout=1)
    assert time.monotonic() - started < 10
    assert "no answer after 1 s" in str(err.value)
    assert list(probe_tmp.iterdir()) == [], "extraction left behind"
    child = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        # Reparented to init and reaped there; a zombie still answers.
        try:
            with open(f"/proc/{child}/stat") as f:
                state = f.read().rsplit(") ", 1)[-1][:1]
        except FileNotFoundError:
            break
        if state == "Z":
            break
        time.sleep(0.05)
    else:
        os.kill(child, 9)
        pytest.fail("the probe's child outlived the timeout")


def _open_fds() -> dict[str, str]:
    """This process's open fds and what each points to (``pipe:[N]``...)."""
    links = {}
    for fd in os.listdir("/proc/self/fd"):
        # Closed since the listdir: its own fd, or one another thread had.
        with contextlib.suppress(FileNotFoundError):
            links[fd] = os.readlink(f"/proc/self/fd/{fd}")
    return links


@posix_only
@pytest.mark.skipif(not __import__("shutil").which("setsid"), reason="needs setsid")
def test_a_descendant_that_left_the_group_does_not_hold_the_probe(tmp_path, probe_tmp):
    """The kill reaches the group only. A descendant in its own session
    still holds stdout, and reading to EOF waited as long as it lived."""
    pidfile = tmp_path / "escaped.pid"
    probe_pid = tmp_path / "probe.pid"
    staged = _script(tmp_path, (
        f'echo $$ > "{probe_pid}"\n'
        f"setsid sh -c 'echo $$ > \"{pidfile}\"; exec sleep 60' &\n"
        "sleep 1000\n"
    ))
    fds = _open_fds() if os.path.isdir("/proc/self/fd") else None
    started = time.monotonic()
    try:
        with pytest.raises(UpdateError) as err:
            update_apply._probe_version(staged, "v9.9.9", timeout=1)
        elapsed = time.monotonic() - started
        # While err, and the frames its traceback holds, are still alive:
        # the pipes are closed and the killed probe is reaped all the same.
        if fds is not None:
            # Only fds opened since, and only pipes: Qt closes and opens
            # eventfds for threads of earlier tests at any time, which made
            # a count of every fd fail in 3 of 4 full Linux runs.
            opened = {f: link for f, link in _open_fds().items() if fds.get(f) != link}
            assert not [link for link in opened.values() if link.startswith("pipe:")], \
                "pipes left open"
            assert not os.path.exists(f"/proc/{probe_pid.read_text().strip()}"), \
                "the killed probe was left a zombie"
    finally:
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if pidfile.exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pidfile.read_text()), 9)
    assert pidfile.exists(), "the descendant never started: nothing was tested"
    assert "no answer after 1 s" in str(err.value)
    # The timeout, two short grace periods and margin; the descendant
    # lives 60 s, which is how long reading to EOF used to take.
    assert elapsed < 10, elapsed
    assert list(probe_tmp.iterdir()) == []


# ── t6: the tarball build.yml actually makes ─────────────────────────────


def test_the_tarball_build_yml_makes_is_one_the_updater_installs(box, tmp_path):
    """``tar -C dist .`` would pack ``./PDFApps`` and pass CI, and every
    installed copy would then refuse every update."""
    from _workflow_steps import find_step, load_workflow, run_bash_script

    step = find_step(load_workflow("build.yml"), "build", "Build (Linux)")
    (line,) = re.findall(r"^\s*tar .*$", step["run"], flags=re.MULTILINE)
    work = tmp_path / "work"
    (work / "dist").mkdir(parents=True)
    (work / "dist" / "PDFApps").write_bytes(NEW_BINARY)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    proc = run_bash_script(line.strip() + "\n", ["-e"], tmp_path=tmp_path,
                           cwd=work, bindir=bindir, env={})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (made,) = (work / "dist").glob("*.tar.gz")
    assert made.name == updater.LINUX_ASSET_NAME

    with tarfile.open(made, "r:gz") as tar:
        assert update_apply._binary_member(tar).name == "PDFApps"
    _apply(box.download(made.read_bytes()), made.name)
    assert box.exe.read_bytes() == NEW_BINARY


# ── the dialog, through the real download and install threads ────────────


class _Response:
    def __init__(self, payload: bytes):
        self._buf = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        return self._buf.read(size)

    def close(self):
        pass


def _release(payload: bytes, *names: str, digest: str | None = None) -> dict:
    digest = digest or hashlib.sha256(payload).hexdigest()
    return {
        "tag_name": TAG,
        "body": "## Checksums (SHA256)\n" + "\n".join(
            f"{digest}  {n}" for n in names),
        "assets": [
            {"name": n, "browser_download_url": f"https://example.invalid/{n}"}
            for n in names
        ],
    }


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(qapp, done, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not done():
        assert time.monotonic() < deadline, "timed out"
        qapp.processEvents()
        time.sleep(0.005)


def _idle(dlg) -> bool:
    return (dlg._dl_thread is None and dlg._install_thread is None
            and not dlg._installing)


def _run_dialog(qapp, monkeypatch, release, payload, **hooks):
    monkeypatch.setattr(sys, "platform", "linux")
    dlg = updater.UpdateDialog(release, **hooks)
    with patch("app.updater.urllib.request.urlopen",
               return_value=_Response(payload)):
        dlg._start_download()
        _pump(qapp, lambda: _idle(dlg))
        qapp.processEvents()
    dlg._stop_dots_animation()
    return dlg


def test_dialog_installs_the_new_binary_and_restarts_once(box, qapp, monkeypatch):
    release = _release(GOOD_TARBALL, "PDFAppsSetup.exe", "PDFApps-macOS.dmg", NEW_NAME)
    dlg = _run_dialog(qapp, monkeypatch, release, GOOD_TARBALL)

    assert dlg._asset["name"] == NEW_NAME
    assert box.exe.read_bytes() == NEW_BINARY
    assert len(box.exec_calls) == 1
    assert not list(box.tmp.glob("PDFApps_update_*")), "download left behind"
    if os.name == "posix":
        assert stat.S_IMODE(box.exe.stat().st_mode) == 0o755


def test_dialog_installs_off_the_gui_thread(box, qapp, monkeypatch):
    _run_dialog(qapp, monkeypatch, _release(GOOD_TARBALL, NEW_NAME), GOOD_TARBALL)
    (call,) = box.probe_calls
    assert call["on_main_thread"] is False
    assert call["version"] == TAG


def test_dialog_cannot_be_closed_or_restarted_while_installing(box, qapp, monkeypatch):
    gate, entered = threading.Event(), threading.Event()
    real_probe = box.fake_probe

    def slow_probe(staged, version, **kw):
        entered.set()
        assert gate.wait(10)
        real_probe(staged, version, **kw)

    monkeypatch.setattr(update_apply, "_probe_version", slow_probe)
    monkeypatch.setattr(sys, "platform", "linux")
    dlg = updater.UpdateDialog(_release(GOOD_TARBALL, NEW_NAME))
    with patch("app.updater.urllib.request.urlopen",
               return_value=_Response(GOOD_TARBALL)):
        dlg._start_download()
        _pump(qapp, entered.is_set)
        assert dlg._installing
        assert not dlg._update_btn.isEnabled() and not dlg._cancel_btn.isEnabled()
        dlg.reject()
        from PySide6.QtGui import QCloseEvent
        event = QCloseEvent()
        dlg.closeEvent(event)
        assert not event.isAccepted()
        assert not dlg._dismissed
        gate.set()
        _pump(qapp, lambda: _idle(dlg))
    dlg._stop_dots_animation()
    assert len(box.exec_calls) == 1, "the install the user could not stop went on"


def test_dialog_drops_a_download_that_finishes_after_it_was_closed(box, qapp, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    dlg = updater.UpdateDialog(_release(GOOD_TARBALL, NEW_NAME))
    dlg.reject()
    downloaded = box.download(GOOD_TARBALL)
    dlg._on_finished(downloaded)
    dlg._stop_dots_animation()
    assert not dlg._installing
    box.assert_untouched()
    assert not os.path.exists(downloaded)


def test_dialog_shows_the_message_after_a_failed_restart(box, qapp, monkeypatch):
    box.exec_error = OSError(8, "Exec format error")
    release = _release(GOOD_TARBALL, NEW_NAME)
    dlg = _run_dialog(qapp, monkeypatch, release, GOOD_TARBALL)

    assert box.exe.read_bytes() == OLD_BINARY
    assert dlg._status.text() == t("update.error.restart_failed", error=box.exec_error)
    assert dlg._update_btn.isEnabled(), "the user can retry"
    assert dlg._cancel_btn.isEnabled()
    assert dlg._progress.maximum() == 100, "left in busy mode"


def test_dialog_shows_apply_errors_without_the_check_prefix(box, qapp, monkeypatch):
    """The prefix says "Could not check for updates", which is false here."""
    box.probe_error = update_apply._probe_failed("exit status 127")
    dlg = _run_dialog(qapp, monkeypatch, _release(GOOD_TARBALL, NEW_NAME), GOOD_TARBALL)
    assert dlg._status.text() == t("update.error.probe_failed", error="exit status 127")
    assert not dlg._status.text().startswith(t("update.error"))
    box.assert_untouched()


def test_dialog_after_a_failed_restore_refuses_another_attempt(box, qapp, monkeypatch):
    box.exec_error = OSError(8, "Exec format error")
    _full_disk_on_restore(monkeypatch)
    dlg = _run_dialog(qapp, monkeypatch, _release(GOOD_TARBALL, NEW_NAME), GOOD_TARBALL)
    (backup,) = box.backups()
    assert str(backup) in dlg._status.text()
    assert not dlg._update_btn.isEnabled()
    assert dlg._cancel_btn.isEnabled()


def test_a_new_dialog_after_a_failed_restore_keeps_the_named_copy(box, qapp, monkeypatch):
    """The next session may offer the update again; the copy the message
    named must survive it."""
    box.exec_error = OSError(8, "Exec format error")
    _full_disk_on_restore(monkeypatch)
    dlg = _run_dialog(qapp, monkeypatch, _release(GOOD_TARBALL, NEW_NAME), GOOD_TARBALL)
    (named,) = box.backups()
    assert str(named) in dlg._status.text()
    monkeypatch.undo()
    _install_box(box, monkeypatch)
    box.exec_error = None

    payload = _tarball(("PDFApps", b"\x7fELF third"))
    _run_dialog(qapp, monkeypatch, _release(payload, NEW_NAME), payload)
    assert box.exe.read_bytes() == b"\x7fELF third"
    assert named.read_bytes() == OLD_BINARY


def test_dialog_status_wraps_and_can_be_copied(qapp):
    """At the dialog's 520 px the restore_failed message used to be cut
    before the path the user needed."""
    from PySide6.QtCore import Qt
    dlg = updater.UpdateDialog(_release(GOOD_TARBALL, NEW_NAME))
    path = "/tmp/PDFApps.k2j3h4.pdfapps-backup"
    message = t("update.error.restore_failed", path=path,
                error=OSError(errno.ENOSPC, "No space left on device"))
    dlg._show_failure(message)
    status = dlg._status
    assert status.wordWrap()
    assert status.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    assert status.fontMetrics().horizontalAdvance(message) > 520
    assert status.minimumSizeHint().width() < 520
    assert status.heightForWidth(480) > status.fontMetrics().height()
    assert path in status.text()


def test_dialog_status_shows_a_message_as_typed_not_as_markup(qapp):
    """The failure messages carry paths the user chose and errors from the
    OS. Read as rich text, a folder named ``<b>x</b>`` lost its tags on
    screen and in what the user copied. text() returns what was set in
    either format; the selection is what is shown."""
    from PySide6.QtCore import Qt
    dlg = updater.UpdateDialog(_release(GOOD_TARBALL, NEW_NAME))
    message = "a <b>x</b>"
    assert Qt.mightBeRichText(message), "the default format would render it"
    dlg._show_failure(message)
    status = dlg._status
    assert status.textFormat() == Qt.TextFormat.PlainText
    status.setSelection(0, len(message))
    assert status.selectedText() == message


def test_dialog_shows_the_message_when_refusing_a_source_run(box, qapp, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    dlg = _run_dialog(qapp, monkeypatch, _release(GOOD_TARBALL, NEW_NAME), GOOD_TARBALL)
    assert dlg._status.text() == t("update.error.not_frozen")
    box.assert_untouched()


def test_dialog_with_a_wrong_hash_never_reaches_the_binary(box, qapp, monkeypatch):
    release = _release(GOOD_TARBALL, NEW_NAME, digest="0" * 64)
    dlg = _run_dialog(qapp, monkeypatch, release, GOOD_TARBALL)
    assert "0" * 64 in dlg._status.text()
    box.assert_untouched()


# ── C1: execve skips closeEvent, so the dialog asks and drains ───────────


def test_dialog_asks_before_downloading_and_cancel_costs_nothing(box, qapp, monkeypatch):
    asked = []
    monkeypatch.setattr(sys, "platform", "linux")
    dlg = updater.UpdateDialog(_release(GOOD_TARBALL, NEW_NAME),
                               confirm_discard=lambda: asked.append(1) or False)
    with patch("app.updater.urllib.request.urlopen") as urlopen:
        dlg._start_download()
        qapp.processEvents()
    assert asked == [1]
    urlopen.assert_not_called()
    assert dlg._dl_thread is None
    assert dlg._update_btn.isEnabled(), "the user can try again later"
    assert not list(box.tmp.glob("PDFApps_update_*"))
    box.assert_untouched()


def test_dialog_drains_the_workers_right_before_execve(box, qapp, monkeypatch):
    dlg = _run_dialog(
        qapp, monkeypatch, _release(GOOD_TARBALL, NEW_NAME), GOOD_TARBALL,
        confirm_discard=lambda: box.events.append("confirm") or True,
        before_exec=lambda: box.events.append("drain"),
    )
    assert box.events == ["confirm", "probe", "drain", "execve"]
    assert dlg._asset["name"] == NEW_NAME


@pytest.mark.parametrize("platform, asset", [
    ("win32", "PDFAppsSetup.exe"), ("darwin", "PDFApps-macOS.dmg"),
])
def test_other_platforms_do_not_ask_in_the_dialog(qapp, monkeypatch, platform, asset):
    """They quit through QApplication.quit(), which reaches closeEvent."""
    monkeypatch.setattr(sys, "platform", platform)
    asked = []
    dlg = updater.UpdateDialog(_release(b"x", asset),
                               confirm_discard=lambda: asked.append(1) or False)
    with patch("app.updater.urllib.request.urlopen",
               side_effect=OSError("offline")):
        dlg._start_download()
        _pump(qapp, lambda: dlg._dl_thread is None)
    dlg._stop_dots_animation()
    assert asked == []


def test_the_controller_hands_the_window_s_prompt_and_teardown_to_the_dialog(monkeypatch):
    from app import update_controller
    window = types.SimpleNamespace(
        _confirm_update_restart=MagicMock(name="confirm"),
        _prepare_update_restart=MagicMock(name="teardown"),
    )
    stub = types.SimpleNamespace(_update_release={"tag_name": TAG}, _window=window)
    made = {}

    class _FakeDialog:
        def __init__(self, release, parent=None, **hooks):
            made.update(hooks, parent=parent)

        def exec(self):
            made["exec"] = True

    monkeypatch.setattr(updater, "UpdateDialog", _FakeDialog)
    update_controller.UpdateController.show_update_dialog(stub)
    assert made["parent"] is window
    assert made["confirm_discard"] is window._confirm_update_restart
    assert made["before_exec"] is window._prepare_update_restart
    assert made["exec"]


def _window_stub(*, pipeline_unsaved: bool, editor_pending: bool,
                 saved: bool = True):
    """``saved`` is what ``_save_pipeline`` answers: False for a Save dialog
    cancelled or refused."""
    from app.window import MainWindow
    calls: list[str] = []
    editor = types.SimpleNamespace(_user_pending=[{"type": "draw"}] if editor_pending else [])

    def _save_pipeline(viewer=None):
        calls.append(f"save {viewer}")
        return saved

    stub = types.SimpleNamespace(
        _viewers=["other tab", "viewer"],
        _viewer_has_unsaved=lambda v: pipeline_unsaved and v == "viewer",
        _save_pipeline=_save_pipeline,
        _edit_tool_idx=lambda: 0,
        stack=types.SimpleNamespace(widget=lambda i: editor),
        _cleanup_pipeline=lambda vid: calls.append("cleanup"),
        _wait_for_workers_on_all_pages=lambda: calls.append("drain"),
        _wipe_all_pdf_passwords=lambda: calls.append("wipe"),
    )
    stub._confirm_discard_unsaved = types.MethodType(
        MainWindow._confirm_discard_unsaved, stub)
    # The real one, so the stub's _save_pipeline is what it calls.
    stub._try_save_pipeline = types.MethodType(
        MainWindow._try_save_pipeline, stub)
    return stub, calls


@pytest.mark.parametrize("pipeline, editor, answers, expected, calls_after", [
    (False, False, [], True, []),
    (True, False, ["Cancel"], False, []),
    (True, False, ["Discard"], True, []),
    (True, False, ["Save"], True, ["save viewer"]),
    (False, True, ["Cancel"], False, []),
    (False, True, ["Discard"], True, []),
    (True, True, ["Discard", "Cancel"], False, []),
    (True, True, ["Save", "Discard"], True, ["save viewer"]),
])
def test_confirm_discard_only_asks(qapp, monkeypatch, pipeline, editor, answers,
                                   expected, calls_after):
    """No cleanup, drain or password sweep in here: execve may still fail,
    and then this process goes on running with all of them."""
    from PySide6.QtWidgets import QMessageBox
    from app import window
    stub, calls = _window_stub(pipeline_unsaved=pipeline, editor_pending=editor)
    replies = [getattr(QMessageBox.StandardButton, a) for a in answers]
    defaults = []

    def question(*args):
        defaults.append(args[-1])
        return replies.pop(0)

    monkeypatch.setattr(window.QMessageBox, "question", question)
    assert stub._confirm_discard_unsaved() is expected
    assert replies == [], "not every prompt was shown"
    assert calls == calls_after
    assert set(defaults) <= {QMessageBox.StandardButton.Cancel}


@pytest.mark.parametrize("editor", [False, True])
def test_confirm_discard_stays_when_the_save_did_not_happen(qapp, monkeypatch, editor):
    """C-1: closeEvent tears down after a True, deleting the result that a
    cancelled or refused Save dialog left unsaved."""
    from PySide6.QtWidgets import QMessageBox
    from app import window
    stub, calls = _window_stub(pipeline_unsaved=True, editor_pending=editor,
                               saved=False)
    replies = [QMessageBox.StandardButton.Save]
    monkeypatch.setattr(window.QMessageBox, "question",
                        lambda *a: replies.pop(0))
    assert stub._confirm_discard_unsaved() is False
    assert replies == []
    assert calls == ["save viewer"], "no editor prompt after it either"


def test_close_event_stops_before_any_teardown_on_cancel(qapp, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox
    from app import window
    stub, calls = _window_stub(pipeline_unsaved=True, editor_pending=False)
    monkeypatch.setattr(window.QMessageBox, "question",
                        lambda *a: QMessageBox.StandardButton.Cancel)
    event = QCloseEvent()
    window.MainWindow.closeEvent(stub, event)
    assert not event.isAccepted()
    assert calls == []


# ── round 3: work the restart would lose, with a real MainWindow ─────────


class _Prompts:
    """``QMessageBox.question`` with scripted answers; records each text
    and the buttons it offered."""

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.texts: list[str] = []
        self.buttons: list = []
        self.defaults: list = []

    def __call__(self, parent, title, text, buttons, default):
        from PySide6.QtWidgets import QMessageBox
        self.texts.append(text)
        self.buttons.append(buttons)
        self.defaults.append(default)
        assert default == QMessageBox.StandardButton.Cancel
        assert self.answers, f"unexpected prompt: {text!r}"
        return getattr(QMessageBox.StandardButton, self.answers.pop(0))


def _make_pdf(path: Path, text: str) -> str:
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    # Bytes, not doc.save: on Windows MuPDF cannot remove a file the
    # viewer has open, and one test rewrites the result on screen.
    data = doc.tobytes()
    doc.close()
    path.write_bytes(data)
    return str(path)


@pytest.fixture
def win(box, qapp, monkeypatch, tmp_path):
    """A real MainWindow with one PDF open, its config and temp dir in tmp_path."""
    from PySide6.QtCore import QObject, Signal
    from app.update_controller import UpdateController
    from app.window import MainWindow

    class _NoInstanceServer(QObject):
        new_paths = Signal(list)

    monkeypatch.setattr("app.i18n._CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(UpdateController, "check_async", lambda self: None)
    monkeypatch.setattr("app.window.SingleInstanceServer", _NoInstanceServer)
    w = MainWindow()
    w._load_and_track(_make_pdf(tmp_path / "doc ç.pdf", "original"))
    qapp.processEvents()
    yield w
    w._pipeline_state.clear()
    w.stack.widget(w._edit_tool_idx())._pending.clear()
    w.close()
    w.deleteLater()
    qapp.processEvents()


def _first_page(w):
    from app.base import BasePage
    return next(w.stack.widget(i) for i in range(w.stack.count())
                if isinstance(w.stack.widget(i), BasePage))


def _pipeline_result(w, text: str = "result", out: str | None = None) -> str:
    """What a tool run in pipeline mode leaves: a temp result in the tab."""
    page = _first_page(w)
    if out is None:
        out = page._make_pipeline_temp(w._viewer.current_path())
    _make_pdf(Path(out), text)
    page._pipeline_success(text, out)
    return out


def _start_task(w, qapp):
    """A real _run_background task that runs until released."""
    page = _first_page(w)
    release, seen = threading.Event(), {}

    def work(worker):
        while not release.wait(0.02):
            if worker.is_cancelled():
                seen["cancelled"] = True
                return None
        return "done"

    page._run_background(work, 100, "task", on_done=lambda r: seen.setdefault("done", r))
    _pump(qapp, page.has_running_workers)
    return page, release, seen


def _finish_task(qapp, page, release):
    release.set()
    _pump(qapp, lambda: not page.has_running_workers())
    qapp.processEvents()


def _save_dialog_returns(monkeypatch, path: str) -> list:
    from PySide6.QtWidgets import QFileDialog
    calls = []

    def dialog(*a, **k):
        calls.append(a)
        return path, ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(dialog))
    return calls


def _update_from_window(w, qapp, monkeypatch, *, on_download_done=None):
    """Update now, through the window's real controller and dialog.

    *on_download_done* runs on the GUI thread once the download is in,
    before the install starts: whatever it does happened "during the
    download".
    """
    monkeypatch.setattr(sys, "platform", "linux")
    made = []
    monkeypatch.setattr(updater.UpdateDialog, "exec", lambda self: made.append(self))
    if on_download_done is not None:
        real = updater.UpdateDialog._on_finished

        def hooked(self, path):
            on_download_done()
            real(self, path)

        monkeypatch.setattr(updater.UpdateDialog, "_on_finished", hooked)
    w._update_controller._update_release = _release(GOOD_TARBALL, NEW_NAME)
    w._update_controller.show_update_dialog()
    (dlg,) = made
    with patch("app.updater.urllib.request.urlopen",
               return_value=_Response(GOOD_TARBALL)) as urlopen:
        dlg._start_download()
        _pump(qapp, lambda: _idle(dlg))
        qapp.processEvents()
    dlg._stop_dots_animation()
    return dlg, urlopen


def test_update_save_then_cancelled_save_dialog_downloads_nothing(win, box, qapp, monkeypatch):
    from app import window
    out = _pipeline_result(win)
    prompts = _Prompts("Save")
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    _save_dialog_returns(monkeypatch, "")
    dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
    urlopen.assert_not_called()
    assert dlg._status.text() == t("update.error.unsaved_work")
    assert dlg._update_btn.isEnabled(), "the user can save, then try again"
    assert prompts.texts == [t("update.unsaved_prompt")]
    assert win._viewer_has_unsaved() and os.path.isfile(out)
    box.assert_untouched()


@pytest.mark.parametrize("where", [
    "missing folder",
    pytest.param("read-only folder", marks=[
        posix_only,
        pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                           reason="root writes in a read-only folder")]),
])
def test_a_save_that_fails_refuses_the_update_and_says_why(
        win, box, qapp, monkeypatch, tmp_path, where):
    """The OSError of a failed save used to escape the dialog, which only
    catches UpdateError, and reach sys.excepthook (measured with a folder
    the user cannot write to)."""
    from app import window
    out = _pipeline_result(win)
    folder = tmp_path / "dest ç"
    if where == "read-only folder":
        folder.mkdir()
        os.chmod(folder, 0o500)
    target = folder / "saved.pdf"
    prompts = _Prompts("Save")
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    saves = _save_dialog_returns(monkeypatch, str(target))
    try:
        dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
    finally:
        if folder.is_dir():
            os.chmod(folder, 0o700)
    assert len(saves) == 1 and not target.exists()
    urlopen.assert_not_called()
    head, tail = t("update.error.save_failed", error="\0").split("\0")
    status = dlg._status.text()
    assert status.startswith(head) and status.endswith(tail)
    assert len(status) > len(head) + len(tail), "the OS error is shown"
    assert dlg._update_btn.isEnabled(), "the user can save elsewhere, then try again"
    assert prompts.texts == [t("update.unsaved_prompt")]
    assert win._viewer_has_unsaved() and os.path.isfile(out)
    box.assert_untouched()


def test_a_save_over_the_original_that_is_refused_refuses_the_update(
        win, box, qapp, monkeypatch):
    """The update's Save calls ``_save_pipeline`` itself, not the window's
    gestures' ``_try_save_pipeline``: a PermissionError from the replace
    onto the original (what Windows gives for a held file) is the reason
    shown, and the original and the result are both still there."""
    from app import window
    out = _pipeline_result(win)
    original = win._pipeline_state[id(win._viewer)]["original_path"]
    before = Path(original).read_bytes()
    listing = sorted(os.listdir(os.path.dirname(original)))
    real_replace = os.replace

    def _replace(src, dst, *a, **k):
        if os.path.normcase(os.fspath(dst)) == os.path.normcase(original):
            raise PermissionError(errno.EACCES, "Permission denied", os.fspath(dst))
        return real_replace(src, dst, *a, **k)
    monkeypatch.setattr(os, "replace", _replace)
    shown = []
    monkeypatch.setattr(window, "show_error", lambda parent, exc: shown.append(exc))
    prompts = _Prompts("Save")
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    saves = _save_dialog_returns(monkeypatch, original)
    dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
    assert len(saves) == 1
    urlopen.assert_not_called()
    head, tail = t("update.error.save_failed", error="\0").split("\0")
    status = dlg._status.text()
    assert status.startswith(head) and status.endswith(tail)
    assert shown == []
    assert dlg._update_btn.isEnabled()
    assert Path(original).read_bytes() == before
    assert sorted(os.listdir(os.path.dirname(original))) == listing
    assert win._viewer_has_unsaved() and os.path.isfile(out)
    box.assert_untouched()


def test_update_with_a_result_in_another_tab_downloads_nothing(win, box, qapp, monkeypatch, tmp_path):
    """Save saves the current tab only; the result elsewhere would be lost."""
    from app import window
    out = _pipeline_result(win)
    first = win._viewer
    win._load_and_track(_make_pdf(tmp_path / "other.pdf", "other"))
    qapp.processEvents()
    assert win._viewer is not first and not win._viewer_has_unsaved()
    prompts = _Prompts("Save")
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    saves = _save_dialog_returns(monkeypatch, str(tmp_path / "never.pdf"))
    dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
    urlopen.assert_not_called()
    assert dlg._status.text() == t("update.error.unsaved_other_tab")
    assert prompts.texts == [], "refused before asking"
    assert saves == [] and not (tmp_path / "never.pdf").exists()
    assert win._viewer_has_unsaved(first) and os.path.isfile(out)
    box.assert_untouched()


def test_results_in_this_tab_and_another_are_refused_before_any_save(win, box, qapp, monkeypatch, tmp_path):
    """A2: Save went through _save_pipeline, which saved this tab and then
    deleted the temp dirs of every tool page, the other tab's result with
    them. That tab was left on a deleted file, and saving it raised
    FileNotFoundError (measured)."""
    from app import window
    first_out = _pipeline_result(win, "first tab")
    first = win._viewer
    win._load_and_track(_make_pdf(tmp_path / "other.pdf", "other"))
    qapp.processEvents()
    assert win._viewer is not first
    current_out = _pipeline_result(win, "current tab")
    assert current_out != first_out
    assert win._viewer_has_unsaved(first) and win._viewer_has_unsaved()
    prompts = _Prompts("Save")
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    saves = _save_dialog_returns(monkeypatch, str(tmp_path / "saved.pdf"))
    dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
    assert os.path.isfile(first_out), "the other tab's result was deleted"
    assert os.path.isfile(current_out)
    assert saves == [] and not (tmp_path / "saved.pdf").exists()
    assert prompts.texts == [], "refused before asking"
    assert win._viewer_has_unsaved(first) and win._viewer_has_unsaved()
    urlopen.assert_not_called()
    assert dlg._status.text() == t("update.error.unsaved_other_tab")
    assert dlg._update_btn.isEnabled(), "the user can save each tab, then try again"
    box.assert_untouched()


def _two_tabs_then_save_the_current(win, qapp, monkeypatch, tmp_path):
    """Results in two tabs, then Save in the current one.

    ``_save_pipeline`` deletes the temp dirs of every tool page, so the
    other tab is left on a result whose file is gone (an older defect,
    not fixed here). Returns that tab and its deleted result. POSIX
    only: on Windows that file survived the delete (measured), so the
    other tab still has a result to lose and the refusal is right.
    """
    first_out = _pipeline_result(win, "first tab")
    first = win._viewer
    win._load_and_track(_make_pdf(tmp_path / "other.pdf", "other"))
    qapp.processEvents()
    assert win._viewer is not first
    _pipeline_result(win, "current tab")
    saved = tmp_path / "saved.pdf"
    _save_dialog_returns(monkeypatch, str(saved))
    win._save_pipeline()
    assert saved.is_file() and not win._viewer_has_unsaved()
    assert win._viewer_has_unsaved(first) and not os.path.exists(first_out)
    return first, first_out


@posix_only
def test_a_result_whose_file_is_gone_is_asked_about_and_cancel_downloads_nothing(
        win, box, qapp, monkeypatch, tmp_path):
    """Its file is gone, but its tab still has the document open (pages on
    screen, text extractable): the restart would lose it. Refusing with
    "save the other tab first" sent the user to a save that raised
    FileNotFoundError (measured), so it is asked about with Discard and
    Cancel only."""
    from PySide6.QtWidgets import QMessageBox
    from app import window
    first, first_out = _two_tabs_then_save_the_current(win, qapp, monkeypatch, tmp_path)
    assert "first tab" in first._canvas._doc[0].get_text()
    prompts = _Prompts("Cancel")
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    saves = _save_dialog_returns(monkeypatch, str(tmp_path / "never.pdf"))
    dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
    assert prompts.texts == [t("update.unsaved_gone_prompt")]
    # No Save: that file is gone, saving it would fail.
    assert prompts.buttons == [QMessageBox.StandardButton.Discard
                               | QMessageBox.StandardButton.Cancel]
    assert prompts.defaults == [QMessageBox.StandardButton.Cancel]
    urlopen.assert_not_called()
    assert dlg._status.text() == "", "Cancel is the user's answer, not an error"
    assert dlg._update_btn.isEnabled()
    assert saves == []
    assert win._viewer_has_unsaved(first)
    assert os.path.normcase(first.current_path()) == os.path.normcase(first_out)
    assert "first tab" in first._canvas._doc[0].get_text()
    box.assert_untouched()


@posix_only
def test_discarding_a_result_whose_file_is_gone_updates(win, box, qapp, monkeypatch, tmp_path):
    from app import window
    _two_tabs_then_save_the_current(win, qapp, monkeypatch, tmp_path)
    prompts = _Prompts("Discard")
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
    assert prompts.texts == [t("update.unsaved_gone_prompt")]
    assert dlg._status.text() != t("update.error.unsaved_other_tab")
    urlopen.assert_called()
    assert len(box.exec_calls) == 1
    assert box.exec_calls[0]["image"] == NEW_BINARY


@posix_only
def test_cancel_on_the_gone_result_asks_nothing_about_this_tab(win, box, qapp, monkeypatch, tmp_path):
    """The gone result is asked about first, so that Cancel there leaves
    the result of this tab unsaved and unasked, and nothing written."""
    from app import window
    _two_tabs_then_save_the_current(win, qapp, monkeypatch, tmp_path)
    out = _pipeline_result(win, "current tab again")
    prompts = _Prompts("Cancel")
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    saves = _save_dialog_returns(monkeypatch, str(tmp_path / "never.pdf"))
    _, urlopen = _update_from_window(win, qapp, monkeypatch)
    assert prompts.texts == [t("update.unsaved_gone_prompt")]
    assert saves == [] and not (tmp_path / "never.pdf").exists()
    assert win._viewer_has_unsaved() and os.path.isfile(out)
    urlopen.assert_not_called()
    box.assert_untouched()


@posix_only
def test_discard_the_gone_result_then_save_this_tab_updates(win, box, qapp, monkeypatch, tmp_path):
    """After Save, the gone result is still there, unchanged: it is the
    one the user already agreed to lose, not work left unsaved."""
    from app import window
    _two_tabs_then_save_the_current(win, qapp, monkeypatch, tmp_path)
    _pipeline_result(win, "current tab again")
    prompts = _Prompts("Discard", "Save")
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    saved = tmp_path / "saved again.pdf"
    _save_dialog_returns(monkeypatch, str(saved))
    dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
    assert prompts.texts == [t("update.unsaved_gone_prompt"), t("update.unsaved_prompt")]
    assert saved.is_file() and not win._viewer_has_unsaved()
    assert dlg._status.text() != t("update.error.unsaved_work")
    urlopen.assert_called()
    assert len(box.exec_calls) == 1


@posix_only
def test_a_new_result_in_the_tab_whose_file_was_gone_stops_the_restart(win, box, qapp, monkeypatch, tmp_path):
    """The gone result the user discarded is not the new one made in that
    tab during the download, which is new work."""
    from app import window
    first, _ = _two_tabs_then_save_the_current(win, qapp, monkeypatch, tmp_path)
    monkeypatch.setattr(window.QMessageBox, "question", _Prompts("Discard"))
    late = []

    def new_result_in_the_first_tab():
        win._tab_bar.setCurrentIndex(0)
        qapp.processEvents()
        assert win._viewer is first
        late.append(_pipeline_result(win, "late"))

    dlg, _ = _update_from_window(
        win, qapp, monkeypatch, on_download_done=new_result_in_the_first_tab)
    (out,) = late
    assert not box.exec_calls
    assert box.exe.read_bytes() == OLD_BINARY, "the old binary is back"
    assert dlg._status.text() == t("update.error.unsaved_work")
    assert win._viewer_has_unsaved(first) and os.path.isfile(out)


@posix_only
def test_a_gone_result_and_a_new_one_in_another_tab_are_refused_before_asking(
        win, box, qapp, monkeypatch, tmp_path):
    """The other tab's result can still be saved there, so the refusal
    comes first: a Discard on the gone one would be asked for nothing."""
    from app import window
    first, _ = _two_tabs_then_save_the_current(win, qapp, monkeypatch, tmp_path)
    second = win._viewer
    win._load_and_track(_make_pdf(tmp_path / "third.pdf", "third"))
    qapp.processEvents()
    third = win._viewer
    third_out = _pipeline_result(win, "third tab")
    win._tab_bar.setCurrentIndex(1)
    qapp.processEvents()
    assert win._viewer is second and second not in (first, third)
    assert not win._viewer_has_unsaved()
    prompts = _Prompts("Discard")
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    saves = _save_dialog_returns(monkeypatch, str(tmp_path / "never.pdf"))
    dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
    assert prompts.texts == [], "refused before asking"
    assert dlg._status.text() == t("update.error.unsaved_other_tab")
    assert saves == []
    urlopen.assert_not_called()
    assert win._viewer_has_unsaved(first)
    assert win._viewer_has_unsaved(third) and os.path.isfile(third_out)
    box.assert_untouched()


@posix_only
def test_two_tabs_on_a_gone_result_are_asked_about_once(win, box, qapp, monkeypatch, tmp_path):
    """One prompt for every gone result, so its text must not say there is
    just one (see the catalog test on that text)."""
    from app import window
    first_out = _pipeline_result(win, "first tab")
    first = win._viewer
    win._load_and_track(_make_pdf(tmp_path / "second.pdf", "second"))
    qapp.processEvents()
    second_out = _pipeline_result(win, "second tab")
    second = win._viewer
    win._load_and_track(_make_pdf(tmp_path / "third.pdf", "third"))
    qapp.processEvents()
    _pipeline_result(win, "third tab")
    assert len({first_out, second_out}) == 2
    _save_dialog_returns(monkeypatch, str(tmp_path / "saved.pdf"))
    win._save_pipeline()
    assert not win._viewer_has_unsaved()
    for viewer, out in ((first, first_out), (second, second_out)):
        assert win._viewer_has_unsaved(viewer) and not os.path.exists(out)
    prompts = _Prompts("Discard")
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    _, urlopen = _update_from_window(win, qapp, monkeypatch)
    assert prompts.texts == [t("update.unsaved_gone_prompt")]
    urlopen.assert_called()
    assert len(box.exec_calls) == 1


@posix_only
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root can stat in a folder with mode 0")
def test_a_result_that_cannot_be_stat_ed_is_not_taken_for_gone(win, box, qapp, monkeypatch):
    """Only a missing file is gone. One whose stat fails otherwise (EACCES
    here) is still there to save, and is asked about as such."""
    from app import window
    out = _pipeline_result(win, "kept")
    folder = os.path.dirname(out)
    mode = stat.S_IMODE(os.stat(folder).st_mode)
    os.chmod(folder, 0)
    try:
        with pytest.raises(PermissionError):
            os.stat(out)
        prompts = _Prompts("Cancel")
        monkeypatch.setattr(window.QMessageBox, "question", prompts)
        _, urlopen = _update_from_window(win, qapp, monkeypatch)
    finally:
        os.chmod(folder, mode)
    assert prompts.texts == [t("update.unsaved_prompt")]
    urlopen.assert_not_called()
    assert os.path.isfile(out) and win._viewer_has_unsaved()
    box.assert_untouched()


def _make_pdf_with_a_note(path: Path) -> str:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "with a note")
    page.add_text_annot((100, 100), "a note already in the file")
    data = doc.tobytes()
    doc.close()
    path.write_bytes(data)
    return str(path)


def test_notes_already_in_the_pdf_are_not_edits_to_lose(win, box, qapp, monkeypatch, tmp_path):
    """The editor mirrors a PDF's own notes into ``_pending`` to draw them.
    Counted as edits, merely opening such a file made the update ask about
    discarding editor changes the user never made."""
    from app import window
    editor = win.stack.widget(win._edit_tool_idx())
    editor._load_pdf(_make_pdf_with_a_note(tmp_path / "noted ç.pdf"))
    _pump(qapp, lambda: editor._pending)
    assert [e.get("_existing") for e in editor._pending] == [True]
    assert editor._user_pending == []
    prompts = _Prompts()
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    _update_from_window(win, qapp, monkeypatch)
    assert prompts.texts == []
    assert len(box.exec_calls) == 1


def test_update_after_a_successful_save_restarts(win, box, qapp, monkeypatch, tmp_path):
    from app import window
    _pipeline_result(win, "keep me")
    monkeypatch.setattr(window.QMessageBox, "question", _Prompts("Save"))
    saved = tmp_path / "saved.pdf"
    _save_dialog_returns(monkeypatch, str(saved))
    _update_from_window(win, qapp, monkeypatch)
    assert saved.is_file()
    assert len(box.exec_calls) == 1
    assert box.exec_calls[0]["image"] == NEW_BINARY


def test_a_result_ready_during_the_download_stops_the_restart(win, box, qapp, monkeypatch):
    """Measured: ready at 2.5 s, execve at 8.6 s, and no question asked."""
    from app import window
    monkeypatch.setattr(window.QMessageBox, "question", _Prompts())
    late = []
    dlg, _ = _update_from_window(
        win, qapp, monkeypatch,
        on_download_done=lambda: late.append(_pipeline_result(win, "late")))
    (out,) = late
    assert not box.exec_calls
    assert box.exe.read_bytes() == OLD_BINARY, "the old binary is back"
    assert not box.backups()
    assert dlg._status.text() == t("update.error.unsaved_work")
    assert win._viewer_has_unsaved() and os.path.isfile(out)


def test_a_new_result_written_over_a_discarded_one_stops_the_restart(win, box, qapp, monkeypatch):
    """Discard covered the result the user saw, not the next one, which
    can land at the very same path."""
    from app import window
    out = _pipeline_result(win, "seen and discarded")
    monkeypatch.setattr(window.QMessageBox, "question", _Prompts("Discard"))
    dlg, _ = _update_from_window(
        win, qapp, monkeypatch,
        on_download_done=lambda: _pipeline_result(win, "a newer and longer result", out=out))
    assert not box.exec_calls
    assert box.exe.read_bytes() == OLD_BINARY
    assert dlg._status.text() == t("update.error.unsaved_work")
    assert os.path.isfile(out)


@pytest.mark.parametrize("answers", [(), ("Discard",)], ids=["nothing-to-ask", "result-discarded"])
def test_an_editor_change_made_during_the_download_stops_the_restart(win, box, qapp, monkeypatch, answers):
    """What the user agreed to lose did not include this edit: with nothing
    at risk no question was asked, and Discard was about the result."""
    from app import window
    if answers:
        _pipeline_result(win)
    prompts = _Prompts(*answers)
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    editor = win.stack.widget(win._edit_tool_idx())
    assert not editor._user_pending
    edit = {"type": "note", "page": 0, "text": "made during the download"}
    dlg, _ = _update_from_window(
        win, qapp, monkeypatch, on_download_done=lambda: editor._pending.append(edit))
    assert prompts.texts == [t("update.unsaved_prompt")] * len(answers)
    assert not box.exec_calls
    assert box.exe.read_bytes() == OLD_BINARY, "the old binary is back"
    assert not box.backups()
    assert dlg._status.text() == t("update.error.unsaved_edits")
    assert editor._user_pending == [edit]


def test_a_running_task_stops_the_update_before_the_download(win, box, qapp, monkeypatch):
    from app import window
    monkeypatch.setattr(window.QMessageBox, "question", _Prompts())
    page, release, seen = _start_task(win, qapp)
    try:
        dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
        assert page.has_running_workers()
    finally:
        _finish_task(qapp, page, release)
    urlopen.assert_not_called()
    assert dlg._status.text() == t("update.error.task_running")
    assert "cancelled" not in seen and seen["done"] == "done"
    box.assert_untouched()


def test_a_task_running_at_restart_time_is_not_cancelled(win, box, qapp, monkeypatch):
    """Draining would cancel it in silence; the update gives way instead."""
    from app import window
    monkeypatch.setattr(window.QMessageBox, "question", _Prompts())
    started = []
    try:
        dlg, _ = _update_from_window(
            win, qapp, monkeypatch,
            on_download_done=lambda: started.append(_start_task(win, qapp)))
        (task,) = started
        assert task[0].has_running_workers()
    finally:
        for page, release, _seen in started:
            _finish_task(qapp, page, release)
    assert "cancelled" not in task[2] and task[2]["done"] == "done"
    assert not box.exec_calls
    assert box.exe.read_bytes() == OLD_BINARY
    assert dlg._status.text() == t("update.error.task_running")


def test_a_task_on_a_page_that_is_not_shown_stops_the_update(win, box, qapp, monkeypatch):
    """The user can start a task and move to another tool while it runs."""
    from app import window
    monkeypatch.setattr(window.QMessageBox, "question", _Prompts())
    page, release, seen = _start_task(win, qapp)
    try:
        other = next(i for i in range(win.stack.count()) if win.stack.widget(i) is not page)
        win.stack.setCurrentIndex(other)
        qapp.processEvents()
        assert win.stack.currentWidget() is not page and page.has_running_workers()
        dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
        assert page.has_running_workers()
    finally:
        _finish_task(qapp, page, release)
    urlopen.assert_not_called()
    assert dlg._status.text() == t("update.error.task_running")
    assert "cancelled" not in seen and seen["done"] == "done"
    box.assert_untouched()


def test_a_running_task_is_named_before_a_result_in_another_tab(win, box, qapp, monkeypatch, tmp_path):
    """The task may still write a result anywhere, so it is the first
    thing the user has to wait for; saving the other tab first would not
    be enough."""
    from app import window
    out = _pipeline_result(win, "first tab")
    first = win._viewer
    win._load_and_track(_make_pdf(tmp_path / "other.pdf", "other"))
    qapp.processEvents()
    assert win._viewer is not first and win._viewer_has_unsaved(first)
    prompts = _Prompts()
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    page, release, seen = _start_task(win, qapp)
    try:
        dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
        assert page.has_running_workers()
    finally:
        _finish_task(qapp, page, release)
    urlopen.assert_not_called()
    assert dlg._status.text() == t("update.error.task_running")
    assert prompts.texts == []
    assert "cancelled" not in seen and seen["done"] == "done"
    assert win._viewer_has_unsaved(first) and os.path.isfile(out)
    box.assert_untouched()


# The viewer has the result open. Linux unlinks it anyway; Windows keeps
# it (and has no self-update to clean up after).
@posix_only
def test_discard_removes_the_pipeline_dirs_right_before_execve(win, box, qapp, monkeypatch):
    from app import window
    out = _pipeline_result(win)
    pipe_dir = os.path.dirname(out)
    assert os.path.basename(pipe_dir).startswith("pdfapps_")
    at_execve = []
    real_execve = os.execve

    def execve(path, argv, env):
        at_execve.append(os.path.exists(pipe_dir))
        real_execve(path, argv, env)

    monkeypatch.setattr(os, "execve", execve)
    monkeypatch.setattr(window.QMessageBox, "question", _Prompts("Discard"))
    _update_from_window(win, qapp, monkeypatch)
    assert at_execve == [False]
    assert len(box.exec_calls) == 1


def test_cancel_downloads_nothing_and_keeps_the_result(win, box, qapp, monkeypatch):
    from app import window
    out = _pipeline_result(win)
    monkeypatch.setattr(window.QMessageBox, "question", _Prompts("Cancel"))
    dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
    urlopen.assert_not_called()
    assert dlg._status.text() == "", "Cancel is the user's answer, not an error"
    assert dlg._update_btn.isEnabled()
    assert os.path.isfile(out) and win._viewer_has_unsaved()
    box.assert_untouched()


def test_wait_for_workers_still_cancels_what_it_drains(win, qapp):
    """closeEvent's drain, now fed by the same lookup as has_running_workers."""
    page, release, seen = _start_task(win, qapp)
    try:
        page.wait_for_workers()
        assert seen.get("cancelled") is True
        assert not page.has_running_workers()
    finally:
        _finish_task(qapp, page, release)


@posix_only
def test_a_failed_execve_after_discard_leaves_the_tab_on_a_deleted_file(win, box, qapp, monkeypatch):
    """What the user gets when execve fails after the teardown: the binary
    they had, and the tab still on the result they discarded, whose file
    is gone and which no longer counts as unsaved."""
    from app import window
    out = _pipeline_result(win)
    box.exec_error = OSError(errno.ENOEXEC, "Exec format error")
    monkeypatch.setattr(window.QMessageBox, "question", _Prompts("Discard"))
    dlg, _ = _update_from_window(win, qapp, monkeypatch)
    assert box.exe.read_bytes() == OLD_BINARY
    assert dlg._status.text() == t("update.error.restart_failed", error=box.exec_error)
    assert not os.path.exists(out)
    assert not win._viewer_has_unsaved()
    assert os.path.normcase(win._viewer.current_path()) == os.path.normcase(out)


def test_the_update_asks_with_its_own_text_and_closing_keeps_its_own(win, box, qapp, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from app import window
    _pipeline_result(win)
    win.stack.widget(win._edit_tool_idx())._pending.append(
        {"type": "note", "page": 0, "text": "user note"})
    update_prompts = _Prompts("Discard", "Cancel")
    monkeypatch.setattr(window.QMessageBox, "question", update_prompts)
    _, urlopen = _update_from_window(win, qapp, monkeypatch)
    urlopen.assert_not_called()
    assert update_prompts.texts == [t("update.unsaved_prompt"),
                                    t("update.unsaved_edits_prompt")]

    close_prompts = _Prompts("Cancel")
    monkeypatch.setattr(window.QMessageBox, "question", close_prompts)
    event = QCloseEvent()
    win.closeEvent(event)
    assert not event.isAccepted()
    assert close_prompts.texts == [t("pipeline.unsaved_prompt")]


def test_update_prompts_differ_from_the_close_prompt_in_every_language():
    catalog = json.loads((ROOT / "app" / "translations.json").read_text("utf-8"))
    for lang, entries in catalog.items():
        close = entries["pipeline.unsaved_prompt"]
        assert entries["update.unsaved_prompt"] != close, lang
        assert entries["update.unsaved_edits_prompt"] != close, lang
        assert entries["update.unsaved_gone_prompt"] not in (
            close, entries["update.unsaved_prompt"]), lang


def test_the_gone_prompt_reads_right_for_one_result_or_several():
    """It is asked once for every gone result: with two tabs, a text about
    "a tab" and "it" told the user one result would be lost, not two."""
    catalog = json.loads((ROOT / "app" / "translations.json").read_text("utf-8"))
    text = catalog["en"]["update.unsaved_gone_prompt"]
    assert "At least one tab" in text
    assert not re.search(r"\b(it|its)\b", text), text


# How each language says "at least one" in update.unsaved_gone_prompt.
GONE_PROMPT_AT_LEAST_ONE = {
    "de": "Mindestens ein",
    "en": "At least one",
    "es": "Al menos una",
    "fr": "Au moins un",
    "it": "Almeno una",
    "nl": "Ten minste één",
    "pt": "Pelo menos um",
    "zh": "至少有一个",
}


def test_the_gone_prompt_covers_several_results_in_every_language():
    """With only English checked, a translation could go back to the text
    about "a tab" and "it" and pass (Portuguese did, in a mutation test)."""
    catalog = json.loads((ROOT / "app" / "translations.json").read_text("utf-8"))
    assert sorted(GONE_PROMPT_AT_LEAST_ONE) == sorted(catalog)
    for lang, phrase in GONE_PROMPT_AT_LEAST_ONE.items():
        text = catalog[lang]["update.unsaved_gone_prompt"]
        assert phrase in text, (lang, text)


def test_another_instance_stops_the_update_before_any_prompt(win, box, qapp, monkeypatch):
    from app import window
    out = _pipeline_result(win)
    monkeypatch.setattr(update_apply, "_instances_of", lambda current, **kw: [4242])
    prompts = _Prompts()
    monkeypatch.setattr(window.QMessageBox, "question", prompts)
    dlg, urlopen = _update_from_window(win, qapp, monkeypatch)
    urlopen.assert_not_called()
    assert prompts.texts == []
    assert dlg._status.text() == t("update.error.other_instance")
    assert os.path.isfile(out)
    box.assert_untouched()


# ── platform dispatch in the dialog ──────────────────────────────────────


@pytest.mark.parametrize("path", ["/tmp/PDFApps_update_x.dmg", "/tmp/PDFApps_update_x.tmp"])
def test_dialog_on_macos_opens_the_dmg_and_leaves_the_binary_alone(box, qapp, monkeypatch, path):
    """No frozen check and no extraction on this path, and it is the asset's
    name that decides it: the temp path may end in anything."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    dlg = updater.UpdateDialog(_release(b"dmg", "PDFApps-macOS.dmg", NEW_NAME))
    assert dlg._asset["name"] == "PDFApps-macOS.dmg"
    with patch("subprocess.Popen") as popen, \
         patch("PySide6.QtWidgets.QApplication.instance") as instance:
        dlg._on_finished(path)
    dlg._stop_dots_animation()
    popen.assert_called_once_with(["open", path])
    instance.return_value.quit.assert_called_once()
    assert not dlg._installing
    box.assert_untouched()


def test_dialog_on_windows_runs_the_installer_and_leaves_the_binary_alone(box, qapp, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    dlg = updater.UpdateDialog(_release(b"exe", "PDFAppsSetup.exe", NEW_NAME))
    assert dlg._asset["name"] == "PDFAppsSetup.exe"
    with patch.object(updater, "_apply_update_windows") as run, \
         patch.object(updater.QMessageBox, "information"), \
         patch("PySide6.QtWidgets.QApplication.instance", return_value=MagicMock()):
        dlg._on_finished("C:/temp/PDFApps_update_x.exe")
    dlg._stop_dots_animation()
    run.assert_called_once_with("C:/temp/PDFApps_update_x.exe")
    box.assert_untouched()


# ── the rename ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("names, expected", [
    ([NEW_NAME], NEW_NAME),
    ([OLD_NAME, NEW_NAME], NEW_NAME),
    ([OLD_NAME], None),
    (["PDFApps-macOS.dmg"], None),
    ([], None),
])
def test_linux_looks_for_the_new_name_only(monkeypatch, names, expected):
    monkeypatch.setattr(sys, "platform", "linux")
    found = updater._find_asset({"assets": [{"name": n} for n in names]})
    assert (found["name"] if found else None) == expected


@pytest.mark.parametrize("platform, name", [
    ("win32", "PDFAppsSetup.exe"), ("darwin", "PDFApps-macOS.dmg"),
])
def test_other_platforms_keep_their_names_and_ignore_the_tarball(monkeypatch, platform, name):
    monkeypatch.setattr(sys, "platform", platform)
    assets = [{"name": n} for n in (NEW_NAME, OLD_NAME, name)]
    assert updater._find_asset({"assets": assets})["name"] == name
    assert updater._find_asset({"assets": [{"name": NEW_NAME}]}) is None


# tests.yml fetches this tag for the test below; the test after it keeps
# the two in step.
V1152_TAG = "v1.15.2"


def _v1152_updater():
    """``app/updater.py`` as v1.15.2 shipped it, run against today's app.*."""
    result = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{V1152_TAG}:app/updater.py"],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip(f"tag {V1152_TAG} is not in this clone")
    module = types.ModuleType("_updater_v1152")
    exec(compile(result.stdout, "updater_v1152.py", "exec"), module.__dict__)
    return module


def test_v1152_refuses_the_renamed_asset(box, qapp, monkeypatch):
    """The reason for the rename, run against the code users have today."""
    old = _v1152_updater()
    monkeypatch.setattr(sys, "platform", "linux")
    assert old._find_asset({"assets": [{"name": OLD_NAME}]}) is not None

    dlg = old.UpdateDialog(_release(GOOD_TARBALL, NEW_NAME))
    assert dlg._asset is None
    assert dlg._status.text() == t("update.no_asset")
    assert not dlg._update_btn.isEnabled()
    dlg._update_btn.click()
    box.assert_untouched()


_RUNS_PYTEST = re.compile(r"-m\s+pytest\b")


def _ci_jobs_that_run_pytest() -> dict[str, list[str]]:
    """``{"<workflow>:<job id>": [each step's run block]}`` for every CI
    job with a step that runs the suite."""
    from _workflow_steps import WORKFLOWS, load_workflow
    jobs = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job_id, job in load_workflow(path.name)["jobs"].items():
            runs = [step.get("run", "") for step in job.get("steps", [])]
            if any(_RUNS_PYTEST.search(run) for run in runs):
                jobs[f"{path.name}:{job_id}"] = runs
    return jobs


def test_ci_fetches_the_tag_the_v1152_test_reads():
    """Otherwise a change on one side makes CI skip that test, in silence.

    Every job that runs the suite needs the fetch, before the step that
    runs it: a job without it would skip the test there and stay green.
    """
    ref = f"refs/tags/{V1152_TAG}"
    jobs = _ci_jobs_that_run_pytest()
    # A pattern that stopped matching would find no job and check nothing.
    assert {"tests.yml:pytest", "tests.yml:pytest-windows",
            "tests.yml:pytest-py312"} <= set(jobs), sorted(jobs)
    unfetched = {}
    for name, runs in jobs.items():
        fetches = [i for i, run in enumerate(runs) if f"+{ref}:{ref}" in run]
        first_pytest = next(i for i, run in enumerate(runs) if _RUNS_PYTEST.search(run))
        if not fetches or fetches[0] > first_pytest:
            unfetched[name] = runs
    assert not unfetched, unfetched


def test_no_download_message_is_the_one_those_versions_show():
    catalog = json.loads((ROOT / "app" / "translations.json").read_text("utf-8"))
    assert catalog["en"]["update.no_asset"].startswith("No download available")


# ── structure ────────────────────────────────────────────────────────────


NEW_KEYS = {
    "update.error.not_frozen": set(),
    "update.error.bad_archive": set(),
    "update.error.apply_failed": {"{error}"},
    "update.error.probe_failed": {"{error}"},
    "update.error.restart_failed": {"{error}"},
    "update.error.restore_failed": {"{error}", "{path}"},
    "update.error.probe_wrong_version": {"{error}", "{expected}"},
    "update.error.other_instance": set(),
    "update.error.unsaved_work": set(),
    "update.error.save_failed": {"{error}"},
    "update.error.unsaved_other_tab": set(),
    "update.error.unsaved_edits": set(),
    "update.error.task_running": set(),
    "update.unsaved_prompt": set(),
    "update.unsaved_edits_prompt": set(),
    "update.unsaved_gone_prompt": set(),
}


@pytest.mark.parametrize("key", sorted(NEW_KEYS))
def test_messages_exist_in_all_languages_with_their_placeholders(key):
    catalog = json.loads((ROOT / "app" / "translations.json").read_text("utf-8"))
    assert sorted(catalog) == ["de", "en", "es", "fr", "it", "nl", "pt", "zh"]
    for lang, entries in catalog.items():
        text = entries[key]
        assert text, lang
        for placeholder in NEW_KEYS[key]:
            assert placeholder in text, (lang, placeholder)


def test_apply_module_loads_without_qt(tmp_path):
    script = tmp_path / "probe.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import app.update_apply\n"
        "assert 'PySide6' not in sys.modules, 'Qt was imported'\n"
        "assert 'pymupdf' not in sys.modules, 'PyMuPDF was imported'\n",
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, "-I", str(script)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_language_restart_sweeps_the_bootloader_variables(monkeypatch):
    """_restart_app shares the sweep with the self-update."""
    from PySide6 import QtCore as qtcore
    from app import window

    captured = {}

    class _FakeProcess:
        def setProgram(self, *a): pass
        def setArguments(self, *a): pass
        def setWorkingDirectory(self, *a): pass
        def setProcessEnvironment(self, env): captured["keys"] = set(env.keys())
        def startDetached(self): captured["started"] = True

    _set_bootloader_env(monkeypatch)
    monkeypatch.setattr(qtcore, "QProcess", _FakeProcess)
    monkeypatch.setattr(window, "QApplication", MagicMock())
    stub = types.SimpleNamespace(
        _wait_for_workers_on_all_pages=lambda: None,
        _wipe_all_pdf_passwords=lambda: None,
    )
    window.MainWindow._restart_app(stub)

    assert captured["started"]
    assert not captured["keys"] & set(BOOTLOADER_VARS)
    assert "KEEP_ME" in captured["keys"]
